# Convenience Store Redistribution & DSD Wholesale API — Product Requirements Document

## 1. Introduction

Convenience-store redistribution is a weekly rhythm: each store has a standing delivery day, a curated order guide of authorized items, a cutoff hour after which the warehouse will no longer accept the week's order, and a credit envelope that gates whether an order may ship at all. On top of that rhythm sit the economics of the wholesale trade — case picks versus split-case eaches, manufacturer-funded promotions, maintained shelf prices, cigarette tax stamps that vary by jurisdiction, minimum drop sizes, and a fuel surcharge that floats with the weekly DOE diesel index. This document specifies the API for a redistribution and DSD (direct-store-delivery) wholesale platform in the style of a large national distributor, covering the full cycle from item-master setup and order-guide curation through manifest loading, door delivery, short/damage credit, and final invoice settlement.

The platform serves five operator constituencies: distributor administrators who run the item master, routes, rates, and item authorization; field sales representatives who curate order guides, promotions, and retail prices; store managers who place and submit orders against their own guide; route drivers who record shorts and damages at the door and confirm delivery; and a credit desk that manages terms, holds, payments, and credit memos. Because a single order's price is computed twice — once provisionally at submission on ordered quantities and once finally at delivery on delivered quantities — and because a retailer's credit posture must stay consistent across pipeline orders, open invoices, payments, and credits, the API is built around explicit state machines, deterministic pricing rules, optimistic concurrency on the two highest-contention writes, and a logical clock that drives cutoffs and past-due aging.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose body is malformed, omits a required field, or supplies a value of the wrong type is rejected with `ERR_VALIDATION` (HTTP 400).

The system recognizes exactly five roles: `WholesaleAdmin`, `SalesRep`, `StoreManager`, `RouteDriver`, and `CreditManager`. Each endpoint admits a fixed set of roles (enumerated in §4); a caller whose role is not admitted, or an entity-backed caller who does not own the target resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ per role. When `X-User-Role` is `StoreManager`, `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any resource that references a retailer — an order guide, a purchase order, an invoice, a price record, a new-item request — compare the resource's `retailer_id` foreign key to `X-User-ID`, and a store manager may only read and act on their own store's resources. When `X-User-Role` is `WholesaleAdmin`, `SalesRep`, `RouteDriver`, or `CreditManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`, and these roles reach resources per the authorization matrix in §4 alone.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All temporal decisions in the system — order-guide cutoffs, promotion eligibility windows, invoice aging, and past-due transitions — are evaluated against a server-side logical clock, never against wall-clock time. At server startup, before any administrative intervention, the logical clock reads exactly 2026-05-01T00:00:00Z. From then on it advances only when a `WholesaleAdmin` explicitly moves it through an admin-only test-driving capability that sets the current logical instant to a supplied `to_iso8601` value; the clock never falls back to wall-clock time on its own. Advancing the logical clock past an open invoice's due date is a business event: the affected invoices transition automatically and the affected retailers' credit postures are re-evaluated, as detailed in §3.7.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, marking creation and last modification respectively; `updated_at` refreshes on every mutation. The `version` field is an integer that starts at creation and increments by one on every mutation of the resource, including mutations driven by side effects such as a manifest assignment bumping an order, and it is the basis for optimistic concurrency control.

One exception applies: order lines are simple child records and carry only `id` and `created_at`. Both `updated_at` and `version` are absent from order lines.

### 2.6. Monetary Precision and Rounding

All money in the system is represented as integer cents — costs, fees, surcharges, allowances, balances, credit limits, and payment amounts alike. Wherever a calculation can produce a fractional cent — the per-line promotion allowance and the fuel surcharge — the result is rounded half-up to integer cents at the step the rule specifies; no other rounding mode is used. Per-unit and per-case catalog prices preserve the precision they were created with, weights such as case weight and truck capacity are plain numbers in pounds, and the weekly diesel index is expressed in USD per gallon.

### 2.7. Optimistic Concurrency Control

Two write operations operate under optimistic concurrency control, and each requires the caller to present the version of the parent resource it last observed.

Submitting a purchase order requires the request to carry `expected_order_version`, holding the order's current `version` as the client last read it. If the order's version has advanced since that read — because another writer modified the draft, each modification having incremented the version — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never submits a draft it has not actually seen.

Closing a delivery manifest requires the request to carry `expected_manifest_version`, holding the manifest's current `version` as the client last read it. Assigning orders to a manifest legitimately increments the manifest's version, so a close that carries an older observed version is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412).

Assigning an order to a manifest also carries `expected_manifest_version` in its payload, and the assignment proceeds only when that value equals the manifest's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here take no version field at all.

### 2.8. Nested Resource Retrieval

Requests that address nested resources are validated strictly left to right along the path. Each identifier in the path is resolved in turn, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later identifier or any business rule is examined. The same discipline applies to resources referenced inside a request body: a payload naming a non-existent retailer, product, guide, manifest, order, invoice, payment, or memo fails with `ERR_NOT_FOUND` before business validation begins.

### 2.9. Credit Exposure and the Retailer's Credit Posture

Every retailer carries two live exposure figures and one derived posture. The `ar_balance_cents` figure is the sum of `balance_cents` over all of the retailer's invoices in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE` status — money actually billed and still outstanding. The `exposure_forward_cents` figure is forward-looking: it equals `ar_balance_cents` plus the sum of `provisional_total_cents` over all of the retailer's purchase orders in `SUBMITTED`, `ASSIGNED`, or `CLOSED` status — the pipeline of orders priced but not yet invoiced. Pipeline orders enter the forward figure at submission and leave it when their invoice is created.

