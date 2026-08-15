# Confectionery Plant Production API — Product Requirements Document

## 1. Introduction

A confectionery plant lives and dies by the calendar. Holiday demand is known months in advance, yet chocolate cannot be cooked, tempered, and deposited into inventory too early without burning shelf life, nor too late without missing the ship window. Between those two cliffs sits everything that makes candy manufacturing hard: cooking and tempering processes that must stay inside tight temperature bands, mold and depositor changeovers that dictate which shapes a line can run, allergen segregation that decides which recipe may follow which washdown, packaging components whose supplier lead times quietly cap the build plan, and a post-season reckoning in which unsold seasonal stock is marked down or reworked into something saleable.

This document specifies the Confectionery Plant Production API, the system of record for that entire cycle. It governs master data for finished goods (own-label, private-label co-pack programs, and assembled gift sets), recipes with their cooking and tempering envelopes, packaging components and the purchase orders that replenish them, mold and line inventories, the swab-and-release changeover protocol, seasonal production windows with their build targets, the scheduling and execution of production, gift-assembly, and rework runs, the lots those runs produce, and the quality holds that adjudicate bloom and process deviations. A central design commitment is that the plant's seasonal position — how much of the build target is confirmed, how much is still pipeline — is always derivable from the data and is recomputed automatically whenever anything underneath it changes.

Section 2 defines the system-wide contracts: authentication, response envelopes, pagination, the logical clock, validation sequencing, concurrency control, and the precision rules every calculation obeys. Section 3 walks the business workflows in narrative form; the numeric thresholds, state gates, and cascade effects are specified there, in the context of the work they guard. Section 4 is the endpoint table and Section 5 the error catalogue; both are deliberately thin indexes back into Sections 2 and 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting operator and `X-User-Role` declares their operational capacity. The system recognizes exactly five roles: `ProductionPlanner`, `PlantManager`, `LineOperator`, `SanitationLead`, and `QualityManager`. A request with missing headers, or whose `X-User-Role` does not name one of these five roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The division of labor follows a segregation-of-duties model. A `ProductionPlanner` plans the season: they own the master data (products, recipes, gift-set bills of material, packaging components, molds, lines, and seasonal windows), issue and receive purchase orders, and schedule or cancel production runs. A `PlantManager` owns season governance: publishing and closing windows, applying post-season markdown, and operating the logical clock. A `LineOperator` runs the floor: starting, holding, resuming, and completing runs, opening changeovers, and raising quality holds. A `SanitationLead` records post-washdown allergen swab results and may never release a line. A `QualityManager` releases changeovers after independent review and dispositions quality holds; quality-hold creation is shared between `QualityManager` and `LineOperator`, and all read endpoints are available to every role.

