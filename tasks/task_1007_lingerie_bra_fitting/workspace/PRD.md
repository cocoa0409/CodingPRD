# Lingerie & Bra-Fitting Boutique API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Lingerie & Bra-Fitting Boutique API, a back-of-house platform that unifies the two halves of a specialty intimates business: the consultative fitting studio and the retail sales floor. On the studio side, the system schedules private and standard fitting appointments across a roster of fitters and rooms, records body measurements, and derives a recommended bra size from those measurements. On the retail side, it manages a band-and-cup SKU matrix, reserves and decrements inventory, prices orders, awards loyalty, and handles the after-sale flows that are unique to intimate apparel — hygiene-restricted exchanges, post-mastectomy insurance reimbursement, and periodic replacement reminders.

The domain carries obligations that ordinary retail does not. Post-surgical and mastectomy fittings must be conducted by certified fitters in private rooms; certain products can never be returned once unsealed; and mastectomy purchases may be partially reimbursable through insurance. The API is therefore designed around strict, ordered validation, conserved inventory accounting, and precise monetary and loyalty arithmetic, so that every downstream consumer — booking front-end, point-of-sale, and billing back office — observes one consistent source of truth.

All resources are exposed as peer collections mounted under the `/boutique` prefix. A separate administrative logical clock supports deterministic, time-dependent testing of the temporal rules (exchange windows and reminder due dates) described throughout this document.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as `Customer`, `Fitter`, `StoreManager`, and `BillingClerk`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two roles are entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership rule guards a `Customer`'s own appointments, orders, exchanges, and reminders. When `X-User-Role` is `Fitter`, `X-User-ID` is the `id` of the acting `Fitter`; it identifies which fitter is conducting the appointment lifecycle actions.

The other two roles are opaque operators. When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: a `StoreManager` administers the catalog, inventory, fulfillment, exchanges, reminders, loyalty adjustments, and the logical clock, and the server does not compare that identifier to any entity's `id`. Likewise, when `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier used for payments, insurance claims, and reimbursements, again never compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties, Versioning, and Optimistic Concurrency

Every primary resource — `Customer`, `Fitter`, `FittingRoom`, `FittingAppointment`, `Product`, `SKU`, `Order`, `OrderLine`, `Exchange`, `InsuranceClaim`, and `ReplacementReminder` — carries four system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits set once at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 and increments by one on every mutation of the resource; it underpins optimistic concurrency control.

`LoyaltyEvent` is the sole exception. It is an append-only ledger row and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because a ledger entry is never modified after it is written.

Optimistic concurrency control applies to exactly one write: submitting a fit (measurements plus recommendation) against a `FittingAppointment`. Because a re-fit legitimately supersedes a prior recommendation, this action is a self-transition that increments the appointment's `version` by one each time it runs. To prevent a client from overwriting a recommendation it never observed, the fit-submission request must carry `expected_appointment_version` holding the client's last observed `version` of the target `FittingAppointment`. If `expected_appointment_version` does not equal the appointment's current `version` — because another re-fit has already advanced it — the submission is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412). No other endpoint requires or accepts a version field.

### 2.5. Monetary Amounts, Loyalty Points, and Rounding

All monetary amounts in the system are stored and returned as integer cents; there are no fractional-cent values in any response. Wherever a rule multiplies a cents amount by a percentage — line-level loyalty discounts and insurance coverage — the product is rounded to a whole number of cents using the round-half-up method (a value ending in exactly half a cent rounds up). Loyalty point balances and per-order point figures are always whole integers; where a division produces a fractional result, the fractional part is discarded by taking the floor.

A caution that governs order totals specifically: when several lines each receive a percentage discount, each line's discount is rounded to whole cents first, and only then are the rounded per-line discounts summed. Summing the raw discounts and rounding once at the end is not permitted, because it can differ from the per-line result by a cent.

### 2.6. Inventory Conservation: Reservation, Availability, and Stock Status

Each `SKU` tracks physical inventory in `stock_on_hand` and exposes two derived quantities. `reserved_count` is the total `quantity` summed across every `OrderLine` for that SKU that is in `ACTIVE` status, is not a special-order line (`is_special_order` is false), and belongs to an `Order` whose `fulfillment_status` is `PLACED`. `available_units` is `stock_on_hand` minus `reserved_count` and is the conserved quantity the boutique may still promise to new orders. These derived values are recomputed immediately after any event that changes physical stock or reservations — placement, cancellation, fulfillment, restock, and exchange restock.

