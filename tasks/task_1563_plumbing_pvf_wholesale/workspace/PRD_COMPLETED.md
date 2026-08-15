# Plumbing PVF Wholesale API — Product Requirements Document

## 1. Introduction

A plumbing and PVF (pipe, valve, and fitting) wholesale distributor lives or dies on three promises made simultaneously: the counter promise, where a contractor walks in and expects a sharp, tier-correct price and immediate will-call availability; the project promise, where a multi-floor job is bid as a quoted package, revised as the spec changes, and kitted floor by floor once awarded; and the credit promise, where the house extends terms to good accounts without letting exposure quietly outrun the credit limit. This document specifies the API that backs all three. It governs the catalog of pipe, valves, fittings, and fixtures; contractor accounts with tiered pricing and terms; project quotes and their revision chains; showroom selection sheets for homeowner special orders; counter orders with promotional and override pricing; per-branch inventory reservation with a backorder waterfall; takeoff kitting and will-call bin staging; truck-window delivery booking bounded by cube capacity; returns of stocked material with restocking fees; and manufacturer stocking programs that accrue rebates against purchase thresholds.

Two design commitments shape every workflow in this document. First, pricing and credit are never improvised at the point of sale: counter prices resolve deterministically from account tier, promotional pricing, and a hard floor over replacement cost, while every order submission re-checks the account's forward-looking credit exposure before a single unit is reserved. Second, the warehouse is honest about time: receipts, backorder fills, quote expiry, delivery-window completion, and past-due aging all hang off a single logical clock, so two branches reading the same account at the same moment see the same standing. Everything is exposed under the `/pvf` API prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The platform recognizes exactly five roles: `BranchManager`, `CounterRep`, `InsideSales`, `WarehouseLead`, and `Contractor`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles divide the work of the branch along familiar lines. A `BranchManager` is the branch general manager and owns the catalog, manufacturer programs, delivery slots, credit reviews, price overrides, and return decisions. A `CounterRep` runs the will-call counter: building counter orders, submitting and cancelling orders, taking payments, booking delivery windows, running pickups, and originating returns. An `InsideSales` representative opens contractor accounts and owns quotes, selection sheets, takeoff kitting, and substitute proposals. A `WarehouseLead` receives stock, manages inventory records, stages orders and kits, dispatches trucks, confirms deliveries, and receives approved returns. A `Contractor` is the customer and acts only within its own account scope.

When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`; ownership checks on any account-scoped resource compare the resource's `account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. This ownership rule governs awarding a quote, approving a selection sheet, deciding a proposed substitute, and every account-scoped read (the contractor's own account, quotes, sheets, orders, order lines, payments, and returns). When `X-User-Role` is `BranchManager`, `CounterRep`, `InsideSales`, or `WarehouseLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution — for example as `posted_by` on a stock receipt, or as `submitted_by` and `decided_by` on a return request — but never compares it to any entity's `id`.

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
- Requests that match no route, or that use an unsupported method on a matched route, are answered in this same envelope with `error_id` `ERR_INVALID_REQUEST` and HTTP status 404 or 405 respectively.

### 2.3. Pagination and Collection Filtering

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

Several list endpoints accept additional filter parameters, all of which combine with pagination: the product list accepts `category`, `manufacturer_name`, and `substitute_group`; the account list accepts `status`; the quote list accepts `account_id`, `branch_id`, `status`, and `supersedes_quote_id`; the selection-sheet list accepts `account_id`, `branch_id`, and `status`; the manufacturer-program list accepts `manufacturer_name` and `status`; order lists scoped to an account or a branch accept `fulfillment_status`; the branch inventory list accepts `product_id`; and the branch delivery-slot list accepts `truck_label`. The job-costing computed read requires a `job_name` query parameter naming the job to report on.

### 2.4. Common Resource Properties

Every resource in the system — branches, products, contractor accounts, manufacturer programs, inventory stock records, stock receipts, payments, quotes, selection sheets, orders, order lines, kits, delivery slots, and return requests — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation of the resource. This field is the basis of optimistic concurrency control where that mechanism applies (§2.8).

Cascading side effects are mutations like any other. When one operation ripples into another resource — a receipt that allocates a waiting order line, a delivered order that debits an account balance, a booking that fills a truck window — each affected resource has its own `updated_at` refreshed and its own `version` incremented. All such cascades settle immediately: every mutation and every downstream effect of a request is visible in that request's response envelope, with no deferred or eventually-consistent states.

### 2.5. The Logical Clock and Scheduled Automation

The platform keeps a single logical clock. Before it has ever been set, the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `BranchManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; a missing or unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`, and any valid instant is accepted unconditionally as the clock's new reading. Every system-stamped timestamp in the domain — a receipt's `received_at`, a payment's `applied_at`, a quote's `awarded_at`, a sheet's `approved_at`, a return's `submitted_at`, an order's `invoiced_at` — reads this logical clock.

Advancing the clock is not a passive act. As time moves forward, the system fires its time-driven transitions in the same envelope: any `SUBMITTED` quote whose `valid_until` the clock has passed falls to `EXPIRED`; any `OPEN` or `FULL` delivery slot whose `window_end` the clock has passed moves to `COMPLETED`; and the credit sweep re-evaluates every account, engaging `CREDIT_HOLD` on accounts that now carry a past-due invoice and releasing holds whose conditions have cleared (§2.9).

### 2.6. Monetary Precision and Rounding Discipline

All monetary values in the system — prices, costs, totals, fees, credits, balances, limits — are integer cents. No floating-point arithmetic is used anywhere. Wherever a calculation produces a fractional cent, the final value is rounded half up to a whole cent; this applies to tier-priced counter lines, volume-discount amounts, and earned rebates. Two deliberate exceptions refine the rule. The price floor (§3.6) is a ceiling-style rounding: the smallest whole-cent amount that is greater than or equal to one hundred and five percent of the product's replacement cost, so a fractional result always rounds up. And the restocking fee on a return is rounded per line before any summation — summing the line values first and rounding once is forbidden (§3.10). Quantities, cube units, and day counts are integers throughout.

### 2.7. Request Validation Pipeline and Nested Resource Retrieval

Every request is validated against an ordered pipeline, and when several checks would fail on the same request, the check that sits earliest in this order determines the returned error:

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.
2. Role authorization — the acting role is listed among the endpoint's authorized roles; otherwise `ERR_FORBIDDEN`.
3. Path-template identifiers — path ids are resolved left to right, and the first id that does not resolve produces that resource's not-found error: `ERR_BRANCH_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, or `ERR_SHEET_NOT_FOUND`. A request aimed at a stock receipt under a branch that does not exist therefore fails with `ERR_BRANCH_NOT_FOUND` before the receipt is ever considered.
4. Ownership scope — when the role is `Contractor`, the `X-User-ID` must equal the `account_id` of the account-scoped resource being read or acted on; otherwise `ERR_FORBIDDEN`. This ownership check runs once the path's resource has resolved and before any state evaluation, so a contractor reaching for another account's quote is refused with `ERR_FORBIDDEN` even if that quote could no longer be awarded anyway.
5. Request body shape — required fields are present, enum members are valid, quantities are at least 1, `cut_length_ft` is present exactly when the line's product is cut-to-order and absent otherwise (necessarily evaluated once the line's `product_id` has resolved), a program's `period_end` is after its `period_start`, and a window's `window_end` is after its `window_start`; otherwise `ERR_INVALID_REQUEST`.
6. Body-referenced identifiers — foreign keys carried in the payload (the `product_id` on a line add, the `slot_id` on a booking, the `order_id` on a return, the `account_id` and `branch_id` on creates, the `substitute_product_id` on a substitute proposal) resolve to existing resources; otherwise the corresponding not-found error, such as `ERR_PRODUCT_NOT_FOUND`, is returned.
7. State-machine gating — the target entity's current status permits the requested transition; otherwise `ERR_INVALID_STATE`.
8. Account-standing gates, quote freshness, optimistic-concurrency freshness, temporal business rules (delivery-window past, return window, program period), business constraints (uniqueness, overlaps, capacity, segregation of duties, returnability, kit membership, substitute eligibility, line-order membership), and finally fiscal rules (credit limit, price floor, override authority) — each detailed in §2.8 through §2.11 and in the workflow narratives of §3.

