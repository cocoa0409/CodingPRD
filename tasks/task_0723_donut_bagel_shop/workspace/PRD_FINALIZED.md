# Donut & Bagel Shop API — Product Requirements Document

## 1. Introduction

This document specifies the back-office and point-of-sale platform for a combined retail and wholesale donut-and-bagel shop. The business runs two intertwined revenue streams on the same physical inventory: a walk-up retail counter that sells single items, dozens, and bulk quantities; and a wholesale operation that bakes to standing route orders, schedules driver deliveries, and bills accounts on credit. Holding these together is the **production day** — a single calendar day of baking whose lifecycle gates when batches may be baked, when the counter may sell, when wholesale routes may be scheduled, and when the day's books may finally be closed.

The platform exists to make a chaotic morning legible. A bake manager plans par-bake quantities the night before, bakes them at dawn, watches the counter sell through them, marks down what is going stale, and sweeps what is left at close. A cashier rings sales and tends a loyalty punch program. A route driver picks, delivers, and the shop invoices wholesale clients against their credit limits. At day's end the shop reconciles: it compares what every baked unit *would* have grossed at full price against what actually came in, net of markdown losses and the cost of swept waste, producing a single variance figure that tells the owner how the day really went.

Because money, inventory, and loyalty value all move together on every sale — and reverse together on every void or refund — the system must treat each operation as a small ledger transaction whose compensations are exact. The sections below define the global contracts every endpoint shares (§2), the day-by-day business workflows where the real logic lives (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or invalid, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401) before any other processing. When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognises exactly five roles, spelled precisely as follows: `ShopAdmin`, `BakeManager`, `Cashier`, `RouteDriver`, and `WholesaleClient`.

- `ShopAdmin` is the operational superset. It owns configuration (creating products and wholesale accounts), the cutoff step of the day lifecycle, refunds, wholesale invoicing, recording wholesale payments, account suspension and reactivation, and pre-order confirmation and fulfilment.
- `BakeManager` owns production: planning and baking batches, sweeping them, and driving the day through its baking, sales, and reconcile transitions.
- `Cashier` owns the retail counter: opening carts, paying them, voiding paid orders, marking down batches, and registering loyalty members.
- `RouteDriver` owns wholesale route execution: picking, delivering, and cancelling deliveries, and may also release deliveries onto a day.
- `WholesaleClient` acts on its own wholesale account: standing orders, pre-orders, and deposits for that account.

For four of the five roles — `ShopAdmin`, `BakeManager`, `Cashier`, and `RouteDriver` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `WholesaleClient`, by contrast, `X-User-ID` is the `id` of the acting `WholesaleAccount`; ownership checks on any resource that references a `WholesaleAccount` (standing orders, pre-orders, deliveries, payments) compare the resource's wholesale-account foreign key to `X-User-ID`.

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