From `available_units` the system derives `stock_status`, one of `IN_STOCK`, `LOW_STOCK`, or `OUT_OF_STOCK`. When `available_units` is zero or below, `stock_status` is `OUT_OF_STOCK`. When `available_units` is greater than zero but no greater than the low-stock threshold of 3 units, `stock_status` is `LOW_STOCK`. When `available_units` is greater than 3, `stock_status` is `IN_STOCK`. The boundaries are exact: `available_units` of precisely 3 is `LOW_STOCK`, and `available_units` of precisely 0 is `OUT_OF_STOCK`.

### 2.7. Scheduling Windows and Interval Semantics

Two distinct interval rules protect the fitting studio at confirm time, and they do not share semantics.

The first is fitter double-booking. Each appointment occupies a half-open interval that begins at its `scheduled_start` and ends at its `scheduled_end` extended by a turnover buffer of 15 minutes. A candidate appointment conflicts with an existing `CONFIRMED` or `CHECKED_IN` appointment on the same `fitter_id` when the candidate's buffered interval and the existing buffered interval overlap — that is, when the candidate's start is strictly before the existing interval's buffered end and the existing interval's start is strictly before the candidate's buffered end. Because the intervals are half-open, two appointments that merely touch at exactly the buffer boundary do not overlap. A conflict is rejected with `ERR_FITTER_DOUBLE_BOOKED`.

The second is room capacity. A room's overlap check uses no buffer and plain half-open intervals over `scheduled_start` and `scheduled_end`. The system counts existing `CONFIRMED` or `CHECKED_IN` appointments on the same `room_id` whose interval overlaps the candidate's interval (each existing start strictly before the candidate's end, and the candidate's start strictly before that existing end). If that count is greater than or equal to the room's `capacity`, the confirmation is rejected with `ERR_ROOM_AT_CAPACITY`; capacity is honored only while the count stays strictly below it.

### 2.8. The Logical Clock and Time-Bounded Actions

The server maintains a logical clock that is the authoritative "now" for every temporal comparison in this document — exchange-window eligibility, reminder due dates, and the `fulfilled_at` stamp. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any client sets it the clock holds that default and never falls back to wall-clock time. A `StoreManager` may advance the clock by supplying a target instant in the `to_iso8601` field; the clock capability returns the new value as `current_utc`. All time-bounded rules read the logical clock, so tests can move time deterministically.

### 2.9. Validation Ordering and Nested Resource Resolution

