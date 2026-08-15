# Dairy DSD Route API — Product Requirements Document

## 1. Introduction

Direct-store-delivery (DSD) is the economic engine of a regional dairy: every morning a refrigerated truck leaves the depot with a load built from standing pars and last-minute orders, runs a fixed route of grocery and convenience stores, drops product, picks up empties, logs temperatures, and comes home with a stack of signed invoices and a cold-chain record that either survives scrutiny or does not. The Dairy DSD Route API is the system of record for that operation — from route setup and store onboarding through order generation, delivery, invoicing, returns, crate accounting, merchandising labor, driver settlement, and ultimately the sale of a route's territory to another distributor.

Two properties of the dairy business shape the design. First, regulated milk pricing: the per-unit price a store pays for regulated products is not set by the distributor but derived from a published Class I announcement, with a processor assessment, a hauling charge, and a diesel-index fuel surcharge layered on top — and because provisional announcements precede final ones, invoices can be repriced after the fact. Second, the cold chain: the refrigerated box must hold 40 degrees Fahrenheit or below, excursions are accumulated as a step function over time, and a confirmed breach cascades automatically into returns, credit memos, and invoice adjustments. Distributors, drivers, store receivers, market administrators, quality inspectors, and territory managers each act on the same data under strict segregation of duties; this document defines exactly what each of them may do, in what order, and with what arithmetic.

## 2. Global Specifications & System-Wide Principles

This section fixes the structural contract that every endpoint obeys: identity headers, response envelope, pagination, common resource properties, validation ordering, optimistic concurrency, monetary precision, and the two domain-wide disciplines (cold-chain bookkeeping and the crate ledger) that recur across workflows.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The declared role names are exactly `TerritoryManager`, `MarketAdministrator`, `DistributorOwner`, `RouteDriver`, `StoreReceiver`, and `QualityInspector`. A request whose headers are missing, or whose role value is not one of these names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not listed for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All GET endpoints are readable by every authenticated role; the read authorization is denoted `Any` in the endpoint table.

Three roles are **entity-backed**, meaning `X-User-ID` is a persisted resource id and ownership checks compare it against foreign keys on the target resource. When `X-User-Role` is `DistributorOwner`, `X-User-ID` is the `id` of the acting `Distributor`; the caller owns a resource when the resource's chain reaches that distributor — for a store, `store.route.distributor_id` must equal `X-User-ID`; for a trip, the trip's route's owning distributor; for a listing, the listing's `seller_distributor_id`; for a return, the owner of the route serving the return's store. When `X-User-Role` is `RouteDriver`, `X-User-ID` is the `id` of the acting `Driver`; for departure, completion, temperature readings, delivery, return creation, and merchandising, the trip's `driver_id` must equal `X-User-ID`; for crate pickup, which names no trip, `X-User-ID` must instead be the `id` of a persisted `Driver` whose `distributor_id` equals the store's route's owning distributor (§3.6). When `X-User-Role` is `StoreReceiver`, `X-User-ID` is the `id` of the acting `Store`; for payments and disputes, the resource's `store_id` must equal `X-User-ID`. A failed entity-backed ownership check is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The remaining roles are opaque. When `X-User-Role` is `TerritoryManager`, `MarketAdministrator`, or `QualityInspector`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server does not compare it to any resource's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — `Distributor`, `Route`, `Driver`, `Store`, `Product`, `StandingPar`, `PricingPeriod`, `PriceAnnouncement`, `TruckTrip`, `RouteOrder`, `Invoice`, `Return`, `CreditMemo`, `MerchandisingSession`, `RouteSaleListing` — carries a standard set of system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and an integer `version` that increments by one on every mutation. Any change to a resource — including a change to a computed field such as `crate_balance` or `loaded_cases` — refreshes `updated_at` and increments `version` on the mutated resource. Two event-log entities are the exception: `TemperatureReading` and `CrateTransaction` are immutable once created and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

The server runs on a **logical clock**, not wall-clock time. Before any test-driving call, the clock stands at exactly 2026-08-01T00:00:00Z. A `TerritoryManager` may advance it to a supplied `to_iso8601` instant — any valid ISO 8601 instant is accepted, with no requirement that it be later than the current value; the response reports the resulting `current_utc`, and the clock never falls back to wall-clock time afterward. All subsequent system timestamps — merchandising check-in and check-out, crate transaction service dates, reading acceptance windows, code-date arithmetic, and return day counts — read from this clock.

### 2.5. Nested Resource Retrieval and Validation Ordering

Paths that nest a sub-resource under a parent (for example, a standing par under a store, a temperature reading under a trip) validate path parameters **left to right**: the first identifier in the path that does not resolve to an existing resource determines the `404` error returned — a request aimed at a non-existent trip's readings fails with `ERR_TRIP_NOT_FOUND` before any reading-level rule is consulted. Body-referenced resources are resolved after the path, in the same existence phase.

