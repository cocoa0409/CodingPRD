# Hydroponics & Indoor-Garden Store API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Hydroponics & Indoor-Garden Store API, the transactional backbone of a specialty retailer that sells complete grow systems, lighting rigs, regulated nutrients, and everyday consumables while also running a services business around them. A single store serves two very different buyers at once: walk-in retail hobbyists who place one-off orders, subscribe to consumables, book design consults, and attend workshops; and commercial growers who buy on credit against a negotiated account with tiered pricing. Behind both sits a finite, lot-tracked inventory that must be reserved, consumed, released, and replenished with exacting consistency.

The system is deliberately built around several hard problems that are easy to get subtly wrong: a finite pool of stock spread across dated inventory lots that must be allocated in a fixed, deterministic order; a pricing engine that produces a *provisional* total at order placement and a possibly different *final* total at ship time; store credit that draws down against a commercial account's limit and must never be corrupted by a client acting on a stale view of that account; warranty-bounded returns that restock goods and refund store credit; and a scheduling layer for consultants and workshop rooms that must respect buffers, capacity, and double-booking rules. Every monetary figure is carried in integer cents, and every derived quantity — available stock, credit used, seats taken — is kept continuously reconciled with the events that move it.

The remainder of this document defines the global contracts every endpoint honours (Section 2), the domain workflows and their business rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `StoreAdmin`, `Customer`, `CommercialBuyer`, and `Consultant`.

A `StoreAdmin` is the store operator. Their `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and may record it in an audit sense, but it never compares it to any entity's `id`. Store administrators manage the catalog, inventory, customers, commercial accounts, consultants, rooms, workshop sessions, order fulfillment (shipping and refunds), and all RMA decisions.

A `Customer` is a retail buyer. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A customer may place and pay for retail orders, subscribe to consumables, book consults, register for workshops, submit returns, and provide requested return information — always against their own records.

A `CommercialBuyer` is a business buyer acting on behalf of a commercial account. When `X-User-Role` is `CommercialBuyer`, `X-User-ID` is the `id` of the acting `CommercialAccount`; placing a commercial order requires the account named in the path to be the very account identified by `X-User-ID`, and any read of an account or its orders is likewise scoped to the account the buyer owns.

A `Consultant` is a design consultant acting on their own bookings. When `X-User-Role` is `Consultant`, `X-User-ID` is the `id` of the acting `Consultant`; completing a booking is permitted only when the booking's `consultant_id` equals `X-User-ID`, and a consultant may list only their own bookings.

Whenever an entity-backed principal (`Customer`, `CommercialBuyer`, or `Consultant`) targets a resource they do not own, the request is rejected with `ERR_OWNERSHIP_REQUIRED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` outside the 1–100 range, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_VALIDATION`.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp in ascending order, with the server-side order in which resources were created serving as a stable tiebreaker when two resources share the same creation timestamp. Beyond pagination, several list endpoints accept exact-match filter query parameters — orders by `customer_id`, `commercial_account_id`, and `status`; subscriptions by `customer_id` and `product_id`; consult bookings by `consultant_id` and `customer_id`; workshop sessions by `room_id`; workshop registrations by `session_id` and `customer_id`; and RMAs by `order_id` and `product_id` — and any unrecognized query parameter is ignored.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in this system — products, inventory lots, customers, commercial accounts, orders, subscriptions, consultants, consult bookings, rooms, workshop sessions, workshop registrations, and RMAs — carries a system-managed set of fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at creation and increments by one on every mutation.

Because a mutation includes not only direct edits but also the reconciliation of derived fields, any event that recomputes a resource's derived values — a product's `total_available_units` and `reorder_flag`, an account's `credit_used_cents`, a customer's `wallet_credit_cents`, `loyalty_points`, and `loyalty_tier`, a session's `seats_taken` — bumps that resource's `version` and refreshes its `updated_at`. Every entity in this catalogue carries the full common-field set; there are no create-only, version-less resources in this domain.

### 2.5. Monetary Values, Units, and Rounding

