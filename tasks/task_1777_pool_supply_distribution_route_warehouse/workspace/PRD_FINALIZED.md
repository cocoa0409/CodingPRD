# Pool Supply Distribution API — Product Requirements Document

## 1. Introduction

A regional pool-supply distribution branch lives and dies by the season. Every spring, dealers and pool service companies commit to pre-season chemical buys; every summer morning, a will-call counter rush collides with a fleet of route trucks being loaded for the day's deliveries; and all year long the branch juggles hazmat storage rules, equipment warranty routing, and the occasional pallet of expired shock treatment that cannot legally come back through the door. This document specifies the Pool Supply Distribution API: the system of record for one such branch's catalog, stock lots, seasonal commitment pools, sales orders, backorders, warranty claims, and returned-goods authorizations.

The API is mounted under the `/pool-supply` prefix. Its design centers on two persistent tensions. The first is allocation under scarcity: when a peak-season chemical runs short, confirmed orders go on backorder and a strict, tier-aware waterfall decides who receives the next replenished units — while the branch's own stocking posture visibly degrades from `NORMAL` to `CONSTRAINED` to `FROZEN`. The second is compliance: oxidizers and corrosives may only be stored at certified warehouses, delivered to licensed accounts within the seasonal window, and never restocked once returned. Product managers and engineers should read this document as the sole normative specification of those behaviors.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to each operation is further restricted by role; acting outside one's role draws `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Five roles exist, spelled exactly as follows:

- `BranchManager` — the branch general manager, holding the full administrative surface: the logical clock, branch and catalog creation, account administration, seasonal program and commitment management, invoicing, backorder cancellation, service-center registration, warranty adjudication, and RMA approval.
- `CounterRep` — the will-call counter representative, who drafts and confirms counter orders and completes pickups.
- `RouteDispatcher` — the route desk operator, who drafts and confirms truck-route orders and records proof of delivery.
- `WarehouseLead` — the warehouse floor lead, who receives and replenishes stock lots, marks orders loaded, allocates backorders, and physically receives returned goods.
- `Account` — a dealer or service-company buyer acting in self-service.

Role identity works as follows. When `X-User-Role` is `Account`, `X-User-ID` is the `id` of the acting `Account` entity; ownership checks on any resource that references an account compare the resource's `account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `BranchManager`, `CounterRep`, `RouteDispatcher`, or `WarehouseLead`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. All list responses are sorted by `created_at` in ascending order, and the `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — Branch, Account, Product, StockLot, SeasonalProgram, SeasonalCommitment, SalesOrder, BackorderRequest, ServiceCenter, WarrantyClaim, and ReturnAuthorization — carries a standard quartet of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, the same format, refreshed on every mutation; and `version`, an integer that starts at its initial value and increments by one on every mutation of the resource, including mutations driven by cascades originating elsewhere. OrderLine is the sole exception: as a lightweight child record it carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.5. Monetary Values and Precision

All money in the system is represented as integer cents; there are no decimal dollar amounts anywhere in the API. Wherever a calculation produces a fractional cent, the value is rounded half up to the nearest whole cent. Two rounding disciplines are pinned and non-interchangeable. Order pricing rounds each line's extended amount half up *before* the line amounts are summed into the order subtotal — summing unrounded line amounts and rounding once at the end is a specification violation. The warranty final credit rounds the actual-hours base half up *before* the cap is applied. Percentages such as `early_buy_discount_pct` and `restocking_fee_pct` are carried as numbers and applied exactly as specified in §3.

### 2.6. The Logical Clock

Time inside the system is governed by a logical clock, not the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit set operation the server must answer all time-dependent questions from that default — never from wall-clock time. A `BranchManager` may advance the clock through an administrative capability that accepts a `to_iso8601` instant; the capability responds with the resulting `current_utc`. Every rule in this document that speaks of "today", "now", "the current calendar year", or a deadline reads from this logical clock.

### 2.7. Branch Stock Posture

Each branch derives a `posture` of `NORMAL`, `CONSTRAINED`, or `FROZEN`, recomputed after every order confirmation, order cancellation, backorder allocation, backorder closure or cancellation, and lot replenishment.

A branch is `FROZEN` when at least one product's open backorder load — the sum of `qty_open` across that branch's backorder requests in `OPEN` status for that product — reaches or exceeds the product's `shortage_freeze_threshold`; reaching the threshold exactly is enough to freeze. Failing that, a branch is `CONSTRAINED` when at least one product whose `low_stock_floor` is greater than zero shows total available units at or below that floor, where total available units means the sum over the branch's lots of that product of physical units on hand minus both reservation buckets; sitting exactly at the floor is constrained. Failing both, the branch is `NORMAL`. The frozen test always takes precedence over the constrained test.

### 2.8. Optimistic Concurrency Control

Three write operations mutate shared, branch-scoped or lot-scoped derived state and therefore require the caller to prove it has observed the current version of a parent aggregate. Endpoints not listed here take no version field at all.

- **Order confirmation** requires a non-optional `expected_branch_version` carrying the client's last observed `version` of the fulfilling branch. If the branch's version has advanced since that observation, the request is rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412). Evaluation precedence on confirmation is pinned: authentication, then ownership, then existence, then the order's state preconditions (such as the draft check), then this version check, then the business checks of §2.9 in their pinned order. A confirm that violates a state precondition reports the state error even when the supplied branch version is also stale.
- **Manual backorder allocation** requires a non-optional `expected_stock_lot_version` carrying the client's last observed `version` of the target stock lot. A mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Precedence is pinned: authentication, then existence, then the backorder's open-state check, then the version check, then the quantity check — so a stale version is reported even when the lot is empty at the same moment.
- **Seasonal commitment creation** requires a non-optional `expected_program_version` carrying the client's last observed `version` of the seasonal program. A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), ensuring pool-cap enforcement runs against a program snapshot the client actually saw.

In each case the losing writer re-reads the parent entity and retries with a fresh version.

### 2.9. Validation Order

Every endpoint evaluates checks in a fixed cascade, and the cascade's ordering is observable when several violations coexist. First come authentication checks: header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`), then entity-backed ownership — an `Account` principal may only act on resources whose `account_id` equals its `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`), a rule enforced on order confirm, order cancel, order pay, claim supply-info, and RMA creation. Next, existence: every path- or body-referenced id — branch, account, product, lot, program, commitment, order, claim, center, or RMA — must resolve, else `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Next, state preconditions: the target entity must be in the state its transition requires, with generic failures reported as `ERR_INVALID_STATE` (HTTP 409) and transition-specific failures carrying their own codes named throughout §3. Business rules come last, and where several apply to one endpoint their relative order is pinned in the workflow narratives: on order confirmation the hazmat storage-certification check precedes the hazmat license check, which precedes the route-date window check, which precedes the will-call authorization check, which precedes the frozen-posture check, which precedes the commitment-exhaustion check, which precedes account orderability. On commitment creation the order-window check precedes the pool-cap check. On warranty claim creation the serial/family check precedes the authorized-center routing check.

### 2.10. Hazardous Materials Governance

Chemical safety gates three independent decisions. Storage: a branch may hold hazmat chemicals at all only if its `hazmat_storage_certified` flag is true, and any order containing a hazmat line is refused at confirmation when the fulfilling branch lacks that certification. Delivery: an account's `hazmat_delivery_license_expiry` records the ISO date after which hazmat route delivery to that account is forbidden; an account with no license on file (a null expiry) may never receive hazmat by truck. Disposal: expired chemicals are hazmat waste — they cannot re-enter the building through the returns channel, and they are never restocked under any circumstances. The specific rejections and their trigger points live in §3.4, §3.6, and §3.9.

### 2.11. The Account Volume Ledger and Tier Ratchet

Each account carries `ytd_volume_cents`, the sum of `invoiced_cents` over its sales orders whose payment reached `INVOICED` or `PAID`, whose fulfillment is not `CANCELLED`, and which were invoiced on or after January 1 at 00:00:00 UTC of the current UTC calendar year; the figure resets at that instant each year. An account's `tier` — one of `PRO`, `ELITE`, or `PREMIER` — is derived from this ledger: at least 5,000,000 cents ($50,000) earns `PREMIER`, at least 2,000,000 cents ($20,000) earns `ELITE`, and anything below earns `PRO`. The boundary is inclusive — an invoice landing exactly on 2,000,000 cents makes the account `ELITE`. Tier is a ratchet: invoicing may push it upward, but cancellations and returns never pull it back down, and it is never recomputed on draft edits. New accounts start at `PRO` with a zeroed ledger.

## 3. Business Logic & Workflows

### 3.1. Branch Setup, Catalog, and Stock Receiving

A `BranchManager` opens a branch by supplying a unique `branch_code` (for example, `PHX-12`), the hazmat flag `hazmat_storage_certified`, and the peak-season boundaries `peak_season_start` and `peak_season_end` as month-day strings (for example, `04-01` and `09-30`). An optional `willcall_cutoff_minutes` governs the morning-rush protocol described in §3.6 and defaults to 90 when omitted. A new branch begins with `status` `OPEN`, `posture` `NORMAL`, and a `seasonal_pool_units` of zero. The branch catalog is browsable by every role, and the branch list and detail views expose the live posture, pool total, and `version`.

Products are registered with a unique `sku`, a `product_family` of `CHEMICAL`, `EQUIPMENT`, or `PARTS`, and a `base_price_cents` list price. Optional registration fields include `hazmat_class` — one of `NONE`, `OXIDIZER_5_1`, or `CORROSIVE_8`, defaulting to `NONE`, and only a `CHEMICAL` product may carry a non-`NONE` class — plus `expiry_tracked` (default false) for dated chemicals, `low_stock_floor` (default 0) feeding the constrained-posture test, and `shortage_freeze_threshold` (default 100) feeding the freeze test. The product list accepts `product_family` and `hazmat_class` filters alongside the standard pagination parameters.

A `WarehouseLead` receives physical stock as lots. Each lot names its owning `branch_id` and `product_id`, a supplier `lot_code` unique within the branch-and-product pairing, the received `qty_on_hand`, and — if and only if the product is `expiry_tracked` — an `expiry_date`. At receipt the lot's `qty_available` equals its `qty_on_hand`, and its `hazmat_storage_class` is copied from the product's `hazmat_class` and frozen forever after. Availability is a three-bucket ledger: `qty_reserved_willcall` counts units held for confirmed counter orders not yet picked up or released, `qty_reserved_route` counts units held for confirmed truck orders not yet shipped or released, and `qty_available` is what remains of `qty_on_hand` after both reservation buckets — it may never go negative. The only way to raise `qty_on_hand` after receipt is replenishment by a `WarehouseLead` with an `add_qty`; replenishment increments `qty_on_hand` by exactly that amount, increments the lot's `version`, fires the backorder waterfall of §3.7, and recomputes branch posture. The lot list supports `branch_id` and `product_id` filters.

### 3.2. Accounts and Commercial Standing

A `BranchManager` onboards a buyer with an externally assigned, unique `account_number` and an `account_type` of `DEALER` (a retail dealer) or `SERVICE_CO` (a pool service company). Optional onboarding fields are the `hazmat_delivery_license_expiry` date, the `willcall_authorized` flag (default true), and the `credit_hold` flag (default false). New accounts begin `ACTIVE` at tier `PRO` with `ytd_volume_cents` zero. Account `status` moves between `ACTIVE` and `SUSPENDED`, and a `BranchManager` may adjust `credit_hold`, `willcall_authorized`, `hazmat_delivery_license_expiry`, and `status` on an existing account at any time. The account list — staff-facing only — accepts `account_type` and `tier` filters.

Two account conditions block order confirmation outright, as detailed in §3.4: a suspended account or an account on credit hold cannot confirm, and an account not authorized for will-call cannot confirm a counter order. Tier economics — how volume accrues, when tier is recomputed, and why it never falls — follow §2.11 and the confirm-time snapshot rule of §3.4.

### 3.3. Seasonal Programs and Pre-Season Commitments

Pre-season stocking runs through seasonal programs. A `BranchManager` creates a program in `DRAFT` with a `branch_id`, a `program_name` such as "2026 Early-Buy Chemical Program", an inclusive commitment window from `order_window_start` to `order_window_end`, an inclusive ship window from `ship_window_start` to `ship_window_end`, an `early_buy_discount_pct` between 0 and 50 applied to committed order lines, and a `pool_cap_units` ceiling on the total units the program will accept. The program list supports `branch_id` and `status` filters.

Opening a program requires it to be `DRAFT` — otherwise `ERR_PROGRAM_NOT_DRAFT` (HTTP 409) — and requires each window's start to be on or before its end, with violations reported as `ERR_PROGRAM_WINDOW_INVALID` (HTTP 400). Opening moves the program to `OPEN` and increments its `version`. Closing an `OPEN` program (attempts on anything else draw `ERR_PROGRAM_NOT_OPEN`, HTTP 409) settles its book: each commitment still `COMMITTED` whose `consumed_units` have reached its `committed_units` becomes `FULFILLED`, while each one still short becomes `DEFAULTED`.

Against an `OPEN` program, a `BranchManager` records a commitment naming `program_id`, `account_id`, and `committed_units`. Creation time must fall within the commitment window, inclusive at both ends — a commitment created exactly at `order_window_end` is allowed — else `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422). The program's pool is finite: if the sum of `committed_units` across the program's `COMMITTED` commitments plus the new units would exceed `pool_cap_units`, creation is rejected with `ERR_PROGRAM_POOL_EXHAUSTED` (HTTP 422), and this pool check is evaluated only after the window check. Because creation mutates the program's pool accounting, it carries the optimistic-concurrency contract of §2.8 via `expected_program_version`, with stale snapshots rejected as `ERR_STALE_PROGRAM_VERSION`.

