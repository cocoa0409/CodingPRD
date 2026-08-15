# Veterinary Supply Distribution API — Product Requirements Document

## 1. Introduction

A veterinary supply distributor operates at the intersection of wholesale logistics and pharmaceutical regulation. Its customers are clinic practices that order prescription pharmaceuticals, vaccines, capital equipment, and everyday consumables against commercial terms negotiated per account: credit limits, minimum order values, weekly delivery cadences, and freight thresholds. Every prescription product the distributor ships is governed by a manufacturer authorization that pins the clinic to a single approved delivery address and caps quarterly purchase volumes, because manufacturers audit diversion aggressively. Vaccines add a second compliance axis — they must travel cold, with an auditable temperature record from dock to door. And because stock is finite and dated, the warehouse allocates inventory first-expiry-first-out, parks uncovered demand on backorders, and credits clinics for product delivered too close to its expiry date.

This document specifies the REST API that runs that distribution operation end to end. It covers clinic account onboarding and standing, the product catalog and lot-level inventory, manufacturer authorization and diversion controls, order capture against a per-clinic delivery calendar, approval gates, allocation and backorder management, cold-chain shipment handling, manufacturer bundle and rebate programs, and short-date credits. Time-dependent behavior — authorization expiry, lot expiry, credit staleness — is driven by an explicit logical clock rather than wall-clock time, so every sweep is reproducible. Five roles share the workload: the clinic's own purchasing users, plus the distributor's account managers, supply chain planners, compliance officers, and a technical administrator. All resources are served under the `/vet` mount.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized role values are exactly `ClinicBuyer`, `AccountManager`, `SupplyChainPlanner`, `ComplianceOfficer`, and `SystemAdmin`. A request with a missing header or an unrecognized role value is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity is anchored differently per role. When `X-User-Role` is `ClinicBuyer`, `X-User-ID` is the `id` of the acting Clinic; ownership checks on any resource that references a Clinic compare the resource's `clinic_id` field to `X-User-ID`. A `ClinicBuyer` may run its mutation capabilities — creating an order, submitting an order, cancelling an order, cancelling a backorder line, requesting a short-date credit, and creating a bundle enrollment — only against resources whose `clinic_id` equals its own `X-User-ID`; acting on another clinic's resource is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Read endpoints are not ownership-scoped. When `X-User-Role` is `AccountManager`, `SupplyChainPlanner`, `ComplianceOfficer`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

Requests that match no defined route, and requests using an unsupported method on a defined route, are answered in the same error envelope with `error_id` `ERR_NOT_FOUND` and HTTP status 404.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Values outside these bounds — a `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either — are rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time-dependent behavior in the system reads a single logical clock — never wall-clock time. At server startup the clock reads exactly `2026-08-01T00:00:00Z`. A `SystemAdmin`-only capability advances the clock by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc`. The clock never moves backward: a `to_iso8601` strictly earlier than the current logical instant is rejected with `ERR_INVALID_REQUEST`, while an instant equal to it is accepted and still runs the sweeps below. Each advance of the clock runs three sweeps as part of the same request: every ManufacturerAuthorization in `APPROVED` whose `valid_until` falls strictly before the new current date moves to `EXPIRED`; every InventoryLot whose `expiry_date` falls strictly before the new current date moves to `EXPIRED`, firing the allocation-release cascade described in §3.6 (a lot expiring exactly on the new date survives the sweep, as does an authorization whose `valid_until` equals it); and every ShortDateCredit in `APPROVED` whose approval date is more than thirty days in the past, and which has not been finalized, moves to `EXPIRED`. The current clock date also drives lot receiving validation, the shelf-life rule in allocation, authorization validity windows, the calendar-quarter labels used by quarterly caps and bundle enrollments, and the day counts behind short-date credits.

### 2.5. Common Resource Properties and Mutation Semantics

Every resource in this API — Clinic, Product, ManufacturerAuthorization, InventoryLot, Order, OrderLine, BackorderLine, Shipment, BundleProgram, BundleEnrollment, RebateAccrual, and ShortDateCredit — carries a common set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): starts at 1 when the resource is created and increments by one on every modification.

The `created_at` and `updated_at` bookkeeping timestamps (and the `api_request_timestamp` of §2.2) are stamped from the server's wall clock in UTC; the logical clock of §2.4 drives only time-dependent business rules — sweeps, expiry and window comparisons, quarter labels, and day counts — never these record-keeping fields.

Every mutation — whether triggered by a client request or by a system cascade such as a clock sweep, an allocation waterfall, or an order recompute — updates `updated_at` and increments `version` on each record it touches, parent and child alike. A triggering request and all of its cascades commit atomically: either every effect lands or the request fails outright. Many system transitions happen without any client call against the affected resource — lots deplete themselves, orders recompute when their backorders resolve, accruals reverse when their order cancels — and each such automatic reconciliation is a full mutation of the record it touches.

### 2.6. Monetary Representation and Rounding Discipline

All monetary amounts are integer cents; no fractional cents exist anywhere in the API. Where a calculation produces a fractional intermediate value, the system rounds half up to whole cents, and the point at which rounding happens is pinned per calculation: per-line bundle discounts are rounded before they are summed, per-line rebate amounts are rounded before they are summed, and per-unit short-date credit amounts are rounded before they are multiplied by quantity. Temperature values are compared exactly as supplied, to a tenth of a degree Celsius.

### 2.7. Optimistic Concurrency Control on Clinic Records