### 2.3. Pagination

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` ascending. For every list response, the `meta` object carries `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records remain beyond the returned page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` in UUID form, with no type prefix. Most resources also carry three system-managed bookkeeping fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at its initial value on creation and increments by one on every mutation that changes the resource. The `created_at` is fixed at creation; `updated_at` is refreshed on every mutation.

All entities in this system — `Product`, `ProductionDay`, `BakeBatch`, `RetailOrder`, `LoyaltyAccount`, `WholesaleAccount`, `StandingOrder`, `WholesaleDelivery`, and `PreOrder` — carry the full set of common fields (`id`, `created_at`, `updated_at`, and `version`).

### 2.5. Monetary Representation, Precision, and Rounding

All monetary amounts are expressed as integer **cents**; there are no fractional-cent values anywhere in the system. Wherever a calculation multiplies a cent amount by a fractional rate (a wholesale discount, a markdown percentage, a deposit percentage), the result is rounded to a whole number of cents using **round half up** (a value ending in exactly one-half rounds away from zero to the next whole cent). Calculations that combine only integer factors — tiered line pricing, for instance — need no rounding and yield exact integer cents directly. Where a calculation specifies an evaluation order (sum first, then discount, then round), that order is mandatory and is spelled out with the calculation in §3.

### 2.6. Nested Resource Addressing

Many resources are addressed through nested paths — a bake batch, a retail order, and a wholesale delivery all live beneath a production day, for example. Path references are validated left to right: the outer resource must exist and the inner resource must genuinely belong to it. If any referenced resource in the path or body does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). This left-to-right existence check is the third validation applied to every request, after authentication and authorisation.

### 2.7. Request Validation Ordering

A consistent precedence governs how a request is screened, and it matters because an earlier failure masks a later one. The order is: first, authentication (`ERR_MISSING_AUTH`); second, role authorisation (`ERR_FORBIDDEN_ROLE`); third, existence of all path and body resource references, checked left-to-right (`ERR_NOT_FOUND`); fourth, request-body well-formedness — required fields present, enum values valid, every line quantity at least 1, and `line_items` non-empty where a body supplies them (`ERR_INVALID_REQUEST`, HTTP 422); fifth, that the parent `ProductionDay` is in the correct status for the operation (`ERR_DAY_INVALID_STATE`, HTTP 409); and sixth, that the target resource itself is in the correct status for the requested transition (HTTP 409, with the error id varying by entity: `ERR_BATCH_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_DELIVERY_INVALID_STATE`, `ERR_PREORDER_INVALID_STATE`, or `ERR_ACCOUNT_INVALID_STATE`). Beyond this shared backbone, individual operations layer further business checks; those are enumerated in §3 in the order they apply, and the most consequential — the wholesale and reconcile guards — are called out explicitly there.

A note on window validation: any endpoint that accepts a start/end window pair (a route stop window or a catering pickup window) requires the end to be strictly after the start; otherwise the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422).

### 2.8. Cascading Side Effects and Compensation

Several operations mutate more than one entity at once, and the system treats those cascades as atomic and exactly reversible. Paying a retail order draws down batch stock and accrues loyalty value; voiding or refunding that order restores the stock and reverses the loyalty value to its pre-sale state. Invoicing a wholesale delivery raises the owning account's outstanding balance; recording a payment lowers it. Whenever any field on a resource changes as part of such a cascade, that resource's `version` increments and its `updated_at` is refreshed. The guiding invariant is compensation symmetry: a sale followed by its reversal, or an invoice followed by a full payment of the same amount, leaves the affected balances exactly where they began.

### 2.9. Optimistic Concurrency on Day Reconciliation

Closing a day's books is the one operation guarded by optimistic concurrency control. The reconcile operation on a production day requires a non-optional input field, `expected_production_day_version`, carrying the client's last observed `version` of that `ProductionDay`. The server compares it to the day's current `version`. If another writer has advanced the day since the client last read it — a batch sweep that froze waste and bumped the day, or a competing reconcile attempt — the values will not match, and the reconcile is rejected with `ERR_STALE_VERSION` (HTTP 412). This refusal prevents the shop from freezing final figures computed against an out-of-date snapshot of the day's pools. No other endpoint accepts or requires a version field.

### 2.10. The Logical Clock

Time-sensitive rules — chiefly the wholesale delivery cutoff — are evaluated against a server-maintained **logical clock** rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until explicitly advanced; before any advance it never reflects real wall-clock time. An administrative capability advances the clock to a supplied instant via the `to_iso8601` field, which lets the delivery-cutoff behaviour be exercised deterministically.

## 3. Business Logic & Workflows

### 3.1. The Product Catalogue and Allergen Labelling

Everything the shop bakes and sells is a `Product`, created by a `ShopAdmin`. Each product carries a `sku` that must be unique across all products, a display `name`, and a `category` that is exactly one of `DONUT` or `BAGEL`. Pricing is layered: `unit_price_cents` is the single-item retail price; `dozen_price_cents` is the price for a full set of twelve; and for large quantities a flat per-unit bulk rate, `bulk_unit_price_cents`, applies to the whole line once the order reaches `bulk_threshold` units. The `bulk_threshold` is optional on creation and defaults to 24 when omitted; whatever its value, it is at least 12. A product also records `unit_cost_cents`, the cost of goods per unit that drives waste accounting, which may be zero but never negative. Each price field — single unit, dozen, and bulk — must be at least 1 cent.

Allergen transparency matters to the counter. A product carries an `allergens` array, defaulting to an empty array, whose members are drawn from the set `WHEAT`, `EGG`, `MILK`, `SOY`, `NUT`, and `SESAME`. The system also tracks an `active` flag, which is true on creation; once a product is retired it becomes false, and a retired product can no longer be added to new batches or orders. Products can be listed (optionally filtered by `category`) and fetched individually, and the catalogue exposes a reverse view that lists every bake batch ever planned for a given product across all days.

### 3.2. Opening a Production Day and the Day Lifecycle

A trading day is represented by a `ProductionDay`, opened by a `ShopAdmin` with a `business_date` (the YYYY-MM-DD calendar date it covers, unique across all production days) and a `delivery_cutoff_utc` — the instant after which no new wholesale delivery may be scheduled and no standing order may be released onto the day. A freshly opened day enters status `OPEN`, and all of its computed reconciliation pools start at zero.

The day advances through a fixed posture sequence that governs which child operations are legal: `OPEN → BAKING → SELLING → CUTOFF → RECONCILED`, with `RECONCILED` terminal. A `BakeManager` starts baking, moving the day from `OPEN` to `BAKING`; this requires the day to currently be `OPEN` (else `ERR_DAY_INVALID_STATE`) and requires at least one bake batch to exist for the day (else `ERR_NO_BATCHES`). The same manager later opens sales, moving `BAKING → SELLING`; this requires the day to be `BAKING` (else `ERR_DAY_INVALID_STATE`) and requires that no bake batch on the day is still in `PLANNED` status — every batch must be `BAKED` or further along (else `ERR_UNBAKED_BATCHES`). A `ShopAdmin` closes the cutoff, moving `SELLING → CUTOFF`, which requires the day to be `SELLING` (else `ERR_DAY_INVALID_STATE`). After cutoff, no new wholesale delivery may be scheduled on the day, but retail orders may still be created, paid, voided, and refunded right up until reconcile. Reconcile itself — moving `CUTOFF → RECONCILED` — is described in §3.9, as it carries the day's heaviest preconditions and its concurrency guard.

A production day can be listed (optionally filtered by `status`) and fetched individually, and the fetched representation exposes its reconciliation pools: `gross_sales_cents`, `markdown_loss_cents`, `waste_cost_cents`, `expected_full_value_cents`, and `reconciliation_variance_cents`. All five read as zero until the day is reconciled, at which point they are computed and frozen.

### 3.3. Planning, Baking, Marking Down, and Sweeping Batches

A `BakeBatch` is the unit of production planning, belonging to a production day (supplied through the day in whose context it is created) and naming the `product_id` it bakes. A `BakeManager` plans a batch with a `par_qty`, the intended par-bake quantity, which must be zero or more; a newly planned batch enters status `PLANNED` with `baked_qty` defaulting to 0. Batches follow the lifecycle `PLANNED → BAKED → MARKED_DOWN → SWEPT`, with `SWEPT` terminal.

When the dough is in the oven, the bake manager bakes the batch, which requires the batch to be `PLANNED` (else `ERR_BATCH_INVALID_STATE`), requires the parent day to be `BAKING` (else `ERR_DAY_INVALID_STATE`), and requires the supplied actual `baked_qty` to be at least 1 (else `ERR_INVALID_BAKE_QTY`). On baking, `baked_qty` is set from the request, `remaining_qty` is initialised equal to `baked_qty`, and `sold_qty` is set to 0. The batch exposes several read-only counters as it lives: `sold_qty` (units of this product sold across paid retail orders on the day, full-price and marked-down alike), `markdown_sold_qty` (units sold at the markdown price after this batch was marked down), `remaining_qty` (`baked_qty` minus `sold_qty`, never falling below zero), and `wasted_qty` (the remaining quantity captured at sweep time, zero until then).

Late in the selling day, a `Cashier` may mark a batch down to clear stale stock, moving it `BAKED → MARKED_DOWN`. This requires the batch to be `BAKED` (else `ERR_BATCH_INVALID_STATE`), requires the parent day to be `SELLING` (else `ERR_DAY_INVALID_STATE`), and requires `remaining_qty` to be at least 1 — there must be something left to discount (else `ERR_NOTHING_TO_MARK_DOWN`). Once a batch is marked down, subsequent retail order lines for that product may opt into the markdown price (see §3.4).

At close, a `BakeManager` sweeps a batch — throwing away whatever is left — moving it to `SWEPT`. A sweep may originate from either `BAKED` or `MARKED_DOWN` status; in both cases the precondition is identical (the batch must be `BAKED` or `MARKED_DOWN`, else `ERR_BATCH_INVALID_STATE`) and the parent day must be `SELLING` or `CUTOFF` (else `ERR_DAY_INVALID_STATE`). Sweeping freezes `wasted_qty` to the batch's current `remaining_qty`, and that batch then contributes `wasted_qty` multiplied by the product's `unit_cost_cents` to the day's waste pool. Batches for a day can be listed (optionally filtered by `product_id`) and fetched individually.

### 3.4. Retail Selling: Carts, Tiered Pricing, and Payment

The retail counter runs through the `RetailOrder`. A `Cashier` opens a cart for a day, supplying `line_items` — an array of entries each naming a `product_id`, a `qty`, and a `marked_down` flag — plus an optional `loyalty_account_id` (null for an anonymous sale) and an optional `redeem_reward` flag that defaults to false. A new order enters status `CART`, and its `subtotal_cents` is computed from the line items at creation. Orders follow `CART → PAID`, and from `PAID` either onward to `REFUNDED` or aside to `VOIDED`; `VOIDED` and `REFUNDED` are both terminal.

**Per-line pricing** follows a strict tiered rule, evaluated per line in this pinned order. If the line is `marked_down`, it bypasses the dozen and bulk tiers entirely and is priced as the quantity multiplied by the product's markdown price (defined in §3.5). Otherwise, if the line quantity is at or above the product's `bulk_threshold` — the boundary is inclusive — the whole line is priced at the quantity multiplied by `bulk_unit_price_cents`, and the dozen tier does not apply at all. Otherwise the line is priced by splitting the quantity into whole dozens and a remainder: the number of complete dozens (the quantity divided by twelve, discarding any remainder) is multiplied by `dozen_price_cents`, and the leftover units (the quantity modulo twelve) are each priced at `unit_price_cents`; the line total is the sum of those two parts. A line's `subtotal_cents` contribution is exact integer cents with no rounding, since every factor is an integer.

The order's `subtotal_cents` is the sum of all line prices, with no loyalty discount applied. The `loyalty_discount_cents` is then determined: it is zero unless `redeem_reward` is set and the linked loyalty account's accrued reward value covers a full reward; when redemption applies, the discount is the smaller of the reward value (1200 cents) and the subtotal, so the discount never exceeds what is owed. The order `total_cents` is the subtotal minus the loyalty discount, floored at zero. This three-step order — subtotal first, then reward redemption, then total — is mandatory.

Paying a cart is performed by a `Cashier` and moves it `CART → PAID`. It requires the order to be in `CART` (else `ERR_ORDER_INVALID_STATE`) and the parent day to be `SELLING` (else `ERR_DAY_INVALID_STATE`). Two stock checks then apply per line: for every `marked_down` line, the product's batch on the day must be in `MARKED_DOWN` status and have `remaining_qty` at least as large as the line quantity (else `ERR_INSUFFICIENT_MARKDOWN_STOCK`); and for every line, the product's batch must have `remaining_qty` at least as large as the line quantity (else `ERR_INSUFFICIENT_STOCK`). On a successful payment, `total_cents` is finalised and the cascade described in §3.5 runs: batch stock decrements, loyalty accrues, and any reward is redeemed.

### 3.5. Markdown Pricing, Loyalty Accrual, and Sale Cascades

**The markdown price** of a product is its `unit_price_cents` reduced by forty percent, rounded half up to whole cents — equivalently, sixty percent of the unit price, rounded half up. For example, a unit price of 150 cents yields a markdown price of 90 cents, and 175 cents yields 105 cents. This single markdown price is what a marked-down batch sells at, and it is the per-unit figure used for marked-down retail lines.

When a retail order is paid, the **stock cascade** decrements each line product's batch `sold_qty` and `remaining_qty`; for marked-down lines it additionally increments that batch's `markdown_sold_qty`. These movements are exactly what `remaining_qty` and the sold counters report on the batch.

The **loyalty cascade** runs whenever the paid order carries a `loyalty_account_id`. A `LoyaltyAccount` is registered with a `phone` (unique across loyalty accounts) and a `name`, and tracks two read-only figures: `punch_count`, the punches accumulated toward the next reward, and `reward_balance_cents`, the accrued free-dozen reward value available to redeem. Both start at zero. On payment, the account earns one punch per full dozen across the order — that is, the total quantity summed across all line items divided by twelve, discarding the remainder — and `punch_count` increases by that earned amount. Whenever `punch_count` reaches the reward threshold of 10 punches, it auto-converts: 10 punches are removed from `punch_count` and 1200 cents are added to `reward_balance_cents`; this conversion repeats as long as `punch_count` remains at or above 10, so a single large order can mint more than one reward. If `redeem_reward` was set on the order and the account's reward balance covered the reward, the redeemed reward (1200 cents, or the subtotal if smaller) is debited from `reward_balance_cents` and recorded as the order's `loyalty_discount_cents`.

**Voiding and refunding** are compensations that must undo the sale exactly. A `Cashier` voids a paid order (`PAID → VOIDED`), which requires the order to be `PAID` (else `ERR_ORDER_INVALID_STATE`) and the parent day to be `SELLING` (else `ERR_DAY_INVALID_STATE`). A `ShopAdmin` refunds a paid order (`PAID → REFUNDED`), which requires only that the order be `PAID` (else `ERR_ORDER_INVALID_STATE`) — a refund carries no day-status precondition, so it remains available after cutoff. Both reversals restore each line product's batch `sold_qty` and `remaining_qty` (and restore `markdown_sold_qty` for marked-down lines), reverse the loyalty punches this order accrued, and undo any reward conversion this order caused (subtracting 1200 cents per conversion that this order triggered). If the order had redeemed a reward, that reward value is refunded back to `reward_balance_cents`. The intended invariant is that punches earned and then reversed leave the account's punch count plus banked reward value exactly where it stood before the sale. Retail orders for a day can be listed (optionally filtered by `status`) and fetched individually, and a loyalty member's own orders can be listed through the member.

### 3.6. Wholesale Accounts, Standing Orders, and the Ledger

A `WholesaleAccount` is created by a `ShopAdmin` with a business `name`, a `discount_pct` (a fractional discount at least 0 and strictly below 1, e.g. 0.15), and a `credit_limit_cents` — the maximum outstanding, invoiced-but-unpaid balance the account may carry, which is zero or more. The account tracks a read-only `outstanding_balance_cents` and a `status` that is `ACTIVE` on creation and may toggle between `ACTIVE` and `SUSPENDED`. A `ShopAdmin` suspends an active account (`ACTIVE → SUSPENDED`, requiring it be `ACTIVE`, else `ERR_ACCOUNT_INVALID_STATE`) and reactivates a suspended one (`SUSPENDED → ACTIVE`, requiring it be `SUSPENDED`, else `ERR_ACCOUNT_INVALID_STATE`).

The **outstanding balance** is, at any moment, the sum of all `amount_cents` across that account's invoiced wholesale deliveries minus the sum of all payments recorded against the account. Invoicing a delivery raises it; a recorded payment lowers it. A `ShopAdmin` records a payment by supplying an `amount_cents`, which decreases the outstanding balance accordingly. The intended ledger invariant is that invoicing a delivery and then paying its exact amount in full returns the outstanding balance to its pre-invoice value.

A `StandingOrder` captures a recurring route order for an account. A `ShopAdmin` or the owning `WholesaleClient` creates one naming the `wholesale_account_id`, a `delivery_dow` (the recurring day of week, an integer from 0 for Monday through 6 for Sunday), and `line_items` (an array of entries each naming a `product_id` and a `qty`). A standing order is `ACTIVE` on creation and may move `ACTIVE → PAUSED` (pause), `PAUSED → ACTIVE` (resume), or from either `ACTIVE` or `PAUSED` to the terminal `CANCELLED` (cancel). Standing orders can be listed (optionally filtered by `wholesale_account_id` and `status`) and fetched individually, and the deliveries realized from a given standing order can be listed through it. Each account can also list its own deliveries across all days.

### 3.7. Releasing, Running, and Invoicing Wholesale Deliveries

A `WholesaleDelivery` realizes a standing order onto a specific production day. A `ShopAdmin` or `RouteDriver` releases a delivery by supplying the `standing_order_id` and the route stop window — `route_window_start` and `route_window_end`, the latter strictly after the former. The delivery's `production_day_id` is the day it is released onto, its `wholesale_account_id` is copied from the standing order for ledger lookups, and its `amount_cents` is computed at release (see below). A released delivery enters status `SCHEDULED`.

Releasing a delivery is fenced by several preconditions, applied in this order. First, the day must not already be in `CUTOFF` or `RECONCILED`, and the logical clock must not be past the day's `delivery_cutoff_utc` (else `ERR_PAST_DELIVERY_CUTOFF`). Second, the named standing order must be `ACTIVE`, not `PAUSED` or `CANCELLED` (else `ERR_STANDING_ORDER_NOT_ACTIVE`). Third, the owning wholesale account must be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`). Fourth, the proposed route window must be buffer-separated from every other non-terminal delivery for the same account on this day: considering each existing delivery for that account on the day whose status is `SCHEDULED`, `PICKED`, or `DELIVERED`, the new stop collides if the proposed start is no later than the existing window's end plus a thirty-minute buffer **and** the existing window's start is no later than the proposed window's end plus that same buffer. Any single such collision rejects the release with `ERR_ROUTE_WINDOW_CONFLICT`. The buffer closes the gap, so two stops must be separated by strictly more than thirty minutes to coexist; back-to-back and near-adjacent stops both reject.

