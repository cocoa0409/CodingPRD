# Video Game Retro Store API — Product Requirements Document

## 1. Introduction

The Video Game & Retro Store API powers the counter operations of a bricks-and-mortar shop that buys, sells, rents, and pre-sells both new and pre-owned video games, consoles, and accessories. A single storefront juggles a surprising number of intertwined money-and-inventory flows at once: customers trade in old cartridges for cash or store credit, put deposits down on unreleased titles that must be fairly rationed from a limited allocation pool, rent physical units for a fixed window, ring up point-of-sale purchases that mix cash, store credit, and loyalty rewards, and sign up for in-store tournaments held on a handful of gaming stations.

This document specifies the behaviour a compliant implementation must exhibit for every one of those flows. The heart of the system is twofold. First, a **quota-allocation** engine that decides, at the moment a pre-order is placed, whether a scarce physical unit can be granted immediately or whether the customer must wait in line — and that fairly promotes a waiting customer the instant a held unit is released. Second, a **store-credit ledger** that is the single, append-only source of truth for every customer's spendable balance, reconciled after every trade-in payout, refund, redemption, and manual adjustment. Around these two cores sit rental scheduling with buffer-aware conflict detection, tournament capacity and window enforcement, dual-variant money calculations that diverge between an estimate and a final settlement, and optimistic concurrency protection so that two clerks working the same allocation pool cannot silently overwrite each other's view of remaining stock.

Because store operations must reconcile immediately and never drift, every calculation in this document is exact: amounts are whole integer cents, counts are conserved across buckets, and the ledger balance always equals the sum of its entries. The remainder of this document defines the global contracts every endpoint honours (Section 2), the business workflows that make up the store's day (Section 3), the full endpoint list (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `Member`, `Clerk`, and `Manager`. If `X-User-Role` is missing or is any value other than these three, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header is valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles form a hierarchy of operational capability. A `Clerk` is a front-of-house operator who is a superset of `Member` business operations and additionally grades trade-ins, fulfills pre-order allocations, checks rentals out and in, rings up sales, and creates members, products, inventory units, and tournaments. A `Manager` is a full operator who can do everything a `Clerk` can, plus release allocation pools from embargo, void settled trade-ins, adjust store credit manually, create pre-order pools and stations, and drive the logical clock.

The `Member` role is **entity-backed**. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity; ownership checks on any resource that references a member compare that resource's `member_id` foreign key to `X-User-ID`. Concretely, a `Member` may only act on a `PreOrder`, `TradeIn`, or `Rental` whose `member_id` equals their own `X-User-ID`; an attempt to act on another member's resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The `Clerk` and `Manager` roles are **opaque**: when `X-User-Role` is `Clerk` or `Manager`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, and a `Clerk` or `Manager` may perform any member-scoped action on behalf of any member without triggering an ownership check.

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

Every list endpoint accepts two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp, `created_at`, in ascending order. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the total number of matching resources before the limit/offset window is applied and `has_more` indicates whether further resources remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `Member`, `Product`, `ProductStock`, `InventoryItem`, `PreOrder`, `Allocation`, `TradeIn`, `Rental`, `Sale`, `Station`, and `Tournament` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at its initial value on creation and increments by exactly one on every mutation. It is the value used for optimistic concurrency control described in Section 2.7.

There is one deliberate exception. A `StoreCreditEntry` is an append-only ledger event, not a mutable resource: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written a ledger entry is never modified. Any derived field that changes as a side effect of another operation — for example a `ProductStock`'s counts, a `Member`'s `store_credit_balance_cents`, or a `PreOrder`'s status — counts as a mutation of its owning resource, so it refreshes that resource's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Reverse-Reachability Listing

Several read endpoints expose a resource's dependents by walking a foreign key in reverse — for example listing all pre-order pools of a product, all inventory units of a product, all allocations of a pool or a pre-order, all store-credit entries or sales of a member, all pre-orders or trade-ins or rentals filtered by member, and all tournaments of a station. For any path containing an identifier, the server validates that identifier before proceeding. When a path carries more than one identifier, they are validated strictly left-to-right, and the first one that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or body validation is attempted. The same rule governs foreign-key references supplied in a request body: an unresolved `member_id`, `product_id`, `product_stock_id`, `inventory_item_id`, or `station_id` yields `ERR_NOT_FOUND`.

