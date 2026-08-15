# Dental Supply Distribution & Equipment Service API — Product Requirements Document

## 1. Introduction

A dental-supply distributor runs two intertwined businesses out of the same catalog: a high-frequency consumables trade, where practices restock gloves, composites, and regulated pharmaceuticals on tight usage cycles, and a capital-equipment trade, where chairs, imaging systems, and sterilizers are quoted, installed, commissioned, and then serviced for years under warranty or purchased service plans. This document specifies the API that operates both businesses end to end — practice onboarding and credit control, catalog management, usage-profile-driven automatic replenishment, order pricing with promotional bundles, manufacturer rebate adjudication, equipment sale pipelines with installation and training, field-technician dispatch with van-stock accounting, coverage determination, and equipment trade-in with final disposal.

The system is built around a logical clock rather than wall time, because rebate windows, warranty expiries, startup-package eligibility, and consumption accrual must all be reproducible and testable. Every monetary figure is carried in integer cents, and every workflow that touches money — order submission, rebate settlement, plan utilization, trade-in credit — is paired with an explicit compensating action so that cancellations, denials, and reopens unwind cleanly. Roles span the distributor's back office, its sales force, its service coordinators and field technicians, the dental practices themselves, and manufacturer representatives, each seeing exactly the slice of the workflow they operate.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representation conventions, and cross-cutting protocols that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly six roles: `DistributionAdmin`, `SalesRep`, `PracticeManager`, `ServiceDispatcher`, `FieldTechnician`, and `ManufacturerAgent`. A request whose headers are missing, or whose role value is not one of these six declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `PracticeManager`, `X-User-ID` is the `id` of the acting Practice; ownership checks on any resource that references a Practice compare the resource's `practice_id` field to `X-User-ID`, so a practice manager may only touch resources belonging to their own practice — their own orders, profiles, tickets, claims, trade-ins, and sales, and their own practice record when reading it. When `X-User-Role` is `FieldTechnician`, `X-User-ID` is the `id` of the acting Technician; assignment checks compare the technician recorded on the install or dispatch to `X-User-ID`, so a field technician may only complete installations, trainings, and ticket resolutions that are assigned to them personally. When `X-User-Role` is `DistributionAdmin`, `SalesRep`, `ServiceDispatcher`, or `ManufacturerAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

In broad strokes: the `DistributionAdmin` is the distributor's back office, owning practices, catalog products, promotions, technicians, van stock, warehouse delivery confirmation, replenishment runs, and the logical clock. The `SalesRep` owns quoting, scheduling, service-plan sales, and trade-in appraisal, and may also place and manage orders and usage profiles on behalf of any practice. The `ServiceDispatcher` assesses coverage and dispatches tickets. The `ManufacturerAgent` adjudicates rebate claims. The per-endpoint role grants are listed exhaustively in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Both may be combined with any endpoint-specific filters described in §3.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `updated_at` ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — practices, products, usage profiles, orders, equipment sales, technicians, service tickets, dispatch jobs, coverage agreements, promotions, rebate claims, and trade-ins — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource and underpins optimistic concurrency control where that is offered.

When one request cascades into several resources — for example, an order delivery that also updates usage profiles and spawns a new draft order — each resource the cascade mutates is treated as independently modified: its own `updated_at` refreshes and its own `version` increments.

### 2.5. The Logical Clock and Lazy Expiry

The server maintains a logical clock that governs every time-dependent rule in this document: order submission and delivery timestamps, usage windows, license and promotion expiry, install and dispatch scheduling, warranty periods, and reopen deadlines all read this clock, never wall-clock time. Before any operator action the logical clock starts at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own. An admin-only, test-driving capability advances the clock to a supplied instant: the caller passes `to_iso8601`, and the response reports the new `current_utc`.

Two resource families interpret the clock lazily. A CoverageAgreement whose `status` is still `ACTIVE` flips to `EXPIRED` — persisted, not just displayed — whenever the agreement is read or used and the logical now is strictly after its `end_date`; its coverage window is inclusive on both ends, so coverage applies while now is on or after `start_date` and on or before `end_date`. A Promotion behaves identically: whenever the promotion is attached to something or read, and the logical now is strictly after its `end_date`, an `ACTIVE` promotion flips to `EXPIRED`, and its program window is likewise inclusive on both ends.

### 2.6. Monetary Units and Numeric Precision

All monetary amounts in this API — prices, discounts, credits, deductibles, caps, funds, estimates, and appraisals — are represented as integer numbers of cents. Wherever a monetary calculation produces a fractional cent, the result is rounded half up to whole cents (zero decimal places); this applies to the volume discount, the bundle discount, each rebate line, the repair cost and customer-due figures, and the trade-in appraisal.

Usage-profile quantities are the exception to integer representation. The `average_daily_usage` and `on_hand_estimate` figures are decimal quantities carried at exactly four decimal places, rounded half up, so that slow-moving consumables accrue fractional depletion faithfully between deliveries. Configuration-style numeric inputs — a promotion's `discount_pct` fraction, per-unit rebate amounts, and similar rate fields — preserve the precision the caller supplied.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in this API is guarded by optimistic concurrency control: the usage-profile upsert, `PUT /api/usage-profiles`. Because the upsert creates-or-supersedes the profile for a practice–product pair, a client holding a stale view of the practice could silently overwrite a profile written against newer practice state. The request must therefore carry `expected_practice_version`, the `version` of the Practice as the client last observed it. If `expected_practice_version` does not equal the Practice's current `version` — because another writer has advanced the practice since the client last read it — the upsert is rejected with `ERR_STALE_VERSION` (HTTP 412), and no profile is created or superseded. No other endpoint accepts a version field; all other writes proceed without an OCC check.

### 2.8. Validation Order and Error Semantics

Every request is validated against a fixed ladder, and a failure at any rung stops further evaluation. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED` (401). Authorization and entity-backed ownership come second, yielding `ERR_FORBIDDEN` (403). Existence comes third: every identifier in the path and every foreign key in the body must reference an existing resource, otherwise `ERR_RESOURCE_NOT_FOUND` (404); the URL space is flat, so each path carries a single resource id, and body references such as `practice_id`, `product_id`, `order_id`, `promotion_id`, `equipment_sale_id`, or `technician_id` are checked at the same rung. Request shape comes fourth: required fields present, enum members valid, quantities strictly positive, datetimes well-formed, a window's end strictly after its start, and no client-supplied order kind of `AUTO` — violations yield `ERR_INVALID_REQUEST` (400). State legality comes fifth on all action endpoints: the requested transition must exist from the resource's current state, terminal states reject every transition, and violations yield `ERR_INVALID_STATE` (409). Optimistic-concurrency staleness comes sixth, yielding `ERR_STALE_VERSION` (412) where §2.7 applies. Only after all six generic rungs pass do the domain rules run — safety gates, business constraints, temporal windows, referential checks, and fiscal limits — in the relative orders stated alongside each workflow in §3.

