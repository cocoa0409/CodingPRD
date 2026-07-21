# Luggage & Travel-Goods Store API — Product Requirements Document

## 1. Introduction

The Luggage & Travel-Goods Store API is the back-office and self-service platform for a specialty retailer that sells hard-shell cases, soft-side bags, backpacks, duffels, and travel accessories, and that stands behind them long after the sale. A single customer relationship may span a purchase, a warranty registration, a wheel or handle or zipper repair years later, a monogram commissioned as a gift, a loyalty tier earned over many orders, a trade-in of an older case, and — should a defect surface across a whole model line — a product recall. The platform's purpose is to hold all of these threads together with consistent money, consistent loyalty accounting, and consistent state.

This document specifies the complete contract for that platform. It describes every resource the system persists, the lifecycle each resource moves through, the financial and loyalty calculations that must be reproduced to the cent and to the point, the cascades that ripple through registrations and open orders when a product is recalled, and the concurrency guards that keep two operators from silently overwriting one another. The reader is the engineer who will build the service; the narrative is deliberately organized around business workflows rather than around a database schema, and the rules governing any one operation are frequently stated in the section where they make business sense rather than gathered into a single block.

The service is mounted under the `/store` path prefix. It additionally exposes one administrative test-driving capability, described in §2.5, that controls the logical clock all temporal rules read from.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes three roles: `Customer`, `Associate`, and `Manager`.

A `Customer` is an entity-backed, self-service account holder. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare that resource's `customer_id` (or, for a warranty claim, the `customer_id` of the registration's owner, and for a repair line or sales-order line, the owning order's `customer_id`) to `X-User-ID`. A `Customer` may create and read their own warranty registrations, warranty claims, repair orders, sales orders, sales-order lines, and special orders; may approve or decline their own repair-order quotes; may decline their own trade-in offers; and may read products, airlines, and recall notices. Any attempt by a `Customer` to read or act on another customer's resource is rejected with `ERR_FORBIDDEN`. For collection (list) endpoints the `Customer`'s view is instead silently narrowed to the resources they own rather than rejected, while catalog and reference lists — products, airlines, and recall notices — are returned unfiltered to every permitted role.

An `Associate` is store staff handling day-to-day operations. When `X-User-Role` is `Associate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record or log it but never compares it to any resource's `id`. An `Associate` handles quoting, scheduling, starting, holding for parts, resuming, marking ready, and closing repairs; reviewing, requesting information on, and resubmitting warranty claims; capturing, fulfilling, and cancelling sales orders; scheduling, starting, and completing monograms; sourcing, marking arrived, fulfilling, and cancelling special orders; creating trade-in offers; and creating catalog and account records.

A `Manager` is a supervisor whose permissions are a superset of the `Associate`'s (a hierarchical override — anything an `Associate` may do, a `Manager` may do) plus fiscal and compliance exclusives: publishing and closing recall notices, discontinuing products, resolving warranty claims, voiding registrations, accepting and voiding trade-ins, refunding sales orders, and setting the logical clock. Like the `Associate`, when `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range or non-numeric values are clamped rather than rejected: a `limit` above 100 becomes 100, a `limit` below 1 becomes 1, a negative `offset` becomes 0, and an unparseable `limit` or `offset` falls back to its default.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order; resources sharing an identical `created_at` are further ordered by their creation sequence (insertion order). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Versioning, and Audit Fields

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 (or its initial persisted value) and increments by one on every mutation, including mutations to computed or derived fields; it is the anchor for optimistic concurrency control described in §2.7.

Three resource types are lightweight reference records that are immutable after creation and therefore carry **only** `id` and `created_at`: airlines, service benches, and monogram stations all omit `updated_at` and `version` entirely. Every other resource type in this system carries the full `id`, `created_at`, `updated_at`, and `version` set.

Whenever a rule in this document says an operation "bumps the version" or "refreshes `updated_at`" of a resource, it means exactly this: the affected resource's `version` increments by one and its `updated_at` advances to the current logical time. A single operation that mutates several resources (for example a recall cascade) independently bumps each one it touches.

### 2.5. The Logical Clock and Temporal Rules

Every temporal comparison in this system — warranty expiry, trade-in offer expiry, and the timestamps stamped onto records — reads from a single logical clock rather than the server's wall clock. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any client sets it, the clock returns exactly this default and never falls back to real-world time. A `Manager` may advance or reset the clock by supplying a target instant in the `to_iso8601` field of the clock-control capability. Once set, the clock holds that value for all subsequent temporal rules until it is set again.

### 2.6. Monetary and Numeric Precision

All monetary amounts are stored and returned as integer cents; there are no fractional cents and no floating-point currency values in responses. Wherever a calculation multiplies by a rate, a discount factor, a condition factor, or a tax rate and the intermediate product is not a whole number of cents, the result is rounded to the nearest whole cent using the round-half-up convention (a value ending in exactly one-half cent rounds up). Where a calculation specifies that per-line amounts are rounded before they are summed, that ordering is load-bearing: each line is rounded to whole cents first, and only the rounded line amounts are added together.

