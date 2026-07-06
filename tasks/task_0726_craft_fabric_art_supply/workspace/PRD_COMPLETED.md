# Craft, Fabric & Art-Supply Store API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a craft, fabric, and art-supply retailer of the Michaels/JOANN mold. The business blends several retail models that rarely coexist in a single system: fabric and trim sold by the yard alongside conventional unit-priced merchandise and bulk goods, weekly-ad coupons and a tiered loyalty program layered over every basket, in-store class and workshop registration with supply kits, a custom-framing counter, project bill-of-materials bundles, vendor special orders, and buy-online-pickup-in-store (BOPIS) fulfillment. Each of these threads touches pricing, inventory, or customer identity, and the interesting behavior lives in how they interact.

The core challenge the service must solve is keeping money and stock exactly correct across a cut-to-order fulfillment flow. A bolt of fabric is priced per yard but the true amount is not known until an associate physically cuts and measures it, so an order carries a provisional estimate at submission and a recomputed final figure once the cut is recorded. Inventory must be reserved the moment an order is submitted and only physically drawn down at pickup, with every cancellation compensating the reservation it created. Discounts, loyalty accrual, loyalty redemption, waitlist promotion, and framing linkage all hang off this same order lifecycle. Prices are always expressed and computed in integer cents.

The audience for this document is the engineering team implementing the API. It describes the domain rules first and the HTTP surface second; the endpoint and error tables in sections 4 and 5 are deliberately thin, and the behavior that governs each endpoint is developed in the business-logic narrative of section 3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or invalid, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `Customer`, `StoreAssociate`, `StoreManager`, and `FramingSpecialist`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; the server accepts and records this identifier but does not enforce resource ownership — access is gated by role alone, and a `Customer` request is never rejected on the ground that a resource's `customer_id` differs from `X-User-ID`. When `X-User-Role` is `StoreAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. When `X-User-Role` is `StoreManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `FramingSpecialist`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter defaults to 0 and has a minimum of 0. A `limit` or `offset` value that falls outside these bounds is silently clamped into range rather than rejected, while a non-integer value is rejected with `ERR_INVALID_REQUEST`. List endpoints return their results sorted by `created_at` in ascending order; ties among records sharing the same `created_at` are broken by server insertion order (the sequence in which the records were created). The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every entity in this system carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at 1 when the resource is created and increments by one on every mutation of that resource, while `updated_at` is refreshed to the mutation time. Read operations never change either field.

### 2.5. Precision, Rounding, and Monetary Invariants

All monetary values are integer cents. Wherever a computation produces a fractional cent, the result is rounded half up to the nearest whole cent. The order of rounding within a calculation is fixed and significant: per-line prices are each rounded to whole cents before any summation, and coupon discounts are computed and rounded step by step in the sequence described in section 3, never in a single combined expression. Two structural invariants hold at all times: for an inventory lot, on-hand stock always equals available stock plus reserved stock; and for a loyalty account, the points balance always equals cumulative points earned minus cumulative points redeemed.

### 2.6. Cascading State Effects and Hierarchical Consistency

Many operations mutate more than one entity in a single logical step. When an order is submitted, submitted-order lines and the inventory lots they draw on change together; when a workshop is cancelled, its registrations and their supply-kit order lines change together; when a registration is cancelled, a waitlisted peer may be promoted in the same step. In every such cascade, each affected entity has its own `version` incremented and its own `updated_at` refreshed as it is mutated. Reservation-creating effects always have a matching compensating release on cancellation, so that the inventory invariant is preserved regardless of the path taken through a lifecycle.

### 2.7. Nested Resource Retrieval