### 2.9. Scheduling Geometry: Technician Calendars and Install Bays

Two different overlap tests govern scheduling, and confusing them produces real-world double bookings.

A technician's personal calendar uses **half-open intervals**: an existing commitment spanning from its start to its end conflicts with a proposed window if and only if the existing start is strictly before the proposed end and the proposed start is strictly before the existing end. Back-to-back commitments are therefore allowed — a proposed window whose start equals an existing end, or whose end equals an existing start, does not conflict. This half-open test is applied against everything on the technician's calendar: their `SCHEDULED` dispatch jobs and their `INSTALL_SCHEDULED` equipment-sale install windows alike. Dispatch windows are themselves half-open: `scheduled_start` is the inclusive start of the requested visit and `scheduled_end` the exclusive end, and the end must be strictly after the start.

A practice's install bay, by contrast, uses **closed intervals**: a proposed install window conflicts with another `INSTALL_SCHEDULED` sale at the same practice if the proposed start is on or before the existing end and the existing start is on or before the proposed end. Touching endpoints do conflict here — the bay cannot turn over instantly between two installs.

### 2.10. Controlled-Product Compliance

Two practice-level credentials gate what may be sold. A practice's `regulated_license_expiry` records the expiry of its regulated-items handling license; when it is null, or earlier than the logical now, the practice may not receive order lines whose product `kind` is `REGULATED`. A practice's `sterilization_compliant` flag certifies that it can receive products requiring a documented sterilization cycle; any order line whose product carries `sterilization_cycle_required` demands this certification. Both credentials are supplied at practice onboarding and are enforced on every order the practice places, as detailed in §3.3. On the catalog side, a product may additionally declare `max_qty_per_order`, a per-line quantity cap that is enforced only for `REGULATED` products; a null cap means unlimited.

### 2.11. Cascading Mutations and Compensating Actions

Many operations in this system are multi-aggregate transactions that run in a fixed hop order, and nearly every financial commitment has a defined compensation. Order submission reserves practice credit; cancellation of a submitted order restores it. Order delivery first stamps the order, then feeds usage profiles, then may spawn automatic draft orders. Ticket resolution debits van stock, computes the customer-due amount, debits a service plan's utilization, and completes the dispatch job; reopening the ticket credits the van stock back, credits the plan's utilization back (never below zero), revives an exhausted plan whose utilization drops below its cap, and clears the resolution fields. Rebate submission reserves promotion funds and can exhaust the promotion; denial releases the reservation and can revive the promotion. Equipment acceptance spawns the manufacturer warranty agreement. The detailed mechanics of each cascade live with their workflows in §3; the invariant everywhere is that compensations restore prior state exactly, so that a cancelled, denied, or reopened workflow leaves ledgers as if the forward action had never happened, modulo the audit trail on `updated_at` and `version`.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Network: Practices, Catalog, and Technicians

A `DistributionAdmin` onboards a dental practice by supplying its display `name`, its service `region` code (which later determines dispatch eligibility), its `credit_limit_cents` (the maximum open-order credit, which must be at least zero), and optionally its commercial `practice_tier` — `STANDARD`, `PREMIER`, or `ELITE`, defaulting to `STANDARD` — which drives the rebate multiplier and the bundle bonus. The onboarding payload may also carry `regulated_license_expiry` (defaulting to null) and `sterilization_compliant` (defaulting to false). A new practice starts with `status` `ACTIVE`, and its `credit_available_cents` is initialized to its `credit_limit_cents`. An administrator may suspend a practice, moving it `ACTIVE` → `SUSPENDED`, and later reinstate it, moving `SUSPENDED` → `ACTIVE`; each action increments the practice's `version` and refreshes `updated_at`. Suspension is a credit hold: while `SUSPENDED`, the practice is blocked from new orders, new equipment-sale quotes, equipment-sale confirmation, and new trade-in requests, each rejected with `ERR_PRACTICE_SUSPENDED`.

The catalog is administrator-managed. Creating a product requires a unique `sku`, a display `name`, a `kind` of `CONSUMABLE`, `EQUIPMENT`, `PART`, or `REGULATED`, a `unit_price_cents` catalog price, and the `manufacturer` name that later serves as the rebate counterparty. Optional product attributes are `max_qty_per_order` (the regulated quantity cap of §2.10), `sterilization_cycle_required` (default false), and `warranty_months` (default 0), the manufacturer warranty duration used when an equipment sale is accepted. The four kinds partition the business: `CONSUMABLE` and `REGULATED` products feed usage profiles and auto-replenishment; `EQUIPMENT` is sold through the equipment-sale pipeline (startup orders excepted); `PART` exists to be stocked on technician vans.

