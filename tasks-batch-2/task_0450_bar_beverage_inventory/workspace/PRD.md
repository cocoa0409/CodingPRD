# Bar Beverage Inventory API — Product Requirements Document

## 1. Introduction

Running a bar profitably is fundamentally a reconciliation problem. Every shift, liquid leaves the building through pours, spills, breakage, and theft, while new stock arrives on vendor trucks against purchase orders that rarely match their invoices line-for-line. The Bar Beverage Inventory API exists to close the loop between what *should* have been consumed — the theoretical depletion implied by recorded sales and published cocktail specs — and what *actually* disappeared, as measured by a physical count of bottles and kegs on the floor. The gap between those two numbers, valued at landed cost, is the variance that tells an operator whether they have a pour-accuracy problem, a shrinkage problem, or a counting problem.

This system models the full beverage program: stock-keeping units expressed as bottles or kegs, par levels that drive replenishment, cocktail recipes whose pour costs feed menu pricing, vendor purchase orders and the invoices that reconcile against them, weight-based and unit-based physical counts, draft-line keg occupation, and a waste ledger. It is built for three operational owners working in parallel — an inventory team that owns products, par configuration, and counts; a purchasing team that owns orders and invoices; and a bar-management team that owns recipes, the menu, sales, and waste. Throughout, all monetary amounts are integer cents, all volumes are milliliters, and all masses are grams. Container "units" express a count of full containers, so a reading of `0.681` means roughly two-thirds of one bottle or keg; stock and depletion are always tracked in units of each product's own container.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which they act. These headers are required on all endpoints, including read-only `GET` endpoints. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation under the access-control matrix in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `InventoryManager`, `PurchasingAgent`, and `BarManager`. An `InventoryManager` owns products, par settings, physical counts, and stock-level reads. A `PurchasingAgent` owns purchase orders and vendor invoices. A `BarManager` owns cocktail recipes, menu items, sales recording, and menu engineering. Waste logging, keg-tap recording, and setting the logical clock are shared capabilities available to more than one role, as detailed in §4.