Filtered list endpoints additionally accept optional query parameters that narrow the result set: pre-orders may be filtered by `member_id` or `product_stock_id`, trade-ins by `member_id` or `product_id`, rentals by `member_id` or `inventory_item_id`, and tournaments by `station_id`.

### 2.6. Monetary Amounts, Points, and Rounding

All money in the system is stored and transported as whole integer cents; there are no fractional-cent or floating-point money fields in any response. Wherever a calculation produces a non-integer intermediate — for example applying a grade multiplier, a store-credit bonus percentage, or a tax rate — the result is rounded to a whole number of cents using the round-half-up method (a value exactly halfway between two integers rounds to the larger). Where a formula prescribes rounding at a specific step (for example, tax is rounded per line before the lines are summed), that step order is binding and must not be rearranged into a round-at-the-end scheme.

Loyalty points are whole integers. Where a points formula produces a fractional intermediate, the result is reduced to a whole number by taking the floor (rounding down), never round-half-up. Physical unit counts on a pool are likewise whole integers and are only ever moved between buckets, never fractionally split.

### 2.7. Optimistic Concurrency on Pre-Order Pools

Creating a pre-order is the one write in this system guarded by optimistic concurrency control. A pre-order creation request must carry `expected_product_stock_version`, holding the client's last observed `version` of the target `ProductStock` pool. Every successful pre-order creation resolves against that pool — granting a unit or waitlisting the request — and advances the pool's `version`; therefore a create still carrying a previously observed version is operating on a stale view of remaining availability. If `expected_product_stock_version` does not match the pool's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from resolving a pre-order against stock it has not actually observed. No other endpoint takes a version field or performs this check.

### 2.8. The Store-Credit Ledger

Each `Member` has a `store_credit_balance_cents` that is never stored as an independently mutable number. It is always the sum of that member's `StoreCreditEntry` rows — every entry carrying an `amount_cents` signed delta (which may be negative), a `reason`, a `related_ref` pointing back to the originating `TradeIn`, `Sale`, or `PreOrder` (or null for a manual adjustment), and the `member_id` it adjusts. The balance invariant holds after every mutation, including compensating reversals: `store_credit_balance_cents` equals the sum of the `amount_cents` of all of that member's entries, and it is never negative.

Entries are written by five kinds of event, distinguished by `reason`: `TRADE_IN_PAYOUT` (a settled store-credit trade-in), `TRADE_IN_VOID_REVERSAL` (undoing such a payout when a settled trade-in is voided), `SALE_REDEMPTION` (store credit spent on a sale, a negative delta), `PREORDER_REFUND` (money returned when a paid pre-order is cancelled), and `MANUAL_ADJUSTMENT` (a manager granting or deducting credit directly). Ledger entries are append-only and are never edited or deleted; a correction is expressed as a new, offsetting entry, and the member's balance is recomputed from the full ledger after each write.

### 2.9. Pool Unit Conservation

Each `ProductStock` pool tracks three count buckets plus a fixed total: `available_count`, `allocated_count`, `fulfilled_count`, and `total_count`. The total is set at creation and never changes thereafter. Units only ever move between buckets, and the conservation invariant `available_count + allocated_count + fulfilled_count` equal to `total_count` holds at all times. Three transitions move units: allocating a unit decrements `available_count` by one and increments `allocated_count` by one; releasing an allocation on cancellation decrements `allocated_count` by one and increments `available_count` by one; fulfilling a pre-order decrements `allocated_count` by one and increments `fulfilled_count` by one. On creation, `available_count` equals `total_count`, while `allocated_count` and `fulfilled_count` are both zero.

### 2.10. The Logical Clock

Time-sensitive behaviour — rental late fees and tournament registration windows — is driven by a server logical clock, never by wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it continues to read that default. A manager may advance or set the clock to a supplied `to_iso8601` instant; the new value takes effect immediately for all subsequent time comparisons.

### 2.11. Validation Ordering and Precedence

