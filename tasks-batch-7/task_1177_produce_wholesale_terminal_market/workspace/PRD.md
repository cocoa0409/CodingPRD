# Produce Terminal Market API — Product Requirements Document

## 1. Introduction

This document specifies the REST API that powers a produce wholesale and terminal market operation, modeled on the daily rhythm of a Hunts Point–style terminal. The system coordinates the full life of a purchased lot — from the morning's posted price report through receiving, federal grade inspection, possible dispute, cold-chain monitoring, ripening-room scheduling, shrink and credit accounting, and finally the customer-facing order, invoicing, and PACA-governed settlement cycle. Because wholesale produce operates under the Perishable Agricultural Commodities Act, money owed to growers is held in a statutory trust; the platform therefore treats every lot's payable exposure and every buyer's outstanding credit as first-class, continuously recomputed aggregates rather than as occasional reports.

Two kinds of pressure shape the design. The first is time pressure: orders must respect a next-day cut-off, ripening bookings occupy rooms within strict half-open intervals, invoices roll from `OPEN` to `PAST_DUE` to `TRUST_CLAIMED` against a logical clock, and unused bookings expire. The second is compliance pressure: a cold-chain violation on a lot must immediately quarantine every order that touches it; a disputed grade finding must suspend cost finalization until a MarketAdmin rules; and a buyer whose invoice ages more than thirty days past due must be suspended and have their confirmed orders held for credit. The API is the single source of truth for both pressures, and every mutation returns its cascaded side effects inside the same response so that operators see the full consequence of an action before moving on.

The audience for this document is the engineer implementing the service. §2 lays out system-wide contracts (auth, envelope, pagination, identifiers, precision, concurrency). §3 walks the business workflows in narrative form, deliberately spreading rules across the subsections where they naturally arise. §4 is the endpoint reference table. §5 is the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, if the role string is not one of the declared roles, or — for the entity-backed role below — if the supplied user id does not resolve to an existing `Customer`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not authorized for the endpoint, or if a `CustomerRep` attempts to touch a resource owned by another customer, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). These two auth checks run before every other validation, in that order.

The declared role names, spelled exactly as the server must match them, are: `MarketAdmin`, `Receiver`, `USDAInspector`, `SalesDesk`, `BillingClerk`, and `CustomerRep`.

Identity semantics differ by role. When `X-User-Role` is `MarketAdmin`, `Receiver`, `USDAInspector`, `SalesDesk`, or `BillingClerk`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it against any entity's `id`. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (orders, invoices, reverse-lookup listings) compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. A `CustomerRep` may create orders only for their own `customer_id` and may cancel only their own orders while those orders are still `PENDING`; the shared `SalesDesk` cancel path covers the broader state set.