The **invoice amount** is computed once, at release, and frozen at invoice. Take the standing order's line items and price each line by the same tiered dozen-or-bulk rule used at the retail counter (no markdown ever applies to wholesale lines), then sum those raw line prices. Apply the account's discount to that single summed total — multiply the raw sum by one minus `discount_pct` — and round the result half up to whole cents. This **sum-then-round** order is mandatory and is not equivalent to rounding each discounted line and summing: for instance, two lines with raw prices 150 and 135 under a 0.15 discount yield round-half-up of 285 times 0.85, which is round-half-up of 242.25, namely 242 — whereas discounting and rounding line by line would give 128 plus 115, namely 243. The summed-then-rounded figure is the contract.

Once on the day, a `RouteDriver` runs the delivery: pick (`SCHEDULED → PICKED`, requiring `SCHEDULED`, else `ERR_DELIVERY_INVALID_STATE`), then deliver (`PICKED → DELIVERED`, requiring `PICKED`, else `ERR_DELIVERY_INVALID_STATE`). A delivery may also be cancelled to the terminal `CANCELLED` state from either `SCHEDULED` or `PICKED` (the precondition in both cases is that the delivery be `SCHEDULED` or `PICKED`, else `ERR_DELIVERY_INVALID_STATE`).

Invoicing is a `ShopAdmin` operation moving a delivery `DELIVERED → INVOICED`, and it is the ledger's money moment. It requires the delivery to be `DELIVERED` (else `ERR_DELIVERY_INVALID_STATE`); it requires the owning wholesale account to be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`); and it requires that the account's current `outstanding_balance_cents` plus this delivery's `amount_cents` not exceed the account's `credit_limit_cents` (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402). On a successful invoice, the account's `outstanding_balance_cents` rises by `amount_cents` as a cascade onto the account. Deliveries for a day can be listed (optionally filtered by `standing_order_id`, `wholesale_account_id`, and `status`) and fetched individually.