Identity is opaque for every role. When `X-User-Role` is `ProductionPlanner`, `PlantManager`, `LineOperator`, `SanitationLead`, or `QualityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `swab_recorded_by` on a changeover, as `qa_released_by` on a changeover release, or as `opened_by` and `disposition_by` on a quality hold — but it never compares `X-User-ID` to any entity's `id`. Where segregation of duties is enforced, the comparison is between two recorded operator identifiers, not between an operator and an owning entity.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints accept filter parameters in addition to `limit` and `offset`. Products filter by `product_type`, `brand`, and `packaging_component_id`. Purchase orders filter by `component_id`. Molds filter by `shape_code` and `status`. Production lines filter by `current_mold_id`. The flat changeover list filters by `line_id` and `to_mold_id`. Seasonal windows filter by `status` and `season_code`. Production runs filter by `window_id`, `product_id`, `recipe_id`, `line_id`, `source_lot_id`, `created_lot_id`, and `status`. Lots filter by `product_id`, `run_id`, and `status`. Quality holds filter by `lot_id` and `status`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource.

Any mutation counts toward this rule, whether it originates from a client action or from an internal cascade — including the recomputation of a derived field such as `qty_available` or `coverage_pct`. When an operation touches several resources (a run completion that creates a lot, consumes packaging, and recomputes a window projection, for example), each touched resource independently refreshes its own `updated_at` and increments its own `version`.

Gift-set bill-of-material rows are the one exception to this contract. A gift-component row is immutable after creation — the API offers no update endpoint for it — and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from that resource.

### 2.5. The Plant Logical Clock

Every time-dependent rule in the system reads a server-side logical clock, never the host's wall clock. Lot expiry, purchase-order due dates, window close eligibility, and markdown day counts are all evaluated against this clock, and system-generated timestamps such as `ordered_at`, `received_at`, and `mfg_date` are taken from it. At startup, before any client intervention, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance.

A `PlantManager`-only, test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and the server sets its logical clock to that instant, returning the resulting `current_utc`. This operation mutates no entity; it only moves the clock that temporal rules consult.

### 2.6. Nested Resource Retrieval

Requests that target nested resources are validated left to right along the path. The existence of each path identifier is checked in order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — a changeover addressed under a non-existent line fails on the line before the changeover is ever looked up.

The same discipline applies to foreign keys supplied in request bodies. Identifiers such as `window_id`, `product_id`, `recipe_id`, `line_id`, `source_lot_id`, `lot_id`, `component_id`, `to_mold_id`, `gift_product_id`, `component_product_id`, and `packaging_component_id` must each reference an existing resource; a dangling reference is likewise rejected with `ERR_NOT_FOUND`.

### 2.7. Request Validation Sequencing

When several things are wrong with a request, the failure reported is determined by a fixed validation order, evaluated highest priority first:

1. **Authentication** — the presence and validity of `X-User-ID` and `X-User-Role` (failures: `ERR_UNAUTHENTICATED`, HTTP 401).
2. **Role authorization** — the authenticated role must appear in the endpoint's authorized list (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. **Existence and request shape** — path and body identifiers must resolve (`ERR_NOT_FOUND`, HTTP 404), and the payload must be well-formed: required fields present, enum values legal, and cross-field shape rules satisfied (`ERR_INVALID_REQUEST`, HTTP 400).
4. **State preconditions** — the target resources must be in the states the transition requires (`ERR_INVALID_STATE`, HTTP 409, with the more specific state errors described in §3 such as `ERR_LINE_NOT_AVAILABLE`, `ERR_LOT_NOT_REWORKABLE`, and `ERR_STALE_VERSION`).
5. **Allergen and sanitation safety** — cross-contact prevention, gift-set allergen declaration, swab results, and segregation of duties (for example `ERR_ALLERGEN_WASH_REQUIRED`, `ERR_UNDECLARED_ALLERGEN`, `ERR_SWAB_FAILED`, HTTP 422; `ERR_SEGREGATION_OF_DUTIES`, HTTP 403).
6. **Structural constraints** — mold shape matching, mold availability, line schedule conflicts, window overlap and date order, and gift-graph acyclicity.
7. **Temporal window rules** — schedule containment within the build window, close timing, purchase-order due dates, and rework lot expiry.
8. **Capacity and quota** — packaging availability, rework quantity against source-lot stock, and gift-component pool sufficiency.

An earlier failure masks every later category: a request that fails authentication never reaches a state check, and a run-start request naming a non-existent line reports the 404 before any allergen or mold rule is evaluated. Implementations must evaluate and report in this order.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both name a parent aggregate whose version the client must echo back.

Scheduling a production run requires the non-optional field `expected_window_version`, carrying the `version` of the target seasonal window as the client last observed it. If the window's current `version` no longer matches — because another writer has advanced it since the client last read the window — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), since the run may have been planned against outdated build dates or targets; the client must re-read the window and retry.

Opening a changeover on a line requires the non-optional field `expected_line_version`, carrying the `version` of the production line as the client last observed it. A mismatch with the line's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because a changeover supersedes the line's mold and clearance state and must not be built on an unobserved revision.

No other endpoint accepts a version field; these two are the complete OCC surface.

### 2.9. Precision, Rounding, and Units

All money is handled as integer cents — list prices, lot unit prices, markdown results, and gift-set prices alike. Where a price calculation produces a fractional cent, the value is rounded half-up to a whole cent. Two calculations pin their rounding order explicitly and are described in §3: markdown rounding is applied to each lot's raw discounted price before the price floor, and gift-set pricing rounds each component line before summing.

Window coverage is reported with one decimal place, rounded half-up. Quality-hold defect rates are reported with two decimal places, rounded half-up, and any threshold comparison uses the rounded value, not the unrounded quotient. Packaging requirements use ceiling division — any fractional component rounds up to a whole component — and the standard rework-yield projection rounds down to a whole unit. Component counts, unit quantities, and gift-pool deductions are all whole units. Temperatures are numbers in degrees Celsius, net weights are numbers in grams, and durations such as `shelf_life_days` and `lead_time_days` are whole days.

### 2.10. Allergen Cross-Contact Governance

The allergen vocabulary is fixed: `MILK`, `SOY`, `PEANUT`, `TREE_NUT`, `EGG`, `WHEAT`, and `SESAME`. A recipe declares which of these allergens its mass contains via its `allergens` list — always a subset of that vocabulary, with an empty list meaning the mass is allergen-free. A production line, in turn, carries a `cleared_allergens` set recording the allergens it is currently verified clean for; a freshly registered line is verified for nothing.

Cross-contact prevention is enforced at two points in the workflow. At run start, every allergen declared by the recipe must be present in the line's cleared set — an allergen-free recipe, whose set is empty, satisfies this on any line, while a line cleared for nothing can only run allergen-free recipes. At gift-set bill-of-material authoring, every allergen carried by any recipe of a component product must already be declared by at least one recipe of the gift product, so a kit can never silently introduce an undeclared allergen. Both rules are specified with their triggers and error codes in §3. Sanitation verification itself is split across two roles — the person who records the swab may not be the person who releases the line — and that segregation-of-duties rule is specified with the changeover workflow in §3.3.

### 2.11. Inventory Conservation and Cascading Consistency

Packaging stock is maintained as a small ledger on each component: `qty_on_hand` counts physical components in stock, `qty_reserved` counts components earmarked by not-yet-completed runs, and `qty_available` is always exactly `qty_on_hand` minus `qty_reserved`, recomputed on every mutation of either operand. The invariant that `qty_available` never drops below zero is what makes packaging shortage a creation-time rejection rather than a floor-side surprise. Finished-goods units obey a parallel conservation: units move between a lot's on-hand count, its rework earmark, and its scrapped count through defined events — rework reservation, gift backflush, release trim, and scrap — and never appear or vanish without one.

State changes propagate automatically. When a lot is blocked, depleted, or scrapped, or when its on-hand quantity changes, the seasonal window that contains the lot's producing run has its build projection recomputed without any client request to the window, and the window's `version` increments with each such recompute. The same cascading principle applies wherever one operation's effects cross entity boundaries: every cascade hop refreshes the affected resource's `updated_at` and increments its `version`, per §2.4.

## 3. Business Logic & Workflows

### 3.1. Product, Recipe, and Gift-Set Master Data

Everything the plant sells begins as a Product authored by a `ProductionPlanner`. Each product carries a `sku_code` — a unique sellable-unit code such as TRUFFLE-24, required and unique across all products — plus a display `name`. The `product_type` is one of `STANDARD` for year-round lines, `SEASONAL` for holiday builds that participate in inventory build and post-season markdown, or `GIFT_SET` for assembled kits. The `brand` is either `OWN` for the plant's own label or `PRIVATE_LABEL` for a co-pack customer program; a private-label product must name its co-pack customer in `customer_name` (omitting it is a missing-required-field violation, rejected with `ERR_INVALID_REQUEST`), while for own-label products the field is simply ignored. Commercial and physical facts complete the record: `base_price_cents` is the list price per unit in cents before any markdown and must be greater than zero; `unit_weight_grams` is the net weight per finished unit and must be greater than zero; `shelf_life_days` counts the days from manufacture to expiry, must be greater than zero, and drives every lot's expiry; and `packaging_component_id` names the primary packaging component consumed for each unit produced.

A Recipe is authored against a product through a payload containing its `product_id`, and a product may accumulate several recipes over time (the recipes of a product can be listed as a reverse lookup). Alongside a `name` such as "Truffle mass v2", the recipe fixes four numbers that define its process envelope: the cooking band runs from `cook_temp_min_c` up through `cook_temp_max_c`, and the temperer-exit band from `temper_exit_min_c` up through `temper_exit_max_c`, both bands inclusive of their endpoints. The `shape_code` names the mold or depositor shape the recipe requires — the line's installed mold must carry the same `shape_code` when a run starts. The `allergens` list declares the allergen content of the mass per §2.10 and defaults to an empty list. Finally, `standard_yield_pct` records the planned fraction of input mass that becomes saleable product — greater than zero and at most one — and feeds the standard rework-yield projection described in §3.5.

Gift sets are composed through bill-of-material rows. A `ProductionPlanner` adds a component to a gift set by naming the `gift_product_id`, the `component_product_id`, and the `qty_per_set` — the units of the component product packed into one kit, which must be greater than zero. A component product may itself be a `GIFT_SET`, allowing nested kits, but the resulting graph must stay acyclic: any new edge that would close a cycle, including the degenerate self-loop where `gift_product_id` equals `component_product_id`, is rejected with `ERR_GIFT_CYCLE`. Allergen declaration is enforced at this authoring step too: the union of allergens across the component product's recipes must be a subset of the union of allergens across the gift product's recipes, otherwise the row is rejected with `ERR_UNDECLARED_ALLERGEN`. The row is immutable once created — it carries only `id` and `created_at`, as §2.4 states. The kit's unit price is not entered anywhere; it is derived from this bill of material when a gift-assembly run completes, per §3.6.

### 3.2. Packaging Inventory and Purchase Ordering

Before any seasonal build can be scheduled, the `ProductionPlanner` registers the packaging the plant consumes: films, cartons, trays, and gift boxes. A packaging component is registered with a unique `sku_code`, a `name`, the `units_per_component` describing how many finished units one component packs (a 24-count shipper that packs ten retail units simply records 10; the value must be at least 1), the supplier `lead_time_days` (zero or more), and the opening physical stock `qty_on_hand` (zero or more). After creation, `qty_on_hand` is mutated only by two events: purchase-order receipt and run-completion consumption. The system maintains `qty_reserved` for components earmarked by runs that are planned, in progress, or on hold — zero on a freshly registered component — and exposes `qty_available` as the derived difference, kept in sync on every mutation of either operand per §2.11.

Replenishment is explicit. Ordering more of a component creates a purchase order for the requested `order_qty` — which must be greater than zero — stamped with `ordered_at` from the logical clock and born in `ORDERED` status. Its `due_at` is computed as `ordered_at` plus the component's `lead_time_days`, and `received_at` stays null until the goods land. Receipt is a distinct action by the `ProductionPlanner`: it requires the order to still be `ORDERED` (a second receipt attempt fails with `ERR_INVALID_STATE`), and it requires the logical clock to have reached `due_at` — an earlier receipt attempt is rejected with `ERR_PO_NOT_DUE`. On receipt the order transitions from `ORDERED` to `RECEIVED`, its terminal state, `received_at` is set to the current clock, and the ledger syncs: the component's `qty_on_hand` increases by the order's `order_qty`, `qty_available` is recomputed, and the component's `version` increments. Purchase orders can be listed and filtered by `component_id`, which is also how the orders raised against one component are retrieved.

Packaging lead time is therefore a first-class planning constraint: a component whose stock has run dry cannot serve a run until the clock reaches the order's due date, and §3.5 shows how the reservation math at run scheduling enforces availability up front with `ERR_PACKAGING_SHORTAGE`.

### 3.3. Lines, Molds, and the Changeover Protocol

The shape inventory lives in Mold records, each registered with the `shape_code` it produces and a `cavity_count` of impressions per mold, which must be greater than zero. A mold is born `AVAILABLE` in inventory; once installed it is `INSTALLED`, and a mold may be installed on at most one line at a time. Production lines are registered with just a `name` such as LINE-1; a new line has no mold — its `current_mold_id` is null — has been verified clean for no allergens (`cleared_allergens` is empty), and starts `AVAILABLE`.

Switching a line between products is a formal, three-step protocol with segregated duties, not a flag flip. A `LineOperator` opens a changeover by declaring a `changeover_type`: `SHAPE_ONLY` for a mold swap with no allergen clearance, `FULL` for a deep clean without allergen validation, or `ALLERGEN_WASH` for a validated allergen wash. The request may name a `to_mold_id` to install on release — omitted when the changeover is a wash without a mold swap — but a named mold must be `AVAILABLE` in inventory, and naming one that is already installed elsewhere is rejected with `ERR_MOLD_NOT_AVAILABLE`. An `ALLERGEN_WASH` must declare a non-empty `target_allergens` set — the allergens the line will be cleared for — while the other two types forbid the field entirely; either mismatch is a request-shape violation rejected with `ERR_INVALID_REQUEST`. Two guards protect the line itself: it must be `AVAILABLE` (opening a changeover on a line already in changeover fails with `ERR_LINE_NOT_AVAILABLE`), and the request must carry `expected_line_version` matching the line's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` per §2.8. An accepted changeover is born `PENDING_SWAB`, with `swab_recorded_by`, `swab_passed`, and `qa_released_by` all unset, and the line flips to `CHANGEOVER` — a status in which it cannot start runs — with the line's `version` incrementing.

