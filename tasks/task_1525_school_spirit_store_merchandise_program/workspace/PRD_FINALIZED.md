# School Spirit Store API — Product Requirements Document

## 1. Introduction

Every school year, the activities office replays the same scramble: a folding table of T-shirts at the homecoming game, a shoebox of cash that nobody counted the same way twice, a preorder Google Form that over-promised sizes the vendor never printed, and a spring argument about which club actually earned the profits. The spirit store is a real retail operation run by volunteers — artwork must clear the district's trademark review before a single shirt is printed, stock is finite and shared between an online storefront and cash-and-card tables at events, preorder campaigns gamble on demand against vendor minimum runs, and every dollar of margin is earmarked for student activity accounts.

This document specifies the School Spirit Store API, the system of record for that operation. All endpoints are mounted under `/spirit-store`. The API governs the full merchandising lifecycle for a school-year program: catalog and vendor management, licensing approval, seasonal drops, preorder campaigns with deposits, purchase orders and receiving, point-of-sale events with strict cash-drawer controls, online orders with school pickup, size exchanges, and the weighted allocation of profit to activity accounts. Six roles share the work — director, store manager, licensing coordinator, treasurer, student cashier, and customer — and the system enforces segregation of duties where money and approval meet. Because the program is calendar-driven (drops open and close, pickup windows expire, campaigns lock), all time-based behavior reads from a server-maintained logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their capacity. A request missing either header, or presenting a role value the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The recognized role values are exactly: `ActivitiesDirector`, `StoreManager`, `LicensingCoordinator`, `Treasurer`, `StudentCashier`, and `Customer`. When the role is recognized but not permitted for the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For every role — `ActivitiesDirector`, `StoreManager`, `LicensingCoordinator`, `Treasurer`, `StudentCashier`, and `Customer` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for it (for example, as `opened_by_user_id` and `counted_by_user_id` on an event's drawer, or as `customer_user_id` on an order or preorder), but it never compares `X-User-ID` to any entity's `id`. There is one ownership exception, and it belongs to the `Customer` role: paying a preorder, cancelling a preorder, and opening an exchange are own-resource actions, and for those the request's `X-User-ID` must equal the resource's `customer_user_id` — for an exchange, the `customer_user_id` of the order being exchanged. A mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`.

The division of labor is deliberate. An `ActivitiesDirector` owns program lifecycle, manual profit adjustments, allocation governance, drawer-discrepancy overrides, ops runs, and the logical clock. A `StoreManager` runs the catalog — vendors, designs as their creator, variants, drops, purchase orders, campaigns, event scheduling, and fulfillment — but a manager who created a design cannot approve its licensing; that power belongs exclusively to the `LicensingCoordinator`, the district's trademark officer. A `Treasurer` counts drawers (and may never count a drawer they did not open — indeed may never count one they *did* open), issues refunds, decides exchanges, and runs allocations. A `StudentCashier` opens event drawers and rings up event sales. A `Customer` browses campaigns and places preorders and online orders.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Every list response sorts by `created_at` in ascending order, and every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

List endpoints also accept optional foreign-key filters that restrict results to matching records — `program_id`, `design_id`, `drop_id`, `variant_id`, `vendor_id`, `campaign_id`, `selected_vendor_id`, `event_id`, `customer_user_id`, `order_id`, `original_variant_id`, and `new_variant_id` — with the filters supported by each list endpoint following the workflows described in §3 (for example, purchase orders filter by `variant_id`, `vendor_id`, and `campaign_id`, while exchanges filter by `order_id`, `original_variant_id`, and `new_variant_id`).

### 2.4. Common Resource Properties

All thirteen primary resources — the merchandising program, vendor, design, product variant, seasonal drop, purchase order, preorder campaign, preorder, event sale, order, exchange request, activity account, and allocation run — share one system-managed field set:

- `id` (string): a unique server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource.

"Mutation" is read broadly: any change to a resource's fields — including computed-counter updates, cascade writes from a parent or child transition, and lifecycle transitions — refreshes `updated_at` and bumps `version`. Three operations name this explicitly: a program lifecycle transition increments the program's `version` by 1, posting a profit adjustment increments it by 1, and creating a seasonal drop increments the owning program's `version` by 1 (see §2.7 for why that last one matters).

### 2.5. The Logical Clock

All temporal reasoning in the system — drop windows, campaign windows, pickup expiries, exchange windows, event windows — reads a server-maintained **logical clock**, never the host's wall clock. An admin-only, test-driving capability lets an `ActivitiesDirector` set the logical clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`. Before any such set call, the logical clock reads exactly `2026-08-01T00:00:00Z` and MUST NOT fall back to wall-clock time.

### 2.6. Money, Precision, and Rounding

All monetary values are integers denominated in cents; there are no fractional-cent amounts anywhere in the system. Where a calculation produces a fractional cent, the rule is **round half up** — a half cent or more rounds up — applied exactly where each workflow in §3 says it applies, and never later. Two rounding disciplines matter most: order lines are rounded per line and only then summed (§3.6), and allocation shares are instead rounded *down* — floored — with the leftover dust assigned deterministically (§3.8). Percentage inputs such as `royalty_pct`, `deposit_pct`, and `discount_pct` are fractions between 0 and 1 inclusive, not whole percents.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a stale writer with the same error: `ERR_STALE_VERSION`, HTTP 412.

Creating a seasonal drop requires the request to carry `expected_program_version`, holding the client last-observed `version` of the owning merchandising program. Because a prior drop creation — or any other program mutation — legitimately advanced the program's merchandising epoch, a mismatch between `expected_program_version` and the program's current `version` means the writer's view of program configuration is out of date, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Every licensing transition on a design likewise requires `expected_design_version`, holding the client's last-observed `version` of the design. If a resubmission or decision was already recorded since that read, the design's version has advanced, and the transition is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting a revision state the client never saw.

No other endpoint accepts a version field; clients must not send expected versions anywhere else.

### 2.8. Request Validation Pipeline

Every request is evaluated against a fixed pipeline of checks, **in the following order**, and a failure at any step short-circuits every later step. The ordering is normative: when a request would fail two checks, the earlier check's error is the one returned.

1. **Authentication context.** `X-User-ID` and `X-User-Role` are present and the role is recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization.** The role is permitted for the endpoint, including the customer-ownership rule of §2.1, else `ERR_UNAUTHORIZED_ROLE`.
3. **Path existence.** Path identifiers are validated left to right — the program first, then the resource within it — and the first missing identifier yields its own 404: `ERR_PROGRAM_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_PO_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_EXCHANGE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, or `ERR_ALLOCATION_RUN_NOT_FOUND`. A request naming a rotation under a nonexistent program, for example, fails with `ERR_PROGRAM_NOT_FOUND` before the child identifier is ever examined. The path identifiers themselves are `programId`, `vendorId`, `designId`, `variantId`, `dropId`, `poId`, `campaignId`, `preorderId`, `eventId`, `orderId`, `exchangeId`, `accountId`, and `runId`.
4. **Body references.** Foreign keys carried in the request body — `design_id`, `variant_id`, `vendor_id`, `campaign_id`, `event_id`, `order_id`, `original_variant_id`, `new_variant_id` — must exist and must belong to the same program as the request's scope; failures draw from the same not-found family as step 3.
5. **Request shape.** Required fields are present, enum values are valid, and ranges hold: `qty` at least 1, percentage fields between 0 and 1 inclusive, `closes_at` strictly after `opens_at`, `ends_at` strictly after `starts_at`, `amount_cents` at least 1. Violations are `ERR_INVALID_REQUEST`.
6. **Program gate.** Catalog, campaign, event, order, preorder, and exchange writes require the program's `status` to be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; posting an allocation run requires it to be `CLOSED`, else `ERR_PROGRAM_NOT_CLOSED`.
7. **State preconditions.** The target resource must sit in a valid from-state for the requested transition. State-specific errors fire here — `ERR_CAMPAIGN_NOT_OPEN`, `ERR_DROP_NOT_OPEN`, `ERR_DRAWER_NOT_OPEN`, `ERR_PREORDER_NOT_PAYABLE`, `ERR_PREORDER_NOT_CANCELLABLE`, `ERR_PICKUP_NOT_READY`, `ERR_PICKUP_EXPIRED`, `ERR_EVENT_WINDOW_PASSED`, `ERR_VENDOR_NOT_APPROVED` — and anything else is the generic `ERR_INVALID_STATE_TRANSITION`.
8. **Licensing gate.** Selling, preordering, submitting a purchase order, or opening a campaign all require the underlying design to be `APPROVED`: a `REVOKED` design yields `ERR_LICENSE_REVOKED`, and any other non-approved status yields `ERR_DESIGN_NOT_LICENSED`.
9. **Temporal windows.** Window checks fire here: the drop sales window (`ERR_DROP_NOT_OPEN`), drop-window overlap on creation (`ERR_DROP_WINDOW_OVERLAP`), register booking conflicts (`ERR_EVENT_REGISTER_CONFLICT`), campaign open and lock windows (`ERR_CAMPAIGN_NOT_OPEN`, `ERR_CAMPAIGN_WINDOW_STILL_OPEN`), and the exchange window (`ERR_EXCHANGE_WINDOW_CLOSED`).
10. **Constraint satisfaction.** Business constraints are enforced: stock sufficiency (`ERR_INSUFFICIENT_STOCK`), vendor minimum order quantity (`ERR_MIN_ORDER_QTY`), one active campaign per design (`ERR_DUPLICATE_ACTIVE_CAMPAIGN`), variant uniqueness (`ERR_DUPLICATE_VARIANT`), preorder variant matching the campaign's design (`ERR_VARIANT_DESIGN_MISMATCH`), exchange same-design different-size (`ERR_EXCHANGE_VARIANT_MISMATCH`), drawer segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), and unresolved sub-resources at program close (`ERR_UNRESOLVED_OPERATIONS`).
11. **Fiscal exactness.** Payment amounts must match what is due — `ERR_DEPOSIT_SHORTFALL` when short, `ERR_PAYMENT_AMOUNT_MISMATCH` when over or mismatched — refunds must stay within what was paid (`ERR_REFUND_EXCEEDS_PAID`), allocations must stay within undistributed profit (`ERR_ALLOCATION_EXCEEDS_PROFIT`), and reconciliation requires profit fully allocated (`ERR_PROFIT_NOT_FULLY_ALLOCATED`).
12. **Selector existence.** The goal-met branch of a campaign lock requires at least one eligible vendor quote, else `ERR_NO_ELIGIBLE_VENDOR`.
13. **Optimistic concurrency.** Where §2.7 applies, the expected version must match the parent entity's current `version`, else `ERR_STALE_VERSION`.

### 2.9. Inventory Counters and Sellability

Every product variant carries three stock counters. `on_hand_qty` is the physical units on the shelf: it starts at 0, grows with purchase-order receipts, shrinks with point-of-sale sales, preorder fulfillments, and exchange swaps, and grows back when an online reservation expires. `reserved_online_qty`, also starting at 0, holds units committed to unfulfilled online orders and approved exchanges. `available_qty` is the derived difference — on-hand minus reserved — and is never allowed to go negative. A variant's `reorder_point` (default 0) is the low-water mark: `low_stock` is true exactly when `available_qty` is at or below it.

Sellability is derived, not stored by hand: a variant is `sellable` when its program is `ACTIVE`, its design is `APPROVED`, and it either belongs to no seasonal drop or its drop is currently `OPEN`. A variant's `landed_unit_cost_cents` — the full per-unit cost including amortized licensing — is 0 until the first receipt against a purchase order for that variant (§3.5).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Season: The Merchandising Program

An `ActivitiesDirector` opens the year by creating the **MerchProgram**, supplying a display `name` and the academic-year label `school_year`, choosing the default inventory `valuation_method` (`FIFO` or `WEIGHTED_AVG`, §3.5), and optionally overriding five policy knobs: `over_short_tolerance_cents` (default 500 — five dollars of drawer slack), `exchange_window_days` (default 14), `pickup_window_days` (default 7), `register_buffer_minutes` (default 30), and `deposit_floor_cents` (default 500). A new program starts in `SETUP` with `undistributed_profit_cents` and `distributed_profit_cents` both at 0 and `ops_run_index` at 0.

The program lifecycle has three director-driven steps, each requested with a target `to_state`. Activation moves `SETUP` to `ACTIVE` — attempting it from any other state is `ERR_INVALID_STATE_TRANSITION`. Closing moves `ACTIVE` to `CLOSED` and is only permitted when every event sale of the program has reached `RECONCILED` or `CANCELLED` and every preorder campaign has reached `CLOSED` or `CANCELLED`; leftover operations block the close with `ERR_UNRESOLVED_OPERATIONS`. The final move, `CLOSED` to `RECONCILED`, requires `undistributed_profit_cents` to be exactly 0 — otherwise `ERR_PROFIT_NOT_FULLY_ALLOCATED` — and no allocation run of the program still in `DRAFT`, which would again surface `ERR_UNRESOLVED_OPERATIONS`. `RECONCILED` is terminal.

While the program runs, the director can post a manual **profit adjustment** — a donation, a fundraiser sweep — by supplying an `amount_cents` and a `reason`; the amount is added to `undistributed_profit_cents`. The director also fires the **ops run**, the system's epoch checkpoint: each run adds 1 to `ops_run_index`, auto-closes every `OPEN` seasonal drop whose `closes_at` the logical clock has reached or passed, and expires every online order still `READY_FOR_PICKUP` whose `expires_at` the clock has passed (§3.6). Program-scoped writes of the catalog, campaign, event, order, preorder, and exchange families are accepted only while the program is `ACTIVE`, per the gate in §2.8.

### 3.2. Vendors, Quotes, and the Licensing Pipeline

A `StoreManager` registers each **Vendor** under its program with a `name` and `contact_email`, optionally seeding its `quotes` at the same time. A vendor begins `PENDING`; the manager promotes it to `APPROVED` (from any other starting state the transition is `ERR_INVALID_STATE_TRANSITION`), and may later move it `APPROVED` to `SUSPENDED` and back to `APPROVED` again. Suspension has teeth: while a vendor is `SUSPENDED`, its quotes are ineligible for the campaign lock selector of §3.4.

Each quote in the `quotes` array names a `design_id`, a `unit_cost_cents`, a `min_order_qty`, a `production_days`, and its own status of `ACTIVE` or `RETIRED`. A vendor may hold at most one `ACTIVE` quote per design. The manager maintains both the vendor's `status` and its quote list through vendor updates, which replace the `quotes` array wholesale; either change bumps the vendor's `version`.

Designs travel a separate, deliberately segregated track. The `StoreManager` creates a **Design** — a `name`, an `artwork_ref` pointing at the artwork, a `royalty_pct` (the licensor's cut as a fraction of the sales price, between 0 and 1 inclusive), and a one-time `licensing_fee_cents` that will later be amortized into landed cost at receiving time (§3.5). New designs start in `DRAFT` with `revision_count` at 0. Only a `LicensingCoordinator` may drive the licensing workflow — the manager who created the design cannot approve their own submission.

Submitting a `DRAFT` design moves it to `SUBMITTED` (else `ERR_INVALID_STATE_TRANSITION`). From `SUBMITTED`, the coordinator either approves it — the design becomes `APPROVED` and its variants can sell — or rejects it, supplying a `note` that is captured into `rejection_reason` while the design sits in `REJECTED`. Rejection is not the end: resubmitting a `REJECTED` design returns it to `SUBMITTED`, increments `revision_count` by 1, and clears `rejection_reason` back to null, and this revision loop may repeat as many times as needed. Resubmission is the moment two coordinators can collide, so every licensing transition — submission, approval, rejection, resubmission, revocation — carries the OCC guard of §2.7: the request must present `expected_design_version`, and a stale value is refused with `ERR_STALE_VERSION`.

Approval can also be withdrawn. Revoking an `APPROVED` design (a `note` accompanies the decision) moves it to the terminal `REVOKED` state and fires a three-link cascade, atomically within the same request. First, every variant of the design recomputes `sellable` to false. Second, every preorder campaign of the design still in `OPEN` or `IN_PRODUCTION` auto-transitions to `CANCELLED`, because its merchandise is no longer sellable. Third, within each cancelled campaign, every preorder in `PAID` moves to `REFUNDED` with `refunded_cents` set to the sum of its `deposit_paid_cents` and `balance_paid_cents`, while every preorder still in `PLACED` moves to `CANCELLED`. Each such refund reverses whatever margin had been recognized — and since preorder margin is recognized only at fulfillment (§3.4), these pre-fulfillment refunds move no program profit.

### 3.3. The Catalog: Variants and Seasonal Drops

With a licensed design in hand, the `StoreManager` builds the sellable catalog one **ProductVariant** at a time: a `design_id`, a `size` (one of `XS`, `S`, `M`, `L`, `XL`, `2XL`, `ONE_SIZE`), a list `unit_price_cents`, an optional `drop_id` pinning the SKU to a seasonal drop, and an optional `reorder_point`. The pair of design and size is unique within a program — a second variant with the same `design_id` and `size` is rejected with `ERR_DUPLICATE_VARIANT`. Stock counters start at zero, per §2.9.

**SeasonalDrops** are the program's limited-time windows. Creating one requires the drop's `name` and its sales window `opens_at` to `closes_at`; the window is half-open — the drop sells from the `opens_at` instant up to but not including `closes_at`. Windows of the same program may touch but never overlap: adjacency, where one drop closes at exactly the instant another opens, is allowed, while any true overlap is rejected with `ERR_DROP_WINDOW_OVERLAP`. Creation is OCC-guarded on the program, per §2.7 — the request carries `expected_program_version` — and, on success, the program's `version` advances by 1. A new drop is `SCHEDULED`.

Opening a drop moves `SCHEDULED` to `OPEN` and requires the logical clock to have reached `opens_at`; an early attempt is `ERR_DROP_WINDOW_NOT_STARTED`. On opening, `sellable` is recomputed for every variant carrying this `drop_id`. Closing — `OPEN` to `CLOSED` — happens either at the manager's hand or automatically during an ops run once the clock has reached `closes_at`; either way, `sellable` recomputes to false for the drop's variants. The last step, `CLOSED` to `SETTLED`, freezes a `settled_margin_cents` snapshot on the drop: the sum of `margin_cents` over all orders whose `payment_status` is `PAID` or `PARTIALLY_REFUNDED` and that contain at least one line whose variant belongs to this drop, with refunded portions already netted out of margin recognition (§3.7). Until settlement, `settled_margin_cents` is null.

### 3.4. Preorder Campaigns: Demand, Deposits, and the Production Lock

A **PreOrderCampaign** lets the store test demand before committing to a print run. The `StoreManager` creates one against an `APPROVED` design, setting a single `unit_price_cents` that applies to all sizes, a `deposit_pct` (the fraction due at placement, between 0 and 1 inclusive), a `goal_units` production threshold, and the window `opens_at` to `closes_at`. The campaign starts in `DRAFT`.

Opening a campaign requires three things: the logical clock has reached `opens_at` (an early open is `ERR_CAMPAIGN_NOT_OPEN`), the design is `APPROVED` (else `ERR_DESIGN_NOT_LICENSED`), and no other campaign of the same design is currently `OPEN`, `IN_PRODUCTION`, or `FULFILLING` (a clash is `ERR_DUPLICATE_ACTIVE_CAMPAIGN`). Once `OPEN`, a `Customer` places a **PreOrder** by naming the `program_id`, `campaign_id`, the desired `variant_id`, their `customer_user_id`, and a `qty` of at least 1. The variant's design must be the campaign's design — a mismatch is `ERR_VARIANT_DESIGN_MISMATCH` — and the campaign must still be `OPEN`, else `ERR_CAMPAIGN_NOT_OPEN`.

At placement the server computes the money split. The raw deposit is the campaign's `unit_price_cents` times `qty` times `deposit_pct`, rounded half-up to whole cents; `deposit_due_cents` is the larger of the program's `deposit_floor_cents` and that raw figure. `balance_due_cents` is the remainder: `unit_price_cents` times `qty` minus `deposit_due_cents`. The preorder starts in `PLACED` with `deposit_paid_cents`, `balance_paid_cents`, and `refunded_cents` all at 0.

Two counters track the campaign's traction, and they deliberately disagree. `placed_units` is the provisional, forward-looking figure: the sum of `qty` over preorders in `PLACED`, `PAID`, or `FULFILLED`. `paid_units` is the final, lock-authoritative figure: the sum over preorders in `PAID` or `FULFILLED` only. `CANCELLED` and `REFUNDED` preorders are excluded from both. Whenever unpaid preorders exist, `placed_units` overstates what the lock will see — a campaign can display `placed_units` at or beyond its goal and still cancel at lock, because the lock consults `paid_units` alone.

Payment comes in two phases through the same act, distinguished by a `phase` field. While the preorder is `PLACED`, a `DEPOSIT` payment of exactly `deposit_due_cents` moves it to `PAID`; less is `ERR_DEPOSIT_SHORTFALL`, more is `ERR_PAYMENT_AMOUNT_MISMATCH`, the campaign must be `OPEN` (else `ERR_CAMPAIGN_NOT_OPEN`), and a preorder in any other state is not payable (`ERR_PREORDER_NOT_PAYABLE`). The paid amount is recorded into `deposit_paid_cents` and the campaign projections are recomputed. While the preorder is `PAID` and the campaign has reached `IN_PRODUCTION` or `FULFILLING`, a `BALANCE` payment of exactly `balance_due_cents` — again, short is `ERR_DEPOSIT_SHORTFALL`, over is `ERR_PAYMENT_AMOUNT_MISMATCH`, wrong state or phase is `ERR_PREORDER_NOT_PAYABLE` — is recorded into `balance_paid_cents`.

When the selling window closes, the `StoreManager` locks the campaign. Locking requires the campaign still `OPEN` (else `ERR_CAMPAIGN_NOT_OPEN`) and the logical clock at or past `closes_at` (else `ERR_CAMPAIGN_WINDOW_STILL_OPEN`), and then the campaign forks. If `paid_units` is at least `goal_units` — exact equality passes — the campaign advances to `IN_PRODUCTION` and the vendor quote selector runs: eligible vendors are `APPROVED` vendors holding a quote on the campaign's design whose quote status is `ACTIVE`; eligible quotes rank by `unit_cost_cents` ascending, ties break by `production_days` ascending, remaining ties by the vendor's `created_at` ascending; the winner lands in `selected_vendor_id`. If no vendor is eligible, the lock is refused with `ERR_NO_ELIGIBLE_VENDOR` and the campaign stays `OPEN`. For every variant of the design whose paid demand is greater than zero, the lock auto-creates a purchase order: `campaign_id` set, `vendor_id` set to the selected vendor, `qty_ordered` equal to the larger of the variant's paid demand and the winning quote's `min_order_qty`, `unit_cost_cents` captured from that quote, status `SUBMITTED`, and `auto_created` true.

If `paid_units` falls short of `goal_units`, the lock instead drops the campaign to `CANCELLED`. The same `CANCELLED` state is reachable two other ways: the manager abandoning a `DRAFT` or `OPEN` campaign outright, or the design-revocation cascade of §3.2 striking a campaign in `OPEN` or `IN_PRODUCTION`. For an `OPEN` campaign the cancel fires the refund cascade — every `PAID` preorder becomes `REFUNDED` with `refunded_cents` equal to `deposit_paid_cents` plus `balance_paid_cents`, and every `PLACED` preorder becomes `CANCELLED`; a `DRAFT` campaign has no preorders, so its cancellation moves no money.

Customers retain an escape hatch while the campaign is still `OPEN`: cancelling one's own `PLACED` preorder moves it to `CANCELLED` with nothing refunded, and cancelling a `PAID` one moves it to `REFUNDED` with `refunded_cents` equal to what was collected (`deposit_paid_cents` plus `balance_paid_cents` — only the deposit can have been paid at that stage). Once the campaign has locked — it is no longer `OPEN` — or the preorder is already terminal, the cancel is rejected with `ERR_PREORDER_NOT_CANCELLABLE`.

Fulfillment closes the loop. Once every purchase order of an `IN_PRODUCTION` campaign has been fully received (§3.5), the campaign auto-advances to `FULFILLING`. A `StoreManager` then fulfills each `PAID` preorder (any other preorder state is `ERR_INVALID_STATE_TRANSITION`; a campaign not yet `FULFILLING` yields `ERR_CAMPAIGN_NOT_OPEN`): the balance must be fully collected — `balance_paid_cents` equal to `balance_due_cents`, else `ERR_DEPOSIT_SHORTFALL` — and the variant's `available_qty` must cover the preorder's `qty`, else `ERR_INSUFFICIENT_STOCK`. Fulfillment decrements the variant's `on_hand_qty` by `qty`, moves the preorder to `FULFILLED`, and recognizes the program's profit: `undistributed_profit_cents` grows by the line revenue (`unit_price_cents` times `qty`) minus the cost of goods (`qty` times the variant's `landed_unit_cost_cents`), minus the licensor's royalty — `royalty_pct` times `unit_price_cents` times `qty`, rounded half-up to whole cents. When the last `PAID` preorder of a campaign is fulfilled, the campaign bubble-closes itself from `FULFILLING` to `CLOSED`.

### 3.5. Purchase Orders, Receiving, and Inventory Valuation

Stock reaches the shelf through **PurchaseOrders**. A `StoreManager` raises a stock purchase order by naming the `program_id`, the `variant_id` being produced, the `vendor_id` producing it, and a `qty_ordered`; the server captures `unit_cost_cents` from that vendor's `ACTIVE` quote on the variant's design — if no such quote exists, creation fails with `ERR_NO_ELIGIBLE_VENDOR`. Manager-created POs start in `DRAFT` with `qty_received` at 0, `auto_created` false, and no `campaign_id`. (Campaign-locked POs, §3.4, arrive already `SUBMITTED` with `auto_created` true.)

Submitting a `DRAFT` purchase order enforces three gates: the vendor must be `APPROVED` (else `ERR_VENDOR_NOT_APPROVED`), the variant's design must be `APPROVED` (else `ERR_DESIGN_NOT_LICENSED`), and `qty_ordered` must be at least the `min_order_qty` of the vendor's `ACTIVE` quote on that design (else `ERR_MIN_ORDER_QTY`). A successful submit moves the order to `SUBMITTED`; from any other state the submit is `ERR_INVALID_STATE_TRANSITION`.

Receiving is a loop. Each receipt records a `qty` of at least 1, and the cumulative `qty_received` may never exceed `qty_ordered` — an over-shipment is `ERR_INVALID_REQUEST`. Every receipt adds `qty` to `qty_received` and to the variant's `on_hand_qty`, and recomputes the variant's landed cost: `landed_unit_cost_cents` becomes the purchase order's `unit_cost_cents` plus the design's `licensing_fee_cents` divided by the order's `qty_ordered`, with that division rounded half-up to whole cents — the one-time licensing fee amortized across the run. The latest receipt always wins: the field is overwritten on each receipt. While the cumulative received quantity stays below `qty_ordered`, the order sits in `PARTIALLY_RECEIVED` and further receipts continue the loop; a receipt bringing the total exactly equal to `qty_ordered` completes the order as `RECEIVED`. Completion fires one more effect: when the finished order carries a `campaign_id` and every purchase order of that campaign has reached `RECEIVED`, the campaign auto-advances from `IN_PRODUCTION` to `FULFILLING`. Cancellation is available only from `DRAFT` or `SUBMITTED` — a partially received order can no longer be cancelled.

For reporting, the program exposes a computed **inventory valuation**. Under `FIFO`, each receipt forms a cost layer stamped with its receipt time and its landed unit cost; layers are consumed oldest-first — receipt time ascending, ties broken by the purchase order's `created_at` ascending — against units sold, fulfilled, or swapped out in chronological order, and the valuation is the sum over the units remaining in each layer of quantity times that layer's landed cost. Under `WEIGHTED_AVG`, each variant's average is its total received cost divided by its total received quantity, rounded half-up to whole cents, and the valuation is the sum over variants of `on_hand_qty` times that average. Identical receipt histories produce different numbers under the two methods whenever receipt costs differ across layers. The valuation read defaults to the program's `valuation_method`, accepts an optional `method` override, and reports the `method` used, the `total_value_cents`, and a `per_variant` breakdown.

### 3.6. Selling at Events and Online

The store sells through two channels, both producing **Orders**, and the `channel` field — `EVENT_POS` or `ONLINE` — decides the rules. An event order requires `event_id`; an online order must leave `event_id` null.

Events begin on the calendar. A `StoreManager` schedules an **EventSale** with a `name`, a `register_location`, and the window `starts_at` to `ends_at` — a closed interval, inclusive at both ends, with `ends_at` strictly after `starts_at`. Register discipline applies at booking: two events on the same `register_location` must keep a gap of at least the program's `register_buffer_minutes` between their windows — a gap exactly equal to the buffer passes, and only a gap strictly smaller than the buffer is rejected — and the buffer rule treats the windows as the closed intervals they are, inclusive endpoints and all; a booking that lands within the buffer of an existing non-`CANCELLED` event on the same register is rejected with `ERR_EVENT_REGISTER_CONFLICT`. A scheduled event sits in `SCHEDULED`, and a manager may cancel it only from there — an opened event must be counted, not cancelled, and cancelling from any other state is `ERR_INVALID_STATE_TRANSITION`.

At the venue, a `StudentCashier` opens the drawer with a starting `opening_float_cents`. The event must still be `SCHEDULED`, and the logical clock must not have passed `ends_at` — a late open is `ERR_EVENT_WINDOW_PASSED`. Opening records `opened_by_user_id` from the request's `X-User-ID`, moves the event to `OPEN`, and starts the drawer's running totals at zero.

With the drawer open, the cashier rings up sales. An `EVENT_POS` order names the `event_id`, the `customer_user_id`, a `payment_method` of `CASH` or `CARD`, and the purchased `lines` — each line a `variant_id`, a `qty` of at least 1, and an optional `discount_pct` (defaulting to 0). The event must be `OPEN`, else `ERR_DRAWER_NOT_OPEN`. Stock leaves the shelf immediately — each line decrements its variant's `on_hand_qty` — and the drawer's running totals absorb the sale: the order total lands on `cash_sales_cents` for a `CASH` payment or on `card_sales_cents` for a `CARD` one. The order is born with `payment_status` `PAID` and `fulfillment_status` `POS_FULFILLED`, goods in hand.

An `ONLINE` order instead reserves rather than ships: each line adds its `qty` to the variant's `reserved_online_qty` and nothing leaves the shelf yet. A line whose variant is pinned to a seasonal drop can be sold only while that drop is `OPEN`; otherwise the sale fails with `ERR_DROP_NOT_OPEN`. The online order is born `PAID` with `fulfillment_status` `PICKUP_PENDING`, awaiting fulfillment.

Whichever the channel, two rules are common. Every line requires the variant's `available_qty` to cover its `qty` — one insufficient line fails the entire order with `ERR_INSUFFICIENT_STOCK` — and every line's design must clear the licensing gate of §2.8: `REVOKED` yields `ERR_LICENSE_REVOKED`, any other unapproved status `ERR_DESIGN_NOT_LICENSED`. At creation the server prices the order: each line total is the variant's current `unit_price_cents` times the line's `qty` times one minus the line's `discount_pct`, rounded half-up to whole cents, and `total_cents` is the sum of those already-rounded line totals — the per-line rounding happens first and the summing second, in that pinned order. Three lines at 333 cents with a ten-percent line discount make the stakes concrete: per-line rounding yields 300 cents a line and a 900-cent order, while summing first and rounding once would yield 899. The order's `margin_cents` is the sum over its lines of the line total minus the line's `qty` times the variant's `landed_unit_cost_cents` as it stood at the moment of sale, and that margin is immediately added to the program's `undistributed_profit_cents`.

Online fulfillment is a small state machine of its own. Marking an order ready moves `PICKUP_PENDING` to `READY_FOR_PICKUP` (from any other state, `ERR_PICKUP_NOT_READY`), stamps `ready_at` from the logical clock, and sets `expires_at` to `ready_at` plus the program's `pickup_window_days`. Pickup moves `READY_FOR_PICKUP` to `PICKED_UP` and is allowed only while the clock is at or before `expires_at` — afterward, `ERR_PICKUP_EXPIRED`; at pickup, each line decrements both `on_hand_qty` and `reserved_online_qty`, and `picked_up_at` is stamped. When pickup never happens, an ops run (§3.1) whose clock has passed `expires_at` releases the order to `EXPIRED_RELEASED`: the reservation is released back to sellable stock, the order is refunded in full — `payment_status` becomes `REFUNDED` and `refunded_cents` becomes the full `total_cents` — and the program's `undistributed_profit_cents` surrenders the order's entire `margin_cents`.

### 3.7. Counting the Drawer, Refunding Orders, and Exchanging Sizes

Cash control is a two-person job. When the event winds down, a `Treasurer` counts the drawer and reports the physical `closing_counted_cents`. Segregation of duties is hard-coded: the counter may not be the opener, so if the request's `X-User-ID` equals the recorded `opened_by_user_id`, the count is refused with `ERR_SEGREGATION_OF_DUTIES`. A valid count — accepted from `OPEN` or from `FLAGGED` — records `closing_counted_cents` and `counted_by_user_id`, moves the event through `COUNTED`, and computes `over_short_cents`: the counted cash minus the expected drawer, where the expected drawer is `opening_float_cents` plus `cash_sales_cents` minus `cash_refunds_cents`. If the absolute value of `over_short_cents` is at or below the program's `over_short_tolerance_cents` — a discrepancy exactly equal to the tolerance passes — the event continues straight from `COUNTED` to `RECONCILED`. Outside the tolerance the event instead lands in `FLAGGED`, and the recount loop begins: a flagged event can be counted again, each recount overwriting `closing_counted_cents` and recomputing the discrepancy, until some count lands within tolerance. Alternatively, an `ActivitiesDirector` reconciles a `FLAGGED` event manually by supplying a `note`, which is preserved in `reconcile_note`; manual reconcile from any state other than `FLAGGED` is `ERR_INVALID_STATE_TRANSITION`.

Refunds belong to the `Treasurer` and run on a payment dimension that is parallel to fulfillment: `payment_status` walks `PAID` to `PARTIALLY_REFUNDED` to `REFUNDED` independently of where the goods stand. A refund carries an `amount_cents` of at least 1. While cumulative `refunded_cents` plus the new amount stays below `total_cents`, the refund is partial and the order sits in (or moves to) `PARTIALLY_REFUNDED`; an amount bringing the cumulative total exactly to `total_cents` completes the refund as `REFUNDED`; anything beyond that is `ERR_REFUND_EXCEEDS_PAID`. Every refund claws back profit proportionally: the program's `undistributed_profit_cents` decreases by `margin_cents` times `amount_cents` divided by `total_cents`, rounded half-up to whole cents. Channel rules apply on top: an event order can be refunded only while its event is still `OPEN` — else `ERR_DRAWER_NOT_OPEN` — and a `CASH` refund adds `amount_cents` to the event's `cash_refunds_cents`; an online order can be refunded only while it is `PICKUP_PENDING` or `READY_FOR_PICKUP` (otherwise `ERR_INVALID_STATE_TRANSITION`), and each online refund releases the reservation proportionally for the refunded whole units. A fully refunded online order that has not been picked up also moves its fulfillment to `EXPIRED_RELEASED`, releasing the entire remaining reservation.

Size exchanges get their own workflow. Within `exchange_window_days` of the order's fulfillment — the final day still counts; an exchange opened later is `ERR_EXCHANGE_WINDOW_CLOSED` — a `Customer` (on their own order only) or a `Treasurer` opens an **ExchangeRequest** naming the `order_id`, the `original_variant_id` being returned, and the `new_variant_id` wanted. The original variant must appear among the order's lines, and the new variant must share the original's design while differing in size; violations are `ERR_EXCHANGE_VARIANT_MISMATCH`. At creation the server computes `differential_cents`: the new variant's `unit_price_cents` minus the unit price captured on the original order line. A positive differential means the customer owes the difference, a negative one means a refund is owed, and zero is an even swap. The request starts `PENDING`.

A `Treasurer` then decides, submitting a `decision` of approve or reject. Approval requires the new variant to have at least one unit of `available_qty` — otherwise `ERR_INSUFFICIENT_STOCK` — and holds that unit by adding 1 to the new variant's `reserved_online_qty`, moving the request from `PENDING` to `APPROVED`. Rejection takes a `note` and ends the request at `REJECTED`; either decision from a non-`PENDING` state is `ERR_INVALID_STATE_TRANSITION`. Completing an `APPROVED` exchange settles the swap and moves the request to `COMPLETED`: the returned unit's `condition` is recorded — `RESALEABLE` units go back on the shelf (the original variant's `on_hand_qty` rises by 1) while `DAMAGED` units are written off and not restocked — and the held new unit leaves the shelf as the new variant's `reserved_online_qty` and `on_hand_qty` each fall by 1. A positive differential must be collected exactly: `amount_collected_cents` equal to `differential_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`. A negative differential is refunded against the original order, whose `refunded_cents` grows by the absolute differential and whose `payment_status` may move to `PARTIALLY_REFUNDED`.

### 3.8. Allocating Profit and Closing the Books

Profits accrue to the program all season — order margins at sale, preorder margins at fulfillment, manual adjustments — and land in `undistributed_profit_cents`. Disbursing them is the domain of **ActivityAccounts** and **AllocationRuns**, both managed under the director's governance with the `Treasurer` at the keyboard.

An `ActivitiesDirector` creates one activity account per club — a `name` like Band or Drama, a strictly positive `allocation_weight` fixing its relative share, and an optional `cap_cents` ceiling on its cumulative allocation (null means uncapped). Each account's `balance_cents` starts at 0.

The `Treasurer` disburses by creating an allocation run with a `distributable_cents` amount, which must be at least 1 and no more than the program's current `undistributed_profit_cents` — anything else is `ERR_ALLOCATION_EXCEEDS_PROFIT`. Creation computes the distribution lines immediately and freezes them on the run, each line an `account_id`, its `credit_cents`, and a `capped` flag recording whether the account's cap limited its credit. The waterfall runs as follows. First, total weight is the sum of `allocation_weight` over all of the program's accounts. Second, each account's raw share is `distributable_cents` times its weight divided by the total weight, rounded down to whole cents. Third, a capped account's tentative credit is the smaller of its raw share and its remaining headroom — `cap_cents` minus its current `balance_cents` — while uncapped accounts have unlimited headroom. Fourth, the overflow left unabsorbed by capped accounts is redistributed among the still-eligible accounts (uncapped, or capped but below their ceiling) in proportion to their weights renormalized among the recipients, each share floored, iterating until nothing overflows or no eligible recipient remains; if every account is capped and the overflow has nowhere to go, the unplaceable remainder simply stays in the program's undistributed profit — the run is still created and the remainder is visible on it as the gap between `distributable_cents` and the sum of line credits. Fifth, the rounding dust left by all that flooring — `distributable_cents` minus the sum of credits — goes to the eligible account with the largest `allocation_weight`, ties broken by the account's `created_at` ascending. Credits are conserved: their sum equals `distributable_cents` minus any unplaceable remainder, and when no account is capped the sum equals `distributable_cents` exactly. The run is born in `DRAFT`.

Posting is deliberately separated from creation. Only a `DRAFT` run can post, and only while the program is `CLOSED` — else `ERR_PROGRAM_NOT_CLOSED`. Posting credits each account's `balance_cents` by its line's credit, moves the same total from `undistributed_profit_cents` to `distributed_profit_cents` on the program, stamps `posted_at`, and leaves the run `POSTED`. A posted run can still be undone: reversing a `POSTED` run debits each account back by its line credit, restores the total to `undistributed_profit_cents` out of `distributed_profit_cents`, and leaves the run `REVERSED` — a compensating action, not a deletion. Either transition attempted from the wrong state is `ERR_INVALID_STATE_TRANSITION`.

With the books disbursed, the season closes in the order §3.1 describes: events reconciled or cancelled, campaigns closed or cancelled, allocation runs out of `DRAFT`, and `undistributed_profit_cents` back to exactly zero — only then does `CLOSED` give way to `RECONCILED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, modify, or transition an existing resource return `200 OK`. The table below is a summary only — request bodies, response bodies, and side effects are specified by the narratives of §2 and §3, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/spirit-store/programs` | Create a MerchProgram (status SETUP) | ActivitiesDirector |
| GET | `/spirit-store/programs` | List programs | ActivitiesDirector, StoreManager, Treasurer, LicensingCoordinator, StudentCashier |
| GET | `/spirit-store/programs/{programId}` | Get one program | ActivitiesDirector, StoreManager, Treasurer, LicensingCoordinator, StudentCashier |
| POST | `/spirit-store/programs/{programId}/lifecycle` | Program lifecycle transition (ACTIVE, CLOSED, RECONCILED) | ActivitiesDirector |
| POST | `/spirit-store/programs/{programId}/profit-adjustments` | Post a manual profit adjustment to undistributed profit | ActivitiesDirector |
| GET | `/spirit-store/programs/{programId}/valuation` | Computed inventory valuation, optional method override | ActivitiesDirector, StoreManager, Treasurer |
| POST | `/spirit-store/programs/{programId}/run-ops` | Ops-run checkpoint: advance epoch, auto-close drops, expire pickups | ActivitiesDirector |
| POST | `/spirit-store/vendors` | Create a Vendor (status PENDING) with optional quotes | StoreManager |
| GET | `/spirit-store/vendors` | List vendors | ActivitiesDirector, StoreManager, Treasurer |
| GET | `/spirit-store/vendors/{vendorId}` | Get one vendor | ActivitiesDirector, StoreManager, Treasurer |
| PATCH | `/spirit-store/vendors/{vendorId}` | Update vendor status and/or replace quotes | StoreManager |
| POST | `/spirit-store/designs` | Create a Design (status DRAFT) | StoreManager |
| GET | `/spirit-store/designs` | List designs | ActivitiesDirector, StoreManager, Treasurer, LicensingCoordinator |
| GET | `/spirit-store/designs/{designId}` | Get one design | ActivitiesDirector, StoreManager, Treasurer, LicensingCoordinator |
| POST | `/spirit-store/designs/{designId}/licensing-transition` | Licensing workflow transition (OCC-guarded) | LicensingCoordinator |
| POST | `/spirit-store/product-variants` | Create a SKU (design x size), unique per program | StoreManager |
| GET | `/spirit-store/product-variants` | List variants | ActivitiesDirector, StoreManager, Treasurer, StudentCashier |
| GET | `/spirit-store/product-variants/{variantId}` | Get one variant | ActivitiesDirector, StoreManager, Treasurer, StudentCashier |
| POST | `/spirit-store/seasonal-drops` | Create a SeasonalDrop (OCC-guarded on program) | StoreManager |
| GET | `/spirit-store/seasonal-drops` | List drops | ActivitiesDirector, StoreManager, Treasurer |
| GET | `/spirit-store/seasonal-drops/{dropId}` | Get one drop | ActivitiesDirector, StoreManager, Treasurer |
| POST | `/spirit-store/seasonal-drops/{dropId}/transition` | Drop lifecycle transition (OPEN, CLOSED, SETTLED) | StoreManager |
| POST | `/spirit-store/purchase-orders` | Create a stock PurchaseOrder (status DRAFT) | StoreManager |
| GET | `/spirit-store/purchase-orders` | List purchase orders | ActivitiesDirector, StoreManager, Treasurer |
| GET | `/spirit-store/purchase-orders/{poId}` | Get one purchase order | ActivitiesDirector, StoreManager, Treasurer |
| POST | `/spirit-store/purchase-orders/{poId}/submit` | Submit a DRAFT purchase order | StoreManager |
| POST | `/spirit-store/purchase-orders/{poId}/receive` | Receive quantity against a submitted order | StoreManager |
| POST | `/spirit-store/purchase-orders/{poId}/cancel` | Cancel a DRAFT or SUBMITTED purchase order | StoreManager |
| POST | `/spirit-store/preorder-campaigns` | Create a preorder campaign (status DRAFT) | StoreManager |
| GET | `/spirit-store/preorder-campaigns` | List campaigns | ActivitiesDirector, StoreManager, Treasurer, Customer |
| GET | `/spirit-store/preorder-campaigns/{campaignId}` | Get one campaign (incl. unit projections) | ActivitiesDirector, StoreManager, Treasurer, Customer |
| POST | `/spirit-store/preorder-campaigns/{campaignId}/open` | Open a DRAFT campaign | StoreManager |
| POST | `/spirit-store/preorder-campaigns/{campaignId}/lock` | Lock an OPEN campaign (goal fork, vendor selection, auto POs) | StoreManager |
| POST | `/spirit-store/preorder-campaigns/{campaignId}/cancel` | Abandon a DRAFT or OPEN campaign | StoreManager |
| POST | `/spirit-store/preorders` | Place a preorder (deposit computed) | Customer |
| GET | `/spirit-store/preorders` | List preorders | ActivitiesDirector, StoreManager, Treasurer, Customer |
| GET | `/spirit-store/preorders/{preorderId}` | Get one preorder | ActivitiesDirector, StoreManager, Treasurer, Customer |
| POST | `/spirit-store/preorders/{preorderId}/pay` | Pay deposit or balance for a preorder | Customer |
| POST | `/spirit-store/preorders/{preorderId}/fulfill` | Fulfill a PAID preorder against on-hand stock | StoreManager |
| POST | `/spirit-store/preorders/{preorderId}/cancel` | Customer cancels a preorder while the campaign is OPEN | Customer |
| POST | `/spirit-store/event-sales` | Schedule a POS event | StoreManager |
| GET | `/spirit-store/event-sales` | List events | ActivitiesDirector, StoreManager, Treasurer, StudentCashier |
| GET | `/spirit-store/event-sales/{eventId}` | Get one event (incl. drawer totals) | ActivitiesDirector, StoreManager, Treasurer, StudentCashier |
| POST | `/spirit-store/event-sales/{eventId}/open-drawer` | Open the cash drawer with a starting float | StudentCashier |
| POST | `/spirit-store/event-sales/{eventId}/close-count` | Count the drawer; auto-reconcile within tolerance else flag | Treasurer |
| POST | `/spirit-store/event-sales/{eventId}/reconcile` | Director override reconcile of a FLAGGED event | ActivitiesDirector |
| POST | `/spirit-store/event-sales/{eventId}/cancel` | Cancel a SCHEDULED event | StoreManager |
| POST | `/spirit-store/orders` | Create an order (EVENT_POS or ONLINE) | StudentCashier, Customer |
| GET | `/spirit-store/orders` | List orders | ActivitiesDirector, StoreManager, Treasurer, StudentCashier, Customer |
| GET | `/spirit-store/orders/{orderId}` | Get one order | ActivitiesDirector, StoreManager, Treasurer, StudentCashier, Customer |
| POST | `/spirit-store/orders/{orderId}/fulfillment-transition` | Online fulfillment transition (READY_FOR_PICKUP, PICKED_UP) | StoreManager |
| POST | `/spirit-store/orders/{orderId}/refund` | Refund an order fully or partially | Treasurer |
| POST | `/spirit-store/exchanges` | Open a size exchange for a fulfilled order line | Customer, Treasurer |
| GET | `/spirit-store/exchanges` | List exchanges | ActivitiesDirector, StoreManager, Treasurer, Customer |
| GET | `/spirit-store/exchanges/{exchangeId}` | Get one exchange | ActivitiesDirector, StoreManager, Treasurer, Customer |
| POST | `/spirit-store/exchanges/{exchangeId}/decision` | Approve (reserves new unit) or reject an exchange | Treasurer |
| POST | `/spirit-store/exchanges/{exchangeId}/complete` | Complete an approved exchange (settle differential, restock/write off) | Treasurer |
| POST | `/spirit-store/activity-accounts` | Create an activity account | ActivitiesDirector |
| GET | `/spirit-store/activity-accounts` | List activity accounts | ActivitiesDirector, Treasurer |
| GET | `/spirit-store/activity-accounts/{accountId}` | Get one activity account | ActivitiesDirector, Treasurer |
| POST | `/spirit-store/allocation-runs` | Create a DRAFT allocation run (waterfall lines frozen) | Treasurer |
| GET | `/spirit-store/allocation-runs` | List allocation runs | ActivitiesDirector, Treasurer |
| GET | `/spirit-store/allocation-runs/{runId}` | Get one allocation run | ActivitiesDirector, Treasurer |
| POST | `/spirit-store/allocation-runs/{runId}/post` | Post a DRAFT run (program must be CLOSED) | Treasurer |
| POST | `/spirit-store/allocation-runs/{runId}/reverse` | Reverse a POSTED run (compensating action) | Treasurer |
| POST | `/spirit-store/_clock/set_current_utc` | Set the server's logical clock | ActivitiesDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue pins only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_DESIGN_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANT_NOT_FOUND` | 404 Not Found |
| `ERR_DROP_NOT_FOUND` | 404 Not Found |
| `ERR_PO_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_PREORDER_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_EXCHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSED` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_DESIGN_NOT_LICENSED` | 409 Conflict |
| `ERR_LICENSE_REVOKED` | 409 Conflict |
| `ERR_DROP_NOT_OPEN` | 409 Conflict |
| `ERR_DROP_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_DROP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_REGISTER_CONFLICT` | 409 Conflict |
| `ERR_EVENT_WINDOW_PASSED` | 409 Conflict |
| `ERR_DRAWER_NOT_OPEN` | 409 Conflict |
| `ERR_VENDOR_NOT_APPROVED` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CAMPAIGN` | 409 Conflict |
| `ERR_DUPLICATE_VARIANT` | 409 Conflict |
| `ERR_VARIANT_DESIGN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PREORDER_NOT_PAYABLE` | 409 Conflict |
| `ERR_PREORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PICKUP_NOT_READY` | 409 Conflict |
| `ERR_PICKUP_EXPIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_MIN_ORDER_QTY` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_VENDOR` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_VARIANT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_SHORTFALL` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_EXCEEDS_PROFIT` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_OPERATIONS` | 409 Conflict |
| `ERR_PROFIT_NOT_FULLY_ALLOCATED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