Segregation of duties is enforced by role assignment rather than by user identity. The `Receiver` files shrink records but may not approve them; only `MarketAdmin` approves. The `BillingClerk` posts invoices, payments, and credit-memo voids but cannot adjust customer terms. The `SalesDesk` confirms orders but cannot rule on disputes or void memos.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. List responses always include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` block. Default sort order on every list endpoint is `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted entity has an `id` field — a server-minted UUID with no type prefix. Entities that carry the common field set also expose `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that entity, including mutations driven by system cascades. The two exceptions are `TemperatureReading` and `Payment`: both are append-only ledger-style rows and carry only `id` and `created_at`; they have neither `updated_at` nor `version`.

The server maintains a logical clock that is the source of truth for every time-sensitive rule: order cut-off, invoice due dates, ripening start/expiry, and all `*_at` stamps such as `received_at`, `issued_at`, `voided_at`, and `paid_at`. At server start the logical clock is exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. An admin-only test-driving capability moves the logical clock forward to a supplied `to_iso8601` instant; the response reports the new `current_utc`. Cut-off, due-date, booking, and expiry rules all read this clock.

### 2.5. Money, Precision, and Rounding

All monetary amounts are stored and returned as integer cents. Every intermediate multiplication that crosses from dollars to cents rounds half-up to integer cents. Unit prices used inside the defect-discount formula round half-up to four decimal places before being multiplied by quantity. Percentages (defects, early-pay discount) are numbers — `defect_pct` ranges from 0 to 100, and the early-pay discount rate is two percent of the invoice `total_cents`. No calculation anywhere in the system uses banker's rounding or truncates.

### 2.6. PACA Trust and Credit Exposure Ledgers

Two derived aggregates are recomputed eagerly after every mutation that could affect them, and are always returned in their current state.

A `Shipper`'s `trust_exposure_cents` is the sum of `payable_cents` over all of that shipper's lots whose `status` is one of `ORDERED`, `RECEIVED`, `INSPECTED`, `DISPUTED`, or `ACCEPTED`. Lots in `REJECTED` or `CLOSED` drop out of the exposure set entirely.

A `Customer`'s `credit_exposure_cents` is the sum of `balance_cents` over that customer's invoices in `OPEN`, `PAST_DUE`, or `TRUST_CLAIMED`, plus the sum of `subtotal_cents` over that customer's orders in `CONFIRMED`, `ON_HOLD`, `PICKED`, or `DELIVERED`. Orders in `CANCELLED` or `INVOICED` are excluded.

Both aggregates are recomputed (never delta-adjusted) on every contributing event so the values can always be reconstructed from the underlying rows.

### 2.7. Optimistic Concurrency on Customer Terms

Updating a customer's credit terms or status is the single write path guarded by optimistic concurrency. The request must carry `expected_customer_version`, a non-optional field holding the `Customer.version` value the caller last observed. If the value does not match the server's current `Customer.version` — because another writer has advanced the customer since the caller last read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; there is no OCC on lots, orders, invoices, or bookings.

### 2.8. Validation Priority Order

When more than one validation could reject a request, the server evaluates checks in a fixed priority order and surfaces the first failure. The order, from first to last, is: authentication (`ERR_UNAUTHENTICATED`); authorization (`ERR_FORBIDDEN`); request shape and field types (`ERR_VALIDATION`); existence of path ids and body foreign keys, validated left-to-right with path parameters first (`ERR_NOT_FOUND`); the target entity's own state legality (`ERR_INVALID_STATE`, including the specialized `ERR_INVOICE_EXISTS` and `ERR_INSPECTION_OPEN` variants where they apply); cross-entity state gates such as customer active status and lot acceptance (`ERR_CUSTOMER_INACTIVE`, `ERR_LOT_NOT_ACCEPTED`); cold-chain and ethylene safety (`ERR_COLD_CHAIN_VIOLATION`, `ERR_ETHYLENE_CONFLICT`); temporal rules (`ERR_CUTOFF_PASSED`, `ERR_ROOM_OVERLAP`, `ERR_WINDOW_OVERLAP`); domain constraints (`ERR_PRICE_NOT_POSTED`, `ERR_DUPLICATE_PRICE`, `ERR_PRICE_OUT_OF_RANGE`, `ERR_ROOM_CAPACITY`, `ERR_INSUFFICIENT_QUANTITY`, `ERR_TERMS_EXCEEDED`); and finally money gates (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_OVERPAYMENT`), which always run last.

### 2.9. Cascades and Compensating Actions

Every mutation returns with all of its cascades already applied; there are no eventual-consistency windows. When a single event mutates several entities — a cold-chain violation that holds orders, a shrink approval that issues a credit memo, a dispute resolution that voids a pending inspection — the response to the triggering request reflects every hop. Compensating actions exist where the business demands them: voiding an `ISSUED` credit memo restores the lot's `payable_cents` to exactly `adjusted_cost_cents` minus the remaining `ISSUED` memos, and a `CREDIT` hold on an order can be released back to `CONFIRMED` once the cause is cleared.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Market: Shippers, Customers, Commodities, and the Daily Price Sheet

Before any lot can change hands, the `MarketAdmin` office registers the participants and the product catalogue. A shipper is registered with its legal `name` and `paca_license`; the shipper's `status` starts at `ACTIVE` and its `trust_exposure_cents` starts at 0. A customer is registered with `name`, `credit_limit_cents`, an optional `terms_days` (defaulting to 10), and an optional `paca_special_agreement` flag (defaulting to false). PACA prompt-payment rules cap `terms_days` at 30 unless the buyer has a written special agreement on file; a create or update that sets `terms_days` greater than 30 while `paca_special_agreement` is false is rejected with `ERR_TERMS_EXCEEDED`. A customer's `status` begins at `ACTIVE`; the only path to `SUSPENDED` is the day-close trust-claim cascade described in §3.7, and only `MarketAdmin` can restore a suspended customer.