All money is stored and returned as integer cents; there are no fractional-cent values anywhere in the system. Where a calculation multiplies a rate against an amount and can produce a non-integer intermediate — a percentage discount, a prorated fee, a restocking deduction — the result is converted to whole cents using the round-half-up convention (ties round upward, away from zero) and the rounding is applied once to the aggregate, not per component, unless a workflow specifies otherwise. Point balances are likewise whole integers. Weights are carried in grams and converted to kilograms only inside the hazmat surcharge, described in Section 3.4. Durations are carried in whole minutes and converted to hours only inside the consult-fee calculation, described in Section 3.7.

### 2.6. The Logical Clock

The server keeps a logical clock that is the single source of "now" for every time-dependent rule: a subscription's next ship date, an order's ship timestamp, warranty windows, and the temporal windows used to detect consult and room conflicts all read this clock rather than wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and until an administrator explicitly sets it, it stays at that default and never falls back to real time. A `StoreAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field; this is a test-driving capability with no domain side effects beyond moving the reference time forward for all subsequent calculations.

### 2.7. Inventory, Lots, and Stock Consistency

Stock for a product is never a single number; it is spread across one or more **inventory lots**, each a dated batch received into the warehouse. A lot records `quantity_on_hand` (the physical units received), a computed `quantity_reserved` (units held for confirmed but unshipped orders, starting at 0), and a computed `quantity_available` equal to `quantity_on_hand` minus `quantity_reserved`. A lot also records a per-unit `unit_cost_cents` landed cost and a `status` of `ACTIVE`, `DEPLETED`, or `QUARANTINED`; lots start `ACTIVE`.

A product's stock-facing derived fields roll up from its lots. `total_available_units` is the sum of `quantity_available` across the product's lots whose `status` is `ACTIVE`; lots in any other status are excluded from that sum. `reorder_flag` is true exactly when `total_available_units` is strictly less than the product's `reorder_threshold`, and false otherwise. Both are recomputed immediately whenever any of the product's lots changes.

Whenever the system must reserve, consume, or release units for an order line, it walks the product's lots in a single deterministic order: by `created_at` ascending, and for lots created at the same instant, by `lot_code` ascending. The lot `id` is never used to break ties. This ordering is described in full as the allocation waterfall in Section 3.5.

A lot's `status` is driven purely by these side effects, never by a direct client call. When a reservation drives a lot's `quantity_available` down to exactly 0, the lot transitions `ACTIVE → DEPLETED` and drops out of the `total_available_units` aggregation. When a release or a restock lifts a depleted lot's `quantity_available` back above 0, the lot transitions `DEPLETED → ACTIVE` and re-enters the aggregation.

### 2.8. Optimistic Concurrency for Commercial Orders

Placing a commercial order draws down the buying account's available credit, and that draw can only be computed correctly against the exact account state the buyer last observed. To protect it, commercial order placement is guarded by optimistic concurrency control on the `CommercialAccount`. The placement request must carry `expected_commercial_account_version` holding the `version` of the target account the client last read. If that value does not equal the account's current `version` — because a prior commercial order already drew credit, or an administrator changed the account's tier or hold status in the meantime — the placement is rejected as stale with `ERR_STALE_VERSION` (HTTP 412). This check is the serialization point for concurrent draws against a shared credit line: the new order may be individually valid and would succeed against fresh state, so a state precondition alone cannot reject it; only the version comparison prevents the client from committing a draw it computed against an account it has not observed. No other endpoint in the system takes a version field, and commercial order placement is the only operation that requires one.

### 2.9. Request Validation Order and Nested Resource Resolution

Every request is validated in a fixed priority order, so that when several rules could reject the same request, the earliest-priority rule is the one whose error surfaces. The order is: first authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every referenced resource (`ERR_NOT_FOUND`), then body/field validity — required fields present and each value of the correct type, enum, and range (`ERR_VALIDATION`), then ownership of the target resource by an entity-backed actor (`ERR_OWNERSHIP_REQUIRED`), then the state legality of the requested transition (`ERR_INVALID_STATE`), and finally the domain-specific business rules described throughout Section 3.

When a path names more than one resource — for example a session and one of its registrations, or a product and one of its lots — the identifiers are resolved strictly left to right, and the request is rejected with `ERR_NOT_FOUND` at the first identifier in the path that does not correspond to an existing resource, before any deeper resource is examined.

## 3. Business Logic & Workflows

### 3.1. Catalog Products and Inventory Lots

A `StoreAdmin` seeds the catalog by creating a **product**, supplying a `sku_code` (a human SKU that must be unique across the catalog), a display `name`, a `category` of `SYSTEM`, `LIGHTING`, `NUTRIENT`, `CONSUMABLE`, or `ACCESSORY`, and a `unit_price_cents` list price that must be greater than zero. Several flags refine the product's behaviour: `is_hazmat` marks regulated goods (defaulting to false) that carry a shipping surcharge and can never be returned; `warranty_months` sets the warranty length in months from the ship date (defaulting to 0, and never negative); `is_subscribable` (defaulting to false) declares whether a consumable subscription may target the product; `reorder_threshold` (defaulting to 0, never negative) is the available-stock level below which the product flags for replenishment; and `unit_weight_g` (defaulting to 0, never negative) is the per-unit shipping weight in grams that feeds the hazmat surcharge. A newly created product has no stock: its `total_available_units` is 0, and its `reorder_flag` is true exactly when its `reorder_threshold` is greater than 0.

Stock arrives when a `StoreAdmin` receives an **inventory lot** against a product, supplying a `lot_code` (unique among that product's lots), the `quantity_on_hand` units received (never negative), and an optional `unit_cost_cents` landed cost. The new lot's `product_id` is the product it was received against, its `quantity_reserved` begins at 0, its `quantity_available` therefore equals its `quantity_on_hand`, and its `status` begins `ACTIVE`. Receiving a lot triggers the product to recompute `total_available_units` and `reorder_flag`. Products and their lots are readable by staff; a product is readable by every role, while the list of a product's lots is a `StoreAdmin` view.

### 3.2. Retail Customers, Loyalty, and Wallet Credit

A `StoreAdmin` registers a retail **customer** with a unique login `email` and a display `full_name`. Each customer starts with a `wallet_credit_cents` store-credit balance of 0, `loyalty_points` of 0, a `loyalty_tier` of `BRONZE`, and a `status` of `ACTIVE`. (The other statuses a customer may carry is `SUSPENDED`.)

Loyalty tier is a pure function of lifetime points and is recomputed whenever points change: a customer is `BRONZE` while their `loyalty_points` are below 1000, `SILVER` once points reach 1000 and while they remain below 5000, and `GOLD` once points reach 5000 or more.

The wallet balance grows only through refunds and RMA approvals, described in Sections 3.5 and 3.9; loyalty points grow when an order is paid and are reversed if that order is later refunded, as detailed in Section 3.5.

### 3.3. Commercial Accounts and Their Lifecycle

A `StoreAdmin` opens a **commercial account** for a business buyer, supplying the legal `business_name`, a `credit_limit_cents` ceiling on outstanding commercial credit (which must be greater than zero), optional `payment_terms_net_days` net terms (defaulting to 30, never negative), and an optional `discount_tier` of `STANDARD`, `SILVER`, or `GOLD` (defaulting to `STANDARD`) that drives the base commercial discount rate. A new account starts with `credit_used_cents` of 0 and a `status` of `PENDING`.

An account moves through `PENDING`, `ACTIVE`, `ON_HOLD`, and the terminal `SUSPENDED`. A `StoreAdmin` activation of an account that is `PENDING` or `ON_HOLD` moves it to `ACTIVE`; attempting to activate from any other state is rejected with `ERR_INVALID_STATE`. Placing an `ACTIVE` account on hold moves it `ACTIVE → ON_HOLD` and blocks new commercial order placement while it remains held; a hold from any state other than `ACTIVE` is rejected with `ERR_INVALID_STATE`. A `StoreAdmin` may also change an account's `discount_tier` at any time. Each of these three administrative actions — activation, hold, and tier change — increments the account's `version` by one, which is precisely why a commercial buyer's cached view of the account can go stale (Section 2.8).

The account's `credit_used_cents` is a continuously reconciled derived field: it is the sum of `total_cents` across every order belonging to the account whose `fulfillment_status` is `CONFIRMED` or `SHIPPED`. It is recomputed whenever a commercial order is confirmed (placed), shipped, or cancelled, so that it always reflects only live, credit-consuming orders.

### 3.4. Order Placement, Pricing, and the Dual-Total Model

Orders come in two flavours distinguished by the system-set `order_type`. A `Customer` places a **retail order** by naming their own `customer_id` and supplying `lines` — an array of at least one line, each identifying a `product_id` and a `quantity` (a positive integer); the system captures each line's `unit_price_cents` as a snapshot of the referenced product's current `unit_price_cents` at placement (any client-supplied line price is ignored) and records the computed `line_total_cents`. A retail order is born with `order_type` of `RETAIL`, a `fulfillment_status` of `DRAFT`, a `payment_status` of `UNPAID`, and its `commercial_account_id` empty. A `CommercialBuyer` places a **commercial order** against their own account by supplying `lines` and the `expected_commercial_account_version` guard; a commercial order is born with `order_type` of `COMMERCIAL`, is created directly in the `CONFIRMED` fulfillment state (reserving inventory immediately, as in Section 3.5), and leaves `customer_id` empty.

Pricing is computed by a single routine that runs twice over an order's life — once at placement to produce the **provisional total**, and again at ship to produce the **final total**. Both runs proceed identically except for which discount tier they read. The routine works in three stages:

**Subtotal.** Each line's value is its snapshot `unit_price_cents` multiplied by its `quantity`, recorded as that line's `line_total_cents`. The order's `subtotal_cents` is the sum of the line totals across all lines. These are exact integer products; no rounding is involved.

**Discount.** For a `RETAIL` order the discount rate is zero and `discount_cents` is zero. For a `COMMERCIAL` order the rate is built from a base and a volume bonus. The base rate is 0 for a `STANDARD` account, 0.05 for a `SILVER` account, and 0.10 for a `GOLD` account, read from the account's `discount_tier`. A volume bonus of an additional 0.05 is added when the order's `subtotal_cents` is at least 500000 cents; below that threshold the bonus is zero. The effective discount rate is the smaller of that base-plus-bonus sum and the ceiling of 0.12. The `discount_cents` is the discount rate applied to `subtotal_cents`, rounded half up once to whole cents.

**Hazmat surcharge.** If no line's product is flagged `is_hazmat`, the order's `hazmat_surcharge_cents` is zero. If any line's product is hazmat, the system totals the shipping weight of the whole order as the sum over lines of `unit_weight_g` times `quantity`, converts that gram total to kilograms by dividing by 1000 and rounding up to the next whole kilogram, and computes a surcharge of a 1500-cent base plus 200 cents per whole kilogram. The recorded `hazmat_surcharge_cents` is the smaller of that computed surcharge and the cap of 5000 cents.

The order's net total is `subtotal_cents` minus `discount_cents` plus `hazmat_surcharge_cents`. At placement this net figure is written to `provisional_total_cents` using the discount tier in force at placement time. The order's `final_total_cents` stays empty until the order ships, at which point the same routine reruns using the discount tier in force at ship time — so a tier change between placement and ship genuinely changes the final figure — and writes `final_total_cents`. The unifying field `total_cents` reads as `provisional_total_cents` until the order ships and as `final_total_cents` thereafter.

Placement of a commercial order is subject to a chain of checks evaluated in a strict order. After the universal existence, field-validity, ownership, and state checks, the account-specific rules run in this sequence: the account must be `ACTIVE` or the placement is rejected with `ERR_ACCOUNT_NOT_ACTIVE`; then every line must have sufficient stock (Section 3.5) or the placement is rejected with `ERR_INSUFFICIENT_STOCK`; then the draw must fit the credit line — the account's `credit_used_cents` plus this order's `total_cents` must not exceed its `credit_limit_cents`, where an exact-equality draw is permitted and only a strictly greater draw is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402); and finally the optimistic-concurrency guard runs, rejecting a stale `expected_commercial_account_version` with `ERR_STALE_VERSION`. A successful commercial placement reserves inventory, computes the provisional total, recomputes `credit_used_cents`, and increments the account's `version` by one.

### 3.5. Order Fulfillment: Confirming, Paying, Shipping, Cancelling, Refunding

An order carries two independent status axes that evolve separately: `fulfillment_status` and `payment_status`. A `DRAFT` order can be paid before it is confirmed, and a `CONFIRMED` order can still be unpaid; the two never gate each other except where explicitly stated.

**Confirming and the reservation waterfall.** A retail `DRAFT` order is confirmed by its `Customer` (or by a `StoreAdmin`), moving it `DRAFT → CONFIRMED`; a commercial order reaches `CONFIRMED` at placement. Confirmation first requires that every line has sufficient stock — each line's `quantity` must be coverable by its product's `total_available_units`, or the request is rejected with `ERR_INSUFFICIENT_STOCK`. When stock suffices, the system reserves each line against the product's lots using the allocation waterfall: it walks the lots in `created_at` ascending then `lot_code` ascending order, and at each lot takes the smaller of the units still needed and that lot's `quantity_available`, adds that amount to the lot's `quantity_reserved`, recomputes the lot's `quantity_available`, and moves on until the line's need reaches zero. Any lot whose `quantity_available` falls to 0 transitions `ACTIVE → DEPLETED`. Each affected product then recomputes `total_available_units`, and if that value drops below the product's `reorder_threshold`, its `reorder_flag` flips to true. A commercial confirmation additionally increments the account's `version` by one and recomputes its `credit_used_cents`.

**Paying and loyalty accrual.** A `Customer` pays an order, moving `payment_status` `UNPAID → PAID`; payment is allowed only while the order is `UNPAID` and its `fulfillment_status` is not `CANCELLED`. Paying accrues loyalty points to the customer. The multiplier comes from the customer's `loyalty_tier` at pay time: 1.0 for `BRONZE`, 1.25 for `SILVER`, and 1.5 for `GOLD`. Points are earned per line and only then summed: for each line, divide its `line_total_cents` by 100, multiply by the tier multiplier, and take the floor to a whole number of points; the earned total is the sum of those per-line floored figures — never the floor of a summed total. That earned total is added to the customer's `loyalty_points`, and the `loyalty_tier` is recomputed.

**Shipping and finalization.** A `StoreAdmin` ships a `CONFIRMED` order, moving it `CONFIRMED → SHIPPED`. Shipping recomputes the pricing routine using the discount tier current at ship time, writes `final_total_cents`, and sets `total_cents` to that final figure. For each lot the order reserved, shipping decrements both `quantity_on_hand` and `quantity_reserved` by the shipped amount and recomputes `quantity_available`. The order's `shipped_at` is stamped with the current logical-clock time, which becomes the origin of the product's warranty clock. A commercial order's account then recomputes `credit_used_cents` against the finalized total; this ship-time recompute refreshes the account's `updated_at` but, unlike confirmation and cancellation, does not increment the account's `version`.

**Cancelling and release.** A `Customer` or `StoreAdmin` cancels an order that is `DRAFT` or `CONFIRMED`, moving it to `CANCELLED`. Cancelling a `DRAFT` order releases nothing, since it never reserved stock. Cancelling a `CONFIRMED` order releases each reserved lot: the reserved amount is subtracted from that lot's `quantity_reserved`, its `quantity_available` is recomputed, and any `DEPLETED` lot whose `quantity_available` rises above 0 reverts `DEPLETED → ACTIVE`. Each affected product recomputes `total_available_units` and its `reorder_flag`. For a commercial order, cancellation also increments the account's `version` by one and recomputes `credit_used_cents`, releasing the drawn credit.

**Refunding.** A `StoreAdmin` refunds a `PAID` order, moving `payment_status` `PAID → REFUNDED`. The refund credits the customer's `wallet_credit_cents` by the order's `total_cents`, and reverses the loyalty points earned for that order — subtracting exactly the points that order accrued from the customer's `loyalty_points`, floored at 0 so the balance never goes negative — and then recomputes the `loyalty_tier`.

### 3.6. Consumable Subscriptions

A `Customer` may set up a recurring **subscription** for a consumable, naming their own `customer_id`, the target `product_id`, an `interval_days` cadence (which must be greater than zero), and a `quantity_per_cycle` (also greater than zero). The target product must be flagged `is_subscribable`; a subscription against a product that is not subscribable is rejected with `ERR_SUBSCRIPTION_INVALID`. On creation the system snapshots the product's current `unit_price_cents` into `price_locked_cents`, sets `next_ship_at` to the current logical-clock time plus `interval_days`, and starts the subscription `ACTIVE`.

A subscription cycles between `ACTIVE` and `PAUSED` and can end at the terminal `CANCELLED`. Pausing an `ACTIVE` subscription freezes `next_ship_at` in place; resuming a `PAUSED` subscription recomputes `next_ship_at` as the current clock time plus `interval_days`. Pausing anything not `ACTIVE`, or resuming anything not `PAUSED`, is rejected with `ERR_SUBSCRIPTION_INVALID`. A subscription may be cancelled from either `ACTIVE` or `PAUSED`, and cancellation is final.

### 3.7. Design Consults and Bookings

The store employs design **consultants** for build and design work. A `StoreAdmin` creates a consultant with a display `name`, a `specialty` string (such as VERTICAL_FARM or AQUAPONICS), an `hourly_rate_cents` billing rate (greater than zero), and an optional `buffer_minutes` idle gap required between consecutive bookings (defaulting to 30, never negative). A consultant starts `ACTIVE` and may otherwise be `INACTIVE`.

A `Customer` books a consult against a consultant, supplying their own `customer_id`, a `start_at` and `end_at` (both ISO 8601 UTC, with `end_at` strictly after `start_at`), and an optional free-text `design_scope` brief (defaulting to empty). Before a booking is accepted, its window is checked against the consultant's existing bookings: the requested window must not fall within `buffer_minutes` of any existing `REQUESTED` or `CONFIRMED` booking on that consultant, and a violation is rejected with `ERR_CONSULTANT_UNAVAILABLE`.

At booking time the system computes the **estimated fee**: it measures the scheduled duration as the whole minutes between `start_at` and `end_at`, converts that to hours by dividing by 60 and rounding up to the next whole hour, and multiplies the whole-hour count by the consultant's `hourly_rate_cents`, writing the result to `estimated_fee_cents`. A new booking starts `REQUESTED`.

A booking moves through `REQUESTED`, `CONFIRMED`, and the terminal `COMPLETED` and `CANCELLED`. A `Consultant` (or a `StoreAdmin`) confirms a `REQUESTED` booking, moving it `REQUESTED → CONFIRMED`. The owning `Consultant` completes a `CONFIRMED` booking by supplying `actual_minutes`, which must be greater than zero; completion moves it `CONFIRMED → COMPLETED` and computes the **actual fee** as `hourly_rate_cents` multiplied by `actual_minutes`, divided by 60, and rounded half up to whole cents, written to `actual_fee_cents`. Because the estimate rounds the scheduled duration up to a whole hour while the actual prorates the real minutes, the two figures diverge whenever the actual time is not a whole-hour multiple that happens to ceil to the same hour. A booking may be cancelled from either `REQUESTED` or `CONFIRMED` by the `Customer`, the `Consultant`, or a `StoreAdmin`, which frees the consultant's held time window; any transition attempted from a state the booking is not currently in is rejected with `ERR_INVALID_STATE`.

### 3.8. Rooms, Workshops, and Registrations

Workshops run in physical **rooms**. A `StoreAdmin` creates a room with a `name` label and an optional `seat_capacity` (defaulting to 20, greater than zero).

A `StoreAdmin` schedules a **workshop session** in a room by supplying the `room_id`, a `title`, a `start_at` and `end_at` (with `end_at` strictly after `start_at`), and a `capacity` that must be greater than zero and no larger than the room's `seat_capacity`. The session's half-open interval from start up to (but not including) end must not overlap any existing non-`CANCELLED` session in the same room; two sessions that merely abut — one ending exactly when the next begins — do not conflict, but any genuine overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED`. A new session starts `SCHEDULED` with `seats_taken` of 0 and can move to `OPEN`, `COMPLETED`, or `CANCELLED`.

