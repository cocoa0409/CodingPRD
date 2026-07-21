# Outdoor Camping Co-op API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a member-owned outdoor and camping co-operative retailer in the spirit of a member-dividend outfitter. The co-op is more than a store: members pay a one-time join fee, earn a share of the co-op's annual surplus in proportion to what they spend, redeem loyalty points, rent physical gear, book guided trips and classes, trade in used equipment, order repairs under warranty, buy seasonal permits, and place special orders for catalog items the shop does not stock. All of these activities are wired together through a shared store-credit wallet and a loyalty ledger, so a single service must keep membership, retail, rental inventory, trip logistics, and fiscal settlement consistent at all times.

The system is built around a handful of intertwined lifecycles. Rentable gear exists both as an abstract catalog `Product` and as physical `RentalUnit` assets whose availability cycles as they are picked up, returned, damaged, retired, and restored. Guided trips move through a publishing and departure workflow gated on a certified, schedule-free guide. Used-gear trade-ins run a bounded back-and-forth negotiation between a member and the front desk. Repairs advance along two independent tracks — the physical repair track and the billing track — that must both be resolved before an item leaves the shop. Because the co-op settles real money and points, every calculation is expressed in integer cents or whole points, every rounding step is pinned, and concurrent edits to the same order are serialized through optimistic version checks.

The consumers of this API are front-desk point-of-sale terminals, member-facing self-service clients, guide-facing read views, and co-op administrators who own the catalog, inventory, guides, and the annual dividend. Time-sensitive behavior (rental peak pricing, warranty windows, pass coverage, dividend-year attribution) is driven by a server-controlled logical clock so that the system is fully deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the two public endpoints described below must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically authenticated caller whose role is not permitted to perform the requested operation — or an entity-backed caller reaching for a resource it does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled exactly as follows: `Anonymous`, `Member`, `Guide`, `StoreStaff`, and `CoopAdmin`.

- When `X-User-Role` is `Anonymous`, the caller is an unauthenticated visitor. The `X-User-ID` is an opaque identifier not tied to any persisted entity; the only operation an `Anonymous` caller may perform is self-registration of a new member. Member registration therefore does not require authentication headers.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's `member_id` to `X-User-ID`; a member may act on and read its own reservations, bookings, trade-ins, passes, special orders, repair orders, purchases, and its own member record, but not those of another member.
- When `X-User-Role` is `Guide`, `X-User-ID` is the `id` of the acting `Guide`. A guide is a read-only participant who may read its own guide profile and the trips it is assigned to.
- When `X-User-Role` is `StoreStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Store staff run the point-of-sale, rental desk, trade-in desk, and repair desk; the server may record the identifier but does not compare it to any entity's `id`.
- When `X-User-Role` is `CoopAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A `CoopAdmin` is an operational superset that owns the catalog, rental-unit inventory, guides, trip lifecycle, dividends, wallet adjustments, and the logical clock.

Where an endpoint lists several authorized roles, any of those roles may call it, subject to the ownership rule for `Member` and `Guide`. On collection (list) reads an entity-backed caller is silently scoped to its own rows rather than rejected: a `Member` calling any list endpoint over a member-scoped collection (reservations, trip bookings, trade-ins, passes, special orders, repair orders, and purchases) receives only rows whose `member_id` equals its `X-User-ID`, and a `Guide` listing trips receives only trips whose `guide_id` equals its `X-User-ID`.

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

