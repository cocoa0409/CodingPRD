# Model, RC & Hobby Store API — Product Requirements Document

## 1. Introduction

The Model, RC & Hobby Store platform is a single back-office and storefront system for a specialty retailer that sells radio-controlled vehicles, kits, spare parts, and batteries, and that also runs a build-and-repair workbench, hosts club race meetings, manages limited pre-order allocations for scarce products, and rewards its members through a tiered loyalty programme. The business problem it solves is that these activities are deeply entangled: a battery sale triggers a safety obligation that later governs whether a racer may take the track, a pre-order reservation quietly draws down a finite allocation pool that must stay perfectly balanced, and every fulfilled sale feeds a lifetime-spend total that promotes a member to a richer discount tier which in turn changes the price of their next order. A change made in one corner of the shop ripples outward, and the system exists to keep those ripples consistent and auditable.

This document specifies the REST API that backs the platform. It is written for the engineers who will implement the service, and it favours domain meaning first and wire-format detail second. Section 2 fixes the system-wide contracts — envelope shape, pagination, identity and roles, concurrency, precision, safety, and time — that every endpoint obeys. Section 3 walks the business workflows: membership and loyalty, the catalogue, pre-order allocation, the order lifecycle, the service bench, and race events. Sections 4 and 5 summarise the endpoint surface and the error catalogue. Because the business rules are deliberately woven through the narrative rather than tabulated, the reader is expected to assemble each operation's full behaviour from the section that owns its business context.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognised roles, the request is rejected with `ERR_MISSING_AUTH` (HTTP 401). The system recognises exactly three roles: `Customer`, `StoreStaff`, and `StoreManager`. When a request is authenticated but the role is not permitted to perform the requested operation — or a `Customer` attempts to act on a resource they do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`: a `Customer` may only place, pay, cancel, or read their own orders, create and cancel their own reservations, register and manage their own race entries, and record their own safety acknowledgement. Public catalogue reads — products, campaigns, and race events — are available to all three roles.