### 3.8. Catering and Holiday Pre-Orders

A `PreOrder` captures a catering, holiday, or event order placed ahead of time. A `ShopAdmin` or the owning `WholesaleClient` creates one naming the `wholesale_account_id`, the `pickup_production_day_id` (the day it will be fulfilled), a pickup window given by `pickup_window_start` and `pickup_window_end` (end strictly after start), and `line_items` (entries each naming a `product_id` and a `qty`). A new pre-order enters status `REQUESTED` with `deposit_paid_cents` at zero, and follows `REQUESTED → CONFIRMED → FULFILLED`, with a cancel path from either `REQUESTED` or `CONFIRMED` to the terminal `CANCELLED`.

At creation the pre-order's `subtotal_cents` is the sum of its line items priced by the standard tiered dozen-or-bulk rule, with no account discount applied. From that subtotal the required **deposit** is derived: if the subtotal is at or above the catering deposit threshold of 4050 cents — the boundary is inclusive — the `deposit_due_cents` is twenty-five percent of the subtotal, rounded half up; otherwise `deposit_due_cents` is zero. Thus a subtotal of exactly 4050 cents requires a deposit of 1013 cents (round-half-up of 4050 times 0.25), while a subtotal of 4035 cents — one reachable step below the threshold — requires no deposit at all.