Alongside the forward figure, the system maintains a chronological accounts-receivable aging view used for reporting and past-due handling: invoice balances in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE`, bucketed by the number of days between the invoice's `due_date` and the current logical date. The credit summary of a retailer reports `ar_balance_cents`, `exposure_forward_cents`, the three aging buckets `exposure_aging_current_cents`, `exposure_aging_due_1_7_cents`, and `exposure_aging_due_8_plus_cents`, and the retailer's `credit_status`.

The `credit_status` of a retailer is either `GOOD_STANDING` or `CREDIT_HOLD` and gates order submission. It is re-evaluated after every balance-affecting event — order submission or cancellation, invoice creation, payment application, payment reversal, credit memo posting or voiding, and any update to the retailer's credit terms. An invoice that rolls to `PAST_DUE` forces the retailer onto `CREDIT_HOLD`; conversely, a re-evaluation may automatically release the hold when the condition that forced it has cleared, such as when a payment or posted credit satisfies the overdue balance. The credit desk may also place or release a hold directly. The forward figure is what the submission credit gate checks: a store may not submit an order that would push `exposure_forward_cents` above its `credit_limit_cents`.

### 2.10. Validation Order

When several checks could reject the same request, the server applies them in a fixed priority order so the error returned is deterministic. First come authentication and payload shape — `ERR_UNAUTHENTICATED` for missing or unrecognized headers, `ERR_VALIDATION` for malformed bodies or mistyped fields. Second, authorization — `ERR_FORBIDDEN`. Third, existence of path- and body-referenced resources — `ERR_NOT_FOUND`. Fourth, state and concurrency — `ERR_INVALID_STATE` for an illegal from-state, `ERR_MANIFEST_NOT_OPEN`, and `ERR_STALE_VERSION`. Fifth, regulated-product safety — the tobacco license and tax-stamp supply checks. Sixth, temporal rules — the order cutoff, delivery-window overlap, and promo-window overlap. Seventh, business constraints — the uniqueness rules, order-guide membership, split-case permission, manifest weight, guide-day matching, and memo-versus-balance checks. Eighth and last, the fiscal gates — `ERR_CREDIT_HOLD`, `ERR_CREDIT_LIMIT_EXCEEDED`, and `ERR_PAYMENT_EXCEEDS_BALANCE`.

Applied to order submission, this ordering means a stale order version surfaces before a missing tobacco license; the missing license surfaces before the absent stamp supply; stamp supply before the cutoff; the cutoff before guide membership; and guide membership before the two credit gates, with the credit hold checked before the credit limit.

## 3. Business Logic & Workflows

### 3.1. Retailers, the Item Master, and the Store Order Guide

A `WholesaleAdmin` onboards a store by creating its retailer account with the legal `store_name`, the tax-stamp `jurisdiction_code` — one of `CA_NORTH`, `CA_SOUTH`, `NV_CLARK`, or `AZ_MARICOPA` — the `credit_terms` of `COD`, `NET7`, or `NET14`, a `credit_limit_cents` ceiling in cents, the scheduled weekly `delivery_day` of `MON`, `TUE`, `WED`, `THU`, or `FRI`, and optionally a `tobacco_license_id` recording the store's state tobacco license. New retailers begin with `credit_status` of `GOOD_STANDING`, an `ar_balance_cents` of zero, and an `exposure_forward_cents` of zero. A `CreditManager` may later amend `credit_terms`, `credit_limit_cents`, or `tobacco_license_id`, and each such amendment re-evaluates the retailer's `credit_status`. The credit desk can also place or release a hold directly by passing a `hold` flag, which sets the retailer's `credit_status` accordingly.

The item master belongs to the `WholesaleAdmin`. Each product is created with a globally unique `sku` — a duplicate is rejected with `ERR_DUPLICATE_SKU` (HTTP 409) — plus a `description`, the `case_pack_units` count of eaches in a full case (at least one), the wholesale `case_cost_cents` per full case, the `unit_cost_cents` per each when split-case picked, a `split_case_allowed` flag governing whether eaches may be ordered, an `is_tobacco` flag (defaulting to false) that triggers tax-stamp handling, and the `weight_lbs_per_case` used for manifest loading. A product's `status` is `ACTIVE`.

Once a store and the catalog exist, a `SalesRep` curates the store's order guide: a payload naming the `retailer_id`, the guide's `delivery_day`, the `cutoff_hours_before` the delivery day after which submission is refused, and the authorized `lines`, an array of entries each pairing a `product_id` with a `par_cases` stocking par. The guide's `delivery_day` must equal the retailer's `delivery_day`; a mismatch is rejected with `ERR_GUIDE_DAY_MISMATCH` (HTTP 422). An order guide's `status` is `ACTIVE`, and only an `ACTIVE` guide accepts orders.

### 3.2. Weekly Promotions and Retail Price Maintenance

Promotions are funded allowances against the merchandise cost of a line. A `SalesRep` creates a promo event for a `product_id` with a `promo_type` of `OFF_INVOICE` or `SCAN_BACK`, a `discount_pct_bps` discount expressed in basis points of line merchandise cost — from 1 to 10,000 inclusive, that is, up to a full one hundred percent — and an eligibility window from `start_date` through `end_date`, both dates inclusive. Two promos for the same product may not overlap: because the windows are closed inclusive intervals, a new event whose date range touches any existing event's range for that product is rejected with `ERR_PROMO_WINDOW_OVERLAP` (HTTP 409). A promo's `status` moves through `SCHEDULED`, `ACTIVE`, and `EXPIRED` under system control as its window arrives and passes. Only `OFF_INVOICE` promos reduce what the store is billed; `SCAN_BACK` events are recorded for manufacturer settlement and never reduce the invoice.

Shelf prices are maintained per store and product through retail price records. A `SalesRep` publishes one by naming the `retailer_id`, the `product_id`, the `shelf_price_cents` to maintain, and an `effective_start` date, with an optional `effective_end`; a null `effective_end` leaves the price open-ended. Publishing a record for a store-product pair supersedes whatever record was previously `ACTIVE` for that pair: the prior record's `status` becomes `SUPERSEDED`, and the new record's `supersedes_id` points back to it, forming a durable price history.

### 3.3. Route Calendars: Delivery Windows, Fuel Rates, and Tax-Stamp Supplies

Route planning begins with delivery windows. A `WholesaleAdmin` creates a window with its `route_code`, a `window_start`, a `window_end`, and a `turnaround_buffer_minutes` gap that must elapse after the window ends before the next window on the same route may begin. Windows are half-open intervals: a window occupies its start up to but not including its end. A new window is rejected with `ERR_DELIVERY_WINDOW_OVERLAP` (HTTP 409) when its half-open span overlaps an existing window on the same route, when it begins before an earlier window's end plus that window's turnaround buffer, or when an existing window that begins at or after the new window's start begins before the new window's end plus the new window's turnaround buffer. The two buffer clauses are directional: a window that begins exactly at an earlier window's end plus that window's buffer is permitted, and an earlier window never constrains a later one through the later window's own buffer.

The fuel surcharge floats with the weekly DOE diesel index. Each week a `WholesaleAdmin` publishes a rate record with its `week_start_date` — the Monday of the rate week — and the `doe_index_usd` value in dollars per gallon, which must be positive. Only one rate may exist per week; a second record for the same `week_start_date` is rejected with `ERR_DUPLICATE_RATE_WEEK` (HTTP 409).

Cigarette handling is jurisdiction-specific. A `WholesaleAdmin` creates one tax-stamp supply per `jurisdiction_code` — a duplicate jurisdiction is rejected with `ERR_DUPLICATE_JURISDICTION` (HTTP 409) — carrying the `stamp_rate_cents_per_pack` excise cost, a flat `handling_fee_per_roll_cents` per stamp roll, the `packs_per_roll` coverage of one roll, and a `min_charge_cents` floor per order. The supply's `rolls_on_hand` counter starts at zero and is drawn down at manifest close as tobacco orders consume rolls; the supply's `status` is `ACTIVE`, and only an `ACTIVE` supply can support tobacco orders.

### 3.4. The Weekly Order Cycle: Drafting and Submission

A `StoreManager` builds the week's order as a draft, naming the `retailer_id`, the `order_guide_id` of the store's guide, and the order `lines`, each entry pairing a `product_id` with a `cases_qty` of full cases and a `split_units_qty` of split-case eaches — both zero or more. Draft creation already enforces three rules: every ordered product must appear in the referenced `ACTIVE` guide's lines, else `ERR_PRODUCT_NOT_ON_GUIDE` (HTTP 422); a line with `split_units_qty` above zero is permitted only when the product's `split_case_allowed` flag is true, else `ERR_SPLIT_CASE_NOT_ALLOWED` (HTTP 422); and any line referencing a tobacco product requires the retailer to carry a `tobacco_license_id`, else `ERR_TOBACCO_LICENSE_MISSING` (HTTP 422). The order is born in `DRAFT` status with `has_tobacco` derived from whether any line references a tobacco product, all of its money fields at zero, `manifest_id` and `submitted_at` null, and each line's `delivered_cases` and `delivered_split_units` at zero. A draft may be cancelled freely, moving `DRAFT` to `CANCELLED`.

Submission is the pricing event. The submit call carries `expected_order_version` per §2.7 and is legal only from `DRAFT`. The checks run in the priority order of §2.10: the guide must still be `ACTIVE`; every line's product must still appear in the guide's lines, else `ERR_PRODUCT_NOT_ON_GUIDE`; a tobacco order re-verifies the retailer's `tobacco_license_id`, else `ERR_TOBACCO_LICENSE_MISSING`, and requires an `ACTIVE` tax-stamp supply for the retailer's `jurisdiction_code`, else `ERR_TAX_STAMP_UNAVAILABLE` (HTTP 422); the logical clock must still be before the cutoff — midnight at the start of the delivery day minus the guide's `cutoff_hours_before` hours — else `ERR_ORDER_CUTOFF_PASSED` (HTTP 422); the retailer must be in `GOOD_STANDING`, else `ERR_CREDIT_HOLD` (HTTP 422); and the order must fit the credit envelope, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422), as described below.

When the checks pass, the pricing engine computes the order's commercial fields. Each line's `line_merch_cents` is its `cases_qty` multiplied by the product's `case_cost_cents` plus its `split_units_qty` multiplied by the product's `unit_cost_cents`, and the order's `merch_subtotal_cents` is the sum over all lines. The `promo_allowance_cents` sums per-line allowances: for each line whose product has an `OFF_INVOICE` promo covering the order's delivery date — the next occurrence of the retailer's `delivery_day` on or after the submit timestamp, eligible when the delivery date falls on or after `start_date` and on or before `end_date` — the line's `line_promo_cents` is the line merchandise cost multiplied by the promo's basis points divided by ten thousand, rounded half-up to integer cents per line, and the order allowance is the sum of those rounded per-line amounts. Rounding each line first and then summing is mandatory; summing across lines and rounding once is not used and yields different cents. The `pick_fee_cents` charges a flat 12 cents for every full case picked and 45 cents for every split-case each, summed over the order. The `min_drop_fee_cents` applies a threshold: take the merchandise subtotal less the promo allowance, and when that net merchandise figure is strictly below 50,000 cents a minimum-drop fee of 2,500 cents applies — an order netting exactly 50,000 cents pays no fee. For tobacco orders, `tax_stamp_cost_cents` is computed from ordered packs: the pack count is the split units summed over tobacco lines plus, for tobacco full cases, `cases_qty` multiplied by the product's `case_pack_units`; the stamp charge is the greater of the pack count times the jurisdiction's `stamp_rate_cents_per_pack` and the jurisdiction's `min_charge_cents`; the rolls needed are the pack count divided by `packs_per_roll` rounded up to a whole number; and the total stamp cost is the stamp charge plus the rolls needed times the `handling_fee_per_roll_cents`. The stamp cost is computed once, at submission, on ordered packs, and is carried unchanged into the final invoice.

The order's `provisional_total_cents` is then the merchandise subtotal minus the promo allowance, plus the pick fee, plus the minimum-drop fee, plus the tax-stamp cost; the fuel surcharge is excluded at submission because the rate week is not yet locked. The order's `weight_lbs` aggregates the case weight of its lines from each product's `weight_lbs_per_case`, `submitted_at` is stamped, and the order moves `DRAFT` to `SUBMITTED` with its `version` incremented. Submission also re-does the retailer's forward exposure: the new `provisional_total_cents` joins the pipeline sum inside `exposure_forward_cents`, and if that exposure now exceeds the retailer's `credit_limit_cents`, the submission is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` instead of proceeding.