Once washdown is complete, a `SanitationLead` records the allergen swab result via a payload carrying `swab_passed`. The changeover must still be `PENDING_SWAB` (otherwise `ERR_INVALID_STATE`). A failed swab — `swab_passed` recorded as false — is rejected with `ERR_SWAB_FAILED` and the changeover remains `PENDING_SWAB`, awaiting re-wash and a new swab. A passing swab stamps `swab_recorded_by` with the recorder's `X-User-ID`, stores `swab_passed` as true, advances the changeover to `PENDING_QA`, and increments its `version`.

Release is the exclusive act of a `QualityManager`, and only from `PENDING_QA` (any other state: `ERR_INVALID_STATE`). Segregation of duties is enforced here: the releasing operator's `X-User-ID` must differ from the recorded `swab_recorded_by`, or the release is rejected with `ERR_SEGREGATION_OF_DUTIES`. On release the changeover stamps `qa_released_by`, increments its `version`, and lands in `RELEASED`, its terminal state. The line returns to `AVAILABLE` with its own `version` incremented, and the physical consequences fall out: if a `to_mold_id` was named, the mold previously referenced by the line's `current_mold_id` — if any — returns to `AVAILABLE`, the new mold becomes `INSTALLED`, each affected mold's `version` increments, and the line's `current_mold_id` points at the new mold. Clearance is then set by changeover type: an `ALLERGEN_WASH` release sets the line's `cleared_allergens` to exactly the changeover's `target_allergens`, while a `SHAPE_ONLY` or `FULL` release resets `cleared_allergens` to empty. The practical consequence for §3.6 is direct: only an allergen wash can make a line eligible to run an allergen-bearing recipe, and a mere mold swap strips whatever clearance the line previously held.

