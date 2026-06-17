# Upholstery Refinishing API — Product Requirements Document

## 1. Introduction

An upholstery and furniture refinishing shop runs a workflow that begins at the front counter and ends, months later, with a warranty conversation. A piece of furniture arrives, is photographed and assessed, has its fabric and foam selected, is quoted, approved, scheduled, produced, and finally delivered or picked up — and any of those steps can loop back on itself when a customer wants a different fabric or a cheaper estimate. This API governs that entire lifecycle as a connected set of resources rather than a pile of paper tickets, so that the price a customer approves, the materials the shop commits to, the labor capacity it consumes, and the money that changes hands all stay reconciled with one another at every step.

The system is built around a central **work order** that ties together the customer, the pieces being worked on, the estimate that was approved, the materials procured, the production days booked, the logistics legs that move the furniture, and any warranty claim filed afterward. Two financial views coexist: a **forward-looking estimate**, computed from catalog prices when a quote is authored, and a **chronological final invoice**, recomputed at production finish from the prices actually paid for materials. Because the two can diverge — fabric and foam are ordered at one price and received at another — the shop must be able to reason about both, and the API keeps each current. Four distinct staff and customer roles share the workflow, each owning a slice of it, and the system enforces who may do what, in which order, and against which version of the truth.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as `IntakeClerk`, `Estimator`, `ShopManager`, and `Customer`. When an authenticated principal attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Three of these roles are operator roles whose identities are opaque. When `X-User-Role` is `IntakeClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The same holds when `X-User-Role` is `Estimator`, and likewise when `X-User-Role` is `ShopManager`: each is an opaque staff identifier with no entity backing.

The `Customer` role is different. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any work order compare that order's `customer_id` to `X-User-ID`. Concretely, the customer-acting operations — approving an estimate, declining an estimate, requesting a revision, and filing a warranty claim — all require that `X-User-ID` equal the `customer_id` of the targeted work order. A customer acting on a work order they do not own is rejected with `ERR_NOT_OWNER`, and this ownership check applies to exactly those four operations.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip before collecting the page; it defaults to 0 and may not be negative. A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_INVALID_PAGINATION`.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp, `created_at`, in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching records and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource the system mints carries a server-generated `id` formatted as a UUID with no type prefix, along with a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources also carry an `updated_at` timestamp, refreshed on every mutation, and a `version` integer that begins at its initial value and increments by one with each mutation. These four common properties appear on customers, fabric SKUs, foam specs, work orders, line items, estimates, material orders, shop days, fulfillment legs, warranty claims, and payments.

One resource is deliberately leaner. A `ConditionPhoto` is immutable once created: it carries only `id` and `created_at`, and it has neither an `updated_at` field nor a `version` field. Any narrative below that speaks of "bumping the version" or "refreshing `updated_at`" therefore never applies to condition photos.

### 2.5. Optimistic Concurrency on the Work Order

Three work-order operations mutate the order in ways that must not silently clobber a concurrent writer's change, so they are guarded by optimistic concurrency control keyed on the work order's `version`. Authoring an estimate version, approving an order, and cancelling an order each require the caller to submit `expected_work_order_version` in the request body, carrying the `version` of the work order the client last observed. If that value does not equal the work order's current `version` at the moment the server processes the request, the operation is rejected with `ERR_STALE_WORK_ORDER_VERSION` and HTTP status 412, and no state changes.

The estimate-authoring case deserves a word on why. A new estimate legitimately supersedes the prior active estimate; if another writer has already authored a superseding version — which bumps the work order's `version` — then the current caller's view of which estimate it is replacing is out of date, and the write is rejected rather than allowed to fork the revision chain. Endpoints that are not in this set of three do not accept `expected_work_order_version` and perform no version check.

### 2.6. Monetary Precision and Day Rounding

All money in the system is stored and returned as integer cents — there are no fractional-cent values and no string-encoded amounts. Wherever a calculation multiplies a quantity by a per-unit price, each individual cost term is rounded to the nearest whole cent using the round-half-up convention *before* terms are summed; the system rounds per term and then adds, never the reverse. This per-term rounding applies to labor cost, fabric cost, and foam cost alike.

Turnaround and warranty windows are measured in whole days. Where a day count is derived from labor hours or from an elapsed-time fraction, the rounding direction is stated explicitly at the point of use (rounding up to the next whole day for turnaround bands, rounding down to a whole number of elapsed days for warranty coverage). No monetary or day value is ever expressed approximately; the exact term, threshold, and rounding direction govern.

