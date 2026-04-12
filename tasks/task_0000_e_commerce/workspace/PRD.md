# E-Commerce Marketplace API — Product Requirements Document

## 1. Introduction

Online marketplaces introduce a fundamental tension between operational velocity and financial accuracy. Customers expect instant checkout with transparent pricing, while sellers demand precise commission accounting and timely payouts. This document specifies the requirements for a marketplace platform API that manages the complete order lifecycle across multiple seller-operated shops — from product catalog management and promotional discount stacking through parallel payment and fulfillment tracking to seller settlement with tiered commission rates.

The platform must resolve several non-trivial challenges. Promotional discounts follow a configurable stacking strategy that produces different totals depending on the shop's chosen application order — a subtlety that affects every downstream calculation from order totals through partial refund amounts to commission deductions. Inventory must be reserved atomically at checkout and released reliably on cancellation or expiry. Commission rates are not flat: they follow a marginal tier structure based on each shop's cumulative monthly gross merchandise value, meaning two identical orders delivered days apart may incur different commission percentages. The settlement process must reconcile all of these moving parts — gross revenue, tiered commissions, and processed refunds — into a verifiable net payout.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. The platform recognizes three roles: `Customer`, `Seller`, and `PlatformAdmin`. A request missing either header or carrying an unrecognized role value is rejected with `ERR_AUTH_HEADER_MISSING`. When a valid user attempts an operation outside the permissions of their declared role, the system responds with `ERR_FORBIDDEN`.

Beyond role-level permissions, the platform enforces ownership constraints. A `Seller` who attempts to manage a shop where the `owner_id` does not match their `X-User-ID` receives `ERR_NOT_SHOP_OWNER`. Similarly, a `Customer` who attempts to act on an order whose `customer_id` does not match their `X-User-ID` is rejected with `ERR_NOT_ORDER_OWNER`.

### 2.2. API Response Structure

#### Standard Success Response

All successful responses (2xx status codes) use the following JSON envelope:

```json
{
  "meta": {
    "api_request_id": "mkt_8f2a1c5b7d9e0346ab12",
    "api_request_timestamp": "2026-03-15T14:22:31.847Z",
    "limit": 20,
    "offset": 0,
    "total_count": 53,
    "has_more": true
  },
  "response_type": "array",
  "data": [ ]
}
```

- The `api_request_id` is a server-generated unique identifier for the request.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` indicates the shape of the payload: `"object"` for a single resource, `"array"` for a list, or `"error"` for failures.
- The `data` field contains the resource object, an array of resource objects, or an empty object for 2xx responses with no payload. Unless otherwise noted, operations that create or modify a resource return the created or updated resource object in the `data` field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) appear only in list endpoint responses.

#### Standard Error Response

All error responses (4xx status codes) follow this envelope:

```json
{
  "meta": {
    "api_request_id": "mkt_c4d20e6f8a1b39570df4",
    "api_request_timestamp": "2026-03-15T14:23:05.219Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_INSUFFICIENT_INVENTORY",
    "message": "Product available count is less than the requested quantity."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a machine-readable identifier for the specific failure condition.
- The `message` provides a human-readable explanation of the error.

### 2.3. Pagination

List endpoints accept optional `limit` and `offset` query parameters. The `limit` specifies the maximum number of items to return and defaults to 20, with a minimum of 1 and a maximum of 100. The `offset` specifies the number of items to skip before beginning to return results and defaults to 0.

All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified. Paginated responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

### 2.4. Common Resource Properties

Most resources in the system — including Shops, Products, Promotions, Orders, Order Items, Refunds, and Settlements — carry a standard set of system-managed fields:

- **`id`** (string): A unique, system-generated UUID.
- **`created_at`** (string): ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-03-15T14:22:31.847Z`), set at creation time.
- **`updated_at`** (string): ISO 8601 UTC timestamp, updated on every mutation to the resource's properties.
- **`version`** (integer): A monotonically increasing integer, incremented on each modification.

Updates to computed fields such as a shop's `monthly_gmv` or `settlement_balance` constitute mutations that update `updated_at` and increment `version` on the parent resource.

Certain resources are append-only event logs. A Payment record, for instance, carries only `id` and `created_at` — it has no `updated_at` or `version`, as payments are immutable once recorded.

### 2.5. Hierarchical Resource Validation

Endpoints targeting nested resources validate path identifiers in strict left-to-right order. A request to `/shops/{shopId}/products/{productId}` first confirms the shop exists, returning `ERR_SHOP_NOT_FOUND` if it does not, before attempting to locate the product. This principle cascades through deeper nesting: a refund request at `/orders/{orderId}/refunds/{refundId}` validates the order before the refund.

For creation and state-transition operations on shop-scoped resources (products, promotions, settlements), the system verifies that the parent shop is in an appropriate state before evaluating child-level rules.

### 2.6. Monetary Precision and Rounding

All monetary calculations — discount application, commission computation, refund distribution, settlement reconciliation — use decimal arithmetic rounded to exactly 2 decimal places using the "round half up" method. Monetary values in API responses are represented as standard numbers (not strings) with a maximum of 2 decimal places. Input fields that represent rates or prices (e.g., `base_price`, commission tier rates) preserve the precision provided at input time.

### 2.7. Optimistic Concurrency Control

Mutation endpoints accept an optional `version` field in the request body. When provided, the server compares this value against the resource's current `version`. A mismatch results in rejection with `ERR_STALE_DATA`, preventing lost updates in concurrent environments. If the `version` field is omitted from the request, the server processes the mutation without performing the concurrency check.

### 2.8. Cascade Consistency Across the Shop Hierarchy

The platform maintains strict consistency between parent and child resource states. When a shop undergoes a state transition that restricts its operational capacity, dependent resources must be brought into alignment. Conversely, operations that depend on a parent resource's operational status — listing a product, activating a promotion, placing an order — are gated on that parent being in the correct state.

Automatic cascading transitions update the `updated_at` and `version` of each affected child resource independently. A suspension that delists three products results in three independent version increments across those products, not a single batch operation on the parent.

### 2.9. Inventory Reservation and Atomicity

Inventory management operates on a reservation model. Each product tracks three quantities: `inventory_count` (total stock), `reserved_count` (units held by unpaid orders), and `available_count` (the difference). Reservation at checkout is atomic across all items in an order — if any single product has insufficient `available_count`, no reservations are made for any item and the entire order is rejected.

Reservations are time-limited. An unpaid order holds inventory for a fixed window, after which the reservation expires and the order is subject to cancellation. Inventory conversions on payment confirmation and restorations on refund processing maintain the integrity of these counters.

### 2.10. Dual-Variant Promotional Stacking

Each shop configures a `discount_strategy` that governs the order in which different promotion types are applied during checkout. The two strategies — `PERCENTAGE_FIRST` and `FIXED_FIRST` — produce different total discounts when both percentage and fixed-amount promotions apply to the same order. This is by design: the stacking order determines the intermediate base on which subsequent discounts are calculated.

Consider a cart with a subtotal of $100, a 20% off promotion, and a $10 off promotion. Under `PERCENTAGE_FIRST`, the 20% reduction yields $80, then the $10 fixed discount produces $70 — a total discount of $30. Under `FIXED_FIRST`, the $10 reduction yields $90, then 20% off produces $72 — a total discount of $28. Both outcomes are correct for their respective configurations.

## 3. Business Logic & Workflows

### 3.1. Shop Registration and Platform Governance

A `Seller` registers a new shop by providing a `shop_name` and their own user identifier as `owner_id`. An optional `description` can accompany the registration, and the `discount_strategy` defaults to `PERCENTAGE_FIRST` if not explicitly provided. Upon registration, the shop enters the `PENDING_REVIEW` state, awaiting platform vetting.

A `PlatformAdmin` reviews pending registrations and may approve a shop. Approval requires the shop to be in `PENDING_REVIEW` — attempting to approve a shop in any other state yields `ERR_SHOP_NOT_PENDING_REVIEW`. Once approved, the shop transitions to `ACTIVE`, and the system initializes both its `monthly_gmv` and `settlement_balance` to zero. These computed fields track the shop's financial position throughout the calendar month.

Platform governance extends to operational oversight. An administrator may suspend an active shop, which triggers an immediate cascade: every `LISTED` product transitions to `DELISTED`, and every `ACTIVE` promotion transitions to `PAUSED`. Critically, suspension does not interrupt orders already in progress — existing orders continue through their payment and fulfillment lifecycle. When the suspension is lifted and the shop is reinstated to `ACTIVE`, products and promotions remain in their suspended states; the seller must manually re-list products and reactivate promotions.

Permanent closure is the terminal action for a shop and carries strict preconditions. No orders may remain in non-terminal states (`CREATED` or `CONFIRMED`), and the `settlement_balance` must be zero — all earnings must have been settled. Closure triggers a final cascade: all non-archived products move to `ARCHIVED`, and all non-terminal promotions move to `CANCELLED`. Attempting to close a shop that still has outstanding orders or an unsettled balance is rejected with `ERR_SHOP_HAS_PENDING_ORDERS`. Closure can be performed on shops that are `ACTIVE` or `SUSPENDED`.

The `Seller` retains the ability to update their own shop's `shop_name`, `description`, and `discount_strategy` at any time via the update endpoint. Changing the `discount_strategy` affects only future orders; existing orders retain the pricing calculated at placement time.

### 3.2. Building the Product Catalog

Within an active shop, a `Seller` creates products by specifying the `product_name`, a `category` string used for promotional matching, the `base_price` per unit (which must be greater than zero), and an initial `inventory_count`. The system populates `shop_id` from the URL path, sets `reserved_count` to zero, computes `available_count` to equal the initial `inventory_count`, and places the product in `DRAFT` status.

Before a product can appear in customer orders, the seller must explicitly list it. Listing transitions the product from `DRAFT` or `DELISTED` to `LISTED` — but only if the parent shop is `ACTIVE`. Attempting to list a product under a non-active shop yields `ERR_SHOP_NOT_ACTIVE`. Products not in `DRAFT` or `DELISTED` cannot be listed, triggering `ERR_PRODUCT_NOT_DRAFT_OR_DELISTED`. To temporarily remove a product from sale, the seller delists it, moving it from `LISTED` to `DELISTED`. Delisting a product that is not currently `LISTED` produces `ERR_PRODUCT_NOT_LISTED_FOR_DELIST`. Existing orders that hold reserved inventory against a delisted product are unaffected — the reservation persists until payment or expiry.

Archival is the terminal state for a product and is irreversible. A product may be archived from either `LISTED` or `DELISTED`, but only when its `reserved_count` is zero. Attempting to archive a product with outstanding reservations results in `ERR_PRODUCT_HAS_RESERVATIONS`. The system also archives products automatically during shop closure or suspension cascades, subject to the same reservation constraint.

Sellers may update product attributes — `product_name`, `category`, `base_price`, `inventory_count` — at any time. When `inventory_count` changes, the system recalculates `available_count` as the new `inventory_count` minus the current `reserved_count`.

### 3.3. Promotional Campaigns and Discount Configuration

Sellers design promotional campaigns by creating promotion resources within their shop. Each promotion requires a `promo_name` for identification, a `promo_type` declaring the discount mechanism — `PERCENTAGE`, `FIXED_AMOUNT`, or `BUY_X_GET_Y_FREE` — and a `promo_value` whose interpretation depends on the type. For `PERCENTAGE` promotions, `promo_value` represents the percentage off (0–100). For `FIXED_AMOUNT`, it is the flat discount in currency units. For `BUY_X_GET_Y_FREE`, the value represents Y, the number of free items the customer receives.

The `promo_threshold` field establishes the minimum condition for activation. In `BUY_X_GET_Y_FREE` promotions, the threshold represents X — the number of items a customer must purchase before the free item benefit applies. For other promotion types, the threshold represents a minimum order subtotal. If omitted, the threshold defaults to zero, meaning no minimum is required.

A `max_discount_cap` may be set on percentage promotions to limit the absolute discount amount. When null, no cap is enforced. The `stackable` boolean — defaulting to `false` — determines whether this promotion can be combined with other promotions on the same order. The `priority` field, a unique integer among the shop's active promotions, controls the application order when stacking occurs (lower values are applied first). Attempting to activate a promotion whose `priority` conflicts with an already-active promotion in the same shop triggers `ERR_DUPLICATE_PROMOTION_PRIORITY`.

Each promotion defines its effective window through `start_time` (inclusive) and `end_time` (exclusive), and may optionally limit total uses via `max_usage`. The system tracks `usage_count`, incremented when payment is confirmed on orders that used the promotion. The `applicable_categories` array restricts the promotion to products matching specific categories; an empty array means the promotion applies universally across the shop's catalog.

Promotions begin in `DRAFT` status with `usage_count` initialized to zero. Activation moves them to `ACTIVE`, subject to the shop being `ACTIVE`, the `end_time` being in the future (otherwise `ERR_PROMOTION_EXPIRED`), and the `priority` being unique. Promotions whose `end_time` has passed transition automatically from `ACTIVE` to `EXPIRED`. A seller may also pause active promotions, reactivate paused ones (with the same preconditions as initial activation), or cancel promotions from `DRAFT`, `ACTIVE`, or `PAUSED` states. Cancellation does not retroactively affect orders that already used the promotion. Activating a promotion that is not in `DRAFT` or `PAUSED` is rejected with `ERR_PROMOTION_NOT_DRAFT_OR_PAUSED`, and pausing one that is not `ACTIVE` yields `ERR_PROMOTION_NOT_ACTIVE`.

### 3.4. Order Placement: Cart Validation, Reservation, and Pricing

A `Customer` places an order by specifying the `shop_id`, a `shipping_address`, and a list of items, each containing a `product_id` and a `quantity` (which must be at least 1). The system captures the customer's identity from the `X-User-ID` header and records it as the order's `customer_id`.

Before proceeding, the system validates that all referenced products belong to the specified shop. If any product's `shop_id` does not match, the order is rejected with `ERR_CROSS_SHOP_ORDER`. Each product must be in the `LISTED` state — a product in any other state triggers `ERR_PRODUCT_NOT_LISTED`. The parent shop must be `ACTIVE`; otherwise `ERR_SHOP_NOT_ACTIVE` halts the process.

Inventory reservation follows. The system attempts to reserve the requested `quantity` for each item by incrementing the product's `reserved_count` and decrementing its `available_count`. This operation is atomic: if any product has insufficient `available_count`, the system rolls back all attempted reservations and returns `ERR_INSUFFICIENT_INVENTORY`. No partial reservations occur. Upon successful reservation, the system sets `reservation_expires_at` to the current time plus half an hour, establishing the payment window.

For each order item, the system captures a `product_snapshot` containing the `product_name`, `base_price`, and `category` at the moment of ordering. The `unit_price` is frozen to the product's `base_price`, and the `line_total` is computed as `unit_price` multiplied by `quantity`. The `order_id` links each item back to its parent order, and `product_id` preserves the cross-aggregate reference.

With item totals established, the system computes the `subtotal` as the sum of all items' `line_total` values. Promotional discounts are then evaluated. The system collects all `ACTIVE` promotions for the shop whose temporal window encompasses the current time, whose `applicable_categories` either is empty or intersects with the categories of the order's items, whose `usage_count` has not reached `max_usage`, and whose `promo_threshold` is met. Among eligible promotions, non-stackable promotions compete on priority — only the highest-priority (lowest `priority` number) non-stackable promotion survives. Stackable promotions all qualify, along with at most one non-stackable promotion. If a promotion has exhausted its maximum usage, it is silently excluded; the error `ERR_PROMOTION_USAGE_EXHAUSTED` applies only when a promotion is the sole candidate and fails the usage check.

The selected promotions are sorted and applied according to the shop's `discount_strategy`. Under `PERCENTAGE_FIRST`, all percentage-type promotions are applied first (ordered by `priority`), followed by fixed-amount promotions, and finally buy-X-get-Y-free promotions. Under `FIXED_FIRST`, fixed-amount promotions lead, followed by percentage, then buy-X-get-Y-free. Each promotion is applied against the running total: a `PERCENTAGE` promotion discounts the running total by `promo_value` percent, capped at the `max_discount_cap` if one is set; a `FIXED_AMOUNT` promotion deducts up to the running total (never below zero); a `BUY_X_GET_Y_FREE` promotion discounts the cheapest Y items' price from the running total. The running total may never drop below 0.01.

The `discount_amount` records the total savings, and `total_amount` is set to `subtotal` minus `discount_amount` (floored at 0.01). The `applied_promotions` array on the order captures each promotion's `promotion_id`, `promo_type`, and `discount_contribution`. Discount allocation then distributes the `discount_amount` proportionally across order items. For each item except the last (sorted by `order_item_id` ascending), the `discount_share` is the rounded proportion of the total discount relative to the item's share of the subtotal. The last item receives the remainder, ensuring the sum of all `discount_share` values equals `discount_amount` exactly. Each item's `final_price` is its `line_total` minus its `discount_share`.

The order is created with `payment_status` set to `UNPAID`, `fulfillment_status` set to `PENDING`, and the derived `order_status` set to `CREATED`.

### 3.5. Payment Flow and Fulfillment Progression

Once an order is placed, the customer has a window — constrained by `reservation_expires_at` — to initiate payment. Attempting to pay after the reservation has expired results in `ERR_RESERVATION_EXPIRED`. Payment initiation requires the `payment_status` to be `UNPAID`; otherwise `ERR_ORDER_NOT_UNPAID` is returned. The customer provides a `payment_method` (one of `CREDIT_CARD`, `DEBIT_CARD`, `WALLET`, or `BANK_TRANSFER`) and a `transaction_ref` from the external payment gateway. The system transitions `payment_status` to `PAYING` and creates a Payment record with `payment_type` set to `CHARGE`, an `amount` equal to the order's `total_amount`, and `status` set to `PENDING`.

Payment confirmation arrives asynchronously. A `PlatformAdmin` confirms successful payment, which requires `payment_status` to be `PAYING` (otherwise `ERR_ORDER_NOT_PAYING`). On confirmation, the Payment record transitions to `SUCCESS`, `payment_status` moves to `PAID`, and the derived `order_status` advances to `CONFIRMED`. Reserved inventory is converted to committed sales: each product's `reserved_count` is decremented by the ordered `quantity`. Each applied promotion's `usage_count` is incremented to reflect actual utilization. If the payment gateway reports failure, the `PlatformAdmin` marks the payment as failed, reverting `payment_status` to `UNPAID` and transitioning the Payment record to `FAILED`. The customer may retry payment provided the reservation has not expired.

A customer may also cancel an order before payment, provided `payment_status` is `UNPAID`. Cancellation transitions the derived `order_status` to `CANCELLED` and releases all reserved inventory — each product's `reserved_count` is decremented by the item's `quantity`. The system also automatically cancels orders when the reservation timeout elapses while the order remains `UNPAID`, triggering the same inventory release.

Fulfillment is a seller-driven workflow. After payment confirmation, the seller begins processing the order by transitioning `fulfillment_status` from `PENDING` to `PROCESSING`. This action requires `payment_status` to be `PAID` or `PARTIAL_REFUND` — attempting it otherwise yields `ERR_ORDER_NOT_PAID`. The order's `order_status` must also be `CONFIRMED`; otherwise `ERR_ORDER_NOT_CONFIRMED` applies. Shipping advances `fulfillment_status` from `PROCESSING` to `SHIPPED` (requiring `ERR_FULFILLMENT_NOT_PROCESSING` if the precondition fails), and delivery confirmation moves it from `SHIPPED` to `DELIVERED` (with `ERR_FULFILLMENT_NOT_SHIPPED` guarding the transition).

### 3.6. Returns and Partial Refund Processing

After payment, a customer may request a refund by specifying a `reason` and a `refund_type` of either `FULL` or `PARTIAL`. For partial refunds, the request includes a `refund_items` array detailing which `order_item_id` entries to refund and the `quantity` for each. An order item referenced in a refund that does not belong to the order triggers `ERR_ORDER_ITEM_NOT_FOUND`. The refund is created in `REQUESTED` status.

The seller reviews the request. Approval requires the refund to be in `REQUESTED` status (`ERR_REFUND_NOT_REQUESTED` otherwise) and the order's `payment_status` to be `PAID` or `PARTIAL_REFUND`. During approval, the system validates that each refund item's `quantity` does not exceed the remaining unrefunded quantity for that order item — the original quantity minus quantities from previously processed refunds. Exceeding this limit triggers `ERR_REFUND_EXCEEDS_REMAINING`. Rejection is also available from `REQUESTED`, simply setting the refund to `REJECTED`.

Processing an approved refund is a `PlatformAdmin` action. The refund must be in `APPROVED` status (`ERR_REFUND_NOT_APPROVED` guards this). For a full refund, the `refund_amount` equals the order's `total_amount` minus any previously processed refunds. For a partial refund, the system computes a `refund_subtotal` by summing the product of each refund item's `quantity` and its corresponding order item `unit_price`. The `refund_discount_share` is then calculated proportionally: for each refund item, the system determines its proportion of the original `subtotal` and allocates that fraction of the total `discount_amount`. Rounding follows the standard 2-decimal, half-up rule, with the last refund item absorbing any remainder to ensure exact totals. The final `refund_amount` is the `refund_subtotal` minus the `refund_discount_share`. The system enforces that cumulative refunds never exceed the order's `total_amount`, rejecting attempts with `ERR_REFUND_EXCEEDS_ORDER_TOTAL`.

Upon processing, the system creates a Payment record with `payment_type` set to `REFUND`. Inventory is restored: the `inventory_count` of each affected product is incremented by the refunded `quantity`, and `inventory_restored` is set to `true` on the refund. If the refund is full, the order's `payment_status` transitions to `FULL_REFUND`, the shop's `settlement_balance` is reduced by the order's net revenue (total minus commission), and `monthly_gmv` is decremented by the `total_amount`. If the refund is partial, `payment_status` moves to `PARTIAL_REFUND` — unless cumulative refunds now equal the `total_amount`, in which case it escalates to `FULL_REFUND` with the same settlement and GMV reversals. Proportional commission amounts are also reversed from `settlement_balance`, and proportional amounts from `monthly_gmv`, ensuring financial accuracy across the ledger.

### 3.7. Revenue Recognition and Tiered Commission

Delivery marks the moment of revenue recognition. When a seller confirms delivery — advancing `fulfillment_status` to `DELIVERED` and `order_status` to `COMPLETED` — the system calculates the platform's commission using a marginal tier structure based on the shop's cumulative gross merchandise value for the current calendar month.

The commission structure operates on three tiers. The first ten thousand dollars of monthly volume carries an eight percent rate. Volume between ten thousand and fifty thousand dollars is charged at five percent. All volume above fifty thousand dollars incurs a three percent rate. These tiers are marginal: when a single order pushes the shop's cumulative volume across a tier boundary, the portion of the order within the lower tier is charged at the lower rate, and only the excess is charged at the higher tier's rate.

To illustrate: if a shop has accumulated $9,500 in monthly GMV and delivers a $1,000 order, the first $500 falls within the initial tier at eight percent ($40), while the remaining $500 enters the second tier at five percent ($25), yielding a total `commission_amount` of $65 and an effective blended `commission_rate` of 6.5%. The commission is rounded to two decimal places using the standard half-up method.

After commission calculation, the system updates the shop's `monthly_gmv` by adding the order's `total_amount`, and increases `settlement_balance` by the order's revenue net of commission (`total_amount` minus `commission_amount`). The `monthly_gmv` resets to zero on the first day of each calendar month, establishing the baseline for the next billing cycle.

### 3.8. Settlement Lifecycle and Dispute Resolution

A `Seller` initiates the payout process by creating a settlement record for a defined time window, specifying `period_start` (inclusive) and `period_end` (exclusive). The system computes the settlement's financials by aggregating completed orders and processed refunds within that window: `gross_amount` sums the `total_amount` of all `COMPLETED` orders delivered during the period, `total_commission` sums their `commission_amount` values, and `total_refunds` sums the `refund_amount` of all `PROCESSED` refunds in the period. The `net_amount` is derived as `gross_amount` minus `total_commission` minus `total_refunds`. Settlement periods must not overlap with existing non-terminal settlements for the same shop; violations trigger `ERR_SETTLEMENT_PERIOD_OVERLAP`. The `shop_id` is set from the URL path.

The settlement begins in `DRAFT` status. Submission for approval transitions it to `PENDING_APPROVAL`, but only if `net_amount` is positive — a zero or negative net triggers `ERR_SETTLEMENT_ZERO_AMOUNT`, and attempting to submit a settlement not in `DRAFT` yields `ERR_SETTLEMENT_NOT_DRAFT`. A `PlatformAdmin` reviews and approves the settlement, verifying that the computed amounts reconcile: `gross_amount` minus `total_commission` minus `total_refunds` must equal `net_amount`. A discrepancy results in `ERR_SETTLEMENT_RECONCILIATION_MISMATCH`. Approval is gated on `PENDING_APPROVAL` status (`ERR_SETTLEMENT_NOT_PENDING` otherwise).

Once approved, the administrator may mark the settlement as paid, which deducts the `net_amount` from the shop's `settlement_balance`. This transition requires `APPROVED` status (`ERR_SETTLEMENT_NOT_APPROVED` guards it).

Alternatively, the seller may dispute a pending settlement, transitioning it from `PENDING_APPROVAL` to `DISPUTED`. Resolution by a `PlatformAdmin` recalculates the settlement amounts and returns it to `PENDING_APPROVAL` for another approval cycle. Disputing requires `PENDING_APPROVAL` status (`ERR_SETTLEMENT_NOT_PENDING`), and resolving requires `DISPUTED` status (`ERR_SETTLEMENT_NOT_DISPUTED_STATE`).

## 4. Endpoint Definitions

Operations that create new stand-alone resources or add new resources to a collection return a `201 Created` status code. Operations that modify an existing resource — including state transitions, updates, and lifecycle actions — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------- |
| POST | `/shops` | Register a new shop | Seller |
| GET | `/shops` | List all shops | Any |
| GET | `/shops/{shopId}` | Get shop details | Any |
| PUT | `/shops/{shopId}` | Update shop details | Seller |
| POST | `/shops/{shopId}/approve` | Approve a shop for operation | PlatformAdmin |
| POST | `/shops/{shopId}/suspend` | Suspend a shop | PlatformAdmin |
| POST | `/shops/{shopId}/reinstate` | Reinstate a suspended shop | PlatformAdmin |
| POST | `/shops/{shopId}/close` | Permanently close a shop | PlatformAdmin |
| POST | `/shops/{shopId}/products` | Create a new product | Seller |
| GET | `/shops/{shopId}/products` | List products for a shop | Any |
| GET | `/shops/{shopId}/products/{productId}` | Get product details | Any |
| PUT | `/shops/{shopId}/products/{productId}` | Update product attributes | Seller |
| POST | `/shops/{shopId}/products/{productId}/list` | List a product for sale | Seller |
| POST | `/shops/{shopId}/products/{productId}/delist` | Remove product from listing | Seller |
| POST | `/shops/{shopId}/products/{productId}/archive` | Archive a product permanently | Seller |
| POST | `/shops/{shopId}/promotions` | Create a new promotion | Seller |
| GET | `/shops/{shopId}/promotions` | List promotions for a shop | Any |
| GET | `/shops/{shopId}/promotions/{promotionId}` | Get promotion details | Any |
| POST | `/shops/{shopId}/promotions/{promotionId}/activate` | Activate a promotion | Seller |
| POST | `/shops/{shopId}/promotions/{promotionId}/pause` | Pause an active promotion | Seller |
| POST | `/shops/{shopId}/promotions/{promotionId}/cancel` | Cancel a promotion | Seller |
| POST | `/orders` | Place a new order | Customer |
| GET | `/orders` | List orders | Any |
| GET | `/orders/{orderId}` | Get order details including items | Any |
| POST | `/orders/{orderId}/cancel` | Cancel an unpaid order | Customer |
| POST | `/orders/{orderId}/pay` | Initiate payment for an order | Customer |
| POST | `/orders/{orderId}/confirm-payment` | Confirm payment success | PlatformAdmin |
| POST | `/orders/{orderId}/payment-failed` | Mark payment as failed | PlatformAdmin |
| POST | `/orders/{orderId}/start-processing` | Begin order fulfillment | Seller |
| POST | `/orders/{orderId}/ship` | Mark order as shipped | Seller |
| POST | `/orders/{orderId}/deliver` | Mark order as delivered | Seller |
| POST | `/orders/{orderId}/refunds` | Request a refund | Customer |
| GET | `/orders/{orderId}/refunds` | List refunds for an order | Any |
| GET | `/orders/{orderId}/refunds/{refundId}` | Get refund details | Any |
| POST | `/orders/{orderId}/refunds/{refundId}/approve` | Approve a refund request | Seller |
| POST | `/orders/{orderId}/refunds/{refundId}/reject` | Reject a refund request | Seller |
| POST | `/orders/{orderId}/refunds/{refundId}/process` | Process an approved refund | PlatformAdmin |
| POST | `/shops/{shopId}/settlements` | Create a settlement record | Seller |
| GET | `/shops/{shopId}/settlements` | List settlements for a shop | Seller, PlatformAdmin |
| GET | `/shops/{shopId}/settlements/{settlementId}` | Get settlement details | Seller, PlatformAdmin |
| POST | `/shops/{shopId}/settlements/{settlementId}/submit` | Submit settlement for approval | Seller |
| POST | `/shops/{shopId}/settlements/{settlementId}/approve` | Approve a settlement | PlatformAdmin |
| POST | `/shops/{shopId}/settlements/{settlementId}/mark-paid` | Mark settlement as paid | PlatformAdmin |
| POST | `/shops/{shopId}/settlements/{settlementId}/dispute` | Dispute a pending settlement | Seller |
| POST | `/shops/{shopId}/settlements/{settlementId}/resolve-dispute` | Resolve a disputed settlement | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_HEADER_MISSING` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_SHOP_OWNER` | 403 Forbidden |
| `ERR_NOT_ORDER_OWNER` | 403 Forbidden |
| `ERR_SHOP_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REFUND_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SHOP_NOT_ACTIVE` | 409 Conflict |
| `ERR_SHOP_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_PRODUCT_NOT_LISTED` | 409 Conflict |
| `ERR_PRODUCT_NOT_DRAFT_OR_DELISTED` | 409 Conflict |
| `ERR_PRODUCT_NOT_LISTED_FOR_DELIST` | 409 Conflict |
| `ERR_PROMOTION_NOT_DRAFT_OR_PAUSED` | 409 Conflict |
| `ERR_PROMOTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_NOT_UNPAID` | 409 Conflict |
| `ERR_ORDER_NOT_PAYING` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_FULFILLMENT_NOT_PROCESSING` | 409 Conflict |
| `ERR_FULFILLMENT_NOT_SHIPPED` | 409 Conflict |
| `ERR_REFUND_NOT_REQUESTED` | 409 Conflict |
| `ERR_REFUND_NOT_APPROVED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PENDING` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DISPUTED_STATE` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_RESERVATION_EXPIRED` | 409 Conflict |
| `ERR_PROMOTION_EXPIRED` | 409 Conflict |
| `ERR_CROSS_SHOP_ORDER` | 400 Bad Request |
| `ERR_DUPLICATE_PROMOTION_PRIORITY` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_ORDER_TOTAL` | 409 Conflict |
| `ERR_SETTLEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SETTLEMENT_ZERO_AMOUNT` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_RECONCILIATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SHOP_HAS_PENDING_ORDERS` | 409 Conflict |
| `ERR_PRODUCT_HAS_RESERVATIONS` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROMOTION_USAGE_EXHAUSTED` | 409 Conflict |
| `ERR_STALE_DATA` | 409 Conflict |