A new commitment supersedes: if the same program-and-account pairing already holds a `COMMITTED` commitment, the old one transitions to `SUPERSEDED` and the new one is born `COMMITTED` — but only when the replacement's `committed_units` are at least the existing commitment's already-`consumed_units`, else `ERR_COMMITMENT_BELOW_CONSUMED` (HTTP 422). Either way the branch's `seasonal_pool_units` — defined as the sum of `committed_units` over `COMMITTED` commitments across the branch's programs — is recomputed: the superseded units leave the pool, the new units enter it, and a defaulted commitment likewise leaves the pool. Commitment `consumed_units` climb as confirmed orders draw against the commitment (§3.4), and when consumption reaches the committed figure the commitment becomes `FULFILLED`. Recording the commitment also increments the program's `version` by one — one more reason stale program snapshots surface. The commitment list supports `program_id`, `account_id`, and `status` filters.

### 3.4. Order Capture and Confirmation

Orders are drafted by a `CounterRep`, a `RouteDispatcher`, the buying `Account` itself, or a `BranchManager`, with the order's lines embedded in the creation payload under `lines`. The draft names the fulfilling `branch_id`, the buying `account_id`, and a `channel` of `WILL_CALL` for counter pickup or `ROUTE_DELIVERY` for truck delivery. An optional `commitment_id` marks the order as drawing down a pre-season commitment. `ROUTE_DELIVERY` drafts carry a `route_date`; `WILL_CALL` drafts carry a `requested_pickup_slot` that must fall within the will-call hours of the order's business day. Each embedded line names a `product_id` and a `qty` of at least one; a malformed payload — a `qty` below one, a window end before its start, a missing required field — is `ERR_INVALID_REQUEST` (HTTP 400). New drafts hold `fulfillment_status` `DRAFT` and `payment_status` `UNINVOICED`, with every computed line field zeroed. The order list supports `branch_id`, `account_id`, `channel`, `fulfillment_status`, `payment_status`, and `commitment_id` filters; lines are reachable per order or through a flat cross-order line listing that accepts `product_id`, `allocated_lot_id`, and `order_id` filters, giving staff reverse reachability from a product or lot to every line touching it.