All list endpoints accept two optional query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and represents the number of leading records skipped. List results are ordered by `created_at` in ascending order (oldest first) unless a subsection states otherwise; when two records share the same `created_at`, they are further ordered by the server-assigned creation sequence, so ties resolve deterministically to insertion order (oldest write first). A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION`. Beyond `limit` and `offset`, list endpoints accept optional equality filters on selected fields, combined conjunctively, with an unmatched value simply yielding an empty result: members by `status`; products by `category` and `is_rentable`; rental units by `product_id` and `status`; reservations by `member_id`, `rental_unit_id`, `product_id`, and `status`; trips by `guide_id` and `status`; trip bookings by `trip_id`, `member_id`, and `status`; trade-ins by `member_id`, `product_id`, and `status`; repair orders by `member_id`, `product_id`, `rental_unit_id`, and `repair_stage`; special orders by `member_id`, `product_id`, and `status`; passes by `member_id`; and purchases by `member_id` and `status`. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix. Most resources also carry three common properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation that changes the resource. Whenever a state transition or field change is applied to a resource, its `updated_at` is refreshed and its `version` is incremented; a pure read never changes either.

One entity is deliberately lighter: a `LoyaltyLedger` entry carries only `id` and `created_at`. It has no `updated_at` and no `version`, because ledger entries are append-only and are never mutated after they are written.

### 2.5. The Logical Clock and Time-Derived Fields

The service does not read wall-clock time. Instead it maintains a logical clock whose startup default is `2026-07-01T00:00:00Z`; before any clock is explicitly set, reads of "now" return exactly this default and never fall back to real time. An administrator may advance or rewind the logical clock by supplying a target instant as `to_iso8601`; the response echoes the new value as `current_utc`. This logical-clock endpoint is the second of the two public endpoints noted in §2.1: it requires no `X-User-ID`/`X-User-Role` headers and applies no role check, so any caller may drive it (the `CoopAdmin` shown for it in §4 is nominal only and is not enforced). Advancing the clock re-derives every clock-dependent field, most visibly a pass's `coverage_status`.

Several fields are computed relative to this clock: rental peak-season pricing, repair warranty coverage, pass coverage windows, and the dividend year a purchase is attributed to are all resolved against the logical clock at the moment the relevant operation runs.

### 2.6. Monetary Precision and Rounding

All money is stored and returned as integer cents; all point balances are whole integers. Two rounding disciplines apply and must not be confused. Where a rule multiplies a monetary amount by a rate to produce a charge or adjusted price — rental peak multiplier, rental tier discount, and per-line sales tax — the result is rounded half-up to the nearest whole cent at each pinned rounding step. Where a rule produces a payout, a redemption, a deposit, a dividend, or points earned, the result is truncated toward zero (floor) to a whole cent or whole point. Each calculation subsection below names which discipline applies at each step and the order in which the steps run; the order is pinned and may not be rearranged.

### 2.7. Optimistic Concurrency Control

Re-quoting a special order is guarded by an optimistic version check. A request to issue or replace a special order's price quote must include `expected_special_order_version` carrying the `version` of the target `SpecialOrder` that the client last observed. The server compares it to the order's current `version`: if another writer has advanced the order's version since the client last read it, the re-quote is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a staffer working from a stale view from silently overwriting a newer quote. When the check passes, the quote is applied and the order's `version` is incremented by 1. No other endpoint accepts or requires a client-supplied version field.

### 2.8. Cascading State Effects and Conservation Invariants

Several operations mutate more than one entity in a single call, and each cascade must be applied in full. A damaged rental return, a trip cancellation, a trip completion, a booking cancellation, a trade-in credit acceptance, a special-order confirmation or cancellation, a purchase, a purchase refund, and a dividend finalize all touch a secondary entity in addition to their primary target; the per-workflow narratives in §3 enumerate each secondary effect. Every entity touched by a cascade has its own `updated_at` refreshed and `version` incremented.

Two quantities are conserved by construction and must remain reconciled at all times. First, a member's `loyalty_points_balance` always equals the sum of the `delta` values of that member's `LoyaltyLedger` entries; a redemption of some number of points paired with its later refund or reversal of the same magnitude leaves the balance unchanged. Second, for any given product, the total number of physical rental units never changes as those units move between statuses: the count of units in `AVAILABLE`, plus the count in `RENTED_OUT`, plus the count in `OUT_OF_SERVICE`, equals the fixed total for that product. A pickup moves one unit from `AVAILABLE` to `RENTED_OUT`; the paired good return moves it back, restoring the available count.

### 2.9. Validation Order and Resource Resolution

When several checks could fail on one request, they are evaluated in a fixed priority order and the first failure is the one reported. The order is: (1) authentication of the request headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the acting role and, for entity-backed roles, ownership of the target, yielding `ERR_UNAUTHORIZED`; (3) existence of every resource referenced by the path or body, checked left to right in the order the identifiers appear and yielding a resource-specific not-found error; (4) state and cross-entity state preconditions, yielding `ERR_INVALID_STATE`, `ERR_TRIP_NOT_OPEN`, `ERR_MEMBERSHIP_NOT_ACTIVE`, or `ERR_RENTAL_UNIT_UNAVAILABLE`; (5) business-safety checks such as guide certification, yielding `ERR_GUIDE_NOT_CERTIFIED`; (6) temporal checks — rental window conflicts, guide schedule conflicts, and interval validity — yielding `ERR_RENTAL_WINDOW_CONFLICT`, `ERR_GUIDE_SCHEDULE_CONFLICT`, or `ERR_INVALID_INTERVAL`; (7) business-constraint checks — trip capacity, quantity/price sanity, the special-order version match, and the trade-in round cap — yielding `ERR_TRIP_FULL`, `ERR_INVALID_QUANTITY`, `ERR_STALE_VERSION`, or `ERR_TRADE_IN_ROUNDS_EXCEEDED`; and (8) fiscal-capacity checks, yielding `ERR_INSUFFICIENT_POINTS` or `ERR_INSUFFICIENT_WALLET`. A body that is structurally malformed — a missing required field, a value of the wrong type, or an unknown enum value — is rejected with `ERR_VALIDATION` (HTTP 400) before business rules run.

Resource existence is resolved for every referenced identifier. A missing member yields `ERR_MEMBER_NOT_FOUND`; a missing product `ERR_PRODUCT_NOT_FOUND`; a missing rental unit `ERR_RENTAL_UNIT_NOT_FOUND`; a missing reservation `ERR_RESERVATION_NOT_FOUND`; a missing trip `ERR_TRIP_NOT_FOUND`; a missing guide `ERR_GUIDE_NOT_FOUND`; a missing trip booking `ERR_BOOKING_NOT_FOUND`; a missing trade-in `ERR_TRADE_IN_NOT_FOUND`; a missing repair order `ERR_REPAIR_ORDER_NOT_FOUND`; a missing special order `ERR_SPECIAL_ORDER_NOT_FOUND`; a missing purchase `ERR_PURCHASE_NOT_FOUND`; a missing dividend declaration `ERR_DECLARATION_NOT_FOUND`; and a missing pass `ERR_PASS_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Membership, the Join Fee, and the Store-Credit Wallet