Two precedence relationships inside this pipeline deserve explicit statement because they guard the same endpoint. When a line is added with a `price_override_cents` that is both below the price floor and offered by a non-manager, the price-floor check outranks the role check: the rejection is `ERR_PRICE_FLOOR_VIOLATION`, not `ERR_OVERRIDE_REQUIRES_MANAGER`. And at order submission, the account-standing gate outranks the credit-limit check: an order submitted against an account already on `CREDIT_HOLD` or `SUSPENDED` is rejected with `ERR_ACCOUNT_CREDIT_HOLD` even when the order would also have breached the credit limit.

### 2.8. Optimistic Concurrency Control

Three write operations in the system require the client to prove it is acting on a current view of a parent resource. Each carries a mandatory expected-version field naming the client-side observation; if the parent resource's `version` has advanced beyond that observation since the client last read it, the request is rejected and no state changes.

- Creating a superseding revision of an awarded quote requires `expected_quote_version` matching the quote's current `version`. A mismatch is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412), because an earlier revision creation has already legitimately superseded the quote — a second creation carrying the older expectation is working from a stale view of a quote that is no longer awarded.
- Booking an order into a delivery slot requires `expected_order_version` matching the order's current `version`. A mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), because intervening mutations — line reservation at submit, allocation cascades, a prior booking — change both the order's cube load and its version, and a stale expectation must not silently double-book or book the wrong load.
- Deciding a proposed substitute on an order line requires `expected_order_line_version` matching the line's current `version`. A mismatch is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412), because a prior decision or a backorder-allocation event has already legitimately moved the line, and a stale expectation carries no authority over its current state.

No other endpoint accepts an expected-version field. For every operation not listed here, mutations proceed without an optimistic-concurrency check.

### 2.9. Contractor Credit Policy: Dual Exposure Views and Hold Hysteresis

Credit is tracked on two complementary lenses over the same ledger, and the two can legitimately disagree for the same account at the same moment. The statement view, exposed as `outstanding_balance_cents`, is the chronological ledger balance: the sum of `total_cents` over orders whose `payment_status` is `INVOICED` or `PAID`, minus the sum of all payment `amount_cents` posted to the account, minus the sum of `credit_cents` over return requests that have reached `CREDITED`. The forward view, exposed as `forward_exposure_cents`, starts from that same statement balance and adds the `total_cents` of every order that is committed but not yet invoiced — orders whose `payment_status` is `UNINVOICED` and whose `fulfillment_status` is neither `DRAFT` nor `CANCELLED`. The account's headroom is `available_credit_cents`, defined as `credit_limit_cents` minus `forward_exposure_cents`; it may legitimately go negative. A computed read on the account reports both variants — `statement_balance_cents` beside `forward_exposure_cents` — together with `account_id`, `credit_limit_cents`, `available_credit_cents`, and the account `status`.

The credit hold cycle runs on hysteresis, so an account hovering near its limit does not flap between states. A hold engages automatically — after any balance recompute or clock advance — when the statement balance is strictly greater than `credit_limit_cents` (equality alone does not engage), or when any invoiced order has gone past due. An invoice is past due when the logical clock has passed its `invoiced_at` by more than the account's payment terms: `COD` terms allow zero days, `NET_15` allows fifteen days, and `NET_30` allows thirty days. A hold releases automatically only when both conditions clear together: the statement balance has fallen to at most eighty percent of `credit_limit_cents` — the threshold itself rounded half up to a whole cent, with a balance exactly equal to the threshold releasing — and no past-due invoice remains. Between eighty and one hundred percent utilization, an engaged hold persists; between them lies the dead band that gives the cycle its memory. Engaging or releasing the hold increments the account's `version`.

### 2.10. Inventory Reservation and the Backorder Waterfall

Stock is tracked per branch and per product on an inventory record holding `on_hand` (physical units present), `reserved` (units committed to allocated order lines), and `available` (always exactly `on_hand` minus `reserved` — an invariant the system maintains at all times). At most one inventory record may exist for a given branch-and-product pair. Reservation happens when an order is submitted: each line that can be fully covered from `available` is reserved in full, and each line that cannot is reserved for whatever portion is available — possibly zero — and joins the backorder pool.

The backorder pool drains through a strict waterfall whenever stock arrives or is freed. For the affected branch-and-product pair, waiting backordered lines are processed oldest first by the line's `created_at`, with ties broken by the owning order's `created_at` — never by resource id. Each candidate takes the smaller of its remaining shortage and the currently available stock; partial fills are allowed, and a candidate later in the queue simply gets nothing when stock exhausts. A candidate whose allocation reaches its full ordered quantity flips from `BACKORDERED` to `ALLOCATED`. After every candidate mutation, the system re-evaluates the owning order's picking readiness and the assembly posture of any kit the line belongs to, so a single receipt can cascade from stock to line to order to kit within one response.

### 2.11. Truck Cubes, Delivery Windows, and Staging Buffers

Delivery capacity is measured in cube units. Every product declares `cubes_per_unit`, and an order's `cubes_total` is the sum, over its non-`CANCELLED` lines, of each line's `qty_allocated` multiplied by its product's `cubes_per_unit`; this load is the basis for truck booking. A delivery slot defines a truck window at a branch with a `capacity_cubes`, and its `booked_cubes` is the sum of `cubes_total` over orders holding an active booking in that slot — orders whose `fulfillment_status` is not `CANCELLED`. A booking is allowed while the slot's `booked_cubes` plus the order's `cubes_total` stays less than or equal to `capacity_cubes`; a booking that lands exactly on capacity is accepted, and it is equality that flips the slot from `OPEN` to `FULL`. When a booking is later released and the load drops below capacity, the slot flips back from `FULL` to `OPEN` automatically.