When several checks could fail at once, the API applies a single global priority ladder, and a dual-failure request returns the error from the lowest priority number: (1) missing or invalid identity headers, producing `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) role not permitted on the endpoint, producing `ERR_INSUFFICIENT_PERMISSIONS`; (3) entity-backed ownership, producing `ERR_OWNERSHIP_MISMATCH`; (4) existence of every path- and body-referenced resource, producing the not-found error for the resource type in question — `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PAR_NOT_FOUND`, `ERR_PRICING_PERIOD_NOT_FOUND`, `ERR_ANNOUNCEMENT_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CREDIT_MEMO_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, or `ERR_SESSION_NOT_FOUND` (`ERR_PRICING_PERIOD_NOT_FOUND` also covers a delivery with regulated lines whose month has no announcement at all); (5) request well-formedness — required fields present, enums in-domain, numeric ranges valid, uniqueness respected — producing `ERR_INVALID_REQUEST`; (6) state-machine preconditions, producing the state family of errors (`ERR_ROUTE_NOT_ACTIVE`, `ERR_STORE_NOT_ACTIVE`, `ERR_TRIP_NOT_PLANNED`, `ERR_TRIP_NOT_DEPARTED`, `ERR_TRIP_NOT_COMPLETED`, `ERR_TRIP_NOT_IN_QA_REVIEW`, `ERR_ORDER_NOT_CONFIRMABLE`, `ERR_ORDER_NOT_CANCELLABLE`, `ERR_ORDER_NOT_DELIVERABLE`, `ERR_RETURN_NOT_REVIEWABLE`, `ERR_RETURN_NOT_DISPUTABLE`, `ERR_LISTING_NOT_OPEN_FOR_OFFER`, `ERR_LISTING_NOT_ACTIONABLE`, `ERR_LISTING_NOT_UNDER_CONTRACT`, `ERR_SESSION_NOT_OPEN`, `ERR_PERIOD_CLOSED`, `ERR_INVOICE_NOT_OPEN`, `ERR_INVOICE_NOT_VOIDABLE`, `ERR_CREDIT_MEMO_NOT_APPLICABLE`, `ERR_CREDIT_MEMO_NOT_VOIDABLE`, `ERR_READINGS_NOT_ACCEPTED`); (7) cold-chain and code safety (`ERR_COLD_CHAIN_PRECOOL_REQUIRED`, `ERR_OUT_OF_CODE_DELIVERY`, `ERR_PRODUCT_DISCONTINUED`); (8) temporal interval rules (`ERR_DOCK_WINDOW_CONFLICT`, `ERR_TRIP_WINDOW_CONFLICT`, `ERR_READING_OUT_OF_ORDER`); (9) capacity and structural constraints (`ERR_TRIP_CAPACITY_EXCEEDED`, `ERR_INSUFFICIENT_CRATE_BALANCE`, `ERR_SELF_DEALING`, `ERR_SESSION_CONFLICT`, `ERR_DELIVERY_QTY_EXCEEDS_ORDER`); (10) cross-referential coherence (`ERR_RETURN_PRODUCT_NOT_DELIVERED`, `ERR_RETURN_STORE_MISMATCH`, `ERR_RETURN_NOT_ELIGIBLE`); and (11) fiscal limits checked last (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_EXCEEDS_DUE`). Within a single state-machine transition, preconditions evaluate in the order the workflow narrative lists them, and the first failing precondition's error is the one returned. Well-formedness also covers rejecting unknown fields: any body field outside an endpoint's documented payload is `ERR_INVALID_REQUEST`.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency. Every such request must carry a non-optional expected-version field holding the client's last observed `version` of the parent entity; if another writer has advanced that version since the client last read it, the request is rejected.

- Creating a standing par for a store must carry `expected_store_version` matching the store's current `version`. Because a par upsert legitimately supersedes the prior active par for the same store and product, a client acting on a stale view of the store's par set is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412).
- Updating a store's configuration must carry `expected_store_version` matching the store's current `version`; changes to pull windows, credit limits, deposit rates, and merchandising terms are lost-update prone, and a stale basis is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412).
- Publishing a price announcement into a pricing period must carry `expected_pricing_period_version` matching the period's current `version`; because a publish supersedes the prior announcement of its kind — and a final announcement reprices open invoices — a stale basis is rejected with `ERR_STALE_PRICING_PERIOD_VERSION` (HTTP 412).

No other endpoint takes a version field. Endpoints not listed here must not require one. On the priority ladder of §2.5, the stale-version check evaluates after existence and well-formedness and before state-machine preconditions.

### 2.7. Monetary Values, Units, and Precision

All money is integer cents. Per-unit prices, however, carry fractional precision: the regulated milk unit price is computed to **3 decimal places** using round-half-up, while its intermediate milk-cost figure is kept at full precision and never rounded early. Line amounts, discounts, credits, commissions, and the weekly-average inside territory valuation are integer cents using round-half-up; subtotals and totals are exact integer sums and differences. `excursion_minutes` is the one non-monetary rounded quantity: 2 decimal places, round-half-up.

Temperatures are recorded in tenths of a degree Fahrenheit as integers (`temp_tenths_f`), so 385 means 38.5°F. Distances and weights matter because regulated milk is announced per hundredweight — one hundred pounds of milk — and each product's `weight_lbs_per_unit` converts the announced per-hundredweight price into a per-unit cost.

### 2.8. The Crate Ledger

Every store maintains a crate ledger, an append-only sequence of `CrateTransaction` events. A `DROP` is system-created at delivery and adds crates; a `PICKUP` records empties hauled back and subtracts crates; an `ADJUSTMENT` carries a signed, non-zero count that corrects the ledger in either direction. The store's `crate_balance` is the sum of all drops, minus the sum of all pickups, plus the sum of all signed adjustments, and it may never go negative: a pickup larger than the current balance is rejected with `ERR_INSUFFICIENT_CRATE_BALANCE` (HTTP 409), while a pickup exactly equal to the balance is allowed and leaves the balance at zero; likewise a negative adjustment may not drive the balance below zero and fails with the same error. The ledger is compensating — for any interval, the ending balance equals the starting balance plus drops minus pickups plus adjustments, so a drop of n followed later by a pickup of n leaves the balance unchanged. The store's `deposit_liability_cents` is always the current `crate_balance` multiplied by its `crate_deposit_cents`, and is recomputed whenever the balance moves.

### 2.9. Cold-Chain Bookkeeping

Each refrigerated trip accumulates `excursion_minutes`, a step-function measure over its `BOX`-zone temperature readings: while a reading's temperature holds above the excursion threshold of 40.0°F, every minute until the next reading accrues; `CAB`-zone readings are logged but never feed the excursion math. Two independent triggers set the trip's `cold_chain_breach` flag: cumulative accrual reaching at least 45.0 minutes (the boundary is inclusive), or any single `BOX` reading above 50.0°F — the instantaneous spike rule. A trip flagged with a breach cannot be reconciled directly; it must pass through quality review. The full reading-acceptance rules and the completion-time trailing accrual appear with the trip workflow in §3.4.

## 3. Business Logic & Workflows

This section walks the operation the way a day unfolds: standing data first, then pricing, then the truck run itself, then the money — invoicing, returns, credits, and settlement — and finally the meta-business of selling a route's territory.

### 3.1. Distributors, Routes, Stores, Drivers, and Products

A `TerritoryManager` registers each distributor with a business `name`, a state dairy `license_number` that must be unique across all distributors (a duplicate is rejected with `ERR_INVALID_REQUEST`), and `credit_terms_days`, the number of days a store may carry an open invoice, defaulting to 7 when omitted and required to be a non-negative integer when supplied.

Routes are the unit of territorial ownership. A `TerritoryManager` creates a route in `DRAFT` status by supplying the owning `distributor_id`, a unique `route_code` (duplicates are `ERR_INVALID_REQUEST`), a display `name`, the `service_weekdays` array drawn from the codes MON through SUN on which the route runs, and an optional `credit_price_basis` of `ORIGINAL` or `CURRENT`, defaulting to `ORIGINAL`, which selects how return credits are priced (see §3.6). A route's `distributor_id` is rewritten by exactly one operation: the territory-manager approval that closes a route sale. Activation moves a route from `DRAFT` to `ACTIVE`, and the same activation also serves a `SUSPENDED` route returning to service; activation from any other state fails with `ERR_ROUTE_NOT_ACTIVE`. Activation from `DRAFT` additionally requires the route to have at least one `ACTIVE` store — a draft route with no live store is not ready and the request fails with `ERR_ROUTE_NOT_ACTIVE`. Suspending moves an `ACTIVE` route to `SUSPENDED` (any other starting state, `ERR_ROUTE_NOT_ACTIVE`), and a suspended route blocks both order confirmation and par-based order generation with `ERR_ROUTE_NOT_ACTIVE`. Retirement moves an `ACTIVE` or `SUSPENDED` route to `RETIRED` — from any other state, `ERR_ROUTE_NOT_ACTIVE` — but only when no order on the route stands in `PLANNED` or `CONFIRMED` and no sale listing for the route stands in `DRAFT`, `LISTED`, `OFFER_PENDING`, or `UNDER_CONTRACT`; either blocker produces `ERR_ROUTE_HAS_OPEN_ORDERS`. Retirement cascades: every `ACTIVE` store on the route becomes `INACTIVE`, and every `PLANNED` order on those stores becomes `CANCELLED`, with each affected trip's `loaded_cases` recomputed as the sum over its remaining `CONFIRMED` orders. Because retirement is only reachable when no `PLANNED` or `CONFIRMED` orders exist, the order leg of the cascade can in practice never find a `CONFIRMED` order to touch.

A `DistributorOwner` hires drivers by supplying the employer `distributor_id` — which must equal the caller's `X-User-ID`, else `ERR_OWNERSHIP_MISMATCH` — along with the driver's `name` and `cdl_class`, one of `A` or `B`. Drivers are readable by all, and a driver's weekly settlement can be read by the owning `DistributorOwner` or by the driver themselves (see §3.7).

A `DistributorOwner` onboards a store onto one of its own routes with a unique `store_code` (duplicates, `ERR_INVALID_REQUEST`), a `name`, and optional policy fields, each with a default: `credit_limit_cents` defaulting to 0 caps the store's open receivables plus the estimated subtotal of a new order; `pull_window_days` defaulting to 4 is the pull-policy window for near-code product; `crate_deposit_cents` defaulting to 400 is the deposit liability per outstanding crate; `merchandising_rate_cents_per_min` defaulting to 0 is the store-billed rate for billable merchandising minutes; `free_merchandising_minutes` defaulting to 15 is the per-visit allowance before billing begins; and `dock_open_min` / `dock_close_min`, defaulting to 480 and 720 (08:00 and 12:00 as minutes from midnight local), define the store's default delivery dock window used by generated orders. Each of these policy fields must be a non-negative integer when supplied, at onboarding and in a patch alike. A new store starts `ACTIVE` with `crate_balance`, `open_ar_cents`, and `deposit_liability_cents` all at zero. Configuration changes arrive as a patch naming `expected_store_version` plus any subset of `credit_limit_cents`, `pull_window_days`, `crate_deposit_cents`, `merchandising_rate_cents_per_min`, `free_merchandising_minutes`, `dock_open_min`, and `dock_close_min`; a successful patch increments the store's `version` by one (see §2.6 for the stale-version rejection), and a patch that changes `crate_deposit_cents` also recomputes `deposit_liability_cents` as the current `crate_balance` times the new rate.

Deactivating a store moves it `ACTIVE` → `INACTIVE` and is refused from any other state with `ERR_STORE_NOT_ACTIVE`; it is also refused while any order for the store stands in `CONFIRMED`, with `ERR_STORE_HAS_CONFIRMED_ORDERS`. Deactivation cascades two levels deep: every `PLANNED` order for the store becomes `CANCELLED`, and each cancelled order releases its reserved cases, so the affected trips' `loaded_cases` recompute as the sum over remaining `CONFIRMED` orders. Reactivating a store requires the store to be `INACTIVE` (else `ERR_STORE_NOT_ACTIVE`) and its route to be `ACTIVE` (else `ERR_ROUTE_NOT_ACTIVE`).

Products are created by a `TerritoryManager` with a unique `sku` (duplicates, `ERR_INVALID_REQUEST`), a `name`, `units_per_case` (sellable units per case — the case count for any line is the quantity in units divided by `units_per_case`, rounded up), `shelf_life_days` from pack to code date, a `regulated` flag, and optional pricing fields: `weight_lbs_per_unit` defaulting to 8.6 (one gallon of milk weighs 8.6 pounds), `list_price_cents` defaulting to 0 as the flat per-unit price for non-regulated products, and `margin_cents_per_unit` defaulting to 0 as the distributor margin layered onto regulated products after the fuel surcharge. `units_per_case` must be a positive integer, `shelf_life_days` a non-negative integer, `weight_lbs_per_unit` a positive number, and `list_price_cents` and `margin_cents_per_unit` non-negative numbers; violations are `ERR_INVALID_REQUEST`. A product starts `ACTIVE`; discontinuing moves it to `DISCONTINUED` (from any other state, `ERR_PRODUCT_DISCONTINUED`), after which it is silently excluded from future generated order lines and rejected outright in new manual order lines with `ERR_PRODUCT_DISCONTINUED` (HTTP 409).

### 3.2. Standing Pars and Order Generation

Each store may maintain a **standing par** per product — the default order quantity by weekday. Creating a par for a store names the `product_id`, the OCC field `expected_store_version` (§2.6), and any subset of the weekday quantities `par_mon`, `par_tue`, `par_wed`, `par_thu`, `par_fri`, `par_sat`, and `par_sun`, each a non-negative integer defaulting to 0. No store-status gate applies: a par may be upserted for a store in any status. At most one par per store–product pair is `ACTIVE` at a time: a new par for a pair with an existing `ACTIVE` par supersedes it, moving the old one to `SUPERSEDED`, and the upsert increments the store's `version` by one. Pars are listed per store (with an optional `status` filter) and per product, and a single par is retrievable directly — for instance, to observe the `SUPERSEDED` status after an upsert.

When a `DistributorOwner` triggers order generation on a `PLANNED` trip, the system walks every `ACTIVE` store on the trip's route in store `created_at` ascending order. The trip's route must be `ACTIVE`, else `ERR_ROUTE_NOT_ACTIVE`, and the trip itself must be `PLANNED`, else `ERR_TRIP_NOT_PLANNED`. For each store, the generated lines come from that store's `ACTIVE` pars: a line `{product_id, quantity_units}` is included when the par quantity for the service date's weekday is greater than zero and the product is `ACTIVE`; `DISCONTINUED` products are silently excluded. A store with no qualifying lines is skipped and recorded in the response's `skipped_store_ids`. A store that already has an order on this trip in any `fulfillment_status` except `CANCELLED` is skipped the same way, which makes re-running generation idempotent. If adding the store's generated cases would push the trip's reserved `loaded_cases` beyond its `case_capacity`, the store is skipped and likewise recorded in `skipped_store_ids`. Otherwise the system creates an order with `source` = `PAR_GENERATED`, `fulfillment_status` = `PLANNED`, `payment_status` = `UNINVOICED`, and a delivery window built from the service date plus the store's default `dock_open_min` and `dock_close_min`; the trip's `loaded_cases` grows by the generated case count. Generated lines carry only `product_id` and `quantity_units`; each line gains its case count at confirmation. The generation response reports `created_count`, `created_order_ids`, and `skipped_store_ids`.

### 3.3. Milk Pricing: Periods, Announcements, and the Regulated Unit Price

Milk pricing runs on monthly cycles. A `MarketAdministrator` creates a `PricingPeriod` for a `month` in `YYYY-MM` form, unique across periods (a duplicate is `ERR_INVALID_REQUEST`); the period starts `OPEN`. Within an open period the administrator publishes `PriceAnnouncement`s, each with a `kind` of `PROVISIONAL` or `FINAL`, a `class_i_base_cents_per_cwt` (the announced Class I base price per hundredweight), a `processor_assessment_cents_per_cwt`, a `hauling_cents_per_cwt`, and a `diesel_index_cents` (the diesel price index in cents per gallon that selects the fuel surcharge tier); all four of these monetary fields must be non-negative integers. Every publish must carry `expected_pricing_period_version` (§2.6); a successful publish increments the period's `version` by one. At most one announcement of each kind is `ACTIVE` within a period: publishing a new announcement of a kind supersedes the prior `ACTIVE` announcement of that kind — the prior one moves to `SUPERSEDED`, the new one's `supersedes_announcement_id` records the prior one's id (or null when there was none), and the period's `current_provisional_id` or `current_final_id` repoints to the new announcement. These two period fields are computed: each holds the id of the currently `ACTIVE` announcement of its kind, or null when none exists. Announcements are listable per period (with an optional `kind` filter) and globally with `pricing_period_id` or `supersedes_announcement_id` filters. Closing a period requires it to be `OPEN` and to have an `ACTIVE` `FINAL` announcement — both failures surface as `ERR_PERIOD_CLOSED` — and a closed period accepts no further announcements (publishing into one is likewise `ERR_PERIOD_CLOSED`).

The **regulated unit price** is computed at delivery time, per delivered line whose product is regulated, and snapshotted onto the line as `unit_price_cents`. The announcement consulted belongs to the pricing period of the order's invoice month: the `ACTIVE` `FINAL` announcement if one exists at delivery time, otherwise the `ACTIVE` `PROVISIONAL` one; if neither exists and at least one delivered line's product is regulated, the delivery fails with `ERR_PRICING_PERIOD_NOT_FOUND`, while a delivery whose lines are all non-regulated consults no announcement and never fails for its absence. The milk cost per unit is the sum of `class_i_base_cents_per_cwt`, `processor_assessment_cents_per_cwt`, and `hauling_cents_per_cwt`, multiplied by the product's `weight_lbs_per_unit` and divided by 100 (one hundredweight is 100 pounds); this intermediate figure is kept at full precision and never rounded. The fuel surcharge rate is tiered on the announcement's `diesel_index_cents`: below 300 cents per gallon there is no surcharge; from 300 up to but not including 400 the rate is 1.5 percent — 300 exactly is surcharged; from 400 up to but not including 500 the rate is 3.0 percent — 400 exactly takes 3.0 percent; at 500 or above the rate is 4.5 percent. The regulated unit price is then the milk cost multiplied by one plus the surcharge rate, plus the product's `margin_cents_per_unit`, rounded half-up to 3 decimal places. A non-regulated product's `unit_price_cents` is simply its `list_price_cents`. These two variants matter downstream: an invoice priced off a provisional announcement carries `pricing_basis` = `PROVISIONAL` and is subject to true-up repricing when the final announcement lands; an invoice priced off a final announcement carries `pricing_basis` = `FINAL` and is never repriced.

### 3.4. The Truck Run: Trips, Temperatures, Orders, and Delivery

A `DistributorOwner` plans a `TruckTrip` by naming the `route_id`, the `driver_id` (who must belong to the route's owning distributor), the `service_date` in `YYYY-MM-DD` form, the refrigerated `truck_plate`, the `case_capacity` in cases as a positive integer, and the planned window `planned_depart_at` to `planned_return_at` in UTC — the return must be strictly later than the departure, else `ERR_INVALID_REQUEST`. Planning applies no route-status gate; a trip may be planned on a route in any status. A driver may not be double-booked: if the driver already holds a non-`CANCELLED` trip whose half-open window from `planned_depart_at` up to but not including `planned_return_at` overlaps the new trip's window, creation fails with `ERR_TRIP_WINDOW_CONFLICT`; because the interval is half-open, back-to-back trips are allowed. A trip starts `PLANNED` with `excursion_minutes` 0, `cold_chain_breach` false, `loaded_cases` 0, and `delivered_cases` 0.

While a trip is `PLANNED` or `DEPARTED`, the assigned `RouteDriver` appends temperature readings; a reading attempted in any other trip state is rejected with `ERR_READINGS_NOT_ACCEPTED`. Each reading carries `recorded_at` (a UTC timestamp), `temp_tenths_f`, and a `zone` of `CAB` or `BOX`. The `recorded_at` must be strictly greater than the previous reading's `recorded_at` on the same trip and no later than the current logical clock; violations are `ERR_READING_OUT_OF_ORDER`. Every accepted reading recomputes the trip's `excursion_minutes` and `cold_chain_breach` per §2.9: considering only `BOX` readings in `recorded_at` ascending order, each reading above 40.0°F (that is, `temp_tenths_f` strictly greater than 400) accrues the interval until the next reading; the accrual uses left-closed intervals so the above-threshold reading's own instant starts its interval. The breach flag is set when cumulative `excursion_minutes` reaches at least 45.0 — the boundary is inclusive — or when any single `BOX` reading exceeds 50.0°F (strictly greater than 500 tenths). Only `BOX` readings feed this math; `CAB` readings are inert.

Departure is the driver's declaration that the truck is rolling. The trip must be `PLANNED` (else `ERR_TRIP_NOT_PLANNED`) and the caller must be the trip's driver (else `ERR_OWNERSHIP_MISMATCH`). Two further gates apply: the **pre-cool check** requires at least one `BOX`-zone reading at or below 40.0°F recorded while the trip was `PLANNED` — without it, departure fails with `ERR_COLD_CHAIN_PRECOOL_REQUIRED` (HTTP 409) — and every order on the trip must already be `CONFIRMED` or `CANCELLED`, because a `PLANNED` order blocks departure with `ERR_ORDER_NOT_CONFIRMABLE`. Departure moves the trip `PLANNED` → `DEPARTED`.

Orders come in two flavors. A **manual order** is created by a `DistributorOwner` naming `store_id`, `trip_id`, an array of `lines` each shaped `{product_id, quantity_units}`, and the dock appointment `delivery_window_start` to `delivery_window_end` in UTC — the end must be strictly after the start, quantities must be positive, and the lines' `product_id` values must be distinct, all else `ERR_INVALID_REQUEST`. The store must be `ACTIVE`, the trip must be `PLANNED` and must serve the store's route on the order's service date. At creation each line gains a case count equal to its `quantity_units` divided by the product's `units_per_case`, rounded up, and the trip's `loaded_cases` immediately grows by the total cases — this is a reservation only, and capacity is enforced at confirmation, never at creation. A manual order is born with `source` = `MANUAL`, `fulfillment_status` = `PLANNED`, and `payment_status` = `UNINVOICED`; its `service_date` is copied from the trip. A line naming a `DISCONTINUED` product is rejected with `ERR_PRODUCT_DISCONTINUED`.

Confirmation is the owner's commitment and runs a battery of checks. The order must be `PLANNED` (else `ERR_ORDER_NOT_CONFIRMABLE`), its store `ACTIVE` (else `ERR_STORE_NOT_ACTIVE`), the store's route `ACTIVE` (else `ERR_ROUTE_NOT_ACTIVE`), and the trip still `PLANNED` (else `ERR_TRIP_NOT_PLANNED`). The **dock buffer** rule then rejects the confirmation with `ERR_DOCK_WINDOW_CONFLICT` when another order for the same store and service date in `CONFIRMED` or `DELIVERED` has a window whose start or end falls within 15 minutes of this window on either side; a gap of exactly 15 minutes equals the buffer and is allowed — only a strictly smaller gap, or an overlap, conflicts. **Capacity re-validation** compares the trip's `loaded_cases` — which by then includes this order's reservation among all `PLANNED` and `CONFIRMED` reservations — against `case_capacity`, and rejects with `ERR_TRIP_CAPACITY_EXCEEDED` when the load would exceed capacity. Last, the **credit check** adds the store's `open_ar_cents` to the order's estimated subtotal at current prices — computed per line as `quantity_units` times the current §3.3 unit price, rounded half-up to integer cents and summed pre-discount, with a regulated line pricing at 0 when no announcement exists for the service month — and rejects with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) only when the sum is strictly greater than `credit_limit_cents` — equality passes. Confirmation moves the order to `CONFIRMED`; its cases were already reserved at creation.

An order may be cancelled by the owner from `PLANNED` or `CONFIRMED` — from any other state, `ERR_ORDER_NOT_CANCELLABLE`. Cancelling a `CONFIRMED` order releases its cases: the trip's `loaded_cases` drops by the order's case count. Cancelling a `PLANNED` order likewise moves it to `CANCELLED` and releases its reservation.

Delivery is the driver's act on a `CONFIRMED` order. The order must be `CONFIRMED` (else `ERR_ORDER_NOT_DELIVERABLE`), the trip must be `DEPARTED` (else `ERR_TRIP_NOT_DEPARTED`), and the caller must be the trip's driver (else `ERR_OWNERSHIP_MISMATCH`). The payload's `delivered_lines` must cover every ordered line exactly once, with each line's `delivered_units` between zero and its `quantity_units` inclusive — an over-delivery, a missing line, or a duplicated line fails with `ERR_DELIVERY_QTY_EXCEEDS_ORDER` (HTTP 422). Every delivered line's `scanned_code_date` must be on or after the order's `service_date`: delivering out-of-code product is refused with `ERR_OUT_OF_CODE_DELIVERY` (HTTP 422). On success the order moves to `DELIVERED`; each line gains `delivered_units`, `scanned_code_date`, the snapshotted `unit_price_cents` from §3.3, a `line_amount_cents` computed as `delivered_units` times `unit_price_cents` rounded half-up to integer cents — per-line rounding is pinned, and summing raw products then rounding once at invoice level is forbidden because it produces different cents — and `cold_chain_flag` initialized to false. A line delivered with zero units contributes zero. The trip's counters swing: `loaded_cases` drops by the order's ordered cases while `delivered_cases` grows by the delivered case count (per delivered line, `delivered_units` divided by `units_per_case`, rounded up). Three further creations happen atomically with delivery. First, the order's `Invoice` is created one-to-one: its `store_id` is copied from the order, its `invoice_month` is the `YYYY-MM` of the service date, its `pricing_basis` is `FINAL` when that period has an `ACTIVE` `FINAL` announcement at delivery and `PROVISIONAL` otherwise, and its `status` starts `OPEN`; the order's `payment_status` moves to `INVOICED`. Second, a `CrateTransaction` of kind `DROP` is system-created for the delivered case count, increasing the store's `crate_balance` by that count and recomputing `deposit_liability_cents`. Third, the store's `open_ar_cents` — the sum of `amount_due_cents` over its `OPEN` invoices — is recomputed. The order's `subtotal_cents`, initialized to 0 at creation, is set to the delivered subtotal (a later true-up refreshes it); an invoice whose `amount_due_cents` is zero at creation starts immediately `SETTLED`, with its order's `payment_status` moving straight to `PAID`; and the crate `DROP` is recorded even when the delivered case count is zero.

The trip itself completes when every order on it is `DELIVERED` or `CANCELLED`: the trip must be `DEPARTED` (else `ERR_TRIP_NOT_DEPARTED`), the caller must be its driver, and any order in any other state blocks completion with `ERR_ORDER_NOT_DELIVERABLE`. Completion finalizes the cold-chain record: any trailing above-threshold `BOX` reading accrues excursion time up to the completion timestamp (the current logical clock), and `cold_chain_breach` is recomputed one final time on the same two triggers — at least 45.0 cumulative minutes, or any single `BOX` reading above 50.0°F. After completion, a `DistributorOwner` may reconcile the trip directly when `cold_chain_breach` is false, moving it `COMPLETED` → `RECONCILED`; attempting reconciliation from any other state, or when the flag is true, fails with `ERR_TRIP_NOT_COMPLETED` — a breached trip must instead go through QA. A `QualityInspector` opens that review on a `COMPLETED` trip whose flag is true, moving it to `QA_REVIEW` (any other state, or a clean trip, is `ERR_TRIP_NOT_COMPLETED`). A planned trip can also be cancelled outright by the owner — the trip must be `PLANNED` (else `ERR_TRIP_NOT_PLANNED`) and must hold no `CONFIRMED` order (else `ERR_ORDER_NOT_CANCELLABLE`) — which moves it to `CANCELLED` and cancels every `PLANNED` order on it.

Adjudication closes QA. The inspector submits a `verdict` of `CLEAR` or `CONFIRM_BREACH`; any other value is `ERR_INVALID_REQUEST`, and the trip must be in `QA_REVIEW` (else `ERR_TRIP_NOT_IN_QA_REVIEW`). A `CLEAR` verdict moves the trip to `RECONCILED`, resets `cold_chain_breach` to false, and fires no order or return cascade. A `CONFIRM_BREACH` verdict moves the trip to `BREACH_CONFIRMED` and fires a five-level cascade. First, every order on the trip with `fulfillment_status` `DELIVERED` has every line's `cold_chain_flag` set to true. Second, for each flagged order line, the system creates a `Return` with `reason_code` `COLD_CHAIN`, `quantity_units` equal to the line's `delivered_units`, the line's `scanned_code_date`, a `credit_pct` of 1.0, and `status` immediately `APPROVED`. Third, each such approved return creates a `CreditMemo` for its `credit_amount_cents` in `ISSUED` status. Fourth, each memo auto-applies to its own order's invoice when that invoice is still `OPEN` — otherwise to the store's oldest `OPEN` invoice per §3.6 — increasing the invoice's `credits_applied_cents` by the memo amount, recomputing `amount_due_cents`, settling the invoice if the due reaches exactly zero, and moving the memo to `PARTIALLY_APPLIED` or `APPLIED` as its remaining balance dictates. Fifth, each affected order's `payment_status` is re-derived from its invoice, moving `INVOICED` → `PARTIALLY_PAID` or `PAID`.

### 3.5. Invoicing and Payments

An invoice aggregates its order's delivered lines: `subtotal_cents` is the exact integer sum of the per-line `line_amount_cents` values, each already rounded half-up to integer cents at delivery (§3.4). The **volume discount** is tiered on the pre-discount `subtotal_cents` — never on the post-discount total, which would make the total depend on itself: a subtotal below 200,000 cents earns no discount; from 200,000 up to but not including 500,000 cents the rate is 1.5 percent — 200,000 exactly earns the 1.5 percent rate; at 500,000 cents or above the rate is 2.5 percent — 500,000 exactly takes 2.5 percent. The `discount_cents` is the subtotal times the rate, rounded half-up to integer cents, and `total_cents` is the subtotal minus the discount. The pre-discount keying has a real consequence: a subtotal of exactly 500,000 yields a total of 487,500, which sits below the 500,000 tier floor, yet the 2.5 percent rate still applies because the tier was selected before the discount. The invoice's `amount_due_cents` is its `total_cents` minus `credits_applied_cents` minus `payments_applied_cents`; `credits_applied_cents` and `payments_applied_cents` both start at zero, as does `true_up_delta_cents`. When payments, credits, or a true-up drive `amount_due_cents` to exactly zero, the invoice auto-settles to `SETTLED` and its order's `payment_status` becomes `PAID`.

The **final-announcement true-up** reprices provisional invoices. When a `FINAL` announcement is published, the system walks every invoice whose `invoice_month` equals the period's month, whose `pricing_basis` is `PROVISIONAL`, and whose `status` is `OPEN`, in invoice `created_at` ascending order. Each such invoice is recomputed line by line with the final announcement's figures per §3.3, re-rounded per the pinned line rounding, and re-discounted per the volume tiers — the repricing rewrites the order's delivered lines (`unit_price_cents` and `line_amount_cents`) and the order's `subtotal_cents`; the `true_up_delta_cents` records the new total minus the old total (which may be zero); the `amount_due_cents` becomes the new total minus existing credits and payments; an invoice driven to exactly zero settles and flips its order's `payment_status` to `PAID`; and the invoice's `pricing_basis` flips to `FINAL`. Invoices already `SETTLED` or `VOID` are not repriced — there is no retroactive reopening.

A `StoreReceiver` pays down an `OPEN` invoice by submitting an `amount_cents`; the invoice must be `OPEN` (else `ERR_INVOICE_NOT_OPEN`), the amount must be positive, and an amount greater than the invoice's `amount_due_cents` is rejected with `ERR_PAYMENT_EXCEEDS_DUE` (HTTP 402) — fiscal checks run last on the priority ladder. A recorded payment increases `payments_applied_cents` by the amount, recomputes `amount_due_cents`, settles the invoice at exactly zero (flipping the order's `payment_status` to `PAID`; a partial payment moves it to `PARTIALLY_PAID`), and recomputes the store's `open_ar_cents`. A `TerritoryManager` may void an `OPEN` invoice, but only while both `payments_applied_cents` and `credits_applied_cents` are zero — otherwise `ERR_INVOICE_NOT_VOIDABLE`; from a non-`OPEN` state the same error applies. Voiding moves the invoice to `VOID`, reverts its order's `payment_status` to `UNINVOICED`, and recomputes the store's `open_ar_cents`.

### 3.6. Returns, Credit Memos, and Crate Backhaul

A return begins when the route's driver — the caller must be the driver of the order's trip, else `ERR_OWNERSHIP_MISMATCH` — scans product back, naming the `order_id`, the `store_id` context, the `pickup_trip_id` of the trip physically collecting the product on its backhaul leg, the `product_id`, the `quantity_units` as a positive integer, a `reason_code`, and the `scanned_code_date` off the product in `YYYY-MM-DD` form. The order must be `DELIVERED`; the named product must appear among the order's delivered lines, and cumulative returned units for that product may not exceed what was delivered — returns in `REJECTED` do not count toward the cumulative total — violations are `ERR_RETURN_PRODUCT_NOT_DELIVERED` (HTTP 422). The caller-supplied store context must match the order's store, else `ERR_RETURN_STORE_MISMATCH` (HTTP 422). Eligibility turns on the code date: the return's `days_to_expiry_at_scan` is the `scanned_code_date` minus the current clock date in days — negative means out of code. An `OUT_OF_CODE` return requires `days_to_expiry_at_scan` below zero; a `PULL_POLICY` return requires it to lie within the store's pull window — at least zero and at most `pull_window_days`, both bounds inclusive; a `DAMAGED` return accepts any value; and `COLD_CHAIN` is system-created only — a manual attempt names it and is rejected with `ERR_RETURN_NOT_ELIGIBLE` (HTTP 422), as is any eligibility window miss. The `credit_pct` follows the reason: `OUT_OF_CODE` credits in full at 1.0, `PULL_POLICY` in full at 1.0, `DAMAGED` at half, 0.5, and `COLD_CHAIN` in full at 1.0. The `unit_credit_cents` depends on the serving route's `credit_price_basis`: under `ORIGINAL`, the credit is priced at the delivered line's snapshotted `unit_price_cents` — what the store actually paid; under `CURRENT`, it is priced as of the scan date — for a regulated product, the announcement of the scan month applied through the same regulated price formula (when no announcement exists for the scan month, the return fails with `ERR_PRICING_PERIOD_NOT_FOUND`); for a non-regulated product, its `list_price_cents`. The two bases diverge whenever the price moved between delivery and scan. The `credit_amount_cents` is the quantity times the unit credit times the credit percentage, rounded half-up to integer cents, with rounding applied only to the final product. A new return starts `UNDER_REVIEW` with all four computed fields — `days_to_expiry_at_scan`, `credit_pct`, `unit_credit_cents`, `credit_amount_cents` — populated.

Review belongs to the owning `DistributorOwner` — the caller must own the route serving the return's store, else `ERR_OWNERSHIP_MISMATCH`. Approval is defined from `UNDER_REVIEW` or `DISPUTED` (any other state, `ERR_RETURN_NOT_REVIEWABLE`) and runs two steps atomically: the return moves to `APPROVED` and then, immediately and by system action, to `CREDITED`. That second step creates a `CreditMemo` for the return's `credit_amount_cents` in `ISSUED` status and auto-applies it: the target is the return's own order invoice if that invoice is still `OPEN`, otherwise the store's oldest `OPEN` invoice by `created_at` ascending; when no `OPEN` invoice exists for the store at all, the memo remains `ISSUED` and unapplied. The application is the smaller of the memo's `remaining_cents` and the invoice's `amount_due_cents`. The invoice's `credits_applied_cents` and `amount_due_cents` recompute, the invoice settles if the due reaches exactly zero, the order's `payment_status` is re-derived, and the store's `open_ar_cents` recomputes. Rejection, likewise from `UNDER_REVIEW` or `DISPUTED` (else `ERR_RETURN_NOT_REVIEWABLE`), moves the return to `REJECTED` and creates no credit memo. The store's receiver — whose `X-User-ID` must equal the return's `store_id`, else `ERR_OWNERSHIP_MISMATCH` — may dispute a `REJECTED` return (from any other state, `ERR_RETURN_NOT_DISPUTABLE`), cycling it back to `DISPUTED` and into review again.

A credit memo tracks `amount_cents` (copied from its source return's `credit_amount_cents`), `applied_cents` starting at zero, and `remaining_cents` equal to the amount minus what's been applied. Its `return_id` names the source return and its `store_id` is copied from that return; its `invoice_id` names the invoice the memo is currently applied to, or null. Beyond the automatic application at approval time, a `DistributorOwner` may apply a memo's remaining balance to a chosen invoice by naming `invoice_id`: the memo must be `ISSUED` or `PARTIALLY_APPLIED` (else `ERR_CREDIT_MEMO_NOT_APPLICABLE`), and the target invoice must exist, belong to the memo's store, and be `OPEN` (else `ERR_INVOICE_NOT_OPEN`). The applied amount is the smaller of the memo's `remaining_cents` and the invoice's `amount_due_cents`; the memo's `applied_cents` grows by it and its `invoice_id` is set; the invoice's `credits_applied_cents` grows and its `amount_due_cents` recomputes, settling at exactly zero with the order's `payment_status` re-derived. A memo whose remaining balance reaches zero lands `APPLIED`; a partial application lands it `PARTIALLY_APPLIED`. A `TerritoryManager` may void a memo in `ISSUED` or `PARTIALLY_APPLIED` (else `ERR_CREDIT_MEMO_NOT_VOIDABLE`): voiding compensates every application the memo ever made — each affected invoice's `credits_applied_cents` is reduced by the amount that memo had applied to it and its `amount_due_cents` increased accordingly, a `SETTLED` invoice reopens to `OPEN`, affected orders' `payment_status` re-derive, the memo becomes `VOID` with its `applied_cents` reset to zero, its `remaining_cents` restored to the full amount, and its `invoice_id` cleared to null, and the store's `open_ar_cents` recomputes.

Crate backhaul is recorded against a store. A `PICKUP` — recorded by a `RouteDriver` whose `X-User-ID` is the `id` of a persisted `Driver` employed by the store's route owner, that is, the driver's `distributor_id` must equal the route's `distributor_id` — carries a positive `crate_count`; an `ADJUSTMENT`, recordable by a `DistributorOwner` only, carries a signed non-zero `crate_count` where a negative value reduces the balance; either may carry a free-text `note`. Submitting kind `DROP` is rejected as system-only with `ERR_INVALID_REQUEST` — drops exist only as delivery side effects. Each transaction's `service_date` is the current clock date. Balance arithmetic and the non-negativity floor follow §2.8, and each recorded transaction increments the store's `version` by one.

### 3.7. Store-Door Merchandising and Driver Settlement

A driver performs store-door merchandising — facing shelves, rotating stock, building displays — as a timed session. Checking in on a trip names the `store_id`, which must be a store on the trip's route; the caller must be the trip's driver, and a driver may hold at most one `OPEN` session at a time — a second check-in while one is open fails with `ERR_SESSION_CONFLICT`. No trip-state gate applies to check-in. The session records `check_in_at` from the server clock, starts `OPEN`, and copies `driver_id` from the trip; `check_out_at`, `minutes`, `billable_minutes`, and `labor_charge_cents` remain null while the session is `OPEN`. Closing a session requires it to be `OPEN` (else `ERR_SESSION_NOT_OPEN`), requires the caller to be the session's driver (else `ERR_OWNERSHIP_MISMATCH`), and requires the current clock to be later than `check_in_at` (else `ERR_INVALID_REQUEST`). Closing stamps `check_out_at` from the clock, computes `minutes` as the elapsed seconds between check-in and check-out divided by 60 and rounded up — the result must be greater than zero — then derives `billable_minutes` as the greater of zero and `minutes` minus the store's `free_merchandising_minutes`, and `labor_charge_cents` as `billable_minutes` times the store's `merchandising_rate_cents_per_min` — the store's merchandising terms are read at close time, not snapshotted at check-in. The session lands `CLOSED`.

A driver's **weekly settlement** is a computed read for a `week_start` date supplied as a query parameter — a missing or malformed `week_start` is `ERR_INVALID_REQUEST` — covering the half-open window from `week_start` 00:00Z up to but not including seven days later, matched on service date or check-in date. Gross sales, `gross_sales_cents`, are the sum of `line_amount_cents` over lines of `DELIVERED` orders on trips this driver drove with service dates in the window. Credits, `credits_cents`, are the sum of `credit_amount_cents` over returns in `APPROVED` or `CREDITED` status whose order's service date is in the window and whose order's trip driver is this driver — evaluated as of read time, so a return approved later changes historical settlements. Net sales, `net_sales_cents`, are gross minus credits. The commission tier is keyed on net sales — never on any post-commission figure, which would make the commission depend on itself: below 500,000 cents the rate is 22 percent; from 500,000 up to and including 1,200,000 cents the rate is 24 percent — 500,000 exactly takes 24 percent; above 1,200,000 cents the rate is 26 percent. The `commission_cents` is net sales times the rate, rounded half-up to integer cents. Labor, `labor_minutes`, sums `minutes` over this driver's `CLOSED` merchandising sessions with check-in dates in the window — `OPEN` sessions are excluded — and `driver_labor_cents` is the labor minutes times 50 cents per minute. The final `settlement_cents` is the commission plus the driver labor. The read returns `gross_sales_cents`, `credits_cents`, `net_sales_cents`, `commission_rate`, `commission_cents`, `labor_minutes`, `driver_labor_cents`, and `settlement_cents`; it is available to the owning `DistributorOwner` and to the driver for their own record.

### 3.8. Route Sale and Territory Transfer

A distributor may sell a route's territory. The seller — a `DistributorOwner` acting for the route's owner — creates a `RouteSaleListing` naming the `route_id` and an `asking_price_cents`, a non-negative integer, with an optional `trailing_weeks` valuation window, a positive integer defaulting to 12. The route must be owned by the caller — else `ERR_OWNERSHIP_MISMATCH` — and must not already sit on a non-terminal listing, which is `ERR_INVALID_REQUEST`. The listing starts `DRAFT` with `seller_distributor_id` fixed to the caller's `X-User-ID`.

Publishing a `DRAFT` listing moves it to `LISTED` and snapshots `territory_value_cents` at that moment. The valuation window covers service dates strictly after the clock date minus seven times `trailing_weeks` days, up to and including the clock date — the lower bound exclusive, the upper bound inclusive. Window net sales are the sum of `line_amount_cents` over the route's `DELIVERED` orders in the window minus the sum of `credit_amount_cents` over returns in `APPROVED` or `CREDITED` status whose orders are on this route with service dates in the window. The average weekly figure is the window net sales divided by `trailing_weeks`, rounded half-up to integer cents, and `territory_value_cents` is ten times that average. Publishing requires the listing to be `DRAFT` (else `ERR_LISTING_NOT_ACTIONABLE`), the caller to be the seller (else `ERR_OWNERSHIP_MISMATCH`), and the route to be `ACTIVE` (else `ERR_ROUTE_NOT_ACTIVE`).

A buyer `DistributorOwner` submits an offer on a `LISTED` listing by naming `buyer_distributor_id` — which must equal the caller's `X-User-ID`, else `ERR_OWNERSHIP_MISMATCH` — and `offer_price_cents`. The buyer may not be the seller, else `ERR_SELF_DEALING` (HTTP 422); the listing must be `LISTED`, else `ERR_LISTING_NOT_OPEN_FOR_OFFER`; and the route must still be `ACTIVE`, else `ERR_ROUTE_NOT_ACTIVE`. The listing moves to `OFFER_PENDING` with the buyer fields recorded. The seller then accepts the offer — moving the listing `OFFER_PENDING` → `UNDER_CONTRACT` — or rejects it, moving it back to `LISTED` with `buyer_distributor_id` and `offer_price_cents` cleared so the cycle can repeat; both actions require the listing to be `OFFER_PENDING` (else `ERR_LISTING_NOT_ACTIONABLE`) and the caller to be the seller (else `ERR_OWNERSHIP_MISMATCH`). The seller may also withdraw from `LISTED` or `OFFER_PENDING` (else `ERR_LISTING_NOT_ACTIONABLE`), landing the listing `WITHDRAWN` with buyer fields cleared.

Closing the sale belongs to the `TerritoryManager`: approving the transfer requires the listing to be `UNDER_CONTRACT` (else `ERR_LISTING_NOT_UNDER_CONTRACT`) and requires no order on the route in `PLANNED` or `CONFIRMED` (else `ERR_ROUTE_HAS_OPEN_ORDERS`). Approval moves the listing to `CLOSED` and rewrites the route's `distributor_id` to the buyer, incrementing the route's `version` and refreshing its `updated_at` — territory ownership has changed hands.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK` — with one exception: recording a payment returns `201 Created` carrying the updated invoice. The API is mounted under `/dairy`, with the logical-clock control at the root level. The table below is a summary only — request payloads, computed fields, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical server clock (startup default 2026-08-01T00:00:00Z) | TerritoryManager |
| POST | `/dairy/distributors` | Register a distributor | TerritoryManager |
| GET | `/dairy/distributors/{id}` | Get a distributor | Any |
| GET | `/dairy/distributors/{id}/routes` | List routes owned by a distributor | Any |
| GET | `/dairy/distributors/{id}/drivers` | List drivers of a distributor | Any |
| POST | `/dairy/routes` | Create a route in DRAFT | TerritoryManager |
| GET | `/dairy/routes/{id}` | Get a route | Any |
| GET | `/dairy/routes/{id}/stores` | List stores on a route | Any |
| POST | `/dairy/routes/{id}/activate` | Activate a DRAFT or SUSPENDED route | TerritoryManager |
| POST | `/dairy/routes/{id}/suspend` | Suspend an ACTIVE route | TerritoryManager |
| POST | `/dairy/routes/{id}/retire` | Retire a route; cascades stores to INACTIVE and PLANNED orders to CANCELLED | TerritoryManager |
| POST | `/dairy/drivers` | Hire a driver for the caller's distributorship | DistributorOwner |
| GET | `/dairy/drivers/{id}` | Get a driver | Any |
| GET | `/dairy/drivers/{id}/weekly-settlement` | Computed weekly settlement for a driver | DistributorOwner, RouteDriver |
| POST | `/dairy/stores` | Onboard a store onto a route owned by the caller | DistributorOwner |
| GET | `/dairy/stores/{id}` | Get a store | Any |
| PATCH | `/dairy/stores/{id}` | Update store configuration; OCC-guarded | DistributorOwner |
| POST | `/dairy/stores/{id}/deactivate` | Deactivate a store; cancels its PLANNED orders and releases trip capacity | DistributorOwner |
| POST | `/dairy/stores/{id}/reactivate` | Reactivate an INACTIVE store | DistributorOwner |
| POST | `/dairy/products` | Create a product | TerritoryManager |
| GET | `/dairy/products/{id}` | Get a product | Any |
| POST | `/dairy/products/{id}/discontinue` | Discontinue a product | TerritoryManager |
| POST | `/dairy/stores/{id}/standing-pars` | Upsert the standing par for a store–product pair; supersedes the prior ACTIVE par; OCC-guarded | DistributorOwner |
| GET | `/dairy/stores/{id}/standing-pars` | List standing pars of a store | Any |
| GET | `/dairy/products/{id}/standing-pars` | List standing pars referencing a product | Any |
| GET | `/dairy/standing-pars/{id}` | Get a single standing par | Any |
| POST | `/dairy/pricing-periods` | Create a monthly pricing period | MarketAdministrator |
| GET | `/dairy/pricing-periods/{id}` | Get a pricing period | Any |
| POST | `/dairy/pricing-periods/{id}/close` | Close a period (requires an ACTIVE FINAL announcement) | MarketAdministrator |
| POST | `/dairy/pricing-periods/{id}/announcements` | Publish a PROVISIONAL or FINAL announcement; supersedes the prior ACTIVE of the same kind; FINAL triggers true-up repricing; OCC-guarded | MarketAdministrator |
| GET | `/dairy/pricing-periods/{id}/announcements` | List announcements of a period | Any |
| GET | `/dairy/price-announcements/{id}` | Get a single announcement | Any |
| GET | `/dairy/price-announcements` | List announcements filtered by period or supersession link | Any |
| POST | `/dairy/trips` | Plan a trip; rejects on driver window overlap | DistributorOwner |
| GET | `/dairy/trips/{id}` | Get a trip | Any |
| GET | `/dairy/trips` | List trips filtered by route, driver, or service date | Any |
| POST | `/dairy/trips/{id}/depart` | Depart a PLANNED trip (pre-cool check; no PLANNED orders) | RouteDriver |
| POST | `/dairy/trips/{id}/complete` | Complete a DEPARTED trip (all orders DELIVERED); finalizes cold-chain math | RouteDriver |
| POST | `/dairy/trips/{id}/cancel` | Cancel a PLANNED trip with no CONFIRMED orders | DistributorOwner |
| POST | `/dairy/trips/{id}/qa-review` | Open QA review on a COMPLETED trip with a cold-chain breach | QualityInspector |
| POST | `/dairy/trips/{id}/adjudicate` | Adjudicate a QA review: CLEAR reconciles; CONFIRM_BREACH fires the five-level cascade | QualityInspector |
| POST | `/dairy/trips/{id}/reconcile` | Reconcile a COMPLETED trip with no breach | DistributorOwner |
| POST | `/dairy/trips/{id}/temperature-readings` | Append a temperature reading (trip PLANNED or DEPARTED) | RouteDriver |
| GET | `/dairy/trips/{id}/temperature-readings` | List readings of a trip, recorded_at ascending; optional `zone` filter | Any |
| POST | `/dairy/orders` | Create a manual order in PLANNED; cases reserved at creation | DistributorOwner |
| POST | `/dairy/trips/{id}/generate-orders` | Generate PAR_GENERATED orders from ACTIVE standing pars; idempotent per store | DistributorOwner |
| GET | `/dairy/orders/{id}` | Get an order | Any |
| GET | `/dairy/orders` | List orders filtered by store, trip, or fulfillment status | Any |
| POST | `/dairy/orders/{id}/confirm` | Confirm a PLANNED order: dock buffer, capacity, and credit checks | DistributorOwner |
| POST | `/dairy/orders/{id}/cancel` | Cancel a PLANNED or CONFIRMED order; releases reserved cases | DistributorOwner |
| POST | `/dairy/orders/{id}/deliver` | Deliver a CONFIRMED order; snapshots prices, creates the invoice and crate DROP | RouteDriver |
| GET | `/dairy/invoices/{id}` | Get an invoice | Any |
| GET | `/dairy/invoices` | List invoices filtered by order, store, or status | Any |
| POST | `/dairy/invoices/{id}/payments` | Record a store payment against an OPEN invoice | StoreReceiver |
| POST | `/dairy/invoices/{id}/void` | Void an OPEN invoice with no payments and no credits | TerritoryManager |
| POST | `/dairy/returns` | Submit a return scan against a DELIVERED order | RouteDriver |
| GET | `/dairy/returns/{id}` | Get a return | Any |
| GET | `/dairy/returns` | List returns filtered by order, store, pickup trip, product, or status | Any |
| POST | `/dairy/returns/{id}/approve` | Approve a return; system immediately credits it and auto-applies the memo | DistributorOwner |
| POST | `/dairy/returns/{id}/reject` | Reject a return under review or disputed | DistributorOwner |
| POST | `/dairy/returns/{id}/dispute` | Dispute a REJECTED return | StoreReceiver |
| GET | `/dairy/credit-memos/{id}` | Get a credit memo | Any |
| GET | `/dairy/credit-memos` | List credit memos filtered by return, store, invoice, or status | Any |
| POST | `/dairy/credit-memos/{id}/apply` | Apply a memo's remaining balance to a chosen OPEN invoice of the same store | DistributorOwner |
| POST | `/dairy/credit-memos/{id}/void` | Void a memo and compensate its invoice applications | TerritoryManager |
| POST | `/dairy/stores/{id}/crate-transactions` | Record a crate PICKUP (driver) or ADJUSTMENT (owner); DROP is system-only | RouteDriver, DistributorOwner |
| GET | `/dairy/stores/{id}/crate-transactions` | List crate transactions of a store; optional `kind` filter | Any |
| POST | `/dairy/trips/{id}/merchandising-sessions` | Check in a store-door merchandising session | RouteDriver |
| POST | `/dairy/merchandising-sessions/{id}/close` | Close an OPEN session and compute billable labor | RouteDriver |
| GET | `/dairy/merchandising-sessions/{id}` | Get a session | Any |
| GET | `/dairy/merchandising-sessions` | List sessions filtered by trip, store, driver, or status | Any |
| POST | `/dairy/route-sale-listings` | Create a DRAFT sale listing for a route owned by the caller | DistributorOwner |
| GET | `/dairy/route-sale-listings/{id}` | Get a listing | Any |
| GET | `/dairy/route-sale-listings` | List listings filtered by route, seller, buyer, or status | Any |
| POST | `/dairy/route-sale-listings/{id}/publish` | Publish a DRAFT listing; snapshots territory value | DistributorOwner |
| POST | `/dairy/route-sale-listings/{id}/submit-offer` | Submit an offer as a buyer distributor | DistributorOwner |
| POST | `/dairy/route-sale-listings/{id}/accept-offer` | Seller accepts the pending offer | DistributorOwner |
| POST | `/dairy/route-sale-listings/{id}/reject-offer` | Seller rejects the pending offer; listing cycles back to LISTED | DistributorOwner |
| POST | `/dairy/route-sale-listings/{id}/withdraw` | Seller withdraws a LISTED or OFFER_PENDING listing | DistributorOwner |
| POST | `/dairy/route-sale-listings/{id}/approve-transfer` | Close an UNDER_CONTRACT listing; route ownership transfers to the buyer | TerritoryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DISTRIBUTOR_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PAR_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_ANNOUNCEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_MEMO_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_STORE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PRICING_PERIOD_VERSION` | 412 Precondition Failed |
| `ERR_ROUTE_NOT_ACTIVE` | 409 Conflict |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_PERIOD_CLOSED` | 409 Conflict |
| `ERR_TRIP_NOT_PLANNED` | 409 Conflict |
| `ERR_TRIP_NOT_DEPARTED` | 409 Conflict |
| `ERR_TRIP_NOT_COMPLETED` | 409 Conflict |
| `ERR_TRIP_NOT_IN_QA_REVIEW` | 409 Conflict |
| `ERR_READINGS_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERABLE` | 409 Conflict |
| `ERR_RETURN_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_RETURN_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_LISTING_NOT_OPEN_FOR_OFFER` | 409 Conflict |
| `ERR_LISTING_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_LISTING_NOT_UNDER_CONTRACT` | 409 Conflict |
| `ERR_SESSION_NOT_OPEN` | 409 Conflict |
| `ERR_INVOICE_NOT_OPEN` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CREDIT_MEMO_NOT_APPLICABLE` | 409 Conflict |
| `ERR_CREDIT_MEMO_NOT_VOIDABLE` | 409 Conflict |
| `ERR_COLD_CHAIN_PRECOOL_REQUIRED` | 409 Conflict |
| `ERR_OUT_OF_CODE_DELIVERY` | 422 Unprocessable Entity |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRIP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_READING_OUT_OF_ORDER` | 409 Conflict |
| `ERR_TRIP_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_CRATE_BALANCE` | 409 Conflict |
| `ERR_SELF_DEALING` | 422 Unprocessable Entity |
| `ERR_SESSION_CONFLICT` | 409 Conflict |
| `ERR_DELIVERY_QTY_EXCEEDS_ORDER` | 422 Unprocessable Entity |
| `ERR_RETURN_PRODUCT_NOT_DELIVERED` | 422 Unprocessable Entity |
| `ERR_RETURN_STORE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RETURN_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_EXCEEDS_DUE` | 402 Payment Required |
| `ERR_ROUTE_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_STORE_HAS_CONFIRMED_ORDERS` | 409 Conflict |
