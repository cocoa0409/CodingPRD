# Ice Cream Shop API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Ice Cream Shop API, the operational backbone of a frozen-dessert retail business. The shop turns bulk frozen product into scooped cones, decorated cakes, and catered events, and it must do so while keeping a precise accounting of a scarce and perishable resource: the volume of frozen dessert in each production batch. Every scoop sold, every cake baked, and every catering cart dispatched draws from the same finite batch inventory, and the system exists to make sure that draw is always accurate, ordered, and reversible.

The API governs the full commercial lifecycle of the shop. On the supply side it tracks flavors, production batches, melt-and-spillage waste, and the shrink that separates a planned loss budget from what actually melted. On the demand side it rings up point-of-sale tickets with per-scoop pricing and modifiers, takes cake pre-orders and catering bookings against reserved windows, runs a loyalty punch-card program, and closes out the cash drawer at the end of each shift with a reconciliation against physically counted cash. Because the same batch volume is competed for by walk-in orders, pre-orders, waste, and catering, the system treats inventory as a quota to be allocated in a strict, deterministic order and never double-committed.

A recurring theme throughout this specification is the distinction between two parallel views of the same number: what the shop *expected* (standard book cost, an allowance for shrink, the estimate quoted to a caterer) versus what *actually happened* (real batch costs consumed first-in-first-out, measured melt, the volume genuinely served). Both views are computed and preserved so that management can reconcile them. The remainder of this document defines the global contracts every endpoint honors (Section 2), the business workflows and their calculations (Section 3), the endpoint catalogue (Section 4), and the error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting staff member, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles: `Manager`, `ShiftLead`, `Scooper`, and `Baker`. A request that omits either header, or that carries an `X-User-Role` value outside these four, is rejected with `ERR_UNAUTHENTICATED`. A request that is authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

For all four roles, `X-User-ID` is an opaque operator identifier: it is not tied to any persisted entity and is never compared against any resource's `id`. `Manager`, `ShiftLead`, `Scooper`, and `Baker` are permission tiers only — the server does not resolve `X-User-ID` to a staff record, and ownership of a ticket, batch, or booking is never determined by who created it. Authorization is decided purely by whether the role named in `X-User-Role` is on the permitted list for the operation (see the endpoint catalogue in Section 4). Broadly, a `Manager` owns catalog and configuration, catering, pre-order pricing, and refunds; a `ShiftLead` owns the cash drawer, voids, and refunds; a `Scooper` runs the frontline point of sale; and a `Baker` owns production — batches, releases, waste, and the production transitions of cakes. Every GET (read) endpoint is available to all four roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100 by clamping any out-of-range value into that band (a `limit` below 1 becomes 1 and above 100 becomes 100). The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but cannot be parsed as an integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. List responses include the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix; the `id` is identity only and is never supplied by the client. Most resources additionally carry three system-managed fields:

- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at creation and increments by one on every mutation of the resource.

There is one deliberate exception. A `WasteEvent` is an append-only log record: once written it is never modified. It therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field. Every other entity (Flavor, SizeOption, Topping, EventCart, DecoratingStation, LoyaltyAccount, CashDrawerSession, Batch, Order, OrderLine, PreOrder, and CateringBooking) carries the full `id` / `created_at` / `updated_at` / `version` set.

Computed fields participate in versioning. When a downstream recomputation changes a resource's derived values — for example when a commit lowers a `Batch`'s `remaining_volume_ml`, or when that in turn changes the owning `Flavor`'s `stock_status` — the affected resource is itself mutated: its `updated_at` is refreshed and its `version` incremented, independently of the resource that triggered the change.

### 2.5. The Logical Clock and Time Windows

All temporal comparisons in the system — seasonal availability, pre-order production gating, and window-overlap checks — are evaluated against a single server-controlled **logical clock**, never against wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and it remains at that value until explicitly moved. An administrative test-driving capability, available to all four roles, sets the clock to a supplied `to_iso8601` instant; the clock may be advanced or rewound freely, and before any such call it never falls back to real time.

Time windows in the system are half-open intervals `[start, end)`: the start instant is included and the end instant is excluded. This applies to seasonal windows (`seasonal_start_utc` inclusive, `seasonal_end_utc` exclusive), decorating windows (`decorate_start_utc` inclusive, `decorate_end_utc` exclusive), and event windows (`event_start_utc` inclusive, `event_end_utc` exclusive). For any window whose end is required to be strictly after its start, an end at or before the start is rejected with `ERR_INVALID_TIME_WINDOW`.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents, and all volumes are integer milliliters (ml). Where a calculation produces a fractional result, it is rounded to the nearest whole unit using **round half up** (a value exactly halfway rounds away from zero to the larger magnitude). Rounding is applied at the precise point each calculation specifies, and the order of rounding versus summation is significant: tax, for instance, is rounded on each line *before* the lines are summed, not after (see Section 3.4). The per-scoop physical volume used throughout inventory math is a fixed **90 ml per scoop**.