When a single request could fail several checks, the system evaluates them in a fixed priority order so that the reported `error_id` is deterministic. Authentication comes first: absent or malformed headers yield `ERR_UNAUTHENTICATED`. Role authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Third is existence — every resource id named in the path, and every foreign-key id in the body, must resolve to a real resource; path ids are validated left to right, and the first unresolved id determines which not-found error is returned (`ERR_CUSTOMER_NOT_FOUND`, `ERR_FITTER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_EXCHANGE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_REMINDER_NOT_FOUND`). Fourth is ownership: a `Customer` acting on a resource whose `customer_id` is not their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`.

Fifth is body well-formedness — required fields present, enum values legal, and numeric ranges honored — reported as `ERR_VALIDATION`. Sixth, specific to fit submission, is the measurement-range check reported as `ERR_MEASUREMENT_OUT_OF_RANGE`. Seventh is the state check: the target must be in a state legal for the requested transition, reported through the state family `ERR_INVALID_STATE`, `ERR_LINE_NOT_EXCHANGEABLE_STATE`, `ERR_ORDER_NOT_PLACED`, `ERR_ORDER_NOT_PAID`, `ERR_ORDER_NOT_CANCELLABLE`, `ERR_EMPTY_ORDER`, `ERR_FIT_NOT_SUBMITTED`, or `ERR_NOTHING_TO_REIMBURSE`. Eighth is the optimistic-concurrency check on re-fit, `ERR_STALE_APPOINTMENT_VERSION`. Ninth are business-safety checks (`ERR_FITTER_NOT_CERTIFIED`, `ERR_ROOM_NOT_PRIVATE`, `ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE`). Tenth are scheduling-conflict checks (`ERR_FITTER_DOUBLE_BOOKED`, `ERR_ROOM_AT_CAPACITY`). Eleventh are temporal-window checks (`ERR_EXCHANGE_WINDOW_EXPIRED`, `ERR_REMINDER_NOT_DUE`). Twelfth are referential checks (`ERR_SKU_INACTIVE`, `ERR_NOT_MASTECTOMY_ORDER`). Thirteenth, and last, is the fiscal inventory check (`ERR_INSUFFICIENT_STOCK`). Where a lower-priority failure and a higher-priority failure coexist, the higher-priority error is the one returned.

### 2.10. State Consistency and Cascading Side Effects

Several operations mutate more than one resource in a single, immediate transaction, and the API guarantees all such effects land together. When an order is cancelled, each of its `ACTIVE` lines is cancelled and every released reservation is reflected in the affected SKUs' recomputed `reserved_count`, `available_units`, and `stock_status`. When an exchange is approved, the affected line, SKU inventory, customer balances, loyalty ledger, and any scheduled reminder for that line are all updated in one step. Every resource touched by such a cascade has its own `updated_at` refreshed and its `version` incremented as part of that mutation. States are referenced throughout by their exact uppercase spellings, and the specific cascades are detailed in the workflows of Section 3.

## 3. Business Logic & Workflows

### 3.1. Boutique Setup: Staff, Rooms, and the Product Catalog

A `StoreManager` seeds the boutique. Registering a `Customer` supplies a `full_name`, a unique `email`, and optionally a `phone`; a `post_mastectomy_flag` may be set to mark the client as a post-mastectomy customer, which is purely informational and does not by itself grant insurance eligibility. A new customer opens with `loyalty_points` of 0, `store_credit_cents` of 0, and a `loyalty_tier` of `BRONZE`. The `loyalty_tier` is always derived from the running `loyalty_points` balance and takes one of the values `BRONZE`, `SILVER`, or `GOLD`: a balance below 1000 points is `BRONZE`, a balance of 1000 points or more (but below 5000) is `SILVER`, and a balance of 5000 points or more is `GOLD` (both thresholds are inclusive lower bounds, so exactly 1000 is `SILVER` and exactly 5000 is `GOLD`). That `loyalty_points` balance is itself the sum of every `points_delta` recorded for the customer across all loyalty ledger entries.

Fitters are registered with a `full_name`, an optional `post_surgical_certified` flag (default false) that records whether the fitter holds post-surgical and mastectomy certification, and an optional `is_active` flag (default true); an inactive fitter cannot be assigned to a confirmed appointment. Fitting rooms are registered with a `room_name`, a `capacity` of at least 1 that bounds how many overlapping confirmed appointments the room admits, an optional `is_private` flag (default false), and an optional `is_active` flag (default true); an inactive room cannot be booked.

The catalog is a two-level structure. A `Product` is created with a `style_name`, a `brand`, a `category` drawn from `EVERYDAY_BRA`, `SPORTS_BRA`, `MASTECTOMY_BRA`, or `LINGERIE_SET`, a `base_price_cents` of zero or more, an optional `hygiene_class` of either `STANDARD_RETURNABLE` (the default) or `INTIMATE_NON_RETURNABLE`, and an optional `is_active` flag (default true) — an inactive product accepts no new order lines. The system computes `is_mastectomy` as true exactly when `category` equals `MASTECTOMY_BRA`; this flag gates insurance eligibility later.

Each cell of a product's band-and-cup matrix is a `SKU`, created against a `product_id` with an even-integer `band_size` in the range 28 to 44, a `cup_size` letter, a unique `sku_code`, an optional starting quantity `initial_stock`, and an optional `is_active` flag (default true); an inactive SKU rejects new standard order lines. The cup letter is one of `AA`, `A`, `B`, `C`, `D`, `E`, `F`, `G`, or `H`. On creation the SKU's `stock_on_hand` is set from `initial_stock`, its `reserved_count`, `available_units`, and `stock_status` are computed, and its `price_cents` is derived: the price is the parent product's `base_price_cents` plus an extended-size surcharge of 500 cents whenever the SKU is an extended size, and plus nothing otherwise. A SKU counts as an extended size when its `band_size` is 40 or greater, or when its cup letter is `F` or larger (that is, `F`, `G`, or `H`). A `StoreManager` adds physical units later by restocking with a `quantity`, which increases `stock_on_hand` by that amount and recomputes `available_units` and `stock_status`.

A `StoreManager` may also post a direct loyalty adjustment for a customer, supplying a signed `points_delta` and a `reason` drawn from `ORDER_EARN`, `ORDER_REVERSAL`, `FINAL_ADJUSTMENT`, `EXCHANGE_REVERSAL`, `PROMOTION`, or `CORRECTION`. Each adjustment appends a `LoyaltyEvent` — which may also record the originating `order_id` when applicable — adds `points_delta` to the customer's `loyalty_points`, and recomputes `loyalty_tier`.

### 3.2. The Fitting Appointment Lifecycle and Size Recommendation

A `Customer` (or a `StoreManager` acting on their behalf) books a fitting by supplying `customer_id`, `fitter_id`, `room_id`, a `fitting_type` of `STANDARD`, `POST_SURGICAL`, or `MASTECTOMY`, a `scheduled_start` instant, and an optional `duration_minutes` (default 30). The appointment is created in `REQUESTED` status, and the system computes `scheduled_end` as `scheduled_start` advanced by `duration_minutes`.

Confirmation, performed by the assigned `Fitter`, advances the appointment `REQUESTED → CONFIRMED` and locks the fitter, room, and time slot. Confirmation runs a battery of guards. The assigned fitter must have `is_active` true and the room must have `is_active` true. When `fitting_type` is `POST_SURGICAL` or `MASTECTOMY`, the fitter must have `post_surgical_certified` true, or the request is rejected with `ERR_FITTER_NOT_CERTIFIED`; and the room must have `is_private` true, or the request is rejected with `ERR_ROOM_NOT_PRIVATE`. The fitter buffered-overlap rule (Section 2.7) then guards against `ERR_FITTER_DOUBLE_BOOKED`, and the room aggregate-capacity rule guards against `ERR_ROOM_AT_CAPACITY`.

Once confirmed, the `Fitter` checks the customer in, advancing `CONFIRMED → CHECKED_IN`. The customer may instead reschedule from `CONFIRMED` back to `REQUESTED`, which releases the slot lock, optionally updates `scheduled_start` if a new value is provided, and requires re-confirmation; this is a deliberate cyclic revision loop. From either `REQUESTED` or `CONFIRMED`, the customer may cancel, advancing the appointment to `CANCELLED` and releasing any slot lock.

The fitting itself is performed while the appointment is `CHECKED_IN` and is a self-transition (`CHECKED_IN → CHECKED_IN`): each submission supersedes the prior recommendation. The `Fitter` supplies `underbust_cm`, `bust_cm`, an optional `fit_preference` of `SNUG`, `STANDARD` (the default), or `RELAXED`, and the `expected_appointment_version` described in Section 2.4. Measurements must lie within range — `underbust_cm` from 55 to 120 and `bust_cm` from 60 to 170 — or the submission is rejected with `ERR_MEASUREMENT_OUT_OF_RANGE`.

The recommendation is derived as follows. The raw band is the underbust measurement in centimetres divided by 2.54 to convert to inches; call half of that value the half-band. The `recommended_band` is an even integer produced by adjusting the half-band according to `fit_preference` and then doubling: for `SNUG`, round the half-band down to the nearest whole number and double it; for `RELAXED`, round the half-band up to the nearest whole number and double it; for `STANDARD`, round the half-band to the nearest whole number using round-half-up and double it. The cup is derived from the difference in centimetres between `bust_cm` and `underbust_cm`: divide that difference by 2.5 and round up to the next whole number to obtain a cup index. If the cup index is below 1 or above 8, the submission is rejected with `ERR_MEASUREMENT_OUT_OF_RANGE`. Otherwise the cup index selects `recommended_cup` by position, where 1 is `A`, 2 is `B`, 3 is `C`, 4 is `D`, 5 is `E`, 6 is `F`, 7 is `G`, and 8 is `H`. The `recommended_size` is the `recommended_band` written immediately before the `recommended_cup` letter, for example `30D`. A successful fit sets `recommended_band`, `recommended_cup`, and `recommended_size`, and increments the appointment's `version` by one.

Completion, by the `Fitter`, advances `CHECKED_IN → COMPLETED`, but only if a recommendation has been submitted — that is, `recommended_size` is not null; otherwise the request is rejected with `ERR_FIT_NOT_SUBMITTED`. `COMPLETED` and `CANCELLED` are terminal.

### 3.3. Orders: Drafting, Lines, and Placement

A `Customer` (or a `StoreManager` on their behalf) opens an order against a `customer_id` with an optional `order_type` of `STANDARD` (the default), `SPECIAL_ORDER`, or `GIFT`, an optional `is_gift` flag (default false), and, when it is a gift, an optional `gift_message` and `gift_recipient_name`. A new order begins with `payment_status` of `UNPAID` and `fulfillment_status` of `DRAFT`.

Lines are added to a draft order by supplying a `sku_id` and a `quantity` of at least 1. When a line is added, its `unit_price_cents` is snapshotted from the SKU's current `price_cents`, and its `line_gross_cents` is that snapshot multiplied by `quantity`. A line begins in `ACTIVE` status. The `is_special_order` flag is set true only when the line is added against an out-of-stock SKU on a `SPECIAL_ORDER` order — such a line takes no reservation; on any other order type a line against an out-of-stock or inactive SKU is not permitted through the ordinary path.

Placement, by the customer, advances `fulfillment_status` `DRAFT → PLACED`. The order must contain at least one `ACTIVE` line, or it is rejected with `ERR_EMPTY_ORDER`. For each `ACTIVE` non-special line, the referenced SKU must have `is_active` true, or the placement is rejected with `ERR_SKU_INACTIVE`; and the SKU's `available_units` must be greater than or equal to that line's `quantity`, or the placement is rejected with `ERR_INSUFFICIENT_STOCK` — an `available_units` of zero rejects any reservation. On success, each in-stock line's SKU has its `reserved_count` recomputed upward and its `available_units` and `stock_status` recomputed accordingly, reflecting the newly held inventory.

### 3.4. Payment, Loyalty, and Fulfillment

Payment is recorded by a `BillingClerk` and advances `payment_status` `UNPAID → PAID`, but only when the order's `fulfillment_status` is already `PLACED`; paying before placing is rejected with `ERR_ORDER_NOT_PLACED`. Payment computes the order totals over its `ACTIVE` lines using the customer's `loyalty_tier` snapshotted at this moment. The tier fixes a discount percentage — `BRONZE` earns 0 percent, `SILVER` earns 5 percent, and `GOLD` earns 10 percent. For each `ACTIVE` line the system computes `line_gross_cents` as `unit_price_cents` times `quantity`, then `line_discount_cents` as `line_gross_cents` multiplied by the tier percentage rounded half-up to whole cents, then `line_net_cents` as `line_gross_cents` minus `line_discount_cents`. The order's `subtotal_cents` is the sum of the line gross amounts, and `discount_cents` is the sum of the already-rounded per-line discounts (each line rounded first, then summed). A `gift_wrap_fee_cents` of 800 applies when `is_gift` is true and is 0 otherwise, and a `special_order_fee_cents` of 1500 applies when `order_type` is `SPECIAL_ORDER` and is 0 otherwise. The `total_cents` is `subtotal_cents` minus `discount_cents` plus `gift_wrap_fee_cents` plus `special_order_fee_cents`.

Payment also awards provisional loyalty. The base points are the order's `total_cents` divided by 100 with the fractional part discarded. At payment the provisional variant applies no tier multiplier, so `provisional_points` equals those base points. The system records a `LoyaltyEvent` with reason `ORDER_EARN` and a `points_delta` equal to `provisional_points`, and updates the customer's `loyalty_points`.

Fulfillment is performed by a `StoreManager` and advances `fulfillment_status` `PLACED → FULFILLED`. It requires the order's `payment_status` to be `PAID`; attempting fulfillment on an unpaid order is rejected with `ERR_ORDER_NOT_PAID`. On fulfillment, for each `ACTIVE` line the SKU's `stock_on_hand` is decremented by the line `quantity`, its `reserved_count`, `available_units`, and `stock_status` are recomputed, and the line's status moves to `FULFILLED`. The order's `fulfilled_at` is stamped from the logical clock. Loyalty is then finalized: the base points (again `total_cents` divided by 100, floored) are multiplied by the tier multiplier — 1 for `BRONZE`, 1 for `SILVER`, and 2 for `GOLD` — to produce `final_points`. A reconciling `LoyaltyEvent` with reason `FINAL_ADJUSTMENT` and a `points_delta` equal to `final_points` minus `provisional_points` is appended, and the customer's `loyalty_points` is updated. Finally, for each fulfilled line whose product `category` is `EVERYDAY_BRA`, `SPORTS_BRA`, or `MASTECTOMY_BRA`, the system creates a `ReplacementReminder` in `SCHEDULED` status whose `due_date` is `fulfilled_at` advanced by 6 calendar months (for example, a line fulfilled at `2026-07-01T00:00:00Z` yields a `due_date` of `2027-01-01T00:00:00Z`).

### 3.5. Cancellations, Exchanges, and Hygiene

An order may be cancelled by the customer while its `fulfillment_status` is `DRAFT` or `PLACED`; a `FULFILLED` order cannot be cancelled and yields `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves `fulfillment_status` to `CANCELLED` and cascades: every `ACTIVE` `OrderLine` moves to `CANCELLED`, and each cancelled line releases its reservation, so the affected SKUs have `reserved_count` recomputed downward and `available_units` and `stock_status` recomputed. If the order's `payment_status` was `PAID`, it moves to `REFUNDED`, and the provisional loyalty is reversed by appending a `LoyaltyEvent` with reason `ORDER_REVERSAL` and a `points_delta` of the negative of `provisional_points`, updating the customer's `loyalty_points` so the balance conserves back to its pre-order value.