Technicians are onboarded by an administrator with a `name`, a home `region`, a `certifications` array whose members are drawn from `INSTALL`, `REPAIR`, and `STERILIZATION`, and an optional `status` that defaults to `ACTIVE` — an `INACTIVE` technician is ineligible for any scheduling. Installs require the `INSTALL` certification and repair dispatch the `REPAIR` certification. Each technician carries a `van_stock`, initially empty, describing the parts van's contents; an administrator loads or adjusts one part line at a time by `product_id`, writing `quantity_on_van` and `min_quantity`, and re-loading the same product overwrites its existing entry rather than duplicating it.

### 3.2. Usage Profiles and the Replenishment Sweep

Automatic replenishment is configured per practice and product through a usage profile. A `PracticeManager` (for their own practice) or a `SalesRep` creates-or-supersedes the profile for a `practice_id` and `product_id` pair — there is exactly one profile per pair, and the upsert legitimately replaces any prior profile for that pair. The payload carries the `reorder_point`, the `target_stock_level`, an optional `auto_replenish_enabled` flag defaulting to false, and the OCC guard `expected_practice_version` described in §2.7; the staleness check runs before the profile's own validity rules. The profiled product must be `CONSUMABLE` or `REGULATED`, and `target_stock_level` must be strictly greater than `reorder_point`; either violation is rejected with `ERR_REORDER_TARGET_INVALID`. Every successful upsert also increments the practice's `version` by one. On creation the profile's `on_hand_estimate` is 0, its `average_daily_usage` is 0, and its `last_evaluated_at` is stamped with the logical now. Profiles can be read individually, and the profile listing may be filtered by `practice_id` and `product_id`.

Two computed quantities drive the automation. The `average_daily_usage` is measured over the trailing 28-day window ending at the logical now, both bounds inclusive: sum the line quantities of this product across this practice's orders whose `status` is `DELIVERED` and whose `delivered_at` falls inside the window — drafts, submitted-but-undelivered orders, and cancelled orders are all excluded — divide that total by 28, and round half up to four decimal places. This average is recomputed whenever a delivery touches the profile and at each replenishment run, before any consumption is accrued.

Consumption itself accrues only at replenishment-run time; deliveries add their full line quantity to `on_hand_estimate` with no accrual at that moment. When a run executes, each profile first accrues: count the whole days elapsed between `last_evaluated_at` and the logical now — that is, the elapsed seconds divided by 86,400 seconds per day, with any partial day discarded — then subtract `average_daily_usage` multiplied by those whole days from `on_hand_estimate`, never letting the estimate fall below zero, round half up to four decimal places, and stamp `last_evaluated_at` with the run's logical now.

After accrual, and also immediately after any delivery that updated the profile, the reorder threshold is evaluated. When `auto_replenish_enabled` is true and `on_hand_estimate` is less than or equal to `reorder_point` — an estimate exactly equal to the point does trigger — and no existing `DRAFT` order of kind `AUTO` already covers this practice–product pair, the system computes a reorder quantity as the ceiling of `target_stock_level` minus `on_hand_estimate`. If that quantity is at least 1, a new order is created with `kind` `AUTO` and `status` `DRAFT`, containing a single line for the product at that quantity; a computed quantity below 1 spawns nothing. The duplicate guard means one outstanding auto-draft per pair at a time.

A `DistributionAdmin` can trigger the full sweep on demand: the replenishment run accrues consumption on every usage profile, then evaluates the reorder threshold profile by profile, and returns the `evaluated_profile_count` together with the `created_order_ids` of any auto-drafts it spawned.

### 3.3. Ordering: Drafts, Submission, Delivery, and Cancellation

Orders are placed by a `PracticeManager` for their own practice or by a `SalesRep` on a practice's behalf, with a payload of `practice_id`, `kind`, an optional `promotion_id`, and `lines`, an array whose entries each name a `product_id` and a `quantity` (an integer greater than zero). The client-facing kinds are `MANUAL`, `STARTUP`, and `BUNDLE`; `AUTO` is reserved for the system, and a client-supplied kind of `AUTO` is rejected as `ERR_INVALID_REQUEST`. At creation the server prices every line by snapshotting the product's current `unit_price_cents` onto the line and computing its `line_total_cents`, so later catalog price changes never retroactively alter an open order.

Pricing then runs in a pinned order — tier selection is keyed on the pre-discount subtotal, the discount is computed from that same subtotal, and only then is the total derived, removing any circular reading. The `subtotal_cents` is the sum of the line totals. The volume tier keys on that pre-discount subtotal: a subtotal of at least 500,000 cents earns ten percent, a subtotal of at least 200,000 cents earns five percent, and anything below earns nothing; the `volume_discount_cents` is the subtotal multiplied by the applicable percentage, rounded half up to whole cents. The bundle discount depends on the attached promotion: when no promotion is attached, or when any product in the promotion's `required_product_ids` is absent from the order's lines, the `bundle_discount_cents` is zero. Otherwise, take the component subtotal — the sum of the line totals whose products appear in `required_product_ids` — add a tier bonus of 0.02 to the promotion's `discount_pct` when the ordering practice is `ELITE` (all other tiers add nothing), multiply the component subtotal by the combined fraction, round half up to whole cents, and then, if the promotion sets a `max_discount_cents` cap, take the lesser of the rounded amount and the cap; an uncapped promotion keeps the rounded amount. Finally, the `discount_cents` combines the two: with no promotion attached it is simply the volume discount; with a promotion whose `stacking_allowed` is false it is the greater of the volume and bundle discounts; with stacking allowed it is their sum. The `total_cents` is the `subtotal_cents` minus the `discount_cents`, and a new order starts in `DRAFT`.