Endpoints whose paths contain more than one resource identifier validate those identifiers strictly from left to right. The parent resource is resolved first; if it does not exist, the corresponding not-found error is returned before any child identifier is examined. The not-found errors are role-specific to the resource: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_FRAMING_NOT_FOUND`, and `ERR_SPECIAL_ORDER_NOT_FOUND`, each HTTP 404. When a request body carries a foreign-key reference (for example a `product_id`, `session_id`, or `order_id` on a create operation) that does not resolve to an existing record, the response is `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404). Individual retrieval by id of a resource that has no dedicated not-found code in the list above — namely an inventory lot, a coupon, a room, an order line, or a project bundle — likewise returns `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) when the id does not resolve. A malformed body, a missing required field (including a required field explicitly present with a null value), or a type mismatch is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: (1) presence and validity of the user-context headers; (2) role permission for the operation; (3) existence of every path resource id, validated left to right; (4) resolution of body foreign-key references; (5) the target resource being in the correct state for the operation, which is also where the optimistic-concurrency version check for coupon application is enforced; (6) business-temporal windows, namely that a workshop session is still open for registration and that a coupon is within its validity window; (7) the by-the-yard cut-increment constraint; (8) room scheduling conflicts; (9) customer session time overlaps; (10) coupon stackability; (11) coupon minimum-basket eligibility; and (12) sufficiency of inventory or loyalty points for the operation. A lower-numbered check always resolves before a higher-numbered one, so an earlier failure masks any later condition.

### 2.9. Optimistic Concurrency on Coupon Application

Applying a coupon to an order is guarded by optimistic concurrency control on the order. The apply-coupon operation requires the input field `expected_order_version`, carrying the client's last observed `version` of the target order. If that value does not match the order's current `version` — because another writer has applied a coupon and advanced the order's version since the client last read it — the operation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a discount base it has not observed. On a successful apply, the order's `version` is incremented by one. No other endpoint takes a version field.

### 2.10. The Logical Clock

All time-dependent behavior — coupon validity windows, workshop registration windows, loyalty projections, and rolling-window tier evaluation — reads a logical clock rather than the wall clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it never advances on its own and never reflects real time. A manager-only test-driving capability sets the clock to a supplied `to_iso8601` instant.

## 3. Business Logic & Workflows

### 3.1. Customers, Loyalty Accounts, and Tiers

A customer is registered with an `email` (unique), a `full_name`, and a `home_store_code` such as `CA01` that designates their BOPIS home store. Registering a customer automatically creates exactly one companion loyalty account for that customer, linked by `customer_id`, with `points_earned` and `points_redeemed` both initialized to 0. The loyalty account's `points_balance` is a maintained invariant equal to `points_earned` minus `points_redeemed`. The account also tracks `spend_ytd_cents`, the sum of finalized (picked-up) order totals in the current calendar year. The loyalty account can be retrieved by reverse lookup from the owning customer; that reverse-lookup endpoint responds as a list (an array `response_type` carrying pagination `meta`) whose single element is the customer's loyalty account. The `points_balance`, `tier_forward`, and `tier_chronological` fields are computed at read time and are not persisted on the stored account.

Each loyalty account carries two independently computed membership tiers, each taking one of the values `BASIC`, `SILVER`, or `GOLD`. The two silver and gold thresholds are 500 dollars and 1500 dollars of qualifying spend respectively — that is, 50000 cents and 150000 cents. Both tiers use an at-least comparison against these thresholds: spend equal to the silver threshold qualifies for `SILVER`, and spend equal to the gold threshold qualifies for `GOLD`; anything below the silver threshold is `BASIC`.

The `tier_forward` field is the forward-looking projection. Compute the number of days elapsed from January 1 of the current year through the current clock instant inclusive, using at least 1 to avoid a zero divisor; divide `spend_ytd_cents` by that elapsed-day count and multiply by 365 to project the full-year spend; then compare the projection to the gold threshold and, failing that, the silver threshold, defaulting to `BASIC`. The `tier_chronological` field instead sums the `final_total_cents` of every picked-up order for the customer whose finalization falls within the trailing 365 days (at or after 365 days before now, excluding anything older), and compares that rolling actual spend against the same gold-then-silver thresholds. Both tiers are recomputed whenever a pickup updates spend, and both are reported when the loyalty account is read.

### 3.2. Catalog, Inventory, and the Cut-by-Yard Model

A product is created with a unique `sku`, a `name`, a `sell_mode` that is one of `UNIT`, `BY_YARD`, or `BULK`, and a `unit_price_cents` giving the price per unit or per yard in integer cents. A product also carries `min_cut_increment_yards`, defaulting to 0.25, which is the minimum cutting increment for `BY_YARD` goods and is ignored for `UNIT` and `BULK`; an `is_clearance` flag defaulting to false, marking clearance and seasonal items; and a `special_order_only` flag defaulting to false, marking items obtainable solely through a special order.

Inventory is tracked in lots. A lot is created against a product and records `on_hand_yards`, the physical stock (measured in yards for by-the-yard goods and in whole units otherwise). A newly created lot has `reserved_yards` set to 0 and `available_yards` equal to `on_hand_yards`. Thereafter `reserved_yards` is the sum of `requested_yards` across all order lines in `RESERVED` status that reference this lot's product, and `available_yards` is `on_hand_yards` minus `reserved_yards`; the identity that on-hand equals available plus reserved holds at all times. Lots may be listed by reverse lookup from their product or fetched individually.

### 3.3. Coupons and the Discount Engine

A coupon is created with a unique `code`, a `discount_type` of either `PERCENT` or `FIXED`, and a `value`. For a `PERCENT` coupon the `value` is a fraction between 0 and 1; for a `FIXED` coupon the `value` is an amount in integer cents. A coupon also carries `min_basket_cents` (defaulting to 0), a `stackable` flag (defaulting to false), an `excludes_clearance` flag (defaulting to true), a `priority` integer that orders application in ascending sequence with ties broken by `created_at` ascending, and a validity window bounded by `valid_from` (inclusive) and `valid_to` (exclusive).

Coupons are applied to an order one at a time through the apply-coupon operation, which takes the coupon `code` and the `expected_order_version` described in section 2.9. Applying a coupon adds it to the order's applied set, sets the order's `coupon_id` to this coupon (it holds the last-applied coupon when only one is present and is null when none is applied), increments the order's `version` by one, and recomputes `provisional_total_cents`. Because a coupon may be applied while the order is still `BUILDING`, this recomputation of `provisional_total_cents` prices over lines in `DRAFT`, `RESERVED`, or `FULFILLED` status (using each line's `requested_yards`), so draft lines contribute to the running total even before submission. The running subtotal used for the `min_basket_cents` eligibility check is likewise computed over the order's `RESERVED` and `FULFILLED` lines when any exist, and otherwise over its `DRAFT`, `RESERVED`, and `FULFILLED` lines. At apply time the coupon's validity window is enforced: if the clock instant is before `valid_from` or at or after `valid_to`, the apply is rejected with `ERR_COUPON_EXPIRED`. Applying a second or subsequent coupon requires that all coupons on the order be stackable; if any applied coupon is not stackable, the apply is rejected with `ERR_COUPON_NOT_STACKABLE`. If the order's current running subtotal is below the coupon's `min_basket_cents`, the apply is rejected with `ERR_COUPON_MIN_NOT_MET`.

The discount itself is computed over the applied coupons taken in order of ascending `priority`, ties broken by ascending `created_at`. Begin with a running amount equal to the order subtotal, and separately compute the clearance subtotal as the sum of `line_subtotal_cents` over lines whose product is flagged clearance. Initialize the accumulated discount to zero and walk the applied coupons in order. For each coupon, if the running amount is below that coupon's `min_basket_cents`, skip it. For a `PERCENT` coupon, the base is the running amount minus the clearance subtotal when the coupon excludes clearance, or the full running amount otherwise; if that base would be negative it is floored at zero before the multiplication; the step discount is that base multiplied by the coupon's `value`, rounded half up to whole cents. For a `FIXED` coupon, the step discount is the smaller of the coupon's `value` and the running amount. Add each step discount to the accumulated discount and subtract it from the running amount before moving to the next coupon. The engine's result is the accumulated discount. Coupons may be listed or fetched individually.

### 3.4. Order Assembly and the BOPIS Lifecycle

An order is created for a customer, optionally seeded from a project bundle via `project_bundle_id`, and begins with `fulfillment_status` of `BUILDING` and `payment_status` of `UNPAID`. If a `project_bundle_id` is supplied, one `DRAFT` order line is created for each entry in the bundle's bill of materials. Orders can be listed and filtered by `customer_id`, by `coupon_id`, or by `project_bundle_id`.

Lines are added while the order is `BUILDING`. A line references a `product_id`, a `requested_yards` quantity (yards for by-the-yard goods, a whole count for unit and bulk goods), and optionally a `workshop_registration_id` when the line is a class supply kit. A new line's `status` is `DRAFT`. For a by-the-yard product, `requested_yards` must be a positive multiple of that product's `min_cut_increment_yards`; otherwise the line is rejected with `ERR_INVALID_CUT_INCREMENT`. Each line also carries a computed `line_subtotal_cents` and, once cut, an `actual_cut_yards` value that is null until measured. Order lines may be listed by their order, filtered globally by `product_id` or `workshop_registration_id`, or fetched individually.

Submitting an order advances `fulfillment_status` from `BUILDING` to `SUBMITTED`, and is rejected with `ERR_INVALID_STATE` if the order is not currently `BUILDING`. Submission requires at least one non-cancelled order line, otherwise `ERR_EMPTY_ORDER`; and for each by-the-yard line, the referenced product's lot must have `available_yards` at least the line's `requested_yards`, otherwise `ERR_INSUFFICIENT_INVENTORY`. When a product has more than one lot, the single earliest-created lot for that product is the one against which availability is checked and reservations, draw-downs, and releases are applied; unit and bulk lines are not inventory-checked at submission. On submission every line moves from `DRAFT` to `RESERVED`, each line's `requested_yards` is added to the corresponding lot's `reserved_yards` with `available_yards` recomputed, and `provisional_total_cents` is computed using the provisional pricing variant. The provisional total is produced by the order-pricing calculation: for each line in `RESERVED` or `FULFILLED` status, the raw amount is the product's `unit_price_cents` times the line quantity, and this is rounded half up to whole cents to yield `line_subtotal_cents`; those already-rounded line values are then summed into the subtotal. The provisional variant always uses `requested_yards` as the quantity for every line. From the subtotal the coupon discount of section 3.3 is subtracted, and then the loyalty redemption (described in section 3.5) is subtracted, with the total floored at zero so it never goes negative.

At the cutting counter an associate records the true cut length on a by-the-yard line, setting its `actual_cut_yards`; this record-cut operation requires only that the line exist and that a numeric `actual_cut_yards` be supplied, imposing no order-state or line-status precondition and no re-check of the cut-increment constraint. Marking an order ready advances `fulfillment_status` from `SUBMITTED` to `READY_FOR_PICKUP`. This step requires that `payment_status` be `PAID`, otherwise `ERR_ORDER_NOT_PAID`, and that every by-the-yard line already has its `actual_cut_yards` recorded, otherwise `ERR_CUT_NOT_RECORDED`. It computes `final_total_cents` using the final pricing variant, which differs from the provisional variant only in that by-the-yard lines use `actual_cut_yards` as the quantity while unit and bulk lines continue to use `requested_yards`; the per-line rounding, summation, discount, and redemption steps are otherwise identical.

Completing the pickup advances `fulfillment_status` from `READY_FOR_PICKUP` to `PICKED_UP` and again requires `payment_status` of `PAID`, otherwise `ERR_ORDER_NOT_PAID`. Every `RESERVED` line becomes `FULFILLED`; for each line the lot's `on_hand_yards` is decreased by `actual_cut_yards` for by-the-yard goods (or by `requested_yards` for unit and bulk goods), and its `reserved_yards` is decreased by `requested_yards`, with `available_yards` recomputed. Pickup is also where loyalty accrues: the account's `points_earned` increases by the whole-number result of dividing `final_total_cents` by 100 and discarding any remainder, `spend_ytd_cents` increases by `final_total_cents`, `points_balance` is recomputed, and both membership tiers are recomputed. Both `PICKED_UP` and `CANCELLED` are terminal fulfillment states.

### 3.5. Payment and Loyalty Redemption

Paying an order advances `payment_status` from `UNPAID` to `PAID`; `REFUNDED` is the only further and terminal payment state. Payment requires that the order's `fulfillment_status` be `SUBMITTED`, otherwise `ERR_INVALID_STATE`. The customer may choose to redeem loyalty points on the order by supplying `points_redeemed_on_order` (defaulting to 0). Each redeemed point is worth 1 cent, so the redemption amount subtracted in pricing is `points_redeemed_on_order` multiplied by one cent. If a positive number of points is being redeemed, the loyalty account's `points_balance` must be at least `points_redeemed_on_order`, otherwise `ERR_INSUFFICIENT_POINTS`; on successful payment with redemption, `points_redeemed` increases by `points_redeemed_on_order` and `points_balance` is recomputed. A successful payment also recomputes and rewrites the order's `provisional_total_cents` under the provisional pricing variant so that it reflects the redemption just recorded.

Cancelling an order is permitted from `BUILDING`, `SUBMITTED`, or `READY_FOR_PICKUP`, and is refused with `ERR_INVALID_STATE` if the order is already `PICKED_UP` or `CANCELLED`. Cancellation drives `fulfillment_status` to `CANCELLED` and moves every non-cancelled line to `CANCELLED`. For each line that had been `RESERVED`, its `requested_yards` is subtracted back out of the lot's `reserved_yards` and `available_yards` is recomputed, releasing the reservation the submission created. If any points had been redeemed on the order, that redemption is compensated: `points_redeemed` is decreased by `points_redeemed_on_order` and `points_balance` is recomputed. Any framing order linked to this order that is currently `QUOTED` or `APPROVED` is cancelled as well. If the order had already been paid, the system issues a refund for `provisional_total_cents` and moves `payment_status` to `REFUNDED`.

### 3.6. Rooms, Workshops, Sessions, and Registration

A classroom is created with a `name` and a `cleanup_buffer_min` (defaulting to 30) that is the required gap in minutes between consecutive sessions in that room. A workshop is created in `DRAFT` status with a `title` and an optional `kit_product_id` naming a supply-kit product to be added to registrants' orders. A workshop opens from `DRAFT` to `OPEN`, which requires at least one session to exist, otherwise `ERR_NO_SESSIONS`; it may then close from `OPEN` to `CLOSED`. Cancelling a workshop from `DRAFT`, `OPEN`, or `CLOSED` drives it to the terminal `CANCELLED` state, cascade-cancels each of its `REGISTERED` or `WAITLISTED` registrations, and for each cancelled registration cancels its supply-kit order line if one exists, releasing the associated inventory reservation.

A session belongs to a workshop (via `workshop_id`) and a room and records an `instructor_code` (an opaque instructor identifier, not an entity id), a `starts_at` (inclusive) and `ends_at` (exclusive), and a `capacity`; its `registered_count` starts at 0. When a session is created, the room's schedule is checked: two sessions in the same room must be separated by at least the room's `cleanup_buffer_min`, treating the interval as closed and adding the buffer; a violation is rejected with `ERR_ROOM_CONFLICT`. Sessions may be reverse-looked-up by workshop, filtered by `room_id`, or fetched individually.

Registration attaches a customer to a session. The request names the `session_id` and `customer_id`, and may include an `order_id` so a supply kit can be attached. Registration is permitted only while the workshop is open for registration: the workshop must be `OPEN` and the clock instant must be strictly before the session's `starts_at`, otherwise `ERR_REGISTRATION_CLOSED`. A customer's `REGISTERED` sessions may not overlap in time; overlap is judged on the half-open interval from `starts_at` to `ends_at`, so back-to-back sessions that merely touch at an endpoint are allowed, while a true overlap is rejected with `ERR_CUSTOMER_SESSION_OVERLAP`. If the session still has room — its `registered_count` is below `capacity` — the new registration's `status` is `REGISTERED` and `registered_count` is incremented; otherwise the registration is `WAITLISTED` and receives a `waitlist_rank`, a 1-based position among waitlisted registrations for that session ordered by `created_at` ascending (null unless waitlisted). The `waitlist_rank` is computed live at read time from the current set of waitlisted registrations rather than frozen at creation, so a registration's reported rank reflects the present waitlist ordering. When the workshop defines a `kit_product_id` and an `order_id` was supplied, a `DRAFT` supply-kit order line referencing this registration is added to that order, with a `requested_yards` quantity of 1. This supply-kit line is created whether the resulting registration is `REGISTERED` or `WAITLISTED`, and its creation is not gated by the `min_cut_increment_yards` check. Registrations may be reverse-looked-up by workshop, filtered by `session_id` or `customer_id`, or fetched individually.

Cancelling a registration is permitted only when it is currently `REGISTERED`, otherwise `ERR_INVALID_STATE`. It moves the registration to the terminal `CANCELLED` state and decrements the session's `registered_count`. If any waitlisted registrations remain for that session, the one with the smallest `created_at` is promoted from `WAITLISTED` to `REGISTERED`, its `waitlist_rank` is cleared, and `registered_count` is incremented back. Promotion selects strictly by `created_at` ascending and never uses `id` as a tiebreaker, and it applies whenever a registered seat is freed and `registered_count` is below `capacity`. This waitlist promotion is also the mechanism by which a `WAITLISTED` registration transitions back to `REGISTERED`. When a registration is cancelled as part of a parent workshop cancellation, it moves directly to `CANCELLED` from either `REGISTERED` or `WAITLISTED` with no promotion.

### 3.7. Custom Framing

A framing order is created against a retail order and a customer, capturing the artwork's `width_in` and `height_in` in inches, and begins in `QUOTED` status with its `quoted_price_cents` computed immediately. The quote is built as follows: the united inches are the width plus the height; if the united inches are at most 40 the per-inch rate is 15 cents, else if the united inches are at most 80 the rate is 25 cents, otherwise the rate is 40 cents. The perimeter is twice the sum of width and height. The quoted price is the base of 2000 cents plus the rate multiplied by the perimeter in inches, all rounded half up to whole cents.

The customer approves the quote, moving the framing order from `QUOTED` to `APPROVED`; approval requires that the linked retail order's `fulfillment_status` be either `SUBMITTED` or `READY_FOR_PICKUP`, otherwise `ERR_LINKED_ORDER_NOT_READY`. A framing specialist then starts production, moving `APPROVED` to `IN_PRODUCTION`, and later completes it, moving `IN_PRODUCTION` to the terminal `READY` state. A framing order in `QUOTED` or `APPROVED` may be cancelled — directly by request or automatically when its linked retail order is cancelled — moving it to the terminal `CANCELLED` state. Framing orders may be filtered by `order_id` or `customer_id` and fetched individually.

### 3.8. Project Bundles and Special Orders

A project bundle captures a reusable bill of materials for a customer. It is created with a `customer_id`, a `name`, and a `bom` that is an array of entries each pairing a `product_id` with a `quantity`, and begins in `DRAFT` status; when an order is later created from the bundle, the bundle materializes into draft order lines. Bundles may be filtered by `customer_id` and fetched individually. The bundle lifecycle spans `DRAFT`, `MATERIALIZED`, and `CANCELLED`; materializing a bundle into order lines does not itself mutate the bundle's stored `status`, which remains `DRAFT`.

A special order obtains an item that is only available through a vendor. It is requested with a `customer_id`, a `product_id` naming the special-order-only product, and a `quantity`, and begins in `REQUESTED` status. A manager quotes it, which requires that the special order be in `REQUESTED` status (otherwise `ERR_INVALID_STATE`, checked before the field-presence check) and that `quoted_unit_price_cents` be provided as an integer (otherwise `ERR_INVALID_REQUEST`), and moves it from `REQUESTED` to `QUOTED` while computing the required `deposit_cents`. The deposit is the line value — the `quoted_unit_price_cents` multiplied by the `quantity` — multiplied by 0.50 (half of the line value), rounded half up to whole cents. The customer confirms a quoted special order, which requires it be in `QUOTED` status (otherwise `ERR_INVALID_STATE`) and moves it from `QUOTED` to `CONFIRMED`. An associate receives a confirmed special order, moving `CONFIRMED` to the terminal `RECEIVED` state and creating or incrementing the product's inventory lot by the `quantity`. A special order may be cancelled from `REQUESTED`, `QUOTED`, or `CONFIRMED`, reaching the terminal `CANCELLED` state. Special orders may be filtered by `customer_id` or `product_id` and fetched individually.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; all other successful mutations and all reads return HTTP 200. Request and response bodies and side effects for each endpoint are governed by the narratives in section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Set the logical clock | StoreManager |
| POST | /customers | Register a customer; auto-creates its loyalty account | StoreAssociate, StoreManager |
| GET | /customers | List customers | StoreAssociate, StoreManager |
| GET | /customers/{id} | Get a customer | Customer, StoreAssociate, StoreManager |
| GET | /customers/{id}/loyalty-account | Reverse lookup loyalty account by customer | Customer, StoreAssociate, StoreManager |
| POST | /products | Create a product SKU | StoreManager |
| GET | /products | List products | Customer, StoreAssociate, StoreManager |
| GET | /products/{id} | Get a product | Customer, StoreAssociate, StoreManager |
| POST | /products/{id}/inventory-lots | Create an inventory lot for a product | StoreManager |
| GET | /products/{id}/inventory-lots | Reverse lookup inventory lots by product | Customer, StoreAssociate, StoreManager |
| GET | /inventory-lots/{id} | Get an inventory lot | StoreAssociate, StoreManager |
| POST | /coupons | Create a coupon / weekly-ad code | StoreManager |
| GET | /coupons | List coupons | Customer, StoreAssociate, StoreManager |
| GET | /coupons/{id} | Get a coupon | Customer, StoreAssociate, StoreManager |
| POST | /orders | Create an order (optionally from a project bundle) | Customer, StoreAssociate |
| GET | /orders | List/filter orders by customer, coupon, or bundle | Customer, StoreAssociate, StoreManager |
| GET | /orders/{id} | Get an order | Customer, StoreAssociate, StoreManager |
| POST | /orders/{id}/lines | Add an order line | Customer, StoreAssociate |
| GET | /orders/{id}/lines | Reverse lookup order lines by order | Customer, StoreAssociate, StoreManager |
| GET | /order-lines | Filter order lines by product or workshop registration | StoreAssociate, StoreManager |
| GET | /order-lines/{id} | Get a single order line | Customer, StoreAssociate, StoreManager |
| PATCH | /order-lines/{id}/record-cut | Record actual cut yards for a by-the-yard line | StoreAssociate |
| POST | /orders/{id}/coupons | Apply a coupon to an order (OCC on order version) | Customer, StoreAssociate |
| POST | /orders/{id}/submit | Submit order: reserve inventory, compute provisional total | Customer, StoreAssociate |
| POST | /orders/{id}/pay | Pay order (redeems loyalty points if requested) | Customer |
| POST | /orders/{id}/ready | Mark ready for pickup: compute final total | StoreAssociate |
| POST | /orders/{id}/pickup | Complete pickup: fulfill lines, decrement inventory, accrue loyalty | StoreAssociate |
| POST | /orders/{id}/cancel | Cancel order: release reservations, refund, compensate loyalty | Customer, StoreAssociate |
| POST | /rooms | Create a classroom | StoreManager |
| GET | /rooms | List rooms | StoreAssociate, StoreManager |
| GET | /rooms/{id} | Get a room | StoreAssociate, StoreManager |
| POST | /workshops | Create a workshop | StoreManager |
| GET | /workshops | List workshops | Customer, StoreAssociate, StoreManager |
| GET | /workshops/{id} | Get a workshop | Customer, StoreAssociate, StoreManager |
| POST | /workshops/{id}/open | Open workshop for registration | StoreManager |
| POST | /workshops/{id}/close | Close workshop registration | StoreManager |
| POST | /workshops/{id}/cancel | Cancel workshop; cascade-cancel registrations and kit lines | StoreManager |
| POST | /workshops/{id}/sessions | Create a workshop session; room overlap validated | StoreManager |
| GET | /workshops/{id}/sessions | Reverse lookup sessions by workshop | Customer, StoreAssociate, StoreManager |
| GET | /workshop-sessions | Filter sessions by room | StoreAssociate, StoreManager |
| GET | /workshop-sessions/{id} | Get a session | Customer, StoreAssociate, StoreManager |
| POST | /workshops/{id}/register | Register a customer to a session; auto-waitlist and auto-kit | Customer, StoreAssociate |
| GET | /workshops/{id}/registrations | Reverse lookup registrations by workshop | Customer, StoreAssociate, StoreManager |
| GET | /workshop-registrations | Filter registrations by session or customer | Customer, StoreAssociate, StoreManager |
| GET | /workshop-registrations/{id} | Get a registration | Customer, StoreAssociate, StoreManager |
| POST | /workshop-registrations/{id}/cancel | Cancel a registration; promote earliest waitlisted | Customer, StoreAssociate |
| POST | /framing-orders | Create a framing order linked to a retail order | Customer, FramingSpecialist |
| GET | /framing-orders | Filter framing orders by order or customer | Customer, FramingSpecialist, StoreManager |
| GET | /framing-orders/{id} | Get a framing order | Customer, FramingSpecialist, StoreManager |
| POST | /framing-orders/{id}/approve | Customer approves framing quote | Customer |
| POST | /framing-orders/{id}/start | Begin framing production | FramingSpecialist |
| POST | /framing-orders/{id}/complete | Mark framing ready | FramingSpecialist |
| POST | /framing-orders/{id}/cancel | Cancel framing order | Customer, FramingSpecialist |
| POST | /project-bundles | Create a project/BOM bundle | Customer, StoreAssociate |
| GET | /project-bundles | Filter project bundles by customer | Customer, StoreAssociate, StoreManager |
| GET | /project-bundles/{id} | Get a project bundle | Customer, StoreAssociate, StoreManager |
| POST | /special-orders | Request a special order | Customer, StoreAssociate |
| GET | /special-orders | Filter special orders by customer or product | Customer, StoreAssociate, StoreManager |
| GET | /special-orders/{id} | Get a special order | Customer, StoreAssociate, StoreManager |
| POST | /special-orders/{id}/quote | Manager quotes a special order | StoreManager |
| POST | /special-orders/{id}/confirm | Customer confirms quoted special order | Customer |
| POST | /special-orders/{id}/receive | Receive special order into inventory | StoreAssociate |
| POST | /special-orders/{id}/cancel | Cancel a special order | Customer, StoreAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_WORKSHOP_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_REGISTRATION_NOT_FOUND | 404 |
| ERR_FRAMING_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_REFERENCED_ENTITY_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_EMPTY_ORDER | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_ORDER_NOT_PAID | 409 |
| ERR_CUT_NOT_RECORDED | 409 |
| ERR_INSUFFICIENT_POINTS | 409 |
| ERR_INVALID_CUT_INCREMENT | 422 |
| ERR_ROOM_CONFLICT | 409 |
| ERR_CUSTOMER_SESSION_OVERLAP | 409 |
| ERR_REGISTRATION_CLOSED | 422 |
| ERR_COUPON_EXPIRED | 422 |
| ERR_COUPON_NOT_STACKABLE | 422 |
| ERR_COUPON_MIN_NOT_MET | 422 |
| ERR_LINKED_ORDER_NOT_READY | 409 |
| ERR_NO_SESSIONS | 409 |