### 2.7. Inventory Volume Accounting and Stock Status

The frozen product on hand is the system's scarcest resource, and it is tracked per production `Batch` through four volume fields that always satisfy one invariant. A batch is produced with an `initial_volume_ml` that is conserved for the life of the batch. Against it the system tracks `committed_volume_ml` (volume permanently consumed by paid tickets and settled catering), `wasted_volume_ml` (volume removed by melt, spillage, trim, or discard), and `reserved_volume_ml` (a soft hold placed by open order lines and booked catering that have not yet been paid or settled). The physical on-hand quantity, `remaining_volume_ml`, is always the initial volume minus committed minus wasted. A reservation is a claim on future volume, not a consumption: it does **not** reduce `remaining_volume_ml`. What a reservation reduces is the batch's *allocatable headroom*, defined as `remaining_volume_ml` minus `reserved_volume_ml`.

Reservations and commitments propagate up to the owning flavor. A `Flavor`'s `total_available_ml` is the sum of `remaining_volume_ml` across only that flavor's batches whose status is `AVAILABLE`. Note carefully that open-ticket reservations do **not** reduce `total_available_ml` — they only shrink per-batch headroom; the flavor's advertised on-hand quantity reflects physical volume, not soft holds. From `total_available_ml` the system derives the flavor's `stock_status` against its `par_level_ml` reorder threshold: when `total_available_ml` is exactly zero the status is `OUT_OF_STOCK`; when it is greater than zero but strictly below `par_level_ml` the status is `BELOW_PAR`; and when it is at least `par_level_ml` (equal to or greater than) the status is `IN_STOCK`. The boundary is deliberate: `total_available_ml` equal to `par_level_ml` is `IN_STOCK`, while one milliliter less is `BELOW_PAR`.

The system recomputes `total_available_ml` and `stock_status` for the owning flavor after every event that can move volume: a batch release, a paid commit, a refund uncommit, a waste log, or a discard. These recomputations are cascades, described operationally in Section 3.

### 2.8. Request Validation Order

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order, and the first failure encountered is the error returned. This ordering is a contract, because a later, more specific error must never be masked by — nor mask — an earlier, more general one. The order is:

1. **Authentication** — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for this operation, else `ERR_FORBIDDEN` (403).
3. **Existence** — every identifier referenced by the request resolves to a real resource. Path identifiers are validated left to right, then body foreign keys. The first unresolved identifier yields its specific not-found error (404), such as `ERR_FLAVOR_NOT_FOUND`, `ERR_SIZE_OPTION_NOT_FOUND`, `ERR_TOPPING_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_WASTE_EVENT_NOT_FOUND`, `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, `ERR_DRAWER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`, `ERR_EVENT_CART_NOT_FOUND`, `ERR_DECORATING_STATION_NOT_FOUND`, or `ERR_CATERING_BOOKING_NOT_FOUND`.
4. **Schema validity** — required fields present, types and enum values correct, quantities and volumes strictly positive where required; a malformed body yields `ERR_VALIDATION` (422), and a window whose end is not after its start yields `ERR_INVALID_TIME_WINDOW` (422).
5. **State legality** — the target resource is in a legal state for the operation (409); the specific code depends on the resource, e.g. `ERR_ORDER_NOT_OPEN`, `ERR_DRAWER_NOT_OPEN`, `ERR_DRAWER_ALREADY_CLOSED`, `ERR_BATCH_NOT_PREP`, `ERR_BATCH_NOT_AVAILABLE`, `ERR_PREORDER_INVALID_STATE`, `ERR_CATERING_INVALID_STATE`, or `ERR_EMPTY_ORDER`.
6. **Business rules** — the operation-specific safety, temporal, capacity, fiscal, and concurrency checks described throughout Section 3 (allergen conflict, out-of-season, availability, window overlap, batch headroom, cash tender, and stale version).

Where an existence check for a path identifier and one for a body identifier both apply, the path identifiers are resolved (in left-to-right order) before body identifiers.

### 2.9. Optimistic Concurrency Control

Re-quoting a cake pre-order is guarded by optimistic concurrency control, because two legitimately valid re-quotes issued from the same starting point would otherwise silently overwrite one another. A re-quote request must carry `expected_preorder_version`, a non-optional field holding the `version` of the target `PreOrder` that the client last observed. If `expected_preorder_version` does not equal the pre-order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's view is stale because another re-quote has already superseded the prior price and advanced the version, and honoring this request would overwrite a quote the client never saw. Only the re-quote operation takes a version field; no other endpoint requires one.

## 3. Business Logic & Workflows

### 3.1. Configuring the Menu and Shop Resources

Before any dessert is sold, a `Manager` establishes the catalog. A **Flavor** is created with a display `name` (unique among flavors) and the costing and reorder parameters that govern it: `standard_cost_cents_per_ml`, the book cost per milliliter used for standard costing, and `par_level_ml`, the reorder threshold that drives stock status. A flavor may declare an `allergens` array of tags present in its base (for example `MILK`, `EGG`, `NUTS`, `PEANUT`, `SOY`, or `GLUTEN`), defaulting to an empty list. It may be marked seasonal by setting `is_seasonal` true, in which case a `seasonal_start_utc` and `seasonal_end_utc` window is required to bound its availability. It may be marked premium by setting `is_premium` true, in which case a `premium_surcharge_cents_per_scoop` applies to every scoop of it sold. A flavor's `is_active` flag (default true) is a manager switch: an inactive flavor cannot be put into cake production (it fails the start-production availability gate of Section 3.6). The flag is not re-checked when ringing frontline POS lines, so an inactive flavor may still be added to an open ticket and sold. On creation, before any batch exists, a flavor's computed `total_available_ml` is zero and its `stock_status` is therefore `OUT_OF_STOCK`. A manager may later adjust a flavor's mutable configuration — its `par_level_ml`, `is_active`, seasonal flags and window (`is_seasonal`, `seasonal_start_utc`, `seasonal_end_utc`), and premium settings (`is_premium`, `premium_surcharge_cents_per_scoop`) — and the flavor's `stock_status` is recomputed against any new `par_level_ml`.

The manager also defines the sizes and modifiers of the menu. A **SizeOption** carries a short `code` (such as `SINGLE`, `DOUBLE`, or `KIDS`, unique among size options), a `scoop_count` of at least one, and a `base_price_cents` charged before modifiers. A **Topping** carries a `name` (unique among toppings), a flat `price_cents` add-on charged per line, and its own `allergens` array contributing to allergen labeling. The manager likewise provisions the physical resources that catering and cakes reserve: an **EventCart** with a `name` and a `capacity_ml` (the maximum total requested volume a single booking may reserve on that cart), and a **DecoratingStation** with a `name`.

Loyalty accounts may be created by a `Manager` or a `Scooper`. A **LoyaltyAccount** is keyed by a `phone` (unique among accounts) and may carry an `allergen_restrictions` array listing allergens the member must never be served. Its three counters — `punches`, `free_scoop_credits`, and `lifetime_scoops` — all start at zero and are maintained by the system as the member's tickets are paid, voided, and refunded.

### 3.2. Production: Batches, Waste, and Shrink

A `Baker` produces frozen product one **Batch** at a time. Creating a batch records its `flavor_id`, the produced `initial_volume_ml`, the `unit_cost_cents_per_ml` that this specific batch actually cost to make, a `produced_at` timestamp, and an `expiry_at` timestamp. A freshly produced batch enters the `PREP` state with `remaining_volume_ml` equal to `initial_volume_ml` and its `reserved_volume_ml`, `committed_volume_ml`, and `wasted_volume_ml` all zero. A batch in `PREP` is not yet sellable; a baker releases it, moving it from `PREP` to `AVAILABLE`, after which it becomes eligible for reservation and allocation and the owning flavor's `total_available_ml` and `stock_status` are recomputed. Releasing a batch that is not in `PREP` is rejected with `ERR_BATCH_NOT_PREP`.

When frozen product is lost, the baker logs a **WasteEvent** against a batch. Each waste event names its `batch_id`, a `waste_type` of `MELT`, `SPILLAGE`, `TRIM_SHRINK`, or `EXPIRED_DISCARD`, a `volume_ml` removed (which must be positive), and an optional free-text `reason`. Logging waste raises the batch's `wasted_volume_ml` by that volume and lowers its `remaining_volume_ml` by the same amount, after which the owning flavor's stock figures are recomputed. A non-discard waste (`MELT`, `SPILLAGE`, or `TRIM_SHRINK`) that drives an `AVAILABLE` batch's `remaining_volume_ml` to exactly zero auto-transitions that batch from `AVAILABLE` to the terminal `DEPLETED` state (a `PREP` batch is not transitioned by such waste). Waste may only be logged against a batch that is in `PREP` or `AVAILABLE`; a waste attempt on any other batch is rejected with `ERR_BATCH_NOT_AVAILABLE`. An `EXPIRED_DISCARD` is a special disposal: it is only valid when its `volume_ml` equals the batch's entire current `remaining_volume_ml` — a mismatched volume is rejected with `ERR_VALIDATION` — and it drives the batch from `PREP` or `AVAILABLE` to the terminal `DISCARDED` state with `remaining_volume_ml` driven to zero.

The shrink accounting for a batch keeps two parallel figures that management reconciles. The **allowance** figure, `expected_shrink_ml`, is the planned shrink budget: it is `initial_volume_ml` multiplied by the shrink allowance of five percent (0.05), rounded half up to a whole milliliter. The **measured** figure, `actual_shrink_ml`, is the real observed loss: it is the sum of the `volume_ml` of every waste event on the batch whose `waste_type` is one of `MELT`, `SPILLAGE`, or `TRIM_SHRINK` — note that `EXPIRED_DISCARD` volumes are deliberately excluded from measured shrink. The `shrink_variance_ml` is the measured figure minus the expected figure (`actual_shrink_ml` minus `expected_shrink_ml`); it diverges from zero whenever real loss differs from the five-percent allowance.

### 3.3. Opening a Ticket and Adding Lines

Frontline sales happen on a POS ticket. A `Scooper` or `ShiftLead` opens an **Order** against a cash drawer by supplying the `drawer_id` of the till it will ring into and, optionally, a `loyalty_account_id` for a member attached to the ticket. Opening the order validates only that the referenced drawer (and any supplied loyalty account) exists; the drawer's `OPEN` status is not checked at order-open time, and that requirement is enforced only later at payment. A new order starts with its `status` field set to `OPEN` and its `subtotal_cents`, `tax_cents`, and `total_cents` all zero. Every stateful entity — orders, batches, pre-orders, catering bookings, and drawer sessions — exposes its lifecycle position through a `status` field carrying one of the exact enumeration strings named in this section.

Lines are then added to the open ticket. An **OrderLine** names its `order_id`, a `size_option_id`, a `flavor_id`, an optional `topping_ids` array (each element identifying a topping to apply; this is a list, not a single foreign key), and an optional `quantity` of identical units defaulting to one. The line's computed `scoops` is the size option's `scoop_count` multiplied by `quantity`. The line's `line_price_cents` is assembled from four parts: a base equal to the size option's `base_price_cents` multiplied by `quantity`; a topping total equal to the sum of the `price_cents` of every topping named in `topping_ids`, multiplied by `quantity`; a seasonal surcharge equal to 40 cents per scoop applied only when the flavor's `is_seasonal` is true, and zero otherwise; and a premium surcharge equal to the flavor's `premium_surcharge_cents_per_scoop` per scoop applied only when the flavor's `is_premium` is true, and zero otherwise. The line price is the sum of those four parts (base plus topping total plus seasonal surcharge plus premium surcharge); all inputs are integer cents, so no rounding is needed. The line also computes an `allergen_label`, the union of the flavor's `allergens` and the `allergens` of every applied topping, deduplicated and returned as a list sorted in ascending (lexicographic) order.

Adding a line places a soft reservation on inventory. The line needs `scoops` multiplied by 90 ml of the chosen flavor, and that need is met by drawing across the flavor's batches first-in-first-out. The candidate batches are those of the flavor in `AVAILABLE` status whose allocatable headroom (`remaining_volume_ml` minus `reserved_volume_ml`) is positive. Candidates are consumed in order of `expiry_at` ascending — earliest expiry first — with ties broken by `created_at` ascending; batch `id` is never used for ordering. The need is drawn across candidates in that order, each contributing up to its available headroom, and the drawn volume raises each touched batch's `reserved_volume_ml`. If the combined headroom across all candidate batches is less than the needed volume, the line is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME` and nothing is reserved. The line records its per-batch draws in `allocations`, an array of entries each carrying a `batch_id`, the drawn `volume_ml`, and that batch's `unit_cost_cents_per_ml`. A newly added line is `ACTIVE`.