A `SUBMITTED` order may still be cancelled, moving `SUBMITTED` to `CANCELLED`, but only until it is assigned to a manifest; cancellation then releases the order's provisional total from `exposure_forward_cents`, re-evaluates the retailer's `credit_status` — possibly releasing a `CREDIT_HOLD` — and increments the order's `version`. Once assigned, an order can no longer be cancelled, and a cancel attempt against an order that is not `DRAFT` or `SUBMITTED` fails with `ERR_INVALID_STATE` (HTTP 409).

### 3.5. Building and Closing the Delivery Manifest

For each delivery day a `WholesaleAdmin` creates a delivery manifest naming the `route_code`, the `delivery_date`, and the truck's `capacity_lbs`. A manifest begins `SCHEDULED` with `total_weight_lbs` at zero, `overweight_flag` false, and `fuel_rate_id` null. Beginning loading moves the manifest `SCHEDULED` to `LOADING` and increments its `version`; orders may be assigned in either `SCHEDULED` or `LOADING`.

Assignment attaches a `SUBMITTED` order to the manifest. The assign call names the `order_id` and carries `expected_manifest_version` per §2.7. The manifest must be in `SCHEDULED` or `LOADING`, else `ERR_MANIFEST_NOT_OPEN` (HTTP 409); its `overweight_flag` must still be false, else `ERR_MANIFEST_OVERWEIGHT` (HTTP 422); and the order must be `SUBMITTED`, else `ERR_INVALID_STATE`. On success the order's `manifest_id` is set, the order moves `SUBMITTED` to `ASSIGNED`, the manifest's `total_weight_lbs` grows by the order's `weight_lbs`, and both the manifest's and the order's `version` increment by one. Should that addition push `total_weight_lbs` above `capacity_lbs`, the manifest's `overweight_flag` flips to true — the assignment that tipped the scale still succeeds, but the flag blocks every later assignment until the manifest closes.