When several checks could reject a single request, they are evaluated in a fixed global precedence so that the returned error is deterministic. The order is: first authentication of the role header (`ERR_UNAUTHENTICATED`, 401); then role authorization for the endpoint (`ERR_FORBIDDEN`, 403); then existence of every path resource and body foreign key (`ERR_NOT_FOUND`, 404); then request-body schema validity — required fields present, enum members legal, numbers in range, sale `lines` non-empty with each `qty` at least 1 (`ERR_VALIDATION`, 400); then member resource ownership (`ERR_NOT_RESOURCE_OWNER`, 403); then the target resource being in a legal state for the requested transition (`ERR_INVALID_STATE`, 409); then item-availability checks (`ERR_ITEM_NOT_AVAILABLE`, 409); then pre-order fulfillment readiness (`ERR_ALLOCATION_NOT_READY`, 409); then the pool-version concurrency check (`ERR_STALE_VERSION`, 412). Domain-specific business checks — rental overlap, station double-booking, registration window, tournament capacity, duplicate registration, one-active-pre-order, insufficient store credit, and insufficient pre-order payment — are evaluated after the foregoing, in that relative order. In particular, on pre-order creation the stale-version check precedes the one-active-pre-order check; and on a sale, item availability is checked before the store-credit sufficiency check.

## 3. Business Logic & Workflows

### 3.1. Catalog, Members, Stations, and Physical Inventory

A `Member` is created by a clerk or manager with a `full_name` and a unique `email`, and an optional `tier`. The `tier` is one of `STANDARD`, `SILVER`, or `GOLD`, defaulting to `STANDARD` when omitted. A new member begins with a `store_credit_balance_cents` of zero and `loyalty_points` of zero, both of which are computed rather than directly set.

A `Product` is a catalog entry created with a `title`, a `kind` that is one of `GAME`, `CONSOLE`, or `ACCESSORY`, a `base_price_cents` that must be greater than zero, a `base_trade_value_cents` (the Grade-A trade-in base value) that must be at least zero, and an optional `daily_rental_rate_cents` that defaults to zero and must be at least zero. The base trade value anchors every trade-in quote, and the daily rental rate is the figure snapshotted onto each rental of a unit of this product.

Physical stock exists in two distinct forms. A `ProductStock` (covered in Section 3.2) is a pre-order allocation pool. An `InventoryItem`, by contrast, is a single physical unit of a product available for rental or sale, created against a product with a `condition_grade` of `A`, `B`, `C`, or `D` and an optional `acquisition_cost_cents` that defaults to zero and must be at least zero. An inventory item's `status` starts at `AVAILABLE` and is one of `AVAILABLE`, `RENTED`, or `SOLD`. Importantly, a rental reservation does not change an item's `status`; the item remains `AVAILABLE` (so multiple future rentals can be booked) until it is physically checked out.

A `Station` is a gaming/play area created by a manager with a `name` and a `seat_capacity` that must be greater than zero. Stations host the tournaments described in Section 3.9.

### 3.2. Pre-Order Pools and the Embargo Gate

A manager opens a pre-order allocation pool by creating a `ProductStock` against a product. Its inputs are `unit_price_cents` (the full per-unit pre-order price, which must be greater than zero), `deposit_cents` (the amount required to reserve a unit, which must be greater than zero and no greater than `unit_price_cents`), and `total_count` (the physical units the pool will ultimately fulfill, which must be greater than zero). The pool records which `product_id` it covers. On creation, `available_count` equals `total_count`, `allocated_count` and `fulfilled_count` are zero, and the pool's `release_state` begins at `EMBARGOED`.

The `release_state` is a gate with two values, `EMBARGOED` and `RELEASED`. Only a manager can lift the embargo, transitioning the pool `EMBARGOED → RELEASED`; this action increments the pool's `version` by one. The gate governs whether new pre-orders can be granted a unit: only a `RELEASED` pool may grant an `ALLOCATED` unit, whereas while a pool is `EMBARGOED` every new pre-order is placed on the waitlist. Once `RELEASED`, the pool is terminal in this dimension and cannot return to embargo.

### 3.3. Placing and Resolving a Pre-Order