Anyone may register as a member by supplying an `email` (unique across all members) and a `full_name`, optionally choosing a `membership_tier` of either `BASIC` or `PREMIER`; when the tier is omitted it defaults to `BASIC`. Registration creates the member in `PENDING` `membership_status` and pins a read-only `join_fee_cents` from the chosen tier: a `BASIC` join costs 3000 cents, while a `PREMIER` join costs 12000 cents. A `PREMIER` member pays the higher join fee in exchange for a standing rental discount described in §3.3. A newly registered member starts with a `loyalty_points_balance` of 0, an `eligible_spend_cents` of 0, and a `wallet_credit_cents` of 0.

Collecting the join fee and moving a member from `PENDING` to `ACTIVE` is a front-desk action; it requires the member currently be `PENDING`, otherwise it is rejected with `ERR_INVALID_STATE`. An active member may be lapsed by an administrator, moving `ACTIVE` to `LAPSED` (rejected with `ERR_INVALID_STATE` if the member is not `ACTIVE`); a lapsed member may be reactivated at the desk, moving `LAPSED` back to `ACTIVE` (rejected unless the member is `LAPSED`), forming the `ACTIVE`↔`LAPSED` cycle. An administrator may close a member whose status is `ACTIVE` or `LAPSED`, moving it to the terminal `CLOSED` state; closing a member in any other state is rejected with `ERR_INVALID_STATE`.

The store-credit wallet is the co-op's internal money rail. A member's `wallet_credit_cents` is credited by trade-in credit payouts, trip-booking refunds, special-order cancellation refunds, dividend payouts, and direct administrative adjustments. An administrator may adjust a wallet directly by supplying a signed `delta_cents` and a `reason`; the amount is added to the member's `wallet_credit_cents` (a negative delta reduces it). A member's `id` returned at registration is the identifier that member presents as `X-User-ID` on all later self-service calls.

The member summary view exposes a compact, fully computed snapshot: the member's `member_id`, its dividend-year `eligible_spend_cents`, a `provisional_dividend_cents` estimate, the `loyalty_points_balance`, and the `wallet_credit_cents`. The provisional estimate is described in §3.9.

### 3.2. Retail Purchases, Sales Tax, and Loyalty Points

A retail sale is rung up at the point of sale by store staff for a given `member_id` with a list of `line_items`, each line naming a `product_id`, a `quantity`, and a `unit_price_cents`; the sale may optionally spend loyalty points via `points_redeemed`, which defaults to 0. Every line quantity must be greater than 0 and every `unit_price_cents` must be at least 0, otherwise the purchase is rejected with `ERR_INVALID_QUANTITY`. A completed purchase starts in `COMPLETED` status.

The purchase totals are computed in a pinned order. First, each line's subtotal is its `unit_price_cents` multiplied by its `quantity`, and `subtotal_cents` is the sum of those line subtotals. Sales tax is computed per line and only then summed: for each line, the line's tax is the line subtotal multiplied by that line's product `tax_rate`, rounded half-up to a whole cent; `tax_cents` is the sum of those per-line rounded taxes. Rounding the tax per line and then summing is the pinned discipline; summing the untaxed line amounts and rounding once at the end is explicitly not used. The loyalty redemption applied, `loyalty_redemption_cents`, is the smaller of the points the member offered in `points_redeemed` and the floor of 0.50 times `subtotal_cents` — that is, redemption may not discount more than half of the pre-tax subtotal. The `total_cents` charged is `subtotal_cents` plus `tax_cents` minus `loyalty_redemption_cents`.

Two further amounts are derived. The dividend-eligible amount, `eligible_spend_cents`, is the pre-tax `subtotal_cents` before any redemption. Points earned, `loyalty_points_earned`, is the floor of `eligible_spend_cents` multiplied by 0.01 — one point per 100 cents (one dollar) of eligible spend. On a purchase the co-op appends a loyalty earn entry to the ledger for the points earned and, when points were redeemed, a matching redemption entry that reduces the balance; the member's rolled-up `eligible_spend_cents` is then recomputed. A member must actually hold enough points to cover `points_redeemed`, otherwise the sale is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 402).

A completed purchase may be refunded by store staff, moving it from `COMPLETED` to `REFUNDED`; a purchase not currently `COMPLETED` cannot be refunded and yields `ERR_INVALID_STATE`. A refund reverses the loyalty effects: it appends a reversal entry removing the `loyalty_points_earned` that the sale granted, and, if the sale had redeemed points, a second reversal entry restoring the redeemed amount. After a refund the purchase is no longer `COMPLETED`, so the member's `eligible_spend_cents` is recomputed to drop this purchase's contribution.

The loyalty ledger is append-only. Each entry records the owning `member_id`, a signed `delta`, a `reason` drawn from `PURCHASE_EARN`, `PURCHASE_REDEEM`, `BOOKING_REDEEM`, `BOOKING_REFUND`, and `PURCHASE_REFUND_REVERSAL`, and an optional `ref_id` naming the purchase or booking that produced it. A member's `loyalty_points_balance` is always exactly the sum of that member's ledger deltas.

### 3.3. Gear Rental: Units, Reservations, and Turnaround