After-sale exchanges are governed by hygiene rules unique to intimate apparel. A `Customer` (or `StoreManager`) requests an exchange against an `order_id` and a specific `order_line_id`, declaring the returned `item_condition` as `SEALED`, `TRIED_ON`, or `WORN`, with an optional `reason`. The exchange begins in `REQUESTED` status. A `StoreManager` then either rejects it — moving it to `REJECTED` with no side effects — or approves it. Approval requires three conditions. First, the referenced `OrderLine` must be in `FULFILLED` status, or the request is rejected with `ERR_LINE_NOT_EXCHANGEABLE_STATE`. Second, the `item_condition` must be `SEALED` and the product's `hygiene_class` must be `STANDARD_RETURNABLE`; a non-sealed item, or any `INTIMATE_NON_RETURNABLE` product, is rejected with `ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE`. Third, the number of whole days between the order's `fulfilled_at` and the logical clock's current instant must be within the exchange window of 30 days, or the request is rejected with `ERR_EXCHANGE_WINDOW_EXPIRED`; the boundary is inclusive, so an approval at exactly 30 days after fulfillment is still allowed and only day 31 onward is rejected.

Approval, which moves the exchange to `APPROVED`, drives a chain of consequences. The `OrderLine` moves to `EXCHANGED`; because the line is exchanged, the SKU's `stock_on_hand` is increased by the line `quantity` and its `reserved_count` and `available_units` are recomputed; and because `available_units` changes, the SKU's `stock_status` is recomputed, so a SKU that had been `OUT_OF_STOCK` rises to `LOW_STOCK` or `IN_STOCK` as its availability climbs back above zero. The exchange's `store_credit_issued_cents` is set to the line's `line_net_cents` and that amount is added to the customer's `store_credit_cents`. The loyalty earned for that line is reversed by appending a `LoyaltyEvent` with reason `EXCHANGE_REVERSAL` and the `points_delta` computed for the line, updating the customer's `loyalty_points`. Finally, any `SCHEDULED` `ReplacementReminder` tied to that `order_line_id` is moved to `CANCELLED`.