A pre-order is placed by (or on behalf of) a member against a specific pool, supplying `member_id`, `product_stock_id`, and the `expected_product_stock_version` described in Section 2.7. Before anything else, the system enforces that a member may hold at most one active pre-order per pool: if the member already has a non-terminal pre-order — one whose `allocation_status` is `PENDING`, `WAITLISTED`, or `ALLOCATED` — for the same `product_stock_id`, the request is rejected with `ERR_ONE_ACTIVE_PREORDER` (HTTP 409).

Every pre-order carries two independent status dimensions. The **allocation dimension**, `allocation_status`, is one of `PENDING`, `WAITLISTED`, `ALLOCATED`, `FULFILLED`, or `RELEASED`, and begins conceptually at `PENDING`. The **payment dimension**, `payment_status` (Section 3.4), is tracked separately. At creation the allocation dimension is resolved immediately by the system: if the referenced pool is `RELEASED` and its `available_count` is at least 1, the pre-order is resolved to `ALLOCATED` (`PENDING → ALLOCATED`); otherwise — if the pool is still `EMBARGOED` or its `available_count` is zero — it is resolved to `WAITLISTED` (`PENDING → WAITLISTED`).

Resolving to `ALLOCATED` creates a companion `Allocation` resource in the `HELD` state, recording the `pre_order_id` it grants a unit to and the `product_stock_id` the unit is drawn from; it decrements the pool's `available_count` by one and increments `allocated_count` by one; and it increments the pool's `version` by one. Resolving to `WAITLISTED` grants no unit and moves no counts, but still increments the pool's `version` by one — which is precisely why a subsequent create carrying a stale `expected_product_stock_version` is refused. An `Allocation`'s own `status` is one of `HELD`, `CONSUMED`, or `RELEASED`.

### 3.4. Paying Down a Pre-Order

Payment is tracked on the pre-order's `payment_status`, one of `UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, or `REFUNDED`, starting at `UNPAID`. A member records a payment by submitting an `amount_cents` toward the pre-order; the amount is added to the running `amount_paid_cents`, which is never allowed to exceed the pool's `unit_price_cents`. Each payment must be positive, the first payment must bring `amount_paid_cents` to at least the pool's `deposit_cents`, and no payment may push the cumulative `amount_paid_cents` above `unit_price_cents`; a violation of any of these is rejected with `ERR_INSUFFICIENT_PAYMENT` (HTTP 402).

The resulting `payment_status` is determined by the new cumulative `amount_paid_cents`. If cumulative payment has reached at least `unit_price_cents`, the status advances to `PAID_IN_FULL` (from `UNPAID`, `DEPOSIT_PAID`, or wherever it stood). Otherwise, if cumulative payment is at least `deposit_cents` but still below `unit_price_cents`, the status advances from `UNPAID` to `DEPOSIT_PAID`. Thus the legal payment progression is `UNPAID → DEPOSIT_PAID → PAID_IN_FULL`, with a full payment able to jump straight from `UNPAID` to `PAID_IN_FULL`.

### 3.5. Fulfilling and Cancelling Pre-Orders

A clerk fulfills a pre-order once it is both allocated and fully paid. Fulfillment requires `allocation_status` equal to `ALLOCATED` and `payment_status` equal to `PAID_IN_FULL`; if either is not met, the request is rejected with `ERR_ALLOCATION_NOT_READY` (HTTP 409). On success the allocation dimension advances `ALLOCATED → FULFILLED`, the owning `Allocation` moves `HELD → CONSUMED`, and the pool's `allocated_count` is decremented by one while `fulfilled_count` is incremented by one.

Cancellation is available to the holding member (or an operator acting for them) and behaves according to where the pre-order stands. If the pre-order is `PENDING`, cancelling simply resolves it to `RELEASED` with no unit to return. If it is `WAITLISTED`, cancelling removes it from the waitlist and resolves it to `RELEASED`, again with no unit to return. If it is `ALLOCATED`, cancelling runs a three-hop cascade: hop 1 releases the held unit — the owning `Allocation` moves `HELD → RELEASED`, the pool's `allocated_count` is decremented by one and its `available_count` incremented by one, and the pre-order's `allocation_status` becomes `RELEASED`; hop 2 runs the waitlist promotion selector over the freed pool; and hop 3, if a promotion winner exists, grants the freed unit to that winner. The promotion advances the winning pre-order `WAITLISTED → ALLOCATED`, creates a new `Allocation` in `HELD` for it, and decrements `available_count` by one while incrementing `allocated_count` by one — so the net effect on the pool's counts is that the freed unit hops from the cancelled holder to the promoted waitlister.