Loyalty points are whole integers. Where a points formula divides or multiplies, the flooring described in §3.2 applies — never round-half-up for points.

### 2.7. Optimistic Concurrency Control

Two write operations in this system require the client to prove it has observed the current state of a parent resource before it mutates around it. These operations carry a non-optional expected-version field, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a warranty claim requires `expected_warranty_registration_version`, which must equal the current `version` of the target `WarrantyRegistration`. Because creating a claim legitimately supersedes any prior non-terminal claim on that registration and bumps the registration's `version`, a client whose `expected_warranty_registration_version` is behind the registration's current `version` has not seen the prior claim creation and would otherwise silently supersede a claim it never observed; its create is therefore rejected with `ERR_STALE_VERSION`.

Creating a trade-in offer requires `expected_customer_version`, which must equal the current `version` of the target `Customer`. Creating an offer bumps the customer's `version` (because a new offer supersedes any prior open offer for the same customer and product), so a client presenting a stale `expected_customer_version` is rejected with `ERR_STALE_VERSION`. No other endpoint in the system accepts an expected-version field.

### 2.8. Validation Order and Existence Checking

When more than one condition could reject a request, the system evaluates them in a fixed order and returns the first failure. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the operation, and an entity-backed `Customer` acts only on its own resources, else `ERR_FORBIDDEN` (403).
3. **Existence** — every path `id` and every body foreign key resolves to an existing resource, validated left to right in the order they appear; the first unresolved identifier yields `ERR_NOT_FOUND` (404).
4. **State validity** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
5. **Product-recall safety** — the referenced product is not `RECALLED` where that is forbidden, else `ERR_PRODUCT_RECALLED` (409).
6. **Registration active** — a warranty-claim action targets a registration in `ACTIVE` status, else `ERR_REGISTRATION_NOT_ACTIVE` (409).
7. **Warranty not expired** — a claim review occurs before the registration's warranty expiry, else `ERR_WARRANTY_EXPIRED` (409).
8. **Offer not expired** — a trade-in accept occurs before the offer's expiry, else `ERR_OFFER_EXPIRED` (409).
9. **Repair lines present** — a repair quote has at least one line, else `ERR_NO_REPAIR_LINES` (422).
10. **Schedule conflict** — a bench or monogram-station window does not conflict, else `ERR_SCHEDULE_CONFLICT` (409).
11. **Uniqueness** — unique constraints hold, else `ERR_DUPLICATE` (409).
12. **Order captured** — a monogram may start only once its order's payment is captured, else `ERR_ORDER_NOT_CAPTURED` (409).
13. **Monograms complete** — an order may be fulfilled only when every monogrammed line is finished, else `ERR_MONOGRAM_PENDING` (409).
14. **Registration concurrency** — `expected_warranty_registration_version` matches, else `ERR_STALE_VERSION` (412).
15. **Customer concurrency** — `expected_customer_version` matches, else `ERR_STALE_VERSION` (412).
16. **Request well-formedness** — required fields are present and every enum value is a member of its declared set, else `ERR_INVALID_REQUEST` (422).
17. **Numeric ranges** — quantities are at least one, money fields are non-negative, and per-line discount fractions lie between zero and one inclusive, else `ERR_VALIDATION_RANGE` (422).

The left-to-right existence rule means that for an operation whose body carries several foreign keys, the earliest-listed key that fails to resolve determines the `ERR_NOT_FOUND`. Path identifiers are checked before body identifiers. The `Customer` ownership component of step 2 is enforced at step 2 only when a body field names the customer directly; when ownership can be read only from a resolved resource — a path target, or a parent named by a body foreign key — it is enforced immediately after that resource passes its existence check, so an as-yet-unresolved foreign key's `ERR_NOT_FOUND` (step 3) can precede that ownership `ERR_FORBIDDEN`.

### 2.9. Recall Cascades and Hierarchical Consistency

Several operations mutate more than one resource in a single logical step, and the system guarantees these cascades run to completion, each affected resource independently having its `version` bumped and `updated_at` refreshed. The most far-reaching is the recall cascade, detailed in §3.8: publishing a recall drives the owning product into `RECALLED`, which in turn flags active registrations, which in turn move certain open claims into a needs-information state, and which also cancels open special orders for that product. Closing the recall reverts the product and its flagged registrations. Wherever this document describes a side effect on a second resource, that side effect is part of the contract of the operation and is not optional.

### 2.10. Bench and Station Scheduling Semantics

Two independent scheduling surfaces exist, and they use deliberately different interval conventions. A **service bench** hosts repair work; a repair scheduled onto a bench occupies the half-open window from its start (inclusive) to its end (exclusive). Two repairs conflict on the same bench when their half-open windows overlap; adjacency, where one window's end instant equals the next window's start instant, is allowed and is not a conflict. A **monogram station** hosts personalization work; a monogram scheduled onto a station occupies a window that, for conflict purposes, is treated as a closed interval expanded on both sides by a buffer of `STATION_BUFFER_MIN` minutes, where `STATION_BUFFER_MIN` is 15 minutes. Two monograms conflict on the same station when, after each occupied window is padded by 15 minutes before its start and after its end, the padded intervals intersect (a closed-interval intersection: touching at a single instant after padding counts as a conflict). In both cases a conflict is reported as `ERR_SCHEDULE_CONFLICT`, and only occupations in live states are considered — for benches, other repairs in `SCHEDULED`, `IN_REPAIR`, or `PARTS_HOLD`; for stations, other lines in `SCHEDULED` or `IN_PROGRESS`.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Products, Airlines, and the Fit Guide