When `X-User-Role` is `StoreStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. `StoreStaff` operate the catalogue, campaigns, fulfilment, service bench, and events, and may act on behalf of members for orders, reservations, and entries. When `X-User-Role` is `StoreManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A `StoreManager` is a hierarchical superset of `StoreStaff`: everything a `StoreStaff` can do, a `StoreManager` can do as well, plus the exclusive authority to cancel a pre-order campaign.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside its permitted range or a negative `offset` is rejected as a field-level validation failure with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; when two resources share an identical `created_at` (as they will whenever they were created under the same logical-clock instant), the tie is broken by their creation order — the sequence in which the server minted them, earliest first. Each list response reports `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every entity in the system — `Customer`, `Product`, `PreOrderCampaign`, `PreOrderReservation`, `Order`, `ServiceJob`, `RaceEvent`, and `RaceEntry` — carries the same four system-managed fields. The `id` is a server-minted UUID with no type prefix, used only for identity. The `created_at` field is an ISO 8601 UTC timestamp with millisecond (three-fractional-digit) precision, set once at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arrive indirectly through a cascade. The `version` field is an integer that begins at 1 when the resource is created and increases by exactly 1 on each mutation, again including cascade-driven mutations. Any change to a computed or derived field — a customer's `loyalty_points_balance`, a campaign's `allocated_units`, an order's `fulfillment_status` — is itself a mutation that refreshes `updated_at` and increments `version`.

Optimistic concurrency control is applied at exactly one write: creating a reservation against a campaign. Because reservations draw down a campaign's finite allocation pool, a client that reserves on a stale view of the campaign could overwrite allocation decisions it never observed. A reservation-create request against a campaign must therefore carry `expected_campaign_version`, and this field is mandatory — it is the client's last observed `version` of the target `PreOrderCampaign`. If `expected_campaign_version` does not equal the campaign's current `version` (for example, because another reservation was created after the client last read the campaign, advancing its version), the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the campaign before retrying. This is a stale-version precondition, evaluated on the observed version alone, and does not depend on requests overlapping in time. No other endpoint takes a version field; all other mutations proceed without an OCC check. Note that each successful reservation create against a campaign is itself a mutation of that campaign that increments the campaign's `version` by 1.

### 2.5. Parallel Order Dimensions and Cascading Cancellation

An `Order` is unusual in that it tracks three independent state fields at once. Its `status` records the placement dimension and moves from `DRAFT` to `PLACED`. Its `payment_status` records the money dimension and moves among `UNPAID`, `PAID`, and `REFUNDED`. Its `fulfillment_status` records the fulfilment dimension and moves among `PENDING`, `FULFILLED`, and `CANCELLED`. The payment and fulfilment dimensions evolve independently: the same `PLACED` order may be paid first and fulfilled later, or fulfilled first and paid later, and neither transition presupposes the other except where a precondition explicitly requires it. An order is terminal once its `fulfillment_status` is either `FULFILLED` or `CANCELLED`.

Several operations cascade across entities, and every level of the cascade must fire. Cancelling a campaign is the deepest example, propagating in three layers. At layer one (L1), each `PreOrderReservation` on the campaign that is in `HELD`, `WAITLISTED`, `ALLOCATED`, or `CONVERTED` is moved to `CANCELLED`. At layer two (L2), each reservation's own cancellation, if it holds an `order_id`, drives that `Order` to `fulfillment_status` `CANCELLED`. At layer three (L3), each order's own cancellation restores product stock and reverses the buyer's provisional loyalty points, exactly as described for order cancellation in Section 3.4. The same layered discipline governs a lone reservation cancellation (L2 into its linked order, then L3) and a race-event cancellation (entries withdrawn, then racer points debited). Because each layer is a mutation of a distinct resource, each one independently refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Monetary Amounts, Loyalty Points, and Rounding

All money in the system is held as an integer number of cents; there are no fractional-cent values and no floating-point money. Where a calculation divides — a percentage discount, a per-line points multiplier, an entry-fee conversion — the intermediate result is reduced to an integer by taking the floor (rounding toward zero for the non-negative quantities involved), and the specific step at which the floor applies is pinned by each calculation in Section 3 and must not be moved. Discount computation floors on the discount step; loyalty points floor per line before summing; a service quote floors on the labour step; entry points floor the fee-to-points conversion. Loyalty tier thresholds are compared as exact integers with an inclusive lower bound: a member whose lifetime spend exactly equals a threshold sits in the higher tier.

Loyalty points and money are conserved quantities. Provisional points credited when an order is placed are reversed in full if that order is later cancelled before fulfilment, and reconciled — not double-counted — when the order is fulfilled. Race entry points credited on registration are debited in full on withdrawal. These compensating movements keep a member's `loyalty_points_balance` consistent with the orders and entries that produced it.

### 2.7. Battery and Hazmat Safety

Batteries are treated as hazardous goods. A product's `is_hazmat` flag is computed at creation and is true exactly when the product's `product_type` is `BATTERY`; for every other product type it is false. Two obligations flow from this flag, and both are gated by a single per-member acknowledgement, `hazmat_safety_ack`, which is false when a member is registered and becomes true only after the member records their battery/hazmat safety acknowledgement. First, an order that contains any line whose product is a battery may only be placed if the buyer's `hazmat_safety_ack` is already true; otherwise placement is rejected with `ERR_HAZMAT_ACK_REQUIRED` (HTTP 409). Second, a racer may only check in to a race if their `hazmat_safety_ack` is true, reflecting a trackside battery inspection; a check-in by a member who has not acknowledged is rejected with `ERR_SAFETY_INSPECTION_REQUIRED` (HTTP 409).

### 2.8. The Logical Clock and Temporal Windows

The server keeps a single logical clock that is the sole source of "now" for every time-based rule; it never reads the real wall clock. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until it is explicitly moved. An administrative, test-driving capability advances or rewinds the logical clock to a supplied `to_iso8601` instant, and all subsequent window checks evaluate against that value.

Three kinds of temporal window govern the business, and all three are half-open — inclusive at the start, exclusive at the end. Reservations may only be created while the current logical time is at or after a campaign's `reservation_open_at` and strictly before its `reservation_close_at`; outside that span the reservation is rejected with `ERR_WINDOW_CLOSED` (HTTP 409). Race registrations may only be created while the current logical time is at or after an event's `registration_open_at` and strictly before its `registration_close_at`; outside that span the registration is rejected with the same `ERR_WINDOW_CLOSED`. Race check-in has its own window that opens a fixed lead time, `CHECKIN_WINDOW_LEAD_MINUTES` (60 minutes), before a heat's `heat_start` and closes at its `heat_end` (exclusive); the window is therefore the half-open interval from `heat_start` minus 60 minutes (inclusive) up to `heat_end` (exclusive), and a check-in whose logical time is before `heat_start` minus that lead or at/after `heat_end` is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409).

Two scheduling conflicts are also policed against time. On the service bench, a job's booked slot must be a valid interval — its `slot_end` strictly after its `slot_start` — and must sit at least `SERVICE_BUFFER_MINUTES` (30 minutes) away from every other slot already booked on the same `bench_code` — that is, the gap between the new slot and every existing neighbour on that bench must be 30 minutes or more; a slot that is invalid or closer than 30 minutes to a neighbour is rejected with `ERR_BENCH_CONFLICT` (HTTP 409). On the track, a race entry's heat interval from `heat_start` (inclusive) to `heat_end` (exclusive) must not overlap another entry sharing the same event and `lane_no`; two intervals that merely touch, where one ends exactly as the next begins, are allowed, but any true overlap is rejected with `ERR_LANE_CONFLICT` (HTTP 409).

### 2.9. Nested Resource Retrieval and the Validation Order

When a path names more than one resource — a reservation created under a campaign, an entry created under an event — the identifiers are validated left to right, and the first identifier that does not resolve to an existing resource stops the request immediately with `ERR_NOT_FOUND` (HTTP 404). This existence check spans every referenced identifier, in the path or the body, including `customer_id`, `product_id`, `campaign_id`, `order_id`, `event_id`, and `entry_id`.

Across the whole API the guard checks run in a fixed priority order, and earlier checks mask later ones so that the returned error is always the highest-priority failure. Authentication comes first: missing or unknown headers yield `ERR_MISSING_AUTH`. Authorization is second: a forbidden role or a `Customer` acting on a resource they do not own yields `ERR_UNAUTHORIZED`. Existence of every referenced resource is third, yielding `ERR_NOT_FOUND`. State validity of the target for the requested transition is fourth, yielding `ERR_INVALID_STATE` (HTTP 409) whenever a resource is not in a state from which the transition is legal, including cross-entity state gates. The campaign-reservation OCC check is fifth, yielding `ERR_STALE_VERSION`. The battery/hazmat safety gates are sixth, yielding `ERR_HAZMAT_ACK_REQUIRED` or `ERR_SAFETY_INSPECTION_REQUIRED`. Temporal-window checks are seventh (`ERR_WINDOW_CLOSED`, `ERR_CHECKIN_WINDOW_CLOSED`); interval-conflict checks are eighth (`ERR_BENCH_CONFLICT`, `ERR_LANE_CONFLICT`). Referential readiness — a reservation must be `ALLOCATED` before it may convert — is ninth, yielding `ERR_RESERVATION_NOT_ALLOCATED`. Business-constraint checks on quantity, capacity, and lane range are tenth (`ERR_ALLOCATION_EXHAUSTED`, `ERR_EVENT_FULL`, `ERR_DUPLICATE_ENTRY`, `ERR_LANE_OUT_OF_RANGE`). Stock sufficiency is eleventh (`ERR_INSUFFICIENT_STOCK`). Payment sufficiency is twelfth (`ERR_INSUFFICIENT_PAYMENT`, HTTP 402). Generic field-level validation — quantities and units at least 1, valid enum members, pagination bounds — is last, yielding `ERR_VALIDATION`. Separately, a `/transition` request whose `action` value is not a recognised action for that resource is rejected with `ERR_INVALID_ACTION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Members and the Loyalty Programme

