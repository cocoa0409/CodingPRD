# Foodservice Distribution Wholesale API — Product Requirements Document

## 1. Introduction

This document specifies a business-to-business ordering and fulfillment platform for a foodservice distribution and wholesale operation. The platform serves restaurants, cafeterias, and other commercial buyers who order from a distributor's catalog against negotiated credit terms, against volume-based case and split pricing, and against route-based delivery cutoffs. A typical day moves from a sales representative building an order off a customer's order guide, through credit approval and warehouse inventory allocation, into picking, loading, and proof-of-delivery, and finally — when goods are damaged or over-shipped — into returns and credit memos.

The hard problems this API exists to solve are the ones that hide in the seams between those steps: a customer's accounts-receivable exposure must never silently exceed its credit limit; perishable inventory must be allocated first-expiry-first-out so that no lot is shipped that will spoil before it is delivered; a volume price tier earned on the quantity a customer ordered must still be honored even when the warehouse can only ship part of it; and two credit approvals racing against the same customer's balance must not both succeed on stale data. The system is multi-tenant — every resource is scoped to a single distributor — and it keeps a server-controlled logical clock so that cutoff and delivery-day arithmetic is deterministic and testable.

This specification is written for the engineering team that will implement the service. It describes the resources, their state machines, the pricing and allocation calculations, the validation rules and their precedence, and the complete endpoint and error surface.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly four roles: `DistributorAdmin`, `SalesRep`, `WarehouseOp`, and `CreditManager`. The `DistributorAdmin` is the operational superset, owning catalog, pricing, route, and warehouse configuration as well as the customer lifecycle, and may also place and cancel orders. The `SalesRep` owns customer-facing order capture and order guides. The `WarehouseOp` owns warehouse fulfillment — receiving stock, picking, loading, and capturing proof of delivery. The `CreditManager` owns credit governance — placing and releasing credit holds, approving an order's credit, and approving, rejecting, or issuing credit memos for returns.

All four roles use an opaque identity model. For each of `DistributorAdmin`, `SalesRep`, `WarehouseOp`, and `CreditManager`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`, and ownership of a resource is never determined by matching `X-User-ID` against a stored foreign key. Authorization is governed entirely by the role named in `X-User-Role` against the permission set for the requested endpoint.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT`.

Unless a specific endpoint says otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Tenancy, Common Resource Properties, and Identifiers

Every resource in the system belongs to exactly one distributor, which is the tenant scope. Resources other than the `Distributor` itself carry a `distributor_id` that pins them to their tenant; for several resources this value is supplied directly on input, and for others it is copied by the server from a parent resource at creation time rather than accepted from the client.