A commodity is registered with a unique `code` (for example `TOM-GRN`), a display `name`, an `ethylene_class` drawn from `PRODUCER`, `SENSITIVE`, or `NEUTRAL`, the cold-chain band `temp_min_f` and `temp_max_f` in Fahrenheit, and an optional `max_violation_minutes` (defaulting to 60). The ethylene class drives the ripening-room conflict rules in §3.5; the temperature band and tolerance drive the cold-chain accumulation in §3.3.

Each trading day begins when the office posts the price sheet. Posting a daily price requires `commodity_id`, `market_date` (in `YYYY-MM-DD` form), `low_price`, and `high_price`. The server computes `mid_price` as the arithmetic mean of `low_price` and `high_price`, rounded half-up to two decimal places. Only one price row may exist per `(commodity_id, market_date)` pair; a duplicate post is rejected with `ERR_DUPLICATE_PRICE` (HTTP 409). The price sheet is the gate for the purchase desk: a lot cannot be created for a `(commodity_id, market_date)` that has no posted row — such a create fails with `ERR_PRICE_NOT_POSTED` — and the agreed `shipper_unit_price` must lie within the day's `[low_price, high_price]` band, inclusive on both ends, or the create is rejected with `ERR_PRICE_OUT_OF_RANGE`.

### 3.2. Buying and Receiving a Lot

A `Receiver` buys at the terminal by naming the `shipper_id`, `commodity_id`, `market_date`, `quantity_units`, `shipper_unit_price`, and the manifest's `declared_grade`. `quantity_units` must be a positive integer. The new lot is created in `ORDERED` status. At creation the server computes the **provisional landed cost**: `provisional_cost_cents` is `quantity_units` multiplied by `shipper_unit_price` multiplied by 100, rounded half-up to integer cents. Until a final-cost event runs, both `adjusted_cost_cents` and `payable_cents` are initialized equal to `provisional_cost_cents`. The lot's `dumped_units`, `reserved_units`, and `sold_units` all start at 0, so `available_units` starts equal to `quantity_units`. Its `cold_chain_status` starts at `OK` with `violation_minutes` at 0. Creating the lot also pulls its `payable_cents` into the shipper's `trust_exposure_cents`.

Physical receipt is a separate step. Receiving transitions the lot from `ORDERED` to `RECEIVED`, stamps `received_at` from the logical clock, and increments the lot's `version`. A receive attempted on a lot that is not `ORDERED` is rejected as `ERR_INVALID_STATE`.

### 3.3. Cold-Chain Surveillance and the Violation Cascade

Throughout a lot's life on the floor, the `Receiver` appends probe readings carrying `purchase_lot_id`, `recorded_at`, `temp_f`, and `duration_minutes` (strictly positive). For each reading the server determines `out_of_range` by comparing `temp_f` against the commodity's band: a reading is out of range when `temp_f` is strictly below `temp_min_f` or strictly above `temp_max_f`. The lot's `violation_minutes` is the cumulative sum of `duration_minutes` across all out-of-range readings on that lot. The metric is cumulative and never resets — repeated short excursions add up, and there is no time window beyond which old readings expire.

The violation flip is a strict inequality: the lot's `cold_chain_status` becomes `VIOLATED` only when `violation_minutes` becomes strictly greater than the commodity's `max_violation_minutes`. A lot whose cumulative minutes exactly equal the tolerance remains `OK`.

The flip fires a three-hop cascade. Hop one: the lot's `cold_chain_status` becomes `VIOLATED` and its `version` increments. Hop two: every `SalesOrder` that has a line on this lot and is currently `CONFIRMED` moves to `ON_HOLD` with `hold_reason` set to `COLD_CHAIN`. Hop three: each held order releases its line reservations — for every line, the lot's `reserved_units` decreases by the line quantity and `available_units` is recomputed. The cascade is visible in the same response that posted the triggering reading.

A `COLD_CHAIN` hold is terminal for the order's confirm path. Unlike a `CREDIT` hold, a cold-chain hold cannot be released back to `CONFIRMED`; the only way out is cancellation.

### 3.4. USDA Inspection, Grade Disputes, and Final Cost

Once a lot is `RECEIVED` (or has looped back to `DISPUTED`, as described below), a `USDAInspector` files an inspection carrying `purchase_lot_id`, the observed `inspected_grade`, the `defect_pct`, and the `result` — either `PASS` or `FAIL`. Filing the inspection creates the `Inspection` row in `SUBMITTED` status and simultaneously transitions the lot from `RECEIVED` (or `DISPUTED`) into `INSPECTED`, incrementing the lot's `version`. Only one inspection may be open at a time per lot: attempting to file while another inspection for the same lot is still `SUBMITTED` is rejected with `ERR_INSPECTION_OPEN`.

