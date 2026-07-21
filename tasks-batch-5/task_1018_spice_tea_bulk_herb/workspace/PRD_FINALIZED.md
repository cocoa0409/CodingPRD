# Spice, Tea & Bulk-Herb Shop API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Spice, Tea & Bulk-Herb Shop API, a back-office platform for a specialty bulk-goods merchant that sells loose spices, teas, and herbs by weight to wholesale customers. The business is unusual in that the same product may be sold as a simple single-origin ingredient or blended — by weight ratio — into a house recipe that is itself produced on a physical production line, drawn from finite lots of raw material, and later packed into gift tins on a shared labeling station. Every gram is tracked from receipt through allocation, and the same physical inventory is simultaneously subject to freshness expiry, first-expiry-first-out rotation, and reservation against open orders.

The platform must reconcile three concerns that pull against one another: **finite lot inventory** that is reserved and released as orders and production runs consume it, **temporal scheduling** of production and labeling windows on shared equipment, and **wholesale credit** that must never be over-committed. Pricing is quoted provisionally against a customer's requested weight and then re-struck against the physically measured net weight at packing time, so the same order carries two distinct monetary snapshots. Because operators act concurrently — a sales agent confirming credit while another confirms a sibling order against the same account — the system uses optimistic concurrency to prevent a confirmation from committing against a stale view of available credit. The sections that follow define the global contract every endpoint honors, then the business workflows that give the domain its behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles: `PlatformAdmin`, `CatalogManager`, `ProductionOperator`, `SalesAgent`, and `Wholesaler`. These are **peer roles** owning disjoint operational surfaces, with one hierarchical override. `PlatformAdmin` is an operator superset: it owns the logical clock and may perform any business operation in place of the peer role that normally owns it. `CatalogManager` owns the catalog — products, blend composition, and inventory receipts. `ProductionOperator` owns production and packing — production lines, batches, labeling stations, tin runs, and order packing. `SalesAgent` owns wholesale accounts and the order lifecycle except packing.

Four of the five roles carry an **opaque identity**. When `X-User-Role` is `PlatformAdmin`, `CatalogManager`, `ProductionOperator`, or `SalesAgent`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The `Wholesaler` role, by contrast, is **entity-backed**: when `X-User-Role` is `Wholesaler`, `X-User-ID` is the `id` of the acting `WholesaleAccount`. Ownership checks on any resource that references a wholesale account compare that resource's `wholesale_account_id` to `X-User-ID`; a `Wholesaler` may open, price, confirm, and cancel only orders whose `wholesale_account_id` equals its own `X-User-ID`, and may read only its own account, orders, lines, and the shared product catalog. A `Wholesaler` acting on an account it does not own is rejected with `ERR_UNAUTHORIZED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most primary resources — `Product`, `InventoryLot`, `ProductionLine`, `Batch`, `LabelingStation`, `TinRun`, `WholesaleAccount`, `CustomerOrder`, and `OrderLine` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the most recent modification. It is refreshed on any mutation, including changes to purely computed fields such as a product's `stock_state`, an account's exposure fields, or an order's stamped totals.
- `version` (integer): a system-managed counter that begins at its initial value on creation and increments by one on every modification to the resource.

One entity is deliberately leaner. A `BlendComponent` is an immutable junction row: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once a component attaches a simple ingredient to a blend at a given weight share it is never modified in place.

### 2.5. Nested Resource Retrieval and Existence Ordering

Whenever a request carries one or more resource identifiers — in the path or in the request body — the system validates their existence in a fixed left-to-right order: product, then inventory lot, then batch, then order line, then order, then account, then production line, then labeling station, then tin run, then blend component. The first identifier that fails to resolve determines the rejection, each with its own dedicated code: `ERR_PRODUCT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_LINE_RESOURCE_NOT_FOUND` (for a production line), `ERR_STATION_NOT_FOUND`, `ERR_TIN_RUN_NOT_FOUND`, and `ERR_COMPONENT_NOT_FOUND`. All existence checks return HTTP 404.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system is stored and returned as an integer number of cents. Weights are integers in grams, except a product's `unit_price_cents_per_gram`, which is a rate that may be fractional (for example, 3.5 cents per gram) and preserves its input precision.

