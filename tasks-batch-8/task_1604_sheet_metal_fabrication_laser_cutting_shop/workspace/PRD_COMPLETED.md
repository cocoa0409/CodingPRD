# Sheet Metal Fabrication & Laser Cutting Shop API — Product Requirements Document

## 1. Introduction

A sheet-metal fabrication shop sells two things at once: machine time on its lasers, brakes, weld bays, and powder line — and the yield it can coax out of expensive plate stock. Quoting that work accurately is hard because the price promised to a customer is only an estimate until the parts are actually nested onto real sheets; the shop's true cost depends on sheet sharing, remnant recovery, and machine load that no per-part formula can see in advance. This API manages that gap. It runs the full commercial loop of a laser-cutting and fabrication shop — customer accounts, material grade catalogs, sheet and remnant inventory, machine and outside-vendor registries, multi-line quotes, fabrication orders, routing and capacity, first-piece inspection, payment, and a scrap-credit ledger that rewards customers for returning usable offcuts.

Two design commitments shape everything that follows. First, money is tracked under two variants: a quoted figure produced before any nesting knowledge exists, and a committed figure recomputed once the nest is real; both are persisted, and their difference is the shop's nesting-loss metric. Second, all time-driven behavior — quote expiry, vendor lead times, schedule service levels, and the machine-capacity horizon — reads a single logical clock rather than the wall clock, so the passage of time is an explicit, controllable input. All resources are mounted under the `/fab` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes seven roles. `ShopManager` is the shop owner: master data (grades, machines, vendors), customer administration, credit voids, audit access, and the logical clock. `Estimator` builds and prices quotes, owning the quote lifecycle up to submission. `CustomerRep` is the customer-facing representative who accepts or rejects quotes on the customer's behalf and records payments. `ProductionPlanner` runs the floor: renesting, release, holds and resumes, cancellation, receiving outside work, and skipping steps. `MachineOperator` completes assigned routing steps, with identity recorded for segregation of duties. `QCInspector` performs first-piece inspection and must never inspect their own work. `InventoryClerk` handles sheet-stock receiving, scrapping, and scrap-credit posting.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `ShopManager`, `Estimator`, `ProductionPlanner`, `MachineOperator`, `QCInspector`, or `InventoryClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may still record it — a `MachineOperator`'s identifier is stamped as `completing_operator_id` when they complete a routing step, and a `QCInspector`'s as `inspector_id` on an inspection report — but it is not compared to any entity's `id` for ownership. On list endpoints a `CustomerRep` sees only rows owned by their own customer: quotes, quote lines, fabrication orders, and scrap credits are narrowed to the caller's customer before any query filters apply, while master-data lists (customers, grades, machines, vendors, and sheet stock) carry no customer ownership and are visible to every role the endpoint admits.

Each endpoint restricts which roles may call it; the authoritative mapping is the endpoint table in §4. A caller whose role is not in the endpoint's list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 or above 100 is clamped into the range, a non-integer `limit` falls back to 10, a negative `offset` is clamped to 0, and a non-integer `offset` falls back to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by creation order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. The Shop Logical Clock

A fabrication shop's commercial promises are all time-relative: quotes expire, vendors quote lead times in days, machines are booked against a rolling horizon. Instead of the wall clock, the server keeps a logical clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterward. A `ShopManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant; the quote expiry sweep runs against the new clock as part of that call. The supplied value must parse as an ISO 8601 instant — one without an offset is read as UTC, and an unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and the clock is set to exactly the supplied instant, with no monotonicity requirement. The response is `200 OK` with a data object carrying the new reading as `current_utc`. Quote validity windows, vendor lead-time arithmetic, routing service levels, and the machine-capacity horizon all read this logical clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource, enabling optimistic concurrency control.

Two resources are append-only exceptions to this convention. An inspection report and an audit event each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, since neither resource is ever modified after creation.

### 2.6. Money, Measurement, and Rounding Discipline

All monetary values in the system are integer cents. Every rounding of a monetary result uses the round-half-up method and is applied exactly where the governing rule says so — per-second rates and estimated seconds are never rounded intermediately. Estimated cut seconds are carried to three decimal places and then rounded up to the next whole second for billing. Areas are tracked internally in integer square millimeters and reported in square centimeters to one decimal place. Sheet yield is a proportion reported to four decimal places, rounded half-up. The first-piece flatness ratio is compared without any rounding at all.

### 2.7. Optimistic Concurrency Control on Guarded Writes

Two writes are guarded by optimistic concurrency control, and only these two. Re-pricing a quote requires the request to carry `expected_quote_version`, the caller's last-observed `version` of the quote; if the quote's version has advanced since the client last read it — another writer may have revised its lines or its expedite tier — the re-price is rejected with `ERR_STALE_VERSION` (HTTP 412), because pricing from a stale snapshot would silently discard those edits. Voiding a scrap credit likewise requires `expected_customer_version` matching the customer's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a credit application or a new posting may have moved `scrap_credit_balance_cents` since the caller last read it, and the void would debit a balance the caller never observed. Endpoints not named here do not take a version field.

### 2.8. Resource Retrieval and Filtering

The API has a flat topology: every resource is addressable by its `id` at the top level, and some collections are additionally reachable nested under a parent — lines under their quote; nest sheets, routing steps, and inspection reports under their order; work queues under a machine or an outside vendor. Where a path contains more than one identifier, the server resolves identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist, before examining later segments, the request body, or any business rule. The same `ERR_NOT_FOUND` covers body foreign keys that fail to resolve.

List endpoints accept optional query filters that narrow the returned collection. Customers filter by `status`. Sheet stock filters by `grade_id`, `status`, `kind`, and `source_order_id`. Machines filter by `station` and `status`, and a machine's work queue filters by `status`. Outside vendors filter by `process` and `status`, and a vendor's queue filters by `status`. Quotes filter by `customer_id` and `status`. The cross-quote line list filters by `quote_id`, `grade_id`, and `status`. Orders filter by `customer_id`, `status`, `payment_status`, and `quote_id`. Nest sheets filter by `order_id`, `sheet_stock_id`, and `remnant_stock_id`. Routing steps filter by `order_id`, `machine_id`, `vendor_id`, `station`, and `status`. Scrap credits filter by `customer_id`, `status`, and `sheet_stock_id`. Audit events filter by `entity_type`, `entity_id`, and `event_type`.

### 2.9. The Validation Cascade

Every request passes through a fixed cascade of validation tiers, and earlier tiers mask later ones: a caller always observes the failure from the earliest tier that applies.