### 3.4. Seasonal Windows and Build Projection

A SeasonalWindow frames one season's build. The `ProductionPlanner` creates it with a `season_code` identifying the season (HOLIDAY, EASTER, BASE, and the like), the build corridor from `build_start` — the earliest instant a run in this window may begin — to `build_end` — the latest instant by which production must complete — the ship corridor from `ship_start` to `ship_end`, a `target_units` build target that must be greater than zero, and the `markdown_tiers` that will govern post-season pricing. Each markdown tier pairs a `day_offset_min` (a whole number of days, zero or more) with a `discount_pct` (at least zero and strictly less than one); the tiers must be sorted by ascending `day_offset_min` with no duplicate offsets. Two structural rules guard the window itself. Its dates must be internally ordered — `build_start` no later than `build_end`, `build_end` no later than `ship_start`, and `ship_start` no later than `ship_end` — with any violation rejected as `ERR_WINDOW_DATE_ORDER`. And its ship interval must not intersect the ship interval of any existing window carrying the same `season_code`; the ship interval is closed, both endpoint dates inclusive, so two windows of the same season whose ship periods merely touch on a boundary date already count as overlapping and the new window is rejected with `ERR_WINDOW_OVERLAP`. Overlap is never checked across different season codes. A new window is born `DRAFT`, with its computed fields — `confirmed_build_units`, `projected_build_units`, and `coverage_pct` — all at zero and `shortfall` true.

Publication is a `PlantManager` act: a `DRAFT` window publishes to `PUBLISHED` (from any other state, `ERR_INVALID_STATE`), and only `PUBLISHED` windows accept production runs. Closing is likewise the `PlantManager`'s: a `PUBLISHED` window closes to `CLOSED`, but only once the logical clock's date is strictly after the `ship_end` date — attempting to close on `ship_end` itself or earlier is rejected with `ERR_PREMATURE_CLOSE`. Both transitions increment the window's `version`. Closure is what unlocks the post-season machinery of §3.8.

