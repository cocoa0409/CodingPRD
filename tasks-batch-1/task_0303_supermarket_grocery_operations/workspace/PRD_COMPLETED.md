# Supermarket Grocery Operations API — Product Requirements Document

## 1. Introduction

This document specifies the back-office operations platform for a full-line supermarket. A grocery store is, at its core, a perpetual ledger of perishable value: cases arrive from direct-store-delivery vendors, are received into dated batches, sit on shelves until they are sold, marked down, written off as shrink, or counted away, and every one of those events moves money on the books. The platform's job is to keep that ledger honest in real time — to know, at any instant, how much sellable inventory is on hand, what it cost, what it is priced at this week, and what was lost to expiration or theft.

The system serves six operator perspectives. Receiving clerks bring in vendor shipments and convert them into dated inventory lots. Price managers run the weekly ad, scheduling effective-price windows, promotions, and digital coupons. Cashiers ring up point-of-sale transactions, applying the right price for each scanned or weighed item and accruing loyalty rewards. Inventory auditors run cycle counts, quarantine and pull suspect stock, and close out the day department by department. A store manager sits above all of them with override authority for fiscal exceptions, refunds, and the member lifecycle. Finally, loyalty members themselves act on their own accounts, clipping the coupons they intend to redeem.

Two design commitments run through everything that follows. First, all money is held as integer cents and all weights as integer milli-units (thousandths of a pound), so that no rounding error can leak into the ledger; every derived monetary figure has a pinned rounding rule. Second, perishability drives the inventory model: stock is depleted First-Expired-First-Out (FEFO), value is reconciled the instant any lot changes, and shrink is measured against opening book value so a department that bleeds margin gets flagged at close.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the actor: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not name one of the roles defined below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are six roles, spelled exactly as follows: `StoreManager`, `ReceivingClerk`, `PriceManager`, `Cashier`, `InventoryAuditor`, and `LoyaltyMember`.

The `StoreManager` is the superset operator: it may perform every operation any other operator can, and additionally owns a narrow set of override and lifecycle actions — creating departments, discontinuing products, suspending, reactivating, and closing members, refunding paid sales, overriding a receiving variance, and advancing the test clock. The `ReceivingClerk` owns direct-store-delivery receiving. The `PriceManager` owns weekly-ad pricing, promotions, and coupon definitions. The `Cashier` operates the point of sale and clips coupons on a shopper's behalf. The `InventoryAuditor` owns cycle counts, end-of-day reconciliation, and lot quarantine, release, pull, and expire.

For five of these roles — `StoreManager`, `ReceivingClerk`, `PriceManager`, `Cashier`, and `InventoryAuditor` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server accepts it as the acting operator's handle but does not compare it to any entity's `id`. The `LoyaltyMember` role is different: it is entity-backed by the `LoyaltyMember` entity, meaning that when `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the `id` of the acting member. Ownership checks on any resource that references a member compare that resource's member foreign key to `X-User-ID`. A `LoyaltyMember` may clip a coupon only onto its own account and may read only its own member record, its own clipped coupons, and individual clip records it owns; an attempt to act on another member's resources is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; a request asking for more than 100 is clamped to the maximum permitted value, and a request below the minimum is rejected as a malformed request. The `offset` parameter defaults to 0 and counts items skipped from the start of the result set. Lists are returned sorted by `created_at` in ascending order — oldest first — unless a specific narrative below states otherwise. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Versioning, and Timestamps

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Resources carry a `created_at` timestamp, set once at creation, and — for every entity in this system — an `updated_at` timestamp and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits. The `version` begins at 1 and increments by exactly one on every mutation that changes the resource, and `updated_at` is refreshed to the moment of that mutation. Throughout this system every entity carries the full set of common properties — `id`, `created_at`, `updated_at`, and `version` — because even configuration records and junction records participate in mutation or recompute flows.

### 2.5. Monetary and Weight Representation, Precision, and Rounding

All amounts of money are integer cents; the API never emits or accepts fractional cents. All weights are integer milli-units, where 1000 milli-units equals one pound, so a weighed item priced "per pound" is priced per 1000 milli-units. Quantities of each-sold items are plain integer counts. Wherever a computation produces a non-integer intermediate — chiefly when a per-pound price or per-pound cost is multiplied by a milli-unit weight and divided by 1000, or when a percentage discount is taken — the result is rounded half up to a whole cent. The phrase "rounded half up" means the fractional part of exactly one-half rounds away from zero to the next whole cent. Two ordering rules about rounding matter and are stated where they apply: per-line monetary figures are each rounded before lines are summed (never summed first and rounded once), and weighted cost is rounded per contributing lot before lot costs are summed.

### 2.6. Denormalized Inventory Reconciliation

Several fields on a `Product` are read-only mirrors of the underlying inventory lots and are never written directly by a client: `on_hand_qty`, `on_hand_value_cents`, and `reorder_flagged`. These are reconciled atomically inside the very request that changes any lot's remaining quantity — receiving, sale depletion, a pull, an expiry, a cycle-count adjustment, or a refund restock. Reconciliation is a strict cascade. First, the product's on-hand quantity and on-hand book value are recomputed from its surviving lots; this is the inventory rollup. That rollup immediately triggers a recomputation of the reorder flag against the product's reorder point. Whenever this recompute is triggered by an operation that also affects the product through receiving or a price-plan create, the product's `version` advances and its `updated_at` is refreshed as part of the same atomic request. Likewise, member loyalty fields — `points_balance`, `lifetime_spend_cents`, and `tier` — are derived mirrors reconciled atomically when a sale that names a member is finalized or refunded.

### 2.7. Optimistic Concurrency on Product Pricing and Receiving

Two write operations carry an optimistic-concurrency guard keyed to a product's `version`, because both legitimately advance that version and must not be allowed to act on a product the caller has not freshly observed.

The first is completing the receipt of a shipment. That request must include `expected_product_version`, a non-optional field carrying the `version` the clerk last observed for the product on the shipment's line. By convention the guard is evaluated against the product referenced by the shipment's first line — the line with the earliest `created_at`. If `expected_product_version` does not equal that product's current `version`, the receive is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412) before any lot is created or any value is bumped. The rejection means another writer has advanced the product's version since the clerk last read it; completing the receive would create a lot and recompute the product's denormalized fields against a stale view.

The second is scheduling a weekly-ad price. Creating a price plan must include `expected_product_version` carrying the `version` the price manager last observed for the target product. If it does not equal the product's current `version`, the create is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412) before the plan is persisted; a new ad price supersedes the product's effective pricing and the create itself advances `version`, so a create still carrying the prior version observed a stale product whose everyday price or status may have changed. In both cases the stale-version check is evaluated before the success path's version bump. No other endpoint accepts a version field.

### 2.8. The Logical Clock and Time-Windowed Pricing

Pricing windows, coupon validity, and lot expiry are all evaluated against a single server-held logical clock rather than wall-clock time, so that time-dependent behavior is deterministic and test-drivable. An administrative capability advances that clock to a supplied absolute instant. Effective windows throughout the system are half-open: a window covers the clock when its inclusive start is at or before the clock and its exclusive end is strictly after the clock. Price plans, promotions, and coupons all require their effective end to be strictly after their effective start; a window whose end is not strictly after its start is rejected with `ERR_INVALID_WINDOW` (HTTP 422).

### 2.9. Nested and Filtered Retrieval

Several collections are reachable both as top-level lists and through a parent's sub-path — a product's price plans and promotions, a member's clipped coupons, a coupon's clips. When a resource is addressed through a path that names a parent and then a child, the path is validated left to right: the parent id is resolved first, and if it does not exist the corresponding not-found error is returned before the child is considered. The same left-to-right rule governs any path with multiple ids and any foreign-key reference in a request body — every referenced id must resolve to an existing record of the right type, or the matching not-found error is returned (for example `ERR_PRODUCT_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_SHIPMENT_LINE_NOT_FOUND`, `ERR_PRICE_PLAN_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`, `ERR_CLIPPED_COUPON_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_CYCLE_COUNT_NOT_FOUND`, `ERR_EOD_NOT_FOUND`), each at HTTP 404.

### 2.10. Validation Order

When a single request could fail several checks, they are evaluated in a fixed priority order so that the returned error is predictable. The order is: (1) user-context headers present and the role recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the acting role authorized for the operation — and for an entity-backed `LoyaltyMember`, ownership matching `X-User-ID` to the resource's member foreign key — else `ERR_UNAUTHORIZED`; (3) existence of every path id and body foreign key, validated left to right, else the matching not-found error; (4) request-body well-formedness — required fields present, types correct, enums in range, integer constraints honored, and conditional-required fields supplied — else `ERR_INVALID_REQUEST`; (5) uniqueness and referential constraints, else `ERR_DUPLICATE_RESOURCE`; (6) the target resource being in a state that permits the requested transition, else the transition's specific state error; (7) window validity, else `ERR_INVALID_WINDOW`; (8) line unit-type safety, else `ERR_LINE_UNIT_MISMATCH`; (9) lot expiry being actually due, else `ERR_LOT_NOT_EXPIRED_YET`; (10) coupon redeemability, else `ERR_COUPON_NOT_REDEEMABLE`; (11) FEFO stock sufficiency, else `ERR_INSUFFICIENT_STOCK`; (12) the receiving fiscal variance gate, else `ERR_RECEIVE_VARIANCE_EXCEEDED`; and (13) the optimistic-concurrency check, else `ERR_STALE_PRODUCT_VERSION`. A check earlier in this order always masks one later: an unauthorized caller never learns whether the resource exists, and a malformed body is rejected before any state or stock reasoning. The optimistic-concurrency check sits last among substantive checks and immediately precedes the success path's version bump.

## 3. Business Logic & Workflows

### 3.1. Departments and the Product Catalog

Operations begin with departments and the catalog of items that hang off them. A `StoreManager` creates a department by supplying a `code`, a human-readable `name`, and optionally a `shrink_alert_bps` threshold. The `code` is a short uppercase identifier — letters A through Z and underscores only — such as PRODUCE, DAIRY, or GROCERY, and it must be unique across all departments; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. The `shrink_alert_bps` value is a shrink threshold expressed in basis points, where 200 basis points means two percent, and it defaults to 200 when omitted; it must be between 0 and 10000 inclusive. It is the line above which a department's loss rate is flagged when the day is closed.

A product is a SKU or PLU catalog item created by a `StoreManager` or `PriceManager` against an owning department named by `department_id`. Each product has a display `name`, a base everyday `unit_price_cents`, and several behavioral flags. The `sell_by_weight` flag — defaulting to false — distinguishes the two fundamental kinds of merchandise. An each-sold item (the flag is false) carries a scannable `sku` and is priced per each; the `sku` is required when `sell_by_weight` is false, must be unique across products where present, and is null for weighed items. A weighed item (the flag is true) carries a `plu` scale code and is priced per pound, that is per 1000 milli-units; the `plu` is required when `sell_by_weight` is true, must be unique across products where present, and is null for each-sold items. For each-sold products `unit_price_cents` is the per-each price; for weighed products it is the per-pound price. The `unit_price_cents` must be at least 0. The `is_perishable` flag — defaulting to false — marks products whose lots carry expiration dates and participate in FEFO depletion and shrink. The `reorder_point_qty` — defaulting to 0 and required to be at least 0 — is the on-hand quantity at or below which the product is flagged for reorder, expressed as an each count for each-sold products and as whole milli-units for weighed products.

When a product is created its computed inventory mirrors start at zero — `on_hand_qty` is 0 and `on_hand_value_cents` is 0 — its `reorder_flagged` is computed immediately, and its lifecycle `status` is `ACTIVE`. Because the reorder flag is set whenever on-hand quantity is at or below the reorder point, a brand-new product with zero on hand and any non-negative reorder point begins flagged. A product's `status` follows a simple lifecycle from `ACTIVE` to `DISCONTINUED`. Only a `StoreManager` may discontinue a product; doing so leaves existing lots untouched and changes no inventory, but it advances the product's `version` by one. Discontinuing a product that is already discontinued, or attempting to receive a shipment line that targets a discontinued product, is rejected with `ERR_PRODUCT_DISCONTINUED`. Products may be listed and filtered by `department_id`, by `status`, and by `reorder_flagged`.

### 3.2. Direct-Store-Delivery Receiving

Receiving turns a vendor delivery into priced, dated inventory. A `ReceivingClerk` (or `StoreManager`) opens a shipment header with a `vendor_name`, a `reference_code`, and an `expected_total_cents` — the vendor-stated invoice total used later to gate the receipt. The `reference_code` must be unique across shipments and the `expected_total_cents` must be at least 0; a duplicate reference is rejected with `ERR_DUPLICATE_RESOURCE`. A fresh shipment is in `PENDING`. The clerk then adds lines while the shipment is still pending, each line naming the delivered `product_id`, an `ordered_qty` (which must be greater than 0), a per-unit `unit_cost_cents` (at least 0), and, for a perishable product, the lot `expiration_date`; the line may also carry an `accepted_qty`. The `accepted_qty` defaults to the `ordered_qty` when the line is accepted without a count override and must be at least 0. A line is created in `OPEN`. Shipment lines may be retrieved individually and listed by `shipment_id`, by `product_id`, and by `status`.

Receiving proceeds through a small state machine. The clerk begins receiving, advancing the shipment from `PENDING` to `RECEIVING`; this requires the shipment to be in `PENDING`, else `ERR_SHIPMENT_NOT_PENDING`, and requires at least one line in `OPEN`, else `ERR_SHIPMENT_EMPTY`. From `RECEIVING` the shipment branches to either `RECEIVED` or `REJECTED`. Completing the receipt requires the shipment to be in `RECEIVING`, else `ERR_SHIPMENT_NOT_RECEIVING`, and requires that every referenced product be `ACTIVE`, else `ERR_PRODUCT_DISCONTINUED`.

Before a receipt is allowed to land, the fiscal variance gate is applied. The shipment's `received_total_cents` is the sum over its lines of accepted quantity multiplied by unit cost — and for a weighed product the accepted milli-unit quantity multiplied by the per-pound cost is divided by 1000 — while `variance_cents` is the signed difference of received total minus expected total. The gate compares the absolute difference between received and expected totals, scaled by 10000 and divided by the expected total with the quotient floored to a whole number of basis points, against a tolerance of 500 basis points (five percent): if that scaled relative variance exceeds 500 basis points the receipt is rejected with `ERR_RECEIVE_VARIANCE_EXCEEDED`, unless a `StoreManager` sets `override_variance` to true on the receive. When `expected_total_cents` is 0, any nonzero received total exceeds the tolerance and the gate blocks the receipt absent an override. The receive request also carries the optimistic-concurrency field `expected_product_version` described in §2.7.

On a successful receipt the shipment moves to `RECEIVED` and the inventory cascade fires. For each line whose `accepted_qty` is greater than 0, one `InventoryLot` is created in `ACTIVE` with its `shipment_id` set to this shipment, its `received_qty` equal to the line's accepted quantity, and its `unit_cost_cents` and `expiration_date` copied from the line; the line is set to `ACCEPTED` when its accepted quantity equals its ordered quantity, otherwise to `SHORT`. Each created lot triggers the inventory rollup on its product, recomputing `on_hand_qty` and `on_hand_value_cents`, and that rollup in turn recomputes the reorder flag — a lot that lifts on-hand above the reorder point clears `reorder_flagged`. The receipt advances both the product's `version` and the shipment's `version` by one. Rejecting a receipt instead moves the shipment from `RECEIVING` to `REJECTED`, requires the shipment to be in `RECEIVING` (else `ERR_SHIPMENT_NOT_RECEIVING`), leaves all lines `OPEN`, creates no lots and changes no inventory, and advances the shipment's `version` by one.

### 3.3. Lot Lifecycle, Quarantine, Pull, and Expiry

An inventory lot is a dated batch of one product. Beyond the receiving-created fields, each lot exposes a `remaining_qty` — its received quantity minus what has been depleted by sales and minus what has been pulled, never falling below 0 — and a lifecycle `status` that starts `ACTIVE`. A lot's product is named by `product_id`; lots may be listed and filtered by `product_id`, by `shipment_id`, and by `status`.

An `InventoryAuditor` (or `StoreManager`) governs the lot's manual transitions. Quarantining moves a lot from `ACTIVE` to `QUARANTINED` and requires it to be `ACTIVE`, else `ERR_LOT_NOT_ACTIVE`. A quarantined lot still counts toward the product's `on_hand_qty` and its book value is unchanged — quarantine writes off nothing — but it is skipped by FEFO sale depletion while quarantined. Releasing moves a lot from `QUARANTINED` back to `ACTIVE`, requires it to be `QUARANTINED`, else `ERR_LOT_NOT_QUARANTINED`, and restores its FEFO eligibility. This active-quarantined cycle is intentionally reversible.

Pulling writes a lot off as shrink. A pull is permitted from either `ACTIVE` or `QUARANTINED`, else `ERR_LOT_NOT_PULLABLE`; it drives the lot to `PULLED`, writes its `remaining_qty` down to 0, and records the pulled value — the remaining quantity multiplied by the lot's per-each cost, or for a weighed lot the remaining milli-units multiplied by the per-pound `unit_cost_cents` and divided by 1000, rounded half up — as shrink. The pull then triggers the product inventory rollup and the cascading reorder-flag recompute; dropping on-hand to or below the reorder point sets `reorder_flagged`. Expiry behaves the same way fiscally but is gated on time. A lot may be expired from either `ACTIVE` or `QUARANTINED`, else `ERR_LOT_NOT_EXPIRABLE`, and only when its `expiration_date` is non-null and at or before the current clock; an attempt to expire a lot whose expiration date is still in the future relative to the clock is rejected with `ERR_LOT_NOT_EXPIRED_YET`. A successful expiry drives the lot to `EXPIRED`, writes `remaining_qty` to 0, records the expired value as shrink, and runs the identical rollup-then-reorder cascade as a pull. A lot also reaches `DEPLETED` by the system itself, when FEFO depletion during a sale finalize reduces its `remaining_qty` to 0; a depleted lot no longer contributes to on-hand quantity or value. The terminal lot states `DEPLETED`, `EXPIRED`, and `PULLED` are all excluded from the on-hand rollup.

### 3.4. The Inventory Rollup and the Reorder Threshold

The denormalized product figures are computed from the lots by one rule, applied any time a lot's remaining quantity changes. The product's `on_hand_qty` is the sum of `remaining_qty` over the lots that are in `ACTIVE` or `QUARANTINED` status. Its `on_hand_value_cents` sums, over those same `ACTIVE` and `QUARANTINED` lots, each lot's contribution: for a weighed product, the lot's remaining milli-units multiplied by its `unit_cost_cents` and divided by 1000 with the result rounded half up before being added; for an each-sold product, the lot's remaining quantity multiplied by its `unit_cost_cents` directly. Lots in `DEPLETED`, `EXPIRED`, or `PULLED` are excluded entirely. The weighed contribution is rounded per lot and then summed, never summed and rounded once.

Immediately after the rollup, the reorder flag is recomputed: `reorder_flagged` is true exactly when `on_hand_qty` is less than or equal to `reorder_point_qty`. The boundary is inclusive — an on-hand quantity exactly equal to the reorder point flags the product, while an on-hand quantity one unit above the reorder point does not.

### 3.5. Weekly-Ad Pricing and Promotions

A `PriceManager` (or `StoreManager`) drives the weekly ad. A price plan schedules an ad price for one product named by `product_id`, with an `ad_price_cents` (at least 0) and an inclusive `effective_start` and exclusive `effective_end`; the end must be strictly after the start, else `ERR_INVALID_WINDOW`, and the create carries the optimistic-concurrency `expected_product_version` of §2.7, advancing the product's `version` on success. A price plan begins `SCHEDULED`. By the logical clock it becomes `ACTIVE` once the clock reaches its `effective_start` and is still before its `effective_end`, and `EXPIRED` once the clock reaches its `effective_end`; these two are time-evaluated rather than explicitly invoked. A `PriceManager` may cancel a plan that is in `SCHEDULED` or `ACTIVE`, driving it to `CANCELLED`; a cancel attempt on a plan in any other state is rejected with `ERR_PRICE_PLAN_NOT_CANCELLABLE`. A product's price plans may be listed through its sub-collection and filtered by `status`.

A promotion targets one product named by `product_id` and has a `promo_type` of `PERCENT_OFF`, `BOGO`, or `FIXED_OFF`. A percentage promotion carries `percent_off_bps`, a discount in basis points where 1000 means ten percent, between 0 and 10000 inclusive when present and null otherwise. A fixed promotion carries `fixed_off_cents`, the per-eligible-unit cents off, at least 0 when present and null otherwise. Every promotion carries a `min_qty` — the minimum eligible quantity for the promo to apply, defaulting to 1, at least 1, and meaningful only for each-sold items — and a `stackable` flag, defaulting to false, governing whether the promotion may stack on top of an active weekly-ad price. A promotion has the same inclusive `effective_start` and exclusive `effective_end` rule as a price plan, the same `ERR_INVALID_WINDOW` guard, and the same `SCHEDULED → ACTIVE → EXPIRED` time-driven lifecycle. A `PriceManager` may cancel a promotion in `SCHEDULED` or `ACTIVE`, driving it to `CANCELLED`; otherwise the cancel is rejected with `ERR_PROMOTION_NOT_CANCELLABLE`. A product's promotions may be listed through its sub-collection and filtered by `status`.

### 3.6. Loyalty Members and Digital Coupons

A loyalty member is created by a `StoreManager` or `Cashier` with an `email` (unique across members, rejected on collision with `ERR_DUPLICATE_RESOURCE`) and a `full_name`. A member's reward state is read-only: `points_balance` starts at 0 and never falls below 0, `lifetime_spend_cents` starts at 0, and `tier` starts `BASIC`. The lifecycle `status` starts `ACTIVE`. Only a `StoreManager` governs the member lifecycle. Suspending requires the member to be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`, and moves it to `SUSPENDED`; reactivating requires `SUSPENDED`, else `ERR_MEMBER_NOT_SUSPENDED`, and returns it to `ACTIVE` — a reversible cycle. Closing is permitted from either `ACTIVE` or `SUSPENDED`, else `ERR_MEMBER_NOT_CLOSEABLE`, and drives the member to `CLOSED`; as a cascade, every one of that member's clipped coupons that is still in `CLIPPED` is moved to `EXPIRED` and can no longer be redeemed.

A digital coupon is a discount definition created by a `PriceManager` or `StoreManager`. It carries a `code` (unique across coupons, else `ERR_DUPLICATE_RESOURCE`), a target `product_id`, a `discount_cents` flat amount off applied once per qualifying transaction (which must be greater than 0), a `min_spend_cents` minimum transaction subtotal required for redemption (defaulting to 0, at least 0), a `stackable` flag (defaulting to false) governing whether the coupon may stack on an active promotion for the same product, and an inclusive `effective_start` with exclusive `effective_end` — the end strictly after the start, else `ERR_INVALID_WINDOW`. Coupons may be listed and filtered by `product_id`, and a coupon's clips may be listed through its sub-collection.

A shopper clips a coupon to make it redeemable. A `LoyaltyMember` (on its own account only), a `Cashier`, or a `StoreManager` clips a coupon, naming the `coupon_id`; the resulting clip is owned by the member named in the path and begins in `CLIPPED`. A member may not clip the same coupon twice while a prior clip for that coupon is still `CLIPPED`; a duplicate live clip is rejected with `ERR_DUPLICATE_RESOURCE`. A clip records the `member_id` who clipped, the `coupon_id` clipped, and a `redeemed_in_sale_id` backref that is null until the clip is redeemed and is then set to the sale that redeemed it — discoverable when reading the clip rather than as a queryable relationship. A clip moves to `REDEEMED` by the system when a sale that names it is finalized, and reverts from `REDEEMED` back to `CLIPPED` by the system when that sale is refunded. A clip moves to `EXPIRED` by the system when its owning member is closed. A member's clips may be listed through its sub-collection and filtered by `status`, and individual clips may be read directly.

### 3.7. The Point of Sale: Opening, Pricing, and Finalizing a Sale

A sale is opened by a `Cashier` or `StoreManager`, optionally naming a loyalty `member_id` (null for an anonymous sale). It carries two independent state dimensions: a tender dimension `tender_status` that begins `UNPAID`, and a fulfillment dimension `fulfillment_status` that begins `OPEN`. These axes advance independently. The sale also exposes read-only computed totals — `subtotal_cents`, `coupon_discount_cents`, `total_cents`, `cogs_cents`, and `points_earned` — all zero until finalize. Sales may be listed and filtered by `member_id`, by `clipped_coupon_id`, by `tender_status`, and by `fulfillment_status`.

While the sale is `OPEN`, a cashier adds line items, each naming a scanned `product_id` and exactly one of two measures: a `quantity` (an each count, required and greater than 0 for an each-sold product) or a `weight_milli` (a weight in milli-units, required and greater than 0 for a weighed product). The line's unit type must match the product: providing a `quantity` for a weighed product, or a `weight_milli` for an each-sold product, is rejected with `ERR_LINE_UNIT_MISMATCH`. Each line additionally exposes three read-only computed fields filled at finalize: `unit_price_applied_cents`, `extended_price_cents`, and `promo_id_applied`. Line items may be retrieved individually and listed by `sale_id` and by `product_id`. Adding a line, or finalizing or voiding the sale, requires the sale's `fulfillment_status` to be `OPEN`, else `ERR_SALE_NOT_OPEN`.

Finalizing advances `fulfillment_status` from `OPEN` to `FINALIZED` and is the heart of the system. It is permitted only when the sale is `OPEN` (else `ERR_SALE_NOT_OPEN`) and has at least one line item (else `ERR_SALE_EMPTY`); if a `member_id` is set, that member must be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`. Pricing each line is a two-step computation evaluated before any inventory is touched. First, the effective unit price is selected: the candidate price plans for the line's product are those whose half-open window covers the clock — that is, whose `effective_start` is at or before the clock and whose `effective_end` is strictly after it (both `SCHEDULED` and `ACTIVE` plans qualify since selection is purely window-based, while `CANCELLED` and `EXPIRED` are excluded). If there is at least one candidate, `unit_price_applied_cents` is the lowest `ad_price_cents` among them, breaking ties by the later `effective_start` first and then by the earlier `created_at`; if there is none, it falls back to the product's everyday `unit_price_cents`. For a weighed product this applied price is per pound.

Second, the line's extended price is computed. The gross is, for a weighed product, the applied per-pound price multiplied by `weight_milli` and divided by 1000 with the result rounded half up at this point, and for an each-sold product the applied price multiplied by `quantity`. At most one promotion is then applied to the line: the eligible promotions are those for the line's product whose half-open window covers the clock, that for an each-sold item meet the `min_qty` threshold (the line `quantity` is at least the promotion's minimum), and that are either stackable or apply when no ad price plan was selected for this line. Among eligible promotions the one yielding the largest computed discount wins, breaking ties by later `effective_start` then earlier `created_at`. If no promotion is eligible, `extended_price_cents` equals the gross and `promo_id_applied` is null. For a `PERCENT_OFF` promotion the discount is the gross multiplied by `percent_off_bps` divided by 10000, rounded half up, and the extended price is the gross minus that discount. For a `FIXED_OFF` promotion (each-sold only) the discount is the smaller of the gross and the product of `fixed_off_cents` and `quantity`, and the extended price is the gross minus that discount. For a `BOGO` promotion (each-sold only, buy-one-get-one-free) the number of free units is the whole-number half of `quantity` (the floor of quantity divided by two), the discount is those free units multiplied by `unit_price_applied_cents`, and the extended price is the gross minus that discount. In every case the extended price is floored at 0, never negative, and `promo_id_applied` records the chosen promotion. When a promotion stacks on an applied ad price, the discount is computed off the already-reduced ad price because the gross used the ad price; when no ad price covered the line, the discount is computed off the everyday price.

The transaction total is then assembled in a strictly pinned order: subtotal first, then the coupon gate against the subtotal, then the total. The `subtotal_cents` is the sum of the already-rounded `extended_price_cents` across all lines — lines are rounded individually and then summed, never summed and then rounded. If no `clipped_coupon_id` is set on the finalize, `coupon_discount_cents` is 0. Otherwise the coupon behind the clip is examined: the clip must belong to the sale's member and be `CLIPPED`, the coupon's half-open window must cover the clock, the `subtotal_cents` must be at least the coupon's `min_spend_cents`, and the stacking rule must hold — either the coupon is stackable or no line on this sale applied a promotion to the coupon's product. The minimum-spend gate is tested against the pre-coupon subtotal, not the total. When all of these hold, `coupon_discount_cents` is the smaller of the coupon's `discount_cents` and the subtotal; if any condition fails, the finalize is rejected with `ERR_COUPON_NOT_REDEEMABLE`. The `total_cents` is the subtotal minus the coupon discount, floored at 0.

### 3.8. FEFO Depletion, Cost of Goods, and Stock Sufficiency

Finalizing a sale depletes physical stock First-Expired-First-Out. For each line the eligible lots are the product's lots that are in `ACTIVE` status and either carry no expiration date or carry one strictly after the clock; quarantined lots and expired lots are not eligible even though quarantined lots still count toward `on_hand_qty`. This is why a finalize can be rejected for insufficient stock even when the product's on-hand quantity appears sufficient. Eligible lots are consumed in order of soonest expiration first (lots with no expiration date sort last), then by earliest `created_at`. Each line's demand — the `quantity` for an each-sold product or the `weight_milli` for a weighed product — is checked against the total eligible on-hand before any mutation; if the demand across the product's eligible lots cannot be met, the finalize is rejected with `ERR_INSUFFICIENT_STOCK`.

When stock is sufficient, depletion proceeds lot by lot in that FEFO order, taking from each lot the smaller of its remaining quantity and the outstanding demand, reducing the lot's `remaining_qty`, and accumulating the cost of goods. For a weighed product the cost taken from a lot is the units taken multiplied by the lot's `unit_cost_cents` divided by 1000, rounded half up per lot before being added; for an each-sold product it is the units taken multiplied by the lot's `unit_cost_cents`. The accumulated figure becomes the sale's `cogs_cents`. A lot whose remaining quantity reaches 0 transitions to `DEPLETED`. After depletion, each affected product gets its inventory rollup and the cascading reorder-flag recompute, so a product whose on-hand drops to or below its reorder point becomes `reorder_flagged`. Note that this book-value rollup and the FEFO cost-of-goods accumulation are deliberately distinct: the rollup values every on-hand lot (`ACTIVE` and `QUARANTINED` alike) while cost of goods values only the lots actually depleted, drawn only from `ACTIVE`, non-expired lots.

### 3.9. Loyalty Accrual, Tendering, Voiding, and Refund Compensation

When a finalized sale names a member, loyalty rewards accrue. The base points are one point per whole dollar of `total_cents` — the floor of the total in cents divided by 100. The member's tier as it stands at the start of finalize, before this sale's spend is added, sets a multiplier: `BASIC` earns the base unchanged, `SILVER` earns one and a half times the base, and `GOLD` earns twice the base, with the result floored to whole points. The resulting `points_earned` is added to the member's `points_balance`, the `total_cents` is added to the member's `lifetime_spend_cents`, and the tier is then recomputed. Tier is a function of lifetime spend: a member reaches `GOLD` at a lifetime spend of at least 200000 cents (two thousand dollars) and `SILVER` at a lifetime spend of at least 50000 cents (five hundred dollars), otherwise `BASIC`; the breakpoints are inclusive, so exactly 50000 cents reaches `SILVER`. If the finalize also names a `clipped_coupon_id`, that clip moves to `REDEEMED` and its `redeemed_in_sale_id` is set to this sale.

The tender axis advances separately. Paying a sale moves `tender_status` from `UNPAID` to `PAID`; it requires the tender status to be `UNPAID`, else `ERR_SALE_NOT_UNPAID`, and gates on the fulfillment axis being `FINALIZED`, else `ERR_SALE_NOT_FINALIZED` — paying touches only the tender axis and changes no inventory. Voiding a sale is a fulfillment-axis action available only while the sale is still `OPEN` (else `ERR_SALE_NOT_OPEN`); it moves `fulfillment_status` to `VOIDED` and has no inventory or ledger effect because nothing was depleted while the sale was open.

Refunding is a `StoreManager`-only compensation on the tender axis. It requires the tender status to be `PAID`, else `ERR_SALE_NOT_PAID`, and moves `tender_status` to `REFUNDED`. The refund reverses the finalize exactly. For each line the depleted units are restocked in reverse FEFO order, recreating `remaining_qty` on the very same lots up to each lot's `received_qty`, and any lot that had been driven to `DEPLETED` is restored to `ACTIVE` as needed. Each restocked product then gets its inventory rollup and the cascading reorder-flag recompute, clearing the flag if on-hand rises back above the reorder point. If a `clipped_coupon_id` was on the sale, its clip reverts from `REDEEMED` to `CLIPPED` and the `redeemed_in_sale_id` backref is cleared. If a member was on the sale, loyalty is reversed: `points_earned` is subtracted from `points_balance` (floored at 0), `total_cents` is subtracted from `lifetime_spend_cents`, and the tier is recomputed. The compensation invariant is exact: after a pay followed by a refund, the product's `on_hand_qty` and `on_hand_value_cents` return to their pre-finalize values, and the member's `points_balance` and `lifetime_spend_cents` return to their pre-finalize values.

### 3.10. Cycle Counts and the Daily Close

Inventory auditors keep the book honest through cycle counts and the end-of-day close. A cycle count reconciles a single product within a department; an `InventoryAuditor` or `StoreManager` opens one naming the `department_id` and the `product_id`, and it begins in `DRAFT` with `counted_qty` 0, `book_qty_snapshot` and `variance_qty` null, and `shrink_value_cents` 0 until it is submitted and reconciled. Submitting it records the operator-entered `counted_qty` (which must be provided and at least 0, else `ERR_INVALID_REQUEST`) and moves it from `DRAFT` to `SUBMITTED`, requiring `DRAFT` else `ERR_CYCLE_COUNT_NOT_DRAFT`. At submit, `book_qty_snapshot` captures the product's `on_hand_qty` at that moment and `variance_qty` is computed as the counted quantity minus that book snapshot, a signed figure. Cycle counts may be listed and filtered by `department_id`, by `product_id`, and by `status`.

Reconciling moves a submitted count from `SUBMITTED` to `RECONCILED`, requiring `SUBMITTED` else `ERR_CYCLE_COUNT_NOT_SUBMITTED`, and applies the variance. When the count is short — `variance_qty` is below 0 — the absolute shortfall is depleted from the product's FEFO-eligible lots (the same `ACTIVE`, non-expired lots as ordinary sale depletion) in FEFO order, taking the smaller of the shortfall and the available eligible quantity when stock falls short, the `shrink_value_cents` is set to the book value of those depleted units (the same per-lot weighed rounding as ordinary depletion), and any lot reaching 0 becomes `DEPLETED`. When the count is over — `variance_qty` is above 0 — one adjustment lot is created in `ACTIVE` with a null `shipment_id` and a `received_qty` equal to the variance, valued at the product's most recent active lot's `unit_cost_cents` (or the product's `unit_price_cents` if it has no lot), and `shrink_value_cents` is 0. Either way the product inventory rollup and the cascading reorder-flag recompute follow. A cycle count may be cancelled from either `DRAFT` or `SUBMITTED`, else `ERR_CYCLE_COUNT_NOT_CANCELLABLE`, moving it to `CANCELLED` with no inventory adjustment.

The end-of-day reconciliation closes one department for a business date. An `InventoryAuditor` or `StoreManager` opens one naming the `department_id` and the `business_date`; at open the `opening_value_cents` snapshots the department's on-hand book value and the reconciliation begins `OPEN`, with its close-computed figures — `sales_total_cents`, `cogs_total_cents`, `shrink_total_cents`, `closing_value_cents`, and `shrink_bps` — all 0 and `shrink_alert` false until close. Closing moves it from `OPEN` to `CLOSED`, requiring `OPEN` else `ERR_EOD_NOT_OPEN`, and is blocked while the department still has any cycle count in `SUBMITTED` (unreconciled) state, in which case it is rejected with `ERR_EOD_OPEN_CYCLE_COUNTS`. At close the rollup runs over the half-open window from the reconciliation's `created_at` up to but not including the current wall-clock instant at the moment of close. This window is evaluated on the wall-clock basis on which `created_at` and `updated_at` are stamped (the moment of each actual mutation, per §2.4), not against the logical pricing/expiry clock of §2.8: the window end is wall-clock "now" at close, and an event's membership is tested against its own wall-clock timestamp. The department's products are those whose `department_id` matches. The `sales_total_cents` sums `total_cents`, and `cogs_total_cents` sums `cogs_cents`, over the sales that are `FINALIZED`, whose `created_at` falls in the window, and that carry at least one line on a department product. The `shrink_total_cents` sums, over the window, the `shrink_value_cents` of the department's cycle counts reconciled in the window — membership keyed to the cycle count's `updated_at` (the moment of the reconcile) — plus the write-off value of the department's lots that became `PULLED` or `EXPIRED` in the window, each lot's membership keyed to its `updated_at` (the moment of the pull or expire). The `closing_value_cents` snapshots the department's current on-hand book value. Finally the shrink alert is computed: when `opening_value_cents` is 0 the `shrink_bps` is 0, otherwise it is the shrink total multiplied by 10000 and divided by the opening value, floored to a whole number of basis points; `shrink_alert` is true exactly when `shrink_bps` is greater than or equal to the department's `shrink_alert_bps`, the boundary being inclusive so an equal value alerts.

### 3.11. The Test-Driving Clock

Because windows and expiry are evaluated against the logical clock, an administrative test-driving capability lets a `StoreManager` advance the server's current UTC clock to a supplied absolute instant carried as `to_iso8601`. The response reports the new current UTC instant in a `current_utc` field (an ISO 8601 UTC string with three fractional digits). After the clock advances, price-plan, promotion, and coupon window evaluation and lot expiry all reckon against the new value — a price plan whose window now covers the clock is selectable, and a lot whose expiration date is now at or before the clock becomes expirable.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; retrievals and state-changing actions on existing resources return HTTP 200. Request bodies, computed responses, and side effects are described in the §3 narratives, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /departments | Create a department | StoreManager |
| GET | /departments | List departments | StoreManager, PriceManager, ReceivingClerk, InventoryAuditor, Cashier |
| GET | /departments/{id} | Get a department | StoreManager, PriceManager, ReceivingClerk, InventoryAuditor, Cashier |
| POST | /products | Create a SKU/PLU product in a department | StoreManager, PriceManager |
| GET | /products | List products; filter by department_id, status, reorder_flagged | StoreManager, PriceManager, ReceivingClerk, InventoryAuditor, Cashier |
| GET | /products/{id} | Get a product with computed inventory fields | StoreManager, PriceManager, ReceivingClerk, InventoryAuditor, Cashier |
| POST | /products/{id}/discontinue | Discontinue a product | StoreManager |
| GET | /products/{id}/price-plans | List a product's price plans | StoreManager, PriceManager, Cashier |
| GET | /products/{id}/promotions | List a product's promotions | StoreManager, PriceManager, Cashier |
| POST | /shipments | Create a DSD shipment header | ReceivingClerk, StoreManager |
| GET | /shipments | List shipments; filter by status | ReceivingClerk, StoreManager, InventoryAuditor |
| GET | /shipments/{id} | Get a shipment with computed totals/variance | ReceivingClerk, StoreManager, InventoryAuditor |
| POST | /shipments/{id}/lines | Add a line to a PENDING shipment | ReceivingClerk, StoreManager |
| GET | /shipment-lines/{id} | Get a shipment line | ReceivingClerk, StoreManager, InventoryAuditor |
| GET | /shipment-lines | List shipment lines; filter by shipment_id, product_id, status | ReceivingClerk, StoreManager, InventoryAuditor |
| POST | /shipments/{id}/start-receiving | Begin receiving (PENDING to RECEIVING) | ReceivingClerk |
| POST | /shipments/{id}/receive | Complete receiving: create lots, recompute inventory, gate variance and OCC | ReceivingClerk, StoreManager |
| POST | /shipments/{id}/reject | Reject receiving (RECEIVING to REJECTED) | ReceivingClerk, StoreManager |
| GET | /inventory-lots | List inventory lots; filter by product_id, shipment_id, status | StoreManager, ReceivingClerk, InventoryAuditor, Cashier |
| GET | /inventory-lots/{id} | Get a lot | StoreManager, ReceivingClerk, InventoryAuditor, Cashier |
| POST | /inventory-lots/{id}/quarantine | Quarantine an ACTIVE lot | InventoryAuditor, StoreManager |
| POST | /inventory-lots/{id}/release | Release a QUARANTINED lot back to ACTIVE | InventoryAuditor, StoreManager |
| POST | /inventory-lots/{id}/pull | Pull (write off) a lot as shrink | InventoryAuditor, StoreManager |
| POST | /inventory-lots/{id}/expire | Expire a lot whose expiration_date is at or before the clock | InventoryAuditor, StoreManager |
| POST | /price-plans | Schedule a weekly-ad price for a product (OCC on Product.version) | PriceManager, StoreManager |
| GET | /price-plans/{id} | Get a price plan | PriceManager, StoreManager, Cashier |
| POST | /price-plans/{id}/cancel | Cancel a price plan | PriceManager, StoreManager |
| POST | /promotions | Schedule a promotion for a product | PriceManager, StoreManager |
| GET | /promotions/{id} | Get a promotion | PriceManager, StoreManager, Cashier |
| POST | /promotions/{id}/cancel | Cancel a promotion | PriceManager, StoreManager |
| POST | /members | Create a loyalty member | StoreManager, Cashier |
| GET | /members/{id} | Get a member with computed loyalty fields | StoreManager, Cashier, LoyaltyMember |
| POST | /members/{id}/suspend | Suspend a member | StoreManager |
| POST | /members/{id}/reactivate | Reactivate a suspended member | StoreManager |
| POST | /members/{id}/close | Close a member; expire its clipped coupons | StoreManager |
| POST | /members/{id}/clip | Member clips a digital coupon | LoyaltyMember, Cashier, StoreManager |
| GET | /members/{id}/clipped-coupons | List a member's clipped coupons | LoyaltyMember, Cashier, StoreManager |
| GET | /clipped-coupons/{id} | Get a clipped coupon | LoyaltyMember, Cashier, StoreManager |
| POST | /coupons | Create a digital coupon definition | PriceManager, StoreManager |
| GET | /coupons | List digital coupons; filter by product_id | PriceManager, StoreManager, Cashier |
| GET | /coupons/{id} | Get a coupon | PriceManager, StoreManager, Cashier |
| GET | /coupons/{id}/clipped-coupons | List clips of a coupon | PriceManager, StoreManager, Cashier |
| POST | /sales | Open a POS sale | Cashier, StoreManager |
| GET | /sales | List sales; filter by member_id, clipped_coupon_id, tender_status, fulfillment_status | Cashier, StoreManager, InventoryAuditor |
| GET | /sales/{id} | Get a sale with computed totals/cogs/points | Cashier, StoreManager, InventoryAuditor |
| POST | /sales/{id}/line-items | Add a line item to an OPEN sale | Cashier, StoreManager |
| GET | /sale-line-items/{id} | Get a sale line item | Cashier, StoreManager, InventoryAuditor |
| GET | /sale-line-items | List sale line items; filter by sale_id, product_id | Cashier, StoreManager, InventoryAuditor |
| POST | /sales/{id}/finalize | Finalize a sale: price lines, apply coupon, deplete FEFO, accrue loyalty | Cashier, StoreManager |
| POST | /sales/{id}/void | Void an OPEN sale | Cashier, StoreManager |
| POST | /sales/{id}/pay | Tender a FINALIZED sale (UNPAID to PAID) | Cashier, StoreManager |
| POST | /sales/{id}/refund | Refund a PAID sale: restock lots, reverse loyalty and coupon | StoreManager |
| POST | /cycle-counts | Open a cycle count for a department and product | InventoryAuditor, StoreManager |
| GET | /cycle-counts/{id} | Get a cycle count | InventoryAuditor, StoreManager |
| GET | /cycle-counts | List cycle counts; filter by department_id, product_id, status | InventoryAuditor, StoreManager |
| POST | /cycle-counts/{id}/submit | Submit the physical count (DRAFT to SUBMITTED) | InventoryAuditor, StoreManager |
| POST | /cycle-counts/{id}/reconcile | Reconcile variance (SUBMITTED to RECONCILED): adjust lots, write off shrink | InventoryAuditor, StoreManager |
| POST | /cycle-counts/{id}/cancel | Cancel a cycle count | InventoryAuditor, StoreManager |
| POST | /eod-reconciliations | Open a department EOD reconciliation; snapshot opening value | InventoryAuditor, StoreManager |
| GET | /eod-reconciliations/{id} | Get an EOD reconciliation | InventoryAuditor, StoreManager |
| GET | /eod-reconciliations | List EOD reconciliations; filter by department_id, status | InventoryAuditor, StoreManager |
| POST | /eod-reconciliations/{id}/close | Close the day: roll up sales/cogs/shrink, compute shrink alert | InventoryAuditor, StoreManager |
| POST | /_clock/advance | Test-driving: set the server's current UTC clock to an absolute ISO 8601 instant | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_DEPARTMENT_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_SHIPMENT_LINE_NOT_FOUND | 404 |
| ERR_PRICE_PLAN_NOT_FOUND | 404 |
| ERR_PROMOTION_NOT_FOUND | 404 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_COUPON_NOT_FOUND | 404 |
| ERR_CLIPPED_COUPON_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_LINE_ITEM_NOT_FOUND | 404 |
| ERR_CYCLE_COUNT_NOT_FOUND | 404 |
| ERR_EOD_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_INVALID_WINDOW | 422 |
| ERR_SHIPMENT_NOT_PENDING | 409 |
| ERR_SHIPMENT_EMPTY | 409 |
| ERR_SHIPMENT_NOT_RECEIVING | 409 |
| ERR_PRODUCT_DISCONTINUED | 409 |
| ERR_LOT_NOT_ACTIVE | 409 |
| ERR_LOT_NOT_QUARANTINED | 409 |
| ERR_LOT_NOT_PULLABLE | 409 |
| ERR_LOT_NOT_EXPIRABLE | 409 |
| ERR_LOT_NOT_EXPIRED_YET | 409 |
| ERR_PRICE_PLAN_NOT_CANCELLABLE | 409 |
| ERR_PROMOTION_NOT_CANCELLABLE | 409 |
| ERR_MEMBER_NOT_ACTIVE | 409 |
| ERR_MEMBER_NOT_SUSPENDED | 409 |
| ERR_MEMBER_NOT_CLOSEABLE | 409 |
| ERR_SALE_NOT_OPEN | 409 |
| ERR_SALE_EMPTY | 409 |
| ERR_SALE_NOT_FINALIZED | 409 |
| ERR_SALE_NOT_UNPAID | 409 |
| ERR_SALE_NOT_PAID | 409 |
| ERR_CYCLE_COUNT_NOT_DRAFT | 409 |
| ERR_CYCLE_COUNT_NOT_SUBMITTED | 409 |
| ERR_CYCLE_COUNT_NOT_CANCELLABLE | 409 |
| ERR_EOD_NOT_OPEN | 409 |
| ERR_EOD_OPEN_CYCLE_COUNTS | 409 |
| ERR_LINE_UNIT_MISMATCH | 422 |
| ERR_COUPON_NOT_REDEEMABLE | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_RECEIVE_VARIANCE_EXCEEDED | 422 |
| ERR_STALE_PRODUCT_VERSION | 412 |