Two business guards apply when a line is added. First, if the ticket carries a loyalty member, the line's `allergen_label` must not intersect that account's `allergen_restrictions`; any overlap rejects the line with `ERR_ALLERGEN_RESTRICTION_CONFLICT`. Second, if the line's flavor is seasonal, the logical clock at the moment of sale must fall within the flavor's `[seasonal_start_utc, seasonal_end_utc)` window; a sale outside that window is rejected with `ERR_FLAVOR_OUT_OF_SEASON`. A line may be removed from an open ticket, which moves it from `ACTIVE` to `REMOVED` and releases its reservation by lowering each affected batch's `reserved_volume_ml`; because a reservation never touched `remaining_volume_ml`, removal leaves physical on-hand unchanged. Removal is legal only for an `ACTIVE` line on an `OPEN` order: if the owning order is not `OPEN` the removal is rejected with `ERR_ORDER_NOT_OPEN`, and if the target line resolves but is no longer `ACTIVE` (already `REMOVED` or `COMMITTED`) it is reported as `ERR_ORDER_LINE_NOT_FOUND`. Adding or removing a line recomputes the order's running totals.

### 3.4. Order Totals, Payment, and Cost of Goods

An order's totals are aggregated from its lines that are in `ACTIVE` or `COMMITTED` status (so a paid ticket's now-`COMMITTED` lines continue to count and its totals do not reset to zero, while `REMOVED` lines never contribute). Each such line's `line_tax_cents` is its `line_price_cents` multiplied by the tax rate of 0.0875, rounded half up to whole cents. The order's `subtotal_cents` is the sum of `line_price_cents` over those lines; its `tax_cents` is the sum of the already-rounded `line_tax_cents` over those lines; its `total_cents` is `subtotal_cents` plus `tax_cents`; and its `punches_earned` is the sum of `scoops` over those same lines. The rounding order is fixed and material: tax is rounded per line and *then* summed, never summed and then rounded — the two approaches yield different totals on many baskets, and only round-per-line-then-sum is correct here.