Rentable gear is modeled in two layers. A catalog `Product` carries a `sku` (unique across products), a `name`, a `category` of `TENT`, `SLEEPING`, `COOKING`, `APPAREL`, `CLIMBING`, or `PADDLE`, a `retail_price_cents`, a `tax_rate`, a `replacement_value_cents`, an `is_rentable` flag defaulting to false, and a `base_daily_rate_cents` defaulting to 0. When a product is marked rentable, its `base_daily_rate_cents` must be greater than 0. Only rentable products may back physical rental assets. Each physical `RentalUnit` names its `product_id` and a unique `asset_tag`, starts life `AVAILABLE`, and carries a `condition` of `GOOD` or `DAMAGED` that starts `GOOD`. A unit's `status` reflects physical possession — `AVAILABLE`, `RENTED_OUT`, or `OUT_OF_SERVICE` — while reservations merely hold windows against the unit rather than the unit itself.

To reserve, a member (or staff on their behalf) supplies a `member_id`, a `rental_unit_id`, a `start_date`, and an `end_date`; the unit's `product_id` is copied onto the reservation at creation and the reservation starts `RESERVED`. The reservation's `rental_days` is the number of whole days between `start_date` and `end_date`, rounded up, with a minimum of 1. Three cross-checks guard creation: the acting member's `membership_status` must be `ACTIVE` (a `PENDING`, `LAPSED`, or `CLOSED` member is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE`); the referenced unit's `status` must not be `OUT_OF_SERVICE`, otherwise `ERR_RENTAL_UNIT_UNAVAILABLE`; and `end_date` must be strictly after `start_date`, otherwise `ERR_INVALID_INTERVAL`.

Rental windows are half-open and separated by a one-day turnaround buffer. Against the same unit, the existing reservations that count are those in `RESERVED` or `PICKED_UP` status. The new window `[start_date, end_date)` conflicts with an existing window `[existing_start, existing_end)` when the new start is earlier than the existing end extended by 1 day, and the existing start is earlier than the new end extended by 1 day. Two windows that merely touch at a boundary are allowed only if the gap between them is at least the 1-day buffer; anything closer is rejected with `ERR_RENTAL_WINDOW_CONFLICT`.

At creation the reservation's `rental_fee_cents` is computed and pinned in a fixed order. Start from the raw fee: the product's `base_daily_rate_cents` multiplied by `rental_days`. If the reservation's `start_date` falls in peak season — on or after `2026-06-01T00:00:00Z` and before `2026-09-01T00:00:00Z` — the raw fee is multiplied by the peak multiplier of 1.25 and rounded half-up to a whole cent; otherwise the raw fee stands. The member's tier discount is then applied: a `BASIC` member's rental discount is 0.00 and a `PREMIER` member's is 0.10, so the peak-adjusted amount is multiplied by one minus that discount and rounded half-up to a whole cent. Finally the result is capped at the product's `replacement_value_cents`: the pinned `rental_fee_cents` is the smaller of the discounted amount and the replacement value. The evaluation order — raw, then peak, then discount, then cap — may not be rearranged.

A reserved unit is handed over by staff, advancing the reservation from `RESERVED` to `PICKED_UP` and moving the unit from `AVAILABLE` to `RENTED_OUT`; pickup requires the reservation be `RESERVED` and the unit be `AVAILABLE`, otherwise `ERR_INVALID_STATE`. A member may cancel a still-`RESERVED` reservation, moving it to the terminal `CANCELLED` state and releasing the held window without touching the unit's status; cancelling anything not `RESERVED` yields `ERR_INVALID_STATE`.

Return is where damage handling branches, and staff supply a `condition` on return. A good return of a `PICKED_UP` reservation moves it to `RETURNED` and then immediately to the terminal `CLOSED` state, and moves the unit from `RENTED_OUT` back to `AVAILABLE`. A damaged return of a `PICKED_UP` reservation instead cascades: the reservation moves to `DAMAGE_ASSESSED`; the unit moves from `RENTED_OUT` to `OUT_OF_SERVICE` with its `condition` set to `DAMAGED`; and a repair order is auto-created for that unit with its `rental_unit_id` set, its `repair_stage` at `RECEIVED`, and its `billing_stage` at `UNBILLED`. Either return requires the reservation be `PICKED_UP`, otherwise `ERR_INVALID_STATE`.

Units also move under direct desk control. Staff may retire an `AVAILABLE` unit — supplying an `action` of `RETIRE` — moving it to `OUT_OF_SERVICE`, or restore an `OUT_OF_SERVICE` unit with an `action` of `RESTORE`, moving it back to `AVAILABLE` with its `condition` reset to `GOOD`. Retiring a unit that is not `AVAILABLE`, or restoring a unit that is not `OUT_OF_SERVICE`, is rejected with `ERR_INVALID_STATE`.

### 3.4. Guided Trips, Certified Guides, and Seat Bookings

A `Guide` is created by an administrator with a `full_name` and an optional list of `certifications` drawn from `SWIFTWATER`, `ALPINE`, and `WILDERNESS_FIRST_AID`; the list defaults to empty, and the guide starts `ACTIVE` with the possibility of being `INACTIVE`. A trip or class is created with a `title`, a `start_time`, an `end_time`, a `capacity` of more than 0, a per-seat `price_cents`, and an optional `required_certification` of `NONE`, `SWIFTWATER`, `ALPINE`, or `WILDERNESS_FIRST_AID` that defaults to `NONE`. A trip starts in `DRAFT`, its `guide_id` null and its `seats_confirmed` at 0. Its `end_time` must be strictly after its `start_time`, otherwise `ERR_INVALID_INTERVAL`, and its `capacity` must be positive, otherwise `ERR_INVALID_QUANTITY`.

