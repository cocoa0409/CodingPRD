# Promo Products API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Promo Products API, the operational backbone of a promotional-products and branded-swag distributor in the mold of firms such as 4imprint and ASI-network suppliers. The business takes a buyer's logo, prints or embroiders or laser-engraves it onto catalog blanks — tote bags, drinkware, apparel — sourced from decorator suppliers, and delivers finished goods against a promised in-hands date. The domain is unusually rich because a single order threads through catalog pricing, an art-approval hand-off between the sales desk and the buyer, supplier procurement of undecorated blanks, shop-floor decoration with real-world spoilage, and a prepaid-credit settlement model.

The API must model several concerns that ordinary storefronts ignore. Pricing is quantity-tiered and decoration-method specific, with one-time setup charges and per-color run charges layered on top. Orders can be rushed when the in-hands date is close, adding a surcharge. Buyers must approve an art proof before anything is printed, and that approval is deliberately segregated from the sales representative who prepares it. Blanks are procured from capacity-constrained suppliers whose concurrent production load must never be over-committed. Finally, because presses spoil a fraction of every run, the quantity a buyer is billed for at shipment can legitimately differ from the quantity quoted, within a tolerance band. Every one of these behaviors is a contract the implementation must honor exactly.

The system is deterministic and test-driven: a logical clock replaces wall-clock time so that lead-time and rush calculations are reproducible, and all money is handled in integer cents to eliminate floating-point drift.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's operational capacity. A request missing either header, or presenting an `X-User-Role` that is not one of the four recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is valid but not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `CatalogAdmin`, `AccountManager`, `ProductionManager`, and `Customer`.

- `CatalogAdmin` owns catalog and configuration data — suppliers, products, price breaks, decoration stations, and customer prepaid accounts — and operates the logical clock.
- `AccountManager` is the internal sales desk: it builds orders, quotes and confirms and cancels them, prepares and submits art proofs, sources blanks through purchase orders, and places reorders.
- `ProductionManager` runs the shop floor: releasing orders to production, scheduling stations, running and inspecting decoration, receiving blanks, and shipping and delivering.
- `Customer` is the buyer acting on their own account: placing and funding orders, paying, and approving or rejecting art proofs.

Three of the four roles carry an **opaque identity**. When `X-User-Role` is `CatalogAdmin`, `AccountManager`, or `ProductionManager`, the `X-User-ID` is an operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. The `Customer` role, by contrast, is **entity-backed**: when `X-User-Role` is `Customer`, the `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any order-scoped resource compare that resource's owning `customer_id` (reached through the order, line, or proof) to `X-User-ID`; when a `Customer` acts on a resource that belongs to a different customer, the request is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403). When a `Customer` creates or reorders an order, the `customer_id` supplied must be their own.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 or above 100 is clamped into that range rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION`.

Unless otherwise stated, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of server-managed fields. Every resource receives an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created.

Resources that can be mutated after creation additionally carry two fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every change to the resource, and `version`, an integer that starts at 1 on creation and increments by one on every mutation. Suppliers, products, customers, orders, order lines, art proofs, purchase orders, and shipments all carry `updated_at` and `version`.