A member is created by store personnel from an `email` and a `full_name`. At registration the system fixes the member's starting economics: `lifetime_spend_cents` is 0, `loyalty_points_balance` is 0, `loyalty_tier` is `BRONZE`, and `hazmat_safety_ack` is false. A member may read their own record, and store personnel may read any member. Recording a member's battery/hazmat safety acknowledgement flips `hazmat_safety_ack` to true and is the prerequisite discussed in Section 2.7 for both hazmat orders and race check-in.

A member's `loyalty_tier` is a pure function of their `lifetime_spend_cents` and is recomputed whenever that spend changes. A member sits in `GOLD` once lifetime spend reaches at least 200,000 cents (2,000 dollars); otherwise in `SILVER` once it reaches at least 50,000 cents (500 dollars); otherwise in `BRONZE`. The comparison is on exact integer cents with an inclusive lower bound, so lifetime spend of exactly 50,000 cents is `SILVER` and exactly 200,000 cents is `GOLD`. Lifetime spend itself is the sum of `total_cents` across only those of the member's orders whose `fulfillment_status` is `FULFILLED`; unfulfilled, draft, or cancelled orders never contribute.

The tier matters because it sets both the discount rate on new orders and the loyalty-points multiplier, and because the points a member earns are conserved across the order and race lifecycles as described in Section 2.6. A member's `loyalty_points_balance` therefore rises and falls as orders are placed, fulfilled, and cancelled, and as race entries are registered and withdrawn.