Certifying a `SUBMITTED` inspection is a separate `USDAInspector` action. The preconditions are that the inspection is `SUBMITTED` and the lot is `INSPECTED`. The behavior then branches on the inspection's `result`:

- When the result is `PASS`, the inspection becomes `CERTIFIED` and the lot transitions `INSPECTED → ACCEPTED`. The final landed cost runs: if the certified `defect_pct` is less than or equal to 5, `adjusted_cost_cents` remains equal to `provisional_cost_cents`; otherwise the defect-discount formula applies. The defect-discount formula computes a final unit price by taking the shipper's unit price, multiplying it by one minus the excess-defect fraction (the excess being `defect_pct` minus 5, divided by 100), rounding that unit price half-up to four decimal places, then multiplying by `quantity_units` and by 100 and rounding half-up to integer cents to obtain the new `adjusted_cost_cents`. `payable_cents` is then recomputed as `adjusted_cost_cents` minus the sum of `ISSUED` credit memos on the lot, and the shipper's `trust_exposure_cents` is recomputed.
- When the result is `FAIL`, the inspection still becomes `CERTIFIED`, but the lot remains `INSPECTED`; the dispute itself is a separate `Receiver` action, not an automatic transition.

A `Receiver` opens a grade/pack dispute on an `INSPECTED` lot only when a `CERTIFIED` inspection with `result` equal to `FAIL` exists for that lot. Opening the dispute moves the lot from `INSPECTED` to `DISPUTED` and increments the lot's `version`. An optional free-text `reason` may accompany the filing.

Ruling on a dispute belongs to `MarketAdmin`. The ruling request carries an `outcome`, and carries `agreed_unit_price` when (and only when) the outcome is `PRICE_ADJUST`. Three outcomes are possible:

- `ACCEPT_AS_IS` moves the lot `DISPUTED → ACCEPTED`. The existing `adjusted_cost_cents` (whatever it was at the time) stands; `payable_cents` is recomputed against `ISSUED` memos; the shipper's `trust_exposure_cents` is recomputed.
- `PRICE_ADJUST` also moves the lot `DISPUTED → ACCEPTED`, but first recomputes `adjusted_cost_cents` as `quantity_units` multiplied by `agreed_unit_price` multiplied by 100, rounded half-up to integer cents. `payable_cents` and `trust_exposure_cents` follow.
- `REJECT_TO_SHIPPER` moves the lot `DISPUTED → REJECTED`. The lot's `payable_cents` is set to 0 (rejecting the lot wipes the shipper's claim on it), and the shipper's `trust_exposure_cents` is recomputed. As a compensating cascade, any `Inspection` still in `SUBMITTED` for this lot is voided — its status flips to `VOIDED` — preserving the invariant that a `REJECTED` lot never has an open inspection.

A re-inspection loop is supported: from `DISPUTED`, a `USDAInspector` may file a fresh inspection (provided none is currently `SUBMITTED` for the lot), which moves the lot back to `INSPECTED`; the `INSPECTED → DISPUTED → INSPECTED` cycle may repeat across multiple rounds.

An `ACCEPTED` lot is closed by the `Receiver` once no ripening booking for the lot is still `SCHEDULED` or `IN_PROCESS`. Closing transitions the lot to `CLOSED`, increments its `version`, and removes its `payable_cents` from the shipper's `trust_exposure_cents` going forward. A close attempted while an active booking remains is `ERR_INVALID_STATE`.

### 3.5. Ripening-Room Scheduling and Ethylene Safety

Ripening rooms are registered with a `name`, a `capacity_pallets`, and an `ethylene_capable` flag. A `Receiver` schedules a booking by naming `room_id`, `purchase_lot_id`, `pallet_count` (strictly positive), `start_time`, `end_time`, an `ethylene_enabled` flag, and a `target_stage` such as `STAGE_4`. The end must be strictly after the start. The lot must not be `REJECTED` or `CLOSED`.