Two spatial disciplines protect shared physical resources. On the same branch and the same `truck_label`, the half-open window intervals of slots — from `window_start` up to but not including `window_end` — may not intersect, though two windows that merely touch end-to-start are allowed; a colliding definition is rejected with `ERR_SLOT_OVERLAP`. In the will-call staging area, a kit occupying a `staging_bin` holds that bin through its `staged_window_end` plus a two-hour turnaround buffer; another kit staged into the same bin collides unless its window starts at or after that buffered hand-off — a gap of exactly two hours is allowed — and a colliding staging is rejected with `ERR_BIN_OVERLAP`.

## 3. Business Logic & Workflows

### 3.1. Catalog, Branches, and Receiving Stock

Everything starts with the branch network and the catalog. A `BranchManager` creates a branch with a display `name` and a short `code`; the code must be unique across all branches, and a duplicate is rejected with `ERR_BRANCH_CODE_EXISTS`. Products are created one at a time with a unique `sku` (a duplicate is rejected with `ERR_SKU_EXISTS`), a catalog `description`, a `category` of exactly one of `PIPE`, `VALVE`, `FITTING`, or `FIXTURE`, a `list_price_cents` of at least 1 (interpreted per foot for cut-to-order items), and a `cost_cents` of at least 0 that anchors the price floor. Each product also carries the `manufacturer_name` label that joins receipts to manufacturer rebate programs, and the `cubes_per_unit` — an integer of at least 0 — that drives truck capacity. Two flags change how a product is sold: `is_cut_to_order` (default false) marks a cut-to-length item sold per foot and never returnable, and `is_special_order` (default false) marks a showroom special-order item, likewise never returnable. Products that can stand in for one another share a non-null `substitute_group` (default null), and a branch counter promotional price may be set through `promo_price_cents` (default null, at least 1 when present); the promotional price applies to counter orders only and never to quote lines.

Before stock can be tracked for a product at a branch, a `WarehouseLead` creates the inventory record for the pair by supplying the `product_id` and an `initial_on_hand`; the record starts with `on_hand` equal to `initial_on_hand` and `reserved` at 0. A second record for the same branch-and-product pair is rejected with `ERR_STOCK_RECORD_EXISTS`.

Receiving is the heartbeat of replenishment. A `WarehouseLead` posts a stock receipt against a branch as a batch of `lines`, each naming a `product_id`, a `qty` of at least 1, and a `unit_cost_cents` of at least 0; a receipt must carry at least one line. Posting stamps `received_at` from the logical clock and `posted_by` from the operator's `X-User-ID`, and the receipt lands in its single, append-only state `POSTED`. Each line adds its quantity to the pair's `on_hand`, auto-creating the inventory record with an `on_hand` of 0 first when none exists yet. Two cascades then fire in the same response. Any manufacturer program whose `manufacturer_name` matches the line's product and whose accrual window contains the receipt's `received_at` accrues the line's quantity times its `unit_cost_cents` into the program's `purchases_cents`. And the backorder waterfall (§2.10) runs for each received product, which can flip waiting lines from `BACKORDERED` to `ALLOCATED`, bubble their orders from `OPEN` to `PICKING`, and recompute kit assembly posture.

For day-to-day visibility, the catalog exposes reverse-reachability reads: the stock rows of a single product across branches, and the order lines that reference a product either as the ordered `product_id` or as a pending `proposed_substitute_product_id`. The order-line rows of this read are returned as stored, without the computed `qty_backordered` overlay that the order-scoped line reads apply (§3.7).

### 3.2. Manufacturer Stocking Programs and Rebates

A stocking program formalizes a rebate agreement with one manufacturer. A `BranchManager` creates it with the `manufacturer_name` it covers (matching the product label), a `period_start` and `period_end` bounding the accrual window, a `tiers` ladder, and the contracted `committed_stock_value_cents` (at least 0) recorded at creation. The window is a closed interval — both boundary instants are inside the period — and `period_end` must be later than `period_start`, with an inverted period rejected as `ERR_INVALID_REQUEST`. The `tiers` ladder holds at least one rung, each rung pairing a `threshold_cents` with a `rebate_pct`; thresholds must be strictly ascending, and each `rebate_pct` is an integer percent from 1 to 50. Programs for the same `manufacturer_name` may not touch or intersect: because the intervals are closed, two periods that share even a boundary date conflict, and the conflicting creation is rejected with `ERR_PROGRAM_OVERLAP`. Different manufacturers are unrestricted.

While a program is `ACTIVE`, qualifying receipt lines accumulate into `purchases_cents` as described in §3.1; `attained_rebate_pct` and `earned_rebate_cents` remain null until close. Once the logical clock has moved past `period_end` — a close attempted earlier is rejected with `ERR_PROGRAM_PERIOD_NOT_ENDED` — a `BranchManager` closes the program. Closing computes attainment: the highest rung whose `threshold_cents` is less than or equal to the accumulated `purchases_cents` is attained (purchases exactly equal to a threshold attain that rung), and `attained_rebate_pct` becomes that rung's percent, or 0 when no rung qualifies. The earned rebate is then `purchases_cents` multiplied by `attained_rebate_pct` and divided by 100, rounded half up to a whole cent, and stored as `earned_rebate_cents`; the program lands in `CLOSED`. A later settle action by a `BranchManager` records payout and moves the program from `CLOSED` to its terminal state `SETTLED`. Each transition increments the program's `version`.

### 3.3. Contractor Accounts, Payments, and the Credit Cycle

An `InsideSales` representative opens a contractor account with the `company_name`, a `pricing_tier` of exactly one of `STANDARD`, `SILVER`, `GOLD`, or `PLATINUM`, payment `terms` of exactly one of `COD`, `NET_15`, or `NET_30`, and a `credit_limit_cents` of at least 0. New accounts start `ACTIVE`. The account's standing fields — `outstanding_balance_cents`, `forward_exposure_cents`, and `available_credit_cents` — are computed continuously per the dual-exposure model of §2.9, and the account `status` cycles among `ACTIVE`, `CREDIT_HOLD`, and `SUSPENDED` without any terminal state.