The catalog begins with the **product**, a model the store sells and services. A product is created by an `Associate` or a `Manager` with a `sku`, a `name`, a `category`, a list price in `msrp_cents`, a `warranty_months` coverage length, and three exterior measurements in millimetres: `length_mm`, `width_mm`, and `height_mm`. The `category` is one of `HARD_SHELL`, `SOFT_SIDE`, `BACKPACK`, `DUFFEL`, or `ACCESSORY`. All of `msrp_cents`, `warranty_months`, `length_mm`, `width_mm`, and `height_mm` must be non-negative integers, and a violation is rejected as `ERR_VALIDATION_RANGE`. A new product begins life in `status` `ACTIVE`.

The `sku` must be unique, but only among products whose `status` is `ACTIVE` or `RECALLED`; a `sku` belonging to a `DISCONTINUED` product may be reused, and any attempt to create a product whose `sku` collides with an existing `ACTIVE` or `RECALLED` product is rejected with `ERR_DUPLICATE`. A product moves through three states: it starts `ACTIVE`, may be driven to `RECALLED` and back by the recall process of §3.8, and may be permanently retired to `DISCONTINUED` by a `Manager`, but only from `ACTIVE` — discontinuing a product that is not `ACTIVE` (one already `RECALLED` or `DISCONTINUED`) is refused with `ERR_INVALID_STATE`, evaluated before the open-special-order guard. Retirement to `DISCONTINUED` is refused with `ERR_OPEN_SPECIAL_ORDER` while any special order in `REQUESTED`, `SOURCED`, or `ARRIVED` still references the product; once discontinued, the product is nonetheless not hard-blocked from new sales-order lines or new registrations (the system enforces no such exclusion and emits no dedicated error for referencing a `DISCONTINUED` product), and `DISCONTINUED` is terminal.

Airlines exist in the catalog purely to power a size guide. An **airline** profile is created with an `iata_code`, a `name`, and four inclusive limits in millimetres: `carry_on_max_length_mm`, `carry_on_max_width_mm`, `carry_on_max_height_mm`, and `checked_linear_limit_mm`, each a non-negative integer. Airlines are immutable reference records and, per §2.4, carry only `id` and `created_at`.

The **fit guide** is a computed read that answers, for one product against one airline, whether the bag fits. The caller supplies the `airline_id` of the airline to compare against. The product fits as carry-on when its `length_mm` is less than or equal to the airline's `carry_on_max_length_mm`, **and** its `width_mm` is less than or equal to `carry_on_max_width_mm`, **and** its `height_mm` is less than or equal to `carry_on_max_height_mm`; every boundary is inclusive, so exact equality on a dimension still fits. The linear dimension is the sum of the product's `length_mm`, `width_mm`, and `height_mm`, and the product fits as checked baggage when that linear sum is less than or equal to the airline's `checked_linear_limit_mm`, again inclusive at the boundary. The read returns the two boolean verdicts and the computed linear measurement as the fields `fits_carry_on`, `fits_checked`, and `linear_mm`.

### 3.2. Customers and the Loyalty Program

A **customer** is a loyalty account, created by an `Associate` or `Manager` with an `email` and a `full_name`. The `email` is globally unique across all customers; a collision is rejected with `ERR_DUPLICATE`. A new customer starts in the `BRONZE` `tier` with a `lifetime_spend_cents` of zero, a `points_balance` of zero, and a `store_credit_cents` of zero. The four tiers, in ascending order, are `BRONZE`, `SILVER`, `GOLD`, and `PLATINUM`, and a customer's `tier` is derived from `lifetime_spend_cents` crossing the configured spend thresholds for each tier. The thresholds, in cents of lifetime spend, are `BRONZE` at 0, `SILVER` at 50000, `GOLD` at 150000, and `PLATINUM` at 500000; a customer's `tier` is the highest tier whose threshold is less than or equal to their `lifetime_spend_cents` (so exactly 50000 lifetime is `SILVER`, exactly 150000 is `GOLD`, exactly 500000 is `PLATINUM`). As lifetime spend accumulates and crosses the next tier's threshold, the customer is upgraded to that tier.

The **loyalty ledger** is maintained entirely as side effects of other operations; a customer's `tier`, `lifetime_spend_cents`, `points_balance`, and `store_credit_cents` are computed fields the client never sets directly. Lifetime spend rises by the net merchandise total of each captured sales order — the subtotal after the loyalty discount, excluding tax and gift wrap — and falls back by the same amount when that order is later refunded. The `points_balance` is credited when a sale is captured and debited when it is refunded, and it must always equal the sum of points earned on captured orders minus the sum reversed on refunded orders. The `store_credit_cents` is credited when a trade-in is accepted and debited when an accepted trade-in is voided, and it must always equal the sum of the offer amounts of trade-ins that are accepted and not voided. Repairs that the customer pays for also earn points, as described in §3.4.