Catering capacity is finite, so pre-order creation is also gated by a **slot-overlap** rule over the pickup day. Treating each pickup window as the half-open interval from its start (inclusive) to its end (exclusive), the candidate window overlaps an existing one when the candidate start is strictly before the existing end and the existing start is strictly before the candidate end — a window that ends exactly when another begins does not overlap. Count, over all non-`CANCELLED` pre-orders sharing the same `pickup_production_day_id`, how many overlap the candidate window. If that count is already at or above the slot capacity of 2, the creation is rejected with `ERR_CATERING_SLOT_FULL`, because admitting it would put three concurrent pickups at the point of densest overlap.

Deposits are recorded incrementally: a `ShopAdmin` or owning `WholesaleClient` records a deposit payment by supplying an `amount_cents`, which raises `deposit_paid_cents`. A `ShopAdmin` confirms a pre-order (`REQUESTED → CONFIRMED`), which requires the pre-order to be `REQUESTED` (else `ERR_PREORDER_INVALID_STATE`), requires `deposit_paid_cents` to have reached `deposit_due_cents` (else `ERR_DEPOSIT_NOT_MET`, HTTP 402), and requires the pickup production day not to be `RECONCILED` (else `ERR_DAY_INVALID_STATE`). A `ShopAdmin` later fulfils a confirmed pre-order (`CONFIRMED → FULFILLED`), which requires it to be `CONFIRMED` (else `ERR_PREORDER_INVALID_STATE`) and the pickup production day to be `SELLING` or `CUTOFF` (else `ERR_DAY_INVALID_STATE`). Cancelling requires the pre-order to be `REQUESTED` or `CONFIRMED` (else `ERR_PREORDER_INVALID_STATE`). Pre-orders can be listed (optionally filtered by `wholesale_account_id`, `pickup_production_day_id`, and `status`) and fetched individually.