Before a trip can be published it must be given a guide. Assigning a guide requires that the guide hold the trip's `required_certification` — the guide's `certifications` must contain it — otherwise the assignment is rejected with `ERR_GUIDE_NOT_CERTIFIED`. The guide must also be schedule-free: among the guide's other trips whose status is `DRAFT`, `OPEN`, or `DEPARTED`, the schedule uses closed intervals with no buffer. This trip's window `[start_time, end_time]` conflicts with an assigned trip's window `[assigned_start, assigned_end]` when this start is at or before the assigned end and the assigned start is at or before this end; because the intervals are closed and inclusive, exact adjacency — this trip starting at the very instant another ends — counts as a conflict, rejected with `ERR_GUIDE_SCHEDULE_CONFLICT`. A successful assignment sets the trip's `guide_id`. Assignment itself carries no precondition on the trip's own status and simply overwrites any previously assigned `guide_id`; the certification and schedule checks above are the only guards.

Publishing moves a `DRAFT` trip to `OPEN`, and requires that a guide already be assigned (its `guide_id` not null) and that the trip be `DRAFT`, otherwise `ERR_INVALID_STATE`. An `OPEN` trip may be marked `DEPARTED`; a `DEPARTED` trip may be `COMPLETED`; each requires the trip be in the expected prior state, otherwise `ERR_INVALID_STATE`. Completing a departed trip also completes attendance: every `TripBooking` on it that is `CHECKED_IN` is moved to `COMPLETED`. An administrator may cancel a trip whose status is `DRAFT` or `OPEN`, moving it to the terminal `CANCELLED` state; cancelling a trip in any other status yields `ERR_INVALID_STATE`. Cancelling a trip with bookings cascades booking cancellations, described below; a `DRAFT` trip carries no bookings.