Wherever a weight is multiplied by a rate to produce a cent amount, the result is rounded to a whole number of cents using the **round-half-up** convention (a fractional part of exactly one half rounds up). This applies to per-line pricing and to the discount amount described in §3. Rounding is always applied at the per-line level before any summation — never after — a pinned ordering detailed in §3.7.

### 2.7. The Logical Clock and Lot Freshness

The server maintains a single **logical clock** in UTC rather than reading wall-clock time. At startup, and before any call is made, the clock reads exactly `2026-07-01T00:00:00Z` and never falls back to real time. A `PlatformAdmin` may advance or reset this clock by supplying a target instant as `to_iso8601`; doing so causes every inventory lot's freshness to be recomputed on its next read.

A lot's freshness is derived, never stored as an input. Comparing the current clock to a lot's `best_by`: if the clock is at or after `best_by` (the boundary is inclusive), the lot is `EXPIRED`; otherwise, if its remaining `grams_on_hand` is zero, it is `DEPLETED`; otherwise it is `AVAILABLE`. Expiry dominates — a lot whose clock has reached `best_by` reads `EXPIRED` even if grams remain and even if it was previously drawn to zero.

### 2.8. Optimistic Concurrency on Wholesale Account Confirmation

Confirming a priced order commits a credit hold against a wholesale account and advances that account's `version`. Because several of an account's priced orders may be awaiting confirmation, and each confirmation changes how much credit remains, order confirmation is guarded by optimistic concurrency against the account. The confirmation request must carry `expected_wholesale_account_version` as a non-optional field, holding the `version` of the target `WholesaleAccount` that the client last observed. If that value does not equal the account's current `version` — because another confirmation has advanced it since the client last read the account — the confirmation is rejected with `ERR_STALE_VERSION` at HTTP 412, so a client can never commit a hold against a stale view of available credit. No other endpoint takes a version field.

### 2.9. Hierarchical Consistency and Stock-State Cascades

A product's `stock_state` is a derived rollup of its lots: a product is `IN_STOCK` when it has at least one `AVAILABLE`, non-expired lot whose `grams_on_hand` is greater than zero, and `OUT_OF_STOCK` otherwise. This value is never set directly by a client; it is reconciled by the server whenever a lot's on-hand quantity crosses zero in either direction.

Two cascade directions exist. When a draw — from packing an order or from producing a batch — takes a lot's `grams_on_hand` to zero, that lot transitions `AVAILABLE → DEPLETED`, and if it was the product's last lot carrying positive grams, the product cascades to `OUT_OF_STOCK`. When a release — from cancelling a packed order — restores grams to a lot, a lot that was `DEPLETED` transitions `DEPLETED → AVAILABLE`, and if the product now has a lot with positive grams it cascades back to `IN_STOCK`. Each such reconciliation independently mutates the affected resources, refreshing `updated_at` and incrementing `version`.

### 2.10. Validation Ordering and Error Precedence