Points accrual on a sales order is computed twice with the same arithmetic but from two different tier readings. The net merchandise base is the order's subtotal minus its loyalty discount. That base is divided by 100 and floored to a whole number of hundred-cent units (each whole 100 cents earns one point at base rate). That whole number is then multiplied by the tier multiplier — `BRONZE` earns 1.00 times, `SILVER` 1.25 times, `GOLD` 1.50 times, and `PLATINUM` 2.00 times — and the product is floored again to a whole number of points. At order creation this is computed using the customer's tier **at creation time** and stored as `provisional_points`, a non-binding estimate that is not added to the balance. At payment capture it is recomputed using the customer's tier **at capture time**, which may be higher if intervening activity upgraded the customer; that final figure is stored as `points_credited` and added to `points_balance`. Until capture, `points_credited` is zero.

### 3.3. Warranty Registration and Claims

When a customer registers a purchased unit, a **warranty registration** is created against a `product_id` and a `customer_id`, carrying the unit's `serial_number` and the `purchase_date` on which the warranty clock starts. The `serial_number` must be unique among registrations of the same `product_id` — the same serial may legitimately recur across different products — and a duplicate within one product is rejected with `ERR_DUPLICATE`. At creation the system computes `warranty_expiry` by adding the product's `warranty_months` whole calendar months to `purchase_date`, preserving the exact time-of-day instant of the purchase; `warranty_expiry` is serialized as an ISO 8601 UTC timestamp with three fractional digits, consistent with the datetime convention of §2.2 and §2.4 (so a midnight instant is emitted as, e.g., `2028-06-01T00:00:00.000Z`). A registration begins `ACTIVE`; it may be flagged `RECALL_FLAGGED` by a recall (§3.8) and reverted, and a `Manager` may retire it to `VOID`, but only from `ACTIVE` — voiding a registration that is not `ACTIVE` is refused with `ERR_INVALID_STATE`, evaluated before the open-claim guard. Voiding is refused with `ERR_CLAIM_OPEN_ON_REGISTRATION` while any claim on the registration sits in `UNDER_REVIEW` or `NEEDS_INFO`; claim creation itself is not guarded by registration status (a new claim may be opened even on a `VOID` or `RECALL_FLAGGED` registration — the `ACTIVE` requirement is enforced only when a claim is later reviewed or resolved), and `VOID` is terminal.

A **warranty claim** opens against a `registration_id` and reports a `defect_type` — one of `WHEEL`, `HANDLE`, `ZIPPER`, `SHELL`, `LINING`, or `OTHER` — together with a free-text `description`. Because a claim's creation is guarded by optimistic concurrency, the request must also carry `expected_warranty_registration_version` matching the registration's current `version`, as described in §2.7. Creating a claim supersedes the registration's prior open claim: any existing claim on the same registration that is still in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO` is closed to `SUPERSEDED`, and the registration's `version` is incremented by one. The new claim starts `SUBMITTED`, and its `resolution` is null while open.

The claim lifecycle is a small cycle attended by staff. An `Associate` begins review, moving `SUBMITTED → UNDER_REVIEW`; this is permitted only when the underlying registration is `ACTIVE` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`, so a claim on a recall-flagged or voided registration cannot enter review) and only when the logical clock is strictly before the registration's `warranty_expiry` (otherwise `ERR_WARRANTY_EXPIRED`). From `UNDER_REVIEW`, an `Associate` may request more information, moving `UNDER_REVIEW → NEEDS_INFO`; from `NEEDS_INFO`, an `Associate` resubmits to move `NEEDS_INFO → UNDER_REVIEW`, and this pair may cycle any number of times. A `Manager` resolves a claim only from `UNDER_REVIEW`. Supplying a `resolution` of `REPAIR` or `REPLACE` moves the claim `UNDER_REVIEW → RESOLVED` and additionally requires the registration to still be `ACTIVE` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`); supplying a `resolution` of `REJECT` moves the claim `UNDER_REVIEW → REJECTED`. The three states `RESOLVED`, `REJECTED`, and `SUPERSEDED` are terminal. A resolution of `REPAIR` is what later entitles a repair to be treated as warranty-covered, per §3.4.

### 3.4. Repair Services

A **repair order** is opened against a `customer_id` and a `product_id`, optionally carrying a `claim_id` that ties the repair to a resolved warranty claim. The order's `pay_mode` is derived, never supplied: it is `WARRANTY_COVERED` when a `claim_id` is present and that claim's `resolution` is `REPAIR`, and it is `CUSTOMER_PAY` in every other case, including when no `claim_id` is given. It is derived at order creation and re-derived again at quote time from the linked claim's `resolution` as it then stands. A new order starts in `INTAKE` with a `quoted_total_cents` and a `warranty_cost_cents` of zero, and with `bench_id`, `bench_start`, and `bench_end` unset until scheduling.