The **waitlist promotion selector** considers only the pre-orders on the same pool whose `allocation_status` is `WAITLISTED`. Among those candidates it ranks by the member's tier rank descending — `GOLD` outranks `SILVER`, which outranks `STANDARD` — and breaks ties by `created_at` ascending (the earliest-created waiting pre-order wins). The single first-ranked candidate is the winner; the resource `id` is never used as a tiebreaker. If no candidate is waiting, no promotion occurs and the freed unit simply remains available.

Cancellation also settles the payment dimension. Regardless of prior payment, cancelling moves `payment_status` to `REFUNDED`. If the pre-order had `amount_paid_cents` greater than zero (that is, it was `DEPOSIT_PAID` or `PAID_IN_FULL`), the refund is issued as store credit: a `StoreCreditEntry` with `reason` `PREORDER_REFUND` and an `amount_cents` equal to the full paid amount is appended, and the member's `store_credit_balance_cents` is recomputed. A pre-order that was still `UNPAID` moves to `REFUNDED` with no ledger entry.

### 3.6. Trade-Ins: Intake, Grading, Dispute, Settlement, and Void

A member brings in a product to trade, creating a `TradeIn` with `member_id`, `product_id`, a `stated_grade` (the grade the member claims, one of `A`, `B`, `C`, or `D`), and a `payout_method` of either `CASH` or `STORE_CREDIT`. The intake computes a `provisional_value_cents` immediately from the stated grade, and the trade-in begins in status `SUBMITTED`. Its `final_grade` and `final_value_cents` remain null until a clerk grades it. The trade-in `status` is one of `SUBMITTED`, `OFFERED`, `DISPUTED`, `SETTLED`, or `VOIDED`.

**Valuation.** A trade-in value is computed in two steps. First, a graded amount is the product's `base_trade_value_cents` multiplied by the grade multiplier for the applicable grade — 1.0 for grade `A`, 0.75 for grade `B`, 0.5 for grade `C`, and 0.25 for grade `D` — with that product rounded half-up to whole cents. Second, if the `payout_method` is `STORE_CREDIT`, the value is the graded amount increased by a ten percent store-credit bonus (the graded amount multiplied by 1.10), again rounded half-up to whole cents; if the `payout_method` is `CASH`, the value is simply the graded amount with no bonus. The **provisional** valuation uses the member's `stated_grade` and writes `provisional_value_cents` at intake. The **final** valuation uses the clerk's `final_grade` and writes `final_value_cents`; it diverges from the provisional value whenever the clerk's `final_grade` differs from the member's `stated_grade`.

**Grading and the dispute cycle.** A clerk grades the trade-in by supplying a `final_grade`. Grading a `SUBMITTED` trade-in advances it `SUBMITTED → OFFERED`, sets `final_grade`, and pins `final_value_cents` from the final valuation. If the member is unhappy, they may dispute the current offer, moving it `OFFERED → DISPUTED`, which sends it back for re-grading with no value change. The clerk then re-grades a `DISPUTED` trade-in, moving it `DISPUTED → OFFERED`, overwriting `final_grade` and recomputing `final_value_cents`. This `OFFERED ↔ DISPUTED` cycle may repeat until the member accepts.

**Settlement.** The member accepts an `OFFERED` trade-in, moving it `OFFERED → SETTLED`. If the `payout_method` is `STORE_CREDIT`, settlement appends a `StoreCreditEntry` with `reason` `TRADE_IN_PAYOUT` and an `amount_cents` equal to the positive `final_value_cents`, and the member's `store_credit_balance_cents` is recomputed; if the `payout_method` is `CASH`, no ledger entry is written, as cash is disbursed out of band.