### 2.7. Cascading Consistency and Derived-Field Reconciliation

Several fields on a work order are derived rather than directly written, and the system keeps them reconciled whenever an underlying fact changes. The `materials_committed_cents` field is the sum of `provisional_cost_cents` across the order's material orders that are in either `ORDERED` or `RECEIVED` status; it is recomputed whenever a material order is placed, received, or cancelled. The `amount_paid_cents` field is the running sum of recorded deposit and settlement payments. The `balance_due_cents` field is reconciled on every event that touches money — estimate authoring, approval, material receipt, production finish, settlement, and cancellation — using the basis rule defined in §3. When an operation mutates a parent or child resource as a side effect, that resource's own `updated_at` is refreshed and, where it carries one, its `version` increments; a `ShopDay`'s automatic flip between `OPEN` and `FULL`, for instance, is a genuine mutation of that shop day.

Compensating cancellation is the most far-reaching cascade and must conserve two invariants. When a work order is cancelled, every fabric yard that was reserved from stock is returned to its `FabricSku.in_stock_yards` (the yard-conservation invariant), and every cent the customer paid is refunded in full (the refund invariant) — to the original method, or, when the refund is directed to the wallet, credited to the customer's `store_credit_cents`. The §3 cancellation narrative enumerates the complete chain.

### 2.8. Nested and Filtered Resource Retrieval

When an endpoint path names a parent resource followed by a collection — for example, a work order followed by its line items, estimates, payments, or warranty claims — the system validates the path left to right. The parent work order's existence is checked first, and if it does not exist the request fails with `ERR_WORK_ORDER_NOT_FOUND` before any child is considered. For collection endpoints addressed by a single id that is not a work order — an estimate, a material order, a fulfillment leg, a warranty claim, a shop day, a customer, a fabric SKU, or a foam spec — a missing target yields `ERR_RESOURCE_NOT_FOUND`. List endpoints that accept a foreign-key filter (such as filtering line items by `work_order_id`, `fabric_sku_id`, or `foam_spec_id`, material orders or fulfillment legs by their references, or estimates by `supersedes_estimate_id`) simply return the matching subset and never error on an absent filter match.

### 2.9. Request Well-Formedness

Across all creating and transitioning endpoints, a request whose required body fields are missing, ill-typed, or carry an invalid enum value is rejected with `ERR_INVALID_REQUEST`. This is the catch-all for malformed input and is evaluated after authentication, authorization, and existence but is distinct from the domain-specific business validations described throughout §3.

## 3. Business Logic & Workflows

### 3.1. Intake: Opening an Order, Photographing the Piece, and the Catalog

The lifecycle begins when an `IntakeClerk` opens a work order against an existing customer. A customer is registered first — by an `IntakeClerk` or a `ShopManager` — with a `full_name`, an `email` that must be unique among active customers, and a `phone`; their `store_credit_cents` is initialized to 0 and may never go negative. Opening the order supplies the `customer_id` of the owning customer, the `service_type`, and an optional `rush_requested` flag that defaults to false. The `service_type` is one of `REUPHOLSTERY`, `REFINISH`, or `REPAIR`, and it governs which line-item fields are required and which pricing branch applies later. A newly opened order sits in `INTAKE` status with its estimate, invoice, and balance counters all at 0, no committed materials, and no promised turnaround yet. If the `customer_id` names no existing customer, the create is rejected with `ERR_FK_NOT_FOUND`.

Before estimating can begin, the piece must be documented. An `IntakeClerk` attaches one or more condition photos, each carrying the `work_order_id` it documents, an `image_uri` pointing at the stored image, and an optional `damage_note` for free-text observations such as tears, stains, or frame damage (defaulting to an empty string). Each photo receives a server-assigned `sequence_no`, a 1-based intake ordinal computed by ordering the order's photos by `created_at` ascending. A photo whose `work_order_id` names no existing order is rejected with `ERR_FK_NOT_FOUND`.

The shop maintains two catalogs that drive pricing, both managed by a `ShopManager`. A `FabricSku` is created with a `sku_code` that is unique among listed SKUs, a display `name`, a `price_cents_per_yard` that may not be negative, a `roll_width_inches` that must be greater than zero, and an optional opening `in_stock_yards` (defaulting to 0). A fabric SKU begins `LISTED` and can later be marked `DISCONTINUED`; only a `LISTED` fabric may be selected on a new line item. A `FoamSpec` is created with a `grade_code` unique among listed specs, a `density_lb` that must be greater than zero and which drives the high-density threshold, and a `price_cents_per_board_foot` that may not be negative. A foam spec likewise begins `LISTED` and may be moved to `DISCONTINUED`, and only a `LISTED` spec may be selected on a reupholstery line item.