### 3.2. The Catalogue and Stock Reservation

Store personnel build the catalogue by creating products, each defined by a `sku`, a display `name`, a `product_type` drawn from `KIT`, `RC_VEHICLE`, `PART`, or `BATTERY`, a `price_cents`, and an opening `stock_on_hand` that defaults to 0. The `is_hazmat` flag is derived at creation from the product type as described in Section 2.7 and is not a client input. Any of the three roles may read a product.

Stock is a reserved-then-settled quantity. When an order is placed, the quantity on each of its lines is debited from the corresponding product's `stock_on_hand`, holding those units against the sale. When an order is cancelled before fulfilment, the same quantities are restored to `stock_on_hand`. Placement and pre-order conversion both demand that every line's product has enough stock on hand to cover the requested quantity at that moment; if any product falls short, the operation is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). Products are listed by store personnel and members alike, optionally narrowed by the product being serviced or pre-sold elsewhere in the system.

### 3.3. Pre-Order Campaigns and Allocation

A pre-order campaign pre-sells a finite quantity of a single product. Store personnel create a campaign against a `product_id` with a `title`, a `total_allocation_units` pool, a `unit_price_cents` charged when a reservation converts, and a reservation window bounded by `reservation_open_at` and `reservation_close_at`. A fresh campaign starts in `DRAFT` with `allocated_units` at 0 and `remaining_units` equal to the full pool. Opening the campaign advances `DRAFT → OPEN` and is the point after which reservations may be created; opening a campaign that is not in `DRAFT` is an invalid-state error.

While a campaign is `OPEN` and the logical clock sits inside its half-open reservation window, a member (or staff acting for them) may hold units by creating a reservation. The reservation names its `customer_id`, the `requested_units` wanted, and the `expected_campaign_version` demanded by the OCC rule of Section 2.4. A new reservation begins `HELD` with `allocated_units` at 0, and its `campaign_id` is taken from the path rather than the body. A reservation's `status` is one of `HELD`, `ALLOCATED`, `WAITLISTED`, `CONVERTED`, `CANCELLED`, or `EXPIRED`, where the last three are terminal. The requested amount must be at least 1 and may not exceed the campaign's whole `total_allocation_units` — a single reservation may not ask for more than the entire pool — and a request that exceeds the pool is rejected with `ERR_ALLOCATION_EXHAUSTED` (HTTP 409). Creating a reservation advances the campaign's `version`, which is precisely why a later reservation from a client holding an older version fails the stale-version check.

Allocation is run as a single sweep that advances the campaign `OPEN → ALLOCATING`; attempting to allocate a campaign that is not `OPEN` — including a second attempt on an already-allocating or cancelled campaign — is rejected with `ERR_CAMPAIGN_ALREADY_ALLOCATED` (HTTP 409). The sweep walks the campaign's `HELD` reservations in ascending `created_at` order; `created_at` is the primary ordering key, and reservations sharing an identical `created_at` (created under the same logical-clock instant) are walked in their creation order — the sequence in which they were minted, earliest first. It carries a running remaining pool that starts at `total_allocation_units`. For each reservation in turn, if its `requested_units` is at most the remaining pool, the reservation is granted in full — its `allocated_units` becomes its `requested_units`, its status moves `HELD → ALLOCATED`, and the remaining pool drops by that amount; otherwise the reservation is passed over, its `allocated_units` stays 0, and its status moves `HELD → WAITLISTED`. After the walk, the campaign's `allocated_units` is `total_allocation_units` minus whatever remains in the pool, and `remaining_units` is `total_allocation_units` minus `allocated_units`. The boundary is inclusive: a reservation whose request exactly equals the remaining pool is allocated, not waitlisted.