All resources carry a system-generated `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Every entity in this system additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation of that resource. The `version` is the basis for optimistic concurrency control described in §2.7. There are no immutable, version-less resources in this domain; every resource type participates in the `updated_at` and `version` discipline.

### 2.5. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one resource at once, and the secondary effects are as much a part of the contract as the primary transition. When the server changes a resource as a side effect of an operation on another resource — for example, advancing a customer's accounts-receivable balance when an order's credit is approved, or releasing an inventory lot's reservation when an order is cancelled — that secondary resource's own `updated_at` is refreshed and its `version` is incremented. A cascade may be transitive: issuing a return's credit memo can reduce a customer's balance, which can lift that customer off a credit hold, which can in turn return one or more of that customer's held orders to a pending credit state. Each link in such a chain is an independent mutation that bumps the affected resource's `version`.

When the same logical action touches several resources, the entire set of effects is applied together and immediately; the system does not defer reconciliation. References between resources are validated left-to-right: a request that names several resources (a path identifier and one or more foreign keys in the body) is checked in the order they appear, and the first identifier that does not resolve to an existing resource under the distributor causes the request to be rejected with `ERR_NOT_FOUND` before any later reference is examined.

### 2.6. Money, Quantities, and Rounding

All monetary amounts in this system are stored and exchanged as integer counts of cents; there are no fractional-cent fields. All inventory quantities are stored as integer counts of split units, where a split is the smallest sellable each-unit and a case contains a fixed whole number of splits. Where a calculation must reduce a price or quantity to a whole number, the specific direction of rounding is part of that calculation's definition and is stated with the calculation in §3: tier and case counts are taken by rounding down to the nearest whole number, a per-split price derived from a case price is taken by rounding up to the nearest whole cent, and per-split delivered value and restocking fees are taken by rounding half up to the nearest whole cent. None of these is ever approximated; each is computed exactly as specified.

### 2.7. Optimistic Concurrency Control on Credit Approval

Approving an order's credit is the one operation in this system guarded by optimistic concurrency control. The request to credit-approve a submitted order must carry `expected_customer_version`, a non-optional field whose value is the `version` of the order's customer that the client last observed. At approval time the server compares `expected_customer_version` against the customer's current `version`. If they do not match — because some other writer has advanced that customer's `version` since the client read it — the approval is rejected with `ERR_STALE_CUSTOMER_VERSION` and HTTP status 412.

This guard exists because a credit decision is evaluated against the customer's accounts-receivable snapshot. Approving a different order for the same customer debits that customer's balance and advances the customer's `version`; a later approval still carrying the pre-debit `expected_customer_version` is therefore working from a balance that has since moved, and rejecting it as stale prevents the client from committing a credit decision it could not have made correctly. The approval advances the customer's `version` even when the order is routed to a held state rather than approved, so the guard remains well defined for the next approval against any sibling order. No other endpoint in the system accepts or requires a version field; only credit approval is version-checked.

### 2.8. Catalog Revision Tracking

Each distributor maintains a `catalog_revision` counter. It begins at zero when the distributor is created and increments by one whenever a `Product` or a `PriceTier` under that distributor is created or repriced. This counter lets clients detect that pricing or catalog content has changed underneath them.

### 2.9. The Server Clock

Cutoff and delivery-day arithmetic depend on the current time, and to keep that arithmetic deterministic the system does not read the wall clock. Instead each distributor carries `current_utc`, a server-held clock that starts at the Unix epoch, `1970-01-01T00:00:00.000Z`, and only ever advances through an administrative test-driving capability that sets it to a supplied instant. Advancing the clock also drives an accounts-receivable sweep, described in §3.5. All cutoff, delivery-day, and freshness comparisons read `current_utc` rather than real time.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Distributors, Warehouses, Routes, Products, and Tiers

Everything begins with a `Distributor`, the tenant root, created with a `name`. A new distributor starts with its `current_utc` at the epoch and its `catalog_revision` at zero.

Under a distributor, a `DistributorAdmin` configures warehouses and routes. A `Warehouse` is created with its `distributor_id`, a short `code`, and a `name`; the `code` must be unique within the distributor, and a clash is rejected with `ERR_DUPLICATE_CODE`. A `Route` is created with its `distributor_id`, the `warehouse_id` of the warehouse that picks and loads it, a `code` unique within the distributor (a clash again raising `ERR_DUPLICATE_CODE`), a `delivery_dow` giving the delivery day of week as an integer from 0 for Monday through 6 for Sunday, a `cutoff_lead_hours` giving how many whole hours before delivery an order must be submitted, and an optional `min_delivery_gap_days`. The `delivery_dow` must lie between 0 and 6 inclusive, and both `cutoff_lead_hours` and `min_delivery_gap_days` must be at least zero; `min_delivery_gap_days` defaults to 0 when omitted. The route's `warehouse_id` must resolve to a warehouse under the same distributor, and a cross-tenant reference is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`.

A `Product` is the catalog item. It is created with its `distributor_id`, a `sku` unique within the distributor (a clash raising `ERR_DUPLICATE_SKU`), a `name`, a `category` such as DAIRY, PRODUCE, or DRY, and a `splits_per_case` giving how many split (each) units make up one case, which must be at least 1. Three booleans tune its behavior: `split_allowed`, defaulting to true, controls whether the product may be ordered in split units; `perishable`, defaulting to false, marks products whose lots carry expiration and allocate first-expiry-first-out; and these combine with an optional `substitute_product_id`, a self-reference to another product to fall back on when this one is out of stock, which defaults to null meaning no substitute. A product also records `case_cost_cents`, the distributor's landed cost per case, which must be at least zero. The product's `status` begins `ACTIVE` and is system-managed; discontinuing a product sets `status` to `DISCONTINUED`. Creating a product increments the distributor's `catalog_revision`.

Volume pricing lives in `PriceTier` rows attached to a product. A tier is created with the `product_id` it belongs to, a `min_cases` giving the inclusive lower bound in case-equivalents at which the tier's price applies (at least 1), and a `case_price_cents` giving the price per case in cents (at least zero). The tier's own `distributor_id` is copied by the server from the product rather than supplied. A product may not have two tiers with the same `min_cases`; a duplicate is rejected with `ERR_DUPLICATE_TIER`. Creating a tier also increments the distributor's `catalog_revision`. A given tier's `case_price_cents` applies when the ordered case-equivalent count is at least that tier's `min_cases` and below the next higher tier's `min_cases`.