**Void and reversal.** A manager may void a settled trade-in, moving it `SETTLED → VOIDED`. If the settlement had created a `TRADE_IN_PAYOUT` entry (that is, it was a store-credit payout), the void is a compensating action: hop 1 appends a `StoreCreditEntry` with `reason` `TRADE_IN_VOID_REVERSAL` and an `amount_cents` equal to the negative of `final_value_cents`, and hop 2 recomputes the member's `store_credit_balance_cents` from the ledger, returning the balance to its pre-settlement value. Voiding a cash trade-in writes no reversal entry.

Every lifecycle action above requires the trade-in to be in the correct originating state — grading a non-`SUBMITTED`/non-`DISPUTED` trade-in, disputing a non-`OFFERED` one, accepting a non-`OFFERED` one, or voiding a non-`SETTLED` one is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.7. Rentals: Reservation, Checkout, Return, and Late Fees

A rental books a specific physical unit for a member over a window. Reservation supplies `member_id`, `inventory_item_id`, a `start_at`, and a `due_at`, where `due_at` must be strictly after `start_at`. At reservation the system snapshots the product's current daily rate into the rental's `daily_rate_cents`, computes `planned_days`, and sets the rental `status` to `RESERVED` — but it does not change the inventory item's `status`, because a reservation only books a future window and multiple future rentals of the same available unit may coexist. The rental `status` is one of `RESERVED`, `CHECKED_OUT`, or `RETURNED`. The `returned_at` is null until the unit is returned, and `late_fee_cents` is zero until then.

**Overlap protection.** A new rental interval is checked against every other active rental (one in `RESERVED` or `CHECKED_OUT` status) on the same inventory item, applying a 24-hour buffer between rentals. The new reservation conflicts with an existing one when the new `start_at` is earlier than the other rental's `due_at` plus 24 hours, and simultaneously the other rental's `start_at` is earlier than the new `due_at` plus 24 hours. Two rentals that are exactly the buffer apart do not conflict and are accepted. A conflict is rejected with `ERR_RENTAL_OVERLAP` (HTTP 409).

**Planned days and the estimated charge.** The `planned_days` is the exact elapsed time from `start_at` to `due_at`, expressed in hours and divided by 24, rounded up to the next whole day (ceiling on whole seconds). At checkout — allowed only while the rental is `RESERVED` and the item is `AVAILABLE` — a clerk moves the rental `RESERVED → CHECKED_OUT`, transitions the item `AVAILABLE → RENTED`, and pins the `estimated_charge_cents` as `daily_rate_cents` multiplied by `planned_days`. This estimate assumes an on-time return and excludes any late fee. If the item is not `AVAILABLE` at checkout time, the checkout is rejected with `ERR_ITEM_NOT_AVAILABLE` (HTTP 409).

**Return, late fee, and final charge.** A clerk returns a `CHECKED_OUT` rental, moving it `CHECKED_OUT → RETURNED`, setting `returned_at` to the current clock time, and transitioning the item `RENTED → AVAILABLE`. The `late_fee_cents` is then pinned: if `returned_at` is at or before `due_at`, the late fee is zero (the boundary is inclusive, so a return exactly on time incurs nothing); otherwise the number of late days is the elapsed time from `due_at` to `returned_at` in hours divided by 24, rounded up to the next whole day (ceiling on whole seconds), and the late fee is that number of late days multiplied by 500 cents per late day. Finally, `final_charge_cents` is pinned as `estimated_charge_cents` plus `late_fee_cents`; it diverges from the estimate exactly when `returned_at` is after `due_at`.

### 3.8. Point-of-Sale Sales, Store Credit, and Loyalty

A clerk rings up a `Sale` for a member, supplying `member_id`, a non-empty `lines` array, and an optional `redeem_store_credit_cents` (defaulting to zero, and at least zero). Each element of `lines` is an object with an `inventory_item_id`, a `unit_price_cents`, and a `qty` that must be at least 1. Every line's inventory item must be `AVAILABLE`; if any targeted item is not `AVAILABLE`, the sale is rejected with `ERR_ITEM_NOT_AVAILABLE` (HTTP 409) before any totals are computed. On a successful sale each line's inventory item transitions `AVAILABLE → SOLD`.