Closing the manifest is the pricing event for freight and stamps. The close call carries `expected_manifest_version` per §2.7 and is legal only from `LOADING`. At close the manifest locks its `fuel_rate_id` to the fuel surcharge rate whose week contains the `delivery_date`, and every `ASSIGNED` order in the manifest is stamped with its `fuel_surcharge_cents` as it moves `ASSIGNED` to `CLOSED`. The surcharge base is computed in a pinned order: start from the order's merchandise subtotal, subtract the promo allowance, then add the pick fee; the minimum-drop fee is evaluated separately and is never part of the surcharge base. The applicable rate comes from the week's `doe_index_usd`: an index below $3.50 per gallon means no surcharge at all; an index of at least $3.50 but below $4.00 selects the 2.5 percent tier — an index of exactly $3.50 included; an index of $4.00 or more selects the 4.0 percent tier. The stamped surcharge is the base multiplied by the tier rate, rounded half-up to integer cents, and once stamped it is never recomputed, even if shorts later reduce the delivery. The same close draws down stamp inventory: for each tobacco order in the manifest, the jurisdiction supply's `rolls_on_hand` is reduced by that order's rolls-needed figure from the stamp calculation. The manifest's `version` increments.

A manifest completes itself: once every non-cancelled order in it has reached `DELIVERED` or `INVOICED`, the manifest auto-transitions `CLOSED` to `COMPLETED` and increments its `version`.