Because an order touches controlled goods and promotional programs, creation applies its domain gates in a fixed order after the generic ladder of §2.8: first the regulated-license gate — any `REGULATED` line requires the practice's `regulated_license_expiry` to be present and not earlier than the logical now, else `ERR_REGULATED_LICENSE_MISSING`; then sterilization certification — any line whose product requires a sterilization cycle demands a `sterilization_compliant` practice, else `ERR_STERILIZATION_NOT_CERTIFIED`; then the regulated quantity cap — a `REGULATED` line's quantity may not exceed the product's `max_qty_per_order` when one is set, else `ERR_REGULATED_QTY_LIMIT`; then equipment orderability — `EQUIPMENT` lines are permitted only on `STARTUP` orders, else `ERR_EQUIPMENT_NOT_ORDERABLE`; then the startup window — a `STARTUP` order is accepted only while the logical now is within ninety days of the practice's `created_at`, else `ERR_STARTUP_WINDOW_EXPIRED`; then the startup package limit — at most one non-`CANCELLED` `STARTUP` order may exist per practice, else `ERR_STARTUP_PACKAGE_LIMIT`; then promotion activity — an attached promotion must be `ACTIVE` after the lazy expiry check with the logical now inside its inclusive program window, else `ERR_PROMOTION_INACTIVE`; then promotion applicability — orders accept only `BUNDLE_DISCOUNT` promotions, else `ERR_PROMOTION_NOT_APPLICABLE`; and finally practice standing — a `SUSPENDED` practice may not open new orders, else `ERR_PRACTICE_SUSPENDED`.

Submission moves a `DRAFT` order to `SUBMITTED`. The order must have at least one line, and its checks again run in a fixed order: for a `BUNDLE` order, every product in the attached promotion's `required_product_ids` must be present in the lines, else `ERR_BUNDLE_INCOMPLETE`; the practice must be `ACTIVE`, else `ERR_PRACTICE_SUSPENDED`; and the order's `total_cents` must not exceed the practice's `credit_available_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`. Available credit is a live figure: it equals the practice's `credit_limit_cents` minus the summed `total_cents` of that practice's orders currently sitting in `SUBMITTED`. A successful submission reserves credit by reducing `credit_available_cents` by the order's `total_cents`, stamps `submitted_at` with the logical now, and increments the practice's `version` by one.

Delivery is the warehouse's confirmation, performed by a `DistributionAdmin`, and moves `SUBMITTED` → `DELIVERED`. The cascade runs in hops. First the order itself is stamped: `delivered_at` takes the logical now. Second, for each delivered line whose product is `CONSUMABLE` or `REGULATED` and for which a usage profile exists for the practice–product pair, the line quantity is added to the profile's `on_hand_estimate` and the profile's `average_daily_usage` is recomputed over the trailing 28-day window. Third, each profile so updated is evaluated against the auto-reorder rule of §3.2, which may spawn a new `DRAFT` auto-order. `DELIVERED` is terminal.

Cancellation releases an order before fulfillment. Cancelling a `DRAFT` order simply moves it to `CANCELLED` and refreshes `updated_at`. Cancelling a `SUBMITTED` order additionally compensates the reservation: the order's `total_cents` is added back to the practice's `credit_available_cents`, and the practice's `version` increments by one. `CANCELLED` is terminal, and no order may be cancelled once delivered. The order listing may be filtered by `practice_id`, `promotion_id`, and `kind`, and a practice manager reading orders sees only their own practice's.

### 3.4. Promotions, Bundles, and Manufacturer Rebates

Promotional programs are created by a `DistributionAdmin` with a `name`, a `promo_kind` of `BUNDLE_DISCOUNT` or `MANUFACTURER_REBATE`, and an inclusive program window from `start_date` to `end_date`. A bundle promotion carries `required_product_ids` — the products that must all appear in a bundle order — plus a `discount_pct`, an optional `max_discount_cents` cap, and a `stacking_allowed` flag (default false) that decides whether the bundle discount combines with or merely competes against the volume discount. A rebate promotion instead carries `eligible_product_ids`, whose order lines accrue manufacturer rebate, a `rebate_per_unit_cents` rate, and a `fund_total_cents` budget, which is required for `MANUFACTURER_REBATE` programs; its `fund_remaining_cents` is initialized to `fund_total_cents` at creation. A promotion starts `ACTIVE`; per §2.5 it flips lazily to `EXPIRED` once the logical now passes its `end_date`, and a rebate promotion whose `fund_remaining_cents` falls to zero or below flips to `EXHAUSTED`, returning to `ACTIVE` if a later denial lifts the fund back above zero.

A `PracticeManager` files a rebate claim against one of their practice's orders by naming the `practice_id`, the `order_id`, and the `promotion_id`. The creation checks run in order: the referenced promotion must be a `MANUFACTURER_REBATE` program — attaching a `BUNDLE_DISCOUNT` here, or a rebate program to an order, is rejected with `ERR_PROMOTION_NOT_APPLICABLE`; the claim's practice must be the order's practice, else `ERR_PRACTICE_MISMATCH`; and no other non-`DENIED` claim may already exist for the same order-and-promotion pair, else `ERR_DUPLICATE_CLAIM`. At creation the `claim_amount_cents` is computed. The practice's tier supplies a multiplier — 1.0 for `STANDARD`, 1.1 for `PREMIER`, 1.25 for `ELITE` — read at claim-creation time. The rounding order is pinned: for each line of the referenced order whose product appears in `eligible_product_ids`, multiply the line quantity by `rebate_per_unit_cents` and by the tier multiplier, and round that line's rebate half up to whole cents first; the claim amount is then the sum of those per-line rounded rebates. Rounding only the grand total instead is a different, rejected reading. A new claim starts in `DRAFT` with `submitted_at`, `paid_at`, and `denial_reason` all null.

Submitting the claim to the manufacturer moves `DRAFT` → `SUBMITTED` and is the practice's own act — the caller must be the claim's practice, else `ERR_FORBIDDEN`. Its three domain checks run in order: the promotion must be `ACTIVE` after the lazy expiry evaluation, else `ERR_PROMOTION_INACTIVE`; the referenced order must be `DELIVERED`, else `ERR_ORDER_NOT_DELIVERED`; and the promotion's `fund_remaining_cents` must be at least the `claim_amount_cents`, else `ERR_REBATE_FUND_EXHAUSTED`. A successful submit stamps `submitted_at`, then reserves funds by subtracting the claim amount from `fund_remaining_cents`, and if that subtraction leaves the fund at zero or below, the promotion flips `ACTIVE` → `EXHAUSTED`.