When several checks could reject one request, they are evaluated in a fixed precedence so the returned error is deterministic. Authentication is evaluated first (`ERR_UNAUTHENTICATED`, 401), then role authorization including wholesale ownership (`ERR_UNAUTHORIZED`, 403), then existence of every referenced identifier in the left-to-right order of §2.5 (the 404 family), then whether the target resource is in a state that permits the requested transition (`ERR_INVALID_STATE`, 409). After state comes the optimistic-concurrency check on order confirmation (`ERR_STALE_VERSION`, 412), then the allergen-acknowledgement gate at packing (`ERR_ALLERGEN_LABEL_REQUIRED`, 409), then temporal and window checks (`ERR_LOT_EXPIRED`, `ERR_LINE_WINDOW_CONFLICT`, `ERR_STATION_BUFFER_CONFLICT`, `ERR_WINDOW_INVALID`, all 409). Referential business checks follow (`ERR_PRODUCT_DISCONTINUED`, `ERR_ACCOUNT_SUSPENDED` at 409, and `ERR_PRODUCT_NOT_BLEND` at 422), then business constraints (`ERR_INSUFFICIENT_STOCK` and `ERR_DUPLICATE_COMPONENT` at 409, `ERR_INVALID_RATIO` at 422, and malformed-body `ERR_VALIDATION` at 400), and finally the fiscal credit gate at confirmation (`ERR_CREDIT_LIMIT_EXCEEDED`, 402). Malformed request bodies — a missing required field, a wrong type, a non-positive weight, or a bad enum value — are rejected with `ERR_VALIDATION` at HTTP 400.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Products, Blends, and Components

The catalog is the foundation of the system, and a `CatalogManager` owns it. A product is created with a `name`, a `category` that is one of `SPICE`, `TEA`, or `HERB`, and a `kind` that is either `SIMPLE` or `BLEND`. Pricing is set through `unit_price_cents_per_gram`, which must be greater than zero, and each product declares a `tare_default_grams` (its default container weight, which must be zero or greater) used for provisional pricing before a physical weigh. A product may also declare `allergen_tags`, an array of allergen strings such as tree nuts or sesame, and a `shelf_life_days` giving its nominal shelf life; when `shelf_life_days` is omitted it defaults to 365. Newly created products begin with `status` of `ACTIVE` and, because no lots exist yet, an initial `stock_state` of `OUT_OF_STOCK`.

The distinction between `SIMPLE` and `BLEND` runs deep. For a `SIMPLE` product, its declared `allergen_tags` are its effective allergens verbatim. For a `BLEND` product, any supplied `allergen_tags` are ignored; its effective allergens are computed as the union of the effective allergens of its component ingredients, resolved recursively. A blend draws its contents from **blend components**, each attaching one `SIMPLE` ingredient to the blend. A component is created with a `blend_product_id` naming the blend, a `component_product_id` naming the simple ingredient, and a `weight_ratio_bps` giving that ingredient's weight share in basis points (ten-thousandths), which must fall between 1 and 10000 inclusive. Attaching the same ingredient to a blend twice is rejected with `ERR_DUPLICATE_COMPONENT`. Across all components of a single blend, the shares are required to sum to exactly 10000 basis points; a blend whose ratios do not sum to ten thousand is rejected at production time with `ERR_INVALID_RATIO`.

A `CatalogManager` may retire a product by discontinuing it, moving its `status` from `ACTIVE` to `DISCONTINUED`. `DISCONTINUED` is terminal. A discontinued product can no longer be added to a draft order line, but any existing lines that already reference it are unaffected.

### 3.2. Receiving and Tracking Inventory Lots

Physical stock enters the system as **inventory lots**, received by a `CatalogManager`. A lot is booked against a product through `product_id` and carries a human-readable `lot_code`, a `grams_received` count that must be greater than zero, a `received_at` receipt instant, and a `best_by` instant after which the goods are no longer sellable. On receipt, the lot's `grams_on_hand` is initialized equal to `grams_received`; it is thereafter decremented on every draw and restored on every release, and it may never go below zero. A lot minted by ordinary receiving has no producing batch, so its `source_batch_id` is null; only lots minted by a blend production run carry a `source_batch_id`. A freshly received lot is `AVAILABLE`, unless its `best_by` is already at or before the current clock, in which case it reads `EXPIRED` immediately; either way the owning product's `stock_state` is recomputed.

Lots can be listed and filtered by their product, by the batch that produced them, or by status, and a single lot read always reflects the current clock. As described in §2.7, a lot's `status` — one of `AVAILABLE`, `DEPLETED`, or `EXPIRED` — is derived on read from the clock and its on-hand quantity, with expiry taking precedence.