Warehouse stock is held in `InventoryLot` rows. A lot is received with the `product_id` it stocks, the `warehouse_id` it sits in, a vendor `lot_code`, an optional `expires_on` expiration timestamp (defaulting to null, and driving first-expiry-first-out ordering for perishables), and an `on_hand_splits` count of sellable split units, which must be at least zero. A lot also tracks `reserved_splits`, which the server initializes to zero and maintains as the count of split units reserved by approved, not-yet-shipped order lines against that lot. The lot's `warehouse_id` must resolve within the same distributor as its product, or the receipt is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`.

### 3.2. Customers, Order Guides, and Par-Based Replenishment

A `Customer` is a ship-to location, created with its `distributor_id`, the `route_id` of the delivery route it sits on, a `name`, a `credit_limit_cents` giving the maximum open accounts-receivable exposure permitted (at least zero), and an optional `split_fee_cents` per-split-line handling surcharge that defaults to zero and must be at least zero. The server initializes the customer's `ar_balance_cents` (its open accounts-receivable exposure) to zero and its `ar_status` to `ACTIVE`. The named `route_id` must resolve within the same distributor, or creation is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`. A customer's `ar_status` moves among `ACTIVE`, `CREDIT_HOLD`, and `CLOSED` over its lifetime, as described in §3.5.

A `CreditManager` or `DistributorAdmin` may adjust a customer's `credit_limit_cents` at any time. Lowering the limit below the current `ar_balance_cents` does not place the customer on hold by itself; the customer is only swept onto hold the next time the clock advances (see §3.5).

Customers shop from order guides. An `OrderGuide` is created for a customer with the `customer_id` it belongs to and a `name` (a customer may keep several, such as WEEKLY or DRY); the guide's `distributor_id` is copied from the customer. Creating a guide for a customer whose `ar_status` is `CLOSED` is rejected with `ERR_CUSTOMER_CLOSED`. Each guide holds `OrderGuideItem` lines, created with the `order_guide_id` they belong to, the `product_id` they track, a `par_level_splits` target on-hand level in split units (at least zero), and an optional `on_hand_splits` giving the customer's last-reported on-hand in split units, which defaults to zero and must be at least zero. The item's `product_id` must resolve within the same distributor, or creation is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`.

The order guide drives a read-only replenishment suggestion. When a `DistributorAdmin` or `SalesRep` requests the fill-to-par suggestions for a guide, the system walks each `OrderGuideItem` and computes a deficit equal to the par level minus the reported on-hand, taken as zero if the on-hand already meets or exceeds par — that is, the deficit in splits is the greater of zero and `par_level_splits` minus `on_hand_splits`. Items whose deficit is zero are omitted entirely from the suggestion list. For an item whose deficit is positive, the suggestion depends on whether the tracked product allows splits. When the product's `split_allowed` is true, the suggestion is given in split units: `suggested_uom` is SPLIT and `suggested_qty` is exactly the split deficit. When the product's `split_allowed` is false, the suggestion is rounded up to whole cases: `suggested_uom` is CASE and `suggested_qty` is the split deficit divided by the product's `splits_per_case`, rounded up to the next whole case. The two branches are deliberately different — a case-only product can be suggested slightly above par because of the round-up, while a split-capable product is suggested exactly to par. The endpoint returns the qualifying guide items annotated with `suggested_uom` and `suggested_qty`; it mutates nothing.

### 3.3. Capturing an Order: Draft, Lines, and Submission

An order is captured by a `SalesRep` or `DistributorAdmin`. Creating an order takes the `customer_id` it is for and a `requested_delivery_date`, the requested delivery calendar date expressed as UTC midnight. The new `Order` begins with `fulfillment_status` of `DRAFT` and `credit_status` of `PENDING` — these are two independent status dimensions that the order carries throughout its life. Its `distributor_id` is copied from the customer, and its `route_id` is left null at draft time, to be snapshotted at submission. Creating an order for a customer whose `ar_status` is `CLOSED` is rejected with `ERR_CUSTOMER_CLOSED`. The order also carries computed money fields — `goods_subtotal_cents`, `split_fee_total_cents`, and `order_total_cents` — all initialized to zero, and a `settled` boolean initialized to false that flips true only once delivery is captured.