A seat is booked by a member on an `OPEN` trip by supplying the `member_id` and an optional `points_redeemed` that defaults to 0. The booking records its `trip_id`, captures the trip's price into `price_paid_cents`, and starts `CONFIRMED`. A booking is only accepted on an `OPEN` trip; a trip in any other status yields `ERR_TRIP_NOT_OPEN`. The booking member's `membership_status` must be `ACTIVE`, otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`. Capacity is enforced by counting seats rather than by a trip status: `seats_confirmed` is the number of that trip's bookings in `CONFIRMED` or `CHECKED_IN` status, and a booking is rejected with `ERR_TRIP_FULL` when `seats_confirmed` already equals `capacity` — the trip itself stays `OPEN`, and there is no full status. When points are redeemed on a booking they are deducted through a loyalty redemption entry, and the member must hold enough points, otherwise `ERR_INSUFFICIENT_POINTS`. Each new confirmed booking raises the trip's `seats_confirmed` by 1.

A `CONFIRMED` booking is checked in by staff once its trip is `DEPARTED`, moving the booking to `CHECKED_IN`; the booking must be `CONFIRMED` and the trip `DEPARTED`, otherwise `ERR_INVALID_STATE`. A member may cancel a `CONFIRMED` booking (rejected with `ERR_INVALID_STATE` if it is not `CONFIRMED`), and a booking may also be cancelled by the cascade from a trip cancellation, which can cancel bookings that are `CONFIRMED` or `CHECKED_IN`. In every cancellation the booking moves to the terminal `CANCELLED` state, a loyalty refund entry is appended returning the member's `points_redeemed`, the member's `wallet_credit_cents` is credited by the `price_paid_cents` minus the `points_redeemed`, and the trip's `seats_confirmed` is recomputed downward by 1.

### 3.5. Used-Gear Trade-In Negotiation

A member submits a used item for trade-in by naming the `member_id`, the `product_id` of the model being traded (its retail price is the valuation base), and a `condition_grade` of `A`, `B`, or `C`. The trade-in starts `SUBMITTED`. Staff make an offer, moving it to `OFFERED`; an offer may be made from `SUBMITTED` or from `COUNTERED`, otherwise `ERR_INVALID_STATE`. At each offer the two payout variants are computed from the product's `retail_price_cents`. The grade factor is 0.50 for grade `A`, 0.35 for grade `B`, and 0.20 for grade `C`. The `offered_cash_cents` is the floor of the retail price times the grade factor times the cash factor of 0.80, and the `offered_credit_cents` is the floor of the retail price times the grade factor times the credit factor of 1.00 — cash pays less than store credit for the same item.

From an `OFFERED` state the member may counter, recording a non-binding `counter_ask_cents`, incrementing the completed-loop counter `rounds` by 1, and moving the trade-in to `COUNTERED`; this forms the `OFFERED`↔`COUNTERED` negotiation loop, since staff may re-offer from `COUNTERED` and recompute the two payout figures. A counter is allowed only while the trade-in is `OFFERED` and only while `rounds` is still below the cap of 3 completed loops; a counter attempted once `rounds` has reached 3 is rejected with `ERR_TRADE_IN_ROUNDS_EXCEEDED`, and a counter attempted from any non-`OFFERED` state yields `ERR_INVALID_STATE`.

From an `OFFERED` state the member may accept by choosing an `accepted_payout_type` of `CASH` or `CREDIT`; acceptance pins `accepted_payout_cents` to the `offered_cash_cents` when `CASH` was chosen or the `offered_credit_cents` when `CREDIT` was chosen, and moves the trade-in to the terminal `ACCEPTED` state. When the accepted channel is `CREDIT`, the accepted amount is added to the member's `wallet_credit_cents`; a cash acceptance pays out externally and does not touch the wallet. Accepting from a non-`OFFERED` state yields `ERR_INVALID_STATE`. The member may instead reject, from either `OFFERED` or `COUNTERED`, moving the trade-in to the terminal `REJECTED` state; rejecting from any other state yields `ERR_INVALID_STATE`.

### 3.6. Repairs and Warranty on Two Independent Tracks

A repair order is opened either directly — by a member or staff supplying a `member_id`, a `product_id` for the model under repair, and a `purchase_date` anchoring the warranty window — or automatically by a damaged rental return, in which case its `rental_unit_id` is set to the returned unit and it is otherwise blank. Every repair order advances along two parallel dimensions that move independently. The repair dimension, `repair_stage`, runs `RECEIVED` → `DIAGNOSED` → `IN_REPAIR` → `READY` → `PICKED_UP`. The billing dimension, `billing_stage`, runs `UNBILLED` → `INVOICED` → `SETTLED`. A fresh order starts `RECEIVED` and `UNBILLED` with `warranty_status` `UNDETERMINED`.

Diagnosis is where charges and coverage are decided. Staff enter a quoted `labor_cents` and `parts_cents` (each defaulting to 0), and the order's `warranty_status` is resolved against the logical clock: coverage is `COVERED` when the number of days between the `purchase_date` and the current clock date is at most 365, and `DENIED` otherwise. The computed `billed_cents` is 0 when the warranty is `COVERED`, and otherwise the sum of `labor_cents` and `parts_cents`. Diagnosis moves `repair_stage` from `RECEIVED` to `DIAGNOSED` and is rejected with `ERR_INVALID_STATE` unless the order is `RECEIVED`.

Starting the repair moves `repair_stage` from `DIAGNOSED` to `IN_REPAIR`; if the order carries a positive `billed_cents`, the same operation advances the billing dimension from `UNBILLED` to `INVOICED`. A zero-billed (fully warranty-covered) order simply stays `UNBILLED`. Marking the work `READY` moves `repair_stage` from `IN_REPAIR` to `READY`. Each of these requires the expected prior repair stage, otherwise `ERR_INVALID_STATE`. Settlement of the invoice is a billing-dimension action that moves `billing_stage` from `INVOICED` to `SETTLED`, independent of where `repair_stage` sits; settling anything not `INVOICED` yields `ERR_INVALID_STATE`.

Handing the item back closes both tracks. Picking up a repair moves `repair_stage` from `READY` to the terminal `PICKED_UP` state, but only when the money is resolved: the `billing_stage` must be `SETTLED`, or the `billed_cents` must be 0. A pickup attempted while billable work remains unsettled is rejected with `ERR_REPAIR_UNSETTLED`, and a pickup attempted before the repair stage reaches `READY` yields `ERR_INVALID_STATE`.

### 3.7. Permits and Passes

A pass or permit is sold to a member with a `member_id`, a `pass_type` of `DAY`, `SEASON`, or `ANNUAL`, a validity window `valid_from` (inclusive) and `valid_to` (exclusive), and a `price_cents`. The window must be valid — `valid_to` strictly after `valid_from`, otherwise `ERR_INVALID_INTERVAL`. A pass's `coverage_status` is fully computed against the logical clock rather than stored: it is `PENDING` while the clock is before `valid_from`, `ACTIVE` while the clock is at or after `valid_from` and before `valid_to`, and `EXPIRED` once the clock reaches or passes `valid_to`. A pass may be voided by staff, which sets its `voided` flag to true and forces its `coverage_status` to `VOID` regardless of the clock; a voided pass reads `VOID` permanently.

### 3.8. Special Orders and Deposits

A special order lets a member request a catalog item the shop does not stock. It is opened with a `member_id`, a `product_id`, and a `quantity` greater than 0 (otherwise `ERR_INVALID_QUANTITY`), and starts `REQUESTED` with a null `quoted_price_cents`. Staff issue a price quote by supplying a `quoted_price_cents`, which sets the order's `quoted_price_cents` (superseding any prior quote), moves the order to `QUOTED`, and increments the order's `version` by 1; a quote may be issued while the order is `REQUESTED` or `QUOTED`, otherwise `ERR_INVALID_STATE`. Because a new quote legitimately overwrites the previous one, this operation is version-guarded exactly as described in §2.7: the request must carry `expected_special_order_version` matching the order's current `version`, or it is rejected with `ERR_STALE_VERSION`.

The member confirms a `QUOTED` order, which computes the required `deposit_cents` as the floor of the `quoted_price_cents` multiplied by the deposit rate of 0.20. Confirmation requires the member's `wallet_credit_cents` to be at least that deposit; if the wallet cannot cover it the confirm is rejected with `ERR_INSUFFICIENT_WALLET`. On success the deposit is debited from `wallet_credit_cents` and the order moves to `CONFIRMED`; confirming anything not `QUOTED` yields `ERR_INVALID_STATE`. Staff fulfill a `CONFIRMED` order — placing it with the vendor, receiving it, and handing it over — moving it to the terminal `FULFILLED` state; fulfilling anything not `CONFIRMED` yields `ERR_INVALID_STATE`. A special order may be cancelled from `REQUESTED`, `QUOTED`, or `CONFIRMED`, moving it to the terminal `CANCELLED` state; if a deposit had been taken (a positive `deposit_cents`), the cancellation refunds it back to the member's `wallet_credit_cents`. Cancelling from any other state yields `ERR_INVALID_STATE`.

### 3.9. Co-op Dividends

The co-op returns a share of the year's surplus to members in proportion to their eligible spending. A member's `eligible_spend_cents` is the sum of the `eligible_spend_cents` of that member's `COMPLETED` purchases within the current dividend year — January 1 through December 31 of the logical clock's year — which is why a refund, by dropping a purchase out of `COMPLETED`, lowers the rolled-up figure.

Two dividend figures share that same eligible base but use different rates. The provisional figure shown on a member's summary before any declaration is finalized, `provisional_dividend_cents`, is the floor of the member's `eligible_spend_cents` multiplied by the fixed provisional rate of 0.05. The final figure is set when an administrator finalizes a declaration. A declaration is created for a `year` (unique across declarations) with a `declared_rate`, starting in `DRAFT` status; finalizing it requires it be `DRAFT`, otherwise `ERR_INVALID_STATE`. At finalize, every member whose `eligible_spend_cents` is at least 100000 cents receives a final dividend equal to the floor of that member's `eligible_spend_cents` multiplied by the declaration's `declared_rate`, credited to the member's `wallet_credit_cents`. The declaration's `payouts` array is pinned as one entry per qualifying member, ordered by ascending member creation order — each carrying the `member_id`, that member's `eligible_spend_cents`, and the `final_dividend_cents` credited — and `total_payout_cents` is pinned as the sum of those final dividends. Members below the 100000-cent threshold receive no payout and no payout entry. The declaration then moves to the terminal `FINALIZED` state.

## 4. Endpoint Definitions

All endpoints are mounted under the `/coop` prefix (the logical-clock utility is the sole exception). Creating a new resource returns HTTP 201; reading, listing, and state-changing actions on an existing resource return HTTP 200. Request and response bodies for each operation are described in the workflow narratives of §3; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /coop/members | Register a new member (self-service); starts PENDING | Anonymous |
| GET | /coop/members | List members | StoreStaff, CoopAdmin |
| GET | /coop/members/{id} | Read a member | Member, StoreStaff, CoopAdmin |
| GET | /coop/members/{id}/summary | Computed member summary | Member, StoreStaff, CoopAdmin |
| GET | /coop/members/{id}/loyalty-ledger | List a member's loyalty ledger entries | Member, StoreStaff, CoopAdmin |
| POST | /coop/members/{id}/activate | Collect join fee and activate a PENDING member | StoreStaff, CoopAdmin |
| POST | /coop/members/{id}/lapse | Lapse an ACTIVE member | CoopAdmin |
| POST | /coop/members/{id}/reactivate | Reactivate a LAPSED member | StoreStaff, CoopAdmin |
| POST | /coop/members/{id}/close | Close a member (ACTIVE or LAPSED) | CoopAdmin |
| POST | /coop/members/{id}/wallet/adjustments | Admin store-credit adjustment | CoopAdmin |
| POST | /coop/products | Create a catalog product/SKU | CoopAdmin |
| GET | /coop/products | List products | Member, StoreStaff, CoopAdmin |
| GET | /coop/products/{id} | Read a product | Member, StoreStaff, CoopAdmin |
| POST | /coop/rental-units | Create a physical rental unit for a rentable product | CoopAdmin |
| GET | /coop/rental-units | List/filter rental units | Member, StoreStaff, CoopAdmin |
| GET | /coop/rental-units/{id} | Read a rental unit | Member, StoreStaff, CoopAdmin |
| POST | /coop/rental-units/{id}/service | Retire an AVAILABLE unit or restore an OUT_OF_SERVICE unit | StoreStaff, CoopAdmin |
| POST | /coop/reservations | Reserve a rental unit for a date window; computes rental_fee_cents | Member, StoreStaff |
| GET | /coop/reservations | List/filter reservations | Member, StoreStaff, CoopAdmin |
| GET | /coop/reservations/{id} | Read a reservation | Member, StoreStaff, CoopAdmin |
| POST | /coop/reservations/{id}/pickup | Member picks up the reserved unit | StoreStaff |
| POST | /coop/reservations/{id}/return | Return a rented unit (GOOD closes; DAMAGED cascades a repair) | StoreStaff |
| POST | /coop/reservations/{id}/cancel | Cancel a RESERVED reservation | Member, StoreStaff |
| POST | /coop/guides | Create a guide | CoopAdmin |
| GET | /coop/guides/{id} | Read a guide | Guide, StoreStaff, CoopAdmin |
| POST | /coop/trips | Create a trip/class in DRAFT | StoreStaff, CoopAdmin |
| GET | /coop/trips | List/filter trips | Member, Guide, StoreStaff, CoopAdmin |
| GET | /coop/trips/{id} | Read a trip | Member, Guide, StoreStaff, CoopAdmin |
| POST | /coop/trips/{id}/assign-guide | Assign a certified, schedule-free guide to a trip | CoopAdmin |
| POST | /coop/trips/{id}/open | Publish a DRAFT trip (requires an assigned guide) | CoopAdmin |
| POST | /coop/trips/{id}/depart | Mark an OPEN trip DEPARTED | CoopAdmin |
| POST | /coop/trips/{id}/complete | Complete a DEPARTED trip; checked-in bookings auto-complete | CoopAdmin |
| POST | /coop/trips/{id}/cancel | Cancel a trip; cascades booking cancellations and refunds | CoopAdmin |
| POST | /coop/trips/{id}/bookings | Book a seat on an OPEN trip; optional loyalty redemption | Member |
| GET | /coop/trip-bookings | List/filter bookings | Member, StoreStaff, CoopAdmin |
| GET | /coop/trip-bookings/{id} | Read a trip booking | Member, StoreStaff, CoopAdmin |
| POST | /coop/trip-bookings/{id}/check-in | Check a confirmed booking in on a departed trip | StoreStaff |
| POST | /coop/trip-bookings/{id}/cancel | Cancel a confirmed booking; refunds points and wallet | Member, StoreStaff |
| POST | /coop/trade-ins | Submit a used-gear trade-in | Member, StoreStaff |
| GET | /coop/trade-ins | List/filter trade-ins | Member, StoreStaff, CoopAdmin |
| GET | /coop/trade-ins/{id} | Read a trade-in | Member, StoreStaff, CoopAdmin |
| POST | /coop/trade-ins/{id}/offer | Staff makes/updates a valuation offer | StoreStaff |
| POST | /coop/trade-ins/{id}/counter | Member counters the current offer | Member |
| POST | /coop/trade-ins/{id}/accept | Member accepts the current offer with a payout channel | Member |
| POST | /coop/trade-ins/{id}/reject | Member rejects the trade-in | Member |
| POST | /coop/repair-orders | Open a repair/warranty work order | Member, StoreStaff |
| GET | /coop/repair-orders | List/filter repair orders | Member, StoreStaff, CoopAdmin |
| GET | /coop/repair-orders/{id} | Read a repair order | Member, StoreStaff, CoopAdmin |
| POST | /coop/repair-orders/{id}/diagnose | Diagnose: enter labor/parts, decide warranty, compute billed_cents | StoreStaff |
| POST | /coop/repair-orders/{id}/start | Begin repair; invoices billable work | StoreStaff |
| POST | /coop/repair-orders/{id}/ready | Mark repair ready for pickup | StoreStaff |
| POST | /coop/repair-orders/{id}/settle | Settle the invoice (billing dimension) | StoreStaff |
| POST | /coop/repair-orders/{id}/pickup | Owner picks up a READY, settled repair | StoreStaff |
| POST | /coop/passes | Sell a permit/pass with a validity window | Member, StoreStaff |
| GET | /coop/passes | List/filter passes | Member, StoreStaff, CoopAdmin |
| GET | /coop/passes/{id} | Read a pass (incl. computed coverage_status) | Member, StoreStaff, CoopAdmin |
| POST | /coop/passes/{id}/void | Void a pass | StoreStaff, CoopAdmin |
| POST | /coop/special-orders | Open a special order for a catalog item | Member, StoreStaff |
| GET | /coop/special-orders | List/filter special orders | Member, StoreStaff, CoopAdmin |
| GET | /coop/special-orders/{id} | Read a special order | Member, StoreStaff, CoopAdmin |
| POST | /coop/special-orders/{id}/quotes | Issue/replace a price quote (OCC-guarded) | StoreStaff |
| POST | /coop/special-orders/{id}/confirm | Member confirms a quote; charges a deposit from wallet | Member |
| POST | /coop/special-orders/{id}/fulfill | Place with vendor, receive, and hand over | StoreStaff |
| POST | /coop/special-orders/{id}/cancel | Cancel a special order; refunds any deposit | Member, StoreStaff |
| POST | /coop/purchases | Ring up a retail purchase | StoreStaff |
| GET | /coop/purchases | List/filter purchases | Member, StoreStaff, CoopAdmin |
| GET | /coop/purchases/{id} | Read a purchase | Member, StoreStaff, CoopAdmin |
| POST | /coop/purchases/{id}/refund | Refund a completed purchase | StoreStaff |
| POST | /coop/dividend-declarations | Create a draft dividend declaration for a fiscal year | CoopAdmin |
| GET | /coop/dividend-declarations/{id} | Read a dividend declaration | Member, StoreStaff, CoopAdmin |
| POST | /coop/dividend-declarations/{id}/finalize | Finalize dividends; credit eligible members' wallets | CoopAdmin |
| POST | /_clock/set_current_utc | Set the server logical clock (test-driving) | Public — no authentication required (CoopAdmin nominal, not enforced) |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_MEMBER_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_RENTAL_UNIT_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_TRIP_NOT_FOUND | 404 |
| ERR_GUIDE_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_TRADE_IN_NOT_FOUND | 404 |
| ERR_REPAIR_ORDER_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_PURCHASE_NOT_FOUND | 404 |
| ERR_DECLARATION_NOT_FOUND | 404 |
| ERR_PASS_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_TRIP_NOT_OPEN | 409 |
| ERR_MEMBERSHIP_NOT_ACTIVE | 409 |
| ERR_RENTAL_UNIT_UNAVAILABLE | 409 |
| ERR_GUIDE_NOT_CERTIFIED | 409 |
| ERR_RENTAL_WINDOW_CONFLICT | 409 |
| ERR_GUIDE_SCHEDULE_CONFLICT | 409 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_TRIP_FULL | 409 |
| ERR_INVALID_QUANTITY | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_TRADE_IN_ROUNDS_EXCEEDED | 409 |
| ERR_INSUFFICIENT_POINTS | 402 |
| ERR_INSUFFICIENT_WALLET | 402 |
| ERR_REPAIR_UNSETTLED | 409 |