The window's build projection is always current, because the server recomputes it on every event that could move it: a run created or cancelled against the window, a run completing and landing its lot, any status change of a lot whose run belongs to the window, and any mutation of such a lot's on-hand quantity. The projection has two variants. The confirmed variant — the post-production truth — sets `confirmed_build_units` to the sum of `qty_on_hand` over exactly those lots whose producing run belongs to this window and whose `status` is `ACTIVE`; blocked, depleted, and scrapped lots contribute nothing. The projected variant — the forward-looking answer to "will we hit target if the schedule executes?" — sets `projected_build_units` to the confirmed figure plus the sum of `planned_units` over this window's runs still in the pipeline, namely those in `PLANNED`, `IN_PROGRESS`, or `ON_HOLD`; `COMPLETED` and `CANCELLED` runs contribute nothing to the pipeline term. For any given window state the projected figure is at least the confirmed one, and the two diverge exactly when runs are still in the pipeline. Two derived indicators round out the window: `coverage_pct` is one hundred times `confirmed_build_units` divided by `target_units`, rounded half-up to one decimal place, and `shortfall` is true exactly when `confirmed_build_units` is less than `target_units`. Every recompute increments the window's `version` and refreshes its `updated_at`, per §2.11 — which is precisely why the run-scheduling OCC check of §2.8 exists.

### 3.5. Scheduling Production Runs

With masters, packaging, and a published window in place, the `ProductionPlanner` schedules a run by naming the `window_id`, the `product_id`, the `recipe_id` to execute, the `line_id` to run on, a `run_type` of `STANDARD`, `GIFT_ASSEMBLY`, or `REWORK`, the `planned_units` to produce (greater than zero), and the `scheduled_start` and `scheduled_end` bounding the run's occupancy of the line. Every run create must also carry `expected_window_version` matching the window's current `version`; a mismatch means the plan was built on a window revision the client has not observed and the create is rejected with `ERR_STALE_VERSION` (HTTP 412), per §2.8.

Request shape is checked before any business rule, per the sequencing of §2.7. The recipe must belong to the product — the recipe's own product reference must equal the payload's `product_id`. A `GIFT_ASSEMBLY` run requires a product whose `product_type` is `GIFT_SET`. A `REWORK` run requires both `source_lot_id` and `rework_qty` to be present, and those two fields are forbidden on the other run types. And `scheduled_start` must be strictly earlier than `scheduled_end`. Each of these violations is rejected with `ERR_INVALID_REQUEST`; unknown identifiers instead produce `ERR_NOT_FOUND`, per §2.6.

State and temporal gates follow. The window must be `PUBLISHED` — scheduling into a `DRAFT` or `CLOSED` window fails with `ERR_INVALID_STATE`. The schedule must sit inside the build corridor: `scheduled_start` no earlier than the window's `build_start` and `scheduled_end` no later than its `build_end`, otherwise `ERR_OUTSIDE_PRODUCTION_WINDOW`. The line's book must be free: a run occupies its line from `scheduled_start` up to but not including `scheduled_end`, and the new run is rejected with `ERR_LINE_SCHEDULE_CONFLICT` when that span intersects the occupied span of any other run on the same line in `PLANNED`, `IN_PROGRESS`, or `ON_HOLD` — because the intervals are half-open, two runs that merely touch at an endpoint are allowed.

Scheduling also commits packaging. The requirement is the run's `planned_units` divided by the product's packaging component's `units_per_component`, rounded up to a whole component; if that requirement exceeds the component's `qty_available`, the create is rejected with `ERR_PACKAGING_SHORTAGE`. On acceptance, the component's `qty_reserved` increases by the requirement, the exact reserved amount is recorded on the run as `packaging_reserved_qty`, the component's `version` increments, and `qty_available` is recomputed — to be released on cancellation or consumed on completion, as §3.6 describes.

A `REWORK` run additionally earmarks its source material at creation. The source lot must be reworkable: `ACTIVE`, or `BLOCKED` with a hold sitting in `REWORK_PENDING`; a `DEPLETED` or `SCRAPPED` lot, or a blocked lot without such a hold, is rejected with `ERR_LOT_NOT_REWORKABLE`. The source lot must not be expired — the logical clock must be strictly earlier than the lot's `expiry_date`, otherwise `ERR_LOT_EXPIRED`. And `rework_qty` must not exceed the source lot's `qty_on_hand`, or the create fails with `ERR_REWORK_QTY_EXCEEDS_LOT`. An accepted rework create moves the earmarked units out of free stock: the source lot's `qty_on_hand` decreases by `rework_qty`, its `qty_reserved_rework` increases by the same amount, and the lot's `version` increments. The run's `expected_output_units` is then computed by the standard yield variant — `rework_qty` multiplied by the recipe's `standard_yield_pct`, rounded down to a whole unit — while for non-rework runs `expected_output_units` stays null.

However the run is shaped, it is born `PLANNED` with `output_units` and `created_lot_id` still null, and the window's build projection is recomputed — the pipeline term of `projected_build_units` now includes the new run — with the window's `version` incrementing.

### 3.6. Executing and Completing Runs

The `LineOperator` drives the floor lifecycle. Starting a run moves it from `PLANNED` to `IN_PROGRESS`, but only through three gates beyond the state check itself (a start attempted from any other run state is `ERR_INVALID_STATE`). The line must be `AVAILABLE` — not mid-changeover — or the start fails with `ERR_LINE_NOT_AVAILABLE`. Every allergen in the recipe's `allergens` must be present in the line's `cleared_allergens`, per the cross-contact rule of §2.10, otherwise `ERR_ALLERGEN_WASH_REQUIRED` tells the operator a validated wash stands between this line and this recipe. And the line's installed mold must match the product's form: the mold referenced by the line's `current_mold_id` must carry a `shape_code` equal to the recipe's `shape_code`, with any mismatch — including a line with no mold installed at all — rejected as `ERR_MOLD_SHAPE_MISMATCH`. A successful start refreshes the run's `updated_at` and increments its `version`.