### 3.2. Pieces and Per-Piece Pricing

A work order describes one or more pieces, each captured as a line item by an `IntakeClerk`. The line item carries the `work_order_id` it belongs to, a human `piece_label` such as "Sofa - 3 cushion", and the labor and material inputs that price it. Adding the very first line item to an order is what advances it from `INTAKE` to `ESTIMATING`, and that advance requires three conditions to hold: the order is still in `INTAKE`, at least one condition photo already exists for the order, and the line item satisfies the service-type field rules below. Subsequent line items added while the order is `ESTIMATING` do not change its status; they only cause the affected per-piece subtotals to be recomputed.

The service-type field rules are strict. When the order's `service_type` is `REUPHOLSTERY`, the line item must name a `fabric_sku_id` and must carry a `yardage_required` greater than zero. When the order's `service_type` is `REFINISH` or `REPAIR`, the line item must leave `fabric_sku_id` unset and must carry a `yardage_required` of exactly 0. A line item that violates these field rules is rejected with `ERR_LINE_ITEM_FIELDS_INVALID`. A foam selection is captured through an optional `foam_spec_id`, which is only meaningful for reupholstery, together with `board_feet_required` (defaulting to 0); `board_feet_required` may be greater than zero only when a `foam_spec_id` is present. Every line item also records `labor_hours`, which must be greater than zero. Independently of the field rules, any selected `fabric_sku_id` or `foam_spec_id` must reference a catalog item that is currently `LISTED`, and a positive `board_feet_required` without a foam spec is itself invalid; a violation of these catalog-availability constraints is rejected with `ERR_CATALOG_ITEM_UNAVAILABLE`. A `fabric_sku_id` or `foam_spec_id` that references no catalog record at all is an `ERR_FK_NOT_FOUND`.

When a line item is created — and again whenever an estimate version is authored — its `piece_subtotal_cents` is computed. The labor component is the piece's `labor_hours` multiplied by the shop labor rate of 6500 cents per hour, rounded to whole cents. The fabric component applies only when the order is `REUPHOLSTERY`: it is the `yardage_required` multiplied by the selected `FabricSku.price_cents_per_yard`, rounded to whole cents; for `REFINISH` and `REPAIR` orders the fabric component is 0. The foam component applies only when a `foam_spec_id` is set: it is the `board_feet_required` multiplied by the selected `FoamSpec.price_cents_per_board_foot`, rounded to whole cents; with no foam spec it is 0. Each of these three components is rounded individually before they are added, and the `piece_subtotal_cents` is their sum.

### 3.3. Authoring Estimates and the Revision Loop

Once an order is `ESTIMATING`, an `Estimator` authors an estimate. Authoring requires that the order be in either `ESTIMATING` or `REVISION_REQUESTED` status and that at least one line item exist; otherwise the transition is rejected with `ERR_INVALID_STATE`. The author submits `expected_work_order_version` (subject to the stale-version rule of §2.5) and, on a revision, a `supersedes_estimate_id` naming the estimate being replaced. On the first estimate `supersedes_estimate_id` is null; on any later version it must name the order's current `ACTIVE` estimate. Authoring creates a new `Estimate` carrying the `work_order_id`, a server-assigned `version_no` equal to the prior maximum plus one, and a `status` of `ACTIVE`; any previously `ACTIVE` estimate on the order is moved to `SUPERSEDED`, so at most one estimate per order is ever `ACTIVE` or `APPROVED` at a time. The order's `active_estimate_id` is repointed to the new estimate, its `estimate_total_cents` is set to the new estimate's `total_cents`, its `balance_due_cents` is reconciled, the work order's `version` increments by one, and the order moves to `AWAITING_APPROVAL`.

The estimate's own totals are computed forward-looking from catalog prices, never from received actuals. Its `labor_total_cents` is the sum, over all line items, of each piece's `labor_hours` times 6500 cents per hour, each product rounded to whole cents. Its `materials_total_cents` is the sum, over all line items, of the fabric and foam components defined in §3.2 (fabric only for reupholstery, foam only where a foam spec is present), each component rounded before summation. The base of the estimate is `labor_total_cents` plus `materials_total_cents`.

The `rush_surcharge_cents` is added only when the order's `rush_requested` flag is set; otherwise it is 0. When rush applies, the surcharge is tiered on the `labor_total_cents`. If `labor_total_cents` is at most 50000 cents, the surcharge is 15 percent of `labor_total_cents`, rounded to whole cents. If `labor_total_cents` exceeds 50000 cents, the surcharge is the sum of two rounded terms: 15 percent of the first 50000 cents, plus 30 percent of the portion of `labor_total_cents` above 50000 cents — each of the two terms rounded to whole cents before they are added. The estimate's `total_cents` is the base plus `rush_surcharge_cents`, and it is mirrored onto the work order's `estimate_total_cents`.

When the customer who owns the order wants changes, they request a revision. Requesting a revision is permitted only while the order is `AWAITING_APPROVAL` and only by the owning customer; it moves the order to `REVISION_REQUESTED` while leaving the current estimate `ACTIVE` until a new version supersedes it. From `REVISION_REQUESTED`, the estimator authors a fresh version exactly as above, returning the order to `AWAITING_APPROVAL` — and this `AWAITING_APPROVAL → REVISION_REQUESTED → AWAITING_APPROVAL` loop may repeat any number of times. A revision or approval attempt made when the order is not in a permitted status is rejected with `ERR_INVALID_STATE`.

### 3.4. Approval, the Deposit Gate, and Committed Turnaround

Approval is a customer action available only while the order is `AWAITING_APPROVAL` and only to the owning customer; otherwise it is rejected with `ERR_INVALID_STATE` or, for a non-owner, `ERR_NOT_OWNER`. The caller submits `expected_work_order_version`, which must match the order's current `version` or the request fails with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), and a `deposit_amount_cents`. The deposit gate requires that `deposit_amount_cents` be at least the required deposit, which is 30 percent of the order's `estimate_total_cents` rounded *up* to the next whole cent. A deposit below that floor is rejected with `ERR_DEPOSIT_TOO_LOW`.

When approval succeeds, several things happen together. The active estimate moves to `APPROVED`. The order's committed turnaround is computed and written to `promised_turnaround_days`. A `DEPOSIT` payment is recorded for the submitted `deposit_amount_cents`, the order's `amount_paid_cents` increases by that amount, and `balance_due_cents` is reconciled. The order moves to `APPROVED`, and its `version` increments by one.

The committed turnaround is a day count. First sum the `labor_hours` across all line items. The standard band is 3 base days plus the total labor hours divided by 8 hours per day and rounded up to the next whole day. If the order is not a rush, `promised_turnaround_days` is that standard band. If the order is a rush, the standard band is compressed: take the standard band, multiply by one half, round up to the next whole day, and then take the larger of that compressed figure and the rush floor of 2 days — so a rush order is never promised fewer than 2 days.

If instead the customer declines, declining is likewise restricted to the owning customer while the order is `AWAITING_APPROVAL`. Declining moves the active estimate to `DECLINED` and the order to `DECLINED`, a terminal state.

### 3.5. Procuring Materials and Reconciling Cost

After an order is approved, a `ShopManager` places material orders against it. A material order carries the `work_order_id` it serves and either a `fabric_sku_id` (with `yards_ordered`, defaulting to 0) for fabric, a `foam_spec_id` (with `board_feet_ordered`, defaulting to 0) for foam, or both; a fabric-only order leaves `foam_spec_id` null and a foam-only order leaves `fabric_sku_id` null. Neither `yards_ordered` nor `board_feet_ordered` may be negative. A selected catalog item that is `DISCONTINUED` is rejected with `ERR_CATALOG_ITEM_UNAVAILABLE`, and a reference to a non-existent catalog item or work order is `ERR_FK_NOT_FOUND`.

At order time the material order's `provisional_cost_cents` is computed forward-looking from catalog prices: the `yards_ordered` times the fabric SKU's `price_cents_per_yard` rounded to whole cents, plus the `board_feet_ordered` times the foam spec's `price_cents_per_board_foot` rounded to whole cents, the two rounded terms then summed. The order opens in `ORDERED` status. When yards are reserved from on-hand stock, the fabric SKU's `in_stock_yards` is debited by the reserved amount, and the parent work order's `materials_committed_cents` increases by this order's `provisional_cost_cents`.

Receiving a material order records what was actually paid. A `ShopManager` receives an `ORDERED` order whose parent work order is in either `APPROVED` or `IN_PRODUCTION` status; otherwise the receive is rejected with `ERR_INVALID_STATE`. The receive call supplies the actual unit prices: `received_fabric_price_cents_per_yard` and `received_foam_price_cents_per_board_foot`. The order's `finalized_cost_cents` is then computed as the `yards_ordered` times `received_fabric_price_cents_per_yard` rounded to whole cents, plus the `board_feet_ordered` times `received_foam_price_cents_per_board_foot` rounded to whole cents, the two terms summed. The order moves to `RECEIVED`, and because it remains a committed material, the parent's `materials_committed_cents` is recomputed and stays committed. The gap between the provisional and the finalized cost is exactly what later makes the final invoice diverge from the estimate.

A `ShopManager` may also cancel an `ORDERED` material order outright. Cancelling returns any fabric yards that were reserved against on-hand stock to the fabric SKU's `in_stock_yards`, decrements the parent work order's `materials_committed_cents` by this order's `provisional_cost_cents`, and moves the order to `CANCELLED`. The same material-cancel compensation is what runs, for every still-`ORDERED` material order, when a whole work order is cancelled.

### 3.6. Scheduling Production and Moving the Piece

Production is scheduled by booking a fulfillment leg. A `ShopManager` first opens a `ShopDay` with a `work_date` in `YYYY-MM-DD` form and a `labor_capacity_hours` greater than zero; at most one non-cancelled shop day may exist per `work_date`, and a duplicate is rejected with `ERR_DUPLICATE_SHOP_DAY`. A shop day opens `OPEN` with `booked_hours` at 0 and may later be `FULL` or `CLOSED`. Closing a shop day is permitted from `OPEN` or `FULL` and moves it to `CLOSED`, after which no further production may book onto it.

A `FulfillmentLeg` carries the `work_order_id` it serves and a `kind` of `PRODUCTION`, `PICKUP`, or `DELIVERY`. A `PRODUCTION` leg names the `shop_day_id` it books and leaves the window fields null; a `PICKUP` or `DELIVERY` leg leaves `shop_day_id` null and instead carries a `scheduled_window_start` and `scheduled_window_end`, where the end must be strictly after the start or the leg is rejected with `ERR_INVALID_WINDOW`. Booking the first `PRODUCTION` leg onto a shop day is what advances the order from `APPROVED` to `IN_PRODUCTION`, and it has preconditions: the order must be `APPROVED`, every material order for the order must already be in `RECEIVED` or `CANCELLED` with none still `ORDERED`, and the target shop day must be `OPEN` with enough remaining capacity. An attempt to start production while a material order is still `ORDERED` is rejected with `ERR_MATERIALS_OUTSTANDING`.

A production booking consumes day capacity equal to the order's total labor — the sum of `labor_hours` across the order's line items. The shop day is treated as an aggregate capacity pool: a `PRODUCTION` leg may not book if the cumulative booked labor hours across all of the day's non-cancelled production legs would exceed `labor_capacity_hours`, and it may not book onto a day that is `FULL` or `CLOSED`; any of these is rejected with `ERR_CAPACITY_EXCEEDED`. On a successful booking, the day's `booked_hours` increases by the order's labor sum, and if `booked_hours` then reaches or exceeds `labor_capacity_hours` the day flips to `FULL` (the boundary where booked exactly equals capacity is `FULL`). When a `PRODUCTION` leg is later cancelled, the day's `booked_hours` is decremented by exactly the labor it had added, and if the day had been `FULL` and now sits below capacity it reverts to `OPEN`.

`PICKUP` and `DELIVERY` legs move the finished piece. Delivery is constrained by a single delivery crew: a new `DELIVERY` leg's window may not overlap the window of any existing non-cancelled `DELIVERY` leg. Overlap is judged on half-open intervals — two delivery windows conflict when the existing window's start is before the new window's end and the new window's start is before the existing window's end; windows that merely touch at an endpoint, where one window's start equals the other's end, do not conflict. A conflicting delivery window is rejected with `ERR_DELIVERY_WINDOW_CONFLICT`.

Any leg progresses through its own small lifecycle. A `PLANNED` leg is dispatched to `DISPATCHED` by a `ShopManager` — and for a `PICKUP` or `DELIVERY` leg, dispatch still requires that `scheduled_window_start` and `scheduled_window_end` be present with the end after the start. A `DISPATCHED` leg is completed to `COMPLETED`. A `PLANNED` leg may instead be cancelled to `CANCELLED`, which for a production leg releases its booked capacity as described above. Acting on a leg that is not in the required state yields `ERR_INVALID_STATE`.

### 3.7. Finishing Production, Settling, and Completing

When the piece is built and its production leg has reached `COMPLETED`, a `ShopManager` finishes production. This is permitted only while the order is `IN_PRODUCTION`, and only once the order's `PRODUCTION` fulfillment leg is itself `COMPLETED`; finishing while the production leg is not complete is rejected with `ERR_PRODUCTION_NOT_COMPLETE`. Finishing production computes the chronological final invoice and moves the order to `READY_FOR_FULFILLMENT`.

The final invoice is computed from actuals rather than projections. Its labor component is the same as the estimate's: the sum, over all line items, of `labor_hours` times 6500 cents per hour, each product rounded to whole cents. Its materials component, however, is the chronological sum of finalized actual costs: walk the order's `RECEIVED` material orders in `created_at` ascending order and accumulate their `finalized_cost_cents`, excluding any `CANCELLED` material order entirely. The rush component carried into the invoice is the `rush_surcharge_cents` of the approved estimate. The order's `final_invoice_cents` is the labor component plus the chronological materials actuals plus that carried rush surcharge. Because received prices can differ from the catalog prices used in the estimate, this figure diverges from `estimate_total_cents` precisely by the accumulated provisional-versus-finalized deltas. Once the invoice is set, `balance_due_cents` is reconciled against it.

The balance basis follows a single rule used everywhere money is reconciled. While the order has no final invoice yet (its `final_invoice_cents` is still 0), `balance_due_cents` equals `estimate_total_cents` minus `amount_paid_cents`. Once `final_invoice_cents` is positive, the basis switches and `balance_due_cents` equals `final_invoice_cents` minus `amount_paid_cents`.

Completion is the last step before warranty. After a `PICKUP` or `DELIVERY` leg for the order has reached `COMPLETED`, a `ShopManager` completes the order while it is `READY_FOR_FULFILLMENT`. The call supplies `settlement_amount_cents`, which must exactly equal the order's `balance_due_cents` as it stands before this call — neither under- nor overpayment is allowed, and a mismatch is rejected with `ERR_SETTLEMENT_MISMATCH`. On success, a `SETTLEMENT` payment is recorded for `settlement_amount_cents`, `amount_paid_cents` increases by it, `balance_due_cents` is reconciled to 0, the order's `completed_at` is stamped with the current server time (which anchors the warranty window), and the order moves to `COMPLETED`. Completion additionally requires that the resulting `balance_due_cents` be at most 0 after this settlement; in normal flow the exact-match settlement guarantees it lands at exactly 0.

### 3.8. Cancellation and the Compensation Chain

A `ShopManager` may cancel a work order that is in either `APPROVED` or `IN_PRODUCTION` status. Cancellation submits `expected_work_order_version`, which must match the order's current `version` or the request fails with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), and an optional `refund_destination` (one of `ORIGINAL` or `WALLET`, defaulting to `ORIGINAL`). Cancelling an order in any other status is rejected with `ERR_INVALID_STATE`.

Cancellation runs a compensation chain that must leave the world consistent. Every material order still in `ORDERED` status moves to `CANCELLED`, and its reserved fabric yards are returned to the corresponding `FabricSku.in_stock_yards`; the order's `materials_committed_cents` is reconciled to 0. Every `PLANNED` `PRODUCTION` fulfillment leg moves to `CANCELLED`, the booked `ShopDay.booked_hours` is decremented by what that leg had added, and any shop day that was `FULL` reverts to `OPEN`. A `REFUND` payment is recorded for the full `amount_paid_cents` directed to the chosen `refund_destination`; when the destination is `WALLET`, the customer's `store_credit_cents` increases by that amount. The order's `amount_paid_cents` is reconciled to 0, its `balance_due_cents` is reconciled, the order moves to `CANCELLED`, and its `version` increments by one. Throughout, fabric yards and customer money are conserved exactly — every reserved yard returns and every paid cent is refunded.

A customer's payments are append-only: the system never voids a payment. Each `Payment` carries the `work_order_id`, a `kind` of `DEPOSIT`, `SETTLEMENT`, or `REFUND`, an `amount_cents` greater than zero, an optional `refund_destination` that is only meaningful for a refund, and a `status` that is always `RECORDED`. A reversal is therefore always modeled as a new `REFUND` payment rather than by mutating an existing one.

### 3.9. Warranty Claims and Coverage

A completed order carries a 90-day warranty, and the warranty window is made deterministic by a server clock. A `ShopManager` may set the server's current UTC clock by supplying a `to_iso8601` instant; subsequent completions stamp `completed_at` from that clock, so tests can place a completion at a known moment.

Only the owning customer may file a warranty claim, and only against a `COMPLETED` order; filing against any other status is rejected with `ERR_ORDER_NOT_COMPLETED`. The claim carries the `work_order_id`, a `defect_note` describing the reported problem, and a `filed_at` instant supplied on the call so coverage is deterministic. At filing, the claim's `covered` flag is computed: take the whole number of elapsed days between the order's `completed_at` and `filed_at`, computed by taking the difference in seconds, dividing by 86400 seconds per day, and rounding down to a whole number of days. The claim is `covered` when the parent order is `COMPLETED` and that elapsed-day count is at most 90 days — a claim filed at exactly 90 days is still covered, while a claim filed on day 91 is not. A new claim opens in `OPEN` status.

A `ShopManager` adjudicates claims. An `OPEN` claim may be approved only when its `covered` flag is true, moving it to `APPROVED`; an attempt to approve a claim whose `covered` flag is false is rejected with `ERR_INVALID_STATE`, so an out-of-window claim can only ever be denied. An `OPEN` claim may instead be denied, moving it to `DENIED`, regardless of coverage. An `APPROVED` claim may finally be resolved, moving it to `RESOLVED`. Acting on a claim that is not in the required state yields `ERR_INVALID_STATE`.

### 3.10. Validation Ordering

When several checks could apply to one request, the system evaluates them in a fixed order so that the reported error is deterministic. Authentication comes first: a missing `X-User-ID` or `X-User-Role` header yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`, and for the four customer-acting operations a non-owning customer yields `ERR_NOT_OWNER`. Existence is then checked left to right along the path — a missing work order in the path yields `ERR_WORK_ORDER_NOT_FOUND`, a missing single-id resource yields `ERR_RESOURCE_NOT_FOUND`, and a missing foreign-key body reference yields `ERR_FK_NOT_FOUND`. Only after those pass does the system evaluate state validity (`ERR_INVALID_STATE`), then the optimistic-concurrency version check (`ERR_STALE_WORK_ORDER_VERSION`), then the cross-entity state guards (`ERR_MATERIALS_OUTSTANDING`, `ERR_PRODUCTION_NOT_COMPLETE`), then the domain business constraints (`ERR_LINE_ITEM_FIELDS_INVALID`, `ERR_CATALOG_ITEM_UNAVAILABLE`, `ERR_INVALID_WINDOW`, `ERR_DUPLICATE_SHOP_DAY`, `ERR_CAPACITY_EXCEEDED`, `ERR_DELIVERY_WINDOW_CONFLICT`, `ERR_DEPOSIT_TOO_LOW`, `ERR_SETTLEMENT_MISMATCH`, `ERR_ORDER_NOT_COMPLETED`), and finally pagination bounds (`ERR_INVALID_PAGINATION`) and request well-formedness (`ERR_INVALID_REQUEST`).

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition actions that drive a work order, material order, fulfillment leg, shop day, or warranty claim through its lifecycle — return `200 OK`. Request and response bodies are not restated here; reconstruct them from the §3 narratives that describe each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | IntakeClerk, ShopManager |
| GET | `/customers/{id}` | Fetch a customer | IntakeClerk, ShopManager, Estimator, Customer |
| GET | `/customers/{id}/work-orders` | List a customer's work orders | IntakeClerk, ShopManager, Estimator, Customer |
| POST | `/fabric-skus` | Create a fabric SKU | ShopManager |
| GET | `/fabric-skus/{id}` | Fetch a fabric SKU | ShopManager, Estimator, IntakeClerk |
| POST | `/fabric-skus/{id}/discontinue` | Mark a fabric SKU discontinued | ShopManager |
| POST | `/foam-specs` | Create a foam spec | ShopManager |
| GET | `/foam-specs/{id}` | Fetch a foam spec | ShopManager, Estimator, IntakeClerk |
| POST | `/foam-specs/{id}/discontinue` | Mark a foam spec discontinued | ShopManager |
| POST | `/work-orders` | Open a work order at intake | IntakeClerk |
| GET | `/work-orders/{id}` | Fetch a work order | IntakeClerk, ShopManager, Estimator, Customer |
| GET | `/work-orders` | List work orders with filters | IntakeClerk, ShopManager, Estimator |
| POST | `/condition-photos` | Attach a condition photo to a work order | IntakeClerk |
| GET | `/condition-photos/{id}` | Fetch a single condition photo | IntakeClerk, ShopManager, Estimator, Customer |
| GET | `/condition-photos` | List condition photos, filterable by work order | IntakeClerk, ShopManager, Estimator, Customer |
| POST | `/work-orders/{id}/line-items` | Add a piece line item | IntakeClerk |
| GET | `/work-orders/{id}/line-items` | List a work order's line items | IntakeClerk, ShopManager, Estimator, Customer |
| GET | `/line-items/{id}` | Fetch a single line item | IntakeClerk, ShopManager, Estimator, Customer |
| GET | `/line-items` | List line items, filterable by catalog item | IntakeClerk, ShopManager, Estimator |
| POST | `/work-orders/{id}/estimates` | Author an estimate version | Estimator |
| GET | `/estimates/{id}` | Fetch an estimate version | Estimator, ShopManager, Customer, IntakeClerk |
| GET | `/work-orders/{id}/estimates` | List a work order's estimate versions | Estimator, ShopManager, Customer, IntakeClerk |
| GET | `/estimates` | List estimates, filterable by supersedes link | Estimator, ShopManager |
| POST | `/work-orders/{id}/request-revision` | Customer requests a revised estimate | Customer |
| POST | `/work-orders/{id}/approve` | Customer approves the active estimate, pays deposit | Customer |
| POST | `/work-orders/{id}/decline` | Customer declines the active estimate | Customer |
| POST | `/material-orders` | Place a material order against an approved order | ShopManager |
| GET | `/material-orders/{id}` | Fetch a material order | ShopManager, Estimator |
| GET | `/material-orders` | List material orders with filters | ShopManager, Estimator |
| POST | `/material-orders/{id}/receive` | Receive a material order and finalize cost | ShopManager |
| POST | `/material-orders/{id}/cancel` | Cancel an ordered material order | ShopManager |
| POST | `/shop-days` | Open a production day with labor capacity | ShopManager |
| GET | `/shop-days/{id}` | Fetch a shop day | ShopManager, Estimator |
| GET | `/shop-days` | List shop days | ShopManager, Estimator |
| POST | `/shop-days/{id}/close` | Close a shop day | ShopManager |
| POST | `/fulfillment-legs` | Create a production, pickup, or delivery leg | ShopManager |
| GET | `/fulfillment-legs/{id}` | Fetch a fulfillment leg | ShopManager, Estimator, Customer |
| GET | `/fulfillment-legs` | List fulfillment legs with filters | ShopManager, Estimator, Customer |
| POST | `/fulfillment-legs/{id}/dispatch` | Dispatch a planned leg | ShopManager |
| POST | `/fulfillment-legs/{id}/complete` | Complete a dispatched leg | ShopManager |
| POST | `/fulfillment-legs/{id}/cancel` | Cancel a planned leg | ShopManager |
| POST | `/work-orders/{id}/finish-production` | Mark production finished; compute final invoice | ShopManager |
| POST | `/work-orders/{id}/complete` | Settle balance and complete the order | ShopManager |
| POST | `/work-orders/{id}/cancel` | Cancel an approved or in-production order | ShopManager |
| GET | `/work-orders/{id}/payments` | List a work order's payments | ShopManager, Estimator, Customer |
| POST | `/_clock/set_current_utc` | Set the server clock for completion stamping | ShopManager |
| POST | `/work-orders/{id}/warranty-claims` | File a warranty claim on a completed order | Customer |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | Customer, ShopManager |
| GET | `/work-orders/{id}/warranty-claims` | List a work order's warranty claims | Customer, ShopManager, Estimator |
| POST | `/warranty-claims/{id}/approve` | Approve a covered warranty claim | ShopManager |
| POST | `/warranty-claims/{id}/deny` | Deny a warranty claim | ShopManager |
| POST | `/warranty-claims/{id}/resolve` | Resolve an approved warranty claim | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_MATERIALS_OUTSTANDING` | 409 Conflict |
| `ERR_PRODUCTION_NOT_COMPLETE` | 409 Conflict |
| `ERR_LINE_ITEM_FIELDS_INVALID` | 422 Unprocessable Entity |
| `ERR_CATALOG_ITEM_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SHOP_DAY` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DEPOSIT_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