Three guards run at scheduling time, in the temporal-and-safety band of the priority order. First, **overlap**: a new booking is rejected with `ERR_ROOM_OVERLAP` if its interval intersects any other active booking's buffer-inflated interval on the same room. Active means `SCHEDULED` or `IN_PROCESS`. The inflation extends each active booking's interval by two hours on both ends — the protected interval runs from two hours before its `start_time` to two hours after its `end_time`, half-open at the end. Touching at an inflated boundary is allowed. Second, **ethylene conflict**: if the new booking has `ethylene_enabled` true and its own (uninflated) interval overlaps an active booking whose lot's commodity is `SENSITIVE`, the create is rejected with `ERR_ETHYLENE_CONFLICT`. Symmetrically, if the new booking's lot is `SENSITIVE` and its interval overlaps an active booking with `ethylene_enabled` true, the create is likewise rejected with `ERR_ETHYLENE_CONFLICT`. Third, **capacity**: the sum of `pallet_count` across all active bookings whose intervals overlap the new one, plus the new booking's `pallet_count`, must be less than or equal to the room's `capacity_pallets`; equality is permitted, and exceeding it yields `ERR_ROOM_CAPACITY`.

A booking's life cycle runs `SCHEDULED → IN_PROCESS → COMPLETED`. Starting requires that the booking is `SCHEDULED`, that the lot is `ACCEPTED` (otherwise `ERR_LOT_NOT_ACCEPTED`), and that the logical clock is inside the half-open interval `[start_time, end_time)` — starting too early or too late is `ERR_INVALID_STATE`. Completing requires the booking be `IN_PROCESS`. Cancelling is allowed only from `SCHEDULED`; a cancelled booking leaves the active set, so its `pallet_count` no longer counts toward the room-capacity invariant. Each of these transitions increments the booking's `version`. A booking that was never started and whose `end_time` has passed is moved to `EXPIRED` by the day-close ops run described in §3.7.

### 3.6. Customer Orders, Credit Gates, and Delivery Windows

Order capture is shared between the house `SalesDesk` and buyer-side `CustomerRep` callers, with the representative restricted to their own `customer_id`. An order is created with `customer_id`, `delivery_date`, `window_start`, `window_end`, an optional `pallet_count` (defaulting to 1), and a non-empty `lines` array, each line naming a `lot_id`, a positive integer `quantity`, and a positive dollar `unit_price`. The order is created in `PENDING`.

Two temporal rules guard order creation. First, the cut-off: a `delivery_date` on or before the current clock date is rejected with `ERR_CUTOFF_PASSED`; so is a `delivery_date` exactly one day ahead when the clock time is strictly after 14:00:00 — exactly 14:00:00 itself is still allowed. Second, the per-customer delivery-window rule: on the same `delivery_date`, the new order's half-open window `[window_start, window_end)` must not intersect the window of any of the customer's existing orders that are neither `CANCELLED` nor `INVOICED`; an intersection is `ERR_WINDOW_OVERLAP`. Adjacency is allowed — an existing `[08:00,10:00)` followed by a new `[10:00,12:00)` passes. `window_end` must be strictly after `window_start` as a shape-level rule.

The order's `subtotal_cents` is computed at creation and is immutable thereafter. The rounding order is pinned: each line is first extended by multiplying its `unit_price` by its `quantity` and by 100, rounding half-up to integer cents; then those per-line amounts are summed to produce `subtotal_cents`. Summing the raw products and rounding once at the end is explicitly not the rule — two lines of 2.505 × 1 yield 251 + 251 = 502, not 501.

Confirming an order is the exclusive province of `SalesDesk`. The confirm action accepts an order in `PENDING`, or one in `ON_HOLD` whose `hold_reason` is `CREDIT` — a `COLD_CHAIN` hold can only be cancelled, never confirmed. The preconditions, all enforced at confirm time, are: the customer's `status` must be `ACTIVE` (otherwise `ERR_CUSTOMER_INACTIVE`); the customer's `credit_exposure_cents` plus this order's `subtotal_cents` must be less than or equal to `credit_limit_cents` — equality is allowed, and strictly-greater overshoot is rejected as `ERR_CREDIT_LIMIT_EXCEEDED`; and every line must reference a lot in `ACCEPTED` status with `quantity` no greater than that lot's `available_units` (otherwise `ERR_LOT_NOT_ACCEPTED` or `ERR_INSUFFICIENT_QUANTITY`). On success, each line reserves its quantity on the lot (`reserved_units` increases by the line quantity, `available_units` recomputes), `hold_reason` is cleared, the customer's `credit_exposure_cents` is recomputed, and the order's `version` increments.