### 3.9. Reconciliation: Closing the Day's Books

Reconciliation is the day's finale and the heart of the system's ledger work — a `BakeManager` operation that moves the day `CUTOFF → RECONCILED`. Before any figures are frozen, several gates apply. The day must be in `CUTOFF` (else `ERR_DAY_INVALID_STATE`). Every bake batch on the day must be `SWEPT` (else `ERR_BATCHES_NOT_SWEPT`). No wholesale delivery on the day may still be open — none in `SCHEDULED`, `PICKED`, or `DELIVERED`; all must be `INVOICED` or `CANCELLED` (else `ERR_DELIVERIES_OPEN`). And the request must carry `expected_production_day_version` matching the day's current `version`, the optimistic-concurrency guard described in §2.9 (else `ERR_STALE_VERSION`, HTTP 412).

Reconcile computes and freezes five figures, a deliberately **dual-variant** pairing of a forward-looking baseline against the realized actual. The **expected full value** (`expected_full_value_cents`) is the forward-looking baseline: summed over every bake batch on the day, each batch's `baked_qty` multiplied by its product's `unit_price_cents` — what the day would have grossed had every baked unit sold at full price. It ignores actual sales, markdowns, and waste entirely. The **gross sales** (`gross_sales_cents`) is the realized actual: the sum of `total_cents` over every paid retail order on the day, plus the sum of `amount_cents` over every invoiced wholesale delivery on the day. The **markdown loss** (`markdown_loss_cents`) is summed over every batch on the day: that batch's `markdown_sold_qty` multiplied by the difference between the product's `unit_price_cents` and its markdown price — the revenue given up by selling marked-down rather than full price. The **waste cost** (`waste_cost_cents`) is summed over every swept batch: its `wasted_qty` multiplied by the product's `unit_cost_cents` — the cost of goods thrown away.