A `Scooper` or `ShiftLead` takes payment, moving the order from `OPEN` to `PAID`. Payment supplies a `payment_method` of `CASH` or `CARD` and, for cash, a `tendered_cash_cents`. Payment is refused unless the order has at least one `ACTIVE` line (`ERR_EMPTY_ORDER`) and the owning drawer is still `OPEN` (`ERR_DRAWER_NOT_OPEN`). For a cash payment, the `tendered_cash_cents` must be at least the `total_cents`; a short tender is rejected with `ERR_INSUFFICIENT_CASH_TENDERED`. On a cash payment the order records `tendered_cash_cents` and a `change_cents` equal to `tendered_cash_cents` minus `total_cents`. On a card payment neither is captured: both `tendered_cash_cents` and `change_cents` remain null.

Paying a ticket runs a three-hop commit cascade over the inventory. First, every `ACTIVE` line becomes `COMMITTED`, and for each of its allocation draws the touched batch converts the soft hold into consumption: its `reserved_volume_ml` drops by the drawn volume, its `committed_volume_ml` rises by that volume, and its `remaining_volume_ml` drops by that volume. Second, any batch whose `remaining_volume_ml` reaches zero as a result auto-transitions from `AVAILABLE` to the terminal `DEPLETED` state and is excluded from future reservations. Third, every affected flavor's `total_available_ml` and `stock_status` are recomputed, possibly falling to `OUT_OF_STOCK`.

Payment also freezes cost of goods on the ticket, in the two parallel variants the shop reconciles. For each committed line, the **standard** cost of goods, `standard_cogs_cents`, is `scoops` multiplied by 90 ml multiplied by the flavor's `standard_cost_cents_per_ml`, rounded half up to whole cents — a uniform book rate applied to the total volume. The **actual** cost of goods, `actual_cogs_cents`, is the sum over that line's `allocations` of each draw's `volume_ml` multiplied by that draw's `unit_cost_cents_per_ml`, rounded half up to whole cents — the true FIFO cost of the specific batches consumed. The order's `standard_cogs_cents` and `actual_cogs_cents` are the sums of the respective line figures; the two diverge whenever a batch's real cost differs from the flavor's book rate.

At payment the ticket also records `cash_collected_cents` — equal to `total_cents` when paid `CASH` and zero when paid `CARD` — which feeds the drawer's expected-cash figure, and it recomputes the drawer accordingly. Finally, the order's `punches_earned` is the total number of scoops on the ticket, and if the ticket carries a loyalty member those scoops are accrued to the account (see Section 3.5).

### 3.5. Loyalty Accrual, Voids, and Refunds

Loyalty accrual happens at payment for any ticket that carries a member. The scoops earned equal the order's `punches_earned`. Those scoops are added to the account's `lifetime_scoops`. They are then combined with the account's current `punches`: taking the running total of prior `punches` plus the earned scoops, the number of new `free_scoop_credits` granted is that running total divided by the punch threshold of 10, taking the whole-number quotient, and those credits are added to `free_scoop_credits`; the account's `punches` is then set to the remainder of that running total after dividing by 10. In other words `punches` always settles into the range from zero up to but not including 10, and each full group of ten scoops crossed grants exactly one credit. A running total of exactly 10 grants one credit and resets `punches` to zero.

A `ShiftLead` may **void** a ticket that is still `OPEN`, moving it from `OPEN` to `VOID`. Voiding moves every `ACTIVE` line to `REMOVED` and releases its soft hold by lowering each affected batch's `reserved_volume_ml`; because the lines were never committed, `remaining_volume_ml` is untouched, no cash moves, and no loyalty accrues. Voiding a ticket that is not `OPEN` is rejected with `ERR_ORDER_NOT_OPEN`.

A **refund** reverses a completed sale. A `ShiftLead` or `Manager` refunds a ticket that is `PAID`, moving it from `PAID` to `REFUNDED`; a refund attempted on a ticket that is not `PAID` is rejected with `ERR_ORDER_NOT_OPEN`. Refunding runs the commit cascade in reverse: for each `COMMITTED` line, the touched batches have their `committed_volume_ml` lowered and their `remaining_volume_ml` raised by the drawn volumes; any batch that had gone `DEPLETED` and whose `remaining_volume_ml` rises back above zero auto-transitions from `DEPLETED` back to `AVAILABLE`; and every affected flavor's `total_available_ml` and `stock_status` are recomputed, possibly rising to `BELOW_PAR` or `IN_STOCK`. On the cash side, the ticket records `cash_refunded_cents` — equal to `total_cents` when the original `payment_method` was `CASH` and zero otherwise — and the drawer's expected cash is recomputed. On the loyalty side, if the ticket carried a member the `punches_earned` scoops are reversed: the account's `lifetime_scoops` is decremented by the reversed scoops, floored at zero so it never goes negative, and the two counters are then recomputed from that new lifetime total — `free_scoop_credits` is set to `lifetime_scoops` divided by the punch threshold of 10 (whole-number quotient) and `punches` to `lifetime_scoops` modulo 10 — which undoes exactly the reward credit and punch balance this order had granted.