Confirmation is the pivot of the whole system — the moment pricing pins, inventory reserves, and shortages become backorders. A `CounterRep` confirms counter orders, a `RouteDispatcher` confirms route orders, an `Account` confirms its own orders, and a `BranchManager` may confirm any. Confirming requires `expected_branch_version` per §2.8, with mismatches drawing `ERR_STALE_BRANCH_VERSION`. The order must be in fulfillment `DRAFT` (`ERR_ORDER_NOT_DRAFT`, HTTP 409) and its branch still `OPEN` (`ERR_BRANCH_CLOSED`, HTTP 409) before any business check runs.

The business gauntlet then runs in this pinned order. Storage safety first: if any line's product is hazmat and the branch is not hazmat-storage certified, `ERR_BRANCH_NOT_HAZMAT_CERTIFIED` (HTTP 422). Delivery licensing second: hazmat lines on a `ROUTE_DELIVERY` order require the account's `hazmat_delivery_license_expiry` to fall strictly after the `route_date`, with an absent license treated as no authorization — `ERR_HAZMAT_LICENSE_EXPIRED` (HTTP 422). Temporal third: a `route_date` before the logical today is always rejected, and when any line is hazmat the `route_date` must also fall no later than the branch's `peak_season_end` — `ERR_ROUTE_DATE_OUTSIDE_WINDOW` (HTTP 422). Channel authorization fourth: a `WILL_CALL` order for an account whose `willcall_authorized` is false draws `ERR_WILLCALL_NOT_AUTHORIZED` (HTTP 422). Posture fifth: a `FROZEN` branch refuses confirmation with `ERR_BRANCH_FROZEN` (HTTP 409), while `CONSTRAINED` branches keep trading. Commitment sixth: when `commitment_id` is set, the commitment must exist, be `COMMITTED`, belong to the order's account, and have remaining units — committed minus consumed — covering the order's total units, else `ERR_COMMITMENT_EXHAUSTED` (HTTP 422). Fiscal standing last: a `SUSPENDED` account or one under `credit_hold` is `ERR_ACCOUNT_NOT_ORDERABLE` (HTTP 402).