### 3.3. Production: Scheduling and Producing Blend Batches

Blends are manufactured on **production lines**, each a simple named resource created by a `ProductionOperator`. A **batch** schedules a production run: it names the `blend_product_id` to produce, the `production_line_id` whose time window it occupies, a `target_output_grams` (the finished quantity to yield, greater than zero), and a `scheduled_start` and `scheduled_end` bounding its window. The window is half-open — start inclusive, end exclusive — and its start must be strictly before its end, or the batch is rejected with `ERR_WINDOW_INVALID`. A batch occupies its line exclusively for that window: if the requested window overlaps another batch already scheduled on the same line, the batch is rejected with `ERR_LINE_WINDOW_CONFLICT`. Because the window is half-open, two batches that merely abut — one ending exactly when the next begins — do not conflict. A newly scheduled batch begins `PLANNED` with `produced_grams` of zero.

Producing a batch — a `ProductionOperator` action that advances it `PLANNED → PRODUCED` — is where raw ingredients are consumed and finished blend is minted. Production first requires that `blend_product_id` resolve to a product whose `kind` is `BLEND`; a non-blend target is rejected with `ERR_PRODUCT_NOT_BLEND`. For each component of the blend, the quantity to draw is the target output multiplied by that component's share in basis points, divided by ten thousand, then rounded **up** to the next whole gram. Each component's draw is satisfied from that ingredient's `AVAILABLE`, non-expired lots taken in first-expiry-first-out order — earliest `best_by` first, ties broken by earliest `received_at`, then by earliest `created_at` — drawing across as many lots as needed until the required grams are met. If a component's total available grams across its lots fall short of what is required, production is rejected with `ERR_INSUFFICIENT_STOCK`. Each lot drawn down has its `grams_on_hand` decremented; a lot that reaches zero transitions `AVAILABLE → DEPLETED`, and a depleted lot that was its product's last positive lot cascades that product to `OUT_OF_STOCK`. On success the system mints one new inventory lot for the blend product, with both `grams_received` and `grams_on_hand` set to the target output, `source_batch_id` set to this batch, and `best_by` computed as the current clock advanced by the blend product's `shelf_life_days`. Finally `produced_grams` is set equal to the target output and the batch becomes `PRODUCED`.

### 3.4. Gift-Tin Labeling and Allergen Sets

Finished goods are packed into gift tins at a **labeling station**, another named resource created by a `ProductionOperator`. A **tin run** schedules a packing session on a station: it names the `labeling_station_id`, carries a `product_ids` array listing the products packed during the run, and is bounded by a `scheduled_start` and `scheduled_end`. As with batches, the window is half-open and its start must be strictly before its end, or the run is rejected with `ERR_WINDOW_INVALID`. From the products packed, the system computes the run's `allergen_set` — the union of the effective allergens across every product in `product_ids`, with a blend's allergens resolved from its components as described in §3.1 — which drives the cross-contamination labeling and the cleaning requirement.

Unlike production lines, a labeling station requires a **cleaning buffer of thirty minutes** between consecutive runs to prevent allergen cross-contamination. A tin run scheduled such that its window falls within thirty minutes of another run on the same station — closer than a half-hour gap on either side — is rejected with `ERR_STATION_BUFFER_CONFLICT`. Tin runs may be listed by their station.

### 3.5. Wholesale Accounts and Credit Exposure

A `SalesAgent` opens a **wholesale account** for a buyer, supplying the `business_name`, a `credit_limit_cents` giving the maximum outstanding exposure (zero or greater), and an optional `tier` — one of `BRONZE`, `SILVER`, or `GOLD` — defaulting to `BRONZE`. A new account is `ACTIVE`, with all exposure figures at zero and available credit equal to its limit.