### 3.6. Insurance Claims for Mastectomy Purchases

A `BillingClerk` submits an insurance claim against an `order_id`. The order must be `PAID` (otherwise `ERR_ORDER_NOT_PAID`) and must contain at least one mastectomy line — a line whose product has `is_mastectomy` true — otherwise the submission is rejected with `ERR_NOT_MASTECTOMY_ORDER`. On submission the claim enters `SUBMITTED` status with `decision` of `PENDING`. Its `claim_amount_cents` is snapshotted as the sum of `line_net_cents` over the order's mastectomy lines. The covered amount is then estimated: it is the claim's base amount multiplied by the coverage rate of 80 percent, rounded half-up to whole cents, and then capped so that it never exceeds the coverage cap of 50000 cents. At submission the base amount is `claim_amount_cents`, and the result populates `covered_amount_cents`.

A `BillingClerk` adjudicates the claim with a `decision` of either `APPROVE` or `DENY`. On `APPROVE`, the clerk must supply an `adjudicated_amount_cents` that is present and zero or greater (otherwise `ERR_VALIDATION`); the claim moves to `APPROVED`, and `covered_amount_cents` is recomputed with the same coverage rate and cap but now over `adjudicated_amount_cents` — the insurer-approved eligible amount, which may be lower than the original claim and therefore may yield a different covered amount. On `DENY`, the claim moves to `DENIED` and `covered_amount_cents` is set to 0. A denied claim may be resubmitted, which returns it to `SUBMITTED`, resets `decision` to `PENDING`, and recomputes `covered_amount_cents` using the estimate over `claim_amount_cents` again — a deliberate cyclic loop between denial and resubmission.