A successful confirmation performs all of the following as one act. The account's current tier is pinned onto the order as `tier_at_confirm`, and prices are computed against that snapshot even if the live tier later moves. Each line is FEFO-allocated: among the branch's lots of the line's product holding enough unreserved units to cover the full line quantity, the system picks the earliest `expiry_date` ascending with expiring lots ranked ahead of non-expiring ones and `created_at` ascending as the tie-break, records it as the line's `allocated_lot_id`, reserves the units as `allocated_qty`, and increments the lot's `qty_reserved_willcall` or `qty_reserved_route` bucket according to channel. A line no single lot can cover goes short: `allocated_qty` stays zero, `backordered_qty` equals the full `qty`, and a backorder request is born per §3.7 — which may cascade the branch into `FROZEN`. When `commitment_id` is set, the commitment's `consumed_units` climb by the order's total units, and a commitment thereby fully consumed becomes `FULFILLED`. Order pricing and freight per §3.5 are computed and stored as `order_subtotal_cents`, `freight_charge_cents`, and their sum `invoiced_cents`. Finally the branch's `version` increments by one, because confirmation has mutated branch-scoped derived state — the posture cascade and possibly the pool figure. The account's tier is then reconsidered only in the pinned bubble-up order of §2.11, and only after this order's own volume has posted.

### 3.5. Order Pricing, Tier Discounts, and the Freight Program

Line pricing at confirmation runs in a pinned sequence. Start from the product's `base_price_cents`. Apply the tier factor implied by `tier_at_confirm`: no discount for `PRO`, 5% for `ELITE`, 10% for `PREMIER`. If the order draws on a commitment, additionally apply the seasonal factor — the program's `early_buy_discount_pct` expressed as a fraction of a hundred; without a commitment that factor is zero. The unrounded unit price is the base price reduced by both factors multiplicatively. The line's `extended_price_cents` is the unrounded unit price times `qty`, rounded half up to whole cents — per line, before any summation. The line's `unit_price_cents` is then derived from that rounded extended amount: the extended amount divided by `qty`, rounded half up. The order's `order_subtotal_cents` is the sum of the per-line rounded extended amounts; summing unrounded amounts and rounding once would be a specification violation.

Freight is an order-level threshold calculation — evaluating the threshold per line instead is a declared trap variant and produces wrong freight on multi-line orders. Counter orders pay no freight: `freight_charge_cents` is zero for `WILL_CALL`. For `ROUTE_DELIVERY`, the freightable amount is the whole `order_subtotal_cents`, and hazmat lines do count toward the minimum. When that amount reaches the free-freight minimum of 50,000 cents ($500), freight is zero. Below it, the charge assembles three parts: a base fee of 2,500 cents; a hazmat surcharge of 1,800 cents when any line's product carries a non-`NONE` `hazmat_class`; and a shortfall fee equal to the gap between the 50,000-cent minimum and the freightable amount, capped at 7,500 cents so that a near-miss order never pays more than the cap on that component. The order's `invoiced_cents` is subtotal plus freight, and it freezes the moment the order is invoiced.