The work to be done is itemized as **repair lines**, each added to an `INTAKE` order by its `repair_order_id` (adding a line to an order in any other state is rejected with `ERR_INVALID_STATE`) and describing a `repair_type` (one of `WHEEL`, `HANDLE`, `ZIPPER`, or `OTHER`), an estimate of `labor_hours`, a `complexity` band that is either `STANDARD` (the default when omitted) or `COMPLEX`, and a `parts_cost_cents` figure. Labor hours must be non-negative and parts cost non-negative, else `ERR_VALIDATION_RANGE`. A line's `line_labor_cents` and `line_total_cents` remain zero until the order is quoted.

Quoting an order — moving it `INTAKE → QUOTED`, an `Associate` action — requires at least one repair line to exist (otherwise `ERR_NO_REPAIR_LINES`) and requires the product not to be `RECALLED` (otherwise `ERR_PRODUCT_RECALLED`). The quote is computed line by line. For each line, a raw labor figure is formed by multiplying the hourly rate for its `repair_type` by its `labor_hours` and by the complexity multiplier, then rounding half-up to whole cents. The hourly rates are 3500 cents for `WHEEL`, 4000 cents for `HANDLE`, 3000 cents for `ZIPPER`, and 4500 cents for `OTHER`; the complexity multiplier is 1.0 for `STANDARD` and 1.5 for `COMPLEX`. That rounded raw figure is then clamped into `line_labor_cents` so that it is never below the labor floor of 1500 cents and never above the labor ceiling of 20000 cents — that is, the labor charged is the raw figure, but not less than 1500 and not more than 20000. The line's `line_total_cents` is its clamped `line_labor_cents` plus its `parts_cost_cents`. The lines total is the sum of every line's `line_total_cents`. For a `CUSTOMER_PAY` order, `quoted_total_cents` is the lines total plus a diagnostic fee of 2500 cents, and `warranty_cost_cents` is zero. For a `WARRANTY_COVERED` order, the customer owes nothing, so `quoted_total_cents` is zero, the diagnostic fee is waived, and `warranty_cost_cents` records the lines total as the store's internal cost.

Once quoted, the customer decides. A `Customer` (or a `Manager` acting for them) approves the quote, moving `QUOTED → APPROVED`, which is again refused with `ERR_PRODUCT_RECALLED` should the product have been recalled in the interim; or declines it, moving `QUOTED → DECLINED`, which is terminal. An approved order is scheduled by an `Associate` onto a bench, moving `APPROVED → SCHEDULED`; the request supplies the `bench_id`, the `bench_start`, and the `bench_end`, the start must be strictly before the end (otherwise `ERR_INVALID_REQUEST`), and the bench window must not conflict with another repair per the half-open bench semantics of §2.10 (otherwise `ERR_SCHEDULE_CONFLICT`). Work then proceeds `SCHEDULED → IN_REPAIR` when the bench begins, may loop `IN_REPAIR → PARTS_HOLD` and back `PARTS_HOLD → IN_REPAIR` as many times as parts availability dictates, and reaches `IN_REPAIR → READY` when the item is ready for pickup. An `Associate` closes a ready order, moving `READY → CLOSED`; at close, and only for a `CUSTOMER_PAY` order, the customer earns loyalty points equal to the `quoted_total_cents` divided by 100 and floored to a whole number, which are added to their `points_balance`; because a customer's `tier` is derived from `lifetime_spend_cents` alone and a repair close does not change lifetime spend, these points never move the customer's `tier`. `DECLINED`, `CLOSED`, and `CANCELLED` are the terminal repair states.

### 3.5. Sales Orders, Monograms, and Fulfillment

A **sales order** captures a purchase. It is opened against a `customer_id`, optionally flagged `is_gift` (default false) and carrying an optional `gift_message`. A fresh order carries two independent status axes: a `payment_status` that starts `PENDING` and a `fulfillment_status` that starts `UNFULFILLED`. Its money fields — `subtotal_cents`, `loyalty_discount_cents`, `tax_cents`, `gift_wrap_fee_cents`, `total_cents` — and its `provisional_points` and `points_credited` all start at zero and are recomputed as lines are added.

Each **sales-order line** is added to a `PENDING` order by its `sales_order_id` (adding a line to an order whose `payment_status` is not `PENDING` is rejected with `ERR_INVALID_STATE`) and names the `product_id` purchased, a `unit_price_cents`, a `qty` of at least one, an optional per-line discount `line_discount_pct` between zero and one inclusive (default zero), and an optional `monogram_text`. Quantities below one, negative money, or a discount outside the zero-to-one range are rejected with `ERR_VALIDATION_RANGE`. When `monogram_text` is present the line acquires a `monogram_fee_cents` of 1200 cents and its `monogram_status` begins at `QUEUED`; when absent, the monogram fee is zero and `monogram_status` is `NONE`. A line's `monogram_station_id`, `monogram_start`, and `monogram_end` are unset until a station window is reserved.