### 3.6. Cake Pre-Orders

A `Scooper` or `Manager` takes a cake **PreOrder**, which begins in the `QUOTED` state. Creating a pre-order records the base `flavor_id`, the `decorating_station_id` whose window it reserves, a `customer_name` for pickup, an `is_custom` flag (default false) with optional `custom_notes`, a decorating window `decorate_start_utc` to `decorate_end_utc` (end strictly after start), a `pickup_utc`, and a `quoted_price_cents`. The pre-order also exposes an `allergen_label` equal to the base flavor's `allergens`. Because a decorating station needs cleaning between cakes, two pre-orders on the same station must be separated by a clean buffer of at least 30 minutes: a new decorating window is accepted only if, for every other non-cancelled pre-order on that station, either the new window starts at least 30 minutes after that pre-order's window ends or the new window ends at least 30 minutes before that pre-order's window starts. Any closer spacing — including back-to-back windows that merely touch — collides and is rejected with `ERR_STATION_OVERLAP`.

The price of a `QUOTED` pre-order may be revised. A `Manager` re-quotes it, replacing `quoted_price_cents` with a new value and incrementing the pre-order's `version` by one. Re-quote is only legal while the pre-order is in `QUOTED`; a re-quote on a pre-order in any other state is rejected with `ERR_PREORDER_INVALID_STATE`, and this state check is evaluated before the version check. Re-quote is the optimistic-concurrency-guarded operation of Section 2.9: the request carries `expected_preorder_version`, and a value not matching the pre-order's current `version` is rejected with `ERR_STALE_VERSION`.

When the customer commits, a `Scooper` or `Manager` **confirms** the pre-order, moving it from `QUOTED` to `CONFIRMED` and taking a deposit: `deposit_cents` is set to `quoted_price_cents` multiplied by the deposit fraction of 0.20 (twenty percent), rounded half up to whole cents. Confirming anything not in `QUOTED` is rejected with `ERR_PREORDER_INVALID_STATE`, as is any pre-order transition attempted from an illegal state.

Production is a `Baker`'s responsibility. Starting production moves a `CONFIRMED` pre-order to `IN_PRODUCTION`, but only after a cross-entity availability gate on the base flavor: the flavor must have `is_active` true, must be in season if it is seasonal (the logical clock within its window, or the flavor non-seasonal), and must not be `OUT_OF_STOCK`. A base flavor failing any of these is rejected with `ERR_FLAVOR_UNAVAILABLE`. Production supports a revision loop: a baker may request a revision on an `IN_PRODUCTION` pre-order, sending it from `IN_PRODUCTION` back to `CONFIRMED` so that production can be re-checked and restarted; this cyclic path may repeat across multiple revision rounds. When the cake is done, a `Scooper` or `Manager` **fulfills** an `IN_PRODUCTION` pre-order, moving it to the terminal `FULFILLED` state and setting `final_price_cents` equal to `quoted_price_cents`.

A `Manager` may **cancel** a pre-order from `QUOTED`, `CONFIRMED`, or `IN_PRODUCTION`, moving it to the terminal `CANCELLED` state; a cancel from any other state is rejected with `ERR_PREORDER_INVALID_STATE`. The refund on cancel depends on how far the pre-order had progressed: if it was in `CONFIRMED` or `IN_PRODUCTION` a deposit had already been taken, so `refunded_cents` is set to `deposit_cents` (the deposit is returned); if it was still in `QUOTED` no deposit had been taken, so `refunded_cents` is zero.

### 3.7. Catering Bookings

A `Manager` books a catering event as a **CateringBooking**, which begins `BOOKED`. Creating a booking names the `event_cart_id` it reserves, an event window `event_start_utc` to `event_end_utc` (end strictly after start), and a `requested_items` array in which each entry pairs a `flavor_id` with a `volume_ml` to reserve. The `requested_items` array must be non-empty and each entry's `volume_ml` must be a strictly positive integer, else `ERR_VALIDATION`. The cart is a single physical resource, so the event window must not overlap another booking's window on the same cart. Cart windows are half-open, and touching is allowed: a new window whose start equals an existing window's end does not collide, but any true overlap is rejected with `ERR_CART_OVERLAP`. The booking prices an `estimate_cents` at the catering rate of 2 cents per milliliter: it is the sum of the `volume_ml` across all `requested_items`, multiplied by 2.