### 3.6. Will-Call Rush, Route Load, and Fulfillment

The morning rush has its own protocol: during the first `willcall_cutoff_minutes` minutes after the will-call rush opens — 90 minutes unless the branch overrides it — will-call reservations hold priority over route load. A confirmed order's units sit in the appropriate reservation bucket until the warehouse acts.

A `WarehouseLead` marks a confirmed order picked and loaded. The order must be in fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`, HTTP 409), and every line must be fully allocated — any line with `backordered_qty` above zero blocks the load with `ERR_ORDER_LINES_SHORT` (HTTP 409). Marking loaded converts reservations into shipments: each allocated line decrements its lot's `qty_on_hand` by the allocated amount and the corresponding reservation bucket is released. The order advances from `CONFIRMED` to `PICKED_LOADED`.

Completion is the handover. For counter orders a `CounterRep` records the pickup; for route orders a `RouteDispatcher` records proof of delivery; a `BranchManager` may do either. Completion requires fulfillment `PICKED_LOADED` (`ERR_ORDER_NOT_LOADED`, HTTP 409) and payment already `PAID` (`ERR_ORDER_UNPAID`, HTTP 409), and moves fulfillment to `COMPLETED`.

The payment dimension runs in parallel to fulfillment, independently: from `UNINVOICED`, invoicing by a `BranchManager` requires fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`) and payment still `UNINVOICED` (`ERR_ORDER_ALREADY_INVOICED`, HTTP 409); it freezes `invoiced_cents`, adds that amount into the account's `ytd_volume_cents`, recomputes the account's tier — which may ratchet upward but never downward — and moves payment to `INVOICED`. Payment recording by the `Account` itself or a `BranchManager` requires payment `INVOICED` (`ERR_ORDER_NOT_INVOICED`, HTTP 409) and lands the order at `PAID`.