Lines are added to a draft order by a `SalesRep` or `DistributorAdmin`. Adding a line takes the `product_id` requested on the line, the `uom` (either CASE or SPLIT), the `ordered_qty` in that unit of measure (at least 1), and an optional `order_guide_item_id` naming the guide line this was placed from, which defaults to null for an ad-hoc line. The new `OrderLine` records the `order_id` it belongs to and begins with `line_status` of `OPEN`. A line requested in SPLIT units against a product whose `split_allowed` is false is rejected with `ERR_SPLIT_NOT_ALLOWED`. The line's `product_id` must resolve within the same distributor, or the request is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`. At draft time the line's allocation and pricing fields — `fulfilled_product_id`, `allocated_splits`, `substituted`, `short_splits`, `unit_case_price_cents`, and `extended_price_cents` — are not yet meaningful; `allocated_splits`, `short_splits`, `unit_case_price_cents`, and `extended_price_cents` default to zero, `substituted` defaults to false, and `fulfilled_product_id` defaults to null until allocation runs at credit approval.

A line may be removed from a draft order by a `SalesRep` or `DistributorAdmin`; removal sets that line's `line_status` to `REMOVED` and recomputes the order's totals from the remaining non-removed lines.

Submitting a draft order is a `SalesRep` or `DistributorAdmin` action that advances `fulfillment_status` from `DRAFT` to `SUBMITTED` and (re-)affirms `credit_status` at `PENDING`. Submission runs a battery of checks. The order must contain at least one `OrderLine` whose `line_status` is not `REMOVED`, or it is rejected with `ERR_EMPTY_ORDER`. The customer's `ar_status` must be `ACTIVE`; a customer on `CREDIT_HOLD` causes `ERR_CUSTOMER_ON_CREDIT_HOLD`. The day of week of `requested_delivery_date` must equal the route's `delivery_dow`, or the order is rejected with `ERR_DELIVERY_DAY_MISMATCH`. The cutoff must not have passed: the distributor's `current_utc` must be at or before the delivery date's midnight minus the route's `cutoff_lead_hours` — equality is allowed, and a `current_utc` strictly after that moment is rejected with `ERR_CUTOFF_PASSED`. Finally, the new order must respect the route's delivery-gap buffer: if the route carries a `min_delivery_gap_days`, then no other order for the same customer whose `fulfillment_status` is `SUBMITTED`, `PICKING`, `LOADED`, or `DELIVERED` may have a `requested_delivery_date` whose whole-day distance from this order's date is less than `min_delivery_gap_days`; a collision is rejected with `ERR_DELIVERY_GAP_CONFLICT`. On a successful submit the order's `route_id` is snapshotted from the customer's `route_id`.

These submission checks are evaluated in the platform's standard precedence, which governs every write endpoint in the system. Authentication comes first (a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_USER_CONTEXT`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`), then existence of every referenced resource validated left-to-right (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present, enum members valid, and constrained integers non-negative — which on failure yields `ERR_INVALID_REQUEST`. Only after those four foundational checks does the system apply the state check that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), and then the endpoint's own business rules. Among submission's business rules, the customer-closed guard comes before the delivery-day, cutoff, and gap checks, and the credit-hold guard governs whether submission may proceed at all.

### 3.4. Credit Approval: Allocation, Pricing, and the AR Decision

Once an order is `SUBMITTED`, a `CreditManager` approves its credit. This single operation is the busiest in the system: it leaves `fulfillment_status` at `SUBMITTED` while moving `credit_status` from `PENDING` toward `APPROVED`, and along the way it allocates inventory, prices every line, totals the order, and makes the accounts-receivable decision. The request carries only `expected_customer_version` (see §2.7). Before any work is done, the approval requires that `credit_status` is `PENDING`, or it is rejected with `ERR_INVALID_STATE`; that `expected_customer_version` matches the customer's current `version`, or it is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412); and that the customer's `ar_status` is `ACTIVE`, or it is rejected with `ERR_CUSTOMER_ON_CREDIT_HOLD`. It also requires, for every perishable line, that at least one eligible lot exists whose freshness window still contains the delivery instant — that is, whose `expires_on` is strictly after `requested_delivery_date`. If for some perishable line every candidate lot, across both the primary product and any substitute, has an `expires_on` at or before `requested_delivery_date`, the approval is rejected with `ERR_LOT_EXPIRES_BEFORE_DELIVERY`.