The manufacturer adjudicates. A `ManufacturerAgent` may deny a `SUBMITTED` claim, supplying a `denial_reason`: the claim moves to `DENIED`, the reserved amount is added back to `fund_remaining_cents`, and if the promotion had been `EXHAUSTED` and the release lifts its fund above zero, the promotion returns to `ACTIVE`. Or the agent may settle a `SUBMITTED` claim, moving it to `PAID` and stamping `paid_at`; `PAID` is terminal. A denied claim is not the end of the road: the claim's own `PracticeManager` (any other caller draws `ERR_FORBIDDEN`) may revise it, supplying a `revision_note`, which returns the claim `DENIED` → `DRAFT`, clears the `denial_reason`, and leaves the correction trail in the record's `updated_at` audit — ready for a fresh submission through the same gauntlet. The claim listing may be filtered by `practice_id`, `order_id`, and `promotion_id`.

### 3.5. Capital Equipment: Quote, Installation, Training, Acceptance

Capital equipment moves through a six-stage pipeline: `QUOTE` → `CONFIRMED` → `INSTALL_SCHEDULED` → `INSTALLED` → `TRAINED` → `ACCEPTED`, with one sanctioned rework cycle. A `SalesRep` opens a quote by naming the `practice_id`, the `product_id` of an `EQUIPMENT`-kind product, and the agreed `sale_price_cents`, which must be greater than zero; the practice must be `ACTIVE` at creation, else `ERR_PRACTICE_SUSPENDED`. The sale is born in `QUOTE`, with `installer_technician_id`, both install-window fields, `training_minutes`, `trade_in_id`, `trade_in_credit_cents`, and `warranty_agreement_id` all null, and `install_rework_count` at zero.

Confirmation — the rep's `QUOTE` → `CONFIRMED` — is the point of commercial commitment and requires the practice to be `ACTIVE`, else `ERR_PRACTICE_SUSPENDED`. Scheduling the install is likewise the rep's: they name a `technician_id` and propose a window from `window_start` to `window_end`. Scheduling's domain checks run in order after the generic ladder (which already rejects a window whose end is not strictly after its start): the named technician must be `ACTIVE` and hold the `INSTALL` certification, else `ERR_CERTIFICATION_MISSING`; the window must not collide with the technician's own calendar under the half-open overlap test of §2.9 — against both their `SCHEDULED` dispatch jobs and their other `INSTALL_SCHEDULED` install windows — else `ERR_TECHNICIAN_SCHEDULE_CONFLICT`; and the window must not collide with another `INSTALL_SCHEDULED` sale at the same practice under the closed-interval bay test, else `ERR_INSTALL_WINDOW_CONFLICT`. A successful scheduling moves `CONFIRMED` → `INSTALL_SCHEDULED` and records `installer_technician_id`, `install_window_start`, and `install_window_end` on the sale.

From `INSTALL_SCHEDULED`, the assigned field technician — and only that technician, matched against `installer_technician_id` else `ERR_FORBIDDEN` — marks the installation complete, moving to `INSTALLED`. If the install fails inspection, the rep may reschedule directly from `INSTALLED` back to `INSTALL_SCHEDULED`: the same certification and both overlap checks apply, the `install_rework_count` increments by one, and the install-window fields are overwritten with the new window. When the hardware is in, the same assigned technician records delivered training — `training_minutes` must be greater than zero — moving `INSTALLED` → `TRAINED` with the duration stored on the sale.

Acceptance belongs to the practice. A `PracticeManager` acting as the sale's practice (any other caller draws `ERR_FORBIDDEN`) accepts a `TRAINED` sale, moving it to the terminal `ACCEPTED` state. Acceptance spawns the manufacturer warranty: a new CoverageAgreement is created with `coverage_type` `WARRANTY`, `deductible_cents` zero, `coverage_cap_cents` null, `start_date` at the logical now, `end_date` exactly the product's `warranty_months` calendar months later, and `status` `ACTIVE`; the sale's `warranty_agreement_id` is set to the new agreement. `ACCEPTED` equipment is "in service" — it becomes eligible for service tickets in §3.7. The equipment-sale listing may be filtered by `practice_id`, `product_id`, `installer_technician_id`, `trade_in_id`, and `warranty_agreement_id`.

### 3.6. Equipment Trade-Ins: Appraisal, Credit, and Disposal

A practice upgrading its equipment may trade in the old unit. The request — from a `PracticeManager` or a `SalesRep`, and only while the practice is `ACTIVE`, else `ERR_PRACTICE_SUSPENDED` — captures the `practice_id`, a free-text `description` of the unit, its `equipment_age_months` in whole months, a `condition` grade of `WORKING`, `NEEDS_REPAIR`, or `SCRAP`, and the `category_base_value_cents`, the as-new market reference value for that equipment category. The trade-in starts in `REQUESTED`, with `valuation_method`, `appraised_value_cents`, `applied_to_equipment_sale_id`, and `disposal_method` all null.

Appraisal is the `SalesRep`'s call, moving `REQUESTED` → `APPRAISED` by choosing a `valuation_method`. Under `MARKET_VALUE`, the unit depreciates exponentially with age and is then graded by condition: multiply `category_base_value_cents` by 0.98 raised to the power of `equipment_age_months` (two percent monthly depreciation), multiply by the condition factor — 1.0 for `WORKING`, 0.6 for `NEEDS_REPAIR`, 0.2 for `SCRAP` — and round half up to whole cents; a floor then applies, so the appraised value is the greater of that rounded figure and ten percent of the category base value, itself rounded half up to whole cents. Under `SCRAP_VALUE`, age and base value are ignored entirely and a flat salvage table applies: 25,000 cents for `WORKING`, 10,000 cents for `NEEDS_REPAIR`, 4,000 cents for `SCRAP`. The result is stored as `appraised_value_cents`.

