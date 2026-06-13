# Custom Apparel Screen Print API — Product Requirements Document

## 1. Introduction

Custom apparel shops live at the intersection of two stubborn realities: a decorated garment is priced before it is ever printed, and the physical blanks it will be printed on are a finite, perishable resource that must be set aside the moment a job is committed. This API models a screen-print and embroidery shop that prices, schedules, and produces decorated apparel while keeping its blank inventory honest at every step. A shop maintains a catalog of garment styles, the blank stock behind each style, the decoration methods it offers (silk-screen presses and embroidery stations), and the customers it serves. On top of that catalog it runs an order lifecycle that moves a job from a rough quote through artwork approval, blank reservation, machine scheduling, production, and final billing.

The system's central tension is that a quote is *forward-looking* — it prices the units a customer asked for — while a final invoice is *consumption-based*, billing only the blanks a production run actually drew from stock. Between those two numbers sit quantity-tier pricing, per-screen and per-design setup charges, rush surcharges keyed to a configurable ship-date window, and a misprint allowance that deliberately reserves more blanks than the customer ordered so that spoilage on press does not short the job. The API must reconcile all of this against a strict inventory invariant: across a confirm-then-cancel cycle, not a single blank unit may be created or destroyed. The sections that follow specify the global contracts every endpoint shares, then the business logic that governs each stage of the order's journey.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malforming either header is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. The system recognizes four roles, spelled exactly as follows: `ShopManager`, `ArtStaff`, `Customer`, and `System`. When a role is syntactically valid but not permitted to perform the requested operation — or when an acting `Customer` attempts to touch an order they do not own — the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The three human roles map to identity differently, and that mapping governs ownership checks. When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds for `ArtStaff`: its `X-User-ID` is an opaque identifier the server does not resolve to a stored record. `System` is likewise opaque — it is the automation actor that performs cascade-driven transitions (voiding proofs on cancellation, fulfilling an order when a run completes, releasing or consuming reservations) and never corresponds to a persisted `id`. By contrast, when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A `Customer` may therefore act only on orders whose `customer_id` equals their own `X-User-ID`, and any attempt to approve a proof, request changes, pay an invoice, or cancel another customer's order is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response carries the pagination bookkeeping inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Lifecycle Bookkeeping