**Allocation runs first.** Each `OrderLine` still in `OPEN` status is processed in `created_at` ascending order, deterministically. For a line, the needed quantity in splits is the `ordered_qty` times the product's `splits_per_case` for a CASE line, or simply the `ordered_qty` for a SPLIT line. The system gathers candidate lots of the line's product held at the order's route warehouse for which the available quantity — `on_hand_splits` minus `reserved_splits` — is greater than zero. For a perishable product, a lot is a candidate only when its `expires_on` is strictly after `requested_delivery_date`; lots that expire on or before the delivery date are excluded. Perishable candidate lots are taken in order of `expires_on` ascending and then `created_at` ascending (first-expiry-first-out); non-perishable candidate lots are taken in `created_at` ascending order. The system draws from candidate lots in that order, taking from each the smaller of the remaining need and that lot's available quantity, adding what it takes to the line's `allocated_splits`, increasing that lot's `reserved_splits` by the same amount, and reducing the remaining need accordingly, until either the need is met or the lots are exhausted. If a shortfall remains and the product carries a `substitute_product_id`, the system repeats the same first-expiry-first-out draw against the substitute product's lots at the same warehouse; if any substitute splits are taken, the line is marked `substituted` true. Whatever quantity still cannot be filled becomes the line's `short_splits`. A line whose `allocated_splits` equals its full needed quantity ends with `line_status` of `ALLOCATED`; otherwise it ends `SHORTED`. The line's `fulfilled_product_id` is set to the substitute product's id when the line was filled entirely from the substitute (the primary took nothing) and to the originally requested `product_id` otherwise.