An approved claim is reimbursed by a `BillingClerk`, moving it `APPROVED → REIMBURSED`. Reimbursement requires `covered_amount_cents` to be greater than 0, or it is rejected with `ERR_NOTHING_TO_REIMBURSE`. On success, `reimbursed_cents` is set to `covered_amount_cents` and that amount is added to the customer's `store_credit_cents`. `REIMBURSED` is terminal.

### 3.7. Replacement Reminders

Replacement reminders keep customers in well-fitting garments over time. Each reminder created at fulfillment references the seeding `customer_id` and `order_line_id` and carries a `status` of `SCHEDULED`, `SENT`, `DISMISSED`, or `CANCELLED`. A `StoreManager` sends a due reminder, advancing `SCHEDULED → SENT`, but only when the logical clock's current instant is at or after the reminder's `due_date`; sending early is rejected with `ERR_REMINDER_NOT_DUE`. A `Customer` (or `StoreManager`) may dismiss a reminder from either `SCHEDULED` or `SENT`, moving it to `DISMISSED`. Independently, the system cancels a `SCHEDULED` reminder whenever its parent line is cancelled or exchanged, moving it to `CANCELLED`, as described in the cancellation and exchange cascades above. `DISMISSED` and `CANCELLED` are terminal.

A note on generic state errors: any state-transition request whose target is not in a legal originating state, and which is not covered by one of the more specific state errors named above, is rejected with the generic `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including all state transitions and inventory mutations — return `200 OK`. Request and response bodies are not repeated here; reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/boutique/customers` | Create a customer | StoreManager |
| GET | `/boutique/customers/{id}` | Get a customer | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/customers/{id}/loyalty-adjustments` | Post an admin loyalty adjustment | StoreManager |
| GET | `/boutique/loyalty-events/{id}` | Get a loyalty event | Customer, StoreManager, BillingClerk |
| GET | `/boutique/loyalty-events` | List loyalty events | Customer, StoreManager, BillingClerk |
| POST | `/boutique/fitters` | Create a fitter | StoreManager |
| GET | `/boutique/fitters/{id}` | Get a fitter | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/rooms` | Create a fitting room | StoreManager |
| GET | `/boutique/rooms/{id}` | Get a fitting room | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/appointments` | Book a fitting appointment | Customer, StoreManager |
| GET | `/boutique/appointments/{id}` | Get an appointment | Customer, Fitter, StoreManager, BillingClerk |
| GET | `/boutique/appointments` | List appointments | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/appointments/{id}/confirm` | Confirm an appointment | Fitter |
| POST | `/boutique/appointments/{id}/check-in` | Check the customer in | Fitter |
| POST | `/boutique/appointments/{id}/fit` | Submit measurements and compute the size recommendation | Fitter |
| POST | `/boutique/appointments/{id}/complete` | Complete an appointment | Fitter |
| POST | `/boutique/appointments/{id}/reschedule` | Reschedule an appointment | Customer, StoreManager |
| POST | `/boutique/appointments/{id}/cancel` | Cancel an appointment | Customer, StoreManager |
| POST | `/boutique/products` | Create a product | StoreManager |
| GET | `/boutique/products/{id}` | Get a product | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/skus` | Create a SKU | StoreManager |
| GET | `/boutique/skus/{id}` | Get a SKU | Customer, Fitter, StoreManager, BillingClerk |
| GET | `/boutique/skus` | List SKUs | Customer, Fitter, StoreManager, BillingClerk |
| POST | `/boutique/skus/{id}/restock` | Add physical inventory units | StoreManager |
| POST | `/boutique/orders` | Create a draft order | Customer, StoreManager |
| GET | `/boutique/orders/{id}` | Get an order | Customer, StoreManager, BillingClerk |
| GET | `/boutique/orders` | List orders | Customer, StoreManager, BillingClerk |
| POST | `/boutique/orders/{id}/lines` | Add a line to a draft order | Customer, StoreManager |
| GET | `/boutique/order-lines/{id}` | Get an order line | Customer, StoreManager, BillingClerk |
| GET | `/boutique/order-lines` | List order lines | Customer, StoreManager, BillingClerk |
| POST | `/boutique/orders/{id}/place` | Place an order and reserve inventory | Customer, StoreManager |
| POST | `/boutique/orders/{id}/pay` | Record payment; compute totals and provisional loyalty | BillingClerk |
| POST | `/boutique/orders/{id}/fulfill` | Fulfill; decrement stock, finalize loyalty, seed reminders | StoreManager |
| POST | `/boutique/orders/{id}/cancel` | Cancel an order; release reservations, reverse loyalty, refund | Customer, StoreManager |
| POST | `/boutique/exchanges` | Request an exchange for a fulfilled line | Customer, StoreManager |
| GET | `/boutique/exchanges/{id}` | Get an exchange | Customer, StoreManager, BillingClerk |
| GET | `/boutique/exchanges` | List exchanges | Customer, StoreManager, BillingClerk |
| POST | `/boutique/exchanges/{id}/approve` | Approve an exchange | StoreManager |
| POST | `/boutique/exchanges/{id}/reject` | Reject an exchange | StoreManager |
| POST | `/boutique/insurance-claims` | Submit an insurance claim for a paid mastectomy order | BillingClerk |
| GET | `/boutique/insurance-claims/{id}` | Get an insurance claim | Customer, StoreManager, BillingClerk |
| GET | `/boutique/insurance-claims` | List insurance claims | Customer, StoreManager, BillingClerk |
| POST | `/boutique/insurance-claims/{id}/adjudicate` | Adjudicate a claim (APPROVE or DENY) | BillingClerk |
| POST | `/boutique/insurance-claims/{id}/reimburse` | Reimburse an approved claim into store credit | BillingClerk |
| POST | `/boutique/insurance-claims/{id}/resubmit` | Resubmit a denied claim | BillingClerk |
| GET | `/boutique/reminders/{id}` | Get a replacement reminder | Customer, StoreManager, BillingClerk |
| GET | `/boutique/reminders` | List reminders | Customer, StoreManager, BillingClerk |
| POST | `/boutique/reminders/{id}/send` | Send a due reminder | StoreManager |
| POST | `/boutique/reminders/{id}/dismiss` | Dismiss a reminder | Customer, StoreManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEASUREMENT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_FITTER_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_SKU_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_EXCHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REMINDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_ORDER_NOT_PLACED` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FIT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LINE_NOT_EXCHANGEABLE_STATE` | 409 Conflict |
| `ERR_NOTHING_TO_REIMBURSE` | 409 Conflict |
| `ERR_STALE_APPOINTMENT_VERSION` | 412 Precondition Failed |
| `ERR_FITTER_NOT_CERTIFIED` | 409 Conflict |
| `ERR_ROOM_NOT_PRIVATE` | 409 Conflict |
| `ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE` | 409 Conflict |
| `ERR_FITTER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_ROOM_AT_CAPACITY` | 409 Conflict |
| `ERR_EXCHANGE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REMINDER_NOT_DUE` | 409 Conflict |
| `ERR_SKU_INACTIVE` | 409 Conflict |
| `ERR_NOT_MASTECTOMY_ORDER` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 402 Payment Required |