### 3.6. Delivery Day: Confirmation, Shorts, and Damages

At the store door the `RouteDriver` confirms delivery of each `CLOSED` order — the manifest itself must be `CLOSED` or `COMPLETED`. Confirmation first settles quantities: each line's `delivered_cases` and `delivered_split_units` are set to the ordered quantities net of any recorded exceptions. The order's `final_total_cents` is then computed on delivered quantities: delivered merchandise less delivered promo allowances — the same per-line half-up rounding rule applied to delivered line amounts — plus delivered pick fees, plus the tax-stamp cost carried unchanged from submission, plus the fuel surcharge stamped at manifest close. Because shorts reduce delivered quantities, the final total differs from the provisional total whenever anything was shorted or damaged. An invoice is created immediately: `invoiced_total_cents` equals the `final_total_cents`, `balance_cents` equals the invoiced total, the invoice's `status` is `OPEN`, and its `due_date` derives from the retailer's terms — the delivery date itself for `COD`, seven days after the delivery date for `NET7`, fourteen days after for `NET14`. The retailer's `ar_balance_cents` grows by the invoiced total. The order moves `CLOSED` to `DELIVERED` and then, once the invoice row is persisted, the system auto-transitions it `DELIVERED` to `INVOICED`; that final step releases the order's provisional total from `exposure_forward_cents` — the order leaves the forward-looking pipeline set — and re-evaluates the retailer's `credit_status` against its limit.

