# Window Fenestration Manufacturing API — Product Requirements Document

## 1. Introduction

Made-to-order window manufacturing runs on a chain of commitments: a dealer configures a unit down to its grid pattern and hardware finish, the plant prices that configuration, promises a date, proves the insulating glass meets the energy code of the destination state, fabricates it, ships it on a rack, and then stands behind the product for years afterward. This document specifies the Window Fenestration Manufacturing API, the system of record for that chain in a plant operating a dealer channel. It is written for the engineers who will build the service; every behavior described here is contractual.

The API covers catalog administration (catalog series and glass packages), dealer order capture with per-line configuration and volume-discount pricing, NFRC-style energy labeling evaluated against per-state code rules, production wave planning with capacity and lead-time gating, insulating-glass unit fabrication with argon-fill quality control and an automated remake cycle, shipping rack reservation and loading, and post-delivery warranty adjudication with service-part fulfillment. Every order advances along two independent dimensions — a production status and a compliance status — and the server maintains a logical clock rather than wall-clock time, so that delivery stamps, warranty windows, and code-rule effective dates are deterministic. All resources are mounted under `/fenestration`.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` specifies their operational capacity. The system recognizes six roles, spelled exactly as follows: `DealerRep`, `PlantEngineer`, `ProductionLead`, `ShippingCoordinator`, `WarrantyAdjuster`, and `PlantManager`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`. Once authenticated, each operation is restricted to designated roles; an attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_ROLE`. The `PlantManager` is the plant administrator: its permission set is a superset of every operational role, and it alone controls dealer credit, the dealer registry, and the test-driving clock.

Role identity works in two ways. When `X-User-Role` is `DealerRep`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's dealer chain to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. Creating an order under this role therefore requires the payload's `dealer_id` to equal `X-User-ID`, and dealer-scoped actions such as confirming delivery, answering an information request, or appealing a denial are limited to the dealer's own orders and claims. When `X-User-Role` is `PlantEngineer`, `ProductionLead`, `ShippingCoordinator`, `WarrantyAdjuster`, or `PlantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field — specifically the resource the path addresses: wave operations (open, assign, unassign, lock, release, close, cancel) return the `ProductionWave` even though the payload names an order, line creation and reconfiguration return the `OrderLine`, reservation load/ship/cancel return the `RackReservation`, claim adjudication returns the `WarrantyClaim`, and the clock operation returns an object carrying `current_utc`.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Both parameters must be non-negative integers: a non-integer value, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — Dealer, CatalogSeries, GlassPackage, EnergyCodeRule, WindowOrder, OrderLine, EnergyLabel, IGUnit, ProductionWave, ShippingRack, RackReservation, WarrantyClaim, and ServicePartShipment — carries a uniform set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-08-01T00:00:00.000Z`) recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp recording the last modification; it refreshes on every change to the resource's properties.
- **`version` (integer):** A system-managed integer that starts at 1 when the resource is created and increments by one with every modification, including mutations caused by cascading side effects and recomputation of derived fields.

This convention provides a consistent audit trail and unique addressability for every entity, and the `version` field is the basis of the optimistic concurrency rules in §2.8.

### 2.5. The Logical Clock

The server runs on a logical clock, never on wall-clock time. At server start the clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time for any computation. A `PlantManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; the supplied instant is not constrained relative to the current reading, so the clock may be moved backward as well as forward. The logical clock governs every time-sensitive rule in this document: it stamps every resource's `created_at` and `updated_at`, supplies the `api_request_timestamp` in every response's `meta`, stamps `delivered_at` at delivery confirmation, it bounds a warranty claim's `failure_date`, and it anchors every date comparison described in §3.

### 2.6. Nested Resource Retrieval

The API enforces strict, hierarchical, left-to-right validation for every request that targets nested resources. When a path contains multiple identifiers (for example, `/fenestration/orders/{orderId}/lines/{lineId}`), the server validates the existence of each identifier in path order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Resources referenced in the request body — a `series_id`, a `glass_package_id`, an `order_id` — are likewise validated for existence before business rules run. A request naming a line under a non-existent order therefore fails on the order before the line is ever examined.

### 2.7. Money, Measurements, and Rounding

All monetary values in this API are integer counts of cents: catalog rates, adders, line totals, order totals, discounts, remedy values, and shipping charges are all whole cents. Whenever a monetary computation produces a fraction — a prorated warranty remedy, a volume discount, a line total — the result is rounded half-up to whole cents, exactly once, at the point the field is stored.

Areas and thermal ratings follow their own fixed precision. A line's glazing area and a wave's allocated glass total are carried at two decimal places, rounded half-up. NFRC ratings (`u_factor`, `shgc`, and the certified U-factor computed at quality control) are carried at two decimal places, rounded half-up. Argon fill percentages, coverage percentages, capacities, lead times, and unit indices are integers. Timestamps and dates exchanged with the API are ISO 8601 values.

### 2.8. Optimistic Concurrency Control

Two write endpoints guard their parent aggregate with optimistic concurrency control, and both make the version token a required input — it is never optional on these endpoints.

Assigning an order to a production wave requires the request to carry `expected_wave_version`, the `version` of the `ProductionWave` the client last observed. If the wave's current `version` does not match — because another assignment, unassignment, breakage cascade, or cancellation has advanced it since the client read the wave — the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412), even when the remaining capacity would legitimately admit the order: the client's view of the wave is stale, and proceeding would overwrite changes the client never saw.

Reconfiguring an order line while the order is in `DRAFT` requires the request to carry `expected_order_version`, the `version` of the parent `WindowOrder` the client last observed. A mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), even though the edit itself would be a legitimate `DRAFT`-state mutation, because line edits reprice the order and advance its version. Endpoints not named in this section do not accept a version field at all.

### 2.9. Cascades, Bubble-Ups, and Derived State

State in this plant is rarely local. The server propagates changes in two directions and does so immediately, within the same request. Cascades travel downward: confirming an order confirms its lines; releasing a wave advances its orders and lines and creates their insulating glass units; cancelling an order cancels its lines and scraps their unfinished units. Bubble-ups travel upward: when the last unfinished unit of a line passes quality control, the line completes, its energy label certifies, and — if it was the order's final incomplete line — the order completes; when the last line of an order ships, the order ships; when a service part is delivered, its parent claim is fulfilled.

Two pieces of state are fully derived rather than set by clients. A shipping rack's `status` flips between `AVAILABLE` and `BOOKED` purely as a function of whether any active reservation exists, and a production wave can reopen on its own when its allocation falls below a threshold (§3.4). Every mutation described above — whether client-invoked, cascaded, or derived — refreshes the mutated resource's `updated_at` and increments its `version`.