Once `CONFIRMED`, picking is a `Receiver` action. Picking requires that every line lot's `cold_chain_status` is `OK`; a violated lot blocks the pick with `ERR_COLD_CHAIN_VIOLATION`. Picking moves the order to `PICKED`. Delivering, also a `Receiver` action, applies the same cold-chain gate and moves the order to `DELIVERED`; on delivery each line's quantity is moved out of `reserved_units` and into `sold_units` on the lot, `available_units` recomputes, and the customer's `credit_exposure_cents` is recomputed.

Cancellation is valid from `PENDING`, `CONFIRMED`, or `ON_HOLD`. The `SalesDesk` may cancel any such order; a `CustomerRep` may cancel only their own orders and only while they are `PENDING`. Cancelling a `CONFIRMED` or `ON_HOLD` order releases each line's reservation (the lot's `reserved_units` decreases and `available_units` recomputes). Cancelling from any of the three states recomputes the customer's `credit_exposure_cents` and increments the order's `version`. Cancelling a `DELIVERED` or later order is `ERR_INVALID_STATE`.

### 3.7. Invoicing, PACA Settlement, and the Day-Close Ops Run

Once an order is `DELIVERED`, the `BillingClerk` invoices it by naming the `sales_order_id`. Exactly one invoice may exist per order; attempting to invoice an already-`INVOICED` order is rejected with `ERR_INVOICE_EXISTS`. Issuance stamps `invoice_date` from the logical clock, copies the customer reference and the order's `subtotal_cents`, computes `deposit_cents` as the order's `pallet_count` multiplied by 2500 cents (a refundable $25.00 per pallet), and sets `total_cents` to the sum of `subtotal_cents` and `deposit_cents`. The `due_date` is `invoice_date` plus the customer's `terms_days`, with the terms snapshotted at issuance — a later terms change on the customer does not move an already-issued due date. The `discount_eligible_until` date is `invoice_date` plus 5 days. The invoice is created in `OPEN`, with `discount_taken_cents` and `paid_cents` at 0 and `balance_cents` equal to `total_cents`. Creating the invoice also flips the order from `DELIVERED` to `INVOICED` and recomputes the customer's `credit_exposure_cents`.

Payments are posted by the `BillingClerk` against a single invoice with `invoice_id` and a positive `amount_cents`. Posting requires the invoice to be in `OPEN`, `PAST_DUE`, or `TRUST_CLAIMED` — a payment on a `PAID` invoice is `ERR_INVALID_STATE`. The early-pay discount is earned on the first payment whose paid date is on or before `discount_eligible_until` (the boundary is inclusive), and only when no discount has yet been taken: in that case `discount_taken_cents` becomes `total_cents` multiplied by two percent, rounded half-up to integer cents. The payment is rejected with `ERR_OVERPAYMENT` when `amount_cents` exceeds the `balance_cents` that would remain after any earned discount. On success, `paid_cents` increases by `amount_cents`, `balance_cents` recomputes as `total_cents` minus `discount_taken_cents` minus `paid_cents`, and the invoice moves to `PAID` exactly when `balance_cents` reaches 0. The customer's `credit_exposure_cents` is recomputed.

The day-close ops run is an admin-only checkpoint that reads the current logical clock and applies three sweeps, returning the counts of `invoices_marked_past_due`, `invoices_trust_claimed`, and `bookings_expired`. First, every `OPEN` invoice whose `due_date` is strictly before the clock date and whose `balance_cents` is still positive becomes `PAST_DUE`; an invoice whose clock date equals its `due_date` exactly remains `OPEN` — the comparison is strict. Second, every `PAST_DUE` invoice whose clock date is more than 30 days past its `due_date` and whose `balance_cents` is still positive becomes `TRUST_CLAIMED`; the trust claim suspends the customer (`status` becomes `SUSPENDED`), moves every `CONFIRMED` order belonging to that customer to `ON_HOLD` with `hold_reason` set to `CREDIT`, releases those orders' line reservations, and recomputes the customer's `credit_exposure_cents`. Third, every `SCHEDULED` ripening booking whose `end_time` is strictly earlier than the clock becomes `EXPIRED`.

### 3.8. Shrink, Credit Memos, and Payable Reconciliation

Shrink on an `ACCEPTED` lot is recorded by the `Receiver` with `purchase_lot_id`, a positive integer `quantity`, and a `reason` of `DUMP`, `TRIM`, `DAMAGE`, or `THEFT`. The record is created in `DRAFT`; no financial consequence flows until approval.