A `StoreAdmin` opens a `SCHEDULED` session, moving it `SCHEDULED → OPEN` and enabling registration. Registration is permitted only while a session is `OPEN`; attempting to register against a session in any other status is rejected with `ERR_SESSION_NOT_OPEN`. A `StoreAdmin` may cancel a session that is `SCHEDULED` or `OPEN`; cancellation cascades to every non-terminal registration under the session — each `REGISTERED` or `WAITLISTED` registration is moved to `CANCELLED` — and the session's `seats_taken` is recomputed as those cancellations land.

A `Customer` registers for an `OPEN` session by naming their own `customer_id`; the resulting **registration** records its `session_id`, the `customer_id`, and a `price_paid_cents` seat-fee snapshot (0 in this scope). A registration is created `REGISTERED` when the session's `seats_taken` is below its `capacity` at creation time, and `WAITLISTED` otherwise; `seats_taken` is the count of the session's registrations whose `status` is `REGISTERED`, recomputed on every registration change. When a `Customer` lists a session's registrations, the result is scoped to that customer's own registrations. Cancelling a registration (by the `Customer` or a `StoreAdmin`) moves it from `REGISTERED` or `WAITLISTED` to the terminal `CANCELLED` and recomputes the session's `seats_taken`. If the cancelled registration had been `REGISTERED` and at least one `WAITLISTED` registration exists on that session, the earliest-created (`created_at` ascending) waitlisted registration is promoted to `REGISTERED` to fill the freed seat; cancelling a merely `WAITLISTED` registration recomputes `seats_taken` but promotes no one.