Every primary resource is assigned a server-minted `id`, formatted as a UUID with no type prefix, and an `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All entities in this system are versioned resources: in addition to `id` and `created_at`, each carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and a `version` integer that begins at its creation value and increments by one on each mutation. There are no immutable-on-creation entities here; `updated_at` and `version` are present on Shop, Customer, DecorationMethod, GarmentStyle, BlankSku, Press, EmbroideryStation, Order, OrderLine, ArtProof, BlankReservation, Quote, and ProductionRun alike.

Whenever the server derives a value as a side effect — refreshing a `BlankSku`'s stock counters, advancing an `Order`'s status, or recomputing a `Customer`'s outstanding balance — that derivation is itself a mutation of the affected resource. It refreshes that resource's `updated_at` and increments its `version`. Cascades that touch several resources at once (described throughout §3) bump each touched resource independently.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed as children of an order or a style — proofs, lines, reservations, production runs, and blank SKUs all live beneath a parent in their URL. When a path names more than one resource identifier, the server validates them left to right and rejects the request with `ERR_NOT_FOUND` at the *first* identifier that does not resolve to an existing resource within the shop. A request for a proof beneath a non-existent order fails on the order before the proof is ever consulted. The same left-to-right precedence applies to creation and mutation endpoints: the parent must exist before any child-level rule is evaluated.

Every entity beneath a shop carries that shop's identity as `shop_id`, and the collection-list endpoints expose this lineage as filters: customers, decoration methods, garment styles, presses, and embroidery stations can each be narrowed by `shop_id`; lines, proofs, reservations, and production runs can be narrowed by their parent `order_id`; and reservations can additionally be narrowed by the `blank_sku_id` of the blank they hold against. These filters reach the same records that the nested sub-resource paths reach; they are alternate read paths over the same foreign-key links the workflows below establish.

### 2.6. Monetary and Quantity Precision

All money in this system is carried as integer cents — there are no fractional cents and no floating-point money fields. Where a rule multiplies or sums cents, the result is an integer; where a rule scales cents by a percentage (the rush surcharge, the deposit), the product is rounded **up** to the next whole cent using the ceiling function. Quantities are likewise integers: the misprint allowance, which scales an ordered quantity by a spoilage fraction, is rounded **up** to the next whole unit. No monetary or quantity calculation in this specification ever rounds to the nearest value or truncates downward unless the formula explicitly floors it (only the rush-window day count is floored).

### 2.7. The Test-Driving Clock

The shop carries a logical server clock, `current_utc`, used for every rush-window and lead-time computation. A new shop's `current_utc` begins at the Unix epoch, `1970-01-01T00:00:00.000Z`, and never advances on its own. The only way it moves is through an administrative test-driving capability that sets it to a supplied instant; that operation overwrites `current_utc` with the provided `to_iso8601` value and is restricted to a `ShopManager`. All rush determinations read this field rather than wall-clock time.

### 2.8. Blank Inventory Conservation

Blank garments are the system's conserved resource, and their accounting is exact. Each `BlankSku` tracks three quantities: `total_stock_qty`, the immutable conserved total set at creation; `on_hand_qty`, the unreserved units available to source new reservations; and `reserved_qty`, the units currently held by `ACTIVE` reservations across all orders. At creation `on_hand_qty` equals `total_stock_qty` and `reserved_qty` is 0. The governing invariant is that for every `BlankSku`, `on_hand_qty` plus the sum of `reserved_qty` over its `ACTIVE` reservations always equals `total_stock_qty`. This equality must hold before a confirm, after a confirm moves units from on-hand to reserved, and after a cancel moves them back — zero drift in blank units across the reserve-then-release compensating pair. Restocking is the one sanctioned way to grow the total: it adds `add_qty` to both `total_stock_qty` and `on_hand_qty` simultaneously, preserving the equality. Consumption at fulfillment is deliberately *outside* this invariant's scope: printed garments leave the shop, so the units a run keeps are a terminal sink, not a quantity that returns to stock.

### 2.9. Optimistic Concurrency on Proof Approval

Proof approval is the one operation guarded by optimistic concurrency control, because an order's `version` advances every time a proof is approved against it, and a second approval acting on a stale view would silently supersede the first. Accordingly, the approve-proof operation requires the client to supply `expected_order_version` carrying the `version` of the parent `Order` it last observed. If `expected_order_version` does not equal the live `version` of that `Order` at the moment the approval is processed, the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP status 412. A prior approve — or a competing proof's approve that legitimately superseded the earlier submission — will already have advanced the order's `version`, making the current approver's view stale; the OCC check reduces this to a deterministic precondition rather than an after-the-fact reconciliation. No other endpoint in this API takes a version field; approval alone carries `expected_order_version`.

### 2.10. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed priority order so that the failure a client sees is deterministic. The ordering, highest priority first, is: (1) user-context headers must be present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) the role must be permitted for the endpoint and, for owned resources, `X-User-ID` must match the resource's `Customer`, else `ERR_FORBIDDEN_FOR_ROLE`; (3) every path resource must exist within the shop, validated left-to-right, else `ERR_NOT_FOUND`; (4) the request body must be well-formed — valid enum members, positive-integer quantities, a non-empty `size_run`, and colors and sizes drawn from the style's catalog — else `ERR_INVALID_REQUEST`; (5) the target resource must be in a state from which the requested transition is allowed, else `ERR_INVALID_STATE`. Beyond these five universal tiers, individual workflows layer their own business preconditions (proof-approved, sufficient blanks, machine availability, and so on); those are described where the workflow lives in §3, and each names the specific error it raises. Authentication therefore always precedes authorization, which precedes existence, which precedes body validation, which precedes state and business rules.

## 3. Business Logic & Workflows

### 3.1. Shop Configuration, Catalog, and Customers

A `ShopManager` stands up a shop by giving it a `name`; the shop also holds the tunable knobs that drive pricing and scheduling. Four of these are configurable at creation and otherwise take documented defaults: the misprint `spoilage_pct` (default five hundredths, i.e. 0.05), the `rush_threshold_days` window (default 7), and the `rush_surcharge_pct` (default one quarter, i.e. 0.25). The shop's `current_utc` is system-managed per §2.7. Customers are created beneath a shop with a `name` and a contact `email`; the `email` must be unique among the shop's non-archived customers. A customer also carries a computed `outstanding_deposit_cents` balance (starting at 0) and an `archived` flag (starting false). Archiving a customer is a soft delete — it sets `archived` to true, after which the customer is excluded from default list results unless a caller explicitly passes `include_archived` to surface them.

Decoration methods describe *how* a garment is decorated and what that decoration costs to set up and run. A method's `method_type` is either `SCREEN_PRINT` or `EMBROIDERY`, and that choice fixes its computed `resource_kind`: a `SCREEN_PRINT` method's `resource_kind` is `PRESS`, an `EMBROIDERY` method's is `EMBROIDERY_STATION`, and the `resource_kind` selects which machine a production run for that method must book. Each method carries a `name` and four cost knobs with defaults: a per-screen `screen_fee_cents` (default 2500), a per-design `digitizing_fee_cents` (default 5000), a per-unit per-location `extra_color_run_cents` uplift charged for each ink color beyond the first on screen-print work (default 75), and a per-unit per-location `stitch_run_per_1k_cents` charged per thousand stitches on embroidery work (default 90). Screen-print pricing draws on the screen fee and the extra-color uplift; embroidery pricing draws on the digitizing fee and the per-thousand-stitch rate.

Garment styles are the catalog backbone. A style is created with a `sku_code` (unique per shop, e.g. `GIL-5000`), a `name`, a per-unit `blank_cost_cents` charged to the customer for the blank itself, and two catalog lists: `available_colors` and `available_sizes`. Every blank, line color, and line size in the system is validated against these lists. Beneath a style sit its blank SKUs — the concrete on-hand stock for a given color and size. A `BlankSku` is created with a `color` (which must be one of the parent style's `available_colors`), a `size` (one of the parent style's `available_sizes`), and an initial `total_stock_qty`; on creation `on_hand_qty` is set equal to `total_stock_qty` and `reserved_qty` to 0. A restock supplies an `add_qty` that raises both `total_stock_qty` and `on_hand_qty` by that amount.

### 3.2. Machines: Presses and Embroidery Stations

Two machine types back production. A `Press` is created with a `name` and a `teardown_buffer_min` (default 30) — the mandatory idle minutes a press needs between two runs. An `EmbroideryStation` is created with a `name` and a `head_count` (default 1), the number of concurrent runs it can host on the same window before it is oversubscribed. A run's booking window is the half-open interval from `window_start` (inclusive) to `window_end` (exclusive). On a press, a new run is rejected when its window starts within `teardown_buffer_min` minutes after a prior non-terminal run's `window_end`, or when it ends within `teardown_buffer_min` minutes before a prior run's `window_start`; that buffered-adjacency conflict raises `ERR_PRESS_WINDOW_CONFLICT`. On an embroidery station, runs may touch exactly (a gap of zero is allowed), but the count of non-terminal runs whose half-open windows overlap a new run's window may not exceed the station's `head_count`; exceeding it raises `ERR_STATION_OVERSUBSCRIBED`.

### 3.3. Composing an Order: Lines, Quantities, and Proofs

A `Customer` or a `ShopManager` opens an order against a shop by naming the buying `customer_id` and a `requested_ship_date`; the order may optionally name a `reorder_of_order_id` to mark it as a reorder of a prior job. A fresh order begins with `fulfillment_status` of `DRAFT` and `billing_status` of `UNBILLED`. While the order is in `DRAFT`, and only then, lines and proofs may be attached; an attempt to add a line or submit a proof on an order that is not `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT`.

Each `OrderLine` decorates one garment style with one method. A line names its `garment_style_id`, its `decoration_method_id`, a `color` drawn from the style's `available_colors`, the number of imprint locations `num_locations` (at least 1), and a `size_run` — a map from size to quantity such as `{S: 10, M: 30, L: 20}`. Every key in `size_run` must be one of the style's `available_sizes` and every value must be a positive integer; an empty `size_run` or any non-positive quantity is rejected as a malformed body. For screen-print lines a `num_colors` gives the ink colors per location (defaulting to 1, and ignored for embroidery); for embroidery lines a `stitch_count` gives the stitches per location (defaulting to 0, and ignored for screen print). The line's `line_qty` is computed as the sum of all the quantities in its `size_run`, and that total is the imprint quantity that selects the pricing tier.

Artwork rides alongside the lines. An `ArtProof` is created in `DRAFT` by a `ShopManager` or `ArtStaff` with a `title` and an `art_hash` — a stable fingerprint of the artwork that later lets a reorder reuse screens when it matches a prior fulfilled order's approved proof. A proof carries a `revision_round` counter that starts at 0 and a `status` that starts at `DRAFT`. `ArtStaff` submits a proof for customer review, advancing it from `DRAFT` to `SUBMITTED`; submission requires the parent order still be in `DRAFT` fulfillment, else `ERR_ORDER_NOT_DRAFT`. A `Customer` who owns the order may then either request changes, sending the proof from `SUBMITTED` to `CHANGES_REQUESTED`, or approve it. When `ArtStaff` resubmits a proof that was in `CHANGES_REQUESTED`, it returns to `SUBMITTED` and its `revision_round` increments by one — this is the cyclic revision loop, `SUBMITTED → CHANGES_REQUESTED → SUBMITTED`, and the resubmission likewise requires the order be in `DRAFT`. Approval by the owning `Customer` moves the proof from `SUBMITTED` to `APPROVED` and, as a side effect, increments the parent `Order`'s `version` by one; approval is the OCC-guarded operation of §2.9 and requires `expected_order_version` to equal the order's live `version`, failing with `ERR_STALE_ORDER_VERSION` (412) otherwise. `APPROVED` and `VOID` are the proof's terminal states; an attempt to drive a transition from a state that does not permit it fails with `ERR_INVALID_STATE`.

### 3.4. Confirming an Order: Pricing, Reservation, and Deposit

Confirmation is the hinge of the lifecycle, performed by a `ShopManager`, and it fans a single request out into pricing, inventory reservation, and a deposit charge. Several preconditions guard it, each with its own error. The order must hold at least one `OrderLine`, else `ERR_ORDER_EMPTY`. The order's `ArtProof` must be `APPROVED`, else `ERR_PROOF_NOT_APPROVED`. And for every line, the `BlankSku` matching that line's style, `color`, and size must have `on_hand_qty` of at least the ordered quantity plus its misprint allowance — that is, at least the ordered quantity plus the ceiling of the ordered quantity times the shop's `spoilage_pct` — else `ERR_BLANK_INSUFFICIENT`.

When those hold, the server computes the order's **ESTIMATE** `Quote`, the forward-looking pricing variant whose `variant` field is always `ESTIMATE`. The quote has five computed money fields. The `blank_subtotal_cents` is the sum across lines of the style's `blank_cost_cents` times that line's `line_qty`. The `decoration_subtotal_cents` is built per line and then summed, with per-line rounding pinned to happen first: for each line the system computes a per-unit-per-location run cost, multiplies it by `num_locations` to get the per-unit line cost in whole cents, multiplies that by the line's `line_qty` to get the line's integer-cent decoration cost, and only then sums those per-line products across all lines — the order is "round per line, then sum," never "sum fractional then round once." The per-unit-per-location run cost itself is tier-priced (§3.5). The `setup_subtotal_cents` collects the per-line setup charges (§3.6). The `rush_surcharge_cents` is the ceiling of `decoration_subtotal_cents` times the shop's `rush_surcharge_pct` when the order is a rush, and 0 otherwise. Finally `grand_total_cents` is the sum of `blank_subtotal_cents`, `setup_subtotal_cents`, `decoration_subtotal_cents`, and `rush_surcharge_cents`.

Whether an order is a rush is settled at confirmation and recorded on its `is_rush` flag. The rush window compares the `requested_ship_date` against the shop's `current_utc`: the system takes the whole days between the two by flooring the difference in seconds divided by 86,400, and the order `is_rush` exactly when that whole-day count is strictly less than the shop's `rush_threshold_days`. A ship date exactly `rush_threshold_days` whole days out is *not* a rush; the boundary is strict.

Confirmation then commits inventory and money. For each line it creates one `ACTIVE` `BlankReservation` recording the line's `ordered_qty`, a computed `allowance_qty` equal to the ceiling of `ordered_qty` times the shop's `spoilage_pct`, and a `reserved_qty` equal to `ordered_qty` plus `allowance_qty`. Creating each reservation mutates its `BlankSku`: `reserved_qty` on the SKU rises by the reservation's `reserved_qty` and `on_hand_qty` falls by the same amount, preserving the conservation invariant of §2.8. The reservation's own `status` starts `ACTIVE`. Confirmation sets the order's `deposit_paid_cents` to the ceiling of the quote's `grand_total_cents` times one half (0.5), adds that deposit to the owning customer's `outstanding_deposit_cents`, advances the order's `fulfillment_status` from `DRAFT` to `CONFIRMED`, and increments the order's `version` by one. The customer's `outstanding_deposit_cents` is, by construction, the sum of `deposit_paid_cents` over that customer's orders whose `fulfillment_status` is `CONFIRMED`, `IN_PRODUCTION`, or `FULFILLED`.

### 3.5. Quantity-Tier and Per-Method Run Pricing

The per-unit-per-location run cost that feeds `decoration_subtotal_cents` depends on the line's quantity and its method. The pricing tier is chosen by the line's `line_qty` as a whole — one flat per-unit rate applies to every unit on the line, not a marginal blend across tiers. A `line_qty` of 23 units or fewer is priced at 800 cents per unit per location; 24 through 71 units at 550 cents; 72 through 143 units at 400 cents; and 144 units or more at 300 cents. (Equivalently: the rate is 800 when `line_qty` is at most 23, 550 when at most 71, 400 when at most 143, and 300 beyond 143.)

For a `SCREEN_PRINT` line, the per-unit-per-location run cost is that tier rate plus the method's `extra_color_run_cents` multiplied by one fewer than `num_colors` — the first ink color is included in the tier rate and each additional color adds the uplift. For an `EMBROIDERY` line, the tier rate does not apply; instead the per-unit-per-location run cost is the method's `stitch_run_per_1k_cents` multiplied by the line's stitch count expressed in whole thousands, where the thousands are obtained by dividing `stitch_count` by 1000 and rounding up to the next whole thousand. In both methods, the per-unit line cost is then this per-unit-per-location figure multiplied by `num_locations`, and the line's decoration cost is that per-unit line cost times `line_qty`, as §3.4 pins.

### 3.6. Setup Charges and the Reorder Waiver

Setup charges cover the one-time cost of burning screens or digitizing a design, accumulated per line into `setup_subtotal_cents`. For a `SCREEN_PRINT` line the setup is `num_colors` times `num_locations` times the method's `screen_fee_cents` — one screen per ink color per location. For an `EMBROIDERY` line the setup is `num_locations` times the method's `digitizing_fee_cents` — one design digitized per location. The setup subtotal is the sum of these per-line setups.

A reorder can waive setup line by line. When the order names a `reorder_of_order_id` and the order's `APPROVED` `ArtProof`'s `art_hash` equals the referenced order's approved proof's `art_hash`, the screens or digitized design already exist and that line's setup charge is waived to zero before it is added to the subtotal. The reorder linkage is validated when the order is created: a supplied `reorder_of_order_id` must reference a `FULFILLED` order belonging to the *same* customer, else creation is rejected with `ERR_INVALID_REORDER_SOURCE`. A reorder whose artwork fingerprint does not match the prior job pays full setup like any new order.

### 3.7. Scheduling and Running Production

Once an order is `CONFIRMED`, a `ShopManager` schedules production runs against the appropriate machine. A `ProductionRun` is created against an order with a booking window `window_start` and `window_end`; for a screen-print order it names a `press_id` and for an embroidery order an `embroidery_station_id` — the order's method `resource_kind` dictates which. Scheduling is permitted only while the order's `fulfillment_status` is `CONFIRMED` or `IN_PRODUCTION`; otherwise the request is rejected with `ERR_ORDER_NOT_CONFIRMED`. The window is checked for machine availability per §3.2, raising `ERR_PRESS_WINDOW_CONFLICT` on a press or `ERR_STATION_OVERSUBSCRIBED` on a station as appropriate. A new run begins in `SCHEDULED` status; if the order was `CONFIRMED`, creating its first run advances `fulfillment_status` from `CONFIRMED` to `IN_PRODUCTION`.

Starting a scheduled run moves it from `SCHEDULED` to `RUNNING` and is also gated on the order being `CONFIRMED` or `IN_PRODUCTION` (`ERR_ORDER_NOT_CONFIRMED`). The start records `blanks_pulled`, the total reserved units drawn for the run, computed as the sum of the order's `ACTIVE` reservations' `reserved_qty` at the moment of start. If the order was still `CONFIRMED`, the start also advances it to `IN_PRODUCTION`.

Completing a running job carries the QC results: a `ShopManager` supplies `good_units`, the units that passed QC, and `spoiled_units`, the misprinted units scrapped. Completion first validates that `good_units` is at least 0, `spoiled_units` is at least 0, and their sum does not exceed `blanks_pulled`; a violation raises `ERR_INVALID_GOOD_UNITS`. It then sets `consumed_units` to `good_units` plus `spoiled_units` — the blanks actually drawn from stock for keeps — and sets `released_units` to `blanks_pulled` minus `consumed_units`, the unused allowance to be returned to stock. Completion can only fulfill the order if `good_units` reaches the total `ordered_qty` summed across the order's reservations; when `good_units` falls short of that total, the run does not change the order's state and the request is rejected with `ERR_RUN_SHORT`. When `good_units` meets or exceeds the total ordered quantity, the run moves from `RUNNING` to `COMPLETED` and cascades the order to `FULFILLED` (§3.8). A run may instead be aborted from either `SCHEDULED` or `RUNNING` to the terminal `ABORTED` status, which frees the booked machine window for that press or station so other runs may take it. `COMPLETED` and `ABORTED` are the run's terminal states.

### 3.8. Fulfillment, Cancellation, and the Stock Cascades

Fulfillment is a system-driven cascade, not a directly called transition: when a production run completes with enough good units, the order advances from `IN_PRODUCTION` to `FULFILLED`. That advance settles every `ACTIVE` `BlankReservation` on the order to `CONSUMED`, because the order was actually produced. Each `CONSUMED` transition mutates the reservation's `BlankSku`: `on_hand_qty` rises by the run's `released_units` — the leftover allowance not used by the run, equal to `blanks_pulled` minus `good_units` minus `spoiled_units` — and the SKU's `reserved_qty` falls by the reservation's held `reserved_qty`, clearing the hold. The blanks the run actually kept are gone from the shop; only the unused allowance returns to `on_hand_qty`. `RELEASED` is reserved for the cancellation path and is never used here.

Cancellation is the compensating action. A `ShopManager` or the owning `Customer` may cancel an order while its `fulfillment_status` is `DRAFT` or `CONFIRMED`; a cancel attempted from any other status is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling drives `fulfillment_status` to the terminal `CANCELLED`. From `DRAFT` there are no reservations yet, so the only cascade is that every non-terminal `ArtProof` on the order — those in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` — is voided to `VOID` by the system. From `CONFIRMED` the cascade is fuller: every `ACTIVE` `BlankReservation` is moved to `RELEASED`, and each release mutates its `BlankSku` by lowering the SKU's `reserved_qty` by the reservation's `reserved_qty` and raising `on_hand_qty` by the same amount, returning the full hold to stock; every non-terminal `ArtProof` is voided to `VOID`; the owning customer's `outstanding_deposit_cents` is decremented by the order's `deposit_paid_cents` as a compensating restoration of the conserved deposit total; and the order's `deposit_paid_cents` is reset to 0. The contrast between the two cascades is the heart of §2.8: a `RELEASED` reservation returns its entire held quantity to stock and conserves total blanks across the confirm-then-cancel pair, whereas a `CONSUMED` reservation is a terminal sink that returns only the unused allowance.