First, the two authentication headers must be present and carry a declared role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400). At the second tier, two checks run together, before any resource is dereferenced: whether the caller's role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`, HTTP 403), and — for endpoints with a body — whether the body is well-formed, meaning required fields present, types matching, and no unknown fields (`ERR_INVALID_REQUEST`, HTTP 400). Within this tier the role check is evaluated first, so a caller failing both observes `ERR_FORBIDDEN_ROLE`. Third, existence: path identifiers resolve left to right, and body foreign-key references such as `grade_id`, `customer_id`, `sheet_stock_id`, and `vendor_id` must point at existing resources (`ERR_NOT_FOUND`, HTTP 404). Fourth, state: the target resource's current status must permit the requested transition; failures surface as `ERR_INVALID_STATE` (HTTP 409) or one of the transition-specific forms named in §3.

The remaining tiers run in this order. Fifth and sixth, business safety: segregation of duties at inspection (`ERR_SOD_VIOLATION`, HTTP 403) is evaluated before the flatness-override guard (`ERR_FLATNESS_EXCEEDED`, HTTP 422). Seventh and eighth, line constraints: structural line validity (`ERR_INVALID_LINE_SPEC`, HTTP 422 — with `ERR_THICKNESS_TIER_UNRESOLVED` as its tier-specific form) runs before finish and route compatibility (`ERR_FINISH_NOT_COMPATIBLE`, HTTP 422). Ninth through eleventh, temporal guards: quote expiry (`ERR_QUOTE_EXPIRED`, HTTP 409), then vendor lead time (`ERR_VENDOR_LEAD_TIME_NOT_ELAPSED`, HTTP 409), then machine capacity within the horizon (`ERR_NO_MACHINE_CAPACITY`, HTTP 409). Twelfth and thirteenth, referential business rules: nest feasibility (`ERR_NEST_INFEASIBLE`, HTTP 409) and scrap-source validity (`ERR_SCRAP_SOURCE_INVALID`, HTTP 422). Fourteenth and fifteenth, fiscal guards: the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402) and scrap-credit sufficiency (`ERR_INSUFFICIENT_SCRAP_CREDIT`, HTTP 402). Sixteenth and last, the optimistic-concurrency check on the two guarded writes (`ERR_STALE_VERSION`, HTTP 412).

### 2.10. The Shop Audit Trail