Three derived figures track the account's credit position, recomputed on every order confirm, pack, and cancel. The `committed_exposure_cents` is the sum of `held_exposure_cents` over the account's orders whose `fulfillment_status` is `CONFIRMED`, `PACKED`, or `SHIPPED`. The `projected_exposure_cents` is a forward-looking what-if: it is the committed exposure plus the `provisional_total_cents` of the account's orders that are `PRICED` but not yet confirmed, and it therefore exceeds committed exposure whenever any priced order is outstanding. The `available_credit_cents` is the credit limit minus the **committed** exposure — never the projected variant — and it is this committed-based figure that gates confirmation.

An account may cycle between `ACTIVE` and `SUSPENDED`. A `SalesAgent` suspending an account moves it `ACTIVE → SUSPENDED`, after which any attempt to confirm a new order against it is blocked with `ERR_ACCOUNT_SUSPENDED`; reinstating it moves it `SUSPENDED → ACTIVE` with no further effect. Neither transition has preconditions beyond the account being in the opposite state.

### 3.6. The Order Lifecycle: Draft, Priced, Confirmed

A `SalesAgent` or a `Wholesaler` opens an order against a wholesale account by supplying the `wholesale_account_id` and, optionally, an `allergen_ack` flag (defaulting to false) recording the buyer's acknowledgement that the goods may contain declared allergens. A new order is `DRAFT` with `held_exposure_cents` of zero. While the order is `DRAFT`, bulk lines are added to it: each **order line** names the `product_id` being purchased and the `requested_grams` the buyer wants, which must be greater than zero. Each line belongs to its parent via `order_id`. A product may only be added while it is `ACTIVE`.

Pricing an order advances it `DRAFT → PRICED` and requires at least one line, with every line's product still `ACTIVE`; a line referencing a discontinued product blocks pricing with `ERR_PRODUCT_DISCONTINUED`. Pricing stamps a provisional snapshot computed from requested weights. On each line, `provisional_line_cents` is the line's `requested_grams` multiplied by its product's `unit_price_cents_per_gram`, rounded half-up to whole cents. The order's `total_net_grams` is the sum of the lines' requested grams. The order's provisional subtotal is the sum of the already-rounded per-line provisional amounts — each line rounded to whole cents first, then summed. A volume discount then applies based on `total_net_grams`: below 500 grams the rate is zero; from 500 grams up to but not including 2000 grams the rate is five percent; at 2000 grams and above the rate is twelve percent. The discount is the subtotal multiplied by that rate, rounded half-up to whole cents, and the `provisional_total_cents` stamped on the order is the subtotal minus that discount.

Confirming a priced order advances it `PRICED → CONFIRMED` and is the point at which credit is committed. Confirmation requires that the account be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), that the supplied `expected_wholesale_account_version` match the account's current `version` (else `ERR_STALE_VERSION`, per §2.8), and that the order's `provisional_total_cents` not exceed the account's `available_credit_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402). On success, the order's `held_exposure_cents` is set to its provisional total, the account's committed exposure increases by that held amount, and the account's `version` increments by one.

### 3.7. Packing: Measurement, FEFO Allocation, and Final Pricing

Packing is a `ProductionOperator` action that advances a confirmed order `CONFIRMED → PACKED`, replacing the provisional estimate with figures struck from physically measured weights supplied as `line_measurements`. For each line the run captures a measured `gross_grams` (product plus container) and `tare_grams` (container alone); the line's `net_grams` is the gross minus the tare. Before allocating, the allergen gate applies: if any line being packed carries a non-empty effective allergen set, the order's `allergen_ack` must be true, or packing is rejected with `ERR_ALLERGEN_LABEL_REQUIRED`.