The campaign's `allocated_units` is a conserved quantity: at all times, after the sweep and after any later release, it equals the sum of `allocated_units` over reservations whose status is `ALLOCATED` or `CONVERTED`. An allocated reservation is turned into a real sale by converting it, which requires that the reservation is `ALLOCATED` (otherwise `ERR_RESERVATION_NOT_ALLOCATED`), that the campaign is still `ALLOCATING` (otherwise `ERR_INVALID_STATE`), and that the product has at least `allocated_units` in stock (otherwise `ERR_INSUFFICIENT_STOCK`). These three preconditions are evaluated in exactly that order, so the reservation's `ALLOCATED` readiness is checked before the campaign's `ALLOCATING` state — a reservation that is not `ALLOCATED` yields `ERR_RESERVATION_NOT_ALLOCATED` even when its campaign is also no longer `ALLOCATING`; this specific ordering governs conversion and takes precedence over the general priority ladder of Section 2.9. Conversion is restricted to store personnel. Conversion moves the reservation `ALLOCATED → CONVERTED`, creates an already-`PLACED` order whose `source` is `PRE_ORDER` for the reservation's own `customer_id` carrying a single line of the campaign's product at the campaign's `unit_price_cents` for the granted `allocated_units`, records the new order's id on the reservation's `order_id`, and — as part of that placement — reserves stock and credits provisional loyalty points. Converting a reservation does not change the campaign's status; it remains `ALLOCATING`.

Cancelling a reservation moves it to `CANCELLED` from any non-terminal state. If the reservation had been `ALLOCATED` or `CONVERTED`, the campaign's `allocated_units` is decreased by that reservation's `allocated_units`, releasing the units back into the conserved total; released units are not auto-promoted to any waitlisted reservation. If the reservation carried an `order_id` and that order is not already terminal, the cascade cancels that order as described in Section 3.4. A member may cancel their own reservation; staff may cancel any. The whole campaign may be cancelled only by a `StoreManager`, from any state other than already-cancelled, and that cancellation runs the full L1→L2→L3 cascade of Section 2.5: every `HELD`, `WAITLISTED`, `ALLOCATED`, or `CONVERTED` reservation is cancelled, each linked order is driven to `fulfillment_status` `CANCELLED`, and each such order restores its stock and reverses its provisional points.

### 3.4. Orders: Placement, Payment, Fulfilment, and Cancellation

An order begins life as a draft. A buyer (or staff acting for them) creates it with the buyer's `customer_id`, an optional `source` that defaults to `STANDARD`, and an array of `lines`, where each line is an object carrying a `product_id`, a `quantity` of at least 1, and a `unit_price_cents`. When the buyer is a `Customer`, the order's `customer_id` must equal `X-User-ID`. A new order rests in `status` `DRAFT`, `payment_status` `UNPAID`, and `fulfillment_status` `PENDING`, with all totals and points at 0 until it is placed.

Placing an order advances `status` `DRAFT → PLACED` and is where the money is computed and stock is committed. Placement is refused unless the order is still `DRAFT`, unless every line's product has stock to cover its quantity (else `ERR_INSUFFICIENT_STOCK`), and — if any line's product is a battery — unless the buyer's `hazmat_safety_ack` is true (else `ERR_HAZMAT_ACK_REQUIRED`). On success, the totals are computed against a snapshot of the buyer's `loyalty_tier` taken at this placement moment. The `subtotal_cents` is the sum over the lines of `quantity` multiplied by `unit_price_cents`. The tier fixes a discount rate — 0 percent for `BRONZE`, 5 percent for `SILVER`, 10 percent for `GOLD` — and `discount_cents` is the floor of `subtotal_cents` multiplied by that rate and divided by 100; the discount is keyed on the subtotal, never on the total. The `hazmat_surcharge_cents` is a flat 500 cents if any line's product is a battery and 0 otherwise. The `total_cents` is then `subtotal_cents` minus `discount_cents` plus `hazmat_surcharge_cents`, with the surcharge added strictly after the discount has been taken. Placement also reserves stock for every line and credits the buyer's provisional points.

Provisional points, stored on the order as `provisional_points`, are computed at placement using the tier snapshot. The multiplier is 100 for `BRONZE`, 150 for `SILVER`, and 200 for `GOLD`. For each line, the line's points are the floor of `quantity` multiplied by `unit_price_cents` multiplied by the tier multiplier, all divided by 10,000; the floor is applied to each line individually and the floored line results are then summed — never summed first and floored once. `provisional_points` is that per-line-floored sum under the placement tier, and it is added to the buyer's `loyalty_points_balance` at placement.