Finally, the **reconciliation variance** (`reconciliation_variance_cents`) is the forward baseline minus the three realized components: `expected_full_value_cents` minus `gross_sales_cents` minus `markdown_loss_cents` minus `waste_cost_cents`. All five figures are frozen on the day at this moment (they read zero before reconcile), and the day's `version` increments by one as part of the transition.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201; all other successful operations, including every state transition and every read, return HTTP 200. A "newly created resource" means one of the system entities listed in §2.4 brought into existence by its create endpoint (`POST /products`, `POST /production-days`, `POST /production-days/{id}/bake-batches`, `POST /production-days/{id}/retail-orders`, `POST /loyalty-accounts`, `POST /wholesale-accounts`, `POST /standing-orders`, `POST /production-days/{id}/wholesale-deliveries`, and `POST /pre-orders`); these alone return 201. Recording a wholesale payment (`POST /wholesale-accounts/{id}/payments`) and recording a pre-order deposit (`POST /pre-orders/{preOrderId}/deposit`) do not create a new entity — each applies a ledger movement and returns 200 with the updated parent resource (the `WholesaleAccount` and the `PreOrder` respectively) in the data field. The clock-setting capability returns 200 with no data body. Request and response payloads are not described here; refer to the §3 narratives to reconstruct each operation's inputs, outputs, and side effects.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/products` | Create a product with retail/dozen/bulk pricing and allergen labels | ShopAdmin |
| GET | `/products` | List products | ShopAdmin, Cashier, BakeManager, RouteDriver, WholesaleClient |
| GET | `/products/{id}` | Get a product (includes allergen labels) | ShopAdmin, Cashier, BakeManager, RouteDriver, WholesaleClient |
| GET | `/products/{id}/bake-batches` | List bake batches for a product across days | ShopAdmin, BakeManager |
| POST | `/production-days` | Open a new production day with a delivery cutoff | ShopAdmin |
| GET | `/production-days` | List production days | ShopAdmin, Cashier, BakeManager, RouteDriver, WholesaleClient |
| GET | `/production-days/{id}` | Get a production day with reconciliation pools | ShopAdmin, Cashier, BakeManager, RouteDriver, WholesaleClient |
| POST | `/production-days/{id}/start-baking` | Move day OPEN to BAKING | BakeManager |
| POST | `/production-days/{id}/open-sales` | Move day BAKING to SELLING | BakeManager |
| POST | `/production-days/{id}/close-cutoff` | Move day SELLING to CUTOFF | ShopAdmin |
| POST | `/production-days/{id}/reconcile` | Move day CUTOFF to RECONCILED; freeze the day's pools (OCC-guarded) | BakeManager |
| POST | `/production-days/{id}/bake-batches` | Plan a par-bake batch for a product on this day | BakeManager |
| GET | `/production-days/{id}/bake-batches` | List batches for the day | ShopAdmin, Cashier, BakeManager |
| GET | `/production-days/{id}/bake-batches/{batchId}` | Get a batch | ShopAdmin, Cashier, BakeManager |
| POST | `/production-days/{id}/bake-batches/{batchId}/bake` | Mark a batch BAKED with actual quantity | BakeManager |
| POST | `/production-days/{id}/bake-batches/{batchId}/markdown` | Mark remaining stock down (BAKED to MARKED_DOWN) | Cashier |
| POST | `/production-days/{id}/bake-batches/{batchId}/sweep` | Throw away remaining stock (BAKED/MARKED_DOWN to SWEPT) | BakeManager |
| POST | `/production-days/{id}/retail-orders` | Open a retail POS cart for this day | Cashier |
| GET | `/production-days/{id}/retail-orders` | List retail orders for the day | ShopAdmin, Cashier |
| GET | `/production-days/{id}/retail-orders/{orderId}` | Get a retail order | ShopAdmin, Cashier |
| POST | `/production-days/{id}/retail-orders/{orderId}/pay` | Pay a cart (CART to PAID) | Cashier |
| POST | `/production-days/{id}/retail-orders/{orderId}/void` | Void a paid order (PAID to VOIDED) | Cashier |
| POST | `/production-days/{id}/retail-orders/{orderId}/refund` | Refund a paid order (PAID to REFUNDED) | ShopAdmin |
| POST | `/loyalty-accounts` | Register a loyalty member | Cashier, ShopAdmin |
| GET | `/loyalty-accounts/{id}` | Get a loyalty member | Cashier, ShopAdmin |
| GET | `/loyalty-accounts/{id}/retail-orders` | List retail orders linked to a loyalty member | Cashier, ShopAdmin |
| POST | `/wholesale-accounts` | Create a wholesale account with discount and credit limit | ShopAdmin |
| GET | `/wholesale-accounts/{id}` | Get a wholesale account with outstanding balance | ShopAdmin, RouteDriver, WholesaleClient |
| GET | `/wholesale-accounts/{id}/wholesale-deliveries` | List deliveries for an account across days | ShopAdmin, RouteDriver, WholesaleClient |
| POST | `/wholesale-accounts/{id}/suspend` | Suspend a wholesale account (ACTIVE to SUSPENDED) | ShopAdmin |
| POST | `/wholesale-accounts/{id}/reactivate` | Reactivate a wholesale account (SUSPENDED to ACTIVE) | ShopAdmin |
| POST | `/wholesale-accounts/{id}/payments` | Record a payment against the account | ShopAdmin |
| POST | `/standing-orders` | Create a recurring route standing order for an account | ShopAdmin, WholesaleClient |
| GET | `/standing-orders` | List standing orders | ShopAdmin, RouteDriver, WholesaleClient |
| GET | `/standing-orders/{id}` | Get a standing order | ShopAdmin, RouteDriver, WholesaleClient |
| GET | `/standing-orders/{id}/wholesale-deliveries` | List deliveries realized from a standing order | ShopAdmin, RouteDriver, WholesaleClient |
| POST | `/standing-orders/{id}/pause` | Pause a standing order (ACTIVE to PAUSED) | ShopAdmin, WholesaleClient |
| POST | `/standing-orders/{id}/resume` | Resume a standing order (PAUSED to ACTIVE) | ShopAdmin, WholesaleClient |
| POST | `/production-days/{id}/wholesale-deliveries` | Release/schedule a delivery for an active standing order onto this day | ShopAdmin, RouteDriver |
| GET | `/production-days/{id}/wholesale-deliveries` | List deliveries for the day | ShopAdmin, RouteDriver, WholesaleClient |
| GET | `/production-days/{id}/wholesale-deliveries/{deliveryId}` | Get a delivery | ShopAdmin, RouteDriver, WholesaleClient |
| POST | `/production-days/{id}/wholesale-deliveries/{deliveryId}/pick` | Driver picks up the delivery (SCHEDULED to PICKED) | RouteDriver |
| POST | `/production-days/{id}/wholesale-deliveries/{deliveryId}/deliver` | Driver completes the route stop (PICKED to DELIVERED) | RouteDriver |
| POST | `/production-days/{id}/wholesale-deliveries/{deliveryId}/invoice` | Invoice a delivered order (DELIVERED to INVOICED); credit-checked | ShopAdmin |
| POST | `/production-days/{id}/wholesale-deliveries/{deliveryId}/cancel` | Cancel a delivery (SCHEDULED/PICKED to CANCELLED) | RouteDriver |
| POST | `/pre-orders` | Create a holiday/event/catering pre-order | ShopAdmin, WholesaleClient |
| GET | `/pre-orders` | List pre-orders | ShopAdmin, WholesaleClient |
| GET | `/pre-orders/{preOrderId}` | Get a pre-order | ShopAdmin, WholesaleClient |
| POST | `/pre-orders/{preOrderId}/deposit` | Record a deposit payment toward a pre-order | ShopAdmin, WholesaleClient |
| POST | `/pre-orders/{preOrderId}/confirm` | Confirm a pre-order (REQUESTED to CONFIRMED) | ShopAdmin |
| POST | `/pre-orders/{preOrderId}/fulfill` | Fulfill a confirmed pre-order (CONFIRMED to FULFILLED) | ShopAdmin |
| POST | `/pre-orders/{preOrderId}/cancel` | Cancel a pre-order (REQUESTED/CONFIRMED to CANCELLED) | ShopAdmin, WholesaleClient |
| POST | `/_clock/set_current_utc` | Set the server logical clock (for delivery-cutoff tests) | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_DAY_INVALID_STATE | 409 |
| ERR_NO_BATCHES | 409 |
| ERR_UNBAKED_BATCHES | 409 |
| ERR_BATCH_INVALID_STATE | 409 |
| ERR_INVALID_BAKE_QTY | 422 |
| ERR_NOTHING_TO_MARK_DOWN | 409 |
| ERR_ORDER_INVALID_STATE | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_MARKDOWN_STOCK | 409 |
| ERR_DELIVERY_INVALID_STATE | 409 |
| ERR_PAST_DELIVERY_CUTOFF | 409 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_ACCOUNT_INVALID_STATE | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_PREORDER_INVALID_STATE | 409 |
| ERR_DEPOSIT_NOT_MET | 402 |
| ERR_BATCHES_NOT_SWEPT | 409 |
| ERR_DELIVERIES_OPEN | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_STANDING_ORDER_NOT_ACTIVE | 409 |
| ERR_ROUTE_WINDOW_CONFLICT | 409 |
| ERR_CATERING_SLOT_FULL | 409 |
| ERR_INVALID_WINDOW | 422 |
</content>
</invoke>