### 3.9. Warranty Returns and RMA Processing

After an order ships, a `Customer` may open a return authorization — an **RMA** — against one of its lines, supplying the `order_id` (which must reference a `SHIPPED` order), the `product_id` being returned, a `return_quantity` greater than zero, and a `reason`. The named product must not be hazmat: hazmat goods are non-returnable, and such a request is rejected with `ERR_HAZMAT_NOT_RETURNABLE`. The product must also appear as a line on the referenced order and the `return_quantity` must not exceed the quantity originally ordered for that product; a product that is not a line on the order, or an over-quantity return, is rejected with `ERR_PRODUCT_NOT_IN_ORDER`. A new RMA starts `SUBMITTED`.

An RMA is worked through a review cycle: a `StoreAdmin` begins review, moving it `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW` the administrator may request more information (optionally attaching a `note`), moving it `UNDER_REVIEW → INFO_REQUESTED`; the `Customer` then provides the requested information (again with an optional `note`), moving it `INFO_REQUESTED → UNDER_REVIEW`. This request-info/provide-info cycle may repeat any number of times. From `UNDER_REVIEW` the administrator ultimately either approves the RMA or rejects it (optionally with a `note`), and both `APPROVED` and `REJECTED` are terminal. Any of these transitions attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

Approval is where the money and stock move. At approval the system sets `within_warranty` by testing whether the current logical-clock time is on or before the order's `shipped_at` plus the product's `warranty_months` times 30 days; a return at exactly that boundary instant still counts as within warranty. It then computes `refund_cents`: the base value is the matched line's snapshot `unit_price_cents` times the `return_quantity`, and if the return is within warranty the refund is that full base value, while if it is out of warranty the refund is the base value reduced by a 15 percent restocking fee — that is, 85 percent of the base — rounded half up to whole cents. Approval also restocks the goods by creating a new inventory lot on the returned `product_id` with `quantity_on_hand` equal to the `return_quantity` and `status` `ACTIVE`; the product then recomputes `total_available_units`, and if that rises back to or above the `reorder_threshold`, its `reorder_flag` flips to false. Finally the customer's `wallet_credit_cents` is increased by the computed `refund_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or act upon an existing resource return `200 OK`. The clock-setting utility returns `200 OK`. Request and response bodies are governed by the workflows in Section 3; this table lists only the routing surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a catalog product | StoreAdmin |
| GET | `/products/{id}` | Fetch a product | StoreAdmin, Customer, CommercialBuyer, Consultant |
| POST | `/products/{id}/inventory-lots` | Receive an inventory lot for a product | StoreAdmin |
| GET | `/products/{id}/inventory-lots` | List a product's inventory lots | StoreAdmin |
| POST | `/customers` | Register a retail customer | StoreAdmin |
| GET | `/customers/{id}` | Fetch a customer | StoreAdmin, Customer |
| POST | `/commercial-accounts` | Create a commercial account (PENDING) | StoreAdmin |
| GET | `/commercial-accounts/{id}` | Fetch a commercial account | StoreAdmin, CommercialBuyer |
| POST | `/commercial-accounts/{id}/activate` | Activate a PENDING/ON_HOLD account | StoreAdmin |
| POST | `/commercial-accounts/{id}/hold` | Place an ACTIVE account ON_HOLD | StoreAdmin |
| POST | `/commercial-accounts/{id}/set-tier` | Change the account discount tier | StoreAdmin |
| POST | `/commercial-accounts/{id}/orders` | Place a commercial order (CONFIRMED, OCC-guarded) | CommercialBuyer |
| POST | `/orders` | Place a retail order (DRAFT) | Customer |
| GET | `/orders/{id}` | Fetch an order | StoreAdmin, Customer, CommercialBuyer |
| GET | `/orders` | List/filter orders | StoreAdmin, Customer, CommercialBuyer |
| POST | `/orders/{id}/confirm` | Confirm a retail DRAFT order | Customer, StoreAdmin |
| POST | `/orders/{id}/pay` | Pay an order and accrue loyalty | Customer |
| POST | `/orders/{id}/ship` | Ship a CONFIRMED order | StoreAdmin |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT/CONFIRMED order | Customer, StoreAdmin |
| POST | `/orders/{id}/refund` | Refund a PAID order to store credit | StoreAdmin |
| POST | `/subscriptions` | Create a consumable subscription | Customer |
| GET | `/subscriptions/{id}` | Fetch a subscription | StoreAdmin, Customer |
| GET | `/subscriptions` | List/filter subscriptions | StoreAdmin, Customer |
| POST | `/subscriptions/{id}/pause` | Pause an ACTIVE subscription | Customer |
| POST | `/subscriptions/{id}/resume` | Resume a PAUSED subscription | Customer |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| POST | `/consultants` | Create a design consultant | StoreAdmin |
| GET | `/consultants/{id}` | Fetch a consultant | StoreAdmin, Customer, Consultant |
| POST | `/consultants/{id}/bookings` | Book a build/design consult | Customer |
| GET | `/consultants/{id}/bookings` | List a consultant's bookings | StoreAdmin, Consultant |
| GET | `/consult-bookings/{id}` | Fetch a consult booking | StoreAdmin, Customer, Consultant |
| GET | `/consult-bookings` | List/filter consult bookings | StoreAdmin |
| POST | `/consult-bookings/{id}/confirm` | Confirm a requested booking | Consultant, StoreAdmin |
| POST | `/consult-bookings/{id}/complete` | Complete a booking with actual minutes | Consultant |
| POST | `/consult-bookings/{id}/cancel` | Cancel a booking | Customer, Consultant, StoreAdmin |
| POST | `/rooms` | Create a workshop room | StoreAdmin |
| GET | `/rooms/{id}` | Fetch a room | StoreAdmin, Customer |
| POST | `/workshop-sessions` | Schedule a workshop session in a room | StoreAdmin |
| GET | `/workshop-sessions/{id}` | Fetch a workshop session | StoreAdmin, Customer |
| GET | `/workshop-sessions` | List/filter sessions | StoreAdmin, Customer |
| POST | `/workshop-sessions/{id}/open` | Open a scheduled session for registration | StoreAdmin |
| POST | `/workshop-sessions/{id}/cancel` | Cancel a session (cascade-cancel registrations) | StoreAdmin |
| POST | `/workshop-sessions/{id}/registrations` | Register a customer for an OPEN session | Customer |
| GET | `/workshop-sessions/{id}/registrations` | List a session's registrations | StoreAdmin, Customer |
| GET | `/workshop-registrations/{id}` | Fetch a registration | StoreAdmin, Customer |
| GET | `/workshop-registrations` | List/filter registrations | StoreAdmin |
| POST | `/workshop-registrations/{id}/cancel` | Cancel a registration (promote earliest waitlist) | Customer, StoreAdmin |
| POST | `/rmas` | Submit an RMA against a shipped order line | Customer |
| GET | `/rmas/{id}` | Fetch an RMA | StoreAdmin, Customer |
| GET | `/rmas` | List/filter RMAs | StoreAdmin |
| POST | `/rmas/{id}/review` | Begin review (SUBMITTED to UNDER_REVIEW) | StoreAdmin |
| POST | `/rmas/{id}/request-info` | Request more info (UNDER_REVIEW to INFO_REQUESTED) | StoreAdmin |
| POST | `/rmas/{id}/provide-info` | Provide requested info (INFO_REQUESTED to UNDER_REVIEW) | Customer |
| POST | `/rmas/{id}/approve` | Approve an RMA: restock and refund to wallet | StoreAdmin |
| POST | `/rmas/{id}/reject` | Reject an RMA | StoreAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_SUBSCRIPTION_INVALID` | 409 |
| `ERR_HAZMAT_NOT_RETURNABLE` | 422 |
| `ERR_CONSULTANT_UNAVAILABLE` | 409 |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 |
| `ERR_PRODUCT_NOT_IN_ORDER` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_VERSION` | 412 |