When product arrives short or damaged, the driver records a delivery exception against the manifest, naming the `order_id`, the `order_line_id`, an `exception_type` of `SHORT` or `DAMAGE`, and the affected `cases_qty` and `split_units_qty`. The exception's `credit_amount_cents` is the shorted or damaged cases multiplied by the referenced line product's `case_cost_cents` plus the affected split units multiplied by its `unit_cost_cents`. An exception begins in `RECORDED` status. When the order's invoice already exists, the system additionally creates a credit memo whose `origin` matches the exception type, whose `exception_id` points back to the exception, and auto-posts it — reducing the invoice's `balance_cents` and the retailer's `ar_balance_cents` and re-evaluating `credit_status` — and the exception moves to `CREDITED`. These recorded-and-credited exceptions are precisely the quantities netted out when delivery confirmation computes delivered line quantities.

### 3.7. The Credit Desk: Invoices, Payments, and Credit Memos

Invoices are collected by a `CreditManager`. Applying a payment names an `amount_cents` that must be positive and a `method` of `CASH_ON_DELIVERY`, `CHECK`, or `ACH`; the payment is born `APPLIED`. The invoice must be in `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE`, and the amount may not exceed the invoice's `balance_cents`, else `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422). A payment smaller than the balance moves an `OPEN` invoice to `PARTIALLY_PAID` — and likewise a `PAST_DUE` invoice to `PARTIALLY_PAID` — while a payment exactly equal to the balance moves an `OPEN`, `PAST_DUE`, or `PARTIALLY_PAID` invoice to `PAID`. Every application subtracts the amount from the invoice's `balance_cents` and from the retailer's `ar_balance_cents`, then re-evaluates the retailer's `credit_status`.

Time works against unpaid invoices: when the logical clock passes an `OPEN` invoice's `due_date` while its `balance_cents` remains positive, the invoice auto-transitions `OPEN` to `PAST_DUE` and the retailer's `credit_status` is set to `CREDIT_HOLD`, blocking further submissions until the desk intervenes or the debt is satisfied.

Payments can be undone. Reversing an `APPLIED` payment marks it `REVERSED`, adds its amount back to the invoice's `balance_cents` and to the retailer's `ar_balance_cents`, and re-evaluates `credit_status`. If the reversed payment was the one that closed the invoice, the invoice returns `PAID` to `OPEN`; a reversal against a `PARTIALLY_PAID` invoice returns it to `OPEN` only when the reversal restores the balance to the full invoiced total, and otherwise the invoice remains `PARTIALLY_PAID`.

Credit memos are the second lever. A `CreditManager` drafts a memo against an invoice by naming an `origin` of `SHORT`, `DAMAGE`, or `MANUAL` and a positive `amount_cents`; the memo is born `DRAFT`, with `exception_id` null unless it originated from a delivery exception. Both at creation and at posting time, the amount may not exceed the invoice's `balance_cents`, else `ERR_MEMO_EXCEEDS_INVOICE` (HTTP 422). Posting is legal only from `DRAFT` and only while the invoice is `OPEN`, `PARTIALLY_PAID`, or `PAST_DUE`; it subtracts the amount from the invoice's `balance_cents` and the retailer's `ar_balance_cents` and re-evaluates `credit_status`, which may automatically release a `CREDIT_HOLD`. A memo that brings the balance to zero marks the invoice `PAID`. Voiding a `POSTED` memo is the compensating action: it adds the amount back to `balance_cents` and `ar_balance_cents`, re-evaluates `credit_status`, and if the invoice had reached `PAID` only because of that credit, the invoice falls back to `PARTIALLY_PAID` or `OPEN` according to its remaining payments. `DRAFT` memos awaiting posting and `VOIDED` memos carry no balance effect.

### 3.8. Slotting and New-Item Authorization

New items reach a store's guide only through authorization. A `SalesRep` files a new-item request naming the `retailer_id`, the candidate `product_id`, and a `proposed_shelf_price_cents`; the request is born `SUBMITTED` with `revision_notes` null. A `WholesaleAdmin` then takes it up, moving `SUBMITTED` to `UNDER_REVIEW`, at which point the request's `slotting_fee_cents` is computed: a base of 50,000 cents plus 250 cents for each unit in the product's `case_pack_units`, capped at 150,000 cents — the fee is the lesser of the raw figure and the cap.

Review supports negotiation rounds. The administrator may send the request back, moving `UNDER_REVIEW` to `REVISION_REQUESTED` and recording the reason in `revision_notes`; the sales rep revises and resubmits — optionally supplying a new `proposed_shelf_price_cents` — which moves `REVISION_REQUESTED` back to `SUBMITTED` and clears `revision_notes`, so the cycle can repeat as many times as the negotiation needs.