Production is interruptible: an `IN_PROGRESS` run can be paused to `ON_HOLD` (a process upset, a depositing delay) and an `ON_HOLD` run resumed back to `IN_PROGRESS`, each transition requiring the named from-state (otherwise `ERR_INVALID_STATE`) and each incrementing the run's `version`. The hold loop can repeat as often as the floor demands.

Completion is the heaviest transaction in the system. The `LineOperator` completes an `IN_PROGRESS` run — again, any other state is `ERR_INVALID_STATE` — by reporting `actual_cook_temp_c`, `actual_temper_exit_c`, and the counted `output_units`. For a `GIFT_ASSEMBLY` run, one precondition gates the whole completion before anything is written: the first-expiry-first-out pool must cover the build, as detailed below, or the completion is rejected outright with `ERR_INSUFFICIENT_COMPONENT_LOTS`. On success the run lands in `COMPLETED` with `output_units` recorded and `version` incremented, and the consequences cascade outward.

First, packaging is consumed: the component's `qty_reserved` decreases by the run's `packaging_reserved_qty` and its `qty_on_hand` decreases by the same amount, with `qty_available` recomputed — the reservation becomes physical consumption. Second, the lot is born: its `product_id` and `run_id` come from the run, `mfg_date` is stamped from the logical clock, `expiry_date` is `mfg_date` plus the product's `shelf_life_days`, `qty_on_hand` is the reported `output_units` with `qty_reserved_rework` and `qty_scrapped` both at zero, `quality_status` starts `OK`, `status` starts `ACTIVE`, and the run's `created_lot_id` points at the new lot. The lot's `unit_price_cents` is the product's `base_price_cents` captured at this moment — except for gift sets, priced as described below — and may later be overwritten by markdown per §3.8. Third, the process-deviation cascade fires in four hops. Hop one: if `actual_cook_temp_c` fell outside the recipe's cooking band — below `cook_temp_min_c` or above `cook_temp_max_c` — or `actual_temper_exit_c` fell outside the tempering band — below `temper_exit_min_c` or above `temper_exit_max_c` — the lot's `quality_status` becomes `SUSPECT`. Hop two: a `SUSPECT` lot causes the system, unprompted, to open a QualityHold on it with `defect_type` `TEMPER_DEVIATION`, `affected_units` equal to the run's full `output_units`, `opened_by` recorded as 'system', and `status` `OPEN`. Hop three: that hold's creation sets the lot's `status` to `BLOCKED`. Hop four: the lot's blocking re-triggers the window's build projection — the confirmed term now excludes this lot — and bumps the window's `version`, per §3.4.

A completed `GIFT_ASSEMBLY` run additionally backflushes its components. For each component product in the gift set's bill of material, the need is the row's `qty_per_set` multiplied by the reported `output_units`. The eligible pool for a component is exactly the lots of that component product whose `status` is `ACTIVE`, whose `quality_status` is `OK`, whose `expiry_date` is strictly later than the current logical clock, and whose `qty_on_hand` is greater than zero. The pool is walked first-expiry-first-out — ordered by `expiry_date` ascending, ties broken by `created_at` ascending — taking from each lot the smaller of the remaining need and that lot's `qty_on_hand`, and any lot whose `qty_on_hand` reaches zero transitions to `DEPLETED`, each depletion re-triggering its own window's build projection. If the eligible pool for any component cannot cover that component's need, the entire completion is rejected with `ERR_INSUFFICIENT_COMPONENT_LOTS` and no lot anywhere is partially deducted. The gift lot's price is then derived: for each bill-of-material row, the component product's current `base_price_cents` is multiplied by `qty_per_set` and reduced by the kit discount of ten percent, and that per-line amount is rounded half-up to a whole cent; the gift lot's `unit_price_cents` is the sum of those rounded per-line amounts. The rounding order is pinned — round each component line first, then sum — because summing first and rounding once can differ by a cent, and the per-line order is the contract.

A completed `REWORK` run settles its earmark instead. The source lot's `qty_reserved_rework` decreases by the run's `rework_qty`; if the source lot's `qty_on_hand` is zero and its `qty_reserved_rework` is zero after that release, the source lot transitions to `DEPLETED`; and if the source lot carries a hold in `REWORK_PENDING`, that hold transitions to `CLOSED_REWORK`, per §3.7. Note the yield asymmetry between planning and reality: the standard variant computed `expected_output_units` at creation, but the actual variant — the operator's counted `output_units` — is what lands in the new lot's `qty_on_hand` and feeds the window's confirmed build; the two diverge whenever actual yield differs from the recipe standard, and the actual figure always wins.

Every completion, of any run type, ends by recomputing the window's build projection and incrementing the window's `version`.

Cancellation unwinds rather than settles. The `ProductionPlanner` may cancel a run from `PLANNED` or `ON_HOLD` — from any other state, `ERR_INVALID_STATE` — landing it in the terminal `CANCELLED`. Cancellation releases the packaging reservation: the component's `qty_reserved` decreases by `packaging_reserved_qty` and `qty_available` is recomputed, with no consumption of `qty_on_hand`. For a rework run, unit conservation is restored at the source: the source lot's `qty_reserved_rework` decreases by `rework_qty` and its `qty_on_hand` increases by the same amount. And the window's projection is recomputed with the `version` incremented, dropping the cancelled run from the pipeline term.