Two entity kinds are immutable configuration and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: a `PriceTier` (a product's quantity price break) and a `DecorationStation`. Clients must not expect concurrency or modification metadata on those two.

### 2.5. Monetary Precision and Integer-Cent Arithmetic

All money in the system is represented and computed in **integer cents**. Unit costs, prices, setup and run charges, escrow, credit, deposits, and order totals are integers; there is no sub-cent representation. Because pricing arithmetic (tier price times quantity, plus setup) is entirely integer multiplication and addition, no rounding is applied there.

The single place rounding occurs is the **rush surcharge**. The surcharge is a percentage of a summed subtotal, and it is rounded exactly once, using the round-half-up method, after the per-line subtotals have been summed — never rounded per line and then summed. The deposit requirement likewise involves a fractional multiplier and is resolved by taking the ceiling (see §3.5). Wherever a percentage produces a fractional cent, the specific rounding direction stated for that calculation governs; nothing is left to implementer discretion.

### 2.6. The Logical Clock

Lead-time, rush classification, and shipment timestamps must be reproducible, so the system never reads the host wall-clock. Instead it maintains a **logical clock** whose value is `2026-05-01T00:00:00Z` until it is explicitly set. An operator advances or sets the clock by supplying a `to_iso8601` instant; the clock then holds that value until set again. All date arithmetic — the whole-day gap to an order's `in_hands_date`, and the `shipped_at` stamp recorded on a shipment — reads this logical clock and never falls back to real time.

### 2.7. Optimistic Concurrency Control

Creating a new art proof for an order line is guarded by optimistic concurrency control. The create request must carry `expected_order_line_version` as a required field, holding the `version` of the target `OrderLine` that the client last observed. If that value does not match the line's current `version` — because another writer has created a proof and advanced the line's version since the client last read it — the request is rejected with `ERR_STALE_ORDER_LINE_VERSION` (HTTP 412). Because a newly created proof legitimately supersedes the line's prior active proof, and only one active proof may exist per line, this check prevents a client operating on a stale view of the line from silently superseding a proof it never saw. No other endpoint takes a version field; art-proof creation is the sole OCC-guarded write.

### 2.8. Hierarchical Consistency and Cascading Side Effects

The system keeps parent and child resources aligned automatically. Whenever an operation mutates a resource, that resource's `updated_at` is refreshed and its `version` incremented; this applies equally to the resource directly targeted and to any resource the server touches as a downstream effect. A single client action can therefore ripple through several entities: approving an art proof bubbles the owning line forward and re-evaluates the order's art-completion flag; confirming an order cascades a state change and a price-lock onto each of its lines; cancelling an order cascades through its lines, then through the purchase orders sourcing those lines, then back onto the affected suppliers' reservation counters. Each such propagation is a genuine mutation of the affected resource. The precise cascades are described in the workflow narratives of §3; the governing rule here is that the system, not the client, performs them, and performs all hops of a cascade, not merely the first.

### 2.9. Nested Retrieval and Validation Ordering

When an endpoint path names more than one resource, the identifiers are validated left to right, and the first identifier that does not resolve produces that resource's not-found error before any deeper resource is examined. The full family of existence errors is `ERR_SUPPLIER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRICE_TIER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ART_PROOF_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`, and `ERR_SHIPMENT_NOT_FOUND`, each returned with HTTP 404.

Across the whole API, checks are applied in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication — headers present and role known, else `ERR_UNAUTHENTICATED`; (2) authorization — the role is permitted and, for an entity-backed `Customer`, owns the target, else `ERR_UNAUTHORIZED` or `ERR_NOT_ORDER_OWNER`; (3) existence — every path and body id resolves, else the matching not-found error; (4) resource state — the target is in the state the transition requires, else the matching state error such as `ERR_ORDER_NOT_QUOTED`; (5) cross-entity referential rules; (6) temporal rules; (7) quantity, capacity, and value constraints; (8) fiscal (money) rules; and (9) low-cost field-format checks on time windows. A malformed request body — a missing required field, wrong type, or an invalid enum value — is rejected with `ERR_VALIDATION` (HTTP 400). When a supplied production or scheduling window has an end that is not strictly after its start, or an unparseable date is supplied, the rejection is `ERR_INVALID_TIME_WINDOW` (HTTP 422).

### 2.10. Prepaid Credit and Escrow Conservation

Every buyer operates a prepaid account. A `Customer` is created with an `initial_credit_cents` funding amount; the account then exposes two read-only figures. The `total_funded_cents` is the total money ever funded into the account — in this version it equals `initial_credit_cents` and is the conserved quantity. The `credit_balance_cents` is the currently available credit: `total_funded_cents` minus the sum of `escrow_cents` held by that customer's orders that have not been refunded. Money is never created or destroyed by a payment — it moves from `credit_balance_cents` into an order's `escrow_cents`, and a cancellation moves it back. This credit-plus-escrow conservation invariant holds at all times.

### 2.11. Supplier Capacity and the Reservation Ledger

Each supplier carries a read-only `reserved_blank_qty` that reflects its currently committed load: the sum of `ordered_blank_qty` across that supplier's purchase orders in the `ISSUED` state. The counter starts at 0 when the supplier is created and is maintained as an invariant — it rises when a purchase order is issued and falls when that order is received or cancelled. No supplier may be over-committed: the aggregate issued load over any instant of a proposed production window, plus the new order's quantity, must respect the supplier's `concurrent_capacity_units`, as detailed in §3.4.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations

Before any order can be built, a `CatalogAdmin` seeds the catalog. A **supplier** is a decorator or blank vendor, created with a `name`, the `blank_unit_cost_cents` the distributor pays that vendor per undecorated unit, and a `concurrent_capacity_units` ceiling describing how many blank units the vendor can have in production at any one instant. A freshly created supplier begins with its `reserved_blank_qty` at zero.

A **product** is a catalog blank, created with a `supplier_id` naming the vendor that sources it, a `sku` code, a `name` such as "12oz Cotton Tote", and a `min_order_qty` below which no single line may order it. Attached to each product are its **price tiers**: quantity price breaks, each carrying the `product_id` it belongs to, a `decoration_method`, a `min_quantity` marking the inclusive lower bound of the tier, and the decorated first-color `unit_price_cents` at that break. A `decoration_method` is always one of `SCREEN_PRINT`, `EMBROIDERY`, or `LASER_ENGRAVE`.

A **decoration station** is a physical press, created with a `name` and a `station_type` — one of `SCREEN_PRESS`, `EMBROIDERY_MACHINE`, or `LASER`. Finally, a **customer** prepaid account is created with a `name` and an `initial_credit_cents` funding amount; at creation the account's `total_funded_cents` and `credit_balance_cents` are both set equal to `initial_credit_cents`.

### 3.2. Building an Order and Pricing Its Lines

An order is opened as a draft by a `Customer` or an `AccountManager`, who supplies the owning `customer_id`, an optional `order_type`, an optional `reorder_source_order_id`, and the `in_hands_date` by which finished goods must reach the buyer. The `order_type` is one of `STANDARD`, `SAMPLE`, or `REORDER` and defaults to `STANDARD`; `reorder_source_order_id` is populated only for a reorder (see §3.9). A new order begins with `fulfillment_status` of `DRAFT`, `payment_status` of `UNPAID`, and `escrow_cents` of 0; its `is_rush` and `art_complete` flags are false, its `quoted_subtotal_cents`, `quoted_rush_cents`, `quoted_total_cents`, and `deposit_required_cents` are 0, and its `final_subtotal_cents`, `final_rush_cents`, and `final_total_cents` are null until shipment strikes them.

Into a draft order, lines are added; the line-creation endpoint applies no fulfillment-status precondition to the parent order, so a line may in fact be added regardless of the order's current `fulfillment_status`. Each **order line** names the `product_id` being decorated, the `decoration_method` to apply, the `quantity` of decorated units, and an optional `imprint_color_count` that defaults to 1. On creation a line enters status `PENDING_ART`, its pricing fields are computed immediately, and the parent order's `art_complete` flag is recomputed (and thereby becomes false, since the new line has no approved art). A line also owns several computed and lifecycle fields set later in the workflow: its `order_id`, an assigned `station_id`, a `scheduled_start` and `scheduled_end`, the selected `unit_price_cents`, the `line_setup_cents`, the `line_subtotal_cents`, a `locked_unit_price_cents`, and the production-outcome fields `produced_qty`, `spoiled_qty`, `good_qty`, and `final_line_subtotal_cents`. The line's lifecycle `status` field moves through `PENDING_ART`, `ART_READY`, `CONFIRMED`, `SCHEDULED`, `PRINTING`, `QC_HOLD`, and `COMPLETED`, or to `CANCELLED`. Purchase orders and art proofs likewise expose their own `status` field.

**Line pricing (`line_subtotal_cents`).** Pricing selects a tier, then adds color-driven run and setup charges. First, among the product's price tiers whose `decoration_method` matches the line and whose `min_quantity` is less than or equal to the line's `quantity`, the system selects the tier with the largest `min_quantity`; that tier's `unit_price_cents` is the decorated first-color unit price. If no tier qualifies, the line is rejected with `ERR_TIER_NOT_FOUND`. The number of extra colors is the `imprint_color_count` minus one. The per-unit run charge for those extra colors is the extra-color count multiplied by the method's per-unit extra-color run charge; adding it to the tier unit price gives the effective per-unit price, and multiplying that by the line `quantity` gives the goods amount. The one-time setup charge (`line_setup_cents`) is the method's first-color setup charge plus the extra-color count multiplied by the method's per-additional-color setup charge. The line subtotal is the goods amount plus the setup charge.

The method-specific constants are fixed. For `SCREEN_PRINT`, the first-color setup is 2500 cents, each additional color adds 1500 cents of setup, each extra color adds 40 cents per unit of run charge, and a line may use at most 6 colors. For `EMBROIDERY`, the first-color setup is 4000 cents, additional colors add no setup and no run charge, and at most 12 colors are allowed. For `LASER_ENGRAVE`, the first-color setup is 3000 cents, there is no additional-color setup or run charge, and exactly 1 color is the maximum. A line whose `imprint_color_count` exceeds its method's color ceiling is rejected with `ERR_MAX_COLORS_EXCEEDED`. A line whose `quantity` is below the product's `min_order_qty` is rejected with `ERR_BELOW_MIN_QUANTITY`.

**Sample orders.** When the order's `order_type` is `SAMPLE`, two pricing and tolerance concessions apply. The line's `line_setup_cents` is forced to 0 — setup is waived on samples — so a sample line's subtotal is purely its goods amount. Additionally, a sample line's `quantity` may not exceed the configured sample maximum `SAMPLE_MAX_QTY`, whose value is 12; a sample line above that ceiling is rejected with `ERR_SAMPLE_QTY_EXCEEDED`. When more than one line-creation constraint would fail, they are evaluated in the fixed order: below the product's `min_order_qty` (`ERR_BELOW_MIN_QUANTITY`), then no qualifying price tier (`ERR_TIER_NOT_FOUND`), then `imprint_color_count` over the method's color ceiling (`ERR_MAX_COLORS_EXCEEDED`), then a sample `quantity` over `SAMPLE_MAX_QTY` (`ERR_SAMPLE_QTY_EXCEEDED`).

### 3.3. The Art Proof Approval Cycle

Nothing is printed until the buyer signs off on the artwork, and the sign-off is deliberately segregated from the person who prepares it. An `AccountManager` creates an **art proof** against a line, supplying the rendered `proof_url`, optional `notes`, and the required `expected_order_line_version` (§2.7). The new proof is assigned a `revision_number` — 1 for the first proof on a line, incremented for each superseding proof — starts in status `DRAFT`, and its creation increments the owning line's `version` by one. If the line already had a non-terminal proof, that prior proof is moved to `SUPERSEDED`; and if the superseded proof had been `APPROVED`, the line reverts from `ART_READY` back to `PENDING_ART` and the order's `art_complete` is recomputed. A proof also carries a computed `approved_version` (see below) and references its `order_line_id`.

The proof then travels a small cyclic workflow. The `AccountManager` submits a proof, advancing it from `DRAFT` to `PENDING_APPROVAL`; a proof not in `DRAFT` (or in `CHANGES_REQUESTED`) at submit time yields `ERR_ART_INVALID_STATE`. The buyer — a `Customer` who must own the parent order — reviews the pending proof. The buyer may reject it, moving it from `PENDING_APPROVAL` to `CHANGES_REQUESTED` and optionally attaching revised `notes`; from there the `AccountManager` resubmits, moving `CHANGES_REQUESTED` back to `PENDING_APPROVAL` and closing the revision loop. Alternatively the buyer approves it, moving `PENDING_APPROVAL` to `APPROVED`. On approval three things happen: the proof's `approved_version` is pinned to the parent line's current `version`; the parent line bubbles from `PENDING_ART` to `ART_READY`; and the order's `art_complete` is recomputed. Both buyer actions require ownership of the parent order, failing with `ERR_NOT_ORDER_OWNER` otherwise, and both require the proof to be in `PENDING_APPROVAL`, failing with `ERR_ART_INVALID_STATE` otherwise. The order's `art_complete` becomes true precisely when every non-cancelled line has an `APPROVED` proof.

### 3.4. Sourcing Blanks Through Purchase Orders

Undecorated blanks are procured from suppliers through **purchase orders**. An `AccountManager` drafts a purchase order against a specific line by supplying that `order_line_id`, the `supplier_id` fulfilling the blanks, the `ordered_blank_qty`, and the supplier production window `production_start` and `production_end`. The purchase order copies the line's `order_id` and `product_id` from the line, and begins in status `DRAFT`. At most one active (non-cancelled) purchase order may exist for a line; a second attempt is rejected with `ERR_PO_ALREADY_EXISTS`. If the line's product is not sourced by the supplied supplier — that is, the product's `supplier_id` differs from the request's `supplier_id` — the create is rejected with `ERR_LINE_PRODUCT_MISMATCH`. A window whose `production_end` is not strictly after its `production_start` is rejected with `ERR_INVALID_TIME_WINDOW`.

Issuing a purchase order advances it from `DRAFT` to `ISSUED`; a purchase order not in `DRAFT` at issue time yields `ERR_PO_INVALID_STATE`. Issuing is capacity-gated. The system treats each issued purchase order as occupying its half-open production window `[production_start, production_end)` with a load equal to its `ordered_blank_qty`. For the window being issued, consider every instant within `[production_start, production_end)`: the peak concurrent load is the maximum over those instants of the new order's `ordered_blank_qty` plus the sum of `ordered_blank_qty` of all already-`ISSUED` purchase orders on the same supplier whose own windows contain that instant. If that peak exceeds the supplier's `concurrent_capacity_units`, the issue is rejected with `ERR_SUPPLIER_CAPACITY_EXCEEDED`. On a successful issue, the `estimated_blank_cost_cents` is computed as `ordered_blank_qty` multiplied by the supplier's `blank_unit_cost_cents`, and the supplier's `reserved_blank_qty` is increased by `ordered_blank_qty`.

Receiving a purchase order advances it from `ISSUED` to `RECEIVED` and requires a `received_blank_qty`; a purchase order not in `ISSUED` yields `ERR_PO_INVALID_STATE`. On receipt the `actual_blank_cost_cents` is computed as `received_blank_qty` multiplied by the supplier's `blank_unit_cost_cents` (this differs from the estimate whenever the supplier under- or over-ships), and the supplier's `reserved_blank_qty` is decreased by `ordered_blank_qty`, releasing the reservation. Cancelling a purchase order is permitted while it is in `DRAFT` or `ISSUED`; any other state yields `ERR_PO_INVALID_STATE`. When the cancelled purchase order had been `ISSUED`, the supplier's `reserved_blank_qty` is decreased by `ordered_blank_qty` as a compensating release.

### 3.5. Quoting, Deposits, and Payment

Once a draft order has at least one line, an `AccountManager` quotes it, advancing `fulfillment_status` from `DRAFT` to `QUOTED`. Quoting on an order not in `DRAFT` yields `ERR_ORDER_NOT_DRAFT`, and quoting an order with no non-cancelled lines yields `ERR_NO_ORDER_LINES`. Quoting fixes several figures. First it fixes the rush flag: the whole-day lead is the number of whole days from the current logical-clock date at midnight UTC to the `in_hands_date` at midnight UTC (the floor of the date difference), and the order's `is_rush` is true when that lead is strictly less than 10 days.

The order totals are then computed. The `quoted_subtotal_cents` is the sum of `line_subtotal_cents` over the non-cancelled lines, using their ordered quantities. The `quoted_rush_cents` is the rush surcharge: when `is_rush` is true, it is 20 percent of the quoted subtotal, rounded half-up exactly once after the lines have been summed; when `is_rush` is false, it is 0. The `quoted_total_cents` is the quoted subtotal plus the quoted rush. Finally the `deposit_required_cents` is set to the ceiling of the quoted total multiplied by 50 percent.

Payment moves money from the buyer's prepaid credit into the order's escrow and is performed by the owning `Customer`, who supplies an `amount_cents`. Each payment requires the customer's `credit_balance_cents` to be at least `amount_cents`, else `ERR_INSUFFICIENT_CREDIT`. On a successful payment the customer's `credit_balance_cents` is decreased by `amount_cents` and the order's `escrow_cents` is increased by the same amount, preserving the conservation invariant of §2.10. The `payment_status` axis then reflects the escrow relative to the required deposit and the quoted total: it moves to `DEPOSIT_PAID` once escrow has reached `deposit_required_cents` but is still below `quoted_total_cents`, and to `PAID_IN_FULL` once escrow has reached `quoted_total_cents` (whether it arrives there from `UNPAID` in one payment or from `DEPOSIT_PAID` in a later one).

### 3.6. Confirmation and Release to Production

Confirming an order is the gate between sales and the shop floor and is performed by an `AccountManager`, advancing `fulfillment_status` from `QUOTED` to `CONFIRMED`. Four preconditions guard confirmation, and they are evaluated in the system's fixed priority order so that the earliest failing check is the one reported. The order must be in `QUOTED`, else `ERR_ORDER_NOT_QUOTED`. Then, as a cross-entity referential check, every non-cancelled line must have an `APPROVED` art proof — that is, `art_complete` must be true — else `ERR_ART_NOT_APPROVED`. Then, as a temporal check, the whole-day lead from the current logical-clock date to the `in_hands_date` must be at least 3 days, else `ERR_INSUFFICIENT_LEAD_TIME`. Finally, as a fiscal check, the order's `escrow_cents` must be at least `deposit_required_cents`, else `ERR_DEPOSIT_REQUIRED`. On success, each non-cancelled line advances from `ART_READY` to `CONFIRMED` and its `locked_unit_price_cents` is pinned to its current `unit_price_cents`, freezing the price against later catalog changes.

Releasing an order to production is performed by a `ProductionManager`, advancing `fulfillment_status` from `CONFIRMED` to `IN_PRODUCTION`. The order must be in `CONFIRMED`, else `ERR_ORDER_NOT_CONFIRMED`, and every non-cancelled line must be in `CONFIRMED`, else `ERR_LINE_INVALID_STATE`.

### 3.7. The Shop Floor: Scheduling, Printing, and QC

With an order in production, a `ProductionManager` works each line through decoration. Scheduling a line assigns it a station and a production window, advancing the line's status from `CONFIRMED` to `SCHEDULED`; the request supplies the `station_id`, the `scheduled_start`, and the `scheduled_end`. Several conditions apply. The line must be in `CONFIRMED`, else `ERR_LINE_INVALID_STATE`, and its parent order must be `IN_PRODUCTION`, else `ERR_ORDER_NOT_IN_PRODUCTION`. The line's active (non-cancelled) purchase order must have reached `RECEIVED`, else `ERR_PO_NOT_RECEIVED` — blanks must be in hand before a press is booked. An unparseable `scheduled_start` or `scheduled_end` is rejected with `ERR_INVALID_TIME_WINDOW`. The window must next not collide with another booking on the same station: treating each window as the half-open interval `[scheduled_start, scheduled_end)`, two windows overlap when this line's start is before the other's end and the other's start is before this line's end. Adjacency — where one window's end equals the next window's start — is permitted and is not an overlap. If the proposed window overlaps any other non-cancelled line already assigned to that `station_id`, the schedule is rejected with `ERR_STATION_DOUBLE_BOOKED`. Finally, as a low-cost field-format check applied after the double-booking check (per the priority order of §2.9), a supplied window whose `scheduled_end` is not strictly after its `scheduled_start` is rejected with `ERR_INVALID_TIME_WINDOW`. On success the `station_id`, `scheduled_start`, and `scheduled_end` are recorded on the line.

Starting the print advances the line from `SCHEDULED` to `PRINTING`; a line not in `SCHEDULED` yields `ERR_LINE_INVALID_STATE`. Completing the run advances the line from `PRINTING` to `QC_HOLD` and records the run outcome: the request supplies `produced_qty` and `spoiled_qty`, the spoiled count must satisfy at least zero and at most the produced count, else `ERR_PRODUCED_QTY_INVALID`, and the line's `good_qty` is set to `produced_qty` minus `spoiled_qty`. A line not in `PRINTING` yields `ERR_LINE_INVALID_STATE`.

Quality control resolves the run. The `ProductionManager` submits a `result` of either PASS or REJECT on a line in `QC_HOLD` (otherwise `ERR_LINE_INVALID_STATE`). A REJECT sends the line from `QC_HOLD` back to `PRINTING` for a rework run, clearing `produced_qty`, `spoiled_qty`, and `good_qty` back to unset. A PASS completes the line, advancing it from `QC_HOLD` to `COMPLETED`, but only if the good count falls within the spoilage tolerance band. Using the ordered `quantity` as the reference, the minimum acceptable good count is the quantity minus the floor of the quantity times 5 percent, and the maximum acceptable good count is the quantity plus the floor of the quantity times 5 percent; the `good_qty` must be at least the minimum and at most the maximum, both bounds inclusive, else the pass is rejected with `ERR_SPOILAGE_OUT_OF_TOLERANCE`. For a `SAMPLE` order the band collapses to exactly the ordered quantity at both ends — no under- or over-run is allowed. On a passing QC, the line's `final_line_subtotal_cents` is computed as the effective per-unit price (the `locked_unit_price_cents` plus the same extra-color per-unit run charge that applied at pricing) multiplied by the `good_qty`, plus the `line_setup_cents`.

### 3.8. Shipment, Final Reconciliation, and Delivery

When every non-cancelled line of an in-production order has reached `COMPLETED`, a `ProductionManager` ships the order. Creating a **shipment** names the `order_id` being shipped, a `carrier`, and an optional `tracking_number`, and advances the order's `fulfillment_status` from `IN_PRODUCTION` to `SHIPPED`. The order must be in `IN_PRODUCTION`, else `ERR_ORDER_NOT_IN_PRODUCTION`, and every non-cancelled line must be `COMPLETED`, else `ERR_LINE_INVALID_STATE`.

Shipment is the moment the order's final, actual totals are struck. The `final_subtotal_cents` is the sum of `final_line_subtotal_cents` — each based on actual `good_qty` — over the non-cancelled lines. The `final_rush_cents` is the rush surcharge applied to that final subtotal, computed the same way as at quote: when `is_rush` is true, 20 percent of the final subtotal rounded half-up exactly once after summing, else 0. The `final_total_cents` is the final subtotal plus the final rush. Because good quantities can differ from ordered quantities within the spoilage band, these final figures may differ from the quoted ones. The shipment itself records a snapshot: its `final_total_cents` copies the order's final total, its `total_good_qty` is the sum of `good_qty` across the order's non-cancelled lines, and its `shipped_at` is the current logical-clock time.

Delivery closes the order: a `ProductionManager` marks a shipped order delivered, advancing `fulfillment_status` from `SHIPPED` to `DELIVERED`. The order must be in `SHIPPED`, else `ERR_ORDER_NOT_SHIPPED`. `DELIVERED` is terminal.

### 3.9. Reorders, Cancellation, and Refunds

A delivered order can seed a **reorder**. A `Customer` or `AccountManager` reorders from a source order by supplying a new `in_hands_date`; the system creates a fresh order with `order_type` of `REORDER` and its `reorder_source_order_id` set to the source order, copying the source's lines in as new `PENDING_ART` lines with pricing recomputed against current catalog tiers. The source order must be in `DELIVERED`, else the reorder is rejected with `ERR_REORDER_SOURCE_NOT_DELIVERED`.

Cancellation unwinds an order and refunds its escrow. An `AccountManager` may cancel an order while its `fulfillment_status` is `DRAFT`, `QUOTED`, or `CONFIRMED`; any other state yields `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order to `CANCELLED` and runs a cascade. In the first hop, every non-cancelled line of the order is moved to `CANCELLED`. In the second hop, for each such line whose active purchase order is in `ISSUED`, that purchase order is moved to `CANCELLED`. In the third hop, each of those cancelled purchase orders releases its supplier's reservation by decreasing that supplier's `reserved_blank_qty` by the purchase order's `ordered_blank_qty`. Independently, the escrow is refunded: the order's `escrow_cents` is returned to the owning customer's `credit_balance_cents`, the order's `escrow_cents` is set to 0, and its `payment_status` moves to `REFUNDED`. Because a refunded order no longer holds escrow, the customer's available credit is restored in full, consistent with the conservation invariant.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state-transition action — return `200 OK`. The logical-clock setter returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/suppliers` | Create a supplier | CatalogAdmin |
| GET | `/suppliers/{supplierId}` | Get a supplier | CatalogAdmin, AccountManager, ProductionManager |
| POST | `/products` | Create a catalog product (blank) | CatalogAdmin |
| GET | `/products/{productId}` | Get a product | CatalogAdmin, AccountManager, ProductionManager, Customer |
| GET | `/products` | List products, optionally filtered by supplier | CatalogAdmin, AccountManager, ProductionManager, Customer |
| POST | `/products/{id}/price-tiers` | Add a quantity price break for a product + method | CatalogAdmin |
| GET | `/products/{id}/price-tiers` | List a product's price tiers | CatalogAdmin, AccountManager, ProductionManager, Customer |
| POST | `/decoration-stations` | Create a decoration station/press | CatalogAdmin |
| GET | `/decoration-stations/{stationId}` | Get a decoration station | CatalogAdmin, AccountManager, ProductionManager |
| POST | `/customers` | Create a customer prepaid account | CatalogAdmin |
| GET | `/customers/{customerId}` | Get a customer | CatalogAdmin, AccountManager, Customer |
| POST | `/orders` | Create a draft order | Customer, AccountManager |
| GET | `/orders/{orderId}` | Get an order | Customer, AccountManager, ProductionManager, CatalogAdmin |
| GET | `/orders` | List orders, optionally filtered by customer or reorder source | Customer, AccountManager, ProductionManager, CatalogAdmin |
| POST | `/orders/{orderId}/lines` | Add a line to a draft order | Customer, AccountManager |
| POST | `/orders/{orderId}/quote` | Quote the order (lock pricing, rush, deposit) | AccountManager |
| POST | `/orders/{orderId}/confirm` | Confirm the order for production | AccountManager |
| POST | `/orders/{orderId}/start-production` | Release the order to the shop floor | ProductionManager |
| POST | `/orders/{orderId}/cancel` | Cancel an order (cascade lines/POs, refund escrow) | AccountManager |
| POST | `/orders/{orderId}/deliver` | Mark a shipped order delivered | ProductionManager |
| POST | `/orders/{orderId}/payments` | Apply a payment from customer credit into order escrow | Customer |
| POST | `/orders/{sourceOrderId}/reorder` | Create a new order by copying a delivered source order's lines | Customer, AccountManager |
| GET | `/order-lines/{lineId}` | Get an order line | Customer, AccountManager, ProductionManager, CatalogAdmin |
| GET | `/order-lines` | List order lines filtered by order/product/station | Customer, AccountManager, ProductionManager, CatalogAdmin |
| POST | `/order-lines/{lineId}/schedule` | Assign a station and production window to a line | ProductionManager |
| POST | `/order-lines/{lineId}/start-print` | Begin the decoration run | ProductionManager |
| POST | `/order-lines/{lineId}/complete-run` | Record produced and spoiled units | ProductionManager |
| POST | `/order-lines/{lineId}/qc` | QC decision (PASS completes, REJECT reworks) | ProductionManager |
| POST | `/order-lines/{id}/art-proofs` | Create a new art proof for a line (OCC on line version) | AccountManager |
| GET | `/order-lines/{id}/art-proofs` | List a line's art proofs | Customer, AccountManager, ProductionManager, CatalogAdmin |
| GET | `/art-proofs/{proofId}` | Get an art proof | Customer, AccountManager, ProductionManager, CatalogAdmin |
| POST | `/art-proofs/{proofId}/submit` | Submit a draft/changes-requested proof for approval | AccountManager |
| POST | `/art-proofs/{proofId}/approve` | Customer approves the proof | Customer |
| POST | `/art-proofs/{proofId}/request-changes` | Customer requests changes | Customer |
| POST | `/purchase-orders` | Create a draft PO to source blanks for a line | AccountManager |
| GET | `/purchase-orders/{poId}` | Get a purchase order | AccountManager, ProductionManager, CatalogAdmin |
| GET | `/purchase-orders` | List POs filtered by line/order/product/supplier | AccountManager, ProductionManager, CatalogAdmin |
| POST | `/purchase-orders/{poId}/issue` | Issue the PO (reserve supplier capacity) | AccountManager |
| POST | `/purchase-orders/{poId}/receive` | Receive blanks | ProductionManager |
| POST | `/purchase-orders/{poId}/cancel` | Cancel a PO (release reservation) | AccountManager |
| POST | `/shipments` | Ship an in-production order (compute final totals, move to SHIPPED) | ProductionManager |
| GET | `/shipments/{shipmentId}` | Get a shipment | Customer, AccountManager, ProductionManager, CatalogAdmin |
| GET | `/shipments` | List shipments filtered by order | Customer, AccountManager, ProductionManager, CatalogAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | CatalogAdmin, AccountManager, ProductionManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_PRICE_TIER_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_ART_PROOF_NOT_FOUND` | 404 |
| `ERR_PURCHASE_ORDER_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_ORDER_NOT_QUOTED` | 409 |
| `ERR_ORDER_NOT_CONFIRMED` | 409 |
| `ERR_ORDER_NOT_IN_PRODUCTION` | 409 |
| `ERR_ORDER_NOT_SHIPPED` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_LINE_INVALID_STATE` | 409 |
| `ERR_ART_INVALID_STATE` | 409 |
| `ERR_PO_INVALID_STATE` | 409 |
| `ERR_STALE_ORDER_LINE_VERSION` | 412 |
| `ERR_ART_NOT_APPROVED` | 409 |
| `ERR_PO_NOT_RECEIVED` | 409 |
| `ERR_PO_ALREADY_EXISTS` | 409 |
| `ERR_LINE_PRODUCT_MISMATCH` | 422 |
| `ERR_REORDER_SOURCE_NOT_DELIVERED` | 409 |
| `ERR_INSUFFICIENT_LEAD_TIME` | 422 |
| `ERR_STATION_DOUBLE_BOOKED` | 409 |
| `ERR_BELOW_MIN_QUANTITY` | 422 |
| `ERR_TIER_NOT_FOUND` | 422 |
| `ERR_MAX_COLORS_EXCEEDED` | 422 |
| `ERR_SAMPLE_QTY_EXCEEDED` | 422 |
| `ERR_NO_ORDER_LINES` | 409 |
| `ERR_PRODUCED_QTY_INVALID` | 422 |
| `ERR_SPOILAGE_OUT_OF_TOLERANCE` | 422 |
| `ERR_SUPPLIER_CAPACITY_EXCEEDED` | 409 |
| `ERR_DEPOSIT_REQUIRED` | 402 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