Payments are append-only credits against the statement ledger. A `CounterRep` posts a payment of `amount_cents` (at least 1) under a `method` of `CHECK`, `ACH`, or `CARD`, optionally with explicit `allocations` — a list pairing an `order_id` with an `amount_cents` to apply to that order. Each allocation's `amount_cents` must be at least 1, and each referenced `order_id` must resolve to an existing order of the same account: an unresolvable id is rejected with `ERR_ORDER_NOT_FOUND`, an order belonging to a different account with `ERR_INVALID_REQUEST`. When `allocations` is omitted, the payment spreads itself FIFO: the account's `INVOICED` orders are visited oldest first by `invoiced_at`, with ties broken by the order's `created_at` — never by id — and each order receives the smaller of what it is still owed (its `total_cents` less what prior payments already allocated to it) and the remaining unapplied payment. An order whose allocations reach its `total_cents` flips from `INVOICED` to `PAID`, its terminal payment state. Either way, explicit or automatic, the posting subtracts the full `amount_cents` from the account's `outstanding_balance_cents` exactly once, stamps `applied_at` from the logical clock, lands the payment in its single state `APPLIED`, increments the account's `version`, and re-evaluates hold release — a payment that brings the statement balance back under the release threshold while no invoice is past due lifts the hold.

Beyond the automatic cycle, a `BranchManager` can act on an account directly through a credit review carrying an `action`. `SUSPEND` moves an `ACTIVE` or `CREDIT_HOLD` account to `SUSPENDED`. `RELEASE_HOLD` moves a `CREDIT_HOLD` or `SUSPENDED` account back to `ACTIVE`; a release from suspension lands on `ACTIVE` regardless of the current balance, and the next balance recompute re-engages `CREDIT_HOLD` if the account is still over limit. `ADJUST_LIMIT` — defined only for an account currently `ACTIVE` — carries `new_credit_limit_cents` (at least 0), rewrites `credit_limit_cents`, recomputes the exposure views, and immediately re-evaluates the automatic hold, so tightening the limit below the current balance engages `CREDIT_HOLD` on the spot. Every credit review increments the account's `version`.

