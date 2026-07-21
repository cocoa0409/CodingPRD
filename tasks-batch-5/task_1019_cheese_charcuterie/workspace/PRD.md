# Cheese & Charcuterie Shop API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a specialty cheese and charcuterie shop that runs its counter, its aging caves, and its wholesale program off a single system of record. The business is unusual in that most of what it sells is priced by weight and loses weight while it waits to be sold: a wheel received into a humidity-controlled cave sheds moisture every day it ages, so the price quoted when a customer places an order and the price charged when the cheese is finally cut can legitimately differ. The platform must therefore keep two views of nearly everything monetary and physical — a provisional view derived from nominal, requested figures and a final view derived from the actual cut recorded at the counter — and it must keep them reconcilable.

Four operator concerns drive the design. First, **pricing** must be exact to the cent across by-weight and by-unit products, curated boards, wholesale volume discounts, and store-credit settlement. Second, **inventory and aging** must be physically honest: a lot's remaining weight is its received weight minus what has been cut from it and minus the moisture it has lost to shrink, and the caves that hold those lots must never be counted as holding more than their capacity. Third, **allocation** must be safe under repeated writes — two counter staff drawing from the same lot must not both believe they hold the last kilogram. Fourth, the shop's **service surfaces** — catering prep stations, subscription cheese clubs and gifts, and the tasting room — each carry their own scheduling and eligibility rules that must be enforced at booking time.

The sections that follow define the global contract (authentication, envelopes, pagination, versioning, precision, concurrency, and inventory accounting), then the domain workflows in detail, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. A request missing either header, or presenting an `X-User-Role` that is not one of the three known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation — or a wholesale principal reaching for a resource it does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles are `ShopManager`, `CounterStaff`, and `WholesaleCustomer`, spelled exactly so.