Order pricing is recomputed whenever the line set changes, and the rounding order is pinned. For each line, the base is the `unit_price_cents` multiplied by `qty` and by one minus the `line_discount_pct`, rounded half-up to whole cents, and then the line's `monogram_fee_cents` is added to produce its `line_subtotal_cents`. The order's `subtotal_cents` is the sum of the rounded per-line subtotals. The `loyalty_discount_cents` is the subtotal multiplied by the tier discount fraction for the customer's tier at order-creation time — `BRONZE` 0.00, `SILVER` 0.05, `GOLD` 0.10, `PLATINUM` 0.15 — rounded half-up. The taxable base is the subtotal minus the loyalty discount, and `tax_cents` is that taxable base multiplied by the tax rate of 0.08, rounded half-up. The `gift_wrap_fee_cents` is 800 cents when the order is a gift and zero otherwise. The `total_cents` is the taxable base plus the tax plus the gift-wrap fee. The order's `provisional_points` is the accrual estimate of §3.2 computed at this point from the tier at creation.

Payment is captured by an `Associate`, moving the payment axis `PENDING → CAPTURED`. Capture requires at least one line (a capture on an order with no lines is rejected with `ERR_INVALID_STATE`) and requires that no line references a `RECALLED` product (otherwise `ERR_PRODUCT_RECALLED`). At capture the final points accrual runs using the customer's tier at capture time; the result is stored in `points_credited` and added to the customer's `points_balance`, and the net merchandise (subtotal minus loyalty discount) is added to the customer's `lifetime_spend_cents`, which may cross a tier threshold and upgrade the customer. A `Manager` may refund a captured order, moving `CAPTURED → REFUNDED`; the refund subtracts the previously credited `points_credited` from `points_balance` and subtracts the same net merchandise from `lifetime_spend_cents`, conserving both invariants.

The fulfillment axis evolves independently of payment. An `Associate` fulfills an order, moving `UNFULFILLED → FULFILLED`, but only when the order's payment is `CAPTURED` (attempting to fulfill an order whose payment is not `CAPTURED` is rejected with `ERR_INVALID_STATE`) and every line bearing a `monogram_text` has reached `monogram_status` `DONE`; a monogrammed line still in progress blocks fulfillment with `ERR_MONOGRAM_PENDING`. Alternatively an `Associate` cancels an unfulfilled order, moving `UNFULFILLED → CANCELLED`.

A monogrammed line runs its own sub-lifecycle. From `QUEUED`, an `Associate` reserves a station window, moving `QUEUED → SCHEDULED`; the request supplies the `monogram_station_id`, the `monogram_start`, and the `monogram_end`, the start must be strictly before the end (otherwise `ERR_INVALID_REQUEST`), and the window must clear the buffered station-overlap check of §2.10 (otherwise `ERR_SCHEDULE_CONFLICT`). From `SCHEDULED`, an `Associate` begins the work, moving `SCHEDULED → IN_PROGRESS`, but only if the parent order's payment is `CAPTURED` (otherwise `ERR_ORDER_NOT_CAPTURED`). From `IN_PROGRESS`, completing the work moves the line `IN_PROGRESS → DONE`, the terminal monogram state. A station's `method` is one of `EMBOSS`, `HEATSTAMP`, or `ENGRAVE`, and a station, like a bench, is created by a `Manager` with a `label` identifying it and is an immutable reference record.

Service benches are created likewise: a `Manager` creates a **service bench** with a `label` and a `skill` that is one of `WHEEL`, `HANDLE`, `ZIPPER`, or `GENERAL`, identifying the repair specialty the bench handles.

### 3.6. Trade-Ins

A customer may trade an older unit toward store credit. A **trade-in** offer is created by an `Associate` or `Manager` against a `customer_id` and the `product_id` of the model being surrendered, assessing its `condition` as one of `LIKE_NEW`, `GOOD`, `FAIR`, or `POOR`. Because offers supersede one another, creation is guarded by optimistic concurrency and must carry `expected_customer_version` matching the customer's current `version` (§2.7). Creating a new offer supersedes any prior offer for the same customer and product that is still `OFFERED`, closing it to `SUPERSEDED`, and increments the customer's `version` by one.

The offer amount is computed at creation. A raw value is the product's `msrp_cents` multiplied by the condition factor — 0.40 for `LIKE_NEW`, 0.30 for `GOOD`, 0.20 for `FAIR`, and 0.10 for `POOR` — rounded half-up to whole cents. The `offer_amount_cents` is that raw value, but never less than the minimum trade value of 500 cents. The offer's `expires_at` is set to 14 days after its `created_at`. A new offer begins in `OFFERED`.

An offer's fate is one of several. A `Manager` accepts it, moving `OFFERED → ACCEPTED`, but only while the logical clock is strictly before `expires_at`; accepting adds the `offer_amount_cents` to the customer's `store_credit_cents`. If a `Manager` attempts to accept after expiry — when the clock is at or past `expires_at` — the offer is auto-expired on that touch, transitioning `OFFERED → EXPIRED`, and the accept is rejected with `ERR_OFFER_EXPIRED`. A `Customer` (or staff) may decline an open offer, moving `OFFERED → DECLINED`. A `Manager` may void an already-accepted offer, moving `ACCEPTED → VOIDED`, which subtracts the `offer_amount_cents` back out of the customer's `store_credit_cents`, restoring the store-credit invariant. `DECLINED`, `EXPIRED`, `VOIDED`, and `SUPERSEDED` are all terminal.