Each line is then filled from a single lot chosen by first-expiry-first-out. The candidate lots for a line are the `AVAILABLE`, non-expired lots of the line's product whose `grams_on_hand` is at least the line's `net_grams`; expired and depleted lots are excluded, as is any lot too small to fill the whole line from itself alone. Among the candidates the system selects the one with the earliest `best_by`, breaking ties by earliest `received_at` and then by earliest `created_at`; the random `id` is never used as a tiebreaker. If no single candidate lot can cover the line, packing is rejected with `ERR_INSUFFICIENT_STOCK`. If the FEFO-selected lot turns out to be expired, packing is rejected with `ERR_LOT_EXPIRED`. The chosen lot is recorded on the line as its `allocated_lot_id`, and that lot's `grams_on_hand` is decremented by the line's net grams; a lot drawn to zero transitions `AVAILABLE → DEPLETED` and cascades its product's `stock_state` toward `OUT_OF_STOCK` as described in §2.9.

Final pricing mirrors the provisional math but uses measured net weights. On each line, `final_line_cents` is its `net_grams` multiplied by the product's `unit_price_cents_per_gram`, rounded half-up to whole cents; this diverges from the provisional amount whenever measured net differs from requested grams. The order's final subtotal is the sum of the per-line final amounts, each rounded to whole cents before summing; the discount tier is re-selected from the packed `total_net_grams` using the same 500-gram and 2000-gram boundaries and the same five-percent and twelve-percent rates; and `final_total_cents` is the final subtotal minus the recomputed discount. Packing then re-sets the order's `held_exposure_cents` to the final total and adjusts the account's committed exposure by the difference between the final and the previously held provisional amount.

### 3.8. Shipment, Cancellation, and Compensation

Shipping is a `SalesAgent` action that advances a packed order `PACKED → SHIPPED`; it makes the allocations permanent, leaving each lot's grams decremented, and has no other effect. `SHIPPED` is terminal.