Paying an order settles the money dimension. Payment supplies an `amount_cents` and requires that the order is `PLACED`, that its `payment_status` is currently `UNPAID`, and that `amount_cents` is at least the order's `total_cents` (else `ERR_INSUFFICIENT_PAYMENT`, HTTP 402). On success the order's `amount_paid_cents` is set to the paid amount and `payment_status` moves `UNPAID → PAID`. Paying an order whose `payment_status` is not `UNPAID` — already paid or refunded — is rejected with `ERR_PAYMENT_ALREADY_SETTLED` (HTTP 409).

Fulfilling an order, an action reserved to store personnel, settles the fulfilment dimension and is where lifetime spend and the final points reconciliation happen. Fulfilment requires that the order is `PLACED`, that its `payment_status` is `PAID` (else `ERR_INVALID_STATE`), and that its `fulfillment_status` is `PENDING`. On success the order's `total_cents` is added to the buyer's `lifetime_spend_cents` before the final tier is evaluated. The order's `final_points` are then computed with the very same per-line-floor-then-sum method used for provisional points, but under the buyer's tier evaluated as of the moment immediately before this order's total was folded into lifetime spend; because a large order can itself push the buyer over a threshold, `final_points` can exceed `provisional_points`. The buyer's `loyalty_points_balance` is adjusted by the difference between `final_points` and `provisional_points` — a reconciliation, not a fresh credit. The order's `fulfillment_status` moves `PENDING → FULFILLED`, and the buyer's `loyalty_tier` is recomputed against the new lifetime spend.

Cancelling an order — by the buyer or staff for a standard order, or by the system through a reservation or campaign cascade — is only possible while `fulfillment_status` is `PENDING`; a `FULFILLED` order can never be cancelled. Cancellation restores stock by adding each line's `quantity` back to its product's `stock_on_hand`, reverses the provisional loyalty credit by subtracting `provisional_points` from the buyer's `loyalty_points_balance`, and, if the order's `payment_status` was `PAID`, moves it `PAID → REFUNDED`. The order's `fulfillment_status` then moves `PENDING → CANCELLED`. Orders may be listed and read by their owner and by store personnel, optionally filtered by `customer_id`.

### 3.5. Build and Repair Service Jobs

The workbench is modelled as a service job, opened by store personnel for a member's item. A job is created with the owner's `customer_id`, an optional `product_id` naming the catalogue item under service (left null when the item is customer-owned and non-catalogue), and a `job_type` of either `BUILD` or `REPAIR`; an optional opening `estimated_parts_cents` defaults to 0. A new job rests in `RECEIVED` with `rework_count` at 0. Jobs may be listed and read, optionally filtered by owner or serviced product.

A job is scheduled onto a workbench by supplying a `bench_code`, a `slot_start`, and a `slot_end`; the system records these and applies the bench-buffer conflict rule of Section 2.8. Scheduling records the slot without changing the job's lifecycle `status` and is permitted from any non-terminal state — it is rejected with `ERR_INVALID_STATE` only once the job is already `COMPLETED` or `CANCELLED`. Diagnosis moves the job `RECEIVED → DIAGNOSING` and captures an `estimated_labor_hours` (which must be provided and be at least 0) together with an optional revised `estimated_parts_cents`; on diagnosis the system recomputes the job's `provisional_quote_cents` as the floor of `estimated_labor_hours` multiplied by the labour rate of 6,000 cents per hour, plus `estimated_parts_cents`. From diagnosis the job may move to `AWAITING_PARTS`, or start work directly. Starting work moves the job from either `DIAGNOSING` or `AWAITING_PARTS` to `IN_PROGRESS`, and requires that the job has already been scheduled onto a bench (its `bench_code` is set).