Booking reserves inventory the same FIFO way an order line does: for each requested flavor, the requested `volume_ml` is drawn across that flavor's `AVAILABLE` batches in order of `expiry_at` ascending then `created_at` ascending, raising each touched batch's `reserved_volume_ml`; if the flavor's combined headroom cannot cover the request, the booking is rejected with `ERR_INSUFFICIENT_BATCH_VOLUME` and nothing is reserved. (The capacity guard on the cart is its `capacity_ml`, the ceiling on the total requested volume a single booking may reserve: when the sum of `volume_ml` across all `requested_items` exceeds `capacity_ml` the booking is rejected with `ERR_VALIDATION`. This capacity guard and the cart-overlap check are both evaluated before any inventory is reserved.)

Closing a booking settles it against what was actually served. A manager closes a `BOOKED` booking with an `actual_items` array, each entry again pairing a `flavor_id` with the `volume_ml` truly consumed; each entry's `volume_ml` may be zero or greater (it need not be strictly positive). Each actual flavor must have been part of `requested_items`, and its actual volume must not exceed the volume reserved for that flavor; a flavor that was not requested, or an actual volume exceeding what was reserved for it, is rejected with `ERR_VALIDATION`. Closing moves the booking from `BOOKED` to the terminal `SETTLED` state and runs the commit cascade over each requested flavor: the flavor's whole reservation is released (`reserved_volume_ml` on each of its reserved batches drops by that batch's reserved amount) while the actual consumed volume for the flavor is committed against those same reserved batches in reservation (FIFO) order, earliest reserved batch first, so `committed_volume_ml` rises and `remaining_volume_ml` drops by the actual amount spread across the leading batches; any batch hitting zero `remaining_volume_ml` auto-transitions `AVAILABLE` to `DEPLETED`, and the settled `actual_cents` is computed as the sum of actual `volume_ml` multiplied by 2 cents per milliliter. The estimate and actual figures diverge whenever actual consumption differs from what was requested. A manager may instead **cancel** a `BOOKED` booking, moving it to the terminal `CANCELLED` state and releasing all reservations by lowering each reserved batch's `reserved_volume_ml`, leaving `remaining_volume_ml` untouched. Any close or cancel attempted on a booking that is not `BOOKED` is rejected with `ERR_CATERING_INVALID_STATE`.

### 3.8. The Cash Drawer and Daily Reconciliation

Cash accountability runs through the **CashDrawerSession**, the daily till. A `ShiftLead` opens a drawer with an `opening_float_cents`, the cash placed in the till at open; the session starts in the `OPEN` state with its `expected_cash_cents` seeded to the opening float and its `reconciliation_status` set to `PENDING`; its `counted_cash_cents` and `variance_cents` are null until the drawer is closed. Every order that rings into the drawer keeps its ledger figures current. The drawer's `expected_cash_cents` is the `opening_float_cents` plus the sum of `cash_collected_cents` across the drawer's orders minus the sum of `cash_refunded_cents` across the drawer's orders — that is, only cash movements adjust expected cash, and card sales do not. The drawer also reports two sales figures that differ once any ticket is refunded: `gross_sales_cents` is the sum of `total_cents` over the drawer's orders in `PAID` or `REFUNDED` status, while `net_sales_cents` is the sum of `total_cents` over orders in `PAID` status only.

At the end of the shift a `ShiftLead` closes the drawer, supplying the physically `counted_cash_cents`. Closing computes `variance_cents` as `counted_cash_cents` minus `expected_cash_cents` and sets the `reconciliation_status`: `BALANCED` when the variance is exactly zero, `OVER` when it is positive, and `SHORT` when it is negative. The drawer then moves from `OPEN` to the terminal `CLOSED` state. Closing an already-closed drawer is rejected with `ERR_DRAWER_ALREADY_CLOSED`. Because payment requires an open till, once a drawer is closed no further ticket may be paid into it.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the drawer close — return `200 OK`. The request and response bodies for each endpoint are as described in the Section 3 workflows; the table below is a routing and authorization summary only. "Any" denotes all four roles (`Manager`, `ShiftLead`, `Scooper`, `Baker`).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc` | Set the server logical clock (UTC) | Any |
| POST   | `/flavors` | Create a flavor | Manager |
| GET    | `/flavors` | List flavors | Any |
| GET    | `/flavors/{id}` | Get a flavor with computed stock fields | Any |
| PATCH  | `/flavors/{id}` | Update mutable flavor config | Manager |
| POST   | `/size-options` | Create a size option | Manager |
| GET    | `/size-options` | List size options | Any |
| POST   | `/toppings` | Create a topping | Manager |
| GET    | `/toppings` | List toppings | Any |
| POST   | `/event-carts` | Create a catering event cart | Manager |
| POST   | `/decorating-stations` | Create a cake decorating station | Manager |
| POST   | `/batches` | Produce a batch (starts PREP) | Baker |
| POST   | `/batches/{id}/release` | Release a batch to AVAILABLE | Baker |
| GET    | `/batches` | List/filter batches | Any |
| GET    | `/batches/{id}` | Get a batch with computed volumes and shrink | Any |
| POST   | `/waste-events` | Log melt/spillage/trim/expired-discard | Baker |
| GET    | `/waste-events` | List waste events | Any |
| GET    | `/waste-events/{id}` | Get a waste event | Any |
| POST   | `/loyalty-accounts` | Create a loyalty account | Manager, Scooper |
| GET    | `/loyalty-accounts/{id}` | Get a loyalty account | Any |
| POST   | `/cash-drawer-sessions` | Open a daily cash drawer | ShiftLead |
| POST   | `/cash-drawer-sessions/{id}/close` | Reconcile and close the drawer | ShiftLead |
| GET    | `/cash-drawer-sessions/{id}` | Get a drawer session with ledger fields | Any |
| POST   | `/orders` | Open a POS ticket against a drawer | Scooper, ShiftLead |
| GET    | `/orders` | List/filter orders | Any |
| GET    | `/orders/{id}` | Get an order with totals and COGS | Any |
| POST   | `/orders/{id}/lines` | Add a line; reserve FIFO batch volume | Scooper, ShiftLead |
| DELETE | `/orders/{id}/lines/{lineId}` | Remove an active line; release reservation | Scooper, ShiftLead |
| GET    | `/order-lines` | List/filter order lines | Any |
| GET    | `/order-lines/{id}` | Get an order line with price, allergens, allocations, COGS | Any |
| POST   | `/orders/{id}/pay` | Take payment, commit lines, accrue loyalty | Scooper, ShiftLead |
| POST   | `/orders/{id}/void` | Void an open ticket; release reservations | ShiftLead |
| POST   | `/orders/{id}/refund` | Refund a paid ticket; reverse cascade | ShiftLead, Manager |
| POST   | `/pre-orders` | Create a cake pre-order (QUOTED) | Scooper, Manager |
| GET    | `/pre-orders` | List/filter pre-orders | Any |
| GET    | `/pre-orders/{id}` | Get a pre-order with deposit/allergen label | Any |
| POST   | `/pre-orders/{id}/requote` | Re-quote price (OCC-guarded) | Manager |
| POST   | `/pre-orders/{id}/confirm` | Confirm pre-order and take deposit | Scooper, Manager |
| POST   | `/pre-orders/{id}/start-production` | Start production (availability gate) | Baker |
| POST   | `/pre-orders/{id}/request-revision` | Send back to CONFIRMED for revision | Baker |
| POST   | `/pre-orders/{id}/fulfill` | Fulfill and set final price | Scooper, Manager |
| POST   | `/pre-orders/{id}/cancel` | Cancel; refund deposit if confirmed | Manager |
| POST   | `/catering-bookings` | Book a catering event; reserve volume | Manager |
| GET    | `/catering-bookings` | List/filter catering bookings | Any |
| GET    | `/catering-bookings/{id}` | Get a catering booking | Any |
| POST   | `/catering-bookings/{id}/close` | Close with actual consumption | Manager |
| POST   | `/catering-bookings/{id}/cancel` | Cancel and release reservations | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_FLAVOR_NOT_FOUND` | 404 |
| `ERR_SIZE_OPTION_NOT_FOUND` | 404 |
| `ERR_TOPPING_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_WASTE_EVENT_NOT_FOUND` | 404 |
| `ERR_LOYALTY_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_DRAWER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_PREORDER_NOT_FOUND` | 404 |
| `ERR_EVENT_CART_NOT_FOUND` | 404 |
| `ERR_DECORATING_STATION_NOT_FOUND` | 404 |
| `ERR_CATERING_BOOKING_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_OPEN` | 409 |
| `ERR_EMPTY_ORDER` | 409 |
| `ERR_DRAWER_NOT_OPEN` | 409 |
| `ERR_DRAWER_ALREADY_CLOSED` | 409 |
| `ERR_BATCH_NOT_PREP` | 409 |
| `ERR_BATCH_NOT_AVAILABLE` | 409 |
| `ERR_PREORDER_INVALID_STATE` | 409 |
| `ERR_CATERING_INVALID_STATE` | 409 |
| `ERR_ALLERGEN_RESTRICTION_CONFLICT` | 409 |
| `ERR_FLAVOR_OUT_OF_SEASON` | 409 |
| `ERR_FLAVOR_UNAVAILABLE` | 409 |
| `ERR_CART_OVERLAP` | 409 |
| `ERR_STATION_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_BATCH_VOLUME` | 409 |
| `ERR_INSUFFICIENT_CASH_TENDERED` | 402 |
| `ERR_STALE_VERSION` | 412 |