An order may be cancelled from `DRAFT`, `PRICED`, `CONFIRMED`, or `PACKED`, moving it to the terminal `CANCELLED` state, with compensation that depends on how far it had progressed. Cancelling a `DRAFT` or `PRICED` order has no financial or inventory side effect. Cancelling a `CONFIRMED` order releases its credit hold: the account's committed exposure decreases by the order's `held_exposure_cents`, and that held amount is reset to zero. Cancelling a `PACKED` order does both — it releases the credit hold in the same way, and it also releases the inventory: for each line, the line's `net_grams` are restored to its `allocated_lot_id`, and any lot that was `DEPLETED` transitions `DEPLETED → AVAILABLE`, cascading its product's `stock_state` back toward `IN_STOCK`. In every case the order's `held_exposure_cents` ends at zero.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or drive a state transition on an existing resource return `200 OK`. Wherever a `PlatformAdmin` is not listed explicitly below, it may still perform the operation as a hierarchical override of the owning peer role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a catalog product (SIMPLE or BLEND) | CatalogManager, PlatformAdmin |
| GET | `/products/{id}` | Fetch one product | CatalogManager, ProductionOperator, SalesAgent, Wholesaler, PlatformAdmin |
| GET | `/products` | List products with optional filters | CatalogManager, ProductionOperator, SalesAgent, Wholesaler, PlatformAdmin |
| POST | `/products/{id}/discontinue` | Discontinue a product | CatalogManager, PlatformAdmin |
| POST | `/blend-components` | Attach a SIMPLE component to a BLEND product | CatalogManager, PlatformAdmin |
| GET | `/blend-components/{id}` | Fetch one blend component | CatalogManager, ProductionOperator, SalesAgent, PlatformAdmin |
| GET | `/blend-components` | List blend components | CatalogManager, ProductionOperator, SalesAgent, PlatformAdmin |
| POST | `/inventory-lots` | Receive a lot of a product into inventory | CatalogManager, PlatformAdmin |
| GET | `/inventory-lots/{id}` | Fetch one lot | CatalogManager, ProductionOperator, SalesAgent, PlatformAdmin |
| GET | `/inventory-lots` | List lots by product, batch, or status | CatalogManager, ProductionOperator, SalesAgent, PlatformAdmin |
| POST | `/production-lines` | Create a production line | ProductionOperator, PlatformAdmin |
| GET | `/production-lines/{id}` | Fetch one production line | ProductionOperator, CatalogManager, SalesAgent, PlatformAdmin |
| POST | `/batches` | Schedule a blend production batch on a line window | ProductionOperator, PlatformAdmin |
| GET | `/batches/{id}` | Fetch one batch | ProductionOperator, CatalogManager, PlatformAdmin |
| GET | `/batches` | List batches by blend product, line, or status | ProductionOperator, CatalogManager, PlatformAdmin |
| POST | `/batches/{id}/produce` | Produce the batch: draw components FEFO, mint output lot | ProductionOperator, PlatformAdmin |
| POST | `/labeling-stations` | Create a gift-tin labeling station | ProductionOperator, PlatformAdmin |
| GET | `/labeling-stations/{id}` | Fetch one labeling station | ProductionOperator, CatalogManager, PlatformAdmin |
| POST | `/tin-runs` | Schedule a gift-tin packing run on a station window | ProductionOperator, PlatformAdmin |
| GET | `/tin-runs/{id}` | Fetch one tin run | ProductionOperator, CatalogManager, PlatformAdmin |
| GET | `/tin-runs` | List tin runs by station | ProductionOperator, CatalogManager, PlatformAdmin |
| POST | `/wholesale-accounts` | Open a wholesale account | SalesAgent, PlatformAdmin |
| GET | `/wholesale-accounts/{id}` | Fetch one account with live exposure fields | SalesAgent, Wholesaler, PlatformAdmin |
| GET | `/wholesale-accounts` | List accounts by status or tier | SalesAgent, PlatformAdmin |
| POST | `/wholesale-accounts/{id}/suspend` | Suspend an account | SalesAgent, PlatformAdmin |
| POST | `/wholesale-accounts/{id}/reinstate` | Reinstate an account | SalesAgent, PlatformAdmin |
| POST | `/orders` | Open a DRAFT order for a wholesale account | SalesAgent, Wholesaler, PlatformAdmin |
| GET | `/orders/{id}` | Fetch one order | SalesAgent, Wholesaler, ProductionOperator, PlatformAdmin |
| GET | `/orders` | List orders by account or fulfillment status | SalesAgent, Wholesaler, ProductionOperator, PlatformAdmin |
| POST | `/orders/{id}/lines` | Add a bulk line to a DRAFT order | SalesAgent, Wholesaler, PlatformAdmin |
| POST | `/orders/{id}/price` | Price a DRAFT order; stamp provisional totals | SalesAgent, Wholesaler, PlatformAdmin |
| POST | `/orders/{id}/confirm` | Confirm a PRICED order with OCC and credit gate | SalesAgent, Wholesaler, PlatformAdmin |
| POST | `/orders/{id}/pack` | Pack a CONFIRMED order: weigh, FEFO-allocate, finalize | ProductionOperator, PlatformAdmin |
| POST | `/orders/{id}/ship` | Ship a PACKED order | SalesAgent, PlatformAdmin |
| POST | `/orders/{id}/cancel` | Cancel an order and compensate holds/allocations | SalesAgent, Wholesaler, PlatformAdmin |
| GET | `/order-lines/{id}` | Fetch one order line | SalesAgent, Wholesaler, ProductionOperator, PlatformAdmin |
| GET | `/order-lines` | List order lines by order, product, or allocated lot | SalesAgent, Wholesaler, ProductionOperator, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (UTC) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_LINE_RESOURCE_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_TIN_RUN_NOT_FOUND` | 404 |
| `ERR_COMPONENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ALLERGEN_LABEL_REQUIRED` | 409 |
| `ERR_LOT_EXPIRED` | 409 |
| `ERR_LINE_WINDOW_CONFLICT` | 409 |
| `ERR_STATION_BUFFER_CONFLICT` | 409 |
| `ERR_WINDOW_INVALID` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_PRODUCT_NOT_BLEND` | 422 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_INVALID_RATIO` | 422 |
| `ERR_DUPLICATE_COMPONENT` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