**Totals.** The `subtotal_cents` is the sum over the lines of each line's `qty` multiplied by its `unit_price_cents`. The `tax_total_cents` is computed per line and then summed: for each line, multiply its `qty` by its `unit_price_cents` by the tax rate of 0.0725 and round that line's tax half-up to whole cents, then sum the rounded per-line taxes — this round-then-sum order is binding and must not be collapsed into a single rounding of the grand total. The `total_cents` is `subtotal_cents` plus `tax_total_cents`.

**Redemption.** The store credit actually applied is the lesser of `redeem_store_credit_cents` and `total_cents` (a redemption is capped at the total, never producing a negative amount due). Before applying, the requested `redeem_store_credit_cents` must not exceed the member's current `store_credit_balance_cents`; if it does, the sale is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 402). The `amount_due_cents` is `total_cents` minus the applied credit. When the applied credit is greater than zero, a `StoreCreditEntry` with `reason` `SALE_REDEMPTION` and a negative `amount_cents` equal to the applied credit is appended, and the member's `store_credit_balance_cents` is recomputed.

**Loyalty.** Loyalty accrues only on the cash portion of the sale — the `total_cents` minus the applied credit — because store credit spent earns nothing further. The `loyalty_points_earned` is computed by multiplying that cash portion (in cents) by the member's tier rate (1.0 for `STANDARD`, 1.5 for `SILVER`, 2.0 for `GOLD`), dividing by 100, and taking the floor to a whole number of points, then capping the result at a maximum of 5000 points per sale. The earned points are pinned on the sale as `loyalty_points_earned` and added to the member's cumulative `loyalty_points`.

A manager may also adjust a member's store credit directly, supplying an `amount_cents` (which may be positive to grant or negative to deduct). This appends a `StoreCreditEntry` with `reason` `MANUAL_ADJUSTMENT` and a null `related_ref`, and recomputes the member's balance.

### 3.9. Tournaments and Registration

A clerk schedules a `Tournament` on a station, supplying `station_id`, `title`, `starts_at`, `ends_at`, `registration_opens_at`, `registration_closes_at`, and `max_participants`. The `ends_at` must be strictly after `starts_at`; the `registration_closes_at` must be strictly after `registration_opens_at` and no later than `starts_at`; and `max_participants` must be greater than zero. A new tournament begins with `registered_count` at zero and an empty `registered_member_ids` list.

**Station double-booking.** A tournament's play interval must not overlap another tournament already scheduled on the same station. Using half-open intervals with no buffer, the new tournament conflicts with an existing one when the new `starts_at` is earlier than the other's `ends_at` and simultaneously the other's `starts_at` is earlier than the new `ends_at`. Exact adjacency — the new `starts_at` equal to the other's `ends_at` — does not conflict and is accepted. A conflict is rejected with `ERR_STATION_DOUBLE_BOOKED` (HTTP 409).