Two write operations guard the Clinic aggregate with optimistic concurrency control: the clinic commercial-terms update (`PATCH /vet/clinics/{id}`) and the bundle-enrollment creation (`POST /vet/clinics/{clinicId}/bundle-enrollments`). Each request must carry `expected_clinic_version`, a non-optional field holding the `version` of the Clinic the client last observed. If the clinic's current `version` differs from `expected_clinic_version` — because another writer has advanced the record since the client read it — the request is rejected with `ERR_STALE_CLINIC_VERSION` (HTTP 412), and the client must re-read the clinic before re-applying its change. On the clinic-terms update, a missing, null, or non-integer `expected_clinic_version` fails with `ERR_STALE_CLINIC_VERSION` as well; on bundle-enrollment creation the field is structurally required, so its absence fails with `ERR_INVALID_REQUEST`, while a non-integer or stale value fails with `ERR_STALE_CLINIC_VERSION`. On the clinic update the version check fires after the clinic resolves and before any field is edited; on enrollment creation it fires after the clinic-`ACTIVE` and program-`ACTIVE` gates. A successful guarded update or enrollment creation increments the Clinic's `version` by one. Endpoints not named in this section do not accept a version field.

### 2.8. Request Validation Pipeline

Every request is validated in a fixed order, and the first failing check determines the error returned:

1. **User context.** `X-User-ID` and `X-User-Role` must be present and the role recognized, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The role must be permitted on the endpoint, otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Ownership.** On `ClinicBuyer`-accessible mutation endpoints, the targeted resource's `clinic_id` must equal `X-User-ID`, otherwise `ERR_FORBIDDEN_OWNERSHIP`. Where the clinic is named in the request body — order creation and bundle-enrollment creation — this check fires against that `clinic_id` before any identifier resolution; on every other mutation the resources named in the path and body are resolved first (in step 4's left-to-right order) and the check fires against the resolved resource's `clinic_id`, so a non-existent path identifier yields its 404 before any ownership check.
4. **Existence.** Resource identifiers referenced in the path and body are resolved strictly left to right, and the first identifier that does not resolve produces the 404 for its resource type: `ERR_CLINIC_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_BACKORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, or `ERR_CREDIT_NOT_FOUND`. A request that names both a non-existent clinic and a non-existent enrollment therefore fails on the clinic, before the enrollment is ever consulted.
5. **State preconditions.** The target entity must sit in the state its transition requires, otherwise the per-entity invalid-state error (HTTP 409): `ERR_CLINIC_INVALID_STATE`, `ERR_PRODUCT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_ORDER_LINE_INVALID_STATE`, `ERR_SHIPMENT_INVALID_STATE`, `ERR_PROGRAM_INVALID_STATE`, `ERR_CREDIT_INVALID_STATE`, or `ERR_BACKORDER_LINE_INVALID_STATE`.
6. **Cross-entity state gates.** Order submission and approval, authorization approval, and bundle-enrollment creation require the Clinic in `ACTIVE` (`ERR_CLINIC_NOT_ACTIVE`); enrollment creation also requires the BundleProgram in `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`); shipment creation requires the Order in `APPROVED` (`ERR_ORDER_INVALID_STATE`).
7. **Business safety rules.** Prescription authorization, controlled-substance registration, diversion address matching, quarterly volume caps, cold-chain carrier certification, and temperature-log applicability, as detailed in §3.
8. **Structural and business constraints.** Required fields present, enum values valid, quantities positive, and the ordering rules on dates and windows, otherwise `ERR_INVALID_REQUEST` or the specific constraint error of §3.
9. **Fiscal rules.** Minimum order value, credit limit, and credit finalize quantity, as detailed in §3.

Within this pipeline, the detection of missing required fields happens the moment an endpoint first reads its request body — for create endpoints, before any identifier in the body is resolved — and each present field's type, enum, and range validation fires at the point the endpoint consumes it. The per-endpoint sequences of §3 pin every remaining ordering question.

### 2.9. Open-Order Credit Exposure

Each Clinic carries a `credit_limit_cents` ceiling and a live `credit_used_cents` exposure figure. Exposure is defined precisely: `credit_used_cents` is the sum of `total_cents` over the clinic's orders in `APPROVED`, `BACKORDERED`, or `SHIPPED` status. Orders in `DRAFT` or `SUBMITTED` have not yet committed funds; a `DELIVERED` order has left the counted set (invoicing is out of scope); `REJECTED` and `CANCELLED` orders are excluded. The figure is recomputed on every order status change for the clinic, so an order that ships, delivers, cancels, or falls back to backorder immediately moves the clinic's exposure.

### 2.10. Cold-Chain Compliance

Cold-chain handling is a derived property, never a declared one. A Product's `requires_cold_chain` flag is computed: it is true exactly when `product_type` is `VACCINE`, and any client-supplied value for it is ignored. A Shipment's own `requires_cold_chain` is likewise computed — true exactly when at least one line of the shipped order is on a product that requires the cold chain. Any shipment carrying cold-chain lines must travel with a carrier declared cold-chain certified, and while in transit it accepts an append-only temperature record. A reading is in range exactly when it lies between 2.0 and 8.0 degrees Celsius inclusive — a reading of exactly 2.0 or exactly 8.0 is acceptable, and anything strictly outside that band is an excursion that automatically quarantines the shipment. Only a quality disposition by a `ComplianceOfficer` resolves a quarantine.

## 3. Business Logic & Workflows

### 3.1. Clinic Onboarding and Account Standing

An `AccountManager` onboards a practice by supplying its `clinic_name`, state veterinary practice `license_number`, primary `ship_to_address`, and commercial terms: `credit_limit_cents` (zero or more), `minimum_order_value_cents` (zero or more), `delivery_frequency_per_week` (at least one), and `free_freight_threshold_cents` (zero or more). Clinics that will order controlled substances also need a `dea_registration_number`; it is optional at onboarding and defaults to null, but its absence blocks controlled-substance orders later. A new clinic starts in `PENDING_VERIFICATION` with `credit_used_cents` at zero and `version` at 1.

Verification moves the clinic from `PENDING_VERIFICATION` to `ACTIVE`; attempting activation from any other state is rejected with `ERR_CLINIC_INVALID_STATE`. An `AccountManager` may later suspend an `ACTIVE` clinic (moving it to `SUSPENDED`) and reinstate a `SUSPENDED` one back to `ACTIVE`; both transitions require the named source state and otherwise fail with `ERR_CLINIC_INVALID_STATE`, and each increments the clinic's `version`. Suspension freezes commercial activity: while a clinic is `SUSPENDED`, order submission, order approval, authorization approval, and bundle enrollment all fail with `ERR_CLINIC_NOT_ACTIVE`, yet the clinic's `DRAFT` orders remain `DRAFT` — suspension cascades to nothing. The clinic's `status` field is always system-managed; clients never set it directly.

Commercial terms change over time, and the `AccountManager` edits them through the version-guarded update described in §2.7: the request carries `expected_clinic_version` plus any subset of `clinic_name`, `ship_to_address`, `credit_limit_cents`, `minimum_order_value_cents`, `delivery_frequency_per_week`, and `free_freight_threshold_cents`; fields outside this subset — including `status`, `credit_used_cents`, and `dea_registration_number` — carry no effect when sent. A stale `expected_clinic_version` is rejected with `ERR_STALE_CLINIC_VERSION`, and a successful edit increments the clinic's `version` by one.

### 3.2. Catalog Management and Stock Receiving

A `SupplyChainPlanner` maintains the catalog. Creating a product takes a `sku` (unique across all products — a duplicate is rejected with `ERR_DUPLICATE_SKU`), a `product_name`, a `manufacturer_code`, a `product_type` of `RX_PHARMACEUTICAL`, `VACCINE`, `EQUIPMENT`, or `CONSUMABLE`, an optional `is_controlled_substance` flag defaulting to false, and a strictly positive `unit_price_cents`. The `manufacturer_code` is a plain string, not a reference: manufacturer authorizations and bundle programs match against it textually. The product's `requires_cold_chain` derives from its type per §2.10, and its `status` starts at `LISTED`. Catalog listings may be filtered by `sku`, `manufacturer_code`, `product_type`, or `status`.

Discontinuing moves a `LISTED` product to `DISCONTINUED` — its terminal state — and is rejected with `ERR_PRODUCT_INVALID_STATE` from anywhere else. Discontinuation is forward-looking only: existing orders are untouched, but submitting a new order containing a `DISCONTINUED` product fails with `ERR_PRODUCT_DISCONTINUED`.

Stock arrives in lots. Receiving a lot takes the `product_id` of the stocked product, a `lot_number`, an `expiry_date`, and a positive `qty_on_hand`. The expiry date must fall strictly after the current clock date at receiving; otherwise the receipt is rejected with `ERR_INVALID_LOT_EXPIRY`. A fresh lot starts `AVAILABLE` with `qty_allocated` at zero and `qty_available` equal to `qty_on_hand`. Lot bookkeeping obeys a conservation invariant at all times: `qty_on_hand` always equals `qty_allocated` plus `qty_available`, where `qty_allocated` counts the units reserved by `ALLOCATED` order lines. When allocation or dispatch drains `qty_available` to zero the lot moves itself from `AVAILABLE` to `DEPLETED`; when a release lifts `qty_available` back above zero it returns from `DEPLETED` to `AVAILABLE`. Receiving new stock also wakes the backorder waterfall for that product, described in §3.6. Lot listings may be filtered by `product_id` or `status`.

### 3.3. Manufacturer Authorizations and Diversion Controls

Before a clinic may buy a manufacturer's prescription products, a `ComplianceOfficer` records a ManufacturerAuthorization naming the `clinic_id`, the `manufacturer_code` it covers, a validity window from `valid_from` through `valid_until` (the window is a closed interval, and `valid_until` before `valid_from` is an `ERR_INVALID_REQUEST`), the single `approved_ship_to_address` that may receive that manufacturer's prescription goods, and a strictly positive `quarterly_quantity_cap`. A new authorization starts `PENDING` with `quantity_approved_this_quarter` at zero. Windows are exclusive per clinic and manufacturer: for the same `clinic_id` and `manufacturer_code`, no two authorizations in `PENDING`, `APPROVED`, or `SUSPENDED` may share any calendar date, and because the intervals are closed, one authorization's `valid_from` landing exactly on another's `valid_until` is already a conflict — reported as `ERR_AUTHORIZATION_WINDOW_OVERLAP`. Authorization listings may be filtered by `clinic_id`, `manufacturer_code`, or `status`.

The lifecycle runs `PENDING` → `APPROVED` on approval, which additionally requires the referenced clinic to be `ACTIVE` (otherwise `ERR_CLINIC_NOT_ACTIVE`); approval from any state other than `PENDING` fails with `ERR_AUTHORIZATION_INVALID_STATE`. An `APPROVED` authorization may be suspended (`APPROVED` → `SUSPENDED`), and a `SUSPENDED` one reinstated back to `APPROVED` — but reinstatement is only possible while the window is still open, that is, while `valid_until` is on or after the current clock date; an out-of-window reinstatement fails with `ERR_AUTHORIZATION_INVALID_STATE`, as does either transition from the wrong source state. Revocation is terminal and available from any of `PENDING`, `APPROVED`, or `SUSPENDED`, moving the authorization to `REVOKED`. Finally, the clock sweep of §2.4 moves an `APPROVED` authorization to `EXPIRED` once its `valid_until` falls strictly before the new current date. `REVOKED` and `EXPIRED` are terminal.

The `quantity_approved_this_quarter` counter tracks how many prescription units of the manufacturer the clinic has had approved in the current calendar quarter: it accrues the order's prescription units at each approval and is decremented when an approved order is cancelled before dispatch. When the calendar quarter of the logical clock changes, the counter resets — evaluated lazily at the next approval rather than by a scheduled job.

### 3.4. Building and Submitting an Order

A `ClinicBuyer` drafts an order for its own clinic by supplying the `clinic_id`, the `ship_to_address`, a delivery window from `delivery_window_start` to `delivery_window_end`, and the `lines` — each naming a `product_id` and a positive `qty_requested`. The `lines` array may be empty at draft time; the at-least-one-line rule below bites only at submission. The window is half-open: the end must be strictly later than the start, and a window whose end equals or precedes its start is an `ERR_INVALID_REQUEST`. A new order starts `DRAFT`, and each of its lines starts `PENDING`. Until submission the order's money fields (`merchandise_subtotal_cents` through `total_cents`) read zero, its `rejection_reason` is null, and each line's `unit_price_cents` and `line_total_cents` are null with `qty_allocated` at zero and `lot_id` null. Order listings may be filtered by `clinic_id` or `status`; order-line listings by `order_id`, `product_id`, `lot_id`, or `status`.

Submission is where an order becomes real, and its checks run in a fixed sequence. First the order must be `DRAFT` (otherwise `ERR_ORDER_INVALID_STATE`) and the clinic must be `ACTIVE` (otherwise `ERR_CLINIC_NOT_ACTIVE`). Structural checks follow: the order must carry at least one line and every line must be well-formed, otherwise `ERR_INVALID_REQUEST`. Then the delivery calendar is consulted. The clinic's orders in `SUBMITTED`, `APPROVED`, or `BACKORDERED` hold their delivery windows; a new window may touch an existing one — the new window's start equalling another's end is fine — but may not intersect it, otherwise `ERR_DELIVERY_WINDOW_OVERLAP`. The weekly cadence is enforced next: counting the submitting order together with the clinic's other window-holding orders whose `delivery_window_start` falls in the same ISO week, the total must remain at or below the clinic's `delivery_frequency_per_week`, otherwise `ERR_DELIVERY_FREQUENCY_EXCEEDED`. Catalog standing is then verified: every line's product must still be `LISTED`, otherwise `ERR_PRODUCT_DISCONTINUED`. Last of the submit-time checks, the merchandise net must reach the clinic's `minimum_order_value_cents` — an order whose net equals the minimum exactly passes — otherwise `ERR_ORDER_BELOW_MINIMUM`.

A successful submission does several things at once. Each line snapshots the product's current `unit_price_cents` — later catalog price changes never rewrite a submitted order — and computes its `line_total_cents` as the snapshotted price multiplied by `qty_requested`, an exact integer. The order's money fields are then computed in a pinned evaluation order. First, `merchandise_subtotal_cents` is the sum of the `line_total_cents` over all lines. Second, bundle qualification is decided: the clinic must hold an `ACTIVE` BundleEnrollment for the calendar-quarter label of the current clock date whose BundleProgram is also `ACTIVE`, and the order's qualifying lines — those whose product matches the program's `manufacturer_code` and whose `product_type` lies within the program's `qualifying_product_types` — must span at least the program's `min_distinct_categories` distinct product types. Third, `bundle_discount_cents` is computed: for each qualifying line, the line's gross total is multiplied by the program's `bundle_discount_pct` and divided by one hundred, rounded half up to whole cents per line, and the per-line results are summed; a non-qualified order gets a discount of zero. Fourth, `merchandise_net_cents` is the subtotal minus the discount. Fifth, `equipment_surcharge_cents` is 1,500 cents per unit summed over the order's `EQUIPMENT` lines, and it is never waived. Sixth, `freight_fee_cents` is zero when the merchandise net reaches the clinic's `free_freight_threshold_cents` — equality waives freight — and a flat 2,500 cents otherwise. Finally, `total_cents` is the merchandise net plus the equipment surcharge plus the freight fee. Freight is therefore always computed on the net, never on the gross subtotal, while the discount is computed on the gross qualifying lines, never on the net. Submission also reserves the delivery window on the clinic's calendar, moves the order from `DRAFT` to `SUBMITTED`, and increments its `version`. The computed totals persist until the order is cancelled or rejected.

### 3.5. Approval, Safety Gates, and Allocation

Approval is the `AccountManager`'s decision, and it is the most heavily gated transition in the system. The checks fire in this order. The order must be `SUBMITTED` (otherwise `ERR_ORDER_INVALID_STATE`) and the clinic still `ACTIVE` (otherwise `ERR_CLINIC_NOT_ACTIVE`). Then the prescription-safety sequence runs. For every `RX_PHARMACEUTICAL` line, the clinic must hold a ManufacturerAuthorization for that line's manufacturer that is `APPROVED` and whose window covers the current clock date on both ends — `valid_from` on or before the date and `valid_until` on or after it — otherwise the approval is rejected with `ERR_RX_AUTHORIZATION_REQUIRED`. If any line's product has `is_controlled_substance` set, the clinic's `dea_registration_number` must be non-null, otherwise `ERR_DEA_REGISTRATION_REQUIRED`. Whenever the order carries any prescription line, the order's `ship_to_address` must equal the authorization's `approved_ship_to_address` exactly — diversion prevention — otherwise `ERR_SHIP_TO_DIVERSION_MISMATCH`. When several distinct manufacturers appear on the order's prescription lines, the comparison runs against each one's covering authorization, so the single `ship_to_address` must equal every such `approved_ship_to_address`. The quarterly volume cap is evaluated per distinct manufacturer on the order's prescription lines: the authorization's `quantity_approved_this_quarter` plus this order's prescription units for that manufacturer may reach but must not exceed `quarterly_quantity_cap` — the cap is inclusive, so landing exactly on it is allowed and only exceeding it yields `ERR_QUARTERLY_CAP_EXCEEDED`. Finally the fiscal gate: the clinic's `credit_used_cents` plus this order's `total_cents` must remain at or below `credit_limit_cents` — equality passes — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

An approval that clears every gate allocates stock first-expiry-first-out, processing the order's lines in the order they were created. For each `PENDING` line, candidate lots are those of the line's product that are `AVAILABLE`, can cover the full `qty_requested` from a single lot — allocation is all-or-nothing per line, never split — and whose `expiry_date` falls at least thirty days beyond the day the delivery window ends, so that product arrives with a minimum shelf life intact. Among candidates the earliest `expiry_date` wins; ties break by the lot's earlier `created_at`, never by identifier. A covered line moves `PENDING` → `ALLOCATED` with its `lot_id` set to the covering lot, its `qty_allocated` set to the full `qty_requested`, and the lot's `qty_allocated` increased by the same amount. A line no single lot can cover moves `PENDING` → `BACKORDERED` and mints a BackorderLine whose `qty_open` equals the full `qty_requested`.

The order's own landing state reflects its lines: when every line allocated, the order moves `SUBMITTED` → `APPROVED`; when at least one line went to backorder, it moves `SUBMITTED` → `BACKORDERED` instead, with identical allocation and accrual side effects. Approval also adds the order's prescription units to each authorization's `quantity_approved_this_quarter`, recomputes the clinic's `credit_used_cents`, and increments the order's `version`. And when the clinic holds an `ACTIVE` BundleEnrollment for the current quarter whose program is `ACTIVE` and the order carries at least one qualifying line, approval mints a RebateAccrual in `PROVISIONAL` status per §3.8.

Rejection is the alternative: an `AccountManager` may reject a `SUBMITTED` order — from any other state the attempt fails with `ERR_ORDER_INVALID_STATE` — recording the supplied `rejection_reason`, releasing the reserved delivery window, and moving the order to its terminal `REJECTED` state.

### 3.6. Backorders, the Allocation Waterfall, and Cancellation

A BackorderLine records unserved demand: it references its `order_line_id`, opens with `qty_open` equal to the shorted line's full `qty_requested`, and carries an `allocation_sequence` — a strictly monotonically increasing integer minted at creation, starting from 1 — that is the sole ordering key of the allocation waterfall and is never derived from the record's `id`. Its `status` runs from `OPEN` to either `FILLED` or `CANCELLED`, both terminal. The backorders of a given order line can be listed, and an individual backorder's history is readable through its order line.

The waterfall wakes whenever new availability appears for a product: a lot receipt, and the allocation release of an order cancellation. A backorder cancellation frees no stock and does not wake it, and neither does the expiry sweep of §2.4 — backorders minted by an expiry wait for the next receipt or cancellation-driven release. It sweeps the `OPEN` BackorderLines whose order line is for the affected product in strict `allocation_sequence` ascending order. A backorder is filled only when a single lot can cover its full `qty_open` — the same all-or-nothing single-lot rule as approval-time allocation, choosing among lots by earliest `expiry_date` and then earliest lot `created_at`. A backorder that no single lot can cover in full is skipped, and the sweep continues to the next one; leftover stock simply remains available. Each fill zeroes the backorder's `qty_open` and moves it to `FILLED`, moves its order line from `BACKORDERED` to `ALLOCATED` with `lot_id` set and `qty_allocated` restored to the full `qty_requested`, and increases the filling lot's `qty_allocated` by the filled quantity. After the fills, each affected order recomputes: when no `OPEN` backorder and no `BACKORDERED` line remain on it and at least one line is `ALLOCATED`, the order moves itself from `BACKORDERED` back to `APPROVED`.

A `ClinicBuyer` (for its own clinic) or an `AccountManager` may cancel an individual `OPEN` backorder; cancelling one in any other state fails with `ERR_BACKORDER_LINE_INVALID_STATE`. Cancellation moves the BackorderLine to `CANCELLED` and its parent order line from `BACKORDERED` to `CANCELLED`, then recomputes the parent order: if no line remains `BACKORDERED` and at least one line is `ALLOCATED`, the order returns to `APPROVED`; if every line is now `CANCELLED`, the order itself moves to `CANCELLED`, releasing its delivery window and recomputing the clinic's credit exposure.

Whole-order cancellation — available to the same two actors — is accepted from `DRAFT`, `SUBMITTED`, `APPROVED`, or `BACKORDERED`, and from anywhere else is rejected with `ERR_ORDER_INVALID_STATE`. Its blast radius depends on the source state. Cancelling a `DRAFT` order simply cancels its `PENDING` lines; no window was reserved yet. Cancelling a `SUBMITTED` order likewise cancels its still-`PENDING` lines and additionally releases the reserved delivery window. Cancelling an `APPROVED` or `BACKORDERED` order fires the full release cascade: every `ALLOCATED` line moves to `CANCELLED` and releases its reservation, decrementing the covering lot's `qty_allocated` by the line's `qty_requested` — which may flip a `DEPLETED` lot back to `AVAILABLE`; the freed availability immediately runs the allocation waterfall for that product, which can fill other orders' backorders and move those orders from `BACKORDERED` to `APPROVED`; the cancelled order's own still-`OPEN` BackorderLines move to `CANCELLED`; its `PROVISIONAL` RebateAccruals move to `REVERSED` and the enrollment's `qtd_qualifying_cents` is decremented accordingly; each authorization's `quantity_approved_this_quarter` is decremented by the order's prescription units — applied, after the same lazy quarter reset, to the most recently created non-terminal (`PENDING`, `APPROVED`, or `SUSPENDED`) authorization for the clinic and manufacturer when one exists, and never driving the counter below zero; and the clinic's `credit_used_cents` is recomputed. Every record touched by the cascade takes its own `updated_at` refresh and `version` increment.

The clock sweep produces the mirror-image cascade. When a lot's `expiry_date` falls strictly before the new current date, the lot moves to `EXPIRED` — terminal — whether it was `AVAILABLE` or `DEPLETED` (a depleted lot may still hold allocations). Every order line holding that lot in `ALLOCATED` reverts to `BACKORDERED` with `qty_allocated` zeroed and `lot_id` cleared, a fresh BackorderLine is minted per reverted line with `qty_open` equal to the full `qty_requested` and a fresh `allocation_sequence`, the lot's own `qty_allocated` is zeroed, and each order left holding at least one `BACKORDERED` line moves from `APPROVED` to `BACKORDERED`.

### 3.7. Shipments, the Cold Chain, and Quarantine Disposition

A `SupplyChainPlanner` creates a shipment against an `APPROVED` order — any other order state fails with `ERR_ORDER_INVALID_STATE` — supplying the `order_id`, a `carrier_name`, and optionally `carrier_cold_chain_certified`, which defaults to false. The shipment's `requires_cold_chain` is computed per §2.10, and when it is true the carrier must be declared certified: a cold-chain shipment without `carrier_cold_chain_certified` set is rejected with `ERR_COLD_CHAIN_CARRIER_REQUIRED`. A new shipment starts `PREPARING`, and shipment listings may be filtered by `order_id` or `status`.

Dispatch moves a `PREPARING` shipment to `IN_TRANSIT` (from any other state, `ERR_SHIPMENT_INVALID_STATE`) and settles the warehouse books in the same breath: every `ALLOCATED` line of the order moves to `SHIPPED`, and for each line the covering lot's `qty_on_hand` and `qty_allocated` are both decremented by the line's `qty_requested`, preserving the conservation invariant of §3.2. The order itself moves from `APPROVED` to `SHIPPED`.

While a cold-chain shipment is `IN_TRANSIT`, the planner appends temperature readings; each reading supplies a `recorded_at` instant and a `temperature_celsius` value and is appended to the shipment's `temperature_log`, an append-only embedded record returned with the shipment. Readings are accepted only for a shipment whose `requires_cold_chain` is true — posting to a non-cold-chain shipment fails with `ERR_TEMPERATURE_LOG_NOT_APPLICABLE` — and only while `IN_TRANSIT`, otherwise `ERR_SHIPMENT_INVALID_STATE`. The applicability check fires first, so a reading posted to a non-cold-chain shipment fails with `ERR_TEMPERATURE_LOG_NOT_APPLICABLE` regardless of the shipment's state. A reading strictly outside the 2.0-to-8.0-degree band of §2.10 marks an excursion: the shipment's `has_unresolved_excursion` flag becomes true and the shipment moves itself from `IN_TRANSIT` to `QUARANTINED` in the same request.

Quarantine ends only by a `ComplianceOfficer`'s quality disposition, which supplies an `outcome` of `RELEASED` or `DESTROYED` — any other value is an `ERR_INVALID_REQUEST`, and this value check fires before the state precondition; disposition from any state other than `QUARANTINED` fails with `ERR_SHIPMENT_INVALID_STATE`. `RELEASED` returns the shipment to `IN_TRANSIT` and clears `has_unresolved_excursion` — it is the only way that flag clears. `DESTROYED` is terminal and fires a two-level cascade: every `SHIPPED` line of the order moves back to `BACKORDERED`, the destroyed goods are not returned to stock — `qty_on_hand` is not restored — a fresh BackorderLine is minted per line for the full `qty_requested` with a fresh `allocation_sequence`, the order moves from `SHIPPED` back to `BACKORDERED`, and the clinic's `credit_used_cents` is recomputed as the order re-enters the counted set.

Delivery is the happy ending: a `SupplyChainPlanner` delivers an `IN_TRANSIT` shipment (otherwise `ERR_SHIPMENT_INVALID_STATE`), moving it to `DELIVERED`, moving every `SHIPPED` line to `DELIVERED`, moving the order from `SHIPPED` to `DELIVERED`, and recomputing the clinic's credit exposure as the order leaves the counted set. Delivered lines become eligible for the short-date credit workflow of §3.9.

### 3.8. Bundle Programs, Enrollment, and Rebate Accrual

An `AccountManager` authors a BundleProgram with a `program_name`, the `manufacturer_code` it scopes, the `qualifying_product_types` it rewards (a non-empty subset of `RX_PHARMACEUTICAL`, `VACCINE`, `EQUIPMENT`, and `CONSUMABLE`), a `min_distinct_categories` of at least one, a `bundle_discount_pct` between 0 and 100 inclusive, the `rebate_base_rate_bp` and `rebate_bonus_rate_bp` accrual rates in basis points, each zero or more — and the bonus rate must be at least the base rate — and the `bonus_threshold_cents` (zero or more) at which the bonus rate kicks in. A program starts `DRAFT`, moves to `ACTIVE` on activation, and to terminal `CLOSED` on close; activation or close from the wrong state fails with `ERR_PROGRAM_INVALID_STATE`.

A `ClinicBuyer` enrolls its own clinic in a program for a calendar quarter by naming the `program_id` and a `quarter` label such as `2026-Q3` on a request routed at the clinic — the path carries the clinic's identifier as `clinicId`. The `quarter` label is accepted as any non-empty string; its format is not validated and it need not equal the quarter of the current clock date. Enrollment requires the clinic `ACTIVE` (`ERR_CLINIC_NOT_ACTIVE`) and the program `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`), and it is the second OCC-guarded write of §2.7: the request must carry `expected_clinic_version` matching the clinic's current `version`, otherwise `ERR_STALE_CLINIC_VERSION`, and a successful enrollment increments the clinic's `version` by one. Only one enrollment per clinic and quarter may be live: creating a new BundleEnrollment for a clinic and quarter that already has an `ACTIVE` one moves the prior enrollment to `SUPERSEDED` and reverses its `PROVISIONAL` accruals — each such RebateAccrual moves to `REVERSED`. The new enrollment starts `ACTIVE` with `qtd_qualifying_cents` at zero. Enrollment listings may be filtered by `clinic_id`, `program_id`, `quarter`, or `status`; accrual listings by `enrollment_id`, `order_id`, or `status`.

Rebates accrue twice, provisionally at approval and finally at program close, and the two variants answer different questions. Both share a definition of the qualifying net line amount: a qualifying line's `line_total_cents` minus that line's share of the bundle discount, where the line's discount is its gross total multiplied by `bundle_discount_pct`, divided by one hundred, and rounded half up to whole cents. The provisional variant runs at order approval — including approvals that land the order in `BACKORDERED`. The rate is chosen by the enrollment's `qtd_qualifying_cents` before this order is counted: when that running total has already reached the program's `bonus_threshold_cents`, the `rebate_bonus_rate_bp` applies, otherwise the `rebate_base_rate_bp`; equality earns the bonus. The accrual's `provisional_amount_cents` is then the sum over the order's qualifying lines of each net line amount multiplied by the chosen rate in basis points and divided by ten thousand, rounded half up per line before summation. The enrollment's `qtd_qualifying_cents` — the sum of net qualifying line amounts over the clinic's orders tagged to this enrollment in `APPROVED`, `BACKORDERED`, `SHIPPED`, or `DELIVERED` status — is then increased by this order's net qualifying amounts.

The final variant runs when the `AccountManager` closes the program. Closing computes, for every enrollment of the program, a final quarter-to-date figure over all of the enrollment's clinic's `DELIVERED` orders only — whether or not an order accrued against that particular enrollment — picks a single retroactive rate by comparing that final figure to `bonus_threshold_cents` — equality earns the bonus — and re-evaluates every `PROVISIONAL` accrual: an accrual whose order is `DELIVERED` moves to `FINALIZED` with its `final_amount_cents` set to the sum over that delivered order's qualifying lines of each net line amount multiplied by the final rate and divided by ten thousand, rounded half up per line; an accrual whose order never delivered moves to `REVERSED` with no final amount. Every `ACTIVE` enrollment of the program moves to `FINALIZED`. The provisional tier is thus non-cumulative — each order's rate was locked by the running total before it — while the final tier is fully retroactive over the quarter's delivered business, so identical order data can yield different provisional and final amounts whenever the quarter crosses the bonus threshold or an order is cancelled or left undelivered. A RebateAccrual's `final_amount_cents` stays null until finalization, and a `PROVISIONAL` accrual reverses on exactly three events: its order is cancelled, its enrollment is superseded, or its program closes with the order undelivered. Accruals carry their `enrollment_id` and `order_id` for traceability.

### 3.9. Short-Dated Stock Credits

Product delivered too close to its expiry earns the clinic a credit. A `ClinicBuyer` requests one against a line of its own clinic by naming the `order_line_id`, the `lot_id`, and the `qty` being credited. The line must be `DELIVERED` — requesting against a line in any other state fails with `ERR_ORDER_LINE_INVALID_STATE` — and the named lot must be the very lot that covered the line, otherwise `ERR_LOT_LINE_MISMATCH`. The quantity must be at least one and no more than the line's `qty_requested`. Eligibility turns on `days_to_expiry_at_request`, computed as the lot's `expiry_date` minus the current clock date in whole days: a line whose lot still has more than 180 days to run is not short-dated at all and is rejected with `ERR_NOT_SHORT_DATED`, while exactly 180 days is eligible. The credit record derives its `clinic_id` from the line's order, starts in `REQUESTED`, and computes its `claimed_credit_cents` immediately. The record also stores `days_to_expiry_at_request`, carries `received_qty` (null until finalization), and stamps `approved_on` with the logical-clock date of approval (null until approved).

The claimed amount uses a tiered per-unit rate keyed to `days_to_expiry_at_request`: thirty days or fewer to expiry earns full credit — one hundred percent of the line's snapshotted `unit_price_cents`; thirty-one to ninety days earns half; ninety-one to one hundred eighty days earns a quarter. The per-unit credit — the snapshot price multiplied by the tier rate — is rounded half up to whole cents first and only then multiplied by `qty` to produce `claimed_credit_cents`; rounding after multiplying is the forbidden alternative. By way of example, a 999-cent unit at the half-credit tier with a quantity of three credits 500 cents per unit for a 1,500-cent total — not 1,499, which is what rounding the un-rounded product would give. Credit listings may be filtered by `clinic_id`, `order_line_id`, `lot_id`, or `status`.

Adjudication belongs to the `ComplianceOfficer`. A `REQUESTED` credit may be approved, moving it to `APPROVED`, or denied, moving it to terminal `DENIED`; either action from the wrong state fails with `ERR_CREDIT_INVALID_STATE`. Once the returned goods physically arrive, the officer finalizes an `APPROVED` credit by supplying the `received_qty`, which must fall between one and the originally claimed `qty` inclusive — a count outside that band is rejected with `ERR_RECEIVED_QTY_EXCEEDS_CLAIMED`. Finalization re-evaluates the tier at the receipt clock date: the days-to-expiry figure is recomputed against the lot's `expiry_date`, the per-unit rate re-selected from the same three tiers, and `final_credit_cents` computed as the per-unit credit rounded half up to whole cents, multiplied by `received_qty`. If the recomputed days-to-expiry exceeds 180 no tier applies, and the finalization is rejected with `ERR_NOT_SHORT_DATED`. The credit then moves to its terminal `CREDITED` state; until that moment `final_credit_cents` remains null. Claimed and final amounts diverge whenever the receipt-date tier differs from the request-date tier or fewer units come back than were claimed. An approved credit left unfinalized too long dies on the vine: the clock sweep of §2.4 moves it from `APPROVED` to `EXPIRED` once the current date runs more than thirty days past its approval date.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that transition or modify an existing resource return `200 OK`. Recording a temperature reading also returns `201 Created`, because each call appends a new reading to the shipment's log.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vet/_clock/set_current_utc` | Advance the logical clock; runs time-based sweeps | SystemAdmin |
| POST | `/vet/clinics` | Onboard a clinic account | AccountManager |
| GET | `/vet/clinics/{id}` | Read a clinic | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| PATCH | `/vet/clinics/{id}` | Update clinic commercial terms (OCC-guarded) | AccountManager |
| POST | `/vet/clinics/{id}/activate` | Verify and activate a clinic | AccountManager |
| POST | `/vet/clinics/{id}/suspend` | Suspend a clinic | AccountManager |
| POST | `/vet/clinics/{id}/reinstate` | Reinstate a suspended clinic | AccountManager |
| POST | `/vet/products` | Create a catalog product | SupplyChainPlanner |
| GET | `/vet/products` | List products with filters | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/products/{id}` | Read a product | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/products/{id}/discontinue` | Discontinue a product | SupplyChainPlanner |
| POST | `/vet/manufacturer-authorizations` | Request a manufacturer authorization for a clinic | ComplianceOfficer |
| GET | `/vet/manufacturer-authorizations` | List authorizations with filters | AccountManager, ClinicBuyer, ComplianceOfficer |
| GET | `/vet/manufacturer-authorizations/{id}` | Read an authorization | AccountManager, ClinicBuyer, ComplianceOfficer |
| POST | `/vet/manufacturer-authorizations/{id}/approve` | Approve a pending authorization | ComplianceOfficer |
| POST | `/vet/manufacturer-authorizations/{id}/suspend` | Suspend an approved authorization | ComplianceOfficer |
| POST | `/vet/manufacturer-authorizations/{id}/reinstate` | Reinstate a suspended authorization | ComplianceOfficer |
| POST | `/vet/manufacturer-authorizations/{id}/revoke` | Revoke an authorization (terminal) | ComplianceOfficer |
| POST | `/vet/inventory-lots` | Receive stock into a new lot; triggers backorder allocation | SupplyChainPlanner |
| GET | `/vet/inventory-lots` | List lots with filters | AccountManager, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/inventory-lots/{id}` | Read a lot | AccountManager, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/orders` | Create a draft order with embedded lines | ClinicBuyer |
| GET | `/vet/orders` | List orders with filters | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/orders/{id}` | Read an order | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/orders/{id}/submit` | Submit a draft order: snapshot prices, compute totals, reserve the window | ClinicBuyer |
| POST | `/vet/orders/{id}/approve` | Approve a submitted order: safety gates, then allocation | AccountManager |
| POST | `/vet/orders/{id}/reject` | Reject a submitted order | AccountManager |
| POST | `/vet/orders/{id}/cancel` | Cancel an order; fires the release cascade | ClinicBuyer, AccountManager |
| GET | `/vet/order-lines` | List order lines with filters | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/order-lines/{id}` | Read an order line | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/order-lines/{id}/backorder-lines` | List backorder lines of an order line | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/backorder-lines/{id}/cancel` | Cancel an open backorder line; parent order recomputes | ClinicBuyer, AccountManager |
| POST | `/vet/shipments` | Create a shipment for an approved order | SupplyChainPlanner |
| GET | `/vet/shipments` | List shipments with filters | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| GET | `/vet/shipments/{id}` | Read a shipment (includes the temperature log) | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/shipments/{id}/dispatch` | Dispatch a preparing shipment | SupplyChainPlanner |
| POST | `/vet/shipments/{id}/deliver` | Deliver an in-transit shipment | SupplyChainPlanner |
| POST | `/vet/shipments/{id}/temperature-readings` | Append a temperature reading | SupplyChainPlanner |
| POST | `/vet/shipments/{id}/resolve-quarantine` | Quality disposition of a quarantined shipment | ComplianceOfficer |
| POST | `/vet/bundle-programs` | Create a bundle/rebate program | AccountManager |
| GET | `/vet/bundle-programs/{id}` | Read a program | AccountManager, ClinicBuyer, SupplyChainPlanner, ComplianceOfficer |
| POST | `/vet/bundle-programs/{id}/activate` | Activate a draft program | AccountManager |
| POST | `/vet/bundle-programs/{id}/close` | Close an active program: finalize accruals and enrollments | AccountManager |
| POST | `/vet/clinics/{clinicId}/bundle-enrollments` | Enroll a clinic in a program for a quarter (OCC-guarded) | ClinicBuyer |
| GET | `/vet/bundle-enrollments` | List enrollments with filters | AccountManager, ClinicBuyer, ComplianceOfficer |
| GET | `/vet/bundle-enrollments/{id}` | Read an enrollment | AccountManager, ClinicBuyer, ComplianceOfficer |
| GET | `/vet/rebate-accruals` | List rebate accruals with filters | AccountManager, ClinicBuyer, ComplianceOfficer |
| GET | `/vet/rebate-accruals/{id}` | Read a rebate accrual | AccountManager, ClinicBuyer, ComplianceOfficer |
| POST | `/vet/short-date-credits` | Request a short-date credit against a delivered order line | ClinicBuyer |
| GET | `/vet/short-date-credits` | List short-date credits with filters | AccountManager, ClinicBuyer, ComplianceOfficer |
| GET | `/vet/short-date-credits/{id}` | Read a short-date credit | AccountManager, ClinicBuyer, ComplianceOfficer |
| POST | `/vet/short-date-credits/{id}/approve` | Approve a requested credit | ComplianceOfficer |
| POST | `/vet/short-date-credits/{id}/deny` | Deny a requested credit | ComplianceOfficer |
| POST | `/vet/short-date-credits/{id}/finalize` | Finalize an approved credit on return receipt | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_BACKORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_CLINIC_INVALID_STATE` | 409 Conflict |
| `ERR_PRODUCT_INVALID_STATE` | 409 Conflict |
| `ERR_AUTHORIZATION_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_LINE_INVALID_STATE` | 409 Conflict |
| `ERR_SHIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_CREDIT_INVALID_STATE` | 409 Conflict |
| `ERR_BACKORDER_LINE_INVALID_STATE` | 409 Conflict |
| `ERR_CLINIC_NOT_ACTIVE` | 409 Conflict |
| `ERR_RX_AUTHORIZATION_REQUIRED` | 403 Forbidden |
| `ERR_DEA_REGISTRATION_REQUIRED` | 403 Forbidden |
| `ERR_SHIP_TO_DIVERSION_MISMATCH` | 403 Forbidden |
| `ERR_QUARTERLY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_COLD_CHAIN_CARRIER_REQUIRED` | 400 Bad Request |
| `ERR_TEMPERATURE_LOG_NOT_APPLICABLE` | 400 Bad Request |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_INVALID_LOT_EXPIRY` | 400 Bad Request |
| `ERR_AUTHORIZATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DELIVERY_FREQUENCY_EXCEEDED` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_NOT_SHORT_DATED` | 400 Bad Request |
| `ERR_LOT_LINE_MISMATCH` | 400 Bad Request |
| `ERR_ORDER_BELOW_MINIMUM` | 400 Bad Request |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_RECEIVED_QTY_EXCEEDS_CLAIMED` | 400 Bad Request |
| `ERR_STALE_CLINIC_VERSION` | 412 Precondition Failed |