For each of the three roles, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may accept and record it, but it does not compare `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching the header against a stored foreign key. Authorization is decided entirely by whether `X-User-Role` is permitted to perform the operation, never by per-record ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single page returns; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before the page begins, and it defaults to 0. Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching resources across all pages and `has_more` indicates whether further pages remain beyond the current one.

### 2.4. Common Resource Properties

Every resource in this system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Because all entities in this domain are mutable, they additionally carry an `updated_at` timestamp — likewise ISO 8601 UTC with three fractional digits — that is refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by exactly 1 on each subsequent mutation. The `version` field underpins the optimistic-concurrency mechanism described in §2.6.

It is important to understand that derived fields are themselves mutations. When a posting elsewhere in the system recomputes a product's `on_hand_units` or `needs_reorder`, recomputes a recipe's `recipe_cost_cents`, or rolls up a count's `total_variance_cost_cents`, that recomputation refreshes the affected resource's `updated_at` and increments its `version`, exactly as a direct edit would.

### 2.5. Nested Resource Retrieval and Referential Validation

Many endpoints address a resource by an `id` embedded in the URL path, and several also carry foreign-key references in their request bodies. The system validates references in a strict left-to-right order: the path identifier is resolved first, and only then are body-level foreign keys checked. The first reference that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs. For example, a request to add a line to a count session whose session `id` does not exist fails on the session before the body's `product_id` is ever examined.

The validation pipeline as a whole runs in a fixed priority order so that the most fundamental failures surface first. Authentication is checked before authorization; authorization before resource existence; existence before state legality; state legality before optimistic-concurrency version checks; and only then are the domain-specific business rules evaluated. Schema-level request validation — required fields present, enum values legal, numbers within their declared ranges, and any method-conditional field present — is enforced as the request is parsed, raising `ERR_INVALID_REQUEST` (HTTP 400) when the body is malformed.

### 2.6. Optimistic Concurrency on Count Sessions

Physical counts are the one place in this system where concurrent writers can silently corrupt a reconciliation, so count sessions are guarded by optimistic concurrency control keyed on the session's `version`. Two write operations carry this guard, and both require the caller to supply an `expected_count_session_version` field in the request body — it is never optional on these two operations.

When a caller adds a count line to a session, the request must include `expected_count_session_version` carrying the `version` of the `CountSession` the caller last observed. If that value does not equal the session's current `version` on the server, the add is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against the case where a prior add — or a finalize the caller never saw — has already advanced the session and its derived totals, leaving the caller's view stale; the new line would otherwise be appended against an outdated basis.

Likewise, finalizing a session requires `expected_count_session_version` to match the session's current `version`. If another writer added a count line after the finalizing caller read the session, the session's `version` will have advanced, and the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412). Rejecting the commit prevents the variance roll-up the caller intends to write from omitting the newer line. No other endpoint in the system takes a version field; mutations outside these two count-session writes proceed without an OCC check.

### 2.7. Monetary, Volume, and Mass Precision

All money in the system is stored and returned as integer cents, never as a decimal currency value. Volumes are milliliters and masses are grams. Where a calculation produces a fractional cent, the result is rounded half-up to a whole cent — that is, a value whose fractional part is exactly one-half rounds away from zero to the next whole cent. Intermediate volume and weight conversions carry their own stated decimal precision (described with the relevant calculations in §3) before any cent rounding is applied. Sums of already-rounded integer cents are exact integer additions and are not rounded again.

### 2.8. Stock, Replenishment, and the Reorder Signal

A product's `on_hand_units` is a computed quantity expressing current stock in that product's own container units; it begins at 0 when a product is created and is mutated only by the postings described in §3 — invoice posting, count finalization, and waste logging. Alongside it, every product carries a computed boolean `needs_reorder` that is true exactly when `on_hand_units` is strictly less than the `reorder_point_units` of the product's currently active par setting, and false otherwise. This flag is recomputed every single time `on_hand_units` changes, and also whenever a new par setting supersedes the old one. A product with no active par setting cannot have its reorder signal evaluated against a threshold; in that situation `needs_reorder` remains false.

Replenishment policy lives in the `ParSetting` entity. Only one par setting may be active per product at any instant: when a new one is created it supersedes the prior active setting, which moves to `SUPERSEDED`, while the new setting is `ACTIVE`. A par setting names the `par_level_units` (the target full-stock level, which must be greater than zero) and the `reorder_point_units` (the replenishment trigger, which must be at least zero and at most the `par_level_units`). If those bounds are violated, the create is rejected with `ERR_INVALID_PAR` (HTTP 422).

### 2.9. Cascade and Compensation Discipline

Several operations in this system mutate more than one entity in a single atomic step, and each downstream effect is part of the operation's contract rather than an optional convenience. Posting an invoice lands new landed cost onto each billed product, adds received stock to each product's `on_hand_units`, recomputes each affected product's `needs_reorder`, and — when the order was still `SUBMITTED` — cascades the purchase order forward to `RECEIVED`. Voiding a posted invoice runs the mirror-image compensation: it reverses the received stock out of each product's `on_hand_units`, recomputes `needs_reorder`, and, if it was the only posted invoice on its order, reverts the order from `RECEIVED` back to `SUBMITTED`. Finalizing a count overwrites each counted product's `on_hand_units` with the freshly measured closing figure and recomputes `needs_reorder`. Each of these cascades bumps the `version` and refreshes the `updated_at` of every entity it touches, consistent with §2.4.

## 3. Business Logic & Workflows

### 3.1. Building the Product Catalog

The catalog is the foundation everything else references. An `InventoryManager` registers a product by supplying its `sku` (a human-readable stock-keeping code of 1 to 40 characters), its display `name`, its `container_type` — one of `BOTTLE` or `KEG` — and its `container_volume_ml`, the nominal volume of one full container, which must be greater than zero. A 750-mL spirits bottle and a 58,670-mL half-barrel keg are both expressed in milliliters here. The creator also supplies the `unit_cost_cents`, the latest landed cost of one full container, which must be at least zero. Three further inputs are optional at creation: `empty_container_weight_g`, the tare weight of an empty container in grams (defaulting to 0, and required in practice for weight-based counting of bottles), which must be at least zero; `density_g_per_ml`, the liquid density used to turn net weight into volume during weight counts (defaulting to 1.0), which must be greater than zero; and `case_pack`, the number of containers per ordering case (defaulting to 1), which must be at least one and against which reorder quantities round up.

A newly created product is born `ACTIVE`, with `on_hand_units` at 0 and `needs_reorder` false. The `sku` must be unique across all products that are not archived; an attempt to register a `sku` that collides with an existing non-archived product is rejected with `ERR_DUPLICATE_SKU` (HTTP 409). A product's lifecycle `status` is one of `ACTIVE` or `ARCHIVED`. Archiving a product is a soft delete performed by an `InventoryManager`: it sets the product's `status` to `ARCHIVED` and bumps its `version`. Because uniqueness is enforced only over non-archived products, archiving a product frees its `sku` for reuse by a future product.

Several read endpoints exist purely to reach the children that reference a product by foreign key: a product's par settings, the recipe lines that pour it, its count lines, its purchase-order lines, its invoice lines, its waste logs, and its keg taps can each be listed by walking from the product. The count-line listing accepts an optional `count_session_id` filter, the waste-log listing accepts an optional `reason` filter, and the keg-tap listing accepts an optional `draft_line_no` filter; all of these list endpoints also accept the standard `limit` and `offset` pagination controls. The flat product list itself can be narrowed by `status`, by `container_type`, and by the `needs_reorder` flag.

### 3.2. Keg Yield and Reorder Suggestions

Two computed reads turn a product's static configuration into operational guidance. The first is keg yield, available only on keg products. A caller supplies a `pour_size_ml` and, optionally, a `line_loss_pct` that defaults to five hundredths (0.05, i.e. five percent of draft volume lost to line and foam). If the product's `container_type` is not `KEG`, the read is rejected with `ERR_NOT_A_KEG` (HTTP 422). Otherwise the system reports the theoretical serving count as the container volume divided by the pour size, dropped to the next lower whole number (`servings_theoretical`); the net serving count as the container volume multiplied by the quantity one minus the line-loss fraction, divided by the pour size, again dropped to the next lower whole number (`servings_net`); and the cost per serving as the product's `unit_cost_cents` divided by the net serving count, rounded half-up to a whole cent (`cost_per_serving_cents`). If the net serving count works out to zero, division is impossible and the request is rejected with the generic business error `ERR_VALIDATION` (HTTP 422), as is a freight value that has gone negative after defaulting.

The second computed read is the reorder suggestion, which requires the product to have an active par setting; if none exists, the read is rejected with `ERR_NO_ACTIVE_PAR` (HTTP 422). When `on_hand_units` is at least the active setting's `reorder_point_units`, no replenishment is needed: the response reports `triggered` as false and `suggested_qty` as 0. When `on_hand_units` falls below the reorder point, `triggered` is true and the suggested quantity is computed in two steps — first take the difference between `par_level_units` and `on_hand_units` and round it up to the next whole container, then round that figure up to the nearest multiple of the product's `case_pack`. The response also echoes the `par_level_units` and the `on_hand_units` that drove the decision.

### 3.3. Cocktail Recipes and Pour Cost

A `BarManager` authors drink specifications as recipes. Creating a recipe takes only a `name` and yields a `RecipeSpec` in `DRAFT` status with a `recipe_cost_cents` of 0; a recipe's `status` is one of `DRAFT`, `PUBLISHED`, or `RETIRED`. While a recipe is in `DRAFT`, ingredient pour lines may be added to it. Each `RecipeLine` names the `recipe_id` it belongs to, the `product_id` of the ingredient poured, and the `pour_ml` poured per serving, which must be greater than zero.

The cost of a single pour line, `line_cost_cents`, is the ingredient product's `unit_cost_cents` multiplied by the line's `pour_ml`, divided by that product's `container_volume_ml`, with the result rounded half-up to a whole cent. A recipe's `recipe_cost_cents` is then the sum of the `line_cost_cents` of every one of its lines, taken across all lines regardless of any filter, with the lines considered in order of their creation time. The rounding order here is deliberate and contractual: each line is rounded to a whole cent first, and only then are the rounded line costs summed. The naive alternative — summing the raw fractional line costs and rounding once at the end — is explicitly not used, because the two approaches can differ by a cent. This recipe cost is recomputed whenever a line is added or updated, whenever a referenced product's `unit_cost_cents` changes, and again when the recipe is published.

Publishing is the transition that freezes a recipe for use on the menu. A `BarManager` publishes a recipe only when it is `DRAFT`, has at least one recipe line, and every line's referenced product is `ACTIVE`; the publish recomputes `recipe_cost_cents` from the round-per-line sum, moves the recipe to `PUBLISHED`, and bumps its `version`. A published recipe can be sent back for editing by revising it, which is allowed only while it is `PUBLISHED` and no active menu item references it, returning it to `DRAFT`. A published recipe can instead be retired, again only while it is `PUBLISHED` and no active menu item references it, moving it to the terminal `RETIRED` state. Both revise and retire bump the recipe's `version`. Attempting any of these transitions from a state that does not allow it is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.4. The Menu and Menu Engineering

A `BarManager` lists a recipe for sale by creating a `MenuItem`, supplying the `recipe_id` and a `menu_price_cents` that must be greater than zero. A menu item may only reference a recipe whose `status` is `PUBLISHED`; an attempt to list a recipe that is not published is rejected with `ERR_RECIPE_NOT_PUBLISHED` (HTTP 422). A new menu item is `ACTIVE`, with `units_sold` at 0 and `menu_class` at `UNCLASSIFIED`; its `status` is one of `ACTIVE` or `DELISTED`. The item's pour-cost percentage, `pour_cost_pct`, is the referencing recipe's `recipe_cost_cents` divided by the item's `menu_price_cents`, multiplied by one hundred and carried to two decimal places; it is recomputed whenever the price changes or the underlying recipe cost changes, and it starts at 0.

Sales are recorded in batches against a menu item by supplying a `quantity` and a `sold_at` timestamp; recording sales adds the `quantity` to the item's cumulative `units_sold`, which is what drives both theoretical depletion and menu engineering. Delisting a menu item moves its `status` to `DELISTED`, bumps its `version`, and removes it from the universe of items eligible for sales recording and for the menu-engineering and depletion calculations. A delisted item can no longer accept recorded sales.

The menu-engineering report classifies every `ACTIVE` menu item that sells a published recipe into one of four quadrants, persisting the resulting `menu_class` onto each item when the report runs. The report's universe is exactly those active items on published recipes; it requires at least one such item whose combined cumulative `units_sold` across the universe is at least 1, otherwise it is rejected with `ERR_EMPTY_MENU` (HTTP 422). For the universe, let the total be the sum of `units_sold` across all members and let the count be the number of members. A popularity threshold is set at seven-tenths (0.70) multiplied by the reciprocal of the member count — that is, 0.70 times one divided by the count. Each item's contribution margin is its `menu_price_cents` minus the `recipe_cost_cents` of its recipe, and the average margin is the sum of those margins divided by the count, compared as an exact value without rounding. For each item, its popularity index is its own `units_sold` divided by the universe total, rounded half-up to four decimal places. An item is treated as high-popularity when its popularity index is at least the popularity threshold (the boundary is inclusive), and as high-margin when its contribution margin is at least the average margin (again inclusive). An item that is both high-popularity and high-margin is classified `STAR`; one that is high-popularity but not high-margin is `PLOWHORSE`; one that is high-margin but not high-popularity is `PUZZLE`; and one that is neither is `DOG`.

### 3.5. Purchase Orders and Receiving

A `PurchasingAgent` opens procurement by creating a purchase order with a `vendor_name` and an `expected_at` promised-delivery datetime; the order is born `DRAFT` with an `ordered_total_cents` of 0. A purchase order's `status` moves through `DRAFT`, `SUBMITTED`, `RECEIVED`, `CLOSED`, and `CANCELLED`, with `CLOSED` and `CANCELLED` terminal. While the order is `DRAFT`, order lines are added to it: each `POLine` names the `purchase_order_id` it belongs to, the `product_id` ordered, the `ordered_qty` of containers (which must be greater than zero), and the `unit_cost_cents` quoted per container at order time (at least zero).

Submitting an order is allowed only when it is `DRAFT`, carries at least one line, and every line's product is `ACTIVE`; otherwise the transition is rejected with `ERR_INVALID_STATE` (HTTP 409) for a wrong-state order. Submission computes the order's `ordered_total_cents` as the sum, over every line, of that line's `ordered_qty` multiplied by its `unit_cost_cents`, moves the order to `SUBMITTED`, and bumps its `version`. An order does not advance to `RECEIVED` by its own action: it cascades to `RECEIVED` automatically when its first invoice posts, as described in §3.6.

Closing an order finishes the procurement cycle and is permitted only when the order is `RECEIVED`. Closure additionally requires that receiving be complete: across all posted invoices, the received quantity summed per product must be at least the order's ordered quantity for that product, so that no short-receipt is left open. If any product remains short-received, the close is rejected with `ERR_SHORT_RECEIPT` (HTTP 422). A successful close moves the order to `CLOSED` and bumps its `version`.

An order may instead be cancelled. Cancellation from `DRAFT` is always permitted. Cancellation from `SUBMITTED` is permitted only when no posted invoice references the order; if a posted invoice exists, the cancel is blocked as an invalid state transition. Cancellation moves the order to the terminal `CANCELLED` state and bumps its `version`.

### 3.6. Invoices: Reconciliation, Landing Cost, and Posting Stock

Against a submitted or received order, a `PurchasingAgent` creates an invoice carrying the `purchase_order_id` it reconciles, the `vendor_invoice_no` (the vendor's own invoice number, which must be unique per vendor), and an optional flat `freight_cents` delivery charge that defaults to 0 and must be at least zero. A new invoice is `DRAFT`, with its `subtotal_cents`, `discount_cents`, `tax_cents`, and `invoice_total_cents` all at 0; an invoice's `status` is one of `DRAFT`, `POSTED`, or `VOID`. Billed lines are added to a draft invoice: each `InvoiceLine` carries the `invoice_id` it belongs to, the `product_id` billed, the `received_qty` of containers actually received (greater than zero), and the billed `unit_cost_cents` per container (at least zero). A billed product must appear on a line of the invoice's purchase order; an invoice line whose `product_id` is not present on any of the order's lines is rejected with `ERR_PRODUCT_NOT_ON_PO` (HTTP 422), and this same check is re-applied at post time.

Posting an invoice is the system's busiest moment, and its effects run in a pinned order. The transition is permitted only when the invoice is `DRAFT`, has at least one line, references an order that is `SUBMITTED` or `RECEIVED`, and has every line's `product_id` present on the order's lines. The reconciliation then computes, in this exact sequence: first, each line's `extension_cents` as its `received_qty` multiplied by its `unit_cost_cents`; second, the invoice `subtotal_cents` as the sum of those extensions; third, the `discount_cents` as a tiered percentage of the subtotal — five percent if the subtotal is at least 40,000 cents, otherwise three percent if it is at least 30,000 cents, otherwise zero — rounded half-up to a whole cent, where the tier boundaries are inclusive so that a subtotal of exactly 40,000 cents takes the five-percent tier; fourth, the `tax_cents` as eight and three-quarters percent (the rate 0.0875) of the subtotal-minus-discount, rounded half-up to a whole cent; and fifth, the `invoice_total_cents` as the subtotal minus the discount, plus the tax, plus the freight. Subtotal and total are exact integer sums; only the discount and tax are rounded.

Posting does far more than tally money. For each billed line, the system overwrites the product's `unit_cost_cents` with the line's billed `unit_cost_cents` so that the product carries the latest landed cost, and it adds the line's `received_qty` to the product's `on_hand_units`. Each affected product then recomputes `needs_reorder` against its active par setting. If the referenced order was still `SUBMITTED`, posting cascades it forward to `RECEIVED`. Finally the invoice moves to `POSTED` and its `version` is bumped. The order's own advance to `RECEIVED` on this first posting bumps the order's `version` as well.

Voiding an invoice is the compensating action and behaves differently depending on the invoice's state. Voiding a `DRAFT` invoice simply moves it to the terminal `VOID` state and bumps its `version`, with no stock or order effects. Voiding a `POSTED` invoice — permitted only while the referenced order is not yet `CLOSED` — runs the mirror compensation: for each line it subtracts the line's `received_qty` back out of the product's `on_hand_units`, recomputes each affected product's `needs_reorder`, and, if this was the only posted invoice on the order, reverts the order from `RECEIVED` back to `SUBMITTED`; the invoice then moves to `VOID` and its `version` is bumped. Attempting to void a posted invoice whose order has already closed is rejected as an invalid state transition.

### 3.7. Physical Counts, Closing Units, and Variance

The reconciliation heart of the system is the physical count. An `InventoryManager` opens a `CountSession` with a human `label` and a `counted_at` logical timestamp that marks the point in time the physical count represents; the session is born `OPEN` with a `version` of 1 and a `total_variance_cost_cents` of 0. A session's `status` is one of `OPEN`, `FINALIZED`, or `VOID`. While the session is open, count lines are added one product at a time, each line OCC-guarded by the session version as described in §2.6.

Each `CountLine` carries the `count_session_id` it belongs to, the `product_id` measured, the `count_method` — one of `UNITS` or `WEIGHT` — and the `expected_count_session_version` that guards the add. When the method is `UNITS`, the caller supplies `counted_units`, a direct full-plus-partial container count that must be at least zero. When the method is `WEIGHT`, the caller instead supplies `gross_weight_g`, the gross weight of the partial container in grams, which must be at least zero. A session may hold at most one count line per product; a second line for a product already counted in the session is rejected with `ERR_DUPLICATE_COUNT_LINE` (HTTP 409).

A line's resolved on-hand quantity, `closing_units`, is computed at finalize. For a `UNITS` line, the closing figure is simply the supplied `counted_units`. For a `WEIGHT` line, the system first computes the net liquid weight as `gross_weight_g` minus the product's `empty_container_weight_g`; converts that to remaining volume by dividing the net liquid weight by the product's `density_g_per_ml`, rounded half-up to one decimal place; and then expresses that as a container fraction by dividing the remaining volume by the product's `container_volume_ml`, rounded half-up to three decimal places. A weight line whose `gross_weight_g` does not exceed the product's `empty_container_weight_g` would imply a net liquid weight that is not positive, and is rejected with `ERR_WEIGHT_BELOW_TARE` (HTTP 422); this tare check is enforced both when the weight line is added and at finalize.

Finalization is where theoretical and actual depletion meet. An `InventoryManager` finalizes a session only when it is `OPEN`, has at least one line, every line measures a distinct product, and the supplied `expected_count_session_version` still matches the session's `version`. There is one further temporal precondition: the session's `counted_at` must be strictly later than the `counted_at` of the most recent finalized session that shares any product with this one, so that the per-product depletion windows — which are half-open intervals — neither overlap nor abut at an equal `counted_at`. A finalize that violates this ordering is rejected with `ERR_COUNT_WINDOW_OVERLAP` (HTTP 422).

For each counted product, finalization derives the depletion window as the half-open interval running from the `counted_at` of that product's most recent prior finalized session up to and including this session's `counted_at`. The prior closing figure is the `closing_units` recorded for the product in that most recent prior finalized session, or zero if there is no prior count. The received-since figure is the sum of `received_qty` across all invoice lines for the product whose invoices posted within the window. Theoretical depletion is built forward from sales: over every active menu item that sells a published recipe containing this product, the system sums the item's units sold within the window, multiplied by the product's `pour_ml` in that recipe, divided by the product's `container_volume_ml`, and rounds the running total half-up to four decimal places at the end — this is the line's `theoretical_units`. Actual depletion is the prior closing figure plus the received-since figure minus this line's `closing_units`. The line's `variance_units` is the actual depletion minus the theoretical depletion, rounded half-up to four decimal places, and is the signed amount by which measured depletion ran over (positive) or under (negative) what the recipes predicted. The line's `variance_cost_cents` is `variance_units` multiplied by the product's `unit_cost_cents`, rounded half-up to a whole cent. The session's `total_variance_cost_cents` is the sum of the signed `variance_cost_cents` across all of its lines.

Finalization closes the loop on stock: each counted product's `on_hand_units` is overwritten with that line's `closing_units`, making the count the authoritative on-hand figure, and each such product recomputes `needs_reorder`. The session moves to `FINALIZED` and its `version` is bumped. Alternatively, an open session may simply be voided, which requires the session to be `OPEN`, takes the same `expected_count_session_version` guard, moves the session to the terminal `VOID` state, and bumps its `version`.

### 3.8. Waste, Spillage, and Draft-Line Occupation

Loss outside of pours is captured in the waste ledger. A `BarManager` or an `InventoryManager` records a waste event by naming the `product_id` spilled, a `reason` drawn from `SPILL`, `BREAKAGE`, `EXPIRY`, `OVERPOUR`, or `COMP`, and the `wasted_units` lost, which may be fractional but must be greater than zero. The event's `waste_cost_cents` is `wasted_units` multiplied by the product's `unit_cost_cents`, rounded half-up to a whole cent at log time. Recording waste also depletes stock: the product's `on_hand_units` is reduced by `wasted_units`, floored at zero so it never goes negative, and the affected product recomputes `needs_reorder`.

Draft kegs occupy physical lines, and the system tracks that occupation to prevent two kegs from claiming the same line at the same time. A `BarManager` or `InventoryManager` taps a keg by naming the keg `product_id` (whose `container_type` must be `KEG`), the `draft_line_no` it occupies (a positive integer line number, capacity one keg per line at any instant), and the closed occupation interval given by `tapped_from` (the inclusive start) and `tapped_until` (the inclusive end, which must be at or after `tapped_from`). Two taps on the same `draft_line_no` may not have overlapping closed intervals, but adjacency is allowed: a tap whose `tapped_from` exactly equals a previous tap's `tapped_until` is permitted, since kegs swap instantaneously. A tap whose interval genuinely overlaps an existing tap on the same line is rejected with `ERR_LINE_OVERLAP` (HTTP 422).

### 3.9. The Logical Clock

Because depletion windows, sales timestamps, and count timestamps all resolve against server time, the system runs on a logical clock rather than wall-clock time. Any of the three roles may set the clock to a supplied `to_iso8601` instant; the clock starts at `2026-01-01T00:00:00Z` on startup and never falls back to wall-clock time once running. All `sold_at` and `counted_at` windows are resolved against this logical clock, which makes count windows and sales attribution fully deterministic and test-drivable. The clock-set capability reports back the resulting `current_utc`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including the lifecycle transitions, sales recording, computed reads, and the clock control — return a `200 OK` status code. Every endpoint requires the `X-User-ID` and `X-User-Role` headers, including the read-only ones.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a bottle/keg SKU | InventoryManager |
| GET | `/products/{id}` | Read a product | InventoryManager, PurchasingAgent, BarManager |
| GET | `/products` | List products with optional filters | InventoryManager, PurchasingAgent, BarManager |
| POST | `/products/{id}/archive` | Archive a product (soft delete) | InventoryManager |
| GET | `/products/{id}/keg-yield` | Computed keg line/yield read | InventoryManager, BarManager |
| GET | `/products/{id}/reorder-suggestion` | Computed par/reorder suggestion | InventoryManager, PurchasingAgent |
| GET | `/products/{id}/par-settings` | List par settings for a product | InventoryManager, PurchasingAgent |
| GET | `/products/{id}/recipe-lines` | List recipe lines that pour a product | BarManager, InventoryManager |
| GET | `/products/{id}/count-lines` | List count lines for a product | InventoryManager |
| GET | `/products/{id}/po-lines` | List PO lines for a product | PurchasingAgent, InventoryManager |
| GET | `/products/{id}/invoice-lines` | List invoice lines for a product | PurchasingAgent, InventoryManager |
| GET | `/products/{id}/waste-logs` | List waste logs for a product | BarManager, InventoryManager |
| GET | `/products/{id}/keg-taps` | List keg taps for a product | BarManager, InventoryManager |
| POST | `/par-settings` | Create/supersede the active par setting for a product | InventoryManager |
| GET | `/par-settings` | List par settings, optionally filtered by product | InventoryManager, PurchasingAgent |
| POST | `/recipes` | Create a DRAFT cocktail recipe spec | BarManager |
| GET | `/recipes/{id}` | Read a recipe spec | BarManager, InventoryManager |
| POST | `/recipes/{id}/lines` | Add an ingredient pour line to a DRAFT recipe | BarManager |
| GET | `/recipes/{id}/lines` | List ingredient lines of a recipe | BarManager, InventoryManager |
| POST | `/recipes/{id}/publish` | Publish a DRAFT recipe | BarManager |
| POST | `/recipes/{id}/revise` | Send a PUBLISHED recipe back to DRAFT | BarManager |
| POST | `/recipes/{id}/retire` | Retire a PUBLISHED recipe | BarManager |
| POST | `/menu-items` | List a PUBLISHED recipe on the menu at a price | BarManager |
| GET | `/menu-items/{id}` | Read a menu item | BarManager, InventoryManager |
| GET | `/menu-items` | List menu items, optionally filtered by recipe | BarManager, InventoryManager |
| POST | `/menu-items/{id}/record-sales` | Record a batch of unit sales for a menu item | BarManager |
| POST | `/menu-items/{id}/delist` | Delist a menu item | BarManager |
| GET | `/menu-items/engineering` | Computed menu-engineering report | BarManager |
| POST | `/count-sessions` | Open a physical count session | InventoryManager |
| GET | `/count-sessions/{id}` | Read a count session | InventoryManager |
| POST | `/count-sessions/{id}/count-lines` | Add a count line (UNITS or WEIGHT); OCC-guarded | InventoryManager |
| GET | `/count-sessions/{id}/count-lines` | List count lines of a session | InventoryManager |
| POST | `/count-sessions/{id}/finalize` | Finalize a count; OCC-guarded | InventoryManager |
| POST | `/count-sessions/{id}/void` | Void an OPEN count session | InventoryManager |
| POST | `/purchase-orders` | Create a DRAFT purchase order | PurchasingAgent |
| GET | `/purchase-orders/{id}` | Read a purchase order | PurchasingAgent, InventoryManager |
| GET | `/purchase-orders` | List purchase orders with pagination | PurchasingAgent, InventoryManager |
| POST | `/purchase-orders/{id}/lines` | Add an order line to a DRAFT PO | PurchasingAgent |
| GET | `/purchase-orders/{id}/lines` | List order lines of a PO | PurchasingAgent, InventoryManager |
| POST | `/purchase-orders/{id}/submit` | Submit a DRAFT PO | PurchasingAgent |
| POST | `/purchase-orders/{id}/close` | Close a fully-received PO | PurchasingAgent |
| POST | `/purchase-orders/{id}/cancel` | Cancel a DRAFT or SUBMITTED PO | PurchasingAgent |
| POST | `/invoices` | Create a DRAFT invoice against a PO | PurchasingAgent |
| GET | `/invoices/{id}` | Read an invoice | PurchasingAgent, InventoryManager |
| GET | `/invoices` | List invoices, optionally filtered by PO | PurchasingAgent, InventoryManager |
| POST | `/invoices/{id}/lines` | Add a billed line to a DRAFT invoice | PurchasingAgent |
| GET | `/invoices/{id}/lines` | List billed lines of an invoice | PurchasingAgent, InventoryManager |
| POST | `/invoices/{id}/post` | Post an invoice; reconcile, land cost, post stock | PurchasingAgent |
| POST | `/invoices/{id}/void` | Void an invoice; compensate stock, revert PO | PurchasingAgent |
| POST | `/waste-logs` | Record a waste/spill event | BarManager, InventoryManager |
| GET | `/waste-logs` | List waste logs, optionally filtered by product | BarManager, InventoryManager |
| POST | `/keg-taps` | Tap a keg onto a draft line for a time interval | BarManager, InventoryManager |
| GET | `/keg-taps` | List keg taps, optionally filtered by product | BarManager, InventoryManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | InventoryManager, PurchasingAgent, BarManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCT_NOT_ON_PO` | 422 Unprocessable Entity |
| `ERR_RECIPE_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_WEIGHT_BELOW_TARE` | 422 Unprocessable Entity |
| `ERR_NOT_A_KEG` | 422 Unprocessable Entity |
| `ERR_INVALID_PAR` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_COUNT_LINE` | 409 Conflict |
| `ERR_NO_ACTIVE_PAR` | 422 Unprocessable Entity |
| `ERR_EMPTY_MENU` | 422 Unprocessable Entity |
| `ERR_SHORT_RECEIPT` | 422 Unprocessable Entity |
| `ERR_COUNT_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_LINE_OVERLAP` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