**Pricing runs next, per line, after allocation.** The pricing tier is chosen on the quantity the customer *ordered*, while the charge is computed on the quantity actually *allocated* — the same line priced on two different quantity bases. To pick the tier, the system first finds the case-equivalents of the ordered quantity: the ordered split count (the `ordered_qty` times `splits_per_case` for a CASE line, or the `ordered_qty` itself for a SPLIT line) divided by `splits_per_case` and rounded down to a whole number; if that comes out below 1 — as it does for a sub-case SPLIT-only line — it is treated as 1 so the line still prices at the lowest tier. Among the fulfilled product's `PriceTier` rows whose `min_cases` is at most that ordered case-equivalent count, the system selects the one with the greatest `min_cases`; since `min_cases` is unique per product, this is unambiguous, but should a tie ever arise it is broken by `created_at` ascending. The selected tier's `case_price_cents` becomes the line's `unit_case_price_cents`. Because a substituted line is fulfilled by a different product, it is priced on that substitute's tiers. The charge is then computed on the allocated quantity: the allocated splits are split into full cases (the `allocated_splits` divided by `splits_per_case`, rounded down) and a residual remainder of splits left over. Each residual split is priced at the case price divided by `splits_per_case`, rounded up to the next whole cent (rounding in the distributor's favor). The line's `extended_price_cents` is the number of full cases times `unit_case_price_cents` plus the residual split count times that rounded-up per-split price.

**Totals run last.** The order's `goods_subtotal_cents` is the sum of `extended_price_cents` across all lines whose `line_status` is not `REMOVED`. The order's `split_fee_total_cents` is the customer's `split_fee_cents` multiplied by the number of lines that are in SPLIT units, are not removed, and allocated more than zero splits — the per-split handling fee is charged once for each such qualifying SPLIT line. The order's `order_total_cents` is `goods_subtotal_cents` plus `split_fee_total_cents`. Each line is rounded by its own pricing before these sums are taken; the order computes line-first then aggregates.

**Then the credit decision.** With the order totaled, the system tests whether the customer can carry it: if the customer's `ar_balance_cents` plus this order's `order_total_cents` is at most the customer's `credit_limit_cents`, the order's `credit_status` becomes `APPROVED` and the customer's `ar_balance_cents` is increased by `order_total_cents`. Otherwise the order's `credit_status` becomes `ON_HOLD`, every reservation just made is rolled back (each touched lot's `reserved_splits` is decremented by what this approval added), and the customer's `ar_balance_cents` is left unchanged. Routing an over-limit order to `ON_HOLD` is the defined behavior and does not raise an over-limit error. Whichever path is taken, the order's `version` increments, and the customer's `version` increments as well — even on the `ON_HOLD` path — so that the optimistic-concurrency guard for any sibling order's approval is always well defined.

### 3.5. Credit Governance: Holds, Releases, the AR Sweep, and Customer Closure

A customer's `ar_status` is the posture that gates ordering. A `CreditManager` may place an `ACTIVE` customer on a manual credit hold, moving `ar_status` from `ACTIVE` to `CREDIT_HOLD`; attempting this on a customer not in `ACTIVE` is rejected with `ERR_INVALID_STATE`. A hold blocks new order submission and credit approval for that customer.

The system also places customers on hold automatically. Whenever the administrative clock-advance capability moves a distributor's `current_utc` forward — the request supplies the `distributor_id` and the `to_iso8601` instant — the server runs an accounts-receivable sweep across that distributor's customers: any customer currently `ACTIVE` whose `ar_balance_cents` exceeds its `credit_limit_cents` is moved to `CREDIT_HOLD`. This is the mechanism by which a credit-limit reduction eventually bites: lowering the limit does not hold the customer immediately, but the next clock advance sweeps it onto hold.

A `CreditManager` releases a customer from hold, moving `ar_status` from `CREDIT_HOLD` back to `ACTIVE`. Release is only permitted while the customer's `ar_balance_cents` is at most its `credit_limit_cents`; a release attempted while the balance still exceeds the limit is rejected with `ERR_OVER_CREDIT_LIMIT`. On a successful release, every order for that customer whose `credit_status` is `ON_HOLD` and whose `order_total_cents` still fits under the remaining headroom (the credit limit minus the current balance) has its `credit_status` cascaded from `ON_HOLD` back to `PENDING`, so it can be re-approved.

A `DistributorAdmin` closes a fully-settled customer, moving `ar_status` to `CLOSED`, a terminal posture. Closure requires that the customer's `ar_balance_cents` is exactly zero, or it is rejected with `ERR_CUSTOMER_NOT_SETTLED`, and that no order for the customer is in `fulfillment_status` `SUBMITTED`, `PICKING`, or `LOADED`, or it is rejected with `ERR_CUSTOMER_HAS_OPEN_ORDERS`. A `CLOSED` customer rejects any further order-creating, order-guide-creating, or return-creating action with `ERR_CUSTOMER_CLOSED`.

### 3.6. Fulfillment: Picking, Loading, and Proof of Delivery

Once an order's `credit_status` is `APPROVED`, a `WarehouseOp` begins picking it. Starting the pick advances the order's `fulfillment_status` from `SUBMITTED` to `PICKING` and creates a `Shipment` for the order. Starting the pick requires that `credit_status` is `APPROVED`, or it is rejected with `ERR_CREDIT_NOT_APPROVED`, and that at least one `OrderLine` is in `ALLOCATED` status, or it is rejected with `ERR_NOTHING_TO_PICK`. The new shipment records the `order_id` it serves, copies its `distributor_id` from the order, snapshots its `warehouse_id` from the route's warehouse, and begins with `status` of `PICKING`. Its `pod_signature` is null and its `delivered_total_cents` is zero until delivery.

Loading the shipment is a `WarehouseOp` action that moves the shipment's `status` from `PICKING` to `LOADED` and bubbles the order's `fulfillment_status` to `LOADED`. Loading requires the shipment to be in `PICKING` and the parent order's `fulfillment_status` to be `PICKING`; otherwise the request is rejected with `ERR_INVALID_STATE`.

Capturing proof of delivery is the terminal fulfillment step, performed by a `WarehouseOp` with a `pod_signature`. It requires the shipment to be in `LOADED`, or it is rejected with `ERR_INVALID_STATE`, and a non-empty `pod_signature`, or it is rejected with `ERR_POD_SIGNATURE_REQUIRED`. On success the shipment's `status` becomes `DELIVERED` and the order's `fulfillment_status` becomes `DELIVERED`, with the order's `settled` flag flipped to true. Inventory is consumed at this point: for each allocated lot, both its `on_hand_splits` and its `reserved_splits` are decremented by the line's `allocated_splits` — the reserved stock is converted into shipped stock. The shipment's `delivered_total_cents` is recorded as a snapshot of the order's `order_total_cents`. The customer's accounts-receivable balance is not touched here; it was already debited at credit approval, and the `settled` flag merely signals that the order no longer counts as open for customer-closure checks.

An order may be cancelled by a `SalesRep` or `DistributorAdmin`. A `DRAFT` order cancels unconditionally, moving `fulfillment_status` to `CANCELLED`. A `SUBMITTED` order may also be cancelled — this requires the order to actually be in `SUBMITTED`, else `ERR_INVALID_STATE` — and this cancellation is the compensating action for a prior credit approval. If the order's `credit_status` was `APPROVED`, cancellation releases every reservation (each allocated line's lot has its `reserved_splits` decremented by that line's `allocated_splits`) and decreases the customer's `ar_balance_cents` by the order's `order_total_cents`, then resets `credit_status` to `PENDING`; accounts-receivable and reservations must net back to zero. The order's `fulfillment_status` becomes `CANCELLED`, which together with `DELIVERED` is a terminal fulfillment state.

### 3.7. Returns and Credit Memos

After an order is delivered, the customer may return goods. A `SalesRep`, `DistributorAdmin`, or `CreditManager` requests a return against a delivered order line, supplying the `customer_id`, the `order_id` being returned against, the `order_line_id` being returned, a `reason` (one of `DAMAGED`, `OVERAGE`, `QUALITY`, or `WRONG_ITEM`), and a `return_splits` quantity in split units (at least 1). The new `Return` begins with `status` of `REQUESTED`; its `distributor_id` is copied from the customer. Requesting a return against a `CLOSED` customer is rejected with `ERR_CUSTOMER_CLOSED`, and the cited `order_line_id` must belong to the cited `order_id`. The return's computed `restock_fee_cents` and `credit_amount_cents` are zero until it is approved.

A `CreditManager` approves a requested return, moving `status` from `REQUESTED` to `APPROVED`. Approval requires that the return is in `REQUESTED`, or `ERR_INVALID_STATE`; that the referenced order's `fulfillment_status` is `DELIVERED`, or `ERR_ORDER_NOT_DELIVERED`; and that `return_splits` does not exceed the referenced line's delivered `allocated_splits`, or `ERR_RETURN_EXCEEDS_DELIVERED`. On approval the system computes the credit. The per-split delivered value is the line's `extended_price_cents` divided by its `allocated_splits`, rounded half up to a whole cent; the returned goods value is that per-split value times `return_splits`. A restocking fee applies only to an `OVERAGE` return, where the customer over-ordered: in that case `restock_fee_cents` is fifteen percent of the returned goods value, rounded half up to a whole cent. For a `DAMAGED`, `QUALITY`, or `WRONG_ITEM` return there is no fee and `restock_fee_cents` is zero. The `credit_amount_cents` is the returned goods value minus `restock_fee_cents` — so a fee-free return credits the full returned value, while an overage return credits the returned value less the fifteen-percent fee, meaning the same returned quantity yields a different credit depending on the reason.

A `CreditManager` may instead reject a requested return, moving `status` from `REQUESTED` to `REJECTED` (a terminal state); rejection requires the return to be in `REQUESTED`, else `ERR_INVALID_STATE`.

Finally, a `CreditManager` issues the credit memo for an approved return, moving `status` from `APPROVED` to `CREDITED` (a terminal state); this requires the return to be in `APPROVED`, else `ERR_INVALID_STATE`. Issuing the credit decreases the customer's `ar_balance_cents` by the return's `credit_amount_cents` — the conserved-quantity compensation against the delivered order's original accounts-receivable debit. If that decrease brings the customer's `ar_balance_cents` to at or below its `credit_limit_cents` while the customer's `ar_status` is `CREDIT_HOLD`, the customer is returned to `ACTIVE`, and then each of that customer's `ON_HOLD` orders whose `order_total_cents` now fits under the remaining headroom is cascaded from `ON_HOLD` to `PENDING` — a transitive chain from the return through the customer to its held orders.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition and every read — return `200 OK`. The request and response payloads for each endpoint are described in the workflow narratives of §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/distributors` | Create a distributor (tenant root) | DistributorAdmin |
| GET | `/distributors/{distributorId}` | Get a distributor | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/_clock/set_current_utc` | Set a distributor's server clock; triggers AR over-limit sweep | DistributorAdmin |
| POST | `/warehouses` | Create a warehouse | DistributorAdmin |
| GET | `/warehouses/{warehouseId}` | Get a warehouse | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/warehouses` | List warehouses | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/routes` | Create a delivery route | DistributorAdmin |
| GET | `/routes/{routeId}` | Get a route | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/routes` | List routes | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/products` | Create a catalog product | DistributorAdmin |
| GET | `/products/{productId}` | Get a product | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/products` | List/browse catalog | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/products/{productId}/discontinue` | Discontinue a product | DistributorAdmin |
| POST | `/price-tiers` | Add a volume price tier to a product | DistributorAdmin |
| GET | `/price-tiers/{priceTierId}` | Get a price tier | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/price-tiers` | List price tiers | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/inventory-lots` | Receive an inventory lot for a product at a warehouse | DistributorAdmin, WarehouseOp |
| GET | `/inventory-lots/{lotId}` | Get an inventory lot | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/inventory-lots` | List lots | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/customers` | Create a customer / ship-to | DistributorAdmin, SalesRep |
| GET | `/customers/{customerId}` | Get a customer | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/customers` | List customers | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/customers/{customerId}/credit-limit` | Adjust a customer's credit limit | CreditManager, DistributorAdmin |
| POST | `/customers/{customerId}/credit-hold` | Place a customer on manual credit hold | CreditManager |
| POST | `/customers/{customerId}/credit-release` | Release a customer from credit hold | CreditManager |
| POST | `/customers/{customerId}/close` | Close a fully-settled customer | DistributorAdmin |
| POST | `/order-guides` | Create an order guide for a customer | DistributorAdmin, SalesRep |
| GET | `/order-guides/{orderGuideId}` | Get an order guide | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/order-guides` | List order guides | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/order-guide-items` | Add an item with a par level to an order guide | DistributorAdmin, SalesRep |
| GET | `/order-guide-items/{orderGuideItemId}` | Get an order guide item | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/order-guide-items` | List order guide items | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/order-guides/{orderGuideId}/replenishment` | Par-based fill-to-par suggestions for the guide | DistributorAdmin, SalesRep |
| POST | `/orders` | Create a draft order for a customer | SalesRep, DistributorAdmin |
| GET | `/orders/{orderId}` | Get an order | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/orders` | List orders | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/orders/{orderId}/lines` | Add a line to a draft order | SalesRep, DistributorAdmin |
| GET | `/order-lines/{orderLineId}` | Get an order line | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/order-lines` | List order lines | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/order-lines/{orderLineId}/remove` | Remove a line from a draft order | SalesRep, DistributorAdmin |
| POST | `/orders/{orderId}/submit` | Submit a draft order | SalesRep, DistributorAdmin |
| POST | `/orders/{orderId}/approve-credit` | Credit-approve a submitted order | CreditManager |
| POST | `/orders/{orderId}/start-pick` | Begin picking an approved order; creates a shipment | WarehouseOp |
| POST | `/orders/{orderId}/cancel` | Cancel a draft or submitted order | SalesRep, DistributorAdmin |
| GET | `/shipments/{shipmentId}` | Get a shipment | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/shipments` | List shipments | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/shipments/{shipmentId}/load` | Mark a shipment loaded | WarehouseOp |
| POST | `/shipments/{shipmentId}/pod` | Capture proof of delivery | WarehouseOp |
| POST | `/returns` | Request a return against a delivered order line | SalesRep, DistributorAdmin, CreditManager |
| GET | `/returns/{returnId}` | Get a return | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| GET | `/returns` | List returns | DistributorAdmin, SalesRep, WarehouseOp, CreditManager |
| POST | `/returns/{returnId}/approve` | Approve a return | CreditManager |
| POST | `/returns/{returnId}/reject` | Reject a return | CreditManager |
| POST | `/returns/{returnId}/issue-credit` | Issue the credit memo for an approved return | CreditManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_TIER` | 409 |
| `ERR_CROSS_DISTRIBUTOR_REFERENCE` | 409 |
| `ERR_SPLIT_NOT_ALLOWED` | 422 |
| `ERR_EMPTY_ORDER` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DELIVERY_DAY_MISMATCH` | 409 |
| `ERR_CUTOFF_PASSED` | 409 |
| `ERR_DELIVERY_GAP_CONFLICT` | 409 |
| `ERR_LOT_EXPIRES_BEFORE_DELIVERY` | 409 |
| `ERR_CUSTOMER_ON_CREDIT_HOLD` | 409 |
| `ERR_CUSTOMER_CLOSED` | 409 |
| `ERR_CUSTOMER_NOT_SETTLED` | 409 |
| `ERR_CUSTOMER_HAS_OPEN_ORDERS` | 409 |
| `ERR_OVER_CREDIT_LIMIT` | 409 |
| `ERR_CREDIT_NOT_APPROVED` | 409 |
| `ERR_NOTHING_TO_PICK` | 409 |
| `ERR_POD_SIGNATURE_REQUIRED` | 422 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_RETURN_EXCEEDS_DELIVERED` | 422 |
| `ERR_STALE_CUSTOMER_VERSION` | 412 |
| `ERR_VALIDATION_LIMIT` | 422 |