A WindowOrder carries two independent status dimensions that evolve in parallel: `production_status` tracks the physical lifecycle from `DRAFT` to `DELIVERED`, while `compliance_status` tracks the energy-compliance lifecycle from `PENDING` through `PROVISIONALLY_COMPLIANT` to `CERTIFIED`. Neither dimension blocks the other except where §3 explicitly says so.

### 2.10. The Request Validation Pipeline

Every request is evaluated against a fixed pipeline of validation stages. When several violations are present at once, the error returned is the one from the earliest stage in this order — later checks never mask earlier ones:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is recognized; failures return `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the role is permitted on this endpoint; failures return `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Ownership** — on `DealerRep`-accessible order, line, and claim endpoints, `X-User-ID` must equal the `dealer_id` of the target order or claim chain; failures return `ERR_OWNERSHIP_MISMATCH` (HTTP 403). Ownership is enforced exactly where an endpoint is anchored to a specific order, order line, or claim: single reads of an order, line, or claim, the per-parent nested lists (an order's lines, a line's energy label, a line's IG units, an order's claims, a claim's service-part shipments), and the dealer-scoped mutations. Direct-by-id reads of `EnergyLabel`, `IGUnit`, and `ServicePartShipment`, and all plant-wide collection lists (`/fenestration/orders`, `/order-lines`, `/energy-labels`, `/ig-units`, `/warranty-claims`, `/service-part-shipments`, `/rack-reservations`), carry no ownership filter — any authenticated role sees the full collection.
4. **Existence** — path- and body-referenced resources exist, validated left-to-right; failures return `ERR_NOT_FOUND` (HTTP 404).
5. **Request shape** — required fields are present, types are valid, enum values are members of their enumeration, `width_in` and `height_in` are greater than zero, `quantity` is at least 1, a `CIRCLE` line has `width_in` equal to `height_in`, and a `failure_date` is not later than the current logical time; failures return `ERR_INVALID_REQUEST` (HTTP 400).
6. **Optimistic concurrency** — on the two endpoints of §2.8, the expected parent version matches the parent's current `version`; failures return `ERR_STALE_VERSION` (HTTP 412).
7. **State preconditions** — the entity is in a state from which the requested transition is defined; failures return `ERR_INVALID_STATE` or the specific state errors `ERR_ORDER_NOT_DRAFT`, `ERR_ORDER_NOT_CONFIRMED`, `ERR_ORDER_NOT_SHIPPABLE`, `ERR_ORDER_NOT_DELIVERED`, `ERR_WAVE_NOT_OPEN`, `ERR_WAVE_HAS_ASSIGNMENTS`, `ERR_IG_NOT_READY_FOR_QC`, `ERR_LINE_NOT_ON_GLASS_HOLD`, or `ERR_CLAIM_NOT_REVIEWABLE` (HTTP 409). Any transition attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE` unless a more specific state error applies.
8. **Regulatory** — at order confirm, every line's energy label compliance must be `PASS` or `UNEVALUATED`; failures return `ERR_ENERGY_CODE_VIOLATION` (HTTP 409).
9. **Temporal** — a wave date must satisfy the lead-time gate (`ERR_WAVE_BEFORE_LEAD_TIME`), a rack reservation window must not collide with an active reservation (`ERR_RACK_OCCUPANCY_CONFLICT`), and a claim's `failure_date` must be on or after the order's `delivered_at` (this last check returns `ERR_INVALID_REQUEST`, HTTP 400).
10. **Business constraints** — the referenced series is not `DISCONTINUED` (`ERR_SERIES_DISCONTINUED`), the line's size stays within the series cap (`ERR_SIZE_EXCEEDS_SERIES_LIMIT`, HTTP 422), a remake chain stays within its limit (`ERR_REMAKE_LIMIT_EXCEEDED`), no duplicate active claim exists for the same line and component (`ERR_DUPLICATE_ACTIVE_CLAIM`), and energy-code rule windows for a state do not overlap (`ERR_ENERGY_RULE_WINDOW_OVERLAP`).
11. **Capacity and fiscal** — the dealer is not on credit hold (`ERR_DEALER_CREDIT_HOLD`), wave unit and glass capacities hold (`ERR_WAVE_CAPACITY_EXCEEDED`, `ERR_WAVE_GLASS_CAPACITY_EXCEEDED`), rack slot capacity holds (`ERR_RACK_CAPACITY_EXCEEDED`), and a claim's coverage is positive at approval (`ERR_WARRANTY_EXPIRED`).

Because of this ordering, an order that would fail both the energy-compliance gate and the dealer credit gate at confirm is rejected with `ERR_ENERGY_CODE_VIOLATION`, not `ERR_DEALER_CREDIT_HOLD`; and a stale wave version surfaces as `ERR_STALE_VERSION` before any state or capacity check on the wave itself is reported.

## 3. Business Logic & Workflows

### 3.1. Dealer Accounts and Catalog Foundations

A `PlantManager` onboards a dealer by supplying a `name` and a default `ship_to_state_code` — the two-letter US state code shipments default to; the code is stored as supplied, with no format validation beyond being a string. Every dealer begins life with `credit_status` set to `ACTIVE`. Credit control is a cyclic mini-lifecycle: the `PlantManager` may place a dealer on `CREDIT_HOLD` and later release it back to `ACTIVE`. Each transition is defined only from its source state — placing a hold on a dealer that is not currently `ACTIVE`, or releasing a dealer that is not on `CREDIT_HOLD`, is rejected with `ERR_INVALID_STATE`. While a dealer sits on `CREDIT_HOLD`, confirming any of its orders is rejected with `ERR_DEALER_CREDIT_HOLD`; nothing else about the dealer's records changes.

The product catalog belongs to the `PlantEngineer` (and, as always, the `PlantManager`). A **CatalogSeries** captures one product line: a `series_code` such as V200 (a plain identifier — the server does not enforce uniqueness, and duplicate codes are accepted), a `frame_material` of `VINYL`, `WOOD`, `ALUMINUM_CLAD`, or `FIBERGLASS`, and the commercial terms `base_rate_cents_per_ui` (the integer-cent base price per united inch, where a unit's united inches are its width plus its height) and `min_billable_sqft` (the smallest glazing area the plant will bill per unit, however small the window). Engineering constraints come along too: `max_united_inches` caps the size the series can be built in, and `special_shape_upcharge_pct` declares the percentage surcharge applied to the base price of any non-`RECTANGLE` shape — a value of 40 means a forty percent uplift. Delivery commitments are split by geometry: `lead_time_standard_days` governs `RECTANGLE` lines, while `lead_time_special_shape_days` governs `ARCH`, `CIRCLE`, and `TRAPEZOID` lines. Finally, `frame_warranty_years` states how long the frame component is warranted. A series starts `ACTIVE`; discontinuing it moves it to `DISCONTINUED`, after which creating or reconfiguring a line with that series is rejected with `ERR_SERIES_DISCONTINUED`. Lines already written against the series are unaffected.

A **GlassPackage** describes the insulating glass build: a `code` (again not uniqueness-checked — duplicates are accepted), a `pane_count` of 2 or 3, a `spacer_type` of `ALUMINUM` or `WARM_EDGE`, the argon fill targets `argon_target_pct` (the fill the line aims for) and `argon_min_pct` (the minimum acceptable fill — the quality-control boundary is inclusive, so a measured fill exactly equal to the minimum passes), the catalog NFRC ratings `catalog_u_factor` and `catalog_shgc`, a `price_per_sqft_cents` surcharge applied per billable square foot per unit, and `ig_warranty_years` for the insulating-glass seal.

### 3.2. Configuring and Pricing an Order

A `DealerRep` opens an order for their own dealership — or a `PlantManager` on any dealer's behalf — by supplying the `dealer_id`, the `order_date`, and optionally a `ship_to_state_code`; when the destination is omitted it defaults to the dealer's own `ship_to_state_code`. The order date is not ceremonial: it selects which energy-code rule applies (§3.3) and anchors the lead-time gate at wave assignment (§3.4). A new order starts with `production_status` `DRAFT` and `compliance_status` `PENDING`; its `wave_id` and `delivered_at` are null, its money fields `subtotal_cents`, `discount_cents`, and `total_price_cents` are zero, and `promised_date` stays null until the first line exists. The orders list can be filtered by `dealer_id`, `wave_id`, or `production_status`.

Lines are added only while the order is `DRAFT` — adding or editing a line on a confirmed-or-later order is rejected with `ERR_ORDER_NOT_DRAFT`. Each line carries the full unit configuration: `series_id` and `glass_package_id` select the catalog entries, `shape` is one of `RECTANGLE`, `ARCH`, `CIRCLE`, or `TRAPEZOID`, `width_in` and `height_in` give the unit dimensions in inches (any positive number is accepted — fractional inches are allowed; both must be greater than zero, and a `CIRCLE` line requires `width_in` equal to `height_in`), `quantity` is the number of identical units and must be an integer of at least 1, `grid_style` is `NONE`, `COLONIAL`, `PRAIRIE`, or `DIAMOND`, and `hardware_finish` is `STANDARD`, `BRUSHED_NICKEL`, or `OIL_RUBBED_BRONZE`. The series must still be `ACTIVE` (a discontinued series yields `ERR_SERIES_DISCONTINUED`), and the configured size must fit the series: a line whose united inches exceed the series' `max_united_inches` is rejected with `ERR_SIZE_EXCEEDS_SERIES_LIMIT` (HTTP 422) — a line exactly at the cap fits. Every line creation automatically creates the line's `EnergyLabel` in `PROVISIONAL` form, prices the line, recomputes the order totals and `promised_date`, and increments the order's `version`. Lines can be browsed per order, or across the plant filtered by `order_id`, `series_id`, `glass_package_id`, or `rack_id`.

Pricing a line follows a fixed sequence. The line's `united_inches` is the sum of `width_in` and `height_in`. Its per-unit `glazing_sqft` is the width times the height divided by 144, scaled by the shape's area factor — 1.0 for `RECTANGLE`, 0.85 for `ARCH`, 0.785 for `CIRCLE`, and 0.9 for `TRAPEZOID` — rounded half-up to two decimal places. The per-unit `billable_sqft` is the greater of that glazing area and the series' `min_billable_sqft`, so a tiny unit still bills the series minimum. The shape multiplier is 1 for a `RECTANGLE`; for any other shape it is 1 plus the series' `special_shape_upcharge_pct` divided by 100. The raw per-unit price is then the `united_inches` multiplied by the series' `base_rate_cents_per_ui` multiplied by the shape multiplier, plus the `billable_sqft` multiplied by the glass package's `price_per_sqft_cents`, plus a grid adder of 0 cents for `NONE`, 4,000 cents for `COLONIAL`, 5,500 cents for `PRAIRIE`, or 7,000 cents for `DIAMOND`, plus a hardware adder of 0 cents for `STANDARD`, 2,500 cents for `BRUSHED_NICKEL`, or 3,200 cents for `OIL_RUBBED_BRONZE`. The `line_total_cents` is that raw per-unit price multiplied by `quantity`, rounded half-up to whole cents.

Each line's `lead_time_days` is the series' `lead_time_special_shape_days` when the shape is anything other than `RECTANGLE`, and `lead_time_standard_days` otherwise. The order's `promised_date` is its `order_date` plus the largest `lead_time_days` among its non-`CANCELLED` lines, recomputed whenever a line is added, edited, or cancelled.

Order totals obey a pinned rounding order. The `subtotal_cents` is the sum of the post-rounding `line_total_cents` of all non-`CANCELLED` lines — each line is rounded first, and no rounding ever happens after the summation. Discounting is then evaluated in a fixed order: compute the pre-discount subtotal, select the tier from that pre-discount figure only, then apply it. A subtotal of at least 500,000 cents ($5,000) earns 5 percent; at least 2,000,000 cents ($20,000) earns 8 percent; at least 5,000,000 cents ($50,000) earns 12 percent; below the first tier there is no discount. The `discount_cents` is the subtotal multiplied by the selected percentage, rounded half-up to whole cents, and `total_price_cents` is the subtotal minus the discount. The discounted total never feeds back into tier selection. These figures recompute on every line change while the order is a draft.

While the order remains `DRAFT`, a line can be reconfigured: the edit carries `expected_order_version` (see §2.8) plus any of `series_id`, `glass_package_id`, `shape`, `width_in`, `height_in`, `quantity`, `grid_style`, or `hardware_finish`, reprices the line under the same rules, re-evaluates its energy label back on the `PROVISIONAL` basis, recomputes the order totals, and increments the order's `version`.

Confirmation is the order's point of no return. A `DealerRep` confirming their own order — or a `PlantManager` — triggers three gates, evaluated in pipeline order: every line's energy label must show compliance `PASS` or `UNEVALUATED` (a single `FAIL` rejects the confirm with `ERR_ENERGY_CODE_VIOLATION`), and the dealer's `credit_status` must be `ACTIVE` (`ERR_DEALER_CREDIT_HOLD`). An order with no non-`CANCELLED` lines cannot be confirmed at all (`ERR_ORDER_HAS_NO_LINES`). On success the server reprices every line one final time, freezes `subtotal_cents`, `discount_cents`, and `total_price_cents`, moves `compliance_status` to `PROVISIONALLY_COMPLIANT`, cascades each line from `PENDING` to `CONFIRMED`, and increments the order's `version`.

### 3.3. Energy Code Rules and the Line's Energy Label

Energy compliance is per-state and per-order-date. A `PlantEngineer` records an **EnergyCodeRule** with a `state_code`, the maximum compliant ratings `max_u_factor` and `max_shgc`, and an effective window from `effective_from` to `effective_to`; leaving `effective_to` unset makes the rule open-ended. No ordering constraint between `effective_from` and `effective_to` is enforced — a rule whose `effective_to` precedes its `effective_from` is accepted as supplied (such a window simply contains no instant). Windows are half-open — a rule applies from its `effective_from` (inclusive) up to but not including its `effective_to`. Two rules for the same state may not have overlapping windows; an overlapping creation is rejected with `ERR_ENERGY_RULE_WINDOW_OVERLAP`. Adjacency is allowed: one rule's `effective_to` may coincide with the next rule's `effective_from`.

Every order line owns exactly one **EnergyLabel**, created automatically with the line, and fetching the label through the line returns an array of zero or one entries. Labels may also be listed across the plant filtered by `order_line_id` or `applied_energy_code_rule_id`. The label carries both a `basis` and a `status`, each `PROVISIONAL` or `CERTIFIED`, plus the current ratings `u_factor` and `shgc`, the `applied_energy_code_rule_id` of the rule selected for it (null when no rule applies), and a `compliance` verdict that is evaluated immediately at line creation — `UNEVALUATED` when no rule applies, otherwise `PASS` or `FAIL` per the comparison below (it does not wait for order confirmation).

Rule selection works as follows. The label's rule is the `EnergyCodeRule` whose `state_code` equals the order's `ship_to_state_code` and whose half-open window contains the order's `order_date` — `effective_from` on or before the order date, and `effective_to` strictly after it when set. When no rule qualifies, `applied_energy_code_rule_id` stays null and `compliance` remains `UNEVALUATED`, which the confirm gate treats as passing. When a rule qualifies, `compliance` is `PASS` when the label's current `u_factor` is no greater than the rule's `max_u_factor` and its `shgc` is no greater than the rule's `max_shgc` — both boundaries inclusive — and `FAIL` otherwise.

While a line is being configured, its label is provisional: `u_factor` is the glass package's `catalog_u_factor` and `shgc` is its `catalog_shgc`, taken verbatim. When the line completes production, the label certifies on a worst-unit basis: the server takes the lowest `argon_measured_pct` among the line's `QC_PASSED` units, derates the catalog U-factor by 0.002 for every percentage point of argon shortfall below the package's `argon_target_pct` — the derate is signed, so a measured fill above the target improves (lowers) the certified U-factor by the same 0.002 per point of overfill, with no clamping at zero shortfall — adds a spacer thermal-bridge derate of 0.01 for `ALUMINUM` spacers or 0.0 for `WARM_EDGE`, and rounds the result half-up to two decimal places. The SHGC stays at the catalog value, unchanged by fill. Because the certified rating is built from measured gas, two lines cut from the same catalog package can certify with different U-factors; certification also re-evaluates `compliance` against the applied rule. The label model nominally permits a fall back from `CERTIFIED` to `PROVISIONAL` on reconfiguration, but since lines can only be edited while the order is a draft — long before certification — that path is unreachable in practice.

The order-level echo of all this is the `compliance_status` dimension: `PENDING` at creation, `PROVISIONALLY_COMPLIANT` once the order is confirmed, and `CERTIFIED` once the order completes. It moves independently of `production_status`.

### 3.4. Production Waves and Order Release

The `ProductionLead` plans the floor in **waves**. Creating a wave takes a `wave_date`, a `capacity_units` ceiling on total window units, and a `capacity_glass_sqft` ceiling on total glazing area; the wave starts `PLANNED` with `allocated_units` and `allocated_glass_sqft` at zero. Opening the wave moves `PLANNED → OPEN` and makes it eligible for assignments; locking moves `OPEN → LOCKED` in preparation for release.

Assigning an order to a wave is the commit point of production planning, and its checks evaluate in pipeline order. The request names the `order_id` and must carry `expected_wave_version` — a stale token is rejected with `ERR_STALE_VERSION` before anything else about the wave is examined (§2.8). Then come the state gates: the wave must be `OPEN` (`ERR_WAVE_NOT_OPEN`) and the order must be `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`). Next the temporal gate: the `wave_date` may not be earlier than the order's `order_date` plus the largest `lead_time_days` among its non-`CANCELLED` lines — an earlier wave date is rejected with `ERR_WAVE_BEFORE_LEAD_TIME`. Finally the capacity gates, both with inclusive boundaries: the order's total line quantity, added to `allocated_units`, must not exceed `capacity_units` (`ERR_WAVE_CAPACITY_EXCEEDED`), and the order's glazing — each line's `glazing_sqft` times its `quantity`, summed — added to `allocated_glass_sqft`, must not exceed `capacity_glass_sqft` (`ERR_WAVE_GLASS_CAPACITY_EXCEEDED`). An exactly-full wave still accepts the assignment. On success the order moves `CONFIRMED → RELEASED` with its `wave_id` set to the wave, each of its lines moves `CONFIRMED → RELEASED`, the wave's allocation counters are recomputed upward, and the wave's `version` increments by one.

The allocation counters count only lines whose status is `RELEASED`, `IN_PRODUCTION`, or `COMPLETED`; lines sitting on `GLASS_HOLD` and cancelled lines are excluded. `allocated_units` is the sum of `quantity` over the counted lines; `allocated_glass_sqft` is the sum of each counted line's `glazing_sqft` times its `quantity`, rounded half-up to two decimal places after the summation.

An assignment can be walked back before the wave releases: unassigning takes the `order_id`, moves the order `RELEASED → CONFIRMED` and its lines back to `CONFIRMED`, clears the order's `wave_id`, releases the allocation, and increments the wave's `version`. Attempting it on an order that is not currently `RELEASED` — or that is `RELEASED` but assigned to a different wave — is rejected with `ERR_INVALID_STATE`.

Releasing a wave moves `LOCKED → RELEASED` and is allowed only when at least one assigned, non-`CANCELLED` order exists (otherwise `ERR_INVALID_STATE`). Release cascades: each assigned order in `RELEASED` moves to `IN_PROGRESS` (orders already `IN_PROGRESS` are untouched), each line in `RELEASED` moves to `IN_PRODUCTION`, and insulating glass units are created only for the lines that transitioned — one per unit of `quantity`, each starting `QUEUED` with `spacer_type` copied from the line's glass package, `unit_index` running from 1 through the line's `quantity`, and `remake_of_id` null. Lines on `GLASS_HOLD` are untouched by release, and re-releasing a wave never creates duplicate units for lines already in production.

A wave reopens on its own when it drains: whenever a downward recompute — a line entering `GLASS_HOLD`, or a cancellation — leaves `allocated_units` strictly below half of `capacity_units` rounded up, a wave in `LOCKED` or `RELEASED` automatically returns to `OPEN` and accepts new assignments again.

Closing a wave (`RELEASED → CLOSED`) is allowed only when nothing is in flight: no assigned order may still be `RELEASED` or `IN_PROGRESS`, and no line may be on `GLASS_HOLD` (violations return `ERR_INVALID_STATE`). Cancelling a wave is possible from `PLANNED` or `OPEN` only while it is empty — an `allocated_units` of zero; otherwise the cancel is rejected with `ERR_WAVE_HAS_ASSIGNMENTS`.

### 3.5. IG Unit Fabrication, Quality Control, and the Remake Cycle

Every insulating glass unit walks the same production line: `QUEUED → GLASS_CUT → SEALED → GAS_FILLED`, one stage per advance by a `ProductionLead` or `PlantManager`. Each advance requires the unit's parent line to be `IN_PRODUCTION`; advancing a unit whose line is in any other state is rejected with `ERR_INVALID_STATE`. Units of a line can be listed per line, or plant-wide filtered by `order_line_id` or `remake_of_id`.

Quality control happens at the `GAS_FILLED` stage — running the check on a unit in any other state is rejected with `ERR_IG_NOT_READY_FOR_QC`. The operator records the `argon_measured_pct`, and two gates decide the outcome. The fill gate requires the measured argon to be at least the glass package's `argon_min_pct`; the boundary is inclusive, so an exact match passes. The code gate applies only when the line's label has an applied energy rule: the certified U-factor at the measured fill — the `catalog_u_factor`, derated by 0.002 for every percentage point the measured argon falls below the `argon_target_pct` (the same signed derate as in §3.3: overfill lowers the value), plus the spacer derate of 0.01 for `ALUMINUM` or 0.0 for `WARM_EDGE`, rounded half-up to two decimal places — must be no greater than the rule's `max_u_factor`, and the catalog `shgc` must be no greater than the rule's `max_shgc`, both boundaries inclusive. When no rule applies, the code gate passes vacuously. A unit that clears both gates becomes `QC_PASSED` with its `argon_measured_pct` recorded; when the last unfinished unit of a line passes, the line bubbles up to `COMPLETED`, its energy label certifies on the worst-unit basis of §3.3, and if that was the order's final incomplete line the order itself moves `IN_PROGRESS → COMPLETED` and its `compliance_status` becomes `CERTIFIED`.

A unit that fails either gate becomes `BROKEN` with `break_cause` set to `GAS_NONCOMPLIANCE`, and the failing `argon_measured_pct` is recorded on the broken unit; the QC endpoint still returns 200 with the unit in this failure case. Physical breakage is reported separately: at any stage from `QUEUED` through `GAS_FILLED`, a `ProductionLead` or `PlantManager` may report a break with a `break_cause` of `HANDLING`, `LAMINATION_DEFECT`, `SEAL_FAILURE`, or `SHIPPING_DAMAGE`. The `GAS_NONCOMPLIANCE` cause is reserved for the quality-control path and is never accepted as manual input.

Both failure paths run the same three-hop cascade. The unit becomes `BROKEN`, and a replacement unit is created immediately at `QUEUED` with its `remake_of_id` pointing at the broken unit — the auto-remake guarantee that keeps the line whole. The remake inherits the broken unit's `unit_index` and `spacer_type` and starts with `argon_measured_pct` and `break_cause` null. The parent line then drops from `IN_PRODUCTION` to `GLASS_HOLD` (hop one), and the wave's allocation is recomputed without the held line (hop two). If that release leaves a `LOCKED` or `RELEASED` wave below half its unit capacity, rounded up, the wave reopens to `OPEN` by itself (hop three). A remake chain is finite: at most three remakes may descend from one original unit, and a breakage or quality-control failure that would spawn a fourth is rejected with `ERR_REMAKE_LIMIT_EXCEEDED`; the rejection is atomic — the unit is left unchanged in its prior state and no cascade runs.

Once the remake units exist — which the auto-remake guarantee ensures — a `ProductionLead` or `PlantManager` resumes a held line. Resuming requires the line to actually be `GLASS_HOLD` (`ERR_LINE_NOT_ON_GLASS_HOLD`), requires every `BROKEN` unit of the line to already have a remake (guaranteed by the auto-remake), and re-admits the line into its wave: the wave must be `RELEASED` (`ERR_INVALID_STATE`), and the capacity gates are checked again exactly as at assignment — the returning line's `quantity` added to `allocated_units` must not exceed `capacity_units` (`ERR_WAVE_CAPACITY_EXCEEDED`), and its `glazing_sqft` times `quantity` added to `allocated_glass_sqft` must not exceed `capacity_glass_sqft` (`ERR_WAVE_GLASS_CAPACITY_EXCEEDED`). On success the line returns `GLASS_HOLD → IN_PRODUCTION` and the wave's allocation is recomputed with the line counted again.

### 3.6. Shipping Racks, Reservations, and Delivery

Finished windows leave the plant on racks. A `ShippingCoordinator` creates a rack with a `rack_code` (like the catalog codes, not uniqueness-checked — duplicates are accepted) and a `slot_capacity` — the maximum number of window units a reservation may load, an inclusive ceiling. The rack's `status` is never set directly: it is `BOOKED` while at least one active reservation (status `RESERVED` or `LOADING`) exists and `AVAILABLE` otherwise, flipping automatically as reservations come and go. Racks can be listed filtered by `status`.

Reserving a rack takes the `order_id`, a `load_date`, and a `ship_date`; no ordering constraint between the two dates is enforced — a `load_date` after its own `ship_date` is accepted as supplied. The order must be `IN_PROGRESS` or `COMPLETED` (any other state is rejected with `ERR_INVALID_STATE`). Occupancy is a closed interval with a one-day turnover buffer: a new window conflicts with an existing active reservation on the same rack unless the new `load_date` falls at least two calendar days after the existing reservation's `ship_date`, or the existing reservation's `load_date` falls at least two calendar days after the new `ship_date`. Put concretely, a `load_date` exactly one day after a prior `ship_date` still conflicts — the turnover day is unavailable — while two days after is allowed; same-day turnover is never allowed. A colliding request is rejected with `ERR_RACK_OCCUPANCY_CONFLICT`. A successful reservation starts `RESERVED` with `assigned_units` zero, and its creation alone flips the rack from `AVAILABLE` to `BOOKED`. Reservations can be browsed per rack, or plant-wide filtered by `order_id` or `rack_id`.

Loading places one whole line at a time: the request names an `order_line_id`, the line must be `COMPLETED` (`ERR_INVALID_STATE`), must belong to the reservation's order (`ERR_RACK_WRONG_ORDER`), must not already be loaded — a line whose `rack_id` is already set is rejected with `ERR_INVALID_STATE` — and the load must fit: the line's `quantity` added to `assigned_units` may not exceed the rack's `slot_capacity`, with equality allowed (`ERR_RACK_CAPACITY_EXCEEDED`). The first successful load moves the reservation `RESERVED → LOADING`; subsequent loads keep it `LOADING` under the same checks. Each load stamps the line's `rack_id` with the reservation's rack and adds the line's `quantity` to `assigned_units`.

Shipping a reservation requires the order's `production_status` to be `COMPLETED`; shipping against an order in any other state is rejected with `ERR_ORDER_NOT_SHIPPABLE`. On ship, the reservation moves `LOADING → SHIPPED`, every loaded line — those whose `rack_id` is this rack and whose status is `COMPLETED` — moves to `SHIPPED`, and if that was the last unshipped non-`CANCELLED` line of the order, the order bubbles up from `COMPLETED` to `SHIPPED`. The rack then recomputes its derived status. A reservation can instead be cancelled, but only before anything has been loaded — `assigned_units` must still be zero (`ERR_INVALID_STATE`) — moving `RESERVED → CANCELLED` and again recomputing the rack's status, which returns to `AVAILABLE` when no active reservations remain.

Delivery is acknowledged by the dealer: a `DealerRep` confirming receipt of their own order, or a `PlantManager`, moves a `SHIPPED` order to `DELIVERED` and stamps `delivered_at` with the current logical clock. That timestamp is the warranty epoch — every coverage computation in §3.7 measures from it.

### 3.7. Warranty Claims and Service-Part Fulfillment

After delivery, a `DealerRep` (for their own orders) or a `PlantManager` files a warranty claim against one line: the payload carries the `order_id`, the `order_line_id` the claim attaches to, the failed `component` — `FRAME`, `IG_SEAL`, `GLASS`, `HARDWARE`, or `GRID` — the `coverage_variant` (`COMPONENT` for per-component windows or `WHOLE_UNIT` for a blanket window), the `failure_date`, and a free-text `description`. The named `order_line_id` must belong to the named order — a line of a different order is rejected with `ERR_NOT_FOUND`, as if it did not exist in this context. The order must be `DELIVERED` (`ERR_ORDER_NOT_DELIVERED`); the `failure_date` must be on or after the order's `delivered_at` and not later than the current logical time, and violations return `ERR_INVALID_REQUEST`. One active claim per line and component is the limit: if another claim for the same `order_line_id` and `component` exists in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED`, the filing is rejected with `ERR_DUPLICATE_ACTIVE_CLAIM`. The claim starts `SUBMITTED` with `remedy`, `remedy_value_cents`, and `denial_reason` unset, and its `coverage_pct` is computed at filing and re-evaluated at approval. Claims can be listed per order, or plant-wide filtered by `order_id`, `order_line_id`, or `status`.

Coverage is measured in whole years: `years_elapsed` is the number of complete 365-day years between the order's `delivered_at` and the claim's `failure_date`. Under the `COMPONENT` variant each component carries its own window. `FRAME` claims use the series' `frame_warranty_years` and `IG_SEAL` claims use the glass package's `ig_warranty_years`; both are in the 20-year class, which pays 100 percent while fewer than ten years have elapsed, then declines by ten percentage points per additional elapsed year — one hundred minus ten times the number of elapsed years beyond ten, never below zero — and pays zero beyond the window. `HARDWARE` and `GRID` carry 10-year windows: 100 percent while fewer than ten years have elapsed, zero thereafter. `GLASS` carries a 2-year window: 100 percent while fewer than two years have elapsed, zero thereafter. Under the `WHOLE_UNIT` variant a single blanket 15-year window covers any component: 100 percent while fewer than five years have elapsed, then one hundred minus twenty times the number of elapsed years beyond five, never below zero, and zero once fifteen or more years have elapsed. Identical failure dates can therefore produce very different `coverage_pct` values under the two variants.

Adjudication is a small workflow. A `WarrantyAdjuster` (or `PlantManager`) takes a `SUBMITTED` claim into `UNDER_REVIEW`, and may bounce it to `INFO_REQUESTED`; the dealer answers — `DealerRep` on their own dealership's claim, or a `PlantManager` — returning it `INFO_REQUESTED → UNDER_REVIEW`. Denial moves `UNDER_REVIEW → DENIED` and records the supplied `denial_reason`; the dealer may appeal, moving `DENIED → UNDER_REVIEW`. The review actions — take-review, request-info, approve, deny — are only defined from their respective review states; calling them from any other state is rejected with `ERR_CLAIM_NOT_REVIEWABLE`. A claim may be closed out from `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `DENIED` by the owning `DealerRep`, a `WarrantyAdjuster`, or a `PlantManager`, moving it to `CLOSED`.

Approval is the adjudicator's final act and requires `coverage_pct` greater than zero — approving an expired claim is rejected with `ERR_WARRANTY_EXPIRED`. The approver chooses the `remedy`: `REPAIR_PART` or `REFUND`. Either way, `remedy_value_cents` is set to the line's frozen `line_total_cents` multiplied by `coverage_pct` and divided by one hundred, rounded half-up to whole cents — prorated first, rounded once. A `REFUND` remedy fulfills the claim immediately, moving it straight to `FULFILLED`. A `REPAIR_PART` remedy also carries `part_sku`, `quantity`, and a `carrier` of `PARCEL`, `STANDARD_FREIGHT`, or `EXPEDITED`, and creates a **ServicePartShipment** in `PICKING` status referencing the claim via `warranty_claim_id`. The shipment's `shipping_charge_cents` is zero when the claim's coverage is a full 100 percent; otherwise it is the carrier's flat fee — 2,500 cents for `PARCEL`, 8,000 cents for `STANDARD_FREIGHT`, or 15,000 cents for `EXPEDITED`.

Service-part shipments walk `PICKING → SHIPPED → DELIVERED` under a `ShippingCoordinator` or `PlantManager`. Delivering the shipment cascades upward: the parent claim moves from `APPROVED` to `FULFILLED`, closing the loop. Shipments can be listed per claim, or plant-wide filtered by `warranty_claim_id`.

### 3.8. Cancellation Paths Across the Lifecycle

Cancellation unwinds whatever the plant has already committed, and what gets unwound depends on how far the order has traveled. A `DealerRep` may cancel their own order, and a `PlantManager` may cancel any order — but once an order is `IN_PROGRESS`, only a `PlantManager` may cancel it. Cancellation is defined only from `DRAFT`, `CONFIRMED`, `RELEASED`, and `IN_PROGRESS`; attempting it from `SHIPPED` or `COMPLETED` is rejected with `ERR_INVALID_STATE`, just as delivered and already-cancelled orders are terminal and accept no further transitions. In every cancellation the order's money fields and `promised_date` are recomputed over the surviving non-`CANCELLED` lines — so a fully cancelled order's `subtotal_cents`, `discount_cents`, and `total_price_cents` recompute to zero and its `promised_date` clears to null — and the order's `version` advances accordingly.

From `DRAFT`, cancellation simply moves the order to `CANCELLED` and cascades its `PENDING` lines to `CANCELLED`. From `CONFIRMED`, the same cascade takes `CONFIRMED` lines to `CANCELLED`. From `RELEASED`, the lines move to `CANCELLED`, the order's `wave_id` is cleared, and the wave's allocation is recomputed without the cancelled lines — a release that may reopen the wave per the auto-unlock rule of §3.4. From `IN_PROGRESS` — the `PlantManager`-only path — each line in `IN_PRODUCTION` or `GLASS_HOLD` moves to `CANCELLED`, the order's `wave_id` is cleared exactly as in the `RELEASED` path, and the cascade reaches one level deeper: every non-terminal insulating glass unit of those lines (any unit still `QUEUED`, `GLASS_CUT`, `SEALED`, or `GAS_FILLED`) is `SCRAPPED`. Lines that were on `GLASS_HOLD` contribute nothing back to the wave, because their allocation was already released when the hold began; lines in `IN_PRODUCTION` release their allocation through the same recompute.

Terminal states close out each aggregate: an order ends at `DELIVERED` or `CANCELLED`; a line at `SHIPPED` or `CANCELLED`; a wave at `CLOSED` or `CANCELLED`; a claim at `FULFILLED` or `CLOSED`; a shipment at `DELIVERED`. Insulating glass units end at `QC_PASSED`, `BROKEN`, or `SCRAPPED` — with the understanding that a `BROKEN` unit extends its story through the remake chain rather than ending it.

## 4. Endpoint Definitions

Operations that create a new resource — a dealer, a catalog entry, an order, a line, a wave, a rack, a reservation, a claim — return `201 Created`. Operations that act on an existing resource, including all state transitions, returns, reads, and the clock capability, return `200 OK`. The complete request payloads, preconditions, and side effects for each operation are specified in §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (starts at 2026-08-01T00:00:00Z; never falls back to wall-clock) | PlantManager |
| POST | `/fenestration/dealers` | Create a Dealer | PlantManager |
| GET | `/fenestration/dealers/{dealerId}` | Get a Dealer | Any authenticated role |
| POST | `/fenestration/dealers/{dealerId}/credit-hold` | Place dealer on credit hold | PlantManager |
| POST | `/fenestration/dealers/{dealerId}/credit-release` | Release dealer credit hold | PlantManager |
| POST | `/fenestration/catalog-series` | Create a CatalogSeries | PlantEngineer, PlantManager |
| GET | `/fenestration/catalog-series/{seriesId}` | Get a CatalogSeries | Any authenticated role |
| POST | `/fenestration/catalog-series/{seriesId}/discontinue` | Discontinue a series | PlantEngineer, PlantManager |
| POST | `/fenestration/glass-packages` | Create a GlassPackage | PlantEngineer, PlantManager |
| GET | `/fenestration/glass-packages/{glassPackageId}` | Get a GlassPackage | Any authenticated role |
| POST | `/fenestration/energy-code-rules` | Create an EnergyCodeRule (half-open windows per state must not overlap) | PlantEngineer, PlantManager |
| GET | `/fenestration/energy-code-rules/{ruleId}` | Get an EnergyCodeRule | Any authenticated role |
| POST | `/fenestration/orders` | Create a DRAFT order | DealerRep, PlantManager |
| GET | `/fenestration/orders/{orderId}` | Get an order | Any authenticated role |
| GET | `/fenestration/orders` | List orders (paginated, filterable) | Any authenticated role |
| POST | `/fenestration/orders/{orderId}/confirm` | Confirm a DRAFT order: freezes prices, evaluates compliance, checks credit | DealerRep, PlantManager |
| POST | `/fenestration/orders/{orderId}/cancel` | Cancel an order (IN_PROGRESS orders: PlantManager only) | DealerRep, PlantManager |
| POST | `/fenestration/orders/{orderId}/confirm-delivery` | Mark a SHIPPED order delivered; starts the warranty epoch | DealerRep, PlantManager |
| POST | `/fenestration/orders/{orderId}/lines` | Add a configured line to a DRAFT order; auto-creates its EnergyLabel | DealerRep, PlantManager |
| GET | `/fenestration/orders/{orderId}/lines` | List lines of an order | Any authenticated role |
| GET | `/fenestration/order-lines/{lineId}` | Get an OrderLine | Any authenticated role |
| GET | `/fenestration/order-lines` | List OrderLines filtered by catalog references or rack | Any authenticated role |
| PATCH | `/fenestration/orders/{orderId}/lines/{lineId}` | Reconfigure a line while the order is DRAFT (OCC on order version) | DealerRep, PlantManager |
| POST | `/fenestration/order-lines/{lineId}/resume-production` | Resume a GLASS_HOLD line; re-checks wave capacity | ProductionLead, PlantManager |
| GET | `/fenestration/order-lines/{lineId}/energy-label` | Get the line's EnergyLabel (array of 0-1) | Any authenticated role |
| GET | `/fenestration/energy-labels/{labelId}` | Get an EnergyLabel | Any authenticated role |
| GET | `/fenestration/energy-labels` | List EnergyLabels filtered by applied rule | Any authenticated role |
| POST | `/fenestration/production-waves` | Create a wave | ProductionLead, PlantManager |
| GET | `/fenestration/production-waves/{waveId}` | Get a wave | Any authenticated role |
| POST | `/fenestration/production-waves/{waveId}/open` | Move a wave PLANNED to OPEN | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/assignments` | Assign a CONFIRMED order to an OPEN wave (OCC on wave version) | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/unassign` | Remove a RELEASED order from a wave before release | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/lock` | Move a wave OPEN to LOCKED | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/release` | Move a wave LOCKED to RELEASED; cascades orders to IN_PROGRESS and creates IGUnits | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/close` | Move a wave RELEASED to CLOSED when nothing is in flight | ProductionLead, PlantManager |
| POST | `/fenestration/production-waves/{waveId}/cancel` | Cancel an empty PLANNED or OPEN wave | ProductionLead, PlantManager |
| GET | `/fenestration/order-lines/{lineId}/ig-units` | List IGUnits of a line | Any authenticated role |
| GET | `/fenestration/ig-units/{igUnitId}` | Get an IGUnit | Any authenticated role |
| GET | `/fenestration/ig-units` | List IGUnits filtered by remake parent | Any authenticated role |
| POST | `/fenestration/ig-units/{igUnitId}/advance` | Advance one production stage (QUEUED, GLASS_CUT, SEALED, GAS_FILLED) | ProductionLead, PlantManager |
| POST | `/fenestration/ig-units/{igUnitId}/qc-check` | Record measured argon and run QC (fill threshold plus certified code gate) | ProductionLead, PlantManager |
| POST | `/fenestration/ig-units/{igUnitId}/report-breakage` | Report physical breakage at any pre-QC stage | ProductionLead, PlantManager |
| POST | `/fenestration/shipping-racks` | Create a rack | ShippingCoordinator, PlantManager |
| GET | `/fenestration/shipping-racks/{rackId}` | Get a rack | Any authenticated role |
| GET | `/fenestration/shipping-racks` | List racks (filterable) | Any authenticated role |
| POST | `/fenestration/shipping-racks/{rackId}/reservations` | Create a RackReservation with overlap-checked occupancy window | ShippingCoordinator, PlantManager |
| GET | `/fenestration/shipping-racks/{rackId}/reservations` | List reservations of a rack | Any authenticated role |
| GET | `/fenestration/rack-reservations/{reservationId}` | Get a RackReservation | Any authenticated role |
| GET | `/fenestration/rack-reservations` | List RackReservations filtered by order or rack | Any authenticated role |
| POST | `/fenestration/rack-reservations/{reservationId}/load` | Load one COMPLETED line (whole quantity) under this reservation | ShippingCoordinator, PlantManager |
| POST | `/fenestration/rack-reservations/{reservationId}/ship` | Ship a LOADING reservation | ShippingCoordinator, PlantManager |
| POST | `/fenestration/rack-reservations/{reservationId}/cancel` | Cancel an un-loaded reservation | ShippingCoordinator, PlantManager |
| POST | `/fenestration/warranty-claims` | File a warranty claim against a line of a DELIVERED order | DealerRep, PlantManager |
| GET | `/fenestration/warranty-claims/{claimId}` | Get a claim | Any authenticated role |
| GET | `/fenestration/warranty-claims` | List claims (filterable) | Any authenticated role |
| GET | `/fenestration/orders/{orderId}/warranty-claims` | List claims of an order | Any authenticated role |
| POST | `/fenestration/warranty-claims/{claimId}/take-review` | Move a claim SUBMITTED to UNDER_REVIEW | WarrantyAdjuster, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/request-info` | Move a claim UNDER_REVIEW to INFO_REQUESTED | WarrantyAdjuster, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/provide-info` | Move a claim INFO_REQUESTED to UNDER_REVIEW | DealerRep, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/approve` | Approve an UNDER_REVIEW claim; sets remedy and remedy value | WarrantyAdjuster, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/deny` | Move a claim UNDER_REVIEW to DENIED | WarrantyAdjuster, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/appeal` | Move a claim DENIED to UNDER_REVIEW | DealerRep, PlantManager |
| POST | `/fenestration/warranty-claims/{claimId}/close` | Close a claim from SUBMITTED, UNDER_REVIEW, INFO_REQUESTED, or DENIED | DealerRep, WarrantyAdjuster, PlantManager |
| GET | `/fenestration/warranty-claims/{claimId}/service-part-shipments` | List service-part shipments of a claim | Any authenticated role |
| GET | `/fenestration/service-part-shipments/{shipmentId}` | Get a ServicePartShipment | Any authenticated role |
| GET | `/fenestration/service-part-shipments` | List ServicePartShipments filtered by claim | Any authenticated role |
| POST | `/fenestration/service-part-shipments/{shipmentId}/ship` | Move a shipment PICKING to SHIPPED | ShippingCoordinator, PlantManager |
| POST | `/fenestration/service-part-shipments/{shipmentId}/deliver` | Move a shipment SHIPPED to DELIVERED; fulfills the parent claim | ShippingCoordinator, PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_HAS_NO_LINES` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_WAVE_NOT_OPEN` | 409 Conflict |
| `ERR_WAVE_HAS_ASSIGNMENTS` | 409 Conflict |
| `ERR_WAVE_BEFORE_LEAD_TIME` | 409 Conflict |
| `ERR_WAVE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_WAVE_GLASS_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_IG_NOT_READY_FOR_QC` | 409 Conflict |
| `ERR_REMAKE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_LINE_NOT_ON_GLASS_HOLD` | 409 Conflict |
| `ERR_RACK_OCCUPANCY_CONFLICT` | 409 Conflict |
| `ERR_RACK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_RACK_WRONG_ORDER` | 409 Conflict |
| `ERR_SERIES_DISCONTINUED` | 409 Conflict |
| `ERR_SIZE_EXCEEDS_SERIES_LIMIT` | 422 Unprocessable Entity |
| `ERR_ENERGY_CODE_VIOLATION` | 409 Conflict |
| `ERR_ENERGY_RULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DEALER_CREDIT_HOLD` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CLAIM` | 409 Conflict |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 Conflict |