Once in progress, work goes to quality control, moving `IN_PROGRESS → QC`. From QC the job either fails and is sent back for rework, moving `QC → IN_PROGRESS` and incrementing `rework_count` by 1, or passes and is readied, moving `QC → READY`. The rework loop may repeat, and each pass through it accumulates one more unit of `rework_count`. Completing a readied job moves it `READY → COMPLETED` and requires both an `actual_labor_hours` and an `actual_parts_cents` to be supplied; on completion the system recomputes the job's `final_invoice_cents` as the floor of `actual_labor_hours` multiplied by the 6,000-cents-per-hour labour rate, plus `actual_parts_cents`, plus `rework_count` multiplied by a rework surcharge of 2,500 cents per rework loop. A job may be cancelled from any non-terminal state, which releases its bench slot. `COMPLETED` and `CANCELLED` are the two terminal states. Every service-job transition is driven by an `action` selector, and an unrecognised action is rejected with `ERR_INVALID_ACTION`.

### 3.6. Race Events, Entries, and Check-In

A race event is created by store personnel with a `name`, an `event_date`, a `capacity` of non-terminal entries, a `lane_count` of available track lanes, an `entry_fee_cents`, and a registration window bounded by `registration_open_at` and `registration_close_at`. A new event starts `SCHEDULED` with `entry_count` at 0. The event's lifecycle is opened for registration (`SCHEDULED → OPEN`), then set running so check-ins begin (`OPEN → RUNNING`), then finished (`RUNNING → FINISHED`); it may be cancelled from any non-terminal state. Each transition requires the event to be in the expected prior state and is otherwise an invalid-state error.

Registering an entry books a racer into a lane. The registration carries the racer's `customer_id`, a `race_class` of `STOCK`, `MODIFIED`, or `PRO`, a `lane_no`, and a heat interval from `heat_start` to `heat_end`; when the actor is a `Customer`, the `customer_id` must equal `X-User-ID`, and the entry's `event_id` is taken from the path. Registration is only accepted while the event is `OPEN` — an event that is still `SCHEDULED`, has already been set `RUNNING`, is `FINISHED`, or has been cancelled rejects registration as an invalid-state error (`ERR_INVALID_STATE`), and this state check precedes the window check per Section 2.9 — and, once the event is `OPEN`, only while the current logical time is inside the event's half-open registration window. The `lane_no` must lie between 1 and the event's `lane_count` inclusive, and a lane outside that range is rejected with `ERR_LANE_OUT_OF_RANGE` (HTTP 400). The event must not already be at capacity — its `entry_count` must be below `capacity`, else `ERR_EVENT_FULL` — and the same member may not hold two non-terminal entries in one event, else `ERR_DUPLICATE_ENTRY`. The heat interval must not overlap another entry sharing the same event and lane, per the lane-conflict rule of Section 2.8. A new entry starts `REGISTERED`. Its `entry_points_awarded` is the floor of the event's `entry_fee_cents` divided by 100, and that many points are credited to the racer's `loyalty_points_balance` at registration; the event's `entry_count` rises by 1.