Two computed reads round out account stewardship. The credit-exposure read reports `account_id`, `credit_limit_cents`, `statement_balance_cents`, `forward_exposure_cents`, `available_credit_cents`, and `status` — the forward-looking and chronological variants side by side. The job-costing read, parameterized by `job_name`, scopes itself to the account's orders carrying that `job_name` whose `fulfillment_status` is not `CANCELLED`, and reports both cost variants: `provisional_cost_cents`, the sum of `line_total_cents` over lines in `OPEN`, `ALLOCATED`, `BACKORDERED`, or `FILLED` status, which includes unfulfilled commitment value and ignores pending returns; and `final_cost_cents`, the sum over `FILLED` lines only, of each line's `line_total_cents` minus its returned value (the `qty_returned` times the line's `unit_price_cents`, times `cut_length_ft` as well for cut items), netting out credited returns. The read also echoes the `job_name` and reports `order_count` — the number of in-scope orders — and `line_count`, the number of their non-`CANCELLED` lines in `OPEN`, `ALLOCATED`, `BACKORDERED`, or `FILLED` status (the same set of lines the provisional variant sums over); identical inputs can produce different provisional and final totals, which is the point of reporting both.

### 3.4. Project Bidding: Quotes, Revisions, and Conversion

Project business begins as a quote. An `InsideSales` representative creates one with the recipient `account_id`, the quoting `branch_id`, a `job_name` label that later anchors job costing, a `valid_until` bid deadline, and at least one bid line in `lines`, each naming a `product_id`, a `qty` of at least 1, and an explicit `unit_price_cents`. Quoted prices are never resolved from tier or promo — the bid price is the payload price — but every line must respect the price floor: at least one hundred and five percent of the product's `cost_cents`, rounded up to a whole cent; a line below the floor rejects the creation with `ERR_PRICE_FLOOR_VIOLATION`. A new quote starts in `DRAFT` with `revision_no` 1 and null `awarded_at`, and its document totals (§3.6) are computed over its lines at creation. `supersedes_quote_id` is null unless the creation payload supplies it; a supplied value must resolve to an existing quote (else `ERR_QUOTE_NOT_FOUND`) and is recorded as given, with `revision_no` still 1.

Submitting the quote — `DRAFT` to `SUBMITTED` — is performed by `InsideSales` and requires the bid still be fresh: `valid_until` must be later than the logical clock, or the submission is rejected with `ERR_QUOTE_EXPIRED`. A submitted quote then has four roads out. The contractor awards it (`SUBMITTED` to `AWARDED`) — an action only the account owner may take, so a contractor whose `X-User-ID` does not equal the quote's `account_id` is refused with `ERR_FORBIDDEN`; awarding also requires freshness, and an award attempted at or after `valid_until` is rejected with `ERR_QUOTE_EXPIRED` and the quote falls to `EXPIRED` in the same stroke. Award stamps `awarded_at` from the logical clock and locks the line prices, which are immutable from that point on. Alternatively, `InsideSales` marks the bid lost (`SUBMITTED` to `LOST`). Or time does the work: when the clock advances past `valid_until`, the quote auto-transitions from `SUBMITTED` to `EXPIRED` (§2.5). Each of these moves increments the quote's `version`.

Awarded quotes support a revision chain rather than edits. Creating a revision of an `AWARDED` quote — an `InsideSales` action guarded by the optimistic-concurrency rule of §2.8 via `expected_quote_version`, with staleness rejected as `ERR_STALE_QUOTE_VERSION` — lands the existing quote in its terminal `REVISED` state, bumps that quote's `version`, and creates a fresh quote in `DRAFT` whose `revision_no` is the predecessor's plus one and whose `supersedes_quote_id` points back at the predecessor. The payload must always carry a fresh `valid_until`; the new revision carries the old lines unless the payload supplies `lines`, and any supplied lines are floor-validated exactly as at creation. The `AWARDED` state gate and the `expected_quote_version` staleness check both run before any supplied `lines` are resolved and floor-validated. The new revision may itself be submitted and awarded, so the chain forms an award → revise → submit → award loop across successive rows, with `REVISED`, `LOST`, `EXPIRED`, and `CONVERTED` all terminal.

The end of a won bid is conversion. Converting an `AWARDED` quote — again `InsideSales` — moves the quote to terminal `CONVERTED` and creates an order in `DRAFT` whose `source` is `PROJECT` with `will_call` false: the order's `quote_id` points back at the quote, its `job_name` is inherited from the quote's `job_name`, and each quote line becomes an order line priced at the quote's locked `unit_price_cents` with `price_source` `QUOTE_LOCKED`. The order's `volume_discount_pct` is copied verbatim from the quote and locked, not re-tiered (§3.6). The orders produced from a quote remain discoverable through the quote's reverse-reachability read.

### 3.5. Showroom Selection Sheets and Special Orders

The showroom channel serves the homeowner standing next to the contractor. An `InsideSales` representative opens a selection sheet with the showroom `account_id` and `branch_id`, the end `customer_name`, and at least one entry in `selections`, each pairing a `product_id` with a `finish` and a `qty` of at least 1. Because sheets exist for fixtures and special-order material, every selected product must either have `category` `FIXTURE` or carry the `is_special_order` flag; a sheet violating this is rejected at creation with `ERR_INVALID_REQUEST`. A new sheet starts in `DRAFT` with a null `approved_at`.

Presenting moves the sheet to `PRESENTED`, from either `DRAFT` or — in the revision loop — from `REVISED`. The customer then approves: a `Contractor` whose `X-User-ID` equals the sheet's `account_id` moves the sheet from `PRESENTED` to `APPROVED` (a foreign contractor is refused with `ERR_FORBIDDEN`), stamping `approved_at` from the logical clock. Approval is not the end of the conversation: `InsideSales` may revise an `APPROVED` sheet, which replaces `selections` wholesale with the payload's `selections`, clears `approved_at` back to null, and returns the sheet to `REVISED` — from which it is presented and approved again, an `APPROVED` → `REVISED` → `PRESENTED` → `APPROVED` loop. Each transition increments the sheet's `version`.

Conversion closes the loop. Converting an `APPROVED` sheet moves it to its terminal state `ORDERED` and creates an order in `DRAFT` whose `source` is `SHOWROOM`, with null `job_name` and `will_call` false: the order's `sheet_id` points back at the sheet, and each selection becomes an order line priced at the product's `list_price_cents` with `price_source` `SHOWROOM_LIST` — no contractor tier discount and no promotional pricing applies to showroom lines, though volume-tier and freight rules still govern the document totals (§3.6). Orders born of a sheet are discoverable through the sheet's reverse-reachability read.

### 3.6. Counter Orders: Line Pricing, Overrides, and Document Totals

Counter business starts when a `CounterRep` creates an order with the buying `account_id`, the fulfilling `branch_id`, an optional `job_name` for job-costing grouping, and an optional `will_call` flag (default false) that chooses the exit path: a will-call order ultimately leaves through pickup, while a delivery order leaves by truck. Orders created at the counter carry `source` `COUNTER`, no quote or sheet lineage (`quote_id` and `sheet_id` null), no delivery booking (`delivery_slot_id` null), and begin with `fulfillment_status` `DRAFT` and `payment_status` `UNINVOICED`.

Lines are added to a `DRAFT` order one at a time, by a `CounterRep` or a `BranchManager`, with a `product_id`, a `qty`, and — exactly when the product is cut-to-order — a `cut_length_ft` of at least 1 (present on a non-cut product, or missing on a cut product, is `ERR_INVALID_REQUEST`). A `PROJECT` order never accepts added lines — its lines are locked to the source quote — and the attempt is rejected with `ERR_INVALID_STATE`. A cut line's `qty_ordered` counts cuts and its extension runs per foot: `line_total_cents` is `qty_ordered` times `unit_price_cents` for ordinary items, and `qty_ordered` times `cut_length_ft` times `unit_price_cents` for cut items, since cut pricing is per foot. The ordered quantity is recorded as `qty_ordered`, the allocation and fulfillment counters `qty_allocated`, `qty_fulfilled`, and `qty_returned` all start at 0, the line's `kit_id` is null until kitting claims it, `status` starts `OPEN`, and `substitute_status` starts `NONE`.

Unit price resolution depends on the order's channel. On a `COUNTER` order, the account's tier sets the baseline: `STANDARD` accounts pay list price, while `SILVER`, `GOLD`, and `PLATINUM` earn 5, 10, and 15 percent off respectively; the tier price is the product's `list_price_cents` reduced by that percentage, rounded half up to a whole cent. When the product carries a `promo_price_cents`, the resolved price is the lower of the tier price and the promotional price — the line stamps `price_source` `PROMO` when the promotional price is strictly lower, otherwise `COUNTER_TIER`. A manual `price_override_cents` — an integer of at least 1 — may instead be supplied, under two guards: the acting role must be `BranchManager` (anyone else is rejected with `ERR_OVERRIDE_REQUIRES_MANAGER`), and the override must respect the same price floor as quotes — at least one hundred and five percent of the product's `cost_cents`, rounded up to a whole cent (a violation is `ERR_PRICE_FLOOR_VIOLATION`, and per §2.7 the floor rejection outranks the role rejection when both fail). An accepted override becomes the line's `unit_price_cents` with `price_source` `MANUAL_OVERRIDE`. On `PROJECT` orders the price is copied from the source quote line and stamped `QUOTE_LOCKED`; on `SHOWROOM` orders it is the product's `list_price_cents`, stamped `SHOWROOM_LIST`. Either way, the resolved `unit_price_cents` and `price_source` are recorded on the line.

Document totals follow one pinned evaluation order, identical in shape for quotes and orders, and it is pinned precisely because the natural reading is circular. First, `subtotal_cents` is the sum of line extensions over non-`CANCELLED` lines (cut items extended per foot as above). Second, `volume_discount_pct` is selected from the volume ladder against the pre-discount subtotal only: a subtotal of at least 500,000 cents earns 2 percent, and a subtotal of at least 2,000,000 cents earns 5 percent, with the highest qualifying tier applying. Third, `discount_cents` is the subtotal multiplied by that percent and divided by 100, rounded half up to a whole cent — the only rounding point in the ladder. Fourth, the post-discount subtotal is the subtotal minus the discount. Fifth, `freight_cents` is 0 when the post-discount subtotal is at least 50,000 cents, and a flat 2,500 cents otherwise. Sixth, `total_cents` is the post-discount subtotal plus freight. Re-tiering the volume discount against the post-discount value is forbidden; the tier keys on the first step alone. `COUNTER` and `SHOWROOM` orders evaluate this ladder at creation and re-run it on every line or allocation mutation — add, submit, backorder-allocation fills, substitute approval, staging picks, booking, or cancel — while `PROJECT` orders skip the second step entirely, carrying the locked `volume_discount_pct` copied from their source quote. Quotes compute the same totals at creation and at each revision.

### 3.7. Order Fulfillment: Reservation, Backorders, and Substitutions

Submitting a `DRAFT` order is the point of commitment, executed by a `CounterRep`. Three gates stand in front of it, in pipeline order: the account must be `ACTIVE` — a `CREDIT_HOLD` or `SUSPENDED` account rejects the submission with `ERR_ACCOUNT_CREDIT_HOLD`; the account's forward exposure plus this order's `total_cents` must stay within `credit_limit_cents`, with equality allowed — a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402), and per §2.7 the standing gate outranks this check when both fail; and the order must carry at least one line, else `ERR_INVALID_STATE`. On a successful submission the order's `fulfillment_status` moves from `DRAFT` to `OPEN`, and each line reserves stock per §2.10: a line whose product's `available` covers its `qty_ordered` becomes `ALLOCATED` with `qty_allocated` set to the full quantity and the stock record's `reserved` raised accordingly, while a short line becomes `BACKORDERED` with `qty_allocated` holding whatever portion was available, possibly zero. The account's `forward_exposure_cents` now counts the order. While a line remains unfulfilled, its `qty_backordered` reads as the ordered quantity minus the allocated and fulfilled quantities; once the line reaches `FILLED` or `CANCELLED` it reads 0.

