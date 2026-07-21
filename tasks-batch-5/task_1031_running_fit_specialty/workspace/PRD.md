# Running-Fit Specialty API — Product Requirements Document

## 1. Introduction

Running-Fit is a specialty running store that blends a retail catalog with the services a serious runner depends on: expert gait analysis and shoe fitment, a shoe-rotation tracker that reminds a runner when a pair has reached the end of its usable mileage, a membership club with training-group sessions, and a loyalty programme that rewards repeat spend. This document specifies the REST API that powers all of these operations behind a single flat topology: members, products, orders, returns, subscriptions, running shoes, fitters, fitment sessions, training sessions, and training bookings all exist as peer collections linked to one another by foreign-key references rather than by nested ownership URLs.

The system exists to keep three separate ledgers perfectly consistent at all times: physical inventory (what is on the shelf versus reserved for an unfulfilled order), loyalty standing (points balances and the tier a member has earned from their trailing-year spend), and the money captured for each order. Many operations touch more than one of these ledgers at once — fulfilling an order draws down stock, settles loyalty points, mints running-shoe records, and advances a member's tier in a single motion, while approving a worn-shoe return unwinds several of those same effects. Because the store also schedules time-boxed appointments and group runs, the API carries a logical clock that test operators drive explicitly, and every temporal rule is evaluated against that clock rather than against wall-clock time.

The remainder of this document defines the global contracts every endpoint honours (Section 2), the domain workflows and their scattered business rules (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than self-registration must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or `X-User-Role` names a role the system does not recognise, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). The four recognised roles are `Member`, `Fitter`, `StoreManager`, and `Anonymous`.

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member — an order, a return, a subscription, a running shoe, a fitment session, or a training booking — compare that resource's member foreign key to `X-User-ID`. A member acting on a resource they do not own is rejected with `ERR_OWNERSHIP_FORBIDDEN` (HTTP 403).
- When `X-User-Role` is `Fitter`, `X-User-ID` is the `id` of the acting `Fitter`. Ownership checks on a resource that references a fitter — for example a fitment session being checked in or completed — compare the resource's `fitter_id` to `X-User-ID`, again yielding `ERR_OWNERSHIP_FORBIDDEN` on a mismatch.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A store manager is a superset operator: ownership checks never apply, and the manager may perform any member or fitter operation in addition to the manager-exclusive ones.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity. An anonymous caller may only self-register a new member and browse the public catalogue and public session listings.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a caller-supplied `limit` above the maximum is clamped to 100. `offset` defaults to 0 and has a minimum of 0. Every list is returned in ascending `created_at` order — oldest resource first — unless a workflow rule explicitly imposes a different ordering. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching resources before pagination), and `has_more` (true when unreturned matches remain beyond the current page).

### 2.4. Common Resource Properties, Versioning, and the Logical Clock