Checking in advances an entry `REGISTERED → CHECKED_IN` and is the safety-critical gate: it requires that the parent event is `RUNNING` (a cross-entity state dependency, else invalid-state), that the racer's `hazmat_safety_ack` is true (else `ERR_SAFETY_INSPECTION_REQUIRED`), and that the current logical time falls inside the check-in window of Section 2.8. A checked-in entry that takes the track is recorded as raced, moving `CHECKED_IN → RACED`. An entry may be disqualified from either `REGISTERED` or `CHECKED_IN`. An entry may also be withdrawn from either `REGISTERED` or `CHECKED_IN`, whether by the racer, by staff, or by the system as the L1 layer of an event cancellation; withdrawal debits the racer's `loyalty_points_balance` by the same `entry_points_awarded` that registration credited, keeping points conserved relative to registration. `RACED`, `DISQUALIFIED`, and `WITHDRAWN` are terminal. The event's `entry_count` counts entries in `REGISTERED`, `CHECKED_IN`, `RACED`, or `DISQUALIFIED`. Cancelling an event withdraws every `REGISTERED` or `CHECKED_IN` entry (L1) and, through each entry's own withdrawal, debits that racer's points (L2). Entries may be listed and read, optionally filtered by event or by member, and every entry transition is selected by an `action`, with an unknown action rejected as `ERR_INVALID_ACTION`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every `/transition`, `/pay`, `/open`, `/allocate`, `/cancel`, and `/safety-ack` action, and the logical-clock control — return `200 OK`. All request and response bodies follow the envelope of Section 2.2; the request payload and side effects of each endpoint are described in the Section 3 narrative that owns its workflow.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager, StoreStaff |
| POST | `/customers` | Register a customer/loyalty member | StoreStaff, StoreManager |
| GET | `/customers/{customer_id}` | Get a customer (own for Customer) | Customer, StoreStaff, StoreManager |
| POST | `/customers/{customer_id}/safety-ack` | Record the member's battery/hazmat safety acknowledgement | Customer, StoreStaff, StoreManager |
| POST | `/products` | Create a catalog product | StoreStaff, StoreManager |
| GET | `/products/{product_id}` | Get a product | Customer, StoreStaff, StoreManager |
| POST | `/campaigns` | Create a pre-order/allocation campaign | StoreStaff, StoreManager |
| GET | `/campaigns/{campaign_id}` | Get a campaign | Customer, StoreStaff, StoreManager |
| GET | `/campaigns` | List campaigns, optionally filtered by product | Customer, StoreStaff, StoreManager |
| POST | `/campaigns/{campaign_id}/open` | Open a campaign for reservations | StoreStaff, StoreManager |
| POST | `/campaigns/{campaign_id}/allocate` | Run the allocation sweep | StoreStaff, StoreManager |
| POST | `/campaigns/{campaign_id}/cancel` | Cancel a campaign (L1→L2→L3 cascade) | StoreManager |
| POST | `/campaigns/{campaign_id}/pre-orders` | Create a reservation (OCC-guarded on campaign version) | Customer, StoreStaff, StoreManager |
| GET | `/pre-orders/{reservation_id}` | Get a reservation | Customer, StoreStaff, StoreManager |
| GET | `/pre-orders` | List reservations by campaign, customer, or order | Customer, StoreStaff, StoreManager |
| POST | `/pre-orders/{reservation_id}/transition` | Reservation lifecycle (CONVERT, CANCEL) | Customer, StoreStaff, StoreManager |
| POST | `/orders` | Create a DRAFT order with line items | Customer, StoreStaff, StoreManager |
| GET | `/orders/{order_id}` | Get an order | Customer, StoreStaff, StoreManager |
| GET | `/orders` | List orders filtered by customer | Customer, StoreStaff, StoreManager |
| POST | `/orders/{order_id}/pay` | Pay a PLACED order | Customer, StoreStaff, StoreManager |
| POST | `/orders/{order_id}/transition` | Order lifecycle (PLACE, FULFILL, CANCEL) | Customer, StoreStaff, StoreManager |
| POST | `/service-jobs` | Open a build/repair service job | StoreStaff, StoreManager |
| GET | `/service-jobs/{job_id}` | Get a service job | Customer, StoreStaff, StoreManager |
| GET | `/service-jobs` | List service jobs by customer or product | Customer, StoreStaff, StoreManager |
| POST | `/service-jobs/{job_id}/transition` | Service job lifecycle + scheduling | StoreStaff, StoreManager |
| POST | `/race-events` | Create a race/club event | StoreStaff, StoreManager |
| GET | `/race-events/{event_id}` | Get a race event | Customer, StoreStaff, StoreManager |
| POST | `/race-events/{event_id}/transition` | Event lifecycle (OPEN, RUN, FINISH, CANCEL) | StoreStaff, StoreManager |
| POST | `/race-events/{event_id}/entries` | Register a race entry | Customer, StoreStaff, StoreManager |
| GET | `/race-entries/{entry_id}` | Get a race entry | Customer, StoreStaff, StoreManager |
| GET | `/race-entries` | List race entries by event or customer | Customer, StoreStaff, StoreManager |
| POST | `/race-entries/{entry_id}/transition` | Entry lifecycle (CHECK_IN, RACED, DISQUALIFY, WITHDRAW) | Customer, StoreStaff, StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CAMPAIGN_ALREADY_ALLOCATED` | 409 Conflict |
| `ERR_ALLOCATION_EXHAUSTED` | 409 Conflict |
| `ERR_RESERVATION_NOT_ALLOCATED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_HAZMAT_ACK_REQUIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_PAYMENT` | 402 Payment Required |
| `ERR_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_LANE_CONFLICT` | 409 Conflict |
| `ERR_BENCH_CONFLICT` | 409 Conflict |
| `ERR_SAFETY_INSPECTION_REQUIRED` | 409 Conflict |
| `ERR_INVALID_ACTION` | 400 Bad Request |
| `ERR_LANE_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_PAYMENT_ALREADY_SETTLED` | 409 Conflict |