### 3.7. Quality Holds and Disposition

Quality holds adjudicate everything from a consumer bloom complaint to an auto-detected tempering deviation. A `QualityManager` or a `LineOperator` may open a hold on an `ACTIVE` lot — a lot in any other state cannot take a manual hold — by naming the `lot_id`, a `defect_type` of `BLOOM` for fat or sugar bloom complaints, `TEMPER_DEVIATION` for the auto-created process-deviation case, `FOREIGN_MATERIAL`, or `OTHER`, and the `affected_units` — greater than zero and no more than the lot's `qty_on_hand` at the moment the hold is created. At creation the system snapshots the lot's `qty_on_hand` into `lot_qty_at_open`, which becomes the denominator of the defect rate: `defect_rate_pct` is one hundred times `affected_units` divided by `lot_qty_at_open`, rounded half-up to two decimal places. The creator's `X-User-ID` is recorded as `opened_by` — or the literal 'system' for the auto-created deviation holds of §3.6, whose `affected_units` equal the completing run's full `output_units`. The hold is born `OPEN`, and its creation blocks the lot: the lot moves from `ACTIVE` to `BLOCKED`, and the window projection is recomputed — the confirmed term excludes blocked lots — with the window's `version` incremented.

Disposition belongs to the `QualityManager` alone, who supplies an `action` of `RELEASE`, `SCRAP`, or `REWORK` on a hold that must be `OPEN` (otherwise `ERR_INVALID_STATE`); in all three branches the hold stamps `disposition_by` — null until this moment — with the manager's `X-User-ID` and increments its `version`.

Release returns most of the lot to sale while trimming the defect. A bloom gate stands first: for a `BLOOM` hold, release is only permitted when the rounded `defect_rate_pct` is below 2.00 percent — at 2.00 percent or worse, release is rejected with `ERR_BLOOM_RELEASE_FORBIDDEN` and only scrap or rework remain on the table; holds of any other defect type carry no such threshold. A permitted release moves the hold to `RELEASED` and trims the lot: `qty_on_hand` decreases by the hold's `affected_units` and `qty_scrapped` increases by the same amount, writing the affected units off. The remainder then unblocks — `BLOCKED` back to `ACTIVE` — unless the trim consumed the entire lot, in which case `qty_on_hand` reaching zero sends it to `DEPLETED` instead; either way the window projection is recomputed with its `version` incremented.

Scrap writes the lot off entirely. The lot's full remaining `qty_on_hand` moves into `qty_scrapped`, `qty_on_hand` becomes zero, and the lot lands in `SCRAPPED` — this applies whether the lot was `ACTIVE` or `BLOCKED` under the hold, with the proviso that a blocked lot's rework earmark, if any, must already have been released. The hold becomes `SCRAPPED`, the window projection is recomputed with its `version` incremented, and the write-off may be exactly what flips the window's `shortfall` to true.

Rework keeps the defect lot in play. The hold moves to `REWORK_PENDING`, and the lot remains `BLOCKED` but becomes eligible as the source of a `REWORK` run per the rules of §3.5. When a rework run sourcing that lot later completes, the system — with no client action on the hold — moves the hold from `REWORK_PENDING` to `CLOSED_REWORK`, incrementing its `version`. `RELEASED`, `SCRAPPED`, and `CLOSED_REWORK` are all terminal for the hold.

### 3.8. Season Close-Out: Markdown and Sell-Through Recovery

Once the ship window has passed and the `PlantManager` has closed the season, attention turns to the seasonal stock still on hand. Applying the markdown is a `PlantManager` action against a `CLOSED` window — against a window in any other state it fails with `ERR_INVALID_STATE` — and it reprices exactly the lots whose run belongs to that window, whose `status` is `ACTIVE`, and whose product's `product_type` is `SEASONAL`; blocked, depleted, and scrapped lots are excluded, as are `STANDARD` and `GIFT_SET` products.

The discount is determined by how far past the season the plant is. The response's `days_after_season_end` is the whole-day difference between the logical clock's current UTC date and the window's `ship_end` date — and because closing already required the clock to be strictly past `ship_end`, this count is at least one day by the time markdown can run. Each markdown tier applies once the day count reaches its `day_offset_min`, and the applicable `discount_pct` is the largest among the tiers whose `day_offset_min` has been reached; when no tier qualifies, the discount is zero. For every lot in scope, the raw price is the product's `base_price_cents` reduced by that discount percentage; the raw price is rounded half-up to a whole cent; and the lot's new `unit_price_cents` is the greater of that rounded figure and the price floor of fifty cents — seasonal stock is never priced below the floor, whatever the tier says. Each updated lot's `version` increments. The operation reports back the `updated_lot_count`, the `discount_pct` that was applied, and the `days_after_season_end` the discount was measured from, and it overwrites whatever `unit_price_cents` the lots carried, including any earlier markdown.