From `OPEN`, the order promotes itself: the moment every non-`CANCELLED` line is `ALLOCATED` or `FILLED` — whether by the initial reservation, by the backorder waterfall, or by a substitute approval — the order bubbles automatically from `OPEN` to `PICKING`. Cancellation is available to a `CounterRep` from `DRAFT`, `OPEN`, or `PICKING`. Cancelling a `DRAFT` order is trivial, since no reservations exist yet. Cancelling from `OPEN` or `PICKING` unwinds the world: each line releases its reservation (the stock record's `reserved` drops by the line's `qty_allocated`), any active delivery booking is released (the slot's `booked_cubes` drops by the order's `cubes_total`, and a `FULL` slot recomputes to `OPEN`), lines in `OPEN`, `ALLOCATED`, or `BACKORDERED` fall to `CANCELLED` (allocated and backordered lines additionally return their reserved quantities), and the account's forward exposure is recomputed. Either way the order lands in terminal `CANCELLED` with its `version` incremented.

When a line sits `BACKORDERED`, `InsideSales` can propose a substitute product by naming a `substitute_product_id`. The proposal is only meaningful on a backordered line, and quote-locked lines may not be substituted at all — proposing on a line that is not `BACKORDERED`, or on one whose `price_source` is `QUOTE_LOCKED`, is rejected with `ERR_INVALID_STATE`. The substitute must share the original product's non-null `substitute_group`; a mismatch is rejected with `ERR_SUBSTITUTE_GROUP_MISMATCH`. An accepted proposal moves the line's `substitute_status` to `PROPOSED` — whether it was `NONE`, `REJECTED`, or a prior `APPROVED` — and records the candidate in `proposed_substitute_product_id`, incrementing the line's `version`.