Approval is segregated: only `MarketAdmin` may approve, and the approval is rejected with `ERR_INSUFFICIENT_QUANTITY` if the shrink's `quantity` exceeds the lot's `available_units` at approval time. On approval the record moves `DRAFT → APPROVED` and a two-hop cascade fires. Hop one: a `CreditMemo` is created in `ISSUED` status with `issued_at` stamped from the logical clock, its `amount_cents` computed as `adjusted_cost_cents` multiplied by the shrink `quantity` divided by the lot's `quantity_units`, rounded half-up to integer cents, and the shrink record's `credit_memo_id` is set to point at it. Hop two: the lot's `dumped_units` increases by the shrink quantity, `payable_cents` recomputes as `adjusted_cost_cents` minus the sum of `ISSUED` memos on the lot, `available_units` recomputes, and the shipper's `trust_exposure_cents` is recomputed.

A `BillingClerk` may void an `ISSUED` memo. Voiding stamps `voided_at`, flips the memo to `VOID`, increments the memo's `version`, recomputes the lot's `payable_cents` against the remaining `ISSUED` memos, and recomputes the shipper's `trust_exposure_cents`. This is the compensating action for the approval cascade: approving a shrink and then voiding its memo restores `payable_cents` exactly.

The reconciling invariant, maintained after every operation in this section, is that for any non-`REJECTED` lot, `payable_cents` plus the sum of its `ISSUED` memo amounts equals `adjusted_cost_cents`. For a `REJECTED` lot, `payable_cents` is pinned at 0 regardless of memos.

### 3.9. Cross-Dock and Repack Labor

Labor on a lot is recorded by the `Receiver` with `purchase_lot_id`, a `ticket_type` of `HOURLY` or `PIECE`, a `work_date`, positive `hours`, and the rate fields matching the ticket type: `hourly_rate` is required for `HOURLY`, while `pieces` and `piece_rate` are required for `PIECE` (and `pieces` is ignored on an `HOURLY` ticket). The ticket's `charge_cents` is computed once at creation and is immutable thereafter.

For an `HOURLY` ticket, the first 8 hours are paid straight at `hourly_rate`; any hours beyond 8 are paid at one and a half times `hourly_rate`. The total dollar pay is converted to cents and rounded half-up to integer cents.