Markdown is the financial recovery path; rework is the physical one. Lots that will not sell even at a tier discount can be routed through the rework workflow of §3.5 and §3.7 — earmarked, cooked back in under a recipe's standard yield, and landed as fresh lots whose confirmed units count again toward whatever window their new run belongs to. Between the two, the plant closes the season with every unit either repriced, remade, or written off.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, receipts, dispositions, markdown application, and the clock setter — return `200 OK`, as do all list and fetch endpoints. Error responses follow §2.2 and §2.7. The table below is an index only: request payloads, derived fields, and side effects are specified by the workflow narratives of §3 and the contracts of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a finished-good SKU (own-label, private-label co-pack, or gift set) | ProductionPlanner |
| GET | `/products` | List products with optional filters and envelope pagination | Any |
| GET | `/products/{id}` | Fetch one product | Any |
| GET | `/products/{id}/recipes` | List the recipes of a product | Any |
| GET | `/products/{id}/gift-components` | List gift-component rows where the product participates, as gift set or as component | Any |
| POST | `/recipes` | Create a recipe with cooking/tempering bands, shape, and allergen set | ProductionPlanner |
| POST | `/gift-components` | Add a component product to a gift-set bill of material; enforces allergen subset and acyclicity | ProductionPlanner |
| POST | `/packaging-components` | Register a packaging component with lead time and opening stock | ProductionPlanner |
| GET | `/packaging-components` | List packaging components | Any |
| POST | `/packaging-components/{id}/purchase-orders` | Order more of a packaging component; due date derives from lead time | ProductionPlanner |
| GET | `/purchase-orders` | List purchase orders, optionally filtered by component | Any |
| GET | `/purchase-orders/{id}` | Fetch one purchase order | Any |
| POST | `/purchase-orders/{id}/receive` | Receive a purchase order once the clock reaches its due date; adds stock to the component | ProductionPlanner |
| POST | `/molds` | Register a mold or depositor in shape inventory | ProductionPlanner |
| GET | `/molds` | List molds | Any |
| POST | `/production-lines` | Register a production or depositor line | ProductionPlanner |
| GET | `/production-lines` | List production lines | Any |
| GET | `/production-lines/{id}` | Fetch one production line | Any |
| POST | `/production-lines/{id}/changeovers` | Open a mold/allergen changeover on a line (OCC-guarded on the line's version); the line enters changeover | LineOperator |
| GET | `/production-lines/{id}/changeovers` | List changeovers of a line | Any |
| GET | `/changeovers` | List changeovers across lines | Any |
| GET | `/changeovers/{id}` | Fetch one changeover | Any |
| POST | `/changeovers/{id}/swab` | Record the post-wash allergen swab result | SanitationLead |
| POST | `/changeovers/{id}/release` | Release the line after independent QA review; installs the mold and sets allergen clearance | QualityManager |
| POST | `/seasonal-windows` | Create a seasonal production window in draft | ProductionPlanner |
| GET | `/seasonal-windows` | List seasonal windows | Any |
| GET | `/seasonal-windows/{id}` | Fetch one window with its computed build-projection fields | Any |
| POST | `/seasonal-windows/{id}/publish` | Publish a draft window so runs can be scheduled against it | PlantManager |
| POST | `/seasonal-windows/{id}/close` | Close a published window once the clock is strictly past the ship end | PlantManager |
| POST | `/seasonal-windows/{id}/apply-markdown` | Apply the current markdown tier price to all active lots of seasonal products built in this window | PlantManager |
| POST | `/production-runs` | Schedule a production, gift-assembly, or rework run in a published window (OCC-guarded on the window's version); reserves packaging and rework units | ProductionPlanner |
| GET | `/production-runs` | List production runs | Any |
| GET | `/production-runs/{id}` | Fetch one production run | Any |
| POST | `/production-runs/{id}/start` | Start a planned run; gates on line availability, allergen clearance, and mold shape | LineOperator |
| POST | `/production-runs/{id}/hold` | Pause an in-progress run | LineOperator |
| POST | `/production-runs/{id}/resume` | Resume a held run | LineOperator |
| POST | `/production-runs/{id}/complete` | Complete an in-progress run with actual process temperatures and output; creates the lot and fires the deviation, gift, and rework cascades | LineOperator |
| POST | `/production-runs/{id}/cancel` | Cancel a planned or held run; releases the packaging reservation and any rework earmark | ProductionPlanner |
| GET | `/lots` | List lots | Any |
| GET | `/lots/{id}` | Fetch one lot | Any |
| POST | `/quality-holds` | Open a quality hold on an active lot; blocks the lot | QualityManager, LineOperator |
| GET | `/quality-holds` | List quality holds | Any |
| GET | `/quality-holds/{id}` | Fetch one quality hold | Any |
| POST | `/quality-holds/{id}/disposition` | Disposition an open hold: release with trim, scrap the lot, or offer it to rework | QualityManager |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical clock | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in §2 and §3 alongside the workflow that raises it; this table is the index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LINE_NOT_AVAILABLE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SWAB_FAILED` | 422 |
| `ERR_ALLERGEN_WASH_REQUIRED` | 422 |
| `ERR_UNDECLARED_ALLERGEN` | 422 |
| `ERR_MOLD_SHAPE_MISMATCH` | 422 |
| `ERR_MOLD_NOT_AVAILABLE` | 409 |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_GIFT_CYCLE` | 422 |
| `ERR_WINDOW_DATE_ORDER` | 422 |
| `ERR_OUTSIDE_PRODUCTION_WINDOW` | 422 |
| `ERR_PREMATURE_CLOSE` | 422 |
| `ERR_PO_NOT_DUE` | 422 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_PACKAGING_SHORTAGE` | 422 |
| `ERR_INSUFFICIENT_COMPONENT_LOTS` | 422 |
| `ERR_REWORK_QTY_EXCEEDS_LOT` | 422 |
| `ERR_BLOOM_RELEASE_FORBIDDEN` | 422 |
| `ERR_LOT_NOT_REWORKABLE` | 409 |