The practice then decides: a `PracticeManager` acting as the trade-in's practice (else `ERR_FORBIDDEN`) accepts the appraisal, moving `APPRAISED` → `ACCEPTED`. An accepted appraisal becomes spending power when the rep applies it to an open equipment sale, moving `ACCEPTED` → `CREDITED`: the target sale must still be in `QUOTE` or `CONFIRMED` — anything later is rejected with `ERR_INVALID_STATE` — the sale must not already carry a trade-in (at most one per sale), else `ERR_TRADE_IN_ALREADY_APPLIED`, and the `appraised_value_cents` must not exceed the sale's `sale_price_cents`, else `ERR_TRADE_IN_CREDIT_EXCEEDS_PRICE`; the already-applied check precedes the price check. Applying stamps the sale's `trade_in_id` and `trade_in_credit_cents` with the trade-in and its appraised value, and records `applied_to_equipment_sale_id` on the trade-in. Finally, an administrator records the unit's disposal, moving `CREDITED` → `DISPOSED` with a `disposal_method` of `RECYCLE`, `RESALE_PARTS`, or `HAZMAT`; `DISPOSED` is terminal. The trade-in listing may be filtered by `practice_id` and `applied_to_equipment_sale_id`.

### 3.7. Equipment Service: Tickets, Coverage, Dispatch, and Resolution

Coverage agreements come into the world two ways. Manufacturer warranties are created by equipment acceptance, as described in §3.5 — always `deductible_cents` zero, `coverage_cap_cents` null. Service plans are sold: a `SalesRep` registers one with the `practice_id`, the `equipment_sale_id` of the covered equipment, `coverage_type` `SERVICE_PLAN`, an inclusive `start_date` to `end_date` window, an optional per-claim `deductible_cents` defaulting to zero, and an optional `coverage_cap_cents` lifetime payout cap whose null means uncapped. Either way, an agreement starts `ACTIVE` with `used_cents` at zero, flips lazily to `EXPIRED` per §2.5, and a capped plan whose `used_cents` reaches or exceeds its `coverage_cap_cents` is marked `EXHAUSTED`. Agreements can be read individually — reads apply the lazy expiry — and the agreement listing filters by `practice_id` and `equipment_sale_id`.

When covered equipment misbehaves, a `PracticeManager` (for their own practice) or a `ServiceDispatcher` opens a service ticket with the `practice_id`, the `equipment_sale_id`, and a free-text `issue_description`. The referenced sale must have reached `ACCEPTED` — the equipment must be in service — and the ticket's practice must be the sale's practice, else `ERR_PRACTICE_MISMATCH`. The ticket starts `OPEN`, with `coverage_determination`, `coverage_agreement_id`, `estimate_cents`, `parts_used`, `labor_minutes`, `customer_due_cents`, and `resolved_at` all null.

Coverage assessment, performed by a `ServiceDispatcher`, is a fork. The system gathers the coverage agreements for the ticket's equipment sale, first applying lazy expiry so any `ACTIVE` agreement whose `end_date` has passed flips to `EXPIRED` and drops out, then keeping those still `ACTIVE` with the logical now inside their inclusive start-to-end window. If any candidate is a `WARRANTY`, it wins outright: `coverage_determination` becomes `WARRANTY` and the ticket moves `OPEN` → `COVERAGE_ASSESSED` with `coverage_agreement_id` pointing at that warranty. Failing that, if any candidate is a `SERVICE_PLAN`, the one with the earliest `end_date` is chosen — ties broken by earliest `created_at` — `coverage_determination` becomes `SERVICE_PLAN`, and the ticket likewise moves to `COVERAGE_ASSESSED`. When no active agreement covers the equipment at all, the ticket forks instead to `AWAITING_APPROVAL`: `coverage_determination` becomes `BILLABLE`, `coverage_agreement_id` stays null, and the practice is shown a flat diagnostic `estimate_cents` of 7,500 cents. The billable branch rejoins the main line when a `PracticeManager` acting as the ticket's practice (else `ERR_FORBIDDEN`) approves the estimate, moving `AWAITING_APPROVAL` → `COVERAGE_ASSESSED`.

Dispatch turns an assessed ticket into a field visit. A `ServiceDispatcher` requests a window from `scheduled_start` to `scheduled_end`. A ticket with an existing `SCHEDULED` dispatch job may not be dispatched again — `ERR_INVALID_STATE`; at most one scheduled job exists per ticket. The certification gate applies here as on installs — dispatch requires the `REPAIR` certification, enforced as `ERR_CERTIFICATION_MISSING` — and it precedes the selector's empty-pool rejection. The selector then builds its candidate pool: technicians who are `ACTIVE`, hold `REPAIR` certification, share the ticket practice's `region`, and whose calendars show no half-open overlap — per §2.9 — between the requested window and any of their `SCHEDULED` jobs or `INSTALL_SCHEDULED` install windows (adjacent, touching windows are allowed). The pool is ranked by each candidate's total already-scheduled minutes intersecting the requested calendar day — midnight of that day to midnight of the next — ascending, so the least-loaded eligible technician wins; ties break by the technician's `created_at`, earliest first. An empty pool rejects the dispatch with `ERR_TECHNICIAN_UNAVAILABLE`. A successful dispatch moves `COVERAGE_ASSESSED` → `DISPATCHED` and creates a DispatchJob in `SCHEDULED`, recording the `service_ticket_id`, the chosen `technician_id`, and the requested window. Dispatch jobs are readable individually, and their listing filters by `service_ticket_id` and `technician_id`.