For a `PIECE` ticket, the piece pay is `pieces` multiplied by `piece_rate`. A guaranteed minimum floor applies: the crew earns at least `hours` multiplied by 15.00 dollars, no matter how few pieces were produced. The charge is the greater of piece pay and the guaranteed minimum, converted to cents and rounded half-up. Identical `hours`, `pieces`, and rate numbers can therefore produce a different charge under the two variants, which is why the ticket type is part of the input rather than inferred.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 and the newly minted resource in `data`. State transitions, modifications, and ops-run actions return HTTP 200 and the updated resource (or the ops summary payload) in `data`. All list endpoints return HTTP 200 with the envelope pagination block described in §2.2 and §2.3. Errors always use the error envelope with the appropriate 4xx code from §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /market/shippers | Register a shipper/grower | MarketAdmin |
| GET | /market/shippers/{id} | Fetch one shipper | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/customers | Register a buyer; `terms_days` over 30 requires `paca_special_agreement` | MarketAdmin |
| GET | /market/customers/{id} | Fetch one customer | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| PATCH | /market/customers/{id} | Update credit terms / status; OCC via `expected_customer_version` | MarketAdmin |
| GET | /market/customers/{id}/sales-orders | List orders of a customer | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| GET | /market/customers/{id}/invoices | List invoices of a customer | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/commodities | Register a commodity with cold-chain band and ethylene class | MarketAdmin |
| GET | /market/commodities/{id} | Fetch one commodity | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/daily-prices | Post the daily price line for a commodity; one per (commodity, date) | MarketAdmin |
| GET | /market/daily-prices/{id} | Fetch one daily price row | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| GET | /market/daily-prices | List daily prices, filterable by `commodity_id` and `market_date` | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/purchase-lots | Buy a lot at the terminal; requires a posted price for the day | Receiver |
| GET | /market/purchase-lots | List lots, filterable by `shipper_id`, `commodity_id`, `status`, `market_date` | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| GET | /market/purchase-lots/{id} | Fetch one lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/purchase-lots/{id}/receive | Mark an `ORDERED` lot `RECEIVED` | Receiver |
| POST | /market/purchase-lots/{id}/dispute | Open a grade/pack dispute after a `FAIL` inspection | Receiver |
| POST | /market/purchase-lots/{id}/resolve-dispute | Rule on an open dispute | MarketAdmin |
| POST | /market/purchase-lots/{id}/close | Close an `ACCEPTED` lot once no active bookings remain | Receiver |
| POST | /market/inspections | File a USDA grade/pack inspection | USDAInspector |
| GET | /market/purchase-lots/{id}/inspections | List inspections of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/inspections/{id}/certify | Certify a `SUBMITTED` inspection | USDAInspector |
| POST | /market/temperature-readings | Append a cold-chain probe record | Receiver |
| GET | /market/purchase-lots/{id}/temperature-readings | List probe records of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/ripening-rooms | Register a ripening room | MarketAdmin |
| GET | /market/ripening-rooms/{id} | Fetch one room | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| GET | /market/ripening-rooms/{id}/ripening-bookings | List bookings of a room | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/ripening-bookings | Schedule a lot into a room | Receiver |
| GET | /market/purchase-lots/{id}/ripening-bookings | List bookings of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/ripening-bookings/{id}/start | Begin a `SCHEDULED` booking | Receiver |
| POST | /market/ripening-bookings/{id}/complete | Finish an `IN_PROCESS` booking | Receiver |
| POST | /market/ripening-bookings/{id}/cancel | Cancel a `SCHEDULED` booking | Receiver |
| POST | /market/shrink-records | Record shrink/dump on an `ACCEPTED` lot | Receiver |
| GET | /market/purchase-lots/{id}/shrink-records | List shrink records of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/shrink-records/{id}/approve | Approve a `DRAFT` shrink record and issue the credit memo | MarketAdmin |
| GET | /market/purchase-lots/{id}/credit-memos | List credit memos of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/credit-memos/{id}/void | Void an `ISSUED` credit memo | BillingClerk |
| POST | /market/sales-orders | Create a customer order with lines | SalesDesk, CustomerRep |
| GET | /market/sales-orders/{id} | Fetch one order | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/sales-orders/{id}/confirm | Confirm a `PENDING` order or release a `CREDIT`-held one | SalesDesk |
| POST | /market/sales-orders/{id}/pick | Pick a `CONFIRMED` order | Receiver |
| POST | /market/sales-orders/{id}/deliver | Deliver a `PICKED` order | Receiver |
| POST | /market/sales-orders/{id}/cancel | Cancel a `PENDING`/`CONFIRMED`/`ON_HOLD` order | SalesDesk, CustomerRep |
| POST | /market/invoices | Invoice a `DELIVERED` order | BillingClerk |
| GET | /market/invoices/{id} | Fetch one invoice | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| GET | /market/sales-orders/{id}/invoices | List invoices of an order (0 or 1 entries) | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/payments | Post a customer payment against one invoice | BillingClerk |
| GET | /market/invoices/{id}/payments | List payments of an invoice | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /market/labor-tickets | Record cross-dock/repack labor on a lot | Receiver |
| GET | /market/purchase-lots/{id}/labor-tickets | List labor tickets of a lot | MarketAdmin, Receiver, USDAInspector, SalesDesk, BillingClerk, CustomerRep |
| POST | /_clock/set_current_utc | Advance the logical clock to `to_iso8601` | MarketAdmin |
| POST | /market/ops/run-day-close | Run the day-close checkpoint at the current logical clock | MarketAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 422 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PRICE_NOT_POSTED | 422 |
| ERR_DUPLICATE_PRICE | 409 |
| ERR_PRICE_OUT_OF_RANGE | 422 |
| ERR_INSPECTION_OPEN | 409 |
| ERR_COLD_CHAIN_VIOLATION | 409 |
| ERR_ETHYLENE_CONFLICT | 409 |
| ERR_ROOM_OVERLAP | 409 |
| ERR_ROOM_CAPACITY | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_CUTOFF_PASSED | 422 |
| ERR_CUSTOMER_INACTIVE | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 422 |
| ERR_INSUFFICIENT_QUANTITY | 422 |
| ERR_LOT_NOT_ACCEPTED | 409 |
| ERR_OVERPAYMENT | 422 |
| ERR_TERMS_EXCEEDED | 422 |
| ERR_INVOICE_EXISTS | 409 |