### 3.7. Special Orders

When a customer wants a model the store does not stock, a **special order** is raised against a `customer_id` and a `product_id`, specifying a `quantity` of at least one and an optional up-front `deposit_cents` (default zero, and non-negative). A quantity below one or a negative deposit is rejected with `ERR_VALIDATION_RANGE`. A special order begins `REQUESTED`. An `Associate` begins sourcing, moving `REQUESTED → SOURCED`, which requires the product not to be `RECALLED` (otherwise `ERR_PRODUCT_RECALLED`); marks stock arrived, moving `SOURCED → ARRIVED`; and hands the goods over, moving `ARRIVED → FULFILLED`. A special order in `REQUESTED` or `SOURCED` may be cancelled, moving to `CANCELLED`, either explicitly by an `Associate` or automatically by the recall cascade of §3.8. `FULFILLED` and `CANCELLED` are terminal.

### 3.8. Recalls and Their Cascades

A **recall notice** is the compliance instrument for pulling a defective model. A `Manager` drafts one against a `product_id`, recording a `reason` and a proposed `remedy` that is one of `REPAIR`, `REPLACE`, or `REFUND`. A draft begins in `DRAFT`.

Publishing a recall — a `Manager` action moving the notice `DRAFT → PUBLISHED` — is permitted only when the notice is `DRAFT` and the owning product is currently `ACTIVE`, and it sets off the system's deepest cascade. First, the owning product transitions `ACTIVE → RECALLED`. That product transition cascades in two directions. Every warranty registration for that product that is currently `ACTIVE` is flagged, transitioning `ACTIVE → RECALL_FLAGGED`; and for each such newly flagged registration, every claim on it that sits in `SUBMITTED` or `UNDER_REVIEW` is moved to `NEEDS_INFO`. Separately, every special order for that product that is in `REQUESTED` or `SOURCED` is cancelled, moving to `CANCELLED`. Each resource touched by this cascade independently has its `version` bumped and `updated_at` refreshed.