The decision belongs to the contractor. Acting within its own account scope (`X-User-ID` equal to the order's `account_id`, else `ERR_FORBIDDEN`) and under the optimistic-concurrency rule of §2.8 (`expected_order_line_version`, staleness rejected with `ERR_STALE_LINE_VERSION`), the contractor answers the proposal with a `decision`. An `APPROVE` decision moves `substitute_status` from `PROPOSED` to `APPROVED`: any partial reservation held on the original product is released first (the stock record's `reserved` drops by the line's `qty_allocated`), the line's `product_id` is swapped to the proposed product, `proposed_substitute_product_id` is cleared, the `unit_price_cents` is re-resolved through the counter price rules of §3.6 (quote-locked lines never reach this path), the reservation is retried against the substitute product's stock — which may land the line `ALLOCATED` through the same waterfall mechanics — and line and order totals are recomputed. A `REJECT` decision moves `substitute_status` to `REJECTED`, clears `proposed_substitute_product_id`, and leaves the line in the backorder pool at its original queue position, its `created_at` unchanged. Either decision increments the line's `version`.

### 3.8. Kitting, Will-Call Staging, and Order Completion

Project material is pulled floor by floor. `InsideSales` groups an order's lines into a kit by supplying a `floor_label` — the takeoff's zone marker, such as `F2` or `MECH-ROOM` — and the `order_line_ids` to group. Every referenced line must belong to the order in the path (a foreign line is rejected with `ERR_LINE_ORDER_MISMATCH`) and must not already belong to another kit whose status is not `RELEASED` (double-kitting is rejected with `ERR_KIT_LINE_CONFLICT`). Kit creation is not gated on the order's fulfillment status or source. Creation writes the kit's id onto each member line's `kit_id`, and the kit's posture is compound: it starts `DRAFT` with no bin or window assigned (`staging_bin`, `staged_window_start`, and `staged_window_end` all null), and promotes automatically to `ASSEMBLED` the moment every member line is `ALLOCATED` or `FILLED` — a condition re-evaluated on line allocation, on kit creation (so a kit built over already-allocated lines assembles immediately), and on substitute approval.

Staging and rework are manual, both `WarehouseLead` actions. Staging an `ASSEMBLED` kit assigns a `staging_bin` together with a `window_start` and `window_end` (end after start, else `ERR_INVALID_REQUEST`), recorded on the kit as `staged_window_start` and `staged_window_end`, and enforces the two-hour bin-turnaround rule of §2.11 — a colliding staging is rejected with `ERR_BIN_OVERLAP`. Unstaging returns a `STAGED` kit to `ASSEMBLED`, clearing the bin assignment and window so the bin is freed. Each move increments the kit's `version`.

With the order `PICKING`, a `WarehouseLead` marks it staged. For a will-call order that has at least one kit, every kit of the order must already be `STAGED` — otherwise the request is rejected with `ERR_INVALID_STATE`; a will-call order with no kits stages directly. Marking staged picks every `ALLOCATED` line: the line's `qty_fulfilled` is set to its `qty_allocated` (which is retained for audit), the line moves to `FILLED`, and the stock record for each line's product has both `on_hand` and `reserved` reduced by the fulfilled quantity. The order's `fulfillment_status` moves from `PICKING` to `STAGED`.

From `STAGED`, the order leaves by one of two doors. A delivery order is dispatched by a `WarehouseLead`, which requires an active delivery booking — an order whose `delivery_slot_id` is null cannot dispatch and is rejected with `ERR_INVALID_STATE`; dispatch moves the order to `DISPATCHED` and releases every `STAGED` kit on the order to `RELEASED`. A subsequent delivery confirmation by a `WarehouseLead` moves the order to terminal `DELIVERED`. A will-call order instead completes at the counter: a `CounterRep` runs the pickup, which requires the order's `will_call` flag be true (a pickup attempted on a delivery order is rejected with `ERR_INVALID_STATE`), moves the order from `STAGED` to terminal `PICKED_UP`, and likewise releases its `STAGED` kits to `RELEASED`.

Either completion fires the invoicing cascade in the same response: the order's `payment_status` moves from `UNINVOICED` to `INVOICED`, `invoiced_at` is stamped from the logical clock (this timestamp drives both the payment FIFO order of §3.3 and past-due aging of §2.9), the order's `total_cents` is added to the account's `outstanding_balance_cents`, and the credit hold is re-evaluated — a completion that pushes the statement balance strictly past the limit engages `CREDIT_HOLD`. The order's two dimensions then evolve independently again until payments carry `payment_status` to terminal `PAID`.

### 3.9. Delivery Windows and Truck Booking

A `BranchManager` defines delivery capacity one truck window at a time: a `truck_label` identifying the truck within the branch, a `window_start` and `window_end` (end strictly after start, else `ERR_INVALID_REQUEST`), and a `capacity_cubes` of at least 1. The half-open overlap rule of §2.11 applies per branch and truck, with touching windows allowed and intersecting ones rejected with `ERR_SLOT_OVERLAP`; slots already in `CANCELLED` or `COMPLETED` status do not participate in the overlap check. A new slot opens in `OPEN` with `booked_cubes` 0 and cycles automatically between `OPEN` and `FULL` as bookings arrive and release (§2.11); when the logical clock passes `window_end`, an `OPEN` or `FULL` slot moves to terminal `COMPLETED` (§2.5). A `BranchManager` may also cancel a slot outright, but only while the slot is `OPEN` or `FULL` and nothing is booked — a cancellation in any other status, or with any active booking, is rejected with `ERR_INVALID_STATE` — moving it to terminal `CANCELLED` and incrementing its `version`.

Booking an order into a slot is a `CounterRep` action guarded on five fronts, in pipeline order. The order's `fulfillment_status` must be `OPEN`, `PICKING`, or `STAGED`, and the order must not already hold an active booking (`delivery_slot_id` must be null); violations are rejected with `ERR_INVALID_STATE`. The account must be `ACTIVE`, else `ERR_ACCOUNT_CREDIT_HOLD`. The request must carry `expected_order_version` matching the order's current `version` per §2.8, else `ERR_STALE_ORDER_VERSION`. The slot's `window_end` must still be ahead of the logical clock, else `ERR_DELIVERY_WINDOW_PAST`. And the slot must have room for the order's `cubes_total` under the equality-allowed capacity rule of §2.11, else `ERR_SLOT_FULL`. A successful booking records the `slot_id` on the order's `delivery_slot_id`, raises the slot's `booked_cubes` by the order's `cubes_total` — flipping the slot to `FULL` when equality is reached — and increments the order's `version`. Cancelling the booking releases the cube load, recomputes a `FULL` slot back to `OPEN`, clears `delivery_slot_id` to null, and increments the order's `version`. The orders booked into a slot remain discoverable through the slot's reverse-reachability read.

### 3.10. Returns, Restocking Fees, and Account Credit

Returns of stocked material begin at the counter: a `CounterRep` creates a return request in `DRAFT` against an `order_id`, with a free-text `reason` and at least one entry in `lines`, each naming an `order_line_id` and a `qty` of at least 1. Every referenced line must belong to the return's order — a foreign line is rejected with `ERR_LINE_ORDER_MISMATCH`, both at creation and again at submission.

Submission is where the return proves itself, through four business checks whose pipeline order matters: the window check first, then returnability, then the aggregate empty check, then per-line quantity. The return window is 90 days: the order's fulfillment timestamp is its `invoiced_at`, and the logical clock at submission may be no more than 90 days after it, else `ERR_RETURN_WINDOW_EXPIRED`; an order that has never been invoiced has no fulfillment timestamp, so the window check does not fire and the aggregate empty check below does the rejecting. No return line may reference a cut-to-order or special-order product, else `ERR_NON_RETURNABLE_ITEM`. Across the referenced lines, at least one must have remaining returnable quantity — fulfilled minus already returned greater than zero — else the return is rejected with `ERR_EMPTY_RETURN`. And per line, the returned `qty` may not exceed that line's fulfilled-minus-returned remainder, else `ERR_RETURN_QTY_EXCEEDS_FULFILLED`. A submission that passes stamps `submitted_by` from the operator's `X-User-ID` and `submitted_at` from the logical clock, moves the return to `SUBMITTED`, and increments its `version`.

The decision belongs to a `BranchManager`, and segregation of duties is hard: the decider's `X-User-ID` must differ from `submitted_by`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `decision` forks the workflow into two deliberately divergent branches. A `REJECT` decision records `decided_by`, moves the return to terminal `REJECTED`, and touches nothing — no inventory, no balance, no fees. An `APPROVE` decision records `decided_by`, computes the money, and moves the return to `APPROVED`. The fee schedule keys on whole days between the order's fulfillment timestamp and the return's `submitted_at`: ten percent when the return was submitted within 30 days of fulfillment, and twenty-five percent when submitted more than 30 but no more than 90 days after. Each returned line's value is its `qty` times the order line's `unit_price_cents` — times `cut_length_ft` as well for cut items — and the rounding order is pinned: each line's fee is its value multiplied by the applicable percent and divided by 100, rounded half up to a whole cent, and the per-line fees are then summed into `restocking_fee_cents`; summing the values first and rounding once is forbidden. The `credit_cents` is the sum of the line values minus `restocking_fee_cents`; freight is never credited.

Receiving closes the loop. A `WarehouseLead` receives an `APPROVED` return, moving it to terminal `CREDITED`, and the restock cascade fires in the same response: for each line, the stock record's `on_hand` rises by the returned quantity (auto-creating the inventory record with an `on_hand` of 0 first when none exists, exactly as at receiving) and the order line's `qty_returned` rises likewise; the restock triggers the backorder waterfall of §2.10 for the restocked products, which can flip waiting lines to `ALLOCATED` and bubble their orders to `PICKING`; the account's `outstanding_balance_cents` falls by the return's `credit_cents`; and the credit hold release is re-evaluated against the new balance. The return's `version` increments, and the credited amount feeds both the statement balance of §2.9 and the final-cost variant of job costing (§3.3).

## 4. Endpoint Definitions

Operations that create a new resource — including conversion actions that mint an order, revision creation, which mints the superseding quote, and posting a payment, which mints a new payment resource on the account — return `201 Created`. Operations that act on an existing resource, including all state-transition actions, return `200 OK`. The complete endpoint surface is:

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pvf/branches` | Create a branch | BranchManager |
| GET | `/pvf/branches` | List branches (paginated) | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/branches/{id}` | Get one branch | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/products` | Create a catalog product | BranchManager |
| GET | `/pvf/products` | List products with filters (paginated) | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/products/{id}` | Get one product | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/products/{id}/inventory` | List stock records holding this product | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/products/{id}/order-lines` | List order lines referencing this product as ordered or proposed substitute | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/contractor-accounts` | Open a contractor account | InsideSales |
| GET | `/pvf/contractor-accounts` | List accounts (paginated, filter by status) | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/contractor-accounts/{id}` | Get one account | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/contractor-accounts/{id}/credit-review` | Manager credit action: RELEASE_HOLD, SUSPEND, or ADJUST_LIMIT | BranchManager |
| GET | `/pvf/contractor-accounts/{id}/credit-exposure` | Computed credit exposure read (statement vs forward variants) | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/contractor-accounts/{id}/job-costing` | Computed job cost report for one job name (provisional and final variants) | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/contractor-accounts/{id}/quotes` | List quotes of an account | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/contractor-accounts/{id}/selection-sheets` | List selection sheets of an account | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/contractor-accounts/{id}/orders` | List orders of an account | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| GET | `/pvf/contractor-accounts/{id}/payments` | List payments of an account | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/contractor-accounts/{id}/payments` | Take a payment; explicit allocations or FIFO auto-allocation over invoiced orders | CounterRep |
| POST | `/pvf/branches/{id}/inventory` | Create the stock record for a branch-and-product pair | WarehouseLead |
| GET | `/pvf/branches/{id}/inventory` | List stock records of a branch | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/branches/{id}/stock-receipts` | Post a stock receipt; replenishes stock and runs the allocation cascade | WarehouseLead |
| GET | `/pvf/branches/{id}/stock-receipts` | List receipts of a branch | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/branches/{id}/orders` | List orders fulfilled by a branch | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/branches/{id}/delivery-slots` | List delivery slots of a branch | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/quotes` | Create a project quote with explicit bid prices | InsideSales |
| GET | `/pvf/quotes` | List quotes with filters (paginated) | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/quotes/{id}` | Get one quote | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/quotes/{id}/submit` | Submit the bid to the contractor | InsideSales |
| POST | `/pvf/quotes/{id}/award` | Contractor awards the bid; locks prices | Contractor |
| POST | `/pvf/quotes/{id}/lose` | Mark the bid lost | InsideSales |
| POST | `/pvf/quotes/{id}/revisions` | Create a superseding revision of an awarded quote (OCC-guarded) | InsideSales |
| POST | `/pvf/quotes/{id}/convert` | Convert an awarded quote to a project order with locked prices | InsideSales |
| GET | `/pvf/quotes/{id}/orders` | List orders converted from a quote | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/selection-sheets` | Create a showroom selection sheet | InsideSales |
| GET | `/pvf/selection-sheets` | List selection sheets with filters (paginated) | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/selection-sheets/{id}` | Get one selection sheet | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/selection-sheets/{id}/present` | Present the sheet to the customer | InsideSales |
| POST | `/pvf/selection-sheets/{id}/approve` | Customer approves the selections | Contractor |
| POST | `/pvf/selection-sheets/{id}/revise` | Revise an approved sheet, replacing its selections | InsideSales |
| POST | `/pvf/selection-sheets/{id}/convert` | Convert an approved sheet to a showroom order at list prices | InsideSales |
| GET | `/pvf/selection-sheets/{id}/orders` | List orders converted from a sheet | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/orders` | Create a counter order | CounterRep |
| GET | `/pvf/orders/{id}` | Get one order | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/orders/{id}/lines` | Add a line to a draft order; resolves the unit price | CounterRep, BranchManager |
| GET | `/pvf/orders/{id}/lines` | List lines of an order | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/orders/{id}/submit` | Submit a draft order: account gate, credit check, inventory reservation | CounterRep |
| POST | `/pvf/orders/{id}/cancel` | Cancel an order; releases reservations and any booking | CounterRep |
| POST | `/pvf/orders/{id}/mark-staged` | Mark a picking order staged; picks all allocated lines | WarehouseLead |
| POST | `/pvf/orders/{id}/dispatch` | Dispatch a staged order holding an active delivery booking | WarehouseLead |
| POST | `/pvf/orders/{id}/confirm-delivery` | Confirm jobsite delivery; auto-invoices | WarehouseLead |
| POST | `/pvf/orders/{id}/pickup` | Will-call pickup of a staged order; auto-invoices | CounterRep |
| POST | `/pvf/orders/{id}/delivery-booking` | Book the order into a delivery slot (OCC-guarded) | CounterRep |
| POST | `/pvf/orders/{id}/delivery-booking/cancel` | Cancel the active delivery booking | CounterRep |
| POST | `/pvf/order-lines/{id}/propose-substitute` | Propose a substitute product for a backordered line | InsideSales |
| POST | `/pvf/order-lines/{id}/substitute-decision` | Contractor approves or rejects a proposed substitute (OCC-guarded) | Contractor |
| POST | `/pvf/orders/{id}/kits` | Create a floor or zone kit over the order's lines | InsideSales |
| GET | `/pvf/orders/{id}/kits` | List kits of an order | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/kits/{id}` | Get one kit | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/kits/{id}/lines` | List lines assigned to a kit | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/kits/{id}/stage` | Stage an assembled kit into a will-call bin for a window | WarehouseLead |
| POST | `/pvf/kits/{id}/unstage` | Unstage a kit back to assembled, freeing the bin | WarehouseLead |
| POST | `/pvf/branches/{id}/delivery-slots` | Define a truck delivery window with cube capacity | BranchManager |
| GET | `/pvf/delivery-slots/{id}` | Get one delivery slot | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/delivery-slots/{id}/cancel` | Cancel an open slot with no active bookings | BranchManager |
| GET | `/pvf/delivery-slots/{id}/orders` | List orders booked into a slot | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/manufacturer-programs` | Create a manufacturer stocking program | BranchManager |
| GET | `/pvf/manufacturer-programs` | List programs with filters (paginated) | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/manufacturer-programs/{id}` | Get one program | BranchManager, CounterRep, InsideSales, WarehouseLead |
| POST | `/pvf/manufacturer-programs/{id}/close` | Close an ended program; computes attained tier and earned rebate | BranchManager |
| POST | `/pvf/manufacturer-programs/{id}/settle` | Settle a closed program | BranchManager |
| POST | `/pvf/returns` | Create a return request against an order | CounterRep |
| GET | `/pvf/returns/{id}` | Get one return request | BranchManager, CounterRep, InsideSales, WarehouseLead |
| GET | `/pvf/orders/{id}/returns` | List returns against an order | BranchManager, CounterRep, InsideSales, WarehouseLead, Contractor |
| POST | `/pvf/returns/{id}/submit` | Submit a return; runs window, returnable, and quantity validations | CounterRep |
| POST | `/pvf/returns/{id}/decision` | Manager approves or rejects; segregation of duties enforced | BranchManager |
| POST | `/pvf/returns/{id}/receive` | Receive and restock an approved return; posts account credit | WarehouseLead |
| POST | `/pvf/_clock/set_current_utc` | Set the logical clock | BranchManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BRANCH_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_KIT_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_SHEET_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_CREDIT_HOLD` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_LINE_VERSION` | 412 |
| `ERR_DELIVERY_WINDOW_PAST` | 422 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_PROGRAM_PERIOD_NOT_ENDED` | 422 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_BIN_OVERLAP` | 409 |
| `ERR_PROGRAM_OVERLAP` | 409 |
| `ERR_SLOT_FULL` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_SUBSTITUTE_GROUP_MISMATCH` | 422 |
| `ERR_NON_RETURNABLE_ITEM` | 422 |
| `ERR_RETURN_QTY_EXCEEDS_FULFILLED` | 422 |
| `ERR_EMPTY_RETURN` | 422 |
| `ERR_LINE_ORDER_MISMATCH` | 422 |
| `ERR_KIT_LINE_CONFLICT` | 409 |
| `ERR_SKU_EXISTS` | 409 |
| `ERR_BRANCH_CODE_EXISTS` | 409 |
| `ERR_STOCK_RECORD_EXISTS` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_PRICE_FLOOR_VIOLATION` | 422 |
| `ERR_OVERRIDE_REQUIRES_MANAGER` | 403 |