Resolution belongs to the assigned field technician: the caller's identity must match the `technician_id` on the ticket's `SCHEDULED` job, else `ERR_FORBIDDEN`. The technician reports `parts_used` — an array of `product_id` and `quantity` pairs — and `labor_minutes`. Every part line must be sufficiently stocked on that technician's van: a line whose quantity exceeds the van entry's `quantity_on_van` rejects the whole resolution with `ERR_PARTS_NOT_ON_VAN`. Resolution then cascades in hops. First, each reported part is debited from the resolving technician's `van_stock`. Second, the money is computed under the recorded `coverage_determination`: the parts cost is the sum, over the `parts_used` entries, of each quantity multiplied by that product's `unit_price_cents` at resolve time; the gross cost is the parts cost plus `labor_minutes` at a labor rate of 200 cents per minute. Under `WARRANTY` the practice owes nothing — `customer_due_cents` is zero and the warranty's `used_cents` is untouched. Under `SERVICE_PLAN`, the remaining cap is the agreement's `coverage_cap_cents` minus its `used_cents` (treated as unlimited when the cap is null); the plan's share is the smaller of two floors — the gross cost minus the `deductible_cents`, never below zero, and the remaining cap, never below zero — the practice owes the gross cost minus that plan share, and the agreement's `used_cents` is debited by the plan share. Under `BILLABLE` the practice owes the full gross cost. Third, a capped plan whose `used_cents` now reaches or exceeds its `coverage_cap_cents` flips `ACTIVE` → `EXHAUSTED`. Finally the linked dispatch job moves `SCHEDULED` → `COMPLETED`, and `resolved_at` is stamped with the logical now.