### 3.9. Billing: Invoicing on Consumption and Payment

The billing dimension evolves independently of fulfillment beyond a single gate: an order may be invoiced only after it is `FULFILLED`. A `ShopManager` invoices a fulfilled order, advancing `billing_status` from `UNBILLED` to `INVOICED`. Invoicing while the order is not yet `FULFILLED` is rejected with `ERR_ORDER_NOT_FULFILLED`; invoicing an order whose `billing_status` is not `UNBILLED` is rejected with `ERR_ALREADY_INVOICED`. Invoicing computes the **FINAL**, consumption-based total and writes it to the order's `final_total_cents`, which is null until then.

The FINAL total differs from the ESTIMATE in exactly one dimension: the blank subtotal. Where the ESTIMATE priced the blank subtotal on the reserved units, the FINAL bills the blank subtotal on the units actually consumed — `good_units` plus `spoiled_units`, capped at each reservation's `reserved_qty` — times each style's `blank_cost_cents`. The decoration subtotal and the setup subtotal are carried over unchanged from the estimate, and the rush surcharge is re-evaluated against the *same* `is_rush` captured at confirmation rather than against the clock at invoice time. Because a run that spoils fewer blanks than its allowance consumes fewer blanks than it reserved, the FINAL blank subtotal can come in below the ESTIMATE whenever spoilage is below the allowance; otherwise the two agree. This dual-variant consumption accounting is mirrored on the blank-cost side: the reserved blank cost counts each reservation's full `ACTIVE` `reserved_qty` (the ordered quantity plus its allowance), while the consumed blank cost counts only the blanks actually drawn — `good_units` plus `spoiled_units` up to `reserved_qty` — so the consumed cost is below the reserved cost precisely when spoilage stays under the allowance.