The mutations enumerated in §3 each append an audit event recording `entity_type` (the entity name of the mutated resource), `entity_id` (the mutated resource's identifier), an `event_type` label such as QUOTE_SUBMITTED, ORDER_RENESTED, or INSPECTION_FAIL_REWORK, the caller's `actor_role` and `actor_id` drawn from the request headers — recorded as the literal `system` for internally driven transitions — and a `detail` map of before-and-after field values for the mutation. Specific event labels appear throughout §3 alongside the transitions that raise them. Audit events are queryable by a `ShopManager` only.

### 2.11. Cross-Entity Consistency and Cascading Effects

State changes propagate across entity boundaries. A quote that expires or is rejected supersedes its lines. An order cancellation releases its nest — consumed sheets return to AVAILABLE, nest-generated remnant rows are scrapped — and frees reserved machine minutes. A failed first-piece inspection resets the implicated routing steps and re-books their minutes. A payment draws down the customer's posted scrap credits. Every resource mutated by such a cascade has its `updated_at` refreshed and its `version` incremented, which is precisely what makes the version guards of §2.7 bite: a client holding a stale snapshot of a quote or customer discovers it at the next guarded write. Capacity is re-validated whenever reservations could shift — at routing generation, on resume, on renest, and on rework reset — and machine assignment follows the selector described in §3.6 each time.

## 3. Business Logic & Workflows

### 3.1. Master Data: Customers, Grades, Machines, and Vendors

A `ShopManager` onboards each customer with a `company_name`, a contact `email`, and a `credit_limit_cents` — the maximum outstanding approved-order total the shop will carry for them, where zero means prepay-only. A new customer starts with `status` ACTIVE and a `scrap_credit_balance_cents` of zero, and registration appends a CUSTOMER_CREATED audit event. Suspension flips a customer to SUSPENDED, which blocks new quote submission: submitting a quote whose owner is suspended is rejected with `ERR_CUSTOMER_SUSPENDED`, and the same guard protects acceptance. Suspension appends a CUSTOMER_SUSPENDED audit event.

Material grades are the pricing backbone of the shop. A `ShopManager` defines each grade with a `code` (shop shorthand such as AL5052, CRS1008, or SS304), an `alloy_family` of ALUMINUM, CARBON_STEEL, or STAINLESS, and a `density_g_per_cm3` used for weight reporting — 2.70 for aluminum, 7.85 for carbon steel, 8.00 for stainless. The `hardness_factor` scales cut rates by material: 1.00 for carbon steel, 1.15 for aluminum, 1.40 for stainless. Commercially the grade carries a `base_cut_rate_cents_per_sec` at its thinnest thickness tier, a `material_cost_cents_per_cm2` for stock, and a `scrap_rate_cents_per_cm2` for credit posting. Its `thickness_tiers` table is an ordered list of gauge ceilings, each entry pairing a `max_thickness_mm` with a `tier_index` in ascending order, which drives both the cut-rate surcharge and the bend thickness class described in §3.3. Finally, `weld_compatible` and `powder_compatible` declare whether the WELD station and the in-house POWDER station accept the grade. Defining a grade appends a GRADE_CREATED audit event.

Machines are registered with a `name`, a `station` of LASER, BRAKE, WELD, or POWDER — outside plating and anodizing are never machines — and `shift_minutes_per_day`, the bookable minutes per calendar day (480 for a single eight-hour shift). A machine starts ACTIVE. A `ShopManager` may set a machine DOWN, which blocks new routing reservations while leaving its existing booked load in place; an order whose assigned machines include a DOWN machine cannot be released to the floor, as §3.6 describes. Registering a machine appends a MACHINE_CREATED audit event, and setting a machine's status appends a MACHINE_STATUS_CHANGED audit event.

Outside finishes run through vendor rows rather than machines. Registering one takes a `name`, a `process` of PLATING or ANODIZING, a `lead_time_days` standard round-trip in calendar days, and a `base_cost_cents_per_part` pass-through cost that flows into finish pricing. A vendor starts ACTIVE and stays ACTIVE — the API offers no retirement transition — and only an ACTIVE vendor of the matching process can satisfy a plating or anodizing line. Registration appends a VENDOR_CREATED audit event.

### 3.2. Sheet Stock Intake and the Scrap Credit Ledger

An `InventoryClerk` receives stock by registering its `grade_id`, `thickness_mm`, `width_mm`, and `height_mm`; `width_mm` and `height_mm` must be positive, with a non-positive dimension rejected by `ERR_INVALID_REQUEST` (HTTP 400). The system classifies `kind` automatically: a sheet measuring exactly 1200 by 2400 millimeters is a FULL_SHEET, and anything else is recorded as a REMNANT — a usable offcut retained in inventory. New stock starts AVAILABLE with `source_order_id` empty; that field is populated only on remnants generated by nesting, where it points back at the fabrication order that produced them. Receiving stock appends a STOCK_RECEIVED audit event.

Stock moves through a small lifecycle. Nesting consumes a sheet, moving it from AVAILABLE to CONSUMED; when the leftover offcut qualifies, a child REMNANT row is created in AVAILABLE status and linked to the consuming order through `source_order_id`. A clerk may scrap any AVAILABLE row — attempting to scrap stock in any other status is rejected with `ERR_STOCK_NOT_AVAILABLE` — moving it to SCRAPPED and recording a STOCK_SCRAPPED audit event. Walk-in drop-offs take a third path: the clerk pre-registers the sheet and posts the customer's credit in one flow, moving the sheet from AVAILABLE to DROPPED_OFF. The final transition is internal to order cancellation: the remnant rows a cancelled order's nest generated are moved to SCRAPPED — a nest-linked remnant row reaches SCRAPPED only through order cancellation or by being surrendered for a scrap credit — while the consumed parent sheets themselves are restored to AVAILABLE instead.

Posting a scrap credit takes a `customer_id` and a `sheet_stock_id`. The source is polymorphic: either a REMNANT surrendered from inventory, which must belong to that customer as traced through the remnant's source order, or a walk-in sheet registered with no source order. A source that is not in AVAILABLE status, or whose `source_order_id` traces to an order owned by another customer, is rejected with `ERR_SCRAP_SOURCE_INVALID`; the source's `kind` is never itself grounds for rejection. Posting also retires the source sheet: a surrendered remnant moves from AVAILABLE to SCRAPPED, and a walk-in sheet moves from AVAILABLE to DROPPED_OFF. The credited area, `credited_area_cm2`, is the smallest of three ceilings: the source sheet's own area, ten percent of the standard sheet area — ten percent of 28,800 square centimeters, which is 2,880 square centimeters — and a hard cap of 90,000 square centimeters per event. The credit itself, `credit_cents`, is the credited area multiplied by the grade's `scrap_rate_cents_per_cm2`, rounded half-up to integer cents. The credit lands in POSTED status, the customer's `scrap_credit_balance_cents` increases by exactly that amount, the customer's `version` increments, and a CREDIT_POSTED audit event is appended.

A `ShopManager` can void a POSTED credit — correcting a mis-posted drop-off, for instance — by presenting `expected_customer_version` matching the customer's current `version`. Voiding a credit in any status other than POSTED is rejected with `ERR_CREDIT_NOT_VOIDABLE`; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412) as §2.7 describes. The void is a compensating reversal: `scrap_credit_balance_cents` is debited by the credit's `credit_cents`, the customer's `version` increments by one, the credit moves to VOID, and a CREDIT_VOIDED audit event is appended. Credits in APPLIED status can never be voided, because their value has already been drawn against an invoice.

### 3.3. Quoting: Lines and the Pricing Pipeline

An `Estimator` opens a quote for a `customer_id`, optionally setting an `expedite_tier` of STANDARD, EXPEDITE, or RUSH — STANDARD when omitted — and optionally passing initial `lines`. The quote begins in DRAFT with `revision_count` zero. Lines may also be added one at a time while the quote is DRAFT; each line names its material through `grade_id` and `thickness_mm`, the part envelope through `bbox_width_mm` and `bbox_height_mm`, optional features — `hole_count` (default 0) at `hole_diameter_mm` (default 20) each, `corner_fillet_count` (default 0), `bend_count` (default 0), and `weld_inches` (default 0) — a `finish` of NONE, POWDER, PLATING, or ANODIZING (default NONE), and a `qty` of at least one. A freshly added line starts in ESTIMATED status. Adding a line to a quote that is not DRAFT is rejected with `ERR_INVALID_STATE` (HTTP 409). Each line's computed pricing fields — cut seconds, costs, discount, and totals per the pipeline below — are populated when the line is added, under the quoted variant, and refreshed by every pricing run.

Line specifications are validated structurally before anything else: bounding-box dimensions must be positive, `qty` at least one, hole, fillet, and bend counts non-negative, the finish a declared enum member, and the thickness resolvable against the grade's tier table. Structural failures are rejected with `ERR_INVALID_LINE_SPEC`, with `ERR_THICKNESS_TIER_UNRESOLVED` as the tier-specific form when the gauge exceeds every tier's `max_thickness_mm`. Compatibility is a separate check that runs after structure: POWDER requires the grade's `powder_compatible` flag, any positive `weld_inches` requires `weld_compatible`, and PLATING or ANODIZING requires an ACTIVE outside vendor of the matching process; violations are rejected with `ERR_FINISH_NOT_COMPATIBLE`. These two checks guard all three line-bearing operations — quote creation with initial lines, line addition, and pricing. Feature flags also shape routing later: any positive `bend_count` routes the order through BRAKE, and any positive `weld_inches` routes it through WELD.

Pricing is an explicit act by an `Estimator` on a DRAFT quote, and it is one of the two version-guarded writes: the request must carry `expected_quote_version`, and a mismatch with the quote's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Pricing a quote that is not DRAFT fails with `ERR_QUOTE_NOT_OPEN`; pricing one with zero lines fails with `ERR_QUOTE_EMPTY` — a check that runs immediately after the state check, before any line is revalidated. The pricing checks run in a fixed order — state first, then structural line validity, then finish compatibility, then the version guard last — so a caller always sees the earliest failure. A successful run recomputes every line in ESTIMATED or PRICED status through the full pipeline below, marks each line PRICED, rolls up fresh quote totals, moves the quote to PRICED, increments the quote's `version` by one, and appends a QUOTE_PRICED audit event.

The pipeline prices each line per single part first; the line quantity multiplies only at order-level aggregation. Step one resolves the gauge: the line's `thickness_tier_index` is the smallest index in the grade's ordered `thickness_tiers` whose `max_thickness_mm` is greater than or equal to the line's `thickness_mm`, and a gauge thicker than the final tier's ceiling is rejected with `ERR_THICKNESS_TIER_UNRESOLVED`. Step two measures the cut. The part area in square centimeters is `bbox_width_mm` times `bbox_height_mm` divided by one hundred. The total cut length is twice the sum of the bounding-box width and height, plus one hole circumference — pi times `hole_diameter_mm` — for every hole in `hole_count`. The pierce count is `hole_count` plus `corner_fillet_count` plus one for the outer profile. The raw estimate `cut_seconds_est` combines a fixed 8.0-second machine overhead, 0.045 seconds per millimeter of cut length, and 1.2 seconds per pierce, carried to three decimal places; the billing quantum `billed_cut_seconds` is that estimate rounded up to the next whole second. Step three converts time to money: the effective per-second rate is the grade's `base_cut_rate_cents_per_sec` scaled by the tier surcharge — one plus twenty percent times the tier index — and then multiplied by the grade's `hardness_factor`; the cut cost is `billed_cut_seconds` times that rate, rounded half-up to integer cents, with no intermediate rounding of rates or seconds.

Step four prices bends. Each bend consumes one plus a thickness class plus a complexity class bend units: the thickness class is 1 when the tier index is 0, 2 when it is 1, and 3 when it is 2 or higher; the complexity class is 1 when `corner_fillet_count` is at least 4 and 0 otherwise. The line's `bend_units` are those per-bend units multiplied by `bend_count`, and the bend cost is `bend_units` times 150 cents. Step five prices the finish stored on the line as `finish_cost_cents`. NONE contributes zero. POWDER is an in-house finish whose line-level rows are computed per line with the quantity multiplied inside: the part area times 0.040 cents per square centimeter, rounded half-up, times the line quantity. PLATING and ANODIZING are outside finishes: the same construction at 0.060 and 0.055 cents per square centimeter respectively, plus the assigned vendor's `base_cost_cents_per_part` multiplied by the line quantity on top. The assigned vendor for an outside process is the ACTIVE vendor of that process with the lowest `base_cost_cents_per_part`, ties broken by earliest `created_at`. Step six estimates material under the quoted variant: per part, the larger of the part area and the 300-square-centimeter minimum billable area, multiplied by the grade's `material_cost_cents_per_cm2`, rounded half-up to integer cents. This `material_cost_cents` is a non-nested estimate — it knows nothing of sheet sharing — and it is superseded at order commit by the committed variant of §3.5. Step seven assembles `line_base_cents`, the per-part line base before discounts: the sum of the cut cost, the bend cost, the finish cost, the material cost, and a 900-cent setup fee per line.

Step eight applies the quantity discount. The tiers are inclusive and evaluated top-down: a `qty` of at least 50 earns 12 percent off, at least 20 earns 8 percent, at least 10 earns 4 percent, and smaller quantities earn none; the line records the winning fraction as `qty_discount_pct`. The discounted net is `line_base_cents` times one minus `qty_discount_pct`, rounded half-up. Step nine applies the expedite multiplier for the quote's `expedite_tier` — 1.00 for STANDARD, 1.25 for EXPEDITE, 1.50 for RUSH — to the discounted net, never to the pre-discount base, and rounds half-up to produce the per-part `line_total_cents`. The evaluation order is pinned: the quantity discount applies first, the expedite multiplier second, and the line quantity multiplies last at order aggregation, because `line_total_cents` is a per-part figure. A RUSH tier additionally compresses the routing service level and halves vendor lead time, as §3.6 and §3.7 describe. The quote then rolls up three figures: `quoted_subtotal_cents`, the sum over lines of each line's discounted per-part net — `line_base_cents` less the quantity discount, rounded half-up under the non-nested material estimate — multiplied by its `qty`; `quoted_expedite_cents`, the sum over lines of each line's expedite surcharge — its per-part `line_total_cents` minus its per-part discounted net — multiplied by its `qty`; and `quoted_total_cents`, the order-level quoted total — the sum over lines of `line_total_cents` multiplied by `qty` — which is the figure the customer credit check uses at acceptance.

### 3.4. Submission, Revision, Expiry, and Acceptance

Once PRICED, an `Estimator` submits the quote. Submission requires the quote to be in PRICED status — otherwise `ERR_QUOTE_NOT_PRICED` — and the owning customer to be ACTIVE, with suspension surfacing as `ERR_CUSTOMER_SUSPENDED`. The transition stamps `submitted_at` from the logical clock, sets `expires_at` to fourteen days after `submitted_at`, moves the quote to SUBMITTED, and appends a QUOTE_SUBMITTED audit event. A SUBMITTED quote is a live commercial offer with a fourteen-day validity window.

Revision is a deliberate loop back: an `Estimator` may return a SUBMITTED quote to DRAFT — any other source state is `ERR_QUOTE_NOT_OPEN`. Revision increments `revision_count` by one, moves every line back to ESTIMATED so stale prices are discarded wholesale, clears `submitted_at` and `expires_at`, and appends a QUOTE_REVISED audit event. The quote can then be edited and re-priced through the same pipeline.

Quotes that are never acted on expire. A lazy sweep runs as part of quote list and detail retrieval and of logical-clock advancement: every quote still SUBMITTED whose `expires_at` is at or before the logical clock moves to EXPIRED, its lines move to SUPERSEDED, and each expired quote appends a QUOTE_EXPIRED audit event. The sweep processes overdue quotes in `expires_at` ascending order, breaking ties by `created_at` ascending. A `CustomerRep` may instead reject a SUBMITTED quote outright — other source states are `ERR_QUOTE_NOT_OPEN` — which moves the quote to REJECTED, supersedes all of its lines, and appends a QUOTE_REJECTED audit event. ACCEPTED, EXPIRED, and REJECTED are terminal quote states.

Acceptance by a `CustomerRep` is the pivotal act that converts a SUBMITTED quote into a fabrication order, and its guards run in the cascade order of §2.9: the quote must be SUBMITTED (`ERR_QUOTE_NOT_OPEN`), the owning customer must be ACTIVE — suspension surfacing as `ERR_CUSTOMER_SUSPENDED` — the logical clock must be strictly earlier than `expires_at` (`ERR_QUOTE_EXPIRED`), machine capacity must absorb the new routing (`ERR_NO_MACHINE_CAPACITY`), the nest must be feasible (`ERR_NEST_INFEASIBLE`), and only then the fiscal check applies — the sum of `quoted_total_cents` over the customer's quotes that already have accepted orders, plus this quote's `quoted_total_cents`, must not exceed the customer's `credit_limit_cents`, or the acceptance is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

A successful acceptance fires a single atomic cascade. The system creates a fabrication order in NESTING status with `payment_status` UNPAID, denormalizing `customer_id` and snapshotting the quote's `expedite_tier`; the order references its quote through `quote_id` one-to-one. The nesting engine of §3.5 runs: it creates nest-sheet rows, consumes stock, creates remnant rows where eligible, and sets the order's `total_plate_area_cm2`; if no nest is feasible the acceptance fails atomically with `ERR_NEST_INFEASIBLE` and no partial nest persists, and if no ACTIVE machine of a required station can absorb the work it fails with `ERR_NO_MACHINE_CAPACITY`. Committed totals are then recomputed under the committed variant, and the routing chain of §3.6 is generated with machine selection and capacity reservation. The quote moves to ACCEPTED, and two audit events are appended: QUOTE_ACCEPTED and ORDER_CREATED. The response carries the newly created order.

### 3.5. Nesting, Sheet Yield, and Committed Totals

Acceptance runs the nesting engine, and a `ProductionPlanner` may re-run it while an order is still in NESTING or NESTED — re-nesting from any other status is rejected with `ERR_INVALID_STATE`. The engine expands every line into `qty` part rectangles of the line's bounding-box dimensions; the three-millimeter cutting kerf between parts is not modeled per part, having been absorbed into the fixed per-sheet kerf allowance. Stock selection considers only sheet-stock rows in AVAILABLE status whose grade and thickness match the line and whose width and height can hold the part's bounding-box width and height — parts are never rotated — and both FULL_SHEET and REMNANT kinds are eligible. Remnants are preferred over full sheets; within a kind the smallest area goes first, ties break by earliest `created_at`, and the stock `id` is never used as a tiebreaker. A consumed sheet serves exactly one line: parts of different lines never share a sheet, and a sheet already taken by an earlier line is skipped.

Packing is a guillotine grid on each sheet. The column count is the whole number of part widths that fit across the sheet width, and the row count is the whole number of part heights that fit down the sheet height; parts are placed row-major from the origin, overflow spills to the next selected sheet, and the count of sheets used grows accordingly. Each consumed sheet yields a nest-sheet row: `sheet_index` is the zero-based sheet number within the order's nest, `sheet_stock_id` identifies the stock unit consumed, `chargeable_area_cm2` is the sum of the areas of the parts placed on it, `kerf_allowance_cm2` is a fixed 5,000-square-centimeter skeleton and kerf allowance charged per sheet, `plate_in_area_cm2` is the sum of those two, and `yield_pct` is the chargeable area divided by the plate-in area, rounded half-up to four decimal places.

Remnant generation weighs two candidate offcuts per sheet: a right strip spanning the unused width at the full sheet height, and a top strip spanning the used width at the remaining height. The larger-area candidate wins, and a tie goes to the right strip. When the winning remnant's area is at least 2,000 square centimeters, a new sheet-stock row of kind REMNANT is created in AVAILABLE status with its `source_order_id` pointing at the order, and the nest sheet's `remnant_stock_id` links to it; otherwise the offcut is scrapped without creating any row. The order's `total_plate_area_cm2` is the sum of `plate_in_area_cm2` across its nest sheets, rounded half-up to a whole square centimeter and stored as an integer. Feasibility is enforced atomically: if no eligible stock row can hold the largest part, or the full-sheet and remnant pools together cannot fit every part, the operation is rejected with `ERR_NEST_INFEASIBLE` and no partial nest persists.

Once at least one nest sheet exists, the order leaves NESTING for NESTED and its committed totals are computed. The committed variant recomputes each line's cut, bend, and finish exactly as the pricing pipeline did, then replaces the material figure: the plate cost is computed per grade — the sum of `plate_in_area_cm2` over that grade's nest sheets multiplied by the grade's `material_cost_cents_per_cm2`, rounded half-up to integer cents — and allocated back to that grade's lines in proportion to each line's total part area (its per-part area times `qty`) using largest-remainder apportionment, lines ranked by area descending, ties broken by earlier line `created_at`, with each line's allocated cents then divided by its `qty` and rounded half-up to produce the per-part material figure. The per-line base, quantity discount, and expedite multiplier are then rebuilt in the same pinned order as the pricing pipeline. The committed figure is usually lower per part than the quoted estimate, because real nesting shares sheets and drops the per-part minimum billable area. The order's `committed_subtotal_cents` is the sum over lines of `line_base_cents` times `qty`, and `committed_total_cents` is the sum over lines of `line_total_cents` times `qty`. When `committed_total_cents` exceeds the quote's `quoted_total_cents`, the shop absorbs the difference — the customer is still invoiced at `quoted_total_cents`, while the committed figure stands as the cost-accounting number; both are persisted, and their delta is the nesting-loss metric.

Re-nesting is a self-loop rebuild available while the order is in NESTING or NESTED: the existing nest-sheet rows are discarded, their stock is released and re-selected — the order's own consumed sheets re-enter the eligible pool, the remnant rows the old nest generated are scrapped and never re-selected, and the capacity re-validation excludes the order's own existing reservations — a fresh nest is built, the committed totals are recomputed, and an ORDER_RENESTED audit event is appended. Cancelling an order — permitted only while it is in NESTING or NESTED, otherwise `ERR_ORDER_NOT_CANCELLABLE` — deletes all of its nest-sheet rows, restores its consumed sheets to AVAILABLE, moves the remnant rows its nest generated to SCRAPPED, zeroes the committed totals and `total_plate_area_cm2`, and releases its capacity reservations — the cancelled order's routing steps remain in place in their current status but no longer count toward any machine's booked load — and appends an ORDER_CANCELLED audit event.

### 3.6. Routing, Machine Capacity, and the Dispatch Chain

Acceptance also generates the order's routing chain. The station sequence is the union of the lines' requirements in a fixed order: LASER always comes first, then BRAKE when any line has a positive `bend_count`, then WELD when any line has positive `weld_inches`, then OUTSIDE_VENDOR when any line's `finish` is PLATING or ANODIZING, then POWDER when any line's `finish` is POWDER — in-house powder always runs last. One routing step is created per station present, at order level rather than per line, with `seq` numbering the steps contiguously from 1, and each step starts in PENDING status. Steps at OUTSIDE_VENDOR carry a `vendor_id` and no `machine_id` — the vendor chosen by the §3.3 selection rule across the outside processes the order's lines require — and in-house steps carry a `machine_id` and no `vendor_id`.

Reserved minutes, stored as `planned_minutes`, are computed per station. LASER reserves the total billed cut seconds across all parts — each line's `billed_cut_seconds` multiplied by its `qty` and summed — divided by sixty and rounded up, plus five load minutes per sheet used. BRAKE reserves three minutes per bend unit across all lines. WELD reserves four minutes per weld inch across all parts, rounded up to a whole minute. POWDER reserves a thirty-minute base plus one minute per five hundred square centimeters of total part area across all parts, that quotient rounded up. OUTSIDE_VENDOR reserves zero in-house minutes; its cost is vendor lead time, not machine capacity.

Machine selection applies to each in-house step. Eligible machines are those whose `station` matches the step's station and whose `status` is ACTIVE. The selector picks the machine with the least booked minutes in the rolling horizon and breaks ties by earliest machine `created_at`; an empty pool rejects the acceptance with `ERR_NO_MACHINE_CAPACITY`. The due-date chain starts at the first step, whose `due_date` is the acceptance time plus the tier service level — five calendar days for STANDARD, three for EXPEDITE, one for RUSH; every generated step, including the OUTSIDE_VENDOR step, initially carries that same due instant, though the outside step's `due_date` is reset at send time as §3.7 describes. The order's own `due_date` is the latest due across its routing steps, extended by the plating vendor's lead time while the order is AWAITING_OUTSIDE.

Capacity accounting runs over a rolling horizon of twelve calendar days measured from the logical clock. A machine's booked load is the sum of `planned_minutes` over its routing steps in PENDING or IN_PROGRESS status whose `due_date` falls inside the window from now through the end of the horizon. A machine's capacity over the horizon is its `shift_minutes_per_day` multiplied by twelve. A candidate machine can absorb a step only while its booked load plus the step's `planned_minutes` stays within ninety percent of capacity: a machine landing exactly at that cap remains feasible, while one minute over is not. Equivalently, a step's occupancy window — from its `due_date` minus its `planned_minutes` up to its `due_date` — must never push the machine past the ninety-percent utilization cap within the horizon. When no ACTIVE machine of a required station qualifies, the operation is rejected with `ERR_NO_MACHINE_CAPACITY`. This accounting runs at routing generation, releases a step's minutes when the step completes or is skipped, re-reserves them on rework resets, and re-validates on resume and re-nest.

Release to the floor is a `ProductionPlanner` act on a NESTED order — any other status is `ERR_ORDER_NOT_RELEASEABLE` — and it requires every routing step's machine to be ACTIVE, with a DOWN machine surfacing as `ERR_MACHINE_DOWN`. Release moves the order to IN_PRODUCTION, moves the first step (sequence 1) to IN_PROGRESS, and appends an ORDER_RELEASED audit event. Routing is strictly serial from then on: a step may enter IN_PROGRESS only when every lower-sequence step of the same order is COMPLETED or SKIPPED.

A `MachineOperator` completes the step they are running; completing a step that is not IN_PROGRESS is rejected with `ERR_STEP_NOT_IN_PROGRESS`. Completion records the caller's `X-User-ID` as the step's `completing_operator_id` — the value that drives segregation of duties at inspection — releases the step's `planned_minutes` from the machine's booked load, advances the chain, and appends a STEP_COMPLETED audit event. Advancement moves the next PENDING step to IN_PROGRESS; when that next step is the OUTSIDE_VENDOR step the order moves to AWAITING_OUTSIDE as §3.7 describes, and when no steps remain the order moves to INSPECTION. A `ProductionPlanner` may instead skip a step that is IN_PROGRESS, releasing its minutes and firing the same advancement — but cutting is never skippable, so skipping a LASER step is rejected with `ERR_STEP_NOT_SKIPPABLE`, and skipping a step not in progress is `ERR_STEP_NOT_IN_PROGRESS` — the not-in-progress check runs first, so skipping a PENDING LASER step surfaces `ERR_STEP_NOT_IN_PROGRESS`. A skipped step lands in SKIPPED, one of the two terminal step states alongside COMPLETED, and a STEP_SKIPPED audit event is appended.

Two order transitions ride on the advancement logic. When the chain advances into the POWDER step, the order moves from IN_PRODUCTION to FINISHING and the POWDER step starts. When no PENDING step remains — every routing step of the order COMPLETED or SKIPPED — the order moves directly to INSPECTION from its current status and appends an ORDER_READY_FOR_INSPECTION audit event.

A `ProductionPlanner` can park an order that is in IN_PRODUCTION, AWAITING_OUTSIDE, or FINISHING — any other status is rejected with `ERR_ORDER_NOT_HOLDABLE` — by supplying a `hold_reason` of CAPACITY or VENDOR_DELAY, which is recorded on the order as it moves to ON_HOLD; an ORDER_HELD audit event is appended. Resuming requires the order to be ON_HOLD (`ERR_ORDER_NOT_ON_HOLD` otherwise) and returns the order to the lifecycle status recorded in its last audit event before ORDER_HELD — one of the three holdable states — after re-validating capacity for every PENDING or IN_PROGRESS step, reassigning machines per the selector where the balance of load has shifted — if no ACTIVE machine can absorb a step, the resume is rejected with `ERR_NO_MACHINE_CAPACITY` (HTTP 409), the original machine assignments are restored, and the order remains ON_HOLD; a successful resume clears `hold_reason`, and an ORDER_RESUMED audit event closes the loop.

### 3.7. The Outside Vendor Loop

When the last in-house step before an outside finish completes and a PENDING OUTSIDE_VENDOR step exists, the order moves itself from IN_PRODUCTION to AWAITING_OUTSIDE: the outside step goes to IN_PROGRESS, its `due_date` is set to the send time — the logical clock at that moment — plus the vendor's `lead_time_days`, halved and rounded up to a whole day when the order's expedite tier is RUSH, and an ORDER_SENT_OUTSIDE audit event is appended. While the order waits, its order-level `due_date` reflects the vendor lead time as §3.6 describes.

Receiving the parts back is a `ProductionPlanner` act with a temporal guard. The order must be in AWAITING_OUTSIDE — otherwise `ERR_ORDER_NOT_AWAITING_OUTSIDE` — and the logical clock must be at or past the outside step's `due_date`; an early receive is rejected with `ERR_VENDOR_LEAD_TIME_NOT_ELAPSED`. A successful receive moves the outside step to COMPLETED, starts the next in-house step if one remains (the POWDER step of a plated-and-powdered order, for instance) or moves the order directly to INSPECTION when none does (appending the ORDER_READY_FOR_INSPECTION audit event), transitions the order from AWAITING_OUTSIDE to FINISHING, and appends an ORDER_RECEIVED_OUTSIDE audit event.

### 3.8. First-Piece Inspection and the Rework Loop

Every order ends its production journey at a first-piece inspection performed by a `QCInspector`, allowed only while the order is in INSPECTION status — otherwise `ERR_ORDER_NOT_IN_INSPECTION`. The report carries the measured `flatness_deviation_mm`, the `measured_diagonal_mm` reference diagonal for the flatness percentage, and a `dimensional_pass` flag declaring whether critical dimensions are in tolerance. `measured_diagonal_mm` must be a positive integer; a non-positive value is rejected with `ERR_INVALID_REQUEST` (HTTP 400), a check evaluated after the segregation-of-duties guard below. The submitting inspector's `X-User-ID` is recorded as `inspector_id`, and segregation of duties is enforced: the inspector must differ from the operator recorded as `completing_operator_id` on the order's last completed routing step, or the submission is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This safety check runs before the flatness guard.

The result is computed, never asserted. The flatness percentage is `flatness_deviation_mm` divided by `measured_diagonal_mm`, compared as an exact ratio without rounding; the report's `result` is PASS if and only if that ratio is at most 0.0015 — one-and-a-half tenths of a percent — and `dimensional_pass` is true. The boundary is inclusive: a ratio of exactly 0.0015 passes, and anything strictly greater fails. A report whose payload claims a pass while the computed result is FAIL is rejected with `ERR_FLATNESS_EXCEEDED` (HTTP 422); a computed failure cannot be overridden by declaration.

A passing report completes the order: the order moves from INSPECTION to COMPLETED, `completed_at` is stamped from the logical clock, and an ORDER_COMPLETED audit event is appended. COMPLETED is terminal for the lifecycle. A failing report starts the rework loop instead: every COMPLETED routing step of the order resets from COMPLETED back to PENDING (SKIPPED steps are untouched), their reserved minutes are re-booked on the same machines through capacity booking — capacity is re-validated before anything is reset, and a machine that cannot absorb the re-booking rejects the submission with `ERR_NO_MACHINE_CAPACITY` (HTTP 409) — the order returns to IN_PRODUCTION with the lowest-sequence reset step immediately re-entering IN_PROGRESS, and an INSPECTION_FAIL_REWORK audit event is appended — the order then works its way back through the serial chain toward a fresh inspection. Inspection reports accumulate on the order and are listable per order; each report is immutable once created.

### 3.9. Payment and Scrap Credit Redemption

Payment is a `CustomerRep` act on a COMPLETED order, and it lives on a parallel dimension: the order's lifecycle status stays COMPLETED while its `payment_status` moves from UNPAID to PAID. Paying an order whose lifecycle is not COMPLETED is rejected with `ERR_INVALID_STATE`; paying one already PAID is rejected with `ERR_ALREADY_PAID`. The payment may optionally carry `scrap_credit_to_apply_cents`, a non-negative amount the customer wishes to draw from their scrap-credit balance — a negative amount is rejected with `ERR_INVALID_REQUEST` (HTTP 400), a check evaluated after the state guards above; requesting more than the customer's `scrap_credit_balance_cents` is rejected with `ERR_INSUFFICIENT_SCRAP_CREDIT` (HTTP 402).

The applied amount is the smallest of the requested amount, the customer's balance, and the order's `committed_total_cents`. The draw drains the customer's POSTED credit rows in first-in-first-out order by `created_at` ascending — never by `id`: whole rows are consumed while the remaining amount covers a row's full `credit_cents`, and the final partially consumed row is split — the original row becomes APPLIED carrying only the consumed portion, its `credit_cents` reduced to the consumed amount and its `credited_area_cm2` scaled to the consumed share of the row's original credit and rounded half-up to one decimal place, while a newly created VOID replacement row — referencing the same `sheet_stock_id` — carries the unconsumed remainder of both figures (the original `credit_cents` minus the consumed amount, and the original `credited_area_cm2` minus the applied row's area). The order's `scrap_credit_applied_cents` records exactly the applied amount, the customer's `scrap_credit_balance_cents` is debited by exactly that amount — so the sum of the APPLIED rows plus the remainder VOID row always equals the original POSTED total — `payment_status` moves to PAID, `paid_at` is stamped from the logical clock, and an ORDER_PAID audit event is appended. The invoice figure itself remains `quoted_total_cents`; the credit offsets what the customer actually tenders against it.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — including quote acceptance, which creates the fabrication order, and inspection-report submission — return a `201 Created` status code. Operations that modify an existing resource, and all list and detail reads, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fab/_clock/set_current_utc` | Set the server logical clock | ShopManager |
| POST | `/fab/customers` | Register a customer | ShopManager |
| GET | `/fab/customers` | List customers | ShopManager, Estimator, ProductionPlanner, InventoryClerk, CustomerRep |
| GET | `/fab/customers/{id}` | Get a customer | ShopManager, Estimator, ProductionPlanner, InventoryClerk, CustomerRep |
| POST | `/fab/customers/{id}/suspend` | Suspend a customer | ShopManager |
| POST | `/fab/material-grades` | Define a material grade with gauge tiers | ShopManager |
| GET | `/fab/material-grades` | List material grades | ShopManager, Estimator, ProductionPlanner, InventoryClerk, MachineOperator, CustomerRep |
| GET | `/fab/material-grades/{id}` | Get a material grade | ShopManager, Estimator, ProductionPlanner, InventoryClerk, MachineOperator, CustomerRep |
| POST | `/fab/sheet-stock` | Receive a full sheet or register walk-in stock | InventoryClerk |
| GET | `/fab/sheet-stock` | List and filter sheet stock | ShopManager, Estimator, ProductionPlanner, InventoryClerk |
| GET | `/fab/sheet-stock/{id}` | Get one stock row | ShopManager, Estimator, ProductionPlanner, InventoryClerk |
| POST | `/fab/sheet-stock/{id}/scrap` | Scrap an AVAILABLE stock row | InventoryClerk |
| POST | `/fab/machines` | Register a machine | ShopManager |
| GET | `/fab/machines` | List machines | ShopManager, Estimator, ProductionPlanner, MachineOperator |
| GET | `/fab/machines/{id}` | Get a machine | ShopManager, Estimator, ProductionPlanner, MachineOperator |
| GET | `/fab/machines/{id}/routing-steps` | List routing steps assigned to a machine (work queue) | ShopManager, ProductionPlanner, MachineOperator |
| POST | `/fab/machines/{id}/status` | Set a machine ACTIVE or DOWN | ShopManager |
| POST | `/fab/outside-vendors` | Register an outside plating or anodizing vendor | ShopManager |
| GET | `/fab/outside-vendors` | List outside vendors | ShopManager, Estimator, ProductionPlanner |
| GET | `/fab/outside-vendors/{id}` | Get an outside vendor | ShopManager, Estimator, ProductionPlanner |
| GET | `/fab/outside-vendors/{id}/routing-steps` | List routing steps assigned to an outside vendor | ShopManager, ProductionPlanner |
| POST | `/fab/quotes` | Create a DRAFT quote, optionally with initial lines | Estimator |
| GET | `/fab/quotes` | List quotes | ShopManager, Estimator, ProductionPlanner, CustomerRep |
| GET | `/fab/quotes/{id}` | Get a quote | ShopManager, Estimator, ProductionPlanner, CustomerRep |
| POST | `/fab/quotes/{id}/lines` | Add a line to a DRAFT quote | Estimator |
| GET | `/fab/quotes/{id}/lines` | List the lines of a quote | ShopManager, Estimator, ProductionPlanner, CustomerRep |
| GET | `/fab/quote-lines/{id}` | Get one quote line | ShopManager, Estimator, ProductionPlanner, CustomerRep |
| GET | `/fab/quote-lines` | Filtered list of quote lines | ShopManager, Estimator, ProductionPlanner, CustomerRep |
| POST | `/fab/quotes/{id}/price` | Price all lines (OCC-guarded) | Estimator |
| POST | `/fab/quotes/{id}/submit` | Submit a PRICED quote | Estimator |
| POST | `/fab/quotes/{id}/revise` | Return a SUBMITTED quote to DRAFT | Estimator |
| POST | `/fab/quotes/{id}/accept` | Accept a SUBMITTED quote; runs nesting, commit totals, routing, capacity | CustomerRep |
| POST | `/fab/quotes/{id}/reject` | Reject a SUBMITTED quote | CustomerRep |
| GET | `/fab/orders` | List fabrication orders | ShopManager, Estimator, ProductionPlanner, MachineOperator, CustomerRep |
| GET | `/fab/orders/{id}` | Get a fabrication order | ShopManager, Estimator, ProductionPlanner, MachineOperator, CustomerRep |
| POST | `/fab/orders/{id}/renest` | Re-run nesting while an order is NESTING or NESTED | ProductionPlanner |
| POST | `/fab/orders/{id}/release` | Release a NESTED order to production | ProductionPlanner |
| POST | `/fab/orders/{id}/receive-outside` | Receive parts back from an outside vendor after lead time | ProductionPlanner |
| POST | `/fab/orders/{id}/hold` | Place an in-flight order ON_HOLD | ProductionPlanner |
| POST | `/fab/orders/{id}/resume` | Resume an ON_HOLD order to its pre-hold status | ProductionPlanner |
| POST | `/fab/orders/{id}/cancel` | Cancel a NESTING or NESTED order and release its nest | ProductionPlanner |
| POST | `/fab/orders/{id}/inspection-reports` | Submit first-piece inspection (PASS completes, FAIL reworks) | QCInspector |
| GET | `/fab/orders/{id}/inspection-reports` | List inspection reports for an order | ShopManager, ProductionPlanner, QCInspector |
| POST | `/fab/orders/{id}/payment` | Pay a COMPLETED order, optionally drawing scrap credit | CustomerRep |
| GET | `/fab/orders/{id}/nest-sheets` | List the nest sheets of an order | ShopManager, Estimator, ProductionPlanner |
| GET | `/fab/nest-sheets` | Filtered list of nest sheets across orders | ShopManager, Estimator, ProductionPlanner |
| GET | `/fab/nest-sheets/{id}` | Get one nest sheet | ShopManager, Estimator, ProductionPlanner |
| GET | `/fab/orders/{id}/routing-steps` | List the routing steps of an order | ShopManager, ProductionPlanner, MachineOperator, QCInspector |
| GET | `/fab/routing-steps` | Filtered list of routing steps | ShopManager, ProductionPlanner, MachineOperator |
| POST | `/fab/routing-steps/{id}/complete` | Complete an IN_PROGRESS step; advances routing and may move the order | MachineOperator |
| POST | `/fab/routing-steps/{id}/skip` | Skip a non-LASER IN_PROGRESS step | ProductionPlanner |
| POST | `/fab/scrap-credits` | Post a scrap credit from a remnant surrender or drop-off | InventoryClerk |
| GET | `/fab/scrap-credits` | List scrap credits | ShopManager, InventoryClerk, CustomerRep |
| GET | `/fab/scrap-credits/{id}` | Get a scrap credit | ShopManager, InventoryClerk, CustomerRep |
| POST | `/fab/scrap-credits/{id}/void` | Void a POSTED credit (OCC on customer version) | ShopManager |
| GET | `/fab/audit-events` | List audit events | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_NOT_OPEN` | 409 Conflict |
| `ERR_QUOTE_EMPTY` | 409 Conflict |
| `ERR_QUOTE_NOT_PRICED` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_INVALID_LINE_SPEC` | 422 Unprocessable Entity |
| `ERR_THICKNESS_TIER_UNRESOLVED` | 422 Unprocessable Entity |
| `ERR_FINISH_NOT_COMPATIBLE` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_NEST_INFEASIBLE` | 409 Conflict |
| `ERR_NO_MACHINE_CAPACITY` | 409 Conflict |
| `ERR_MACHINE_DOWN` | 409 Conflict |
| `ERR_ORDER_NOT_RELEASEABLE` | 409 Conflict |
| `ERR_ORDER_NOT_AWAITING_OUTSIDE` | 409 Conflict |
| `ERR_VENDOR_LEAD_TIME_NOT_ELAPSED` | 409 Conflict |
| `ERR_ORDER_NOT_HOLDABLE` | 409 Conflict |
| `ERR_ORDER_NOT_ON_HOLD` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_IN_INSPECTION` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_FLATNESS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STEP_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_STEP_NOT_SKIPPABLE` | 409 Conflict |
| `ERR_ALREADY_PAID` | 409 Conflict |
| `ERR_INSUFFICIENT_SCRAP_CREDIT` | 402 Payment Required |
| `ERR_SCRAP_SOURCE_INVALID` | 422 Unprocessable Entity |
| `ERR_CREDIT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_STOCK_NOT_AVAILABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