Every resource carries a server-minted `id` (a UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC values with three fractional digits. `version` begins at 1 when the resource is created and increments by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant on every such mutation. All ten entity types in this system — `Member`, `Product`, `Order`, `OrderLine`, `WearReturn`, `Subscription`, `RunningShoe`, `Fitter`, `FitmentSession`, `TrainingSession`, and `TrainingBooking` — carry the full set of common properties including `updated_at` and `version`.

The system keeps a **logical clock** that is the sole source of "now" for every temporal comparison in this specification. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any operator sets it the clock returns that default rather than the machine's wall-clock time. A store manager advances the clock by supplying a target instant as `to_iso8601`; the response reports the new value as `current_utc`. Appointment-in-the-past checks, the trailing-365-day spend window, and schedule-overlap checks are all evaluated against this clock.

### 2.5. Money, Rounding, and Pricing Precision

All monetary amounts are integer cents. Wherever a fractional cent arises — most commonly when a percentage discount is applied to a subtotal, or when per-line loyalty points are computed — the result is rounded half up (a value whose fractional part is exactly one-half rounds away from zero to the next whole unit). Discount percentages themselves are held as exact fractions (for example, 0.10 for a ten-percent discount) and are only converted to cents at the single, defined rounding point described in Section 3.3. Loyalty points are always whole integers.

### 2.6. Inventory Accounting Invariants

Each `Product` maintains two stored counters and two derived views. `stock_on_hand` is the number of physical units in inventory; `stock_reserved` is the number of units held against reserved-but-unfulfilled orders. From these, `available_units` is computed as `stock_on_hand` minus `stock_reserved`, and `availability` is `IN_STOCK` whenever `stock_on_hand` is greater than zero and `OUT_OF_STOCK` otherwise. These derived values are recomputed immediately after any change to either stored counter — on restock, on order reservation, on fulfillment, and on the release that accompanies a cancellation. The invariant the system preserves throughout is that reserving units never touches `stock_on_hand`, fulfilling units draws down both counters together, and cancelling a reserved order returns the reserved units without ever having removed them from hand.

### 2.7. Parallel Order State and Cascade Consistency

An `Order` carries two independent state dimensions that evolve separately. The **payment dimension**, `payment_status`, moves through `UNPAID`, `AUTHORIZED`, `PAID`, and the terminal `REFUNDED`. The **fulfillment dimension**, `fulfillment_status`, moves through `PENDING`, `RESERVED`, `FULFILLED`, and the terminal states `RETURNED` and `CANCELLED`. Neither dimension gates the other's transitions except where a workflow rule in Section 3 says so explicitly (for example, fulfillment requires the payment dimension to have reached `PAID`).

Several operations mutate more than one entity in a single motion; the system applies each cascade in full and atomically, bumping `version` and refreshing `updated_at` on every entity it touches. Two named cascades recur throughout Section 3 — **Cascade B**, fired when an order is fulfilled (drawing down stock, settling loyalty, minting running shoes, and crediting tier spend), and **Cascade A**, fired when a worn-shoe return is approved (flipping the order to returned/refunded and unwinding the loyalty and tier credit for the returned line). A third cascade governs training-group waitlist promotion. Each is specified in full in its home subsection.

### 2.8. Optimistic Concurrency Control on Price Overrides

Applying a manager price override to an order is guarded by optimistic concurrency control on the order's `version`. The override request must carry `expected_order_version`, which is the client's last-observed `version` of the target order. If `expected_order_version` does not equal the order's current `version` — because some other writer has advanced the order since the client read it — the override is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists precisely because a new override legitimately supersedes any prior one: without the version check, a second override issued against a stale reading would silently overwrite an intervening override the client never saw. No other endpoint takes a version field; only the price-override operation is version-guarded.

### 2.9. Validation Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed priority order and the first failure determines the returned error. The order is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401). This applies to every endpoint except member self-registration.
2. **Authorization** — the role is permitted to call this endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named in the path and then every foreign key in the body must resolve to an existing resource, validated left to right (path parameters first, then body references), else `ERR_NOT_FOUND` (404).
4. **Ownership** — an entity-backed caller (`Member` or `Fitter`) must own the targeted resource; a `StoreManager` is exempt. A violation is `ERR_OWNERSHIP_FORBIDDEN` (403).
5. **Body well-formedness** — required fields present, enum values valid, `quantity` at least 1, and `scheduled_end` strictly after `scheduled_start`, else `ERR_VALIDATION` (422). A `POST /orders` request that carries zero lines is rejected specifically with `ERR_EMPTY_ORDER` (422).
6. **State** — the target resource is in a state that permits the requested transition, else one of the state errors (`ERR_INVALID_STATE`, `ERR_ORDER_NOT_MODIFIABLE`, `ERR_RETURN_NOT_INSPECTABLE`, `ERR_PAYMENT_NOT_CAPTURED`, `ERR_SHOE_ALREADY_RETIRED`), all HTTP 409.
7. **Temporal** — appointment-in-the-past and schedule-overlap checks (Section 3.9), yielding `ERR_APPOINTMENT_IN_PAST` (422), `ERR_SCHEDULE_CONFLICT` (409), or `ERR_FITTER_UNAVAILABLE` (409).
8. **Cross-entity preconditions** — a training booking requires an active subscription (`ERR_SUBSCRIPTION_REQUIRED`, 409) and a return requires its order to be fulfilled (`ERR_ORDER_NOT_FULFILLED`, 409).
9. **Stock sufficiency** — reservation requires enough available units (`ERR_INSUFFICIENT_STOCK`, 409).
10. **Redemption fiscal rules** — sufficient points and a well-formed redemption amount (`ERR_INSUFFICIENT_POINTS`, 402; `ERR_REDEMPTION_EXCEEDS_CAP`, 422).
11. **Optimistic concurrency** — `expected_order_version` matches the order's current `version` on a price override (`ERR_STALE_VERSION`, 412).

Lower-numbered checks are decisive: a request that both fails authentication and would fail a state check returns `ERR_UNAUTHENTICATED`, never the state error.

### 2.10. Resource Retrieval and Reverse Reachability

Every resource is fetchable by its `id` through its collection, and the path is validated left to right — a nonexistent identifier anywhere in the path yields `ERR_NOT_FOUND` before any body is inspected. Because the topology is flat, child and cross-aggregate resources are reached through list endpoints filtered by foreign key rather than through nested URLs: order lines are listed by `order_id` and/or `product_id`; orders, subscriptions, running shoes, returns, fitment sessions, and training bookings are each listable filtered by `member_id` (and, where relevant, by `product_id`, `source_order_id`, `fitter_id`, `recommended_product_id`, or `session_id`); products may be filtered by `category`; and training sessions may be filtered by `fitter_id`. All such lists obey the pagination and `created_at` ordering rules of Sections 2.3.

## 3. Business Logic & Workflows

### 3.1. Membership, Loyalty Points, and Tier Standing

A new customer is created by self-registration or by a store manager, supplying `email` (the unique contact address), `full_name`, and a two-letter `state_code`. A freshly created `Member` begins with `status` `ACTIVE` (the alternative being `SUSPENDED`), a `loyalty_points_balance` of zero, a `tier_qualifying_spend_cents` of zero, and a `loyalty_tier` of `STANDARD`.

The **loyalty points balance** is a live count of redeemable points. It is increased when an order is fulfilled (points are earned and settled), decreased when a member redeems points against an order, restored when a redemption is reversed by cancellation, reduced when a return reverses previously earned points, and adjusted up or down when a manager records a manual correction. A manager adjustment supplies `points_delta` (which may be negative) and a `reason`; the delta is added to the balance, and the balance is floored at zero so it can never go negative. The endpoint returns the member with the new balance.

**Tier-qualifying spend** accumulates the `net_paid_cents` of every order this member has had fulfilled within the trailing 365 days of the logical clock, and is reduced when a return is approved. A member's `loyalty_tier` is derived from that running total: the tier is `GOLD` when `tier_qualifying_spend_cents` is at least 150000 cents, otherwise `SILVER` when it is at least 50000 cents, otherwise `STANDARD`. Comparisons are exact and inclusive at each boundary. The tier is recomputed every time `tier_qualifying_spend_cents` changes — both when fulfillment credits it and when a return debits it.

### 3.2. Catalog, Stock, and Inventory Accounting

A store manager creates a catalog `Product` with a unique `sku`, a display `name`, a `category` (`SHOE`, `NUTRITION`, `GEAR`, or `APPAREL`), and a `unit_price_cents` that must be zero or greater. For a shoe, `mileage_life_miles` records the recommended retirement mileage and defaults to 500 when omitted; it is meaningless for non-shoe categories. The manager may seed inventory at creation with `initial_stock`, which sets `stock_on_hand` (defaulting to zero); `stock_reserved` starts at zero and `availability` is computed immediately.

Restocking adds a supplied `quantity` to `stock_on_hand` and recomputes `availability`. As described in Section 2.6, `available_units` and `availability` are always kept consistent with the two stored counters. The public may browse the catalog and fetch individual products; managing the catalog and its stock is manager-only.

### 3.3. Placing an Order and Provisional Pricing

A member (or a manager acting on their behalf) places an order by supplying the buyer's `member_id`, a non-empty list of `lines`, and an optional `promo_code`. Each entry in `lines` names a `product_id` and a `quantity` of at least one. An order with no lines is rejected with `ERR_EMPTY_ORDER`. On creation the system creates one `OrderLine` per entry, stamping each line's `order_id`, snapshotting the product's price into the line's `unit_price_cents`, and setting `is_returned` to false. A line's `line_gross_cents` is its snapshot `unit_price_cents` multiplied by its `quantity`.

**Provisional pricing** is computed at creation and written to `provisional_total_cents`. First, `subtotal_cents` is the sum, over every line, of that line's `unit_price_cents` times its `quantity`. Next comes the **effective discount** (`discount_pct_applied`), assembled from up to three sources:

- A subscription component: if the member holds an `ACTIVE` subscription, the plan grants 0.05 for `BASIC`, 0.10 for `PLUS`, or 0.15 for `ELITE`; with no active subscription this component is zero.
- A loyalty component keyed on the member's current tier: 0.00 for `STANDARD`, 0.05 for `SILVER`, 0.10 for `GOLD`.
- A promotional component: if `promo_code` is present and recognised, `WELCOME10` grants 0.10 and `SPRING15` grants 0.15; an absent or unrecognised code contributes zero.

The subscription and loyalty components are added together to form a member base, and that base is capped at 0.12 — the member stack may never exceed twelve percent. The promotional component is then considered separately: only if the promotional component is greater than zero **and** `subtotal_cents` is at least 5000 cents is the promo added on top of the capped member stack, with the combined result capped at a hard ceiling of 0.20. If the promo does not qualify (no promo, unrecognised code, or a subtotal below 5000 cents), `discount_pct_applied` is simply the capped member stack.

With the discount fraction fixed, `discount_cents` is computed as `subtotal_cents` multiplied by `discount_pct_applied`, rounded half up to whole cents at this single point — unless a manager price override is in force, in which case `discount_cents` is replaced by the override amount (Section 3.4). Then `subtotal_after_discount` is `subtotal_cents` minus `discount_cents`. Shipping is decided on that intermediate figure, not on the final total: `shipping_fee_cents` is zero when `subtotal_after_discount` is at least 7500 cents, and 599 cents otherwise. Redemption is valued at one cent per point, so `redemption_cents` is `redeemed_points` times one. The order total is `subtotal_after_discount` minus `redemption_cents` plus `shipping_fee_cents`, evaluated strictly in that order: subtotal, then discount, then subtotal-after-discount, then shipping keyed on subtotal-after-discount, then subtract redemption, then add shipping to reach the total.

In the **provisional** variant written at creation, `redeemed_points` is treated as zero (no redemption has yet been applied) and the discount uses the member's tier and subscription as they stand at creation. Order creation also projects **estimated loyalty points** (`estimated_points_earned`). Points are computed per line and then summed — never by summing dollars and rounding once. For each line, take its `unit_price_cents` times `quantity`, divide by 100 to get dollars, multiply by 10 points per dollar, multiply by the member's tier multiplier (1.0 for `STANDARD`, 1.25 for `SILVER`, 1.5 for `GOLD`), and round that line result half up to a whole number; store it as the line's `line_points_earned`. The estimate sums the rounded per-line figures across every line, using the tier as of creation.

### 3.4. Payment, Redemption, Fulfillment, and Cancellation

An order's money and inventory advance through a sequence of operator actions. All of these leave the two order dimensions independent except where noted.

**Redemption.** Before payment, a member may apply loyalty points to the order, supplying `points_to_redeem`. Redemption is only permitted while `payment_status` is `UNPAID`; attempting it on an order past that point yields `ERR_ORDER_NOT_MODIFIABLE`. The fiscal rules are: the member must hold at least `points_to_redeem` in `loyalty_points_balance`, or the request fails with `ERR_INSUFFICIENT_POINTS`; and the amount must be a whole multiple of 100 whose cent value does not exceed half of `subtotal_after_discount`, or the request fails with `ERR_REDEMPTION_EXCEEDS_CAP`. On success, `redeemed_points` is set to `points_to_redeem`, `redemption_cents` is recomputed, and the member's `loyalty_points_balance` is debited by `points_to_redeem` immediately — the points leave the balance at redemption time, not at payment.

**Authorization and capture.** Authorizing payment moves `payment_status` from `UNPAID` to `AUTHORIZED`. Capturing payment moves it from `AUTHORIZED` to `PAID`; at capture the order's total is recomputed in the **final** variant and written to both `final_total_cents` and `net_paid_cents`. The final variant differs from the provisional one in two ways: the redemption actually applied is now included, and the discount is recomputed against the member's tier and subscription as they stand at that moment, which may differ from creation. (The redemption debit already occurred at redemption time, so capture makes no further balance change.)

**Fulfillment and Cascade B.** Reserving an order moves `fulfillment_status` from `PENDING` to `RESERVED`. Reservation requires, for every line, that the product's `available_units` be at least that line's `quantity`; otherwise the reservation fails with `ERR_INSUFFICIENT_STOCK`. On success each line's product has its `stock_reserved` increased by the line quantity. Fulfilling an order then moves `fulfillment_status` from `RESERVED` to `FULFILLED`, but only if `payment_status` has already reached `PAID`; a fulfill attempt on an unpaid order fails with `ERR_PAYMENT_NOT_CAPTURED`. Fulfillment fires **Cascade B** in full: for every line, the product's `stock_reserved` and `stock_on_hand` are both reduced by the line quantity; any product whose `stock_on_hand` thereby reaches zero has its `availability` recomputed to `OUT_OF_STOCK`; the order's `final_total_cents` is recomputed in the final variant; settled loyalty points are computed and added to the member's `loyalty_points_balance` with each line's `line_points_earned` recorded; for every shoe line, one `RunningShoe` is created per unit (see Section 3.6); and the member's `tier_qualifying_spend_cents` is increased by the order's `net_paid_cents`, after which the member's `loyalty_tier` is recomputed. The **settled** points variant differs from the estimate in that it includes only lines that are not returned and uses the tier as of fulfillment; once a return is later approved, the returned line's points are reversed, so the net earned diverges from the original estimate.

**Price override.** A store manager may replace an order's computed discount with a fixed amount by supplying `override_discount_cents`, which is stored as the order's `price_override_discount_cents` and, while set, takes the place of the normally computed `discount_cents` in every subsequent repricing. Each override supersedes any prior one, and the operation increments the order's `version` by one. Because a fresh override would otherwise silently overwrite an intervening one, the request must carry `expected_order_version` and is subject to the stale-version guard of Section 2.8.

**Cancellation.** A member may cancel an order while its `fulfillment_status` is either `PENDING` or `RESERVED`, which moves it to the terminal `CANCELLED`. If the order was `RESERVED`, every line's product has its `stock_reserved` reduced by the line quantity, releasing the held units so `available_units` is restored. If the order carried a redemption (`redeemed_points` greater than zero), those points are returned to the member's `loyalty_points_balance` as a redeem reversal. And if `payment_status` was `AUTHORIZED` or `PAID`, it cascades to the terminal `REFUNDED`; on a full cancel of a paid order, `net_paid_cents` is set to zero.

### 3.5. The Wear/Return Lifecycle

Running-Fit's wear/return policy lets a member send back a worn shoe. A return is opened against a single `order_line_id`, with a customer-stated `reason` and an optional `wear_days` recording how long the shoe was worn as wear-test evidence. A return may only be opened when the line's order is `FULFILLED`; otherwise it is rejected with `ERR_ORDER_NOT_FULFILLED`. On creation the `WearReturn` enters status `REQUESTED` and its `member_id` is copied from the order that owns the line.

The return then follows a non-linear lifecycle. A manager begins inspection, moving `REQUESTED` to `UNDER_INSPECTION`. From `UNDER_INSPECTION` the manager either approves the return (to the terminal `APPROVED`) or rejects it (to `REJECTED`), recording `inspection_notes`; a rejection has no order, inventory, or loyalty effect of its own. A rejected return is not the end of the road: the member may resubmit it, reverting `REJECTED` back to `REQUESTED` for a fresh inspection, or may withdraw it to the terminal `WITHDRAWN`. A member may also withdraw a return directly from `REQUESTED`. Attempting to start inspection, approve, or reject a return that is not in the state that transition requires yields `ERR_RETURN_NOT_INSPECTABLE`; other out-of-state transitions on a return yield `ERR_INVALID_STATE`.

**Approval fires Cascade A** in full. First, the `WearReturn` becomes `APPROVED` and the underlying `OrderLine` has `is_returned` set to true. Second, the order linked through that line (reached via the line's `order_id`) has its `fulfillment_status` moved to the terminal `RETURNED` and its `payment_status` moved to `REFUNDED`, and its `net_paid_cents` is reduced by the net amount attributable to the returned line. Third, the member's `loyalty_points_balance` is reduced by that returned line's `line_points_earned`, reversing the points that line originally earned. Fourth, the member's `tier_qualifying_spend_cents` is reduced by the same returned-line net, and the member's `loyalty_tier` is recomputed against the new total.

### 3.6. Shoe Rotation and Mileage Reminders

When an order containing shoe lines is fulfilled, the system mints a `RunningShoe` for each shoe unit purchased, so a member can track each physical pair in their rotation. Each new shoe records the buyer's `member_id`, the model's `product_id`, and the `source_order_id` of the fulfilling order; it snapshots the product's `mileage_life_miles` into `retirement_threshold_miles`; it starts with `total_mileage_miles` at zero and `status` `ACTIVE`.

As the member runs, they log miles on a shoe by supplying `miles`, which is added to `total_mileage_miles`. If the shoe is `ACTIVE` and its cumulative `total_mileage_miles` reaches or exceeds its `retirement_threshold_miles` — the boundary is inclusive — the shoe automatically moves to `RETIREMENT_DUE`, raising the mileage reminder that tells the runner it is time to rotate in a new pair. A member may retire a shoe outright, moving it from either `ACTIVE` or `RETIREMENT_DUE` to the terminal `RETIRED`. Logging mileage against, or retiring, an already-`RETIRED` shoe is rejected with `ERR_SHOE_ALREADY_RETIRED`.

### 3.7. Club Subscriptions

A member joins the club by creating a `Subscription` with a chosen `plan` (`BASIC`, `PLUS`, or `ELITE`), which starts `ACTIVE`. The plan sets the subscription's `discount_pct` — the store discount the plan grants — but that discount only counts toward order pricing while the subscription is `ACTIVE`.

A manager may mark an active subscription `PAST_DUE`, at which point its discount effectively drops to zero and it no longer discounts the member's orders. A past-due subscription can be reactivated by the member back to `ACTIVE` once dues are paid, or either an active or a past-due subscription may be cancelled by the member to the terminal `CANCELLED`. Requesting a transition from a state that does not allow it — reactivating an active subscription, for instance — yields `ERR_INVALID_STATE`.

### 3.8. Fitment Appointments

A fitter is store staff created by a manager with a `full_name`; a new fitter begins with `is_active` set to true, meaning they take appointments. A member books a gait-analysis fitment by supplying their `member_id`, the chosen `fitter_id`, and a `scheduled_start` and `scheduled_end`; the end must be strictly after the start. The appointment is created `SCHEDULED`. Three temporal guards apply at booking, all evaluated against the logical clock. If `scheduled_start` is before the current clock, the booking is rejected with `ERR_APPOINTMENT_IN_PAST`. If the same member already holds an overlapping fitment or training commitment, it is rejected with `ERR_SCHEDULE_CONFLICT`; member overlap uses half-open interval semantics, so two windows that merely touch end-to-start do not conflict. If the chosen fitter is already committed within a 15-minute service buffer of the requested window — that is, the gap between this window and any of the fitter's other sessions is less than 15 minutes on either side — it is rejected with `ERR_FITTER_UNAVAILABLE`.

Once scheduled, a fitter checks the member in, moving `SCHEDULED` to `CHECKED_IN`. The fitter then completes the session, moving `CHECKED_IN` to `COMPLETED` and recording the gait-analysis outcome: an optional `recommended_product_id` (the shoe the fitter recommends) and free-text `notes`. A session may also be cancelled to the terminal `CANCELLED` — by the member while it is still `SCHEDULED`, or by the fitter while it is `CHECKED_IN` — and cancelling a scheduled session frees the fitter's time slot so it no longer counts toward fitter-overlap checks. `NO_SHOW` is a further terminal status a session may carry. Out-of-state transitions on a session yield `ERR_INVALID_STATE`.

### 3.9. Training Groups and the Waitlist

A fitter or manager creates a group-run `TrainingSession` with a `title`, a `start_time` and `end_time` (end strictly after start), a `capacity` of at least one, and an optional `fitter_id` for the coach leading it. The session tracks `booked_count` — the number of its bookings currently in `BOOKED` status — and `available_slots`, computed as `capacity` minus `booked_count`.

A member books into a session by supplying the `session_id` and their `member_id`. Two preconditions gate the booking: the member must hold an `ACTIVE` subscription, or the request fails with `ERR_SUBSCRIPTION_REQUIRED`; and the booking must not overlap the member's own existing schedule, or it fails with `ERR_SCHEDULE_CONFLICT` under the same half-open semantics as fitment. A full session is **not** an error — when `available_slots` is greater than zero the booking is created `BOOKED` and the session's `booked_count` rises, but when the session is full the booking is instead created `WAITLISTED`. While a booking is `WAITLISTED` it carries a `waitlist_position` reflecting its place in line, ordered by `created_at` ascending (never by id); a `BOOKED` booking has no waitlist position.

Cancelling a booking moves it to the terminal `CANCELLED` from either `BOOKED` or `WAITLISTED`. When a `BOOKED` booking is cancelled a slot frees, firing the waitlist cascade: the session's `booked_count` is reduced by one, and the earliest `WAITLISTED` booking on that session — the one with the smallest `created_at` — is promoted from `WAITLISTED` to `BOOKED`, which raises `booked_count` back by one and clears that booking's `waitlist_position`. When a `WAITLISTED` booking is cancelled instead, no slot frees (it held none), and the remaining waitlist positions recompute. A fitter marks a `BOOKED` booking `ATTENDED` after the run. A `BOOKED` booking that is never attended is moved by the system to `NO_SHOW` after the session ends. Cancelling or attending a booking that is not in the required state yields `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; all other successful operations, including state transitions and mutations, return HTTP 200 with the affected resource. Request bodies, response bodies, and side effects for each endpoint are described in the Section 3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock | StoreManager |
| POST | `/members` | Register a new member | Anonymous, StoreManager |
| GET | `/members/{memberId}` | Fetch a member | Member, Fitter, StoreManager |
| POST | `/members/{memberId}/loyalty-adjustments` | Grant or deduct loyalty points | StoreManager |
| POST | `/products` | Create a catalog product | StoreManager |
| GET | `/products/{productId}` | Fetch a product | Anonymous, Member, Fitter, StoreManager |
| GET | `/products` | List products (filter by category) | Anonymous, Member, Fitter, StoreManager |
| POST | `/products/{productId}/restock` | Add units to stock on hand | StoreManager |
| POST | `/orders` | Create an order with provisional pricing | Member, StoreManager |
| GET | `/orders/{orderId}` | Fetch an order | Member, StoreManager |
| GET | `/orders` | List orders (filter by member_id) | Member, StoreManager |
| POST | `/orders/{orderId}/apply-redemption` | Apply loyalty points to an unpaid order | Member, StoreManager |
| POST | `/orders/{orderId}/authorize-payment` | Authorize payment | Member, StoreManager |
| POST | `/orders/{orderId}/capture-payment` | Capture payment; compute final total | Member, StoreManager |
| POST | `/orders/{orderId}/reserve` | Reserve inventory | Member, StoreManager |
| POST | `/orders/{orderId}/fulfill` | Fulfill a reserved, paid order (Cascade B) | StoreManager |
| POST | `/orders/{orderId}/cancel` | Cancel an order; release and reverse | Member, StoreManager |
| POST | `/orders/{orderId}/price-overrides` | Apply a manager discount override (OCC-guarded) | StoreManager |
| GET | `/order-lines/{lineId}` | Fetch a single order line | Member, StoreManager |
| GET | `/order-lines` | List order lines (filter by order_id, product_id) | Member, StoreManager |
| POST | `/returns` | Open a wear/return request | Member, StoreManager |
| GET | `/returns/{returnId}` | Fetch a return | Member, StoreManager |
| GET | `/returns` | List returns (filter by order_line_id, member_id) | Member, StoreManager |
| POST | `/returns/{returnId}/start-inspection` | Begin inspection | StoreManager |
| POST | `/returns/{returnId}/approve` | Approve a return (Cascade A) | StoreManager |
| POST | `/returns/{returnId}/reject` | Reject a return | StoreManager |
| POST | `/returns/{returnId}/resubmit` | Resubmit a rejected return | Member, StoreManager |
| POST | `/returns/{returnId}/withdraw` | Withdraw a return | Member, StoreManager |
| POST | `/subscriptions` | Create a club subscription | Member, StoreManager |
| GET | `/subscriptions/{subscriptionId}` | Fetch a subscription | Member, StoreManager |
| GET | `/subscriptions` | List subscriptions (filter by member_id) | Member, StoreManager |
| POST | `/subscriptions/{subscriptionId}/mark-past-due` | Mark subscription past-due | StoreManager |
| POST | `/subscriptions/{subscriptionId}/reactivate` | Reactivate a past-due subscription | Member, StoreManager |
| POST | `/subscriptions/{subscriptionId}/cancel` | Cancel a subscription | Member, StoreManager |
| GET | `/running-shoes/{shoeId}` | Fetch a running shoe | Member, StoreManager |
| GET | `/running-shoes` | List running shoes (filter by member_id, product_id, source_order_id) | Member, StoreManager |
| POST | `/running-shoes/{shoeId}/log-mileage` | Log miles run; may trigger retirement-due | Member, StoreManager |
| POST | `/running-shoes/{shoeId}/retire` | Retire a shoe | Member, StoreManager |
| POST | `/fitters` | Create a fitter | StoreManager |
| GET | `/fitters/{fitterId}` | Fetch a fitter | Anonymous, Member, Fitter, StoreManager |
| POST | `/fitment-sessions` | Book a gait-analysis fitment appointment | Member, StoreManager |
| GET | `/fitment-sessions/{sessionId}` | Fetch a fitment session | Member, Fitter, StoreManager |
| GET | `/fitment-sessions` | List fitment sessions (filter by member_id, fitter_id, recommended_product_id) | Member, Fitter, StoreManager |
| POST | `/fitment-sessions/{sessionId}/check-in` | Check the member in | Fitter, StoreManager |
| POST | `/fitment-sessions/{sessionId}/complete` | Complete the session; record recommendation | Fitter, StoreManager |
| POST | `/fitment-sessions/{sessionId}/cancel` | Cancel a fitment session | Member, Fitter, StoreManager |
| POST | `/training-sessions` | Create a training-group session | Fitter, StoreManager |
| GET | `/training-sessions/{sessionId}` | Fetch a training session | Anonymous, Member, Fitter, StoreManager |
| GET | `/training-sessions` | List training sessions (filter by fitter_id) | Anonymous, Member, Fitter, StoreManager |
| POST | `/training-bookings` | Book a member into a training session | Member, StoreManager |
| GET | `/training-bookings/{bookingId}` | Fetch a training booking | Member, Fitter, StoreManager |
| GET | `/training-bookings` | List training bookings (filter by session_id, member_id) | Member, Fitter, StoreManager |
| POST | `/training-bookings/{bookingId}/cancel` | Cancel a booking; promote waitlist | Member, StoreManager |
| POST | `/training-bookings/{bookingId}/mark-attended` | Mark a booking attended | Fitter, StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_OWNERSHIP_FORBIDDEN | 403 |
| ERR_VALIDATION | 422 |
| ERR_EMPTY_ORDER | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_NOT_MODIFIABLE | 409 |
| ERR_PAYMENT_NOT_CAPTURED | 409 |
| ERR_ORDER_NOT_FULFILLED | 409 |
| ERR_RETURN_NOT_INSPECTABLE | 409 |
| ERR_SHOE_ALREADY_RETIRED | 409 |
| ERR_SCHEDULE_CONFLICT | 409 |
| ERR_FITTER_UNAVAILABLE | 409 |
| ERR_APPOINTMENT_IN_PAST | 422 |
| ERR_SUBSCRIPTION_REQUIRED | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_POINTS | 402 |
| ERR_REDEMPTION_EXCEEDS_CAP | 422 |
| ERR_STALE_VERSION | 412 |