Closing a recall — a `Manager` action moving the notice `PUBLISHED → CLOSED` — reverses the product-level effects. The owning product transitions `RECALLED → ACTIVE`, and every registration for that product still in `RECALL_FLAGGED` is reverted, transitioning `RECALL_FLAGGED → ACTIVE`. A published recall is the mechanism by which a product sits in `RECALLED`, and while a product is `RECALLED` the safety checks of §2.8 block quoting and approving its repairs, capturing sales orders that include it, and sourcing special orders for it. `CLOSED` is terminal for a recall notice, as is `DISCONTINUED` reached separately by the product's own retirement path.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read a resource or drive an existing resource through a state transition return `200 OK`. All endpoints are mounted under the `/store` prefix except the administrative clock capability.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | Manager |
| POST | `/store/products` | Create a catalog product | Manager, Associate |
| GET | `/store/products/{id}` | Fetch a product | Manager, Associate, Customer |
| GET | `/store/products` | List products (filter by category, status) | Manager, Associate, Customer |
| GET | `/store/products/{id}/airline-fit` | Compute carry-on / checked fit against an airline | Manager, Associate, Customer |
| POST | `/store/products/{id}/discontinue` | Discontinue a product | Manager |
| POST | `/store/airlines` | Create an airline size profile | Manager, Associate |
| GET | `/store/airlines/{id}` | Fetch an airline | Manager, Associate, Customer |
| GET | `/store/airlines` | List airlines | Manager, Associate, Customer |
| POST | `/store/customers` | Create a customer | Manager, Associate |
| GET | `/store/customers/{id}` | Fetch a customer | Manager, Associate, Customer |
| GET | `/store/customers` | List customers | Manager, Associate |
| POST | `/store/warranty-registrations` | Register a unit's warranty | Manager, Associate, Customer |
| GET | `/store/warranty-registrations/{id}` | Fetch a registration | Manager, Associate, Customer |
| GET | `/store/warranty-registrations` | List/filter registrations | Manager, Associate, Customer |
| POST | `/store/warranty-registrations/{id}/void` | Void a registration | Manager |
| POST | `/store/warranty-claims` | Open a warranty claim (OCC-guarded) | Manager, Associate, Customer |
| GET | `/store/warranty-claims/{id}` | Fetch a claim | Manager, Associate, Customer |
| GET | `/store/warranty-claims` | List/filter claims | Manager, Associate, Customer |
| POST | `/store/warranty-claims/{id}/review` | Begin review | Manager, Associate |
| POST | `/store/warranty-claims/{id}/request-info` | Request more info | Manager, Associate |
| POST | `/store/warranty-claims/{id}/resubmit` | Resubmit info | Manager, Associate |
| POST | `/store/warranty-claims/{id}/resolve` | Resolve a claim | Manager |
| POST | `/store/repair-orders` | Open a repair order | Manager, Associate, Customer |
| GET | `/store/repair-orders/{id}` | Fetch a repair order | Manager, Associate, Customer |
| GET | `/store/repair-orders` | List/filter repair orders | Manager, Associate, Customer |
| POST | `/store/repair-orders/{id}/quote` | Compute and set the quote | Manager, Associate |
| POST | `/store/repair-orders/{id}/approve` | Approve the quote | Customer, Manager |
| POST | `/store/repair-orders/{id}/decline` | Decline the quote | Customer, Manager |
| POST | `/store/repair-orders/{id}/schedule` | Assign a bench and window | Manager, Associate |
| POST | `/store/repair-orders/{id}/start` | Begin work | Manager, Associate |
| POST | `/store/repair-orders/{id}/parts-hold` | Hold for parts | Manager, Associate |
| POST | `/store/repair-orders/{id}/resume` | Resume work | Manager, Associate |
| POST | `/store/repair-orders/{id}/ready` | Mark ready for pickup | Manager, Associate |
| POST | `/store/repair-orders/{id}/close` | Close a repair | Manager, Associate |
| POST | `/store/repair-lines` | Add a repair line | Manager, Associate |
| GET | `/store/repair-lines/{id}` | Fetch a repair line | Manager, Associate, Customer |
| GET | `/store/repair-lines` | List/filter repair lines | Manager, Associate, Customer |
| POST | `/store/sales-orders` | Open a sales order | Manager, Associate, Customer |
| GET | `/store/sales-orders/{id}` | Fetch a sales order | Manager, Associate, Customer |
| GET | `/store/sales-orders` | List/filter sales orders | Manager, Associate, Customer |
| POST | `/store/sales-orders/{id}/capture` | Capture payment | Manager, Associate |
| POST | `/store/sales-orders/{id}/refund` | Refund a captured order | Manager |
| POST | `/store/sales-orders/{id}/fulfill` | Fulfill an order | Manager, Associate |
| POST | `/store/sales-orders/{id}/cancel` | Cancel fulfillment | Manager, Associate |
| POST | `/store/sales-order-lines` | Add a line to a pending order | Manager, Associate, Customer |
| GET | `/store/sales-order-lines/{id}` | Fetch a sales-order line | Manager, Associate, Customer |
| GET | `/store/sales-order-lines` | List/filter sales-order lines | Manager, Associate, Customer |
| POST | `/store/sales-order-lines/{id}/schedule-monogram` | Reserve a monogram station window | Manager, Associate |
| POST | `/store/sales-order-lines/{id}/start-monogram` | Begin the monogram | Manager, Associate |
| POST | `/store/sales-order-lines/{id}/complete-monogram` | Finish the monogram | Manager, Associate |
| POST | `/store/trade-ins` | Create a trade-in offer (OCC-guarded) | Manager, Associate |
| GET | `/store/trade-ins/{id}` | Fetch a trade-in | Manager, Associate, Customer |
| GET | `/store/trade-ins` | List/filter trade-ins | Manager, Associate, Customer |
| POST | `/store/trade-ins/{id}/accept` | Accept an offer | Manager |
| POST | `/store/trade-ins/{id}/decline` | Decline an offer | Manager, Associate, Customer |
| POST | `/store/trade-ins/{id}/void` | Void an accepted trade-in | Manager |
| POST | `/store/special-orders` | Create a special order | Manager, Associate, Customer |
| GET | `/store/special-orders/{id}` | Fetch a special order | Manager, Associate, Customer |
| GET | `/store/special-orders` | List/filter special orders | Manager, Associate, Customer |
| POST | `/store/special-orders/{id}/source` | Begin sourcing | Manager, Associate |
| POST | `/store/special-orders/{id}/arrive` | Mark stock arrived | Manager, Associate |
| POST | `/store/special-orders/{id}/fulfill` | Fulfill a special order | Manager, Associate |
| POST | `/store/special-orders/{id}/cancel` | Cancel a special order | Manager, Associate |
| POST | `/store/recall-notices` | Draft a recall notice | Manager |
| GET | `/store/recall-notices/{id}` | Fetch a recall notice | Manager, Associate, Customer |
| GET | `/store/recall-notices` | List/filter recall notices | Manager, Associate, Customer |
| POST | `/store/recall-notices/{id}/publish` | Publish a recall | Manager |
| POST | `/store/recall-notices/{id}/close` | Close a recall | Manager |
| POST | `/store/service-benches` | Create a repair bench | Manager |
| GET | `/store/service-benches/{id}` | Fetch a bench | Manager, Associate |
| GET | `/store/service-benches` | List benches | Manager, Associate |
| POST | `/store/monogram-stations` | Create a monogram station | Manager |
| GET | `/store/monogram-stations/{id}` | Fetch a station | Manager, Associate |
| GET | `/store/monogram-stations` | List stations | Manager, Associate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCT_RECALLED` | 409 |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_NO_REPAIR_LINES` | 422 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_ORDER_NOT_CAPTURED` | 409 |
| `ERR_MONOGRAM_PENDING` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_OPEN_SPECIAL_ORDER` | 409 |
| `ERR_CLAIM_OPEN_ON_REGISTRATION` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |
