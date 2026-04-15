# Food Delivery API — Product Requirements Document

## 1. Introduction

Modern on-demand food delivery bridges the gap between hungry customers who want restaurant-quality meals at home and restaurants seeking wider reach without building their own logistics. This platform connects five distinct stakeholder groups — customers, restaurants, delivery riders, platform administrators, and customer service agents — through a unified API that orchestrates the full order-to-delivery lifecycle.

At its core, the system must balance competing priorities: customers expect transparent pricing and reliable delivery windows; restaurants need efficient order management and predictable revenue settlement; riders require fair compensation and a clear penalty framework; and the platform must sustain itself through commissions, service fees, and surge pricing while preventing abuse. The API governs everything from menu curation and dynamic fee calculation through multi-party financial settlement, complaint adjudication, and a loyalty rewards program, all underpinned by real-time state machines that coordinate concurrent participants in a single transaction.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two HTTP headers that establish the caller's identity and authorization scope. The `X-User-ID` header supplies the unique identifier of the acting user, while the `X-User-Role` header declares the role under which the request is made. Five roles are recognized by the platform:

- `platform_admin` — full administrative access to restaurants, riders, promotions, surge zones, settlements, and complaint escalation
- `restaurant` — manages own menu, confirms/prepares/readies orders, rejects orders, and rates riders
- `customer` — places and cancels orders, tops up wallet, redeems loyalty points, rates restaurants and riders
- `rider` — manages own location and online status, picks up and delivers orders, cancels own deliveries
- `customer_service` — assigns, escalates, and resolves complaints

When either header is missing or contains an unrecognized value, the request is rejected with `ERR_UNAUTHORIZED`. If the headers are valid but the caller's role is not authorized for the requested endpoint, the request is rejected with `ERR_FORBIDDEN`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful responses (2xx status codes) follow a standard envelope:

```json
{
  "meta": {
    "api_request_id": "req_fd7a2c9e4b1d",
    "api_request_timestamp": "2026-03-15T14:22:07.841Z",
    "limit": 20,
    "offset": 0,
    "total_count": 58,
    "has_more": true
  },
  "response_type": "object",
  "data": { }
}
```

#### Standard Error Response Format

All error responses (4xx status codes) follow this envelope:

```json
{
  "meta": {
    "api_request_id": "req_b3e01f8c92a7",
    "api_request_timestamp": "2026-03-15T14:22:09.103Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "ERR_RESTAURANT_NOT_FOUND",
    "message": "The referenced restaurant does not exist."
  }
}
```

Field-level semantics:

- `api_request_id`: A server-generated unique identifier for every request, prefixed with `req_`.
- `api_request_timestamp`: Server-generated ISO 8601 UTC timestamp with exactly three fractional-second digits.
- `response_type`: One of `"object"` (single resource), `"array"` (collection), or `"error"`.
- `data`: The business payload — a resource object, an array of resource objects, or an empty object for 2xx responses with no content. For error responses, `data` contains `error_id` (machine-readable error code) and `message` (human-readable explanation).
- Pagination fields (`limit`, `offset`, `total_count`, `has_more`) appear inside `meta` only for list-endpoint responses.

Unless otherwise noted, operations that create or modify a resource return the created or updated resource object in the `data` field.

### 2.3. Pagination

List endpoints accept two query parameters for pagination. The `limit` parameter controls the maximum number of items returned per page; it defaults to **20**, with a minimum of **1** and a maximum of **100**. The `offset` parameter controls how many items to skip and defaults to **0**.

All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified.

Paginated responses include `limit`, `offset`, `total_count`, and `has_more` within the `meta` object.

### 2.4. Common Resource Properties and Identity

Every primary resource in the system (Restaurants, Menu Items, Customers, Riders, Orders, Order Items, Deliveries, Promotions, Ratings, Complaints, and Surge Zones) is assigned the following system-managed fields upon creation:

- **`id`** (string): A unique, system-generated UUID.
- **`created_at`** (string): An ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-03-15T14:22:07.841Z`), set once at creation.
- **`updated_at`** (string): An ISO 8601 UTC timestamp, updated on every mutation to the resource.
- **`version`** (integer): A monotonically increasing counter that increments with every mutation.

Certain auxiliary entities — Settlements, Rider Penalty Logs, and Wallet Transactions — carry `id` and `created_at` but omit `updated_at` and `version` because they are immutable after creation.

Updates to computed fields (e.g., `rating_average` on a Restaurant, `earnings_balance_cents` on a Rider) count as mutations, updating `updated_at` and incrementing `version` on the parent resource.

### 2.5. Monetary Calculations and Precision

All monetary values in this system are denominated in **integer cents** to avoid floating-point imprecision. Intermediate calculations that involve multiplication by a rate (commission rate, surge multiplier, service fee percentage) use integer arithmetic with explicit rounding:

- After multiplying by a rate, apply `floor` (round toward zero) unless the specific calculation rule states otherwise (some fee calculations use `ceil` — see the service fee and delivery fee rules in Section 3).
- The `cancellation_rate` on a Rider is stored to **4 decimal places** using **round half up**.
- The `rating_average` on both Restaurants and Riders is stored to **2 decimal places** using **round half up**.

### 2.6. Optimistic Concurrency Control

Resources that carry a `version` field support optimistic concurrency control (OCC). When a client sends a `PATCH` request to update a resource, it may include `version` in the request body. If `version` is provided and does not match the resource's current version, the server rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409). If the client omits `version` from the request body, the concurrency check is skipped and the update proceeds unconditionally.

### 2.7. Hierarchical Validation and Nested Resources

For endpoints whose URL path contains multiple resource identifiers — for example, `/platform/restaurants/:restaurant_id/menu-items/:menu_item_id` or `/platform/orders/:order_id/deliveries/:delivery_id` — the server validates each identifier in strict left-to-right order. A request targeting a menu item under a nonexistent restaurant is rejected with `ERR_RESTAURANT_NOT_FOUND` before the system ever looks for the menu item. Similarly, a delivery endpoint validates the order first (`ERR_ORDER_NOT_FOUND`) before checking the delivery (`ERR_DELIVERY_NOT_FOUND`). This sequential validation extends to creation and modification endpoints: the parent resource must exist (and in some cases be in an appropriate state) before child-level validations proceed.

### 2.8. Surge Pricing and Dynamic Delivery Fees

Geographic zones can be designated as **surge zones**, each defined by a center point (`center_latitude`, `center_longitude`), a `radius_km`, and a `surge_multiplier` between 1.0 and 3.0 inclusive. Any attempt to set a multiplier outside this range is rejected with `ERR_INVALID_SURGE_MULTIPLIER`. When computing a delivery fee, the system identifies all `ACTIVE` surge zones whose radius encompasses the restaurant's location and applies the highest applicable `surge_multiplier`. If no active surge zone covers the restaurant, the multiplier defaults to 1.0. Surge zones track `active_rider_count` (online riders within the zone) and `pending_order_count` (unassigned orders within the zone) for operational visibility.

### 2.9. Loyalty Points and Customer Wallet

Customers maintain a prepaid `wallet_balance_cents` and an accumulated `loyalty_points` balance. The wallet serves as the payment instrument: when an order is confirmed, the full `total_cents` is debited from the wallet. If the wallet balance is insufficient at authorization time, the system rejects the transaction with `ERR_INSUFFICIENT_BALANCE`.

Loyalty points are earned on every completed delivery at a rate of one point per 100 cents of `total_cents` (rounded down). Points may be redeemed during order creation to offset the total, at a conversion rate of 100 points equaling 100 cents ($1.00). A minimum of 500 points is required for any redemption; attempts to redeem fewer are rejected with `ERR_INSUFFICIENT_LOYALTY_POINTS`.

Every financial mutation — top-ups, payments, refunds, credits, loyalty redemptions — is recorded as a `WalletTransaction` with a `type` indicating the nature of the transaction (`TOP_UP`, `PAYMENT`, `REFUND`, `CREDIT`, `LOYALTY_REDEMPTION`), an `amount_cents` (positive for credits, negative for debits), a `reference_id` tying it to the originating order or complaint, and a `balance_after_cents` snapshot.

### 2.10. Rider Discipline and Penalty Framework

Riders accumulate `penalty_points` through infractions. The point schedule is:

- A late delivery accrues **10 points**
- Cancelling an assigned delivery accrues **20 points**
- An upheld complaint against the rider accrues **15 points**
- A no-show (no pickup within half an hour of assignment) accrues **25 points**

Each penalty event is recorded in a `RiderPenaltyLog` entry that captures the `reason` (`LATE_DELIVERY`, `CANCELLATION`, `COMPLAINT_UPHELD`, `NO_SHOW`), the `points` assessed, and optionally the associated `delivery_id` or `complaint_id`. The log entry also stores `cumulative_points` — the rider's total penalty points after the event.

When a rider's `penalty_points` reach or exceed the **100-point threshold**, the system automatically suspends the rider, following the same cascade effects as an admin-triggered suspension (described in Section 3). Upon reinstatement by a `platform_admin`, the rider's `penalty_points` are reset to zero.

---

## 3. Business Logic & Workflows

### 3.1. Restaurant Onboarding and Lifecycle

A `platform_admin` registers a new restaurant by supplying its `name`, `cuisine_type`, `address`, geographic coordinates (`latitude` and `longitude`), the `commission_rate` (a decimal between 0.10 and 0.30 that governs the platform's take on each order's subtotal), and the `average_prep_time_minutes` that sets the baseline preparation estimate. The newly created restaurant enters `PENDING_APPROVAL` status and cannot accept orders until an administrator explicitly approves it, transitioning it to `ACTIVE`.

Once a restaurant is `ACTIVE`, it can toggle its `is_accepting_orders` flag to signal whether it is currently open for business. Orders may only be placed against a restaurant that is both `ACTIVE` and accepting orders; a request against a non-active restaurant triggers `ERR_RESTAURANT_NOT_ACTIVE`, while one targeting a restaurant with `is_accepting_orders` set to false is rejected with `ERR_RESTAURANT_NOT_ACCEPTING`.

Suspension by a `platform_admin` moves a restaurant from `ACTIVE` to `SUSPENDED`. This cascade has immediate consequences: all orders in `PLACED` status for that restaurant are automatically cancelled with the status `CANCELLED_BY_PLATFORM`, and the restaurant's `is_accepting_orders` flag is forced to false. A suspended restaurant can be reinstated back to `ACTIVE` by an administrator.

Closing a restaurant — the terminal state `CLOSED` — is permitted from either `ACTIVE` or `SUSPENDED`. When closing from `ACTIVE`, a precondition requires that no orders are currently in `CONFIRMED` or `PREPARING` status; if any such orders exist, the request is rejected with `ERR_ACTIVE_ORDERS_EXIST`. Upon closure from `ACTIVE`, all `PLACED` orders are auto-cancelled (`CANCELLED_BY_PLATFORM`) and every menu item's `is_available` flag is set to false. Closing from `SUSPENDED` similarly sets all menu items to unavailable but does not need to cancel orders (since suspension already cancelled `PLACED` orders).

Restaurants accumulate computed metrics: `rating_average` (2 decimal places, round half up), `rating_count`, `total_orders_completed`, `balance_pending_cents` (unsettled earnings), and `balance_settled_cents` (cumulative settled payouts). These are updated as downstream events occur — order deliveries, ratings, and settlements.

### 3.2. Menu Curation

A `restaurant` role holder adds items to the establishment's menu by providing a `name`, `base_price_cents` (which must be at least 100 — that is, $1.00 minimum), a `category` label (such as appetizer, main, dessert, or drink), and a `prep_time_minutes` estimate specific to that item. An optional `description` may accompany the item. Each menu item carries an `is_available` boolean that the restaurant can toggle; when set to false, the item cannot be included in new orders and any attempt to do so results in `ERR_ITEM_NOT_AVAILABLE`.

Menu items inherit the restaurant as their parent. The `restaurant_id` field on each MenuItem is set by the system when the item is created. Updating a menu item's `base_price_cents`, `name`, `is_available`, `prep_time_minutes`, or `description` requires the restaurant role and supports optimistic concurrency through the `version` field.

### 3.3. Customer Registration and Wallet Management

Customers register with a `name` and `phone` number, and may optionally provide a `default_address` with accompanying `default_latitude` and `default_longitude`. The phone number must be unique across all customers; a duplicate triggers `ERR_DUPLICATE_PHONE`. Similarly, rider phone numbers must be unique among riders.

Upon registration, the customer's `status` is set to `ACTIVE`, `wallet_balance_cents` initializes to zero, `loyalty_points` to zero, and `total_orders` to zero. Customers who are not in `ACTIVE` status cannot place orders — the system rejects such attempts with `ERR_CUSTOMER_NOT_ACTIVE`.

Topping up the wallet is accomplished by posting an `amount_cents` value to the wallet top-up endpoint. This creates a WalletTransaction of type `TOP_UP`, increments the customer's `wallet_balance_cents` by the specified amount, and records the resulting `balance_after_cents`.

### 3.4. Placing an Order

When a `customer` places an order, the request includes the `customer_id`, `restaurant_id`, the `delivery_address` with `delivery_latitude` and `delivery_longitude`, and an `items` array where each element references a `menu_item_id` and `quantity`. Optional fields include `tip_cents` (defaults to 0, must be non-negative or `ERR_INVALID_TIP` is raised), `promotion_id`, `special_instructions` for the rider, and `loyalty_points_to_redeem`.

Before accepting the order, the system validates several constraints in priority order. The restaurant must exist (`ERR_RESTAURANT_NOT_FOUND`), be `ACTIVE` (`ERR_RESTAURANT_NOT_ACTIVE`), and be accepting orders (`ERR_RESTAURANT_NOT_ACCEPTING`). The customer must exist and be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`). The items array must not be empty (`ERR_EMPTY_ORDER`), must not exceed 20 distinct items (`ERR_TOO_MANY_ITEMS`), and every item's `quantity` must be at least 1 (`ERR_INVALID_QUANTITY`). Each referenced menu item must exist and belong to the specified restaurant (`ERR_MENU_ITEM_NOT_FOUND`), must be currently available (`ERR_ITEM_NOT_AVAILABLE`), and all items must belong to the same restaurant (`ERR_CROSS_RESTAURANT_ORDER`).

For each item in the order, the system snapshots the menu item's `base_price_cents` into `unit_price_cents` and computes `item_total_cents` as `unit_price_cents` multiplied by `quantity`. Any `special_requests` text at the item level is preserved for the restaurant.

The order's `subtotal_cents` is the sum of all `item_total_cents` values. The `estimated_prep_time_minutes` is set to the maximum `prep_time_minutes` across all ordered items.

The order is created in `PLACED` status with `payment_status` of `PENDING`. The `placed_at` timestamp is set to the current time.

### 3.5. Fee Calculation and Pricing Engine

Once the subtotal is known, the system computes several fees in sequence.

**Delivery fee.** The platform charges a base of $2.99 (299 cents) plus $1.00 (100 cents) for each kilometer of distance between the restaurant and the delivery address, where the distance in kilometers is rounded up to the nearest whole number. The haversine formula determines the distance. This raw fee is then multiplied by the applicable surge multiplier (see Section 2.8), and the result is floored to produce an integer-cent delivery fee. At order creation time — before a rider is assigned — this constitutes the **provisional delivery fee** and does not include vehicle-type adjustments. After a rider is assigned, the delivery fee may be recalculated: bicycle riders incur an additional $2.00 (200 cents) surcharge when the distance exceeds 5 kilometers, and car riders always incur a $1.50 (150 cents) premium vehicle surcharge. This recalculated amount becomes the **final delivery fee** and may differ from the provisional estimate.

**Service fee.** The platform assesses a service charge that depends on the subtotal tier. For orders with a subtotal below $20.00 (2000 cents), the service fee is 15% of the subtotal, rounded up to the next cent. For subtotals from $20.00 up to but not including $50.00 (5000 cents), the rate drops to 10%, again rounded up. Orders at or above $50.00 are charged 5%, rounded up. Regardless of the computed percentage, the service fee never falls below $0.99 (99 cents).

**Small order fee.** If the subtotal is under $15.00 (1500 cents), a supplemental fee equal to the difference between 1500 and the subtotal is applied, capped at a maximum of $5.00 (500 cents). Orders meeting or exceeding the $15.00 threshold incur no small order fee.

**Promotion discount.** When a `promotion_id` is included in the order, the system verifies the promotion exists (`ERR_PROMOTION_NOT_FOUND`), is in `ACTIVE` status, falls within its `valid_from` to `valid_until` date range, has not been exhausted (`current_uses < max_uses`), and the customer has not exceeded the `max_uses_per_customer` limit. Failure on any count yields `ERR_PROMOTION_NOT_VALID`. Additionally, the order's subtotal must meet or exceed the promotion's `minimum_order_cents`, or the system rejects the order with `ERR_BELOW_MINIMUM_ORDER`.

For a `PERCENTAGE` type promotion, the discount is the subtotal multiplied by `discount_value` divided by 100, floored to the nearest cent, and then capped at `max_discount_cents` if that field is set. A `FIXED_AMOUNT` promotion simply applies its `discount_value` in cents. A `FREE_DELIVERY` promotion sets the discount equal to the computed `delivery_fee_cents`. In all cases, `discount_cents` may never exceed `subtotal_cents`. Upon successful application, `promotion.current_uses` is incremented by one.

**Order total.** The final `total_cents` combines all components: `subtotal_cents` + `delivery_fee_cents` + `service_fee_cents` + `small_order_fee_cents` - `discount_cents` + `tip_cents`. The total must be non-negative.

### 3.6. Order Fulfillment Lifecycle

After an order is `PLACED`, the restaurant may confirm it, transitioning the order to `CONFIRMED`. Confirmation requires the restaurant to be `ACTIVE` and all referenced menu items to still be available. Upon confirmation, `confirmed_at` is recorded, the `payment_status` transitions from `PENDING` to `AUTHORIZED` (at which point the customer's wallet is debited by `total_cents` via a `PAYMENT` wallet transaction — failing with `ERR_INSUFFICIENT_BALANCE` if the balance is inadequate), and `estimated_prep_time_minutes` is computed as the maximum prep time across the order's items.

From `CONFIRMED`, the restaurant signals that cooking has begun by moving the order to `PREPARING`. Once the kitchen has finished, it marks the order `READY_FOR_PICKUP`.

A rider picks up the food by advancing the order from `READY_FOR_PICKUP` to `PICKED_UP`. This action requires the order to have an assigned delivery whose `rider_id` matches the requesting rider, and the delivery must be in `AT_RESTAURANT` status. Upon pickup, `picked_up_at` is set, and the delivery's status also transitions to `PICKED_UP` with its own `pickup_at` timestamp. The delivery then automatically progresses to `EN_ROUTE`.

Finally, the rider marks the order as `DELIVERED`. The delivery must be in `PICKED_UP` or `EN_ROUTE` status. Delivery completion triggers a cascade of financial settlements: `delivered_at` is recorded, `payment_status` moves from `AUTHORIZED` to `CAPTURED`, and payouts are credited — `restaurant_payout_cents` is added to the restaurant's `balance_pending_cents`, while `rider_payout_cents` is added to the rider's `earnings_balance_cents`. Counters are incremented: `total_deliveries_completed` on the rider, `total_orders_completed` on the restaurant, and `total_orders` on the customer. The customer also earns loyalty points equal to `floor(total_cents / 100)`. The delivery's `actual_delivery_time_minutes` is calculated, and `is_late` is flagged as true if the actual time exceeds 1.5 times the `estimated_delivery_time_minutes`. A late delivery triggers a 10-point penalty and a corresponding `RiderPenaltyLog` entry with reason `LATE_DELIVERY`.

### 3.7. Commission and Payout Calculations

When an order reaches `DELIVERED` status, the platform computes the financial split. The restaurant's `commission_amount_cents` equals `floor(subtotal_cents * restaurant.commission_rate)`, and the `restaurant_payout_cents` is `subtotal_cents - commission_amount_cents`.

For the rider, the platform retains 20% of the delivery fee: `rider_platform_fee_cents = floor(delivery_fee_cents * 0.20)`. The rider's payout is then `delivery_fee_cents - rider_platform_fee_cents + tip_cents`. At order confirmation time, a provisional payout estimate is computed using the provisional delivery fee; the final payout at delivery uses the actual delivery fee that incorporates vehicle-type surcharges.

The `rider_earnings_cents` on the Delivery record captures the rider's payout for that specific delivery.

### 3.8. Order Cancellation Scenarios

Customers may cancel their own orders, but only before the kitchen begins work. From `PLACED` status, a customer cancellation transitions the order to `CANCELLED_BY_CUSTOMER`, sets `cancelled_at`, and leaves `payment_status` at `PENDING` (no charge occurred). From `CONFIRMED`, customer cancellation is permitted only if no delivery has been assigned yet, or the delivery is still in `ASSIGNED` status; the `payment_status` transitions from `AUTHORIZED` to `REFUNDED`, and a `REFUND` wallet transaction restores the `total_cents` to the customer's balance. If a delivery exists, its status becomes `CANCELLED_BY_RIDER` and the rider's `active_delivery_count` decreases by one. Once an order reaches `PREPARING` or beyond, the customer can no longer cancel — the system rejects such attempts with `ERR_CANCELLATION_TOO_LATE`.

Restaurants may reject orders from `PLACED` or `CONFIRMED` status, transitioning them to `CANCELLED_BY_RESTAURANT`. A rejection from `PLACED` incurs no charge. A rejection from `CONFIRMED` triggers a refund of the authorized amount, transitioning `payment_status` to `REFUNDED` and crediting the customer's wallet. If a delivery had been assigned, its status is set to `CANCELLED_BY_RIDER`.

Platform administrators can cancel any `CONFIRMED` order via platform-cancel, moving it to `CANCELLED_BY_PLATFORM` with corresponding refund and delivery cancellation effects. Orders in `PLACED` status are auto-cancelled by the system when the associated restaurant is suspended or closed.

### 3.9. Rider Onboarding and Delivery Operations

A `platform_admin` registers riders by supplying `name`, `phone`, `vehicle_type` (one of `BICYCLE`, `MOTORCYCLE`, or `CAR`), and optionally `max_concurrent_deliveries` (defaults to 3). The rider begins in `PENDING_APPROVAL` status and must be approved before going online. Once `ACTIVE`, the rider can update their `current_latitude`, `current_longitude`, `is_online` flag, and `max_concurrent_deliveries`.

The rider's `is_at_capacity` flag is computed as true whenever `active_delivery_count` reaches or exceeds `max_concurrent_deliveries`. Assignment of a delivery to a rider who is at capacity is rejected with `ERR_RIDER_AT_CAPACITY`. The rider must also be `ACTIVE` and have `is_online` set to true, or the assignment fails with `ERR_RIDER_NOT_AVAILABLE`.

A `platform_admin` creates a delivery by posting a `rider_id` to the order's delivery endpoint. The delivery is created in `ASSIGNED` status, `distance_km` is computed via haversine between the restaurant and delivery address, `assigned_at` is set, and `rider.active_delivery_count` is incremented by one. The delivery fee may be recalculated at this point to incorporate vehicle-type adjustments.

The delivery proceeds through a progression: the rider starts heading to the restaurant (`ASSIGNED` to `HEADING_TO_RESTAURANT`), arrives (`HEADING_TO_RESTAURANT` to `AT_RESTAURANT`), picks up the food (handled via the order pickup action, which sets the delivery to `PICKED_UP`), automatically moves to `EN_ROUTE`, and finally reaches the customer (`DELIVERED`). Upon completion, `delivered_at` is set, `actual_delivery_time_minutes` is computed (time from `pickup_at` to `delivered_at`), and `active_delivery_count` is decremented.

A rider may cancel an assigned delivery from `ASSIGNED` or `HEADING_TO_RESTAURANT` status, transitioning it to `CANCELLED_BY_RIDER`. Each cancellation decrements `active_delivery_count`, increments `cancellation_count` by one, assesses 20 penalty points, and creates a RiderPenaltyLog entry with reason `CANCELLATION`. If a delivery sits in `ASSIGNED` status for 30 minutes with no progression, the system marks it `FAILED`, decrements `active_delivery_count`, assesses 25 penalty points, and logs a `NO_SHOW` penalty.

The `cancellation_rate` on a rider is recalculated after every delivery completion or cancellation: `cancellation_count / (total_deliveries_completed + cancellation_count)`. When `total_deliveries_completed` is zero and there are no cancellations, the rate is 0.0. The result is stored to 4 decimal places with round half up.

### 3.10. Rider Suspension and Deactivation

When a `platform_admin` suspends a rider (or the system auto-suspends upon reaching the penalty threshold), the rider's `is_online` flag is set to false. All deliveries in `ASSIGNED` status for that rider transition to `CANCELLED_BY_RIDER`, and the corresponding orders revert to `READY_FOR_PICKUP` to enable reassignment. Each cancelled delivery accrues 15 penalty points.

Reinstatement by a `platform_admin` restores a `SUSPENDED` rider to `ACTIVE` and resets `penalty_points` to zero.

Deactivation is the terminal state `DEACTIVATED`. From `ACTIVE`, deactivation requires that the rider has no active deliveries (`active_delivery_count = 0`); otherwise the request is rejected with `ERR_ACTIVE_DELIVERIES_EXIST`. Upon deactivation, `is_online` is forced to false and any remaining `earnings_balance_cents` is settled in the next settlement run. Deactivation from `SUSPENDED` has no preconditions and similarly schedules remaining earnings for settlement.

### 3.11. Delivery Time Estimation

When an order is created and a delivery is later assigned, the system estimates how long the delivery will take. The haversine distance between the restaurant and the delivery address is computed. Each vehicle type has a per-kilometer travel time: a bicycle covers one kilometer in 3 minutes, a motorcycle in 1.5 minutes, and a car in 2 minutes. The travel time is the distance multiplied by the per-km rate, rounded up to the next whole minute, added to the order's `estimated_prep_time_minutes`.

A delivery is considered late when `actual_delivery_time_minutes` exceeds `estimated_delivery_time_minutes` multiplied by 1.5.

### 3.12. Ratings and Reputation

After an order reaches `DELIVERED` status, participants may submit ratings. Attempting to rate a non-delivered order triggers `ERR_ORDER_NOT_DELIVERED`. Each rating captures a `rater_type` — one of `CUSTOMER_TO_RESTAURANT`, `CUSTOMER_TO_RIDER`, or `RESTAURANT_TO_RIDER` — along with a `rater_id`, `ratee_id`, an integer `score` between 1 and 5 inclusive (violations produce `ERR_INVALID_RATING`), and an optional `comment`. A combination of `rater_type`, `rater_id`, and `order_id` must be unique; duplicates are rejected with `ERR_DUPLICATE_RATING`.

Ratings are created in `PENDING` status and must be published by a `platform_admin` before they affect averages. Upon publication (`PENDING` to `PUBLISHED`), the target entity's `rating_average` and `rating_count` are recalculated. For restaurants, the average covers all `PUBLISHED` ratings where `rater_type` is `CUSTOMER_TO_RESTAURANT`. For riders, it covers `PUBLISHED` ratings where `rater_type` is `CUSTOMER_TO_RIDER` or `RESTAURANT_TO_RIDER`. If a rating count drops to zero (e.g., all ratings are hidden), the average resets to 0.0. A `platform_admin` may also hide a published rating (`PUBLISHED` to `HIDDEN`), triggering a recalculation.

### 3.13. Complaints and Resolution

Complaints can be filed against a `DELIVERED` or cancelled order (any of the `CANCELLED_BY_*` statuses). Attempting to file on an order in any other state yields `ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT`. A maximum of 2 complaints per order is enforced; exceeding this limit triggers `ERR_MAX_COMPLAINTS_REACHED`.

When filing a complaint, the caller specifies `filed_by` (`CUSTOMER`, `RESTAURANT`, or `RIDER`), `filer_id`, a `category` chosen from `WRONG_ITEMS`, `MISSING_ITEMS`, `COLD_FOOD`, `LATE_DELIVERY`, `RUDE_BEHAVIOR`, `DAMAGED_PACKAGING`, or `OTHER`, and a free-text `description`. The complaint enters `FILED` status.

A `customer_service` agent assigns themselves to a filed complaint by posting an `assigned_agent_id`, moving it to `UNDER_REVIEW`. From `UNDER_REVIEW`, the agent may escalate the complaint to `ESCALATED` status, or resolve it. An escalated complaint can be reassigned (by a `platform_admin`) back to `UNDER_REVIEW` with a new `assigned_agent_id`, forming a cyclic path.

Resolution from either `UNDER_REVIEW` or `ESCALATED` status can take three forms based on the `resolution_type` provided:

- **Refund** (`RESOLVED_REFUND`): A `resolution_amount_cents` is set. If the amount equals the order's `total_cents`, the order's `payment_status` transitions to `REFUNDED`; otherwise it becomes `PARTIALLY_REFUNDED`. A WalletTransaction of type `REFUND` credits the customer's wallet. For a full refund, the restaurant's `balance_pending_cents` is clawed back by the `restaurant_payout_cents` amount. If the complaint was filed against a rider, the rider receives 15 penalty points and a `COMPLAINT_UPHELD` penalty log entry.
- **Credit** (`RESOLVED_CREDIT`): A `resolution_amount_cents` is set. A WalletTransaction of type `CREDIT` (not `REFUND`) credits the customer's wallet. No clawback from the restaurant occurs.
- **No action** (`RESOLVED_NO_ACTION`): No financial adjustment is made.

The resolution amount must not exceed the order's `total_cents`; otherwise `ERR_RESOLUTION_EXCEEDS_ORDER` is raised.

Resolved complaints (in any of the `RESOLVED_*` states) are automatically closed by the system after 7 days, transitioning to `CLOSED`.

### 3.14. Promotions and Discount Management

A `platform_admin` creates promotions by specifying a unique `code` (`ERR_DUPLICATE_PROMOTION_CODE` if already taken), a `discount_type` (`PERCENTAGE`, `FIXED_AMOUNT`, or `FREE_DELIVERY`), a `discount_value` (a percentage from 1 to 50 for percentage type, or a fixed cent amount), a `minimum_order_cents` threshold, `max_uses`, `valid_from` and `valid_until` timestamps, and optionally `max_discount_cents` (applicable to percentage discounts), `max_uses_per_customer` (defaults to 1), and a `restaurant_id` to scope the promotion to a specific restaurant.

Promotions are created in `ACTIVE` status and can be disabled by an administrator, moving to `DISABLED`. The system automatically transitions a promotion to `EXPIRED` when the current time passes `valid_until`, and to `EXHAUSTED` when `current_uses` reaches `max_uses`.

### 3.15. Settlement and Payout Processing

Periodically, a `platform_admin` triggers a settlement run by specifying `period_start` and `period_end`. The system processes each restaurant with a positive `balance_pending_cents`: a Settlement record is created with `entity_type` set to `RESTAURANT`, `gross_amount_cents` equal to the pending balance, and `deductions_cents` equal to the sum of `restaurant_payout_cents` from any orders whose complaints were resolved with a refund during the settlement period (clawbacks). The `net_amount_cents` is `gross_amount_cents - deductions_cents`. The restaurant's `balance_pending_cents` is zeroed and `balance_settled_cents` is increased by the net amount.

For each rider with positive `earnings_balance_cents`, a Settlement is created with `entity_type` `RIDER`, `gross_amount_cents` equal to the pending earnings, and `deductions_cents` of zero (rider penalties are point-based, not monetary). The rider's `earnings_balance_cents` is zeroed and `earnings_settled_cents` is increased by the net (which equals the gross).

Settlements are created in `DRAFT` status, transition to `CALCULATED` once the system completes the computation, then require admin approval (`CALCULATED` to `APPROVED`) and final confirmation of payment (`APPROVED` to `PAID`). A `DISPUTED` status also exists for contested settlements. Settlement records carry `id`, `created_at`, `period_start`, `period_end`, `total_orders`, `gross_amount_cents`, `deductions_cents`, `net_amount_cents`, and `status` but lack `updated_at` and `version`.

---

## 4. Endpoint Definitions

All resource-creating endpoints return HTTP 201 upon success. All other modifying or retrieval endpoints return HTTP 200 on success.

| Method | Path | Description | Authorized Roles |
|--------|------|-------------|-----------------|
| POST | /platform/restaurants | Register a new restaurant | platform_admin |
| GET | /platform/restaurants | List restaurants (filter by status, cuisine_type) | platform_admin, customer |
| GET | /platform/restaurants/:restaurant_id | Get restaurant details | platform_admin, restaurant, customer |
| PATCH | /platform/restaurants/:restaurant_id | Update restaurant details | restaurant, platform_admin |
| POST | /platform/restaurants/:restaurant_id/approve | Approve a pending restaurant | platform_admin |
| POST | /platform/restaurants/:restaurant_id/suspend | Suspend a restaurant | platform_admin |
| POST | /platform/restaurants/:restaurant_id/reinstate | Reinstate a suspended restaurant | platform_admin |
| POST | /platform/restaurants/:restaurant_id/close | Permanently close a restaurant | platform_admin |
| POST | /platform/restaurants/:restaurant_id/menu-items | Add a menu item | restaurant |
| GET | /platform/restaurants/:restaurant_id/menu-items | List menu items (filter by category, is_available) | restaurant, customer, platform_admin |
| PATCH | /platform/restaurants/:restaurant_id/menu-items/:menu_item_id | Update a menu item | restaurant |
| POST | /platform/customers | Register a new customer | platform_admin, customer |
| GET | /platform/customers/:customer_id | Get customer details | customer, platform_admin, customer_service |
| PATCH | /platform/customers/:customer_id | Update customer profile | customer |
| POST | /platform/customers/:customer_id/wallet/top-up | Add funds to wallet | customer |
| POST | /platform/riders | Register a new rider | platform_admin |
| GET | /platform/riders | List riders (filter by status, vehicle_type, is_online) | platform_admin |
| GET | /platform/riders/:rider_id | Get rider details | rider, platform_admin |
| PATCH | /platform/riders/:rider_id | Update rider profile | rider |
| POST | /platform/riders/:rider_id/approve | Approve a pending rider | platform_admin |
| POST | /platform/riders/:rider_id/suspend | Suspend a rider | platform_admin |
| POST | /platform/riders/:rider_id/reinstate | Reinstate a suspended rider | platform_admin |
| POST | /platform/riders/:rider_id/deactivate | Permanently deactivate a rider | platform_admin |
| POST | /platform/orders | Place a new order | customer |
| GET | /platform/orders | List orders (filter by customer_id, restaurant_id, status) | customer, restaurant, platform_admin, customer_service |
| GET | /platform/orders/:order_id | Get order details including items | customer, restaurant, rider, platform_admin, customer_service |
| POST | /platform/orders/:order_id/confirm | Restaurant confirms an order | restaurant |
| POST | /platform/orders/:order_id/start-preparing | Start preparing the order | restaurant |
| POST | /platform/orders/:order_id/mark-ready | Mark order as ready for pickup | restaurant |
| POST | /platform/orders/:order_id/pickup | Rider picks up the order | rider |
| POST | /platform/orders/:order_id/deliver | Rider confirms delivery | rider |
| POST | /platform/orders/:order_id/cancel | Customer cancels an order | customer |
| POST | /platform/orders/:order_id/reject | Restaurant rejects an order | restaurant |
| POST | /platform/orders/:order_id/platform-cancel | Platform cancels an order | platform_admin |
| POST | /platform/orders/:order_id/deliveries | Assign a rider to an order | platform_admin |
| GET | /platform/orders/:order_id/deliveries/:delivery_id | Get delivery details | rider, restaurant, platform_admin |
| POST | /platform/orders/:order_id/deliveries/:delivery_id/start | Rider starts heading to restaurant | rider |
| POST | /platform/orders/:order_id/deliveries/:delivery_id/arrive | Rider arrives at restaurant | rider |
| POST | /platform/orders/:order_id/deliveries/:delivery_id/cancel | Rider cancels a delivery | rider |
| POST | /platform/orders/:order_id/ratings | Submit a rating | customer, restaurant |
| GET | /platform/orders/:order_id/ratings | List ratings for an order | customer, restaurant, rider, platform_admin |
| POST | /platform/orders/:order_id/ratings/:rating_id/publish | Publish a pending rating | platform_admin |
| POST | /platform/orders/:order_id/ratings/:rating_id/hide | Hide a published rating | platform_admin |
| POST | /platform/orders/:order_id/complaints | File a complaint | customer, restaurant, rider |
| GET | /platform/orders/:order_id/complaints | List complaints for an order | customer, restaurant, rider, platform_admin, customer_service |
| POST | /platform/orders/:order_id/complaints/:complaint_id/assign | Assign agent to complaint | customer_service, platform_admin |
| POST | /platform/orders/:order_id/complaints/:complaint_id/escalate | Escalate a complaint | customer_service |
| POST | /platform/orders/:order_id/complaints/:complaint_id/resolve | Resolve a complaint | customer_service, platform_admin |
| POST | /platform/promotions | Create a promotion | platform_admin |
| GET | /platform/promotions | List promotions (filter by status) | platform_admin |
| GET | /platform/promotions/:promotion_id | Get promotion details | platform_admin, customer |
| POST | /platform/promotions/:promotion_id/disable | Disable a promotion | platform_admin |
| POST | /platform/surge-zones | Create a surge zone | platform_admin |
| GET | /platform/surge-zones | List surge zones | platform_admin |
| PATCH | /platform/surge-zones/:surge_zone_id | Update a surge zone | platform_admin |
| POST | /platform/settlements/run | Run settlement calculation | platform_admin |
| GET | /platform/settlements | List settlements (filter by entity_type, status) | platform_admin |
| POST | /platform/settlements/:settlement_id/approve | Approve a settlement | platform_admin |
| POST | /platform/settlements/:settlement_id/mark-paid | Mark settlement as paid | platform_admin |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| ERR_UNAUTHORIZED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_BAD_REQUEST | 400 |
| ERR_RESTAURANT_NOT_FOUND | 404 |
| ERR_MENU_ITEM_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_RIDER_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_DELIVERY_NOT_FOUND | 404 |
| ERR_COMPLAINT_NOT_FOUND | 404 |
| ERR_RATING_NOT_FOUND | 404 |
| ERR_PROMOTION_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_SURGE_ZONE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_RESTAURANT_NOT_ACTIVE | 409 |
| ERR_RESTAURANT_NOT_ACCEPTING | 409 |
| ERR_CUSTOMER_NOT_ACTIVE | 409 |
| ERR_RIDER_NOT_AVAILABLE | 409 |
| ERR_RIDER_AT_CAPACITY | 409 |
| ERR_CANCELLATION_TOO_LATE | 409 |
| ERR_ACTIVE_ORDERS_EXIST | 409 |
| ERR_ACTIVE_DELIVERIES_EXIST | 409 |
| ERR_ITEM_NOT_AVAILABLE | 409 |
| ERR_EMPTY_ORDER | 422 |
| ERR_INVALID_QUANTITY | 422 |
| ERR_TOO_MANY_ITEMS | 422 |
| ERR_CROSS_RESTAURANT_ORDER | 422 |
| ERR_DUPLICATE_PHONE | 409 |
| ERR_DUPLICATE_PROMOTION_CODE | 409 |
| ERR_DUPLICATE_RATING | 409 |
| ERR_ORDER_NOT_DELIVERED | 409 |
| ERR_ORDER_NOT_ELIGIBLE_FOR_COMPLAINT | 409 |
| ERR_MAX_COMPLAINTS_REACHED | 409 |
| ERR_INSUFFICIENT_BALANCE | 402 |
| ERR_PROMOTION_NOT_VALID | 422 |
| ERR_BELOW_MINIMUM_ORDER | 422 |
| ERR_INSUFFICIENT_LOYALTY_POINTS | 422 |
| ERR_RESOLUTION_EXCEEDS_ORDER | 422 |
| ERR_INVALID_SURGE_MULTIPLIER | 422 |
| ERR_INVALID_TIP | 422 |
| ERR_INVALID_RATING | 422 |
| ERR_VERSION_CONFLICT | 409 |