Once invoiced, the owning `Customer` pays, advancing `billing_status` from `INVOICED` to `PAID`. Payment requires the order's `billing_status` to be `INVOICED` (`ERR_NOT_INVOICED`) and the acting customer to own the order (`ERR_FORBIDDEN_FOR_ROLE`). The quote and its subtotals can be read back at any time as a computed sub-resource of the order.

## 4. Endpoint Definitions

Operations that create a new, standalone resource — a shop, a customer, a style, a blank SKU, an order, a line, a proof, or a production run — return `201 Created`. Operations that modify an existing resource, including the lifecycle transitions (confirm, cancel, invoice, pay, submit, approve, start, complete, abort, restock, archive) and the clock-setting capability, return `200 OK`. Request and response bodies are reconstructed from the workflow narratives in §3; the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server clock (test-driving) | ShopManager |
| POST | `/shops` | Create a Shop | ShopManager |
| GET | `/shops/{id}` | Get a Shop | ShopManager, ArtStaff, Customer |
| POST | `/customers` | Create a Customer | ShopManager |
| GET | `/customers/{id}` | Get a Customer | ShopManager, ArtStaff, Customer |
| POST | `/customers/{id}/archive` | Archive (soft-delete) a Customer | ShopManager |
| GET | `/customers` | List Customers | ShopManager, ArtStaff |
| POST | `/decoration-methods` | Create a DecorationMethod | ShopManager |
| GET | `/decoration-methods/{id}` | Get a DecorationMethod | ShopManager, ArtStaff, Customer |
| GET | `/decoration-methods` | List DecorationMethods | ShopManager, ArtStaff |
| POST | `/garment-styles` | Create a GarmentStyle | ShopManager |
| GET | `/garment-styles/{id}` | Get a GarmentStyle | ShopManager, ArtStaff, Customer |
| GET | `/garment-styles` | List GarmentStyles | ShopManager, ArtStaff, Customer |
| POST | `/garment-styles/{id}/blank-skus` | Create a BlankSku (initial stock) | ShopManager |
| POST | `/garment-styles/{id}/blank-skus/{id}/restock` | Add stock to a BlankSku | ShopManager |
| GET | `/garment-styles/{id}/blank-skus` | List BlankSkus for a GarmentStyle | ShopManager, ArtStaff, Customer |
| GET | `/garment-styles/{id}/blank-skus/{id}` | Get a BlankSku | ShopManager, ArtStaff, Customer |
| POST | `/presses` | Create a Press | ShopManager |
| GET | `/presses/{id}` | Get a Press | ShopManager, ArtStaff |
| GET | `/presses` | List Presses | ShopManager, ArtStaff |
| POST | `/embroidery-stations` | Create an EmbroideryStation | ShopManager |
| GET | `/embroidery-stations/{id}` | Get an EmbroideryStation | ShopManager, ArtStaff |
| GET | `/embroidery-stations` | List EmbroideryStations | ShopManager, ArtStaff |
| POST | `/orders` | Create a draft Order | ShopManager, Customer |
| GET | `/orders/{id}` | Get an Order | ShopManager, ArtStaff, Customer |
| GET | `/orders` | List Orders | ShopManager, ArtStaff, Customer |
| POST | `/orders/{id}/lines` | Add an OrderLine | ShopManager, Customer |
| GET | `/orders/{id}/lines` | List OrderLines of an Order | ShopManager, ArtStaff, Customer |
| GET | `/order-lines/{id}` | Get an OrderLine | ShopManager, ArtStaff, Customer |
| GET | `/order-lines` | List OrderLines (filtered) | ShopManager, ArtStaff, Customer |
| POST | `/orders/{id}/confirm` | Confirm an Order (price, reserve, deposit) | ShopManager |
| POST | `/orders/{id}/cancel` | Cancel an Order | ShopManager, Customer |
| POST | `/orders/{id}/invoice` | Invoice a FULFILLED Order | ShopManager |
| POST | `/orders/{id}/pay` | Pay an INVOICED Order | Customer |
| GET | `/orders/{id}/quote` | Get the Order's ESTIMATE Quote | ShopManager, ArtStaff, Customer |
| POST | `/orders/{id}/art-proofs` | Create an ArtProof | ShopManager, ArtStaff |
| GET | `/orders/{id}/art-proofs` | List ArtProofs of an Order | ShopManager, ArtStaff, Customer |
| GET | `/orders/{id}/art-proofs/{id}` | Get an ArtProof | ShopManager, ArtStaff, Customer |
| POST | `/orders/{id}/art-proofs/{id}/submit` | Submit/resubmit a proof | ArtStaff |
| POST | `/orders/{id}/art-proofs/{id}/request-changes` | Request revisions on a proof | Customer |
| POST | `/orders/{id}/art-proofs/{id}/approve` | Approve a proof (OCC) | Customer |
| GET | `/orders/{id}/reservations` | List BlankReservations of an Order | ShopManager, ArtStaff |
| GET | `/blank-reservations/{id}` | Get a BlankReservation | ShopManager, ArtStaff |
| GET | `/blank-reservations` | List BlankReservations (filtered) | ShopManager, ArtStaff |
| POST | `/orders/{id}/production-runs` | Schedule a ProductionRun | ShopManager |
| GET | `/orders/{id}/production-runs` | List ProductionRuns of an Order | ShopManager, ArtStaff |
| GET | `/production-runs/{id}` | Get a ProductionRun | ShopManager, ArtStaff |
| GET | `/production-runs` | List ProductionRuns (filtered) | ShopManager, ArtStaff |
| POST | `/orders/{id}/production-runs/{id}/start` | Start a scheduled run | ShopManager |
| POST | `/orders/{id}/production-runs/{id}/complete` | Complete a run with QC results | ShopManager |
| POST | `/orders/{id}/production-runs/{id}/abort` | Abort a run | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_PROOF_NOT_APPROVED` | 409 |
| `ERR_ORDER_EMPTY` | 409 |
| `ERR_BLANK_INSUFFICIENT` | 409 |
| `ERR_ORDER_NOT_CONFIRMED` | 409 |
| `ERR_PRESS_WINDOW_CONFLICT` | 409 |
| `ERR_STATION_OVERSUBSCRIBED` | 409 |
| `ERR_INVALID_GOOD_UNITS` | 400 |
| `ERR_RUN_SHORT` | 409 |
| `ERR_ORDER_NOT_FULFILLED` | 409 |
| `ERR_ALREADY_INVOICED` | 409 |
| `ERR_NOT_INVOICED` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_INVALID_REORDER_SOURCE` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