- A `ShopManager` is a back-of-house operator responsible for catalog and inventory: products, caves, lots, rotation runs, boards, prep stations, tasting rooms, and customer accounts. When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`.
- A `CounterStaff` is a front-of-house operator who builds and fulfills orders, allocates lots, and books tasting events. When `X-User-Role` is `CounterStaff`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any resource's `id`.
- A `WholesaleCustomer` is a self-service wholesale/restaurant account acting on its own behalf. When `X-User-Role` is `WholesaleCustomer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`. A `WholesaleCustomer` may create and manage only orders and subscriptions whose `customer_id` equals its own `X-User-ID`, and may read only its own orders, order lines, and subscriptions (plus the shared read-only catalog of products, lots, and boards). Any attempt to act on another account's resource is an ownership failure and yields `ERR_UNAUTHORIZED`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a supplied `limit` outside that range is clamped to the nearest bound. The `offset` defaults to 0 and its minimum is 0. Results are always ordered by `created_at` ascending — oldest first — so that pagination is stable across pages. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every persisted resource carries a server-minted `id` — an opaque UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set once at creation. All entities in this system additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by one on each mutation of that resource. Timestamps that record domain time — a lot's `aging_start_date`, an order's catering `prep_window_start`, `prep_window_end`, and `event_date`, a subscription's `next_ship_date`, a tasting event's `start_at` and `end_at` — are all ISO 8601 UTC values and are distinct from the bookkeeping `created_at`/`updated_at` fields.

The `version` field is the anchor of the concurrency mechanism described in §2.7 and is the value clients echo back when they must prove they are acting on a current view of a resource.

### 2.5. The Logical Clock and Aging Time

All time-dependent behavior in this system is measured against a **logical clock**, never the wall clock. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly set it stays at that value and never falls back to real time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant; advancing it changes how lots age and how booking windows compare.

A lot's age in whole days, `aging_days`, is the number of complete days between its `aging_start_date` and the current clock instant — that is, the elapsed time floored to whole days. This value governs both when a lot becomes sellable and how much moisture it has lost, and it is recomputed against the clock on every read.

### 2.6. Monetary Precision and Rounding Discipline

All money is stored and computed in integer **cents**; all weights in integer **grams**. Wherever a computation produces a fractional cent or a fractional gram, the result is rounded **half up** to the nearest whole cent or whole gram (a value ending in exactly one-half rounds away from zero). The order in which rounding is applied is contractual and is specified with each calculation in §3 — most importantly, per-component board pricing rounds each component to whole cents *before* summing, and the wholesale volume discount is computed against the already-whole-cent subtotal. Implementers must not defer rounding to a single final step where the specification calls for intermediate rounding, nor round early where the specification calls for a running exact sum.

### 2.7. Optimistic Concurrency on Lot Allocation

Allocating an order line to a lot is the one write in this system guarded by optimistic concurrency, because two lines drawing from the same lot must not both reserve against the same remaining weight. When a line is allocated to a lot, that allocation reserves weight and advances the lot's `version` by one. A subsequent allocation request must therefore carry `expected_lot_version` equal to the target lot's **current** `version`. If another allocation has advanced the lot's `version` since the client last read it, the request is operating on a stale view of remaining availability and is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Two strictly sequential allocation calls that reuse the same `expected_lot_version` reproduce this rejection deterministically: the first succeeds and bumps the version, the second fails the version check. No other endpoint takes a version field; allocation is the only OCC-guarded write.

### 2.8. Cave Weight Accounting and Inventory Consistency

A cave is a fixed-capacity aging space, and the system keeps its occupancy exact at all times. A cave's `used_g` is the sum of `current_weight_g` across the lots it holds whose `status` is either `AGING` or `READY`; lots that are `DEPLETED` or `DISCARDED` are excluded from that sum. A cave's `available_g` is its `capacity_g` minus `used_g`, never allowed to fall below zero. These two computed figures are recomputed on every event that can change them: receiving a lot, a rotation run, a manual discard, and order fulfillment or return.

Because a cave's occupancy is derived from the physical weight of its lots, the physical-weight bookkeeping on each lot must itself stay honest. For any lot, its received weight always equals the sum of its current remaining weight, the weight already consumed by fulfilled cuts, and the moisture it has cumulatively lost to shrink. Fulfillment and return form a compensating pair: fulfilling moves reserved weight into consumed weight (current weight drops), and returning moves it back (current weight rises, consumed weight falls). With no rotation run occurring between a fulfill and its matching return, the sum of a lot's current weight and its consumed weight is left unchanged by the pair.

### 2.9. Validation Ordering and Referential Integrity

Requests are validated in a fixed precedence so that the same request always fails for the same, most-fundamental reason. Authentication (§2.1) is checked first (`ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_UNAUTHORIZED`). Next, every identifier — path ids and body foreign keys alike — is resolved left to right, and the first that does not resolve to an existing resource yields `ERR_NOT_FOUND`. Only then is the request body checked for well-formedness — required fields present, enum values legal, types correct — with a malformed body rejected as `ERR_VALIDATION` (HTTP 400). Domain-specific checks (state, pricing coherence, capacity, safety, temporal, and fiscal rules) run after these gates, in the per-operation order given in §3.

Nested reads follow the same left-to-right resolution: any path that names more than one identifier resolves each segment in order and returns `ERR_NOT_FOUND` at the first unknown id.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Catalog: Customers, Products, Caves, and Stations

A `ShopManager` seeds the shop's reference data. Creating a **customer** records an `account_type` of either `RETAIL` or `WHOLESALE_RESTAURANT`, a display `name`, and a two-letter `region_code` that is recorded on labels but has no structural effect. Wholesale accounts also carry a `wholesale_tier` — one of `NONE`, `BRONZE`, `SILVER`, or `GOLD`, defaulting to `NONE` — and an informational `credit_limit_cents` that defaults to 0. A customer may hold a prepaid `store_credit_cents` balance, set at creation, defaulting to 0 and never negative; this balance is the funding source for store-credit payments and is credited back on refunds. Every customer begins life with a `status` of `ACTIVE`. A `ShopManager` may later move a customer's `status` to `DELINQUENT`, back to `ACTIVE`, or to the terminal `CLOSED` by supplying the target `status` on the set-status operation. A `DELINQUENT` customer can no longer host tasting events (see §3.9); the status transitions themselves carry no further preconditions.

Creating a **product** (a SKU) records its `name`, a `category` of `CHEESE` or `CHARCUTERIE`, a `milk_type` of `COW`, `GOAT`, `SHEEP`, `BUFFALO`, or `NONE` (charcuterie uses `NONE`), a `pasteurized` boolean (false marks a raw-milk product subject to legal minimum aging), and a `form` of `WHEEL`, `WEDGE`, `BLOCK`, `WHOLE_MUSCLE`, or `SLICED`. Each product declares a `pricing_mode` of `BY_WEIGHT` or `BY_UNIT`. Pricing configuration must be internally coherent: a `BY_WEIGHT` product requires `price_per_kg_cents` greater than zero and `unit_price_cents` exactly zero, while a `BY_UNIT` product requires `unit_price_cents` greater than zero and `price_per_kg_cents` exactly zero. A product violating either rule is rejected at creation with `ERR_INVALID_PRICING_CONFIG` (HTTP 422). A product also carries an `allergens` array of tokens such as `[MILK]`, `[MILK,NUTS]`, or `[PORK]` (defaulting to empty), a `min_aging_days` before a lot of it can become sellable (default 0), a `target_aging_days` horizon used for projected shrink (default 0), and a `shrink_pct_per_day` fractional daily moisture-loss rate (for example `0.001` means one-tenth of one percent per day, default 0).

Creating a **cave** records its `name`, a set-point `temp_c` and `humidity_pct`, and a total `capacity_g` in grams that must be greater than zero; its `used_g` starts at 0 and its `available_g` starts equal to `capacity_g`. A `ShopManager` also creates **prep stations** (each with only a `name`) used for catering, and **tasting rooms** (§3.9).

### 3.2. Receiving Lots and the Aging-Cave Lifecycle

Inventory enters as a **lot**: a `ShopManager` receives a quantity of one product into one cave, supplying `product_id`, `cave_id`, and a `received_weight_g` in grams that must be greater than zero. At receipt the lot is stamped `AGING`, its `aging_start_date` is set to the current clock instant, its `current_weight_g` is set to the received weight, its `cumulative_shrink_g` is 0, and its `last_aged_days` is 0. A lot's `current_weight_g` is always its received weight minus its cumulative shrink and minus the weight consumed by fulfilled cuts; its `reserved_weight_g` is the sum of requested weights over order lines that reference it on live (non-terminal, non-fulfilled) orders; its `available_weight_g` is current weight minus reserved weight, never below zero; and its `consumed_weight_g` is the sum of actual cut weights over fulfilled lines drawn from it. Receiving is refused if it would push the cave over capacity — that is, the received weight must not exceed the cave's `available_g` — otherwise the receipt is rejected with `ERR_CAVE_CAPACITY_EXCEEDED`.

At the moment of receipt the system also computes a one-shot **projected ready weight**, `projected_ready_weight_g`: the received weight multiplied by one minus the product's daily shrink rate times the product's target aging days, rounded half up to whole grams. This projection is linear on the original received weight across the whole target horizon and is deliberately distinct from the weight the lot will actually have after aging, because actual shrink compounds on a diminishing weight (below).

A **rotation run** is the ops checkpoint that advances aging for an entire cave. When a `ShopManager` runs a rotation, the system walks every `AGING` or `READY` lot in the cave and, for each, applies the day's realized moisture loss, then re-evaluates the lot's state. The realized per-run shrink for a lot is its **current** weight multiplied by the product's daily shrink rate multiplied by the number of days aged since the last run — that is, the difference between the lot's present `aging_days` and its stored `last_aged_days` — rounded half up to whole grams. That shrink is subtracted from `current_weight_g`, added to `cumulative_shrink_g`, and the lot's `last_aged_days` is then set to its present `aging_days`. Because each run shrinks the already-reduced current weight, the realized weight drifts below the receipt-time projection over successive runs.

After applying a run's shrink, the lot's state is resolved in this order. If the lot's cumulative shrink has reached or exceeded 35 percent of its received weight (`LOT_MAX_SHRINK_PCT` = 0.35), the lot is over-shrunk and transitions to `DISCARDED`, leaving inventory. Otherwise, an `AGING` lot whose `aging_days` has reached its product's `min_aging_days` — the boundary is inclusive, so a lot exactly at the minimum flips — and whose cumulative shrink is still strictly below the 35-percent ceiling transitions `AGING → READY` and becomes sellable. A lot that is neither over-shrunk nor yet old enough stays `AGING`. After the walk, the cave's `used_g` and `available_g` are recomputed.

A lot may also be **discarded manually** by a `ShopManager` for spoilage, with an optional `reason`; this moves the lot to `DISCARDED`. A manual discard of a `READY` lot is refused unless its `reserved_weight_g` is zero — a lot with live reservations cannot be discarded out from under an order. A discarded lot leaves inventory and the cave usage is recomputed. `DEPLETED` and `DISCARDED` are terminal lot states.

### 3.3. Curated Boards and Platters

A **board** is a pre-composed platter that a `ShopManager` defines once and that orders can then reference. A board has a `name`, an optional free-text `pairing_notes` beverage/accompaniment suggestion, and a `components` list of objects, each naming a `product_id` and a `portion_g` weight for that product. Every component's product must be a `BY_WEIGHT` product. The board's `base_price_cents` is computed by pricing each component independently — the component's `portion_g` divided by 1000 to convert grams to kilograms, multiplied by that product's `price_per_kg_cents`, and rounded half up to whole cents — then summing those rounded component prices, and finally adding a fixed assembly fee. The board records that assembly fee in `assembly_fee_cents`, which is always the fixed `BOARD_ASSEMBLY_FEE_CENTS` of 1500 cents (fifteen dollars). Rounding is per component first, then the integer sum, then the fee — never sum-then-round.

### 3.4. Building an Order: Lines, Allocation, and Provisional Pricing

An **order** is opened by a `CounterStaff` (for `RETAIL`, `BOARD`, or `CATERING`) or by a `WholesaleCustomer` (for `WHOLESALE`, only under its own `customer_id`). Creation records the `order_type` — one of `RETAIL`, `BOARD`, `CATERING`, or `WHOLESALE` — and the `customer_id`. A new order begins with `fulfillment_status` `DRAFT`, `payment_status` `UNPAID`, `payment_method` `NONE`, and every money field at zero. Catering orders additionally supply a `prep_station_id`, a `prep_window_start` (inclusive) and `prep_window_end` (exclusive), and an informational `event_date`; these are null for non-catering orders. A catering order's prep window is checked for conflicts immediately at creation (see §3.5's temporal rule).

Lines are added to a `DRAFT` order; adding a line to an order that is not `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT`. A line has a `line_type` of `PRODUCT` or `BOARD`. A `PRODUCT` line names a `product_id` and, depending on the product's pricing mode, a `requested_weight_g` (for a by-weight product) or a `requested_qty` (for a by-unit product); a `BOARD` line names a `board_id` instead. Each line records the `order_id` it belongs to (taken from context, not the caller). On add, the system computes the line's **provisional price** and writes it to `provisional_price_cents`, with `final_price_cents` mirroring it until fulfillment. For a by-weight product line the provisional price is the requested weight divided by 1000 (grams to kilograms) times the product's `price_per_kg_cents`, rounded half up to whole cents. For a by-unit product line it is the requested quantity times the product's `unit_price_cents`. For a board line it is the referenced board's `base_price_cents`. Adding a line recomputes the order's running subtotal and total.

A by-weight product line must be tied to physical inventory before the order can be submitted. A `CounterStaff` **allocates** such a line to a specific `READY` lot, supplying the target `lot_id` and the `expected_lot_version` described in §2.7. Allocation requires the owning order to still be `DRAFT` (else `ERR_ORDER_NOT_DRAFT`), the target lot to be in `READY` status (else `ERR_LOT_NOT_READY`), and the lot's `available_weight_g` to be at least the line's `requested_weight_g` (else `ERR_INSUFFICIENT_LOT_WEIGHT`). On success the line's `lot_id` is set, the line's `reserved_weight_g` becomes its requested weight, the lot's `reserved_weight_g` and `available_weight_g` are recomputed, and the lot's `version` increments by one. A stale `expected_lot_version` is rejected with `ERR_STALE_LOT_VERSION` before any reservation is made. An order line may be read individually or listed and filtered by its `order_id`, `product_id`, `lot_id`, or `board_id`.

### 3.5. Submitting, Paying, and Fulfilling

**Submitting** a `DRAFT` order (by `CounterStaff`, or by a `WholesaleCustomer` for its own order) runs a battery of checks in a fixed priority order and, on success, moves the order `DRAFT → SUBMITTED` and recomputes its totals. The checks, in order: first, the order must have at least one line — an empty order is rejected with `ERR_EMPTY_ORDER`. Next, every by-weight product line must be allocated to a lot (a line still lacking a `lot_id` is not in a submittable state and is rejected with `ERR_INVALID_STATE`). Then the raw-milk safety check runs: no allocated lot of an unpasteurized product may have `aging_days` below the legal minimum of 60 days (`RAW_MILK_MIN_LEGAL_AGING_DAYS`); a violation is rejected with `ERR_RAW_MILK_AGING`. Then, for a catering order, the prep-window temporal check runs (below), rejecting a conflict with `ERR_PREP_STATION_CONFLICT`. Finally, for a wholesale order, the fiscal floor is enforced: the order's `subtotal_cents` must be at least the wholesale minimum of 10000 cents (one hundred dollars); a shortfall is rejected with `ERR_WHOLESALE_MIN_ORDER`.

The **temporal rule** for catering: a catering order's half-open prep window `[prep_window_start, prep_window_end)` must not overlap the prep window of any other live catering order — one whose `fulfillment_status` is `DRAFT`, `SUBMITTED`, or `FULFILLED` — on the same prep station. A prep station admits a single occupant at a time; two windows that merely touch at an endpoint (one window's end equal to the other's start) do not overlap and are permitted. This rule is enforced both when a catering order is created and again at submit.

Order **totals** are recomputed at submit and again at fulfillment, following a fixed evaluation order. First, `billable_weight_g` is the sum of requested weights over the order's by-weight product lines (and, once fulfilled, the sum of their actual cut weights). Second, `subtotal_cents` is the sum of every line's price — provisional prices before fulfillment, final prices at and after fulfillment. Third, a wholesale volume-discount percentage is chosen from the billable weight, and only for `WHOLESALE` orders (it is zero for every other order type): a billable weight below 5000 grams (5 kilograms) earns no discount; from 5000 grams up to but not including 20000 grams (20 kilograms) earns 8 percent; 20000 grams or more earns 15 percent. Fourth, `discount_cents` is that percentage applied to the whole-cent subtotal, rounded half up, then capped at the maximum wholesale discount of 50000 cents (five hundred dollars) — whichever is smaller. Fifth, `delivery_fee_cents` is the fixed catering delivery fee of 2500 cents (twenty-five dollars) when the order type is `CATERING`, and zero otherwise. Sixth, `total_cents` is the subtotal minus the discount plus the delivery fee.

**Payment** moves the order `UNPAID → PAID` and is independent of fulfillment. Paying requires the order to be `SUBMITTED` (else `ERR_INVALID_STATE`) and still `UNPAID` (a second payment is rejected with `ERR_ALREADY_PAID`). The payer supplies a `payment_method` of `STORE_CREDIT` or `EXTERNAL`, which is recorded on the order. A store-credit payment requires the customer's `store_credit_cents` to be at least the order's `total_cents`; otherwise it is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 402). On a successful store-credit payment, the customer's `store_credit_cents` is reduced by the order total and the order's `store_credit_applied_cents` records exactly that amount debited. External payments touch no store-credit balance.

**Fulfillment** moves the order `SUBMITTED → FULFILLED` and requires the order to be `SUBMITTED` (else `ERR_INVALID_STATE`) and `PAID` (else `ERR_ORDER_NOT_PAID`). The fulfill request carries `line_actuals`, a list that records the `actual_cut_weight_g` cut for each by-weight product line; every such line must have its actual weight supplied. The raw-milk legality check is re-run at fulfillment and again rejects with `ERR_RAW_MILK_AGING` if any allocated unpasteurized lot is younger than 60 days. For each product line the system recomputes `final_price_cents` from the actual cut weight (by-weight lines reprice on the real cut; the final price may differ from the provisional), adds that actual weight to the lot's `consumed_weight_g`, subtracts it from the lot's `current_weight_g`, and releases the line's reservation. As a cascade, any lot whose `available_weight_g` reaches zero after this consumption transitions `READY → DEPLETED`, and the affected cave's `used_g` and `available_g` are recomputed. The order's `subtotal_cents` and `total_cents` are then recomputed from the final line prices.

### 3.6. Cancellations, Returns, and the Compensating Ledgers

**Cancelling** an order (permitted from `DRAFT` or `SUBMITTED`, carrying no further precondition) moves it to the terminal `CANCELLED` state. Cancellation releases every line's reservation, so each affected lot's `reserved_weight_g` and `available_weight_g` are recomputed and the held weight is restored to availability. If the order had already been paid, the cancellation also refunds it: the `payment_status` moves `PAID → REFUNDED`, and for a store-credit order the customer's `store_credit_cents` is increased by the order's `store_credit_applied_cents`, returning exactly what was debited.

**Returning** an order applies only to a `FULFILLED` order (a return attempted on any other fulfillment state is rejected with `ERR_ORDER_NOT_FULFILLED`) that is also `PAID`, and moves it `FULFILLED → RETURNED`. A return reverses the physical consumption of every product line: each line's actual cut weight is subtracted from its lot's `consumed_weight_g` and added back to the lot's `current_weight_g`, returning the stock. A lot that had been driven to `DEPLETED` reverts to `READY` once it regains available weight. The return also refunds the payment (`PAID → REFUNDED`), crediting a store-credit customer's `store_credit_cents` back by `store_credit_applied_cents`, and the affected cave's `used_g` is recomputed.

Both compensating flows preserve the system's two conservation invariants. The **weight ledger** holds that a lot's received weight always equals its current weight plus its consumed weight plus its cumulative shrink; a fulfill followed by its matching return, with no rotation run between them, leaves the sum of current and consumed weight exactly as it was before the fulfill. The **store-credit ledger** holds that paying by store credit reduces the balance by the order total and the matching refund restores it by the amount applied, so a store-credit payment followed by its compensating refund — whether via cancellation or return — leaves the customer's `store_credit_cents` at its pre-payment value.

### 3.7. Allergen Labeling

Any order exposes a computed **label** read used for allergen disclosure at the counter. The label reports the order's `order_id`, a de-duplicated, sorted `allergens` list, a `contains_raw_milk` boolean, and a `line_count`. The allergen list is the sorted union of the allergen tokens of every product on the order — the product on each product line, and every component product of each board line — with duplicates collapsed and the output deterministically sorted. The `contains_raw_milk` flag is true when any product involved in the order, whether a line's product or a board component's product, has `pasteurized` equal to false. This read performs no state change.

### 3.8. Subscriptions, Cheese Clubs, and Gifts

A **subscription** is a recurring board shipment created by a `CounterStaff` or by a `WholesaleCustomer` (for its own account). It names the billing `customer_id`, the `board_id` shipped each cycle, and a `tier` of `CLASSIC` or `PREMIUM`. It carries a `cadence_days` gap between shipments (defaulting to 30, and required to be greater than zero) and a `monthly_price_cents` charge per cycle (required to be greater than zero). A subscription may be a gift: when `is_gift` is true a `gift_recipient_email` names the recipient, and `is_gift` defaults to false. A new subscription starts `ACTIVE`, and its `next_ship_date` is set to the current clock instant plus its cadence in days.

A subscription's lifecycle is cyclic. The owner may **pause** an `ACTIVE` subscription, moving it `ACTIVE → PAUSED`; pausing carries no side effect on the ship date. The owner may **resume** a `PAUSED` subscription, moving it `PAUSED → ACTIVE` and advancing `next_ship_date` by another `cadence_days`. Pause and resume may alternate any number of times. The owner may **cancel** from either `ACTIVE` or `PAUSED`, moving the subscription to the terminal `CANCELLED` state. Any of these three actions attempted from an incompatible state is rejected with `ERR_SUBSCRIPTION_INVALID_STATE`.

### 3.9. Tasting Events and Room Scheduling

The shop hosts sampling and pairing sessions in **tasting rooms**. A room has a `name`, a `seat_capacity` greater than zero, and a `buffer_minutes` clean-down gap (defaulting to 30, and at least zero) required between two non-overlapping sessions in that same room. A `CounterStaff` **books** a **tasting event** by naming the `tasting_room_id`, the hosting `customer_id`, an inclusive `start_at`, an exclusive `end_at`, a positive number of `seats`, and an optional `pairing_product_ids` list of the products featured. A booked event starts `SCHEDULED`.

Three booking constraints apply, each independently rejecting the request. First, the hosting customer must be `ACTIVE`; a `DELINQUENT` or `CLOSED` host cannot book, and the attempt is rejected with `ERR_CUSTOMER_NOT_ACTIVE`. Second, the room's buffer must be respected: for any other `SCHEDULED` event in the same room whose time interval does **not** overlap this one, the gap between the two must be at least `buffer_minutes`; a nearer non-overlapping neighbor is rejected with `ERR_TASTING_ROOM_CONFLICT`. Third, aggregate seating must fit: across the set of `SCHEDULED` events in the same room whose `[start_at, end_at)` intervals overlap this one, the sum of their `seats` plus this event's `seats` must not exceed the room's `seat_capacity`; an overflow is rejected with `ERR_TASTING_SEATS_EXCEEDED`. A `CounterStaff` may **cancel** a `SCHEDULED` event, moving it `SCHEDULED → CANCELLED`, which frees the event's seats and buffer so they no longer constrain later bookings; cancelling anything not `SCHEDULED` is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

All endpoints share the envelope and pagination contract of §2. Resource-creating endpoints return HTTP 201 with the created resource; state transitions and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. Error responses carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/_clock/set_current_utc` | Set the server logical clock (test-driving) | ShopManager |
| POST | `/api/customers` | Create a customer / wholesale account | ShopManager |
| GET | `/api/customers/{customer_id}` | Get a customer | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/customers/{customer_id}/set-status` | Set customer status (ACTIVE/DELINQUENT/CLOSED) | ShopManager |
| POST | `/api/products` | Create a product SKU | ShopManager |
| GET | `/api/products/{product_id}` | Get a product | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/caves` | Create an aging cave | ShopManager |
| GET | `/api/caves/{cave_id}` | Get a cave with computed usage | ShopManager, CounterStaff |
| POST | `/api/caves/{cave_id}/rotate` | Run a rotation: age, shrink, promote, discard, recompute usage | ShopManager |
| POST | `/api/lots` | Receive a lot into a cave (status AGING) | ShopManager |
| GET | `/api/lots/{lot_id}` | Get a lot with computed weights and aging_days | ShopManager, CounterStaff, WholesaleCustomer |
| GET | `/api/lots` | List lots (filter by product, cave, or status) | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/lots/{lot_id}/discard` | Manually discard a lot | ShopManager |
| POST | `/api/orders` | Create an order (DRAFT/UNPAID) | CounterStaff, WholesaleCustomer |
| GET | `/api/orders/{order_id}` | Get an order with computed totals | ShopManager, CounterStaff, WholesaleCustomer |
| GET | `/api/orders` | List orders (filter by customer, prep station, type, status) | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/orders/{order_id}/lines` | Add a line to a DRAFT order | CounterStaff, WholesaleCustomer |
| POST | `/api/order-lines/{line_id}/allocate` | Allocate a product line to a READY lot (OCC) | CounterStaff |
| GET | `/api/order-lines/{line_id}` | Get an order line | ShopManager, CounterStaff, WholesaleCustomer |
| GET | `/api/order-lines` | List order lines (filter by order, product, lot, board) | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/orders/{order_id}/submit` | Submit a DRAFT order | CounterStaff, WholesaleCustomer |
| POST | `/api/orders/{order_id}/pay` | Pay a SUBMITTED+UNPAID order | CounterStaff, WholesaleCustomer |
| POST | `/api/orders/{order_id}/fulfill` | Fulfill a SUBMITTED+PAID order (record actual cuts) | CounterStaff |
| POST | `/api/orders/{order_id}/cancel` | Cancel a DRAFT or SUBMITTED order | CounterStaff, WholesaleCustomer |
| POST | `/api/orders/{order_id}/return` | Return a FULFILLED order | CounterStaff |
| GET | `/api/orders/{order_id}/label` | Computed allergen/label read for the order | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/boards` | Create a curated board | ShopManager |
| GET | `/api/boards/{board_id}` | Get a board with computed base_price | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/subscriptions` | Create a subscription (cheese club / gift) | CounterStaff, WholesaleCustomer |
| GET | `/api/subscriptions/{subscription_id}` | Get a subscription | ShopManager, CounterStaff, WholesaleCustomer |
| GET | `/api/subscriptions` | List subscriptions (filter by customer, board, status) | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/subscriptions/{subscription_id}/pause` | Pause an ACTIVE subscription | CounterStaff, WholesaleCustomer |
| POST | `/api/subscriptions/{subscription_id}/resume` | Resume a PAUSED subscription | CounterStaff, WholesaleCustomer |
| POST | `/api/subscriptions/{subscription_id}/cancel` | Cancel a subscription | CounterStaff, WholesaleCustomer |
| POST | `/api/prep-stations` | Create a catering prep station | ShopManager |
| GET | `/api/prep-stations/{prep_station_id}` | Get a prep station | ShopManager, CounterStaff |
| POST | `/api/tasting-rooms` | Create a tasting room | ShopManager |
| GET | `/api/tasting-rooms/{tasting_room_id}` | Get a tasting room | ShopManager, CounterStaff |
| POST | `/api/tasting-events` | Book a tasting/sampling event | CounterStaff |
| GET | `/api/tasting-events/{event_id}` | Get a tasting event | ShopManager, CounterStaff, WholesaleCustomer |
| GET | `/api/tasting-events` | List tasting events (filter by room or customer) | ShopManager, CounterStaff, WholesaleCustomer |
| POST | `/api/tasting-events/{event_id}/cancel` | Cancel a scheduled tasting event | CounterStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_PRICING_CONFIG | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_NOT_DRAFT | 409 |
| ERR_ALREADY_PAID | 409 |
| ERR_ORDER_NOT_PAID | 409 |
| ERR_ORDER_NOT_FULFILLED | 409 |
| ERR_SUBSCRIPTION_INVALID_STATE | 409 |
| ERR_LOT_NOT_READY | 409 |
| ERR_STALE_LOT_VERSION | 412 |
| ERR_INSUFFICIENT_LOT_WEIGHT | 409 |
| ERR_CAVE_CAPACITY_EXCEEDED | 409 |
| ERR_RAW_MILK_AGING | 422 |
| ERR_EMPTY_ORDER | 422 |
| ERR_WHOLESALE_MIN_ORDER | 422 |
| ERR_INSUFFICIENT_STORE_CREDIT | 402 |
| ERR_PREP_STATION_CONFLICT | 409 |
| ERR_TASTING_ROOM_CONFLICT | 409 |
| ERR_TASTING_SEATS_EXCEEDED | 409 |
| ERR_CUSTOMER_NOT_ACTIVE | 409 |