Cancellation unwinds a `CONFIRMED` order — any other fulfillment state draws `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409) — and is available to a `BranchManager` or the owning `Account`. The compensating act releases every line's lot reservation by its `allocated_qty`, cancels the order's `OPEN` backorder requests, and recomputes branch posture, which may drop the branch out of `FROZEN` into `CONSTRAINED` or `NORMAL`. If the order drew on a commitment, the commitment's `consumed_units` fall by the order's total units, and a commitment that this order had pushed to `FULFILLED` reverts to `COMMITTED`. The account's `ytd_volume_cents` is decremented by the order's `invoiced_cents` — but per §2.11 the tier ratchet holds and the account's tier is not recomputed downward.

### 3.7. Backorders and the Replenishment Waterfall

When confirmation leaves a line short, the system births a backorder request in `OPEN` status: it references the `branch_id`, the short `order_line_id`, the `product_id` copied from the line, the `account_id` copied from the order, the original shortage as an immutable `qty_original`, the still-owed balance `qty_open`, and a `priority_rank` snapshotted at creation — 1 when the confirming order's `tier_at_confirm` was `PREMIER`, 2 for `ELITE`, 3 for `PRO`. That snapshot is a ratchet: a backorder's place in line never moves even if the account's live tier changes afterward. The backorder list supports `branch_id`, `product_id`, `account_id`, `status`, `order_line_id`, and `superseded_by_id` filters.

Allocation is a waterfall with a pinned evaluation order, triggered two ways: automatically whenever a `WarehouseLead` replenishes a lot, and manually when a `WarehouseLead` or `BranchManager` allocates a specific `OPEN` backorder against a chosen lot. The candidate set is the `OPEN` backorders whose product and branch match the lot's — requests already `ALLOCATED` with a residual do not re-enter a sweep. Candidates are ranked by `priority_rank` ascending, ties broken by `created_at` ascending; the UUID `id` must never be used as a ranking key. The sweep walks the ranked candidates, granting each the smaller of its `qty_open` and the lot's remaining `qty_available`, reserving the grant in the bucket matching the parent order's channel, decrementing `qty_open`, and stopping when availability is exhausted. A candidate drained to zero becomes `CLOSED`; one still owed units remains `ALLOCATED` with its residual. Branch posture is recomputed once after the sweep — falling back below a product's `shortage_freeze_threshold` may unfreeze the branch.

Manual allocation names a `lot_id` and carries the lot-version OCC contract of §2.8 via `expected_stock_lot_version`, with mismatches rejected as `ERR_STALE_LOT_VERSION`; it increments the lot's `version`. The backorder must be `OPEN` (`ERR_BACKORDER_NOT_OPEN`, HTTP 409), and the target lot must have at least one unit of `qty_available` — a completely empty lot draws `ERR_LOT_EMPTY` (HTTP 422), though per §2.8 a stale lot version is reported first when both conditions hold. A `BranchManager` may also cancel an `OPEN` backorder outright — again `ERR_BACKORDER_NOT_OPEN` guards the state — moving it to `CANCELLED` with a posture recompute.

One rollback path completes the picture: if the order whose reservation covered an allocation is cancelled before load, and the freed allocation cannot be reassigned to another backorder of the same product, the request rolls from `ALLOCATED` back to `OPEN` — the lot reservation is released, `qty_open` is restored by the released units, and posture is recomputed, which may push the branch back into `FROZEN`.

### 3.8. Equipment Warranty and Authorized Service Routing

Warranty covers equipment only. A claim is submitted by the owning `Account` or a `BranchManager`, naming `account_id`, `product_id`, the unit's `serial_number`, its `brand`, the original `purchase_date` from which the warranty term is measured, and a free-text `failure_description`. Two creation checks run in order. First, the product's `product_family` must be `EQUIPMENT`, and the `serial_number` must not already appear on any claim for the same product that is not `REJECTED` — violations draw `ERR_CLAIM_SERIAL_DUPLICATE` (HTTP 409). Second, at least one `ACTIVE` service center must carry the `brand` in its `authorized_brands`, else the claim cannot be routed and is rejected with `ERR_NO_AUTHORIZED_CENTER` (HTTP 422). Claims support listing with `account_id`, `status`, `product_id`, and `assigned_center_id` filters.

Service centers are registered by a `BranchManager` with a `center_name`, a `region_code` such as `SW`, `TX`, or `FL`, the `authorized_brands` array, and an hourly `labor_rate_cents`; centers begin `ACTIVE` and may later be moved to `SUSPENDED` or have their rate adjusted. The center list supports `region_code` and `status` filters. At submission the claim's `assigned_center_id` is chosen by a deterministic selector over `ACTIVE` centers authorized for the brand: centers whose `region_code` matches the region of the account's branch rank first, then cheaper `labor_rate_cents`, then earlier `created_at`. Submission also books a provisional credit: a flat two-hour labor estimate at the assigned center's hourly rate, stored as `provisional_credit_cents`, with the claim entering `SUBMITTED`.

Adjudication belongs to the `BranchManager`. Starting review requires `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`, HTTP 409) and moves the claim to `UNDER_REVIEW`. From there the manager may request more information — moving the claim to `MORE_INFO` — and the owning account then supplies it via an `info_note`: supply requires the claim in `MORE_INFO` (`ERR_CLAIM_NOT_MORE_INFO`, HTTP 409), requires the caller to own the claim (`ERR_NOT_CLAIM_OWNER`, HTTP 403), and increments the `info_cycles` counter. The loop may run at most three times: when `info_cycles` has already reached 3, a further supply attempt is rejected with `ERR_CLAIM_INFO_CYCLE_EXHAUSTED` (HTTP 409), and the claim must then be settled by rejection. Request-info, approve, and reject all require `UNDER_REVIEW` (`ERR_CLAIM_NOT_UNDER_REVIEW`, HTTP 409).

Approval additionally requires the assigned center to still be `ACTIVE` — a suspended center blocks approval with `ERR_CENTER_SUSPENDED` (HTTP 409) — and moves the claim to `APPROVED`. Rejection lands the claim at `REJECTED` and zeroes the `provisional_credit_cents` as compensation. Resolution requires `APPROVED` (`ERR_CLAIM_NOT_APPROVED`, HTTP 409) and a supplied `actual_labor_hours` greater than zero (`ERR_INVALID_REQUEST`); it computes the final credit as the actual hours times the assigned center's hourly rate, rounded half up to whole cents, then capped at six hours at that rate — so the payable amount never exceeds a six-hour job. The provisional figure stays on record, and `final_credit_cents` minus `provisional_credit_cents` is the observable payable delta, which may be negative when the flat estimate overshot — a clawback. Closing requires `RESOLVED` (`ERR_CLAIM_NOT_RESOLVED`, HTTP 409) and lands the claim at `CLOSED`.

### 3.9. Returned Goods, Expired Chemicals, and Season Closeout

Returns run through a return merchandise authorization. The owning `Account` or a `BranchManager` requests one by naming `account_id`, the original `order_id` (which must have reached fulfillment `COMPLETED` before approval, checked as `ERR_RMA_ORDER_NOT_COMPLETED`, HTTP 409), the `product_id`, the `lot_id` the goods came from, a `qty` of at least one, and a `reason` of `DEFECTIVE`, `WRONG_ITEM`, `OVERSTOCK`, or `EXPIRED`. The RMA list supports `account_id`, `order_id`, `status`, `product_id`, and `lot_id` filters. One rejection happens at request time rather than approval time: an `EXPIRED`-reason return of a `CHEMICAL` product whose lot's `expiry_date` is on or before the logical today is refused outright with `ERR_RETURN_EXPIRED_CHEMICAL` (HTTP 422), because expired chemicals are hazmat waste and cannot re-enter the branch. A fresh request sits in `REQUESTED`.

A `BranchManager` approves or denies. Both require `REQUESTED` (`ERR_RMA_NOT_REQUESTED`, HTTP 409); denial moves the RMA to `DENIED` and ends it. Approval re-runs the expiry guard for `EXPIRED`-reason chemical returns — if the lot has expired since the request, approval is refused with `ERR_RMA_LOT_EXPIRED_SINCE_REQUEST` (HTTP 409) — and on success computes the credit. The credit references the order line matching the RMA's order and product, choosing the earliest-created line when several match; the base is that line's frozen historical `unit_price_cents` — the tier-pinned price from the original confirmation, never current pricing — multiplied by the returned `qty`. The fee percentage is decided before the credit: zero for `DEFECTIVE` and `WRONG_ITEM`, a 15% restocking fee for `OVERSTOCK`, and zero for `EXPIRED`. The resulting `restocking_fee_pct` and `credit_cents` — the base reduced by the fee and rounded half up — are stored at approval, moving the RMA to `APPROVED`.

Physical receipt is a `WarehouseLead` act requiring `APPROVED` (`ERR_RMA_NOT_APPROVED`, HTTP 409). For chemical products the lot's `expiry_date` must still be after the logical today at receipt, else `ERR_RMA_LOT_EXPIRED_SINCE_REQUEST`. Receipt restocks the goods only when the product is not `CHEMICAL` and the reason is not `EXPIRED` — the lot's `qty_on_hand` grows by the returned `qty` — because chemicals are never restocked, full stop. Receipt moves the RMA to `RECEIVED`. Final credit posting by a `BranchManager` requires `RECEIVED` (`ERR_RMA_NOT_RECEIVED`, HTTP 409), moves the RMA to `CREDITED`, and has no effect on account volume: returns never move `ytd_volume_cents`.

The year's final act is season closeout. A `BranchManager` closes the branch's season only when no order of the branch remains in fulfillment `CONFIRMED` or `PICKED_LOADED` (`ERR_BRANCH_ORDERS_OPEN`, HTTP 409) and no backorder request of the branch remains `OPEN` or `ALLOCATED` (`ERR_BRANCH_BACKORDERS_OPEN`, HTTP 409). Closing moves the branch from `OPEN` to `CLOSED_SEASON`, cascades every `OPEN` seasonal program of the branch to `CLOSED` — settling each program's commitments exactly as a manual close would, short commitments to `DEFAULTED` and fully consumed ones to `FULFILLED` — and increments the branch's `version` by one.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition — return `200 OK`. Request payloads, computed fields, and side effects for each operation are defined by the workflows of §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pool-supply/_clock/set_current_utc` | Set the logical clock | BranchManager |
| POST | `/pool-supply/branches` | Create a branch | BranchManager |
| GET | `/pool-supply/branches` | List branches | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/branches/{id}` | Get a branch (posture, pool, version) | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| POST | `/pool-supply/branches/{id}/close-season` | Close the branch season; cascades to programs and commitments | BranchManager |
| POST | `/pool-supply/accounts` | Create an account | BranchManager |
| GET | `/pool-supply/accounts` | List accounts | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| GET | `/pool-supply/accounts/{id}` | Get an account | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| PATCH | `/pool-supply/accounts/{id}` | Update account flags (credit hold, will-call, license, status) | BranchManager |
| POST | `/pool-supply/products` | Create a product | BranchManager |
| GET | `/pool-supply/products` | List products | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/products/{id}` | Get a product | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| POST | `/pool-supply/stock-lots` | Receive a stock lot | WarehouseLead |
| GET | `/pool-supply/stock-lots` | List lots | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| GET | `/pool-supply/stock-lots/{id}` | Get a lot | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| POST | `/pool-supply/stock-lots/{id}/replenish` | Add units to a lot; triggers the backorder waterfall | WarehouseLead |
| POST | `/pool-supply/seasonal-programs` | Create a seasonal program (DRAFT) | BranchManager |
| GET | `/pool-supply/seasonal-programs` | List programs | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/seasonal-programs/{id}` | Get a program | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| POST | `/pool-supply/seasonal-programs/{id}/open` | Open a program for commitments | BranchManager |
| POST | `/pool-supply/seasonal-programs/{id}/close` | Close a program; settle commitments | BranchManager |
| POST | `/pool-supply/seasonal-commitments` | Create a commitment; supersedes an existing COMMITTED commitment for the same program and account; OCC on program version | BranchManager |
| GET | `/pool-supply/seasonal-commitments` | List commitments | BranchManager, Account |
| GET | `/pool-supply/seasonal-commitments/{id}` | Get a commitment | BranchManager, Account |
| POST | `/pool-supply/orders` | Create a draft order with embedded lines | CounterRep, RouteDispatcher, Account, BranchManager |
| GET | `/pool-supply/orders` | List orders | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/orders/{id}` | Get an order | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/order-lines` | Flat list of order lines across orders | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| GET | `/pool-supply/order-lines/{id}` | Get a single order line | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| GET | `/pool-supply/orders/{id}/lines` | List an order's lines | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| POST | `/pool-supply/orders/{id}/confirm` | Confirm an order: tier snapshot, FEFO allocation, backorders, posture cascade, pricing; OCC on branch version | CounterRep, RouteDispatcher, Account, BranchManager |
| POST | `/pool-supply/orders/{id}/mark-loaded` | Mark an order picked and loaded; decrements on-hand, releases reservations | WarehouseLead |
| POST | `/pool-supply/orders/{id}/complete` | Record pickup handover or proof of delivery; requires PAID | CounterRep, RouteDispatcher, BranchManager |
| POST | `/pool-supply/orders/{id}/cancel` | Cancel a CONFIRMED order with compensating releases | BranchManager, Account |
| POST | `/pool-supply/orders/{id}/invoice` | Invoice a CONFIRMED order; freezes the invoiced amount and posts volume | BranchManager |
| POST | `/pool-supply/orders/{id}/pay` | Record payment | BranchManager, Account |
| GET | `/pool-supply/backorder-requests` | List backorder requests | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| GET | `/pool-supply/backorder-requests/{id}` | Get a backorder request | BranchManager, CounterRep, RouteDispatcher, WarehouseLead |
| POST | `/pool-supply/backorder-requests/{id}/allocate` | Manually allocate an OPEN backorder against a lot; OCC on lot version | WarehouseLead, BranchManager |
| POST | `/pool-supply/backorder-requests/{id}/cancel` | Cancel an OPEN backorder | BranchManager |
| POST | `/pool-supply/service-centers` | Register an authorized service center | BranchManager |
| GET | `/pool-supply/service-centers` | List service centers | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| GET | `/pool-supply/service-centers/{id}` | Get a service center | BranchManager, CounterRep, RouteDispatcher, WarehouseLead, Account |
| PATCH | `/pool-supply/service-centers/{id}` | Update a center (status, labor rate) | BranchManager |
| POST | `/pool-supply/warranty-claims` | Submit a claim; assigns a service center; computes provisional credit | Account, BranchManager |
| GET | `/pool-supply/warranty-claims` | List claims | BranchManager, Account |
| GET | `/pool-supply/warranty-claims/{id}` | Get a claim | BranchManager, Account |
| POST | `/pool-supply/warranty-claims/{id}/start-review` | Move a claim to UNDER_REVIEW | BranchManager |
| POST | `/pool-supply/warranty-claims/{id}/request-info` | Request more information (MORE_INFO) | BranchManager |
| POST | `/pool-supply/warranty-claims/{id}/supply-info` | Account supplies information; loops back to UNDER_REVIEW | Account |
| POST | `/pool-supply/warranty-claims/{id}/approve` | Approve a claim; center must be ACTIVE | BranchManager |
| POST | `/pool-supply/warranty-claims/{id}/reject` | Reject a claim; provisional credit zeroed | BranchManager |
| POST | `/pool-supply/warranty-claims/{id}/resolve` | Resolve with actual hours; computes final credit | BranchManager |
| POST | `/pool-supply/warranty-claims/{id}/close` | Close a resolved claim | BranchManager |
| POST | `/pool-supply/return-authorizations` | Request a return authorization | Account, BranchManager |
| GET | `/pool-supply/return-authorizations` | List return authorizations | BranchManager, WarehouseLead, Account |
| GET | `/pool-supply/return-authorizations/{id}` | Get a return authorization | BranchManager, WarehouseLead, Account |
| POST | `/pool-supply/return-authorizations/{id}/approve` | Approve an RMA; computes credit; re-checks lot expiry | BranchManager |
| POST | `/pool-supply/return-authorizations/{id}/deny` | Deny an RMA | BranchManager |
| POST | `/pool-supply/return-authorizations/{id}/receive` | Receive returned goods; non-chemical restock only | WarehouseLead |
| POST | `/pool-supply/return-authorizations/{id}/credit` | Post the credit | BranchManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_CLAIM_OWNER` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_LOADED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_LINES_SHORT` | 409 Conflict |
| `ERR_ORDER_ALREADY_INVOICED` | 409 Conflict |
| `ERR_ORDER_NOT_INVOICED` | 409 Conflict |
| `ERR_ORDER_UNPAID` | 409 Conflict |
| `ERR_BRANCH_CLOSED` | 409 Conflict |
| `ERR_BRANCH_FROZEN` | 409 Conflict |
| `ERR_BRANCH_NOT_HAZMAT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_BRANCH_ORDERS_OPEN` | 409 Conflict |
| `ERR_BRANCH_BACKORDERS_OPEN` | 409 Conflict |
| `ERR_HAZMAT_LICENSE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ROUTE_DATE_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_WILLCALL_NOT_AUTHORIZED` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_NOT_ORDERABLE` | 402 Payment Required |
| `ERR_COMMITMENT_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_BELOW_CONSUMED` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_POOL_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_PROGRAM_WINDOW_INVALID` | 400 Bad Request |
| `ERR_BACKORDER_NOT_OPEN` | 409 Conflict |
| `ERR_LOT_EMPTY` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_MORE_INFO` | 409 Conflict |
| `ERR_CLAIM_INFO_CYCLE_EXHAUSTED` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_RESOLVED` | 409 Conflict |
| `ERR_CLAIM_SERIAL_DUPLICATE` | 409 Conflict |
| `ERR_NO_AUTHORIZED_CENTER` | 422 Unprocessable Entity |
| `ERR_CENTER_SUSPENDED` | 409 Conflict |
| `ERR_RMA_NOT_REQUESTED` | 409 Conflict |
| `ERR_RMA_NOT_APPROVED` | 409 Conflict |
| `ERR_RMA_NOT_RECEIVED` | 409 Conflict |
| `ERR_RMA_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_RETURN_EXPIRED_CHEMICAL` | 422 Unprocessable Entity |
| `ERR_RMA_LOT_EXPIRED_SINCE_REQUEST` | 409 Conflict |
| `ERR_STALE_BRANCH_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