Authorization is the terminal success path: from `UNDER_REVIEW`, and only while the product's `status` is `ACTIVE`, the administrator authorizes the request, which appends a line pairing the `product_id` with a `par_cases` of zero to the store's `ACTIVE` order guide and publishes a retail price record at the `proposed_shelf_price_cents`, superseding any `ACTIVE` record for that store-product pair per §3.2. The request lands in `AUTHORIZED`. Alternatively the administrator may reject the request outright, moving `UNDER_REVIEW` to the terminal `REJECTED`.

## 4. Endpoint Definitions

Endpoints that create a new resource — a retailer, product, guide, promo, price record, window, rate, stamp supply, manifest, exception, order, payment, credit memo, or new-item request — return `201 Created`. Endpoints that modify an existing resource or drive a state transition — submit, cancel, assign, begin-loading, close, confirm-delivery, post, void, reverse, review actions, authorize, reject, credit-hold, clock-set, and retailer update — return `200 OK`. Read endpoints return `200 OK`. Request and response payloads for each operation are as specified in §3 and the principles of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/retailers` | Create a retailer account | WholesaleAdmin |
| GET | `/retailers/{id}` | Fetch a retailer | WholesaleAdmin, CreditManager, SalesRep, StoreManager |
| GET | `/retailers/{id}/credit-summary` | Computed credit posture: AR, forward exposure, aging buckets, credit status | WholesaleAdmin, CreditManager, StoreManager |
| PATCH | `/retailers/{id}` | Update credit terms, credit limit, or tobacco license | CreditManager |
| POST | `/retailers/{id}/credit-hold` | Manually place or release a credit hold | CreditManager |
| GET | `/retailers/{id}/order-guides` | List a retailer's order guides | WholesaleAdmin, SalesRep, StoreManager |
| GET | `/retailers/{id}/retail-prices` | List a retailer's retail price records, optionally filtered by `product_id` or `status` | WholesaleAdmin, SalesRep, StoreManager |
| POST | `/products` | Create a product in the item master | WholesaleAdmin |
| GET | `/products` | List products, optionally filtered by `status` or `is_tobacco` | WholesaleAdmin, SalesRep, StoreManager |
| GET | `/products/{id}` | Fetch a product | WholesaleAdmin, SalesRep, StoreManager |
| POST | `/order-guides` | Create a store order guide | SalesRep |
| GET | `/order-guides/{id}` | Fetch an order guide | WholesaleAdmin, SalesRep, StoreManager |
| POST | `/promo-events` | Create a promo/allowance event | SalesRep |
| GET | `/promo-events` | List promo events, optionally filtered by `product_id` or `status` | WholesaleAdmin, SalesRep, StoreManager |
| GET | `/promo-events/{id}` | Fetch a promo event | WholesaleAdmin, SalesRep, StoreManager |
| POST | `/retail-price-records` | Publish a maintained shelf price, superseding the prior active record | SalesRep |
| GET | `/retail-price-records` | List retail price records, optionally filtered by `retailer_id`, `product_id`, `supersedes_id`, or `status` | WholesaleAdmin, SalesRep |
| GET | `/retail-price-records/{id}` | Fetch a retail price record | WholesaleAdmin, SalesRep |
| POST | `/delivery-windows` | Create a route delivery window | WholesaleAdmin |
| GET | `/delivery-windows` | List delivery windows, optionally filtered by `route_code` | WholesaleAdmin |
| POST | `/fuel-surcharge-rates` | Publish the weekly DOE diesel index | WholesaleAdmin |
| GET | `/fuel-surcharge-rates` | List weekly fuel surcharge rates | WholesaleAdmin, SalesRep |
| POST | `/tax-stamp-supplies` | Create a jurisdiction tax-stamp supply | WholesaleAdmin |
| GET | `/tax-stamp-supplies` | List tax stamp supplies, optionally filtered by `jurisdiction_code` | WholesaleAdmin, SalesRep |
| POST | `/delivery-manifests` | Create a delivery-day manifest | WholesaleAdmin |
| GET | `/delivery-manifests` | List manifests, optionally filtered by `route_code`, `delivery_date`, or `fuel_rate_id` | WholesaleAdmin, RouteDriver |
| GET | `/delivery-manifests/{id}` | Fetch a manifest | WholesaleAdmin, RouteDriver |
| POST | `/delivery-manifests/{id}/begin-loading` | Advance a manifest from `SCHEDULED` to `LOADING` | WholesaleAdmin |
| POST | `/delivery-manifests/{id}/assign-order` | Assign a `SUBMITTED` order to a manifest | WholesaleAdmin |
| POST | `/delivery-manifests/{id}/close` | Close a manifest; stamp fuel surcharges and draw down stamp rolls | WholesaleAdmin |
| POST | `/delivery-manifests/{id}/delivery-exceptions` | Record a short/damage exception at the door | RouteDriver |
| GET | `/delivery-exceptions` | List delivery exceptions, optionally filtered by `manifest_id`, `order_id`, or `order_line_id` | WholesaleAdmin, RouteDriver, CreditManager |
| GET | `/delivery-exceptions/{id}` | Fetch a delivery exception | WholesaleAdmin, RouteDriver, CreditManager |
| POST | `/purchase-orders` | Create a draft order with lines against the store's guide | StoreManager |
| GET | `/purchase-orders` | List purchase orders, optionally filtered by `retailer_id`, `manifest_id`, `order_guide_id`, or `status` | WholesaleAdmin, SalesRep, StoreManager, RouteDriver |
| GET | `/purchase-orders/{id}` | Fetch an order | WholesaleAdmin, SalesRep, StoreManager, RouteDriver |
| GET | `/purchase-orders/{id}/lines` | List the lines of an order | WholesaleAdmin, SalesRep, StoreManager, RouteDriver |
| GET | `/order-lines` | List order lines, optionally filtered by `order_id` or `product_id` | WholesaleAdmin |
| GET | `/order-lines/{id}` | Fetch an order line | WholesaleAdmin, SalesRep, StoreManager, RouteDriver |
| POST | `/purchase-orders/{id}/submit` | Submit a draft order; runs the pricing engine and credit gate | StoreManager |
| POST | `/purchase-orders/{id}/cancel` | Cancel a draft or submitted order | StoreManager |
| POST | `/purchase-orders/{id}/confirm-delivery` | Driver confirms delivery; finalizes totals and issues the invoice | RouteDriver |
| GET | `/invoices` | List invoices, optionally filtered by `order_id`, `retailer_id`, or `status` | WholesaleAdmin, CreditManager, StoreManager |
| GET | `/invoices/{id}` | Fetch an invoice | WholesaleAdmin, CreditManager, StoreManager |
| POST | `/invoices/{id}/payments` | Apply a payment to an invoice | CreditManager |
| GET | `/invoices/{id}/payments` | List an invoice's payments | WholesaleAdmin, CreditManager |
| POST | `/invoices/{id}/credit-memos` | Create a draft credit memo against an invoice | CreditManager |
| GET | `/invoices/{id}/credit-memos` | List an invoice's credit memos | WholesaleAdmin, CreditManager |
| GET | `/credit-memos` | List credit memos, optionally filtered by `invoice_id`, `exception_id`, or `status` | WholesaleAdmin, CreditManager |
| GET | `/credit-memos/{id}` | Fetch a credit memo | WholesaleAdmin, CreditManager |
| POST | `/credit-memos/{id}/post` | Post a draft credit memo against its invoice | CreditManager |
| POST | `/credit-memos/{id}/void` | Void a posted credit memo | CreditManager |
| POST | `/payments/{id}/reverse` | Reverse an applied payment | CreditManager |
| POST | `/new-item-requests` | File a slotting / new-item authorization request | SalesRep |
| GET | `/new-item-requests` | List new-item requests, optionally filtered by `retailer_id`, `product_id`, or `status` | WholesaleAdmin, SalesRep |
| GET | `/new-item-requests/{id}` | Fetch a new-item request | WholesaleAdmin, SalesRep |
| POST | `/new-item-requests/{id}/start-review` | Move a request from `SUBMITTED` to `UNDER_REVIEW` and compute the slotting fee | WholesaleAdmin |
| POST | `/new-item-requests/{id}/request-revision` | Move a request from `UNDER_REVIEW` to `REVISION_REQUESTED` | WholesaleAdmin |
| POST | `/new-item-requests/{id}/resubmit` | Move a request from `REVISION_REQUESTED` back to `SUBMITTED` | SalesRep |
| POST | `/new-item-requests/{id}/authorize` | Authorize the item: add it to the order guide and publish its price record | WholesaleAdmin |
| POST | `/new-item-requests/{id}/reject` | Reject the request | WholesaleAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | WholesaleAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MANIFEST_NOT_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TOBACCO_LICENSE_MISSING` | 422 |
| `ERR_TAX_STAMP_UNAVAILABLE` | 422 |
| `ERR_ORDER_CUTOFF_PASSED` | 422 |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 |
| `ERR_PRODUCT_NOT_ON_GUIDE` | 422 |
| `ERR_SPLIT_CASE_NOT_ALLOWED` | 422 |
| `ERR_MANIFEST_OVERWEIGHT` | 422 |
| `ERR_MEMO_EXCEEDS_INVOICE` | 422 |
| `ERR_CREDIT_HOLD` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_RATE_WEEK` | 409 |
| `ERR_DUPLICATE_JURISDICTION` | 409 |
| `ERR_GUIDE_DAY_MISMATCH` | 422 |