A resolved ticket has two exits. Closing it — by the practice or the dispatcher — moves `RESOLVED` → `CLOSED`, terminal. Reopening it, by the same two roles, returns `RESOLVED` → `OPEN` for rework, but only while the logical now is within thirty days of `resolved_at`; later attempts are rejected with `ERR_REOPEN_WINDOW_EXPIRED`. Reopening is a full compensation of resolution: the reported parts are credited back onto the resolving technician's van, a `SERVICE_PLAN` agreement's `used_cents` is credited by the prior plan share (never below zero), an agreement that had flipped `EXHAUSTED` returns to `ACTIVE` if the credit drops its utilization below the cap, and the ticket's coverage fields — `coverage_determination`, `coverage_agreement_id`, `customer_due_cents`, `parts_used`, `labor_minutes`, and `resolved_at` — are all cleared to null, ready for a fresh assessment. The ticket listing may be filtered by `practice_id`, `equipment_sale_id`, and `coverage_agreement_id`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify, transition, or act upon an existing resource return `200 OK`. All endpoints are mounted under the `/api` prefix. Request payloads, computed fields, side effects, and the filters accepted by each list endpoint are specified in the narratives of §2 and §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/practices` | Onboard a dental practice | DistributionAdmin |
| GET | `/api/practices/{id}` | Read a practice (PracticeManager restricted to own id) | DistributionAdmin, SalesRep, PracticeManager |
| POST | `/api/practices/{id}/suspend` | Suspend a practice (credit hold) | DistributionAdmin |
| POST | `/api/practices/{id}/reinstate` | Reinstate a suspended practice | DistributionAdmin |
| POST | `/api/products` | Create a catalog product | DistributionAdmin |
| GET | `/api/products/{id}` | Read a product | DistributionAdmin, SalesRep, PracticeManager, ServiceDispatcher, FieldTechnician, ManufacturerAgent |
| PUT | `/api/usage-profiles` | Create-or-supersede the usage profile for a practice–product pair (OCC-guarded) | PracticeManager, SalesRep |
| GET | `/api/usage-profiles/{id}` | Read a usage profile | DistributionAdmin, SalesRep, PracticeManager |
| GET | `/api/usage-profiles` | List usage profiles | DistributionAdmin, SalesRep, PracticeManager |
| POST | `/api/orders` | Create an order with inline lines; lines priced and totals computed | PracticeManager, SalesRep |
| GET | `/api/orders/{id}` | Read an order (PracticeManager restricted to own practice) | DistributionAdmin, SalesRep, PracticeManager |
| GET | `/api/orders` | List orders | DistributionAdmin, SalesRep, PracticeManager |
| POST | `/api/orders/{id}/submit` | Submit a draft order; reserves practice credit | PracticeManager, SalesRep |
| POST | `/api/orders/{id}/deliver` | Mark a submitted order delivered; runs the usage-profile and auto-reorder cascade | DistributionAdmin |
| POST | `/api/orders/{id}/cancel` | Cancel a draft or submitted order; restores reserved credit | PracticeManager, SalesRep |
| POST | `/api/_replenishment/run` | Run the replenishment sweep: accrue consumption on all profiles, then evaluate auto-reorder | DistributionAdmin |
| POST | `/api/equipment-sales` | Create an equipment sale quote | SalesRep |
| GET | `/api/equipment-sales/{id}` | Read an equipment sale | DistributionAdmin, SalesRep, PracticeManager, ServiceDispatcher, FieldTechnician |
| GET | `/api/equipment-sales` | List equipment sales | DistributionAdmin, SalesRep, PracticeManager, ServiceDispatcher, FieldTechnician |
| POST | `/api/equipment-sales/{id}/confirm` | Confirm a quote into a sale | SalesRep |
| POST | `/api/equipment-sales/{id}/schedule-install` | Schedule (or re-schedule for rework) the installation window with an explicit technician | SalesRep |
| POST | `/api/equipment-sales/{id}/complete-install` | Assigned technician marks installation complete | FieldTechnician |
| POST | `/api/equipment-sales/{id}/complete-training` | Assigned technician records delivered training | FieldTechnician |
| POST | `/api/equipment-sales/{id}/accept` | Practice accepts the installation; spawns the manufacturer warranty | PracticeManager |
| POST | `/api/technicians` | Onboard a field technician | DistributionAdmin |
| GET | `/api/technicians/{id}` | Read a technician including van stock | DistributionAdmin, SalesRep, ServiceDispatcher, FieldTechnician |
| PUT | `/api/technicians/{id}/van-stock` | Load or adjust one part line on the technician's van | DistributionAdmin |
| POST | `/api/service-tickets` | Open a service ticket against accepted equipment | PracticeManager, ServiceDispatcher |
| GET | `/api/service-tickets/{id}` | Read a service ticket | DistributionAdmin, ServiceDispatcher, PracticeManager, FieldTechnician |
| GET | `/api/service-tickets` | List service tickets | DistributionAdmin, ServiceDispatcher, PracticeManager, FieldTechnician |
| POST | `/api/service-tickets/{id}/assess-coverage` | Determine coverage; billable determinations fork to estimate approval | ServiceDispatcher |
| POST | `/api/service-tickets/{id}/approve-estimate` | Practice approves the billable estimate | PracticeManager |
| POST | `/api/service-tickets/{id}/dispatch` | Select a technician by selector policy and create a dispatch job | ServiceDispatcher |
| POST | `/api/service-tickets/{id}/resolve` | Assigned technician resolves the ticket with parts and labor | FieldTechnician |
| POST | `/api/service-tickets/{id}/reopen` | Reopen a resolved ticket within 30 days; compensates parts and plan usage | PracticeManager, ServiceDispatcher |
| POST | `/api/service-tickets/{id}/close` | Close a resolved ticket | PracticeManager, ServiceDispatcher |
| GET | `/api/dispatch-jobs/{id}` | Read a dispatch job | DistributionAdmin, ServiceDispatcher, FieldTechnician |
| GET | `/api/dispatch-jobs` | List dispatch jobs | DistributionAdmin, ServiceDispatcher, FieldTechnician |
| POST | `/api/coverage-agreements` | Sell/register a service-plan coverage agreement | SalesRep |
| GET | `/api/coverage-agreements/{id}` | Read a coverage agreement (applies lazy expiry) | DistributionAdmin, SalesRep, ServiceDispatcher, PracticeManager |
| GET | `/api/coverage-agreements` | List coverage agreements | DistributionAdmin, SalesRep, ServiceDispatcher, PracticeManager |
| POST | `/api/promotions` | Create a promotion program (bundle discount or manufacturer rebate) | DistributionAdmin |
| GET | `/api/promotions/{id}` | Read a promotion (applies lazy expiry) | DistributionAdmin, SalesRep, PracticeManager, ServiceDispatcher, ManufacturerAgent |
| POST | `/api/rebate-claims` | File a manufacturer rebate claim against an order; amount computed at creation | PracticeManager |
| GET | `/api/rebate-claims/{id}` | Read a rebate claim | DistributionAdmin, PracticeManager, ManufacturerAgent |
| GET | `/api/rebate-claims` | List rebate claims | DistributionAdmin, PracticeManager, ManufacturerAgent |
| POST | `/api/rebate-claims/{id}/submit` | Submit a claim to the manufacturer; reserves promotion funds | PracticeManager |
| POST | `/api/rebate-claims/{id}/revise` | Return a denied claim to draft for correction | PracticeManager |
| POST | `/api/rebate-claims/{id}/deny` | Manufacturer denies a submitted claim; releases reserved funds | ManufacturerAgent |
| POST | `/api/rebate-claims/{id}/settle` | Manufacturer pays a submitted claim | ManufacturerAgent |
| POST | `/api/trade-ins` | Request an equipment trade-in | PracticeManager, SalesRep |
| GET | `/api/trade-ins/{id}` | Read a trade-in | DistributionAdmin, SalesRep, PracticeManager |
| GET | `/api/trade-ins` | List trade-ins | DistributionAdmin, SalesRep, PracticeManager |
| POST | `/api/trade-ins/{id}/appraise` | SalesRep appraises under market-value or scrap-value method | SalesRep |
| POST | `/api/trade-ins/{id}/accept` | Practice accepts the appraisal | PracticeManager |
| POST | `/api/trade-ins/{id}/apply-to-sale` | Apply the accepted trade-in credit to an open equipment sale | SalesRep |
| POST | `/api/trade-ins/{id}/dispose` | Record final disposal of the traded equipment | DistributionAdmin |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | DistributionAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the workflow narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_REGULATED_LICENSE_MISSING` | 422 |
| `ERR_STERILIZATION_NOT_CERTIFIED` | 422 |
| `ERR_REGULATED_QTY_LIMIT` | 422 |
| `ERR_EQUIPMENT_NOT_ORDERABLE` | 422 |
| `ERR_STARTUP_WINDOW_EXPIRED` | 422 |
| `ERR_STARTUP_PACKAGE_LIMIT` | 409 |
| `ERR_REORDER_TARGET_INVALID` | 422 |
| `ERR_PROMOTION_INACTIVE` | 422 |
| `ERR_PROMOTION_NOT_APPLICABLE` | 422 |
| `ERR_BUNDLE_INCOMPLETE` | 422 |
| `ERR_CERTIFICATION_MISSING` | 422 |
| `ERR_TECHNICIAN_SCHEDULE_CONFLICT` | 409 |
| `ERR_INSTALL_WINDOW_CONFLICT` | 409 |
| `ERR_TECHNICIAN_UNAVAILABLE` | 409 |
| `ERR_REOPEN_WINDOW_EXPIRED` | 422 |
| `ERR_PRACTICE_MISMATCH` | 422 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_PRACTICE_SUSPENDED` | 409 |
| `ERR_TRADE_IN_ALREADY_APPLIED` | 409 |
| `ERR_PARTS_NOT_ON_VAN` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_REBATE_FUND_EXHAUSTED` | 422 |
| `ERR_TRADE_IN_CREDIT_EXCEEDS_PRICE` | 422 |