**Registration.** A member registers for a tournament by supplying their `member_id`. Registration is guarded by three checks, evaluated in this order. First, the current clock time must fall within the half-open window from `registration_opens_at` (inclusive) up to `registration_closes_at` (exclusive); outside that window registration is rejected with `ERR_REGISTRATION_CLOSED` (HTTP 409). Second, the tournament must have remaining capacity — `registered_count` strictly less than `max_participants`; a full tournament is rejected with `ERR_TOURNAMENT_FULL` (HTTP 409). Third, the member must not already appear in `registered_member_ids`; a repeat registration is rejected with `ERR_ALREADY_REGISTERED` (HTTP 409). A successful registration increments `registered_count` by one and appends the member's id to `registered_member_ids`, and `registered_count` never exceeds `max_participants`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, payments, registrations, and the logical-clock control — return `200 OK`. All list and get operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Manager |
| POST | `/members` | Create a member | Clerk, Manager |
| GET | `/members/{id}` | Get a member | Member, Clerk, Manager |
| GET | `/members/{id}/store-credit-entries` | List a member's store-credit ledger entries | Member, Clerk, Manager |
| GET | `/members/{id}/sales` | List a member's sales | Member, Clerk, Manager |
| POST | `/members/{id}/store-credit/adjustments` | Manually grant or deduct store credit | Manager |
| POST | `/products` | Create a catalog product | Clerk, Manager |
| GET | `/products/{id}` | Get a product | Member, Clerk, Manager |
| GET | `/products/{id}/stocks` | List a product's pre-order pools | Member, Clerk, Manager |
| GET | `/products/{id}/inventory-items` | List a product's physical units | Member, Clerk, Manager |
| POST | `/products/{id}/stocks` | Create a pre-order pool (starts EMBARGOED) | Manager |
| GET | `/product-stocks/{id}` | Get a pre-order pool | Member, Clerk, Manager |
| POST | `/product-stocks/{id}/release` | Release a pool from embargo | Manager |
| GET | `/product-stocks/{id}/allocations` | List allocations drawn from a pool | Clerk, Manager |
| POST | `/products/{id}/inventory-items` | Create a physical unit (starts AVAILABLE) | Clerk, Manager |
| GET | `/inventory-items/{id}` | Get a physical unit | Member, Clerk, Manager |
| POST | `/pre-orders` | Create a pre-order (resolves allocation; OCC-guarded) | Member, Clerk, Manager |
| GET | `/pre-orders/{id}` | Get a pre-order | Member, Clerk, Manager |
| GET | `/pre-orders` | List pre-orders by member or pool | Member, Clerk, Manager |
| GET | `/pre-orders/{id}/allocations` | List allocations held by a pre-order | Member, Clerk, Manager |
| POST | `/pre-orders/{id}/payments` | Record a payment toward a pre-order | Member, Clerk, Manager |
| POST | `/pre-orders/{id}/fulfill` | Fulfill an allocated, fully-paid pre-order | Clerk, Manager |
| POST | `/pre-orders/{id}/cancel` | Cancel a pre-order (release unit, refund) | Member, Clerk, Manager |
| POST | `/trade-ins` | Submit a trade-in | Member, Clerk, Manager |
| GET | `/trade-ins/{id}` | Get a trade-in | Member, Clerk, Manager |
| GET | `/trade-ins` | List trade-ins by member or product | Member, Clerk, Manager |
| POST | `/trade-ins/{id}/grade` | Grade or re-grade a trade-in and make an offer | Clerk, Manager |
| POST | `/trade-ins/{id}/dispute` | Dispute the current offer | Member, Clerk, Manager |
| POST | `/trade-ins/{id}/accept` | Accept the offer and settle | Member, Clerk, Manager |
| POST | `/trade-ins/{id}/void` | Void a settled trade-in | Manager |
| POST | `/rentals` | Reserve a rental over a window | Member, Clerk, Manager |
| GET | `/rentals/{id}` | Get a rental | Member, Clerk, Manager |
| GET | `/rentals` | List rentals by member or item | Member, Clerk, Manager |
| POST | `/rentals/{id}/checkout` | Check out a reserved rental | Clerk, Manager |
| POST | `/rentals/{id}/return` | Return a checked-out rental | Clerk, Manager |
| POST | `/sales` | Ring up a point-of-sale sale | Clerk, Manager |
| POST | `/stations` | Create a gaming station | Manager |
| POST | `/tournaments` | Schedule a tournament on a station | Clerk, Manager |
| GET | `/tournaments/{id}` | Get a tournament | Member, Clerk, Manager |
| GET | `/tournaments` | List tournaments by station | Member, Clerk, Manager |
| POST | `/tournaments/{id}/register` | Register a member for a tournament | Member, Clerk, Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_NOT_AVAILABLE` | 409 |
| `ERR_ALLOCATION_NOT_READY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RENTAL_OVERLAP` | 409 |
| `ERR_STATION_DOUBLE_BOOKED` | 409 |
| `ERR_REGISTRATION_CLOSED` | 409 |
| `ERR_TOURNAMENT_FULL` | 409 |
| `ERR_ALREADY_REGISTERED` | 409 |
| `ERR_ONE_ACTIVE_PREORDER` | 409 |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 402 |
| `ERR_INSUFFICIENT_PAYMENT` | 402 |
| `ERR_PAGINATION_INVALID` | 400 |
