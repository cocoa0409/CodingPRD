# Skate & Surf Shop API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Skate & Surf Shop API, the operational backbone of a combined skateboard and surf retail and service business. The shop sells catalog products and assembles custom boards from those products; it books bay time for grip, wheel, and wax service; it runs a rental fleet that can be tied to instructor-led lessons; it takes trade-ins for cash or consignment; it runs loyalty and sponsorship tiers; it fulfills special orders for items not carried in the catalog; and it hosts community events that members register for with loyalty points.

The system's central challenge is keeping finite inventory and scheduled capacity consistent as items move through overlapping workflows. A single physical part can be reserved by a board build, consumed by a service order, or freed again when either is cancelled, and the shop's derived stock figures must always reconcile. Likewise, service bays, instructors, and rental units are shared resources whose calendars must never conflict. The requirements below define the entities, their lifecycles, the money and points calculations, the validation ordering, and the cascading effects that hold the whole picture together.

This API is consumed by shop staff and members through a small set of roles. It is authoritative, immediate-consistency, and single-tenant: every mutation takes effect at once, and derived values such as available stock and event registration counts are recomputed on the spot rather than deferred.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or the role is not one the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `ShopManager`, `Associate`, `Instructor`, and `Member`. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The `ShopManager` is the operational superset: catalog authorship, product restocking and discontinuation, instructor and bay and rental-unit creation, member suspension and reinstatement, trade-in appraisals, event creation and closure, and control of the logical clock all belong to this role, in addition to every shared operation. An `Associate` is floor staff who run the build, service, rental, trade-in (except appraisal), special-order, and registration workflows, and may create members. Both `ShopManager` and `Associate` are operator roles whose identity is opaque: when `X-User-Role` is `ShopManager` or `Associate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it against any entity's `id`.

The remaining two roles are entity-backed and carry ownership semantics. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an `Instructor` compare the resource's `instructor_id` to `X-User-ID`, so an instructor may confirm, complete, or cancel only lessons assigned to them. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's `member_id` to `X-User-ID`, so a member may request or cancel only their own special orders and register or cancel only their own event registrations. An ownership mismatch on an entity-backed role is treated as an authorization failure and rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in the system carries a server-minted `id` formatted as a UUID (no type prefix) and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits marking creation. All entities in this domain are mutable and additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that starts at 1 and increments by one on each mutation. Any state transition, field change, or recomputation of a derived value on a resource is a mutation: it refreshes `updated_at` and increments `version`. Derived recomputations count — for example, when a build reservation changes a product's `stock_reserved`, that product's `updated_at` and `version` advance as well.

Relationships between resources are expressed as foreign-key identifier fields carried in the request body (for example a build's `member_id` or a rental's `unit_id`), never as nested URL paths. When a request references several resources at once, the system validates identifiers left to right — the path identifier first, then each body foreign key in the order the workflow reads them — and returns the not-found error for the first identifier that fails to resolve before evaluating any later reference or business rule.

### 2.5. Validation Order and Error Precedence

When a single request could fail more than one check, the system evaluates checks in a fixed priority order and returns the error for the first check that fails. The order is:

1. **Authentication** — both auth headers present and the role recognized, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role (and, for entity-backed roles, ownership) is permitted for this operation, otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — the path identifier and every body foreign key resolve to an existing resource, checked left to right, otherwise the matching `ERR_<ENTITY>_NOT_FOUND` (404).
4. **Body well-formedness** — required fields present, enum values valid, constrained integers non-negative, quantities strictly greater than zero, and any interval's start strictly before its end, otherwise `ERR_VALIDATION` (422).
5. **State** — the target resource is in a state from which the transition is allowed (`ERR_INVALID_STATE`, 409); and where an operation requires it, the relevant member is `ACTIVE` (`ERR_MEMBER_SUSPENDED`, 409), the event is `OPEN` (`ERR_EVENT_CLOSED`, 409), or a build component product is `ACTIVE` (`ERR_PRODUCT_DISCONTINUED`, 409).
6. **Referential business state** — a serviced build is ready (`ERR_BUILD_NOT_READY`, 409) or a lesson's linked rentals are ready (`ERR_RENTAL_NOT_READY`, 409).
7. **Business constraints** — duplicate registration (`ERR_DUPLICATE_REGISTRATION`, 409), event capacity (`ERR_EVENT_FULL`, 409), rental length (`ERR_RENTAL_TOO_LONG`, 422), and stock sufficiency (`ERR_INSUFFICIENT_STOCK`, 409).
8. **Temporal constraints** — instructor calendar (`ERR_INSTRUCTOR_UNAVAILABLE`, 409), bay separation (`ERR_BAY_UNAVAILABLE`, 409), and rental-unit calendar (`ERR_UNIT_UNAVAILABLE`, 409).
9. **Fiscal constraints** — sufficient loyalty points for an event (`ERR_INSUFFICIENT_POINTS`, 402).
10. **Concurrency** — the optimistic-concurrency version guard on special-order quoting (`ERR_STALE_VERSION`, 412).

Within event registration specifically, this means a closed-event or suspended-member rejection surfaces before a duplicate-registration check, which surfaces before the capacity check, which surfaces before the insufficient-points check.

### 2.6. Monetary Amounts, Points, and Rounding

All money in the system is stored and returned as an integer number of cents; there are no fractional-cent values in stored fields. Loyalty points and day counts are likewise whole integers. Wherever a calculation multiplies a cents amount by a rate — tier discounts on a build, trade-in payout rates — the result is rounded to the nearest whole cent using the round-half-up convention (a half-cent rounds up). Where a formula pins the rounding boundary (the per-line build discount below), that boundary is authoritative and must be applied exactly as stated. Point calculations that divide use whole-number floor division, and the per-transaction point cap is applied after the tier multiplier, as detailed in §2.9.

### 2.7. Inventory and Stock Reconciliation

Each `Product` tracks three inventory numbers plus a derived fourth. `stock_on_hand` is the count of physical units the shop holds; `stock_reserved` is the count committed to open builds and service orders but not yet handed over; and `stock_available` is a computed field defined as `stock_on_hand` minus `stock_reserved`. `stock_available` is never stored independently — it is recomputed every time a reservation is taken, released, consumed, or restocked, and it is this available figure that all sufficiency checks read.

Reserving inventory raises `stock_reserved` without touching `stock_on_hand`; releasing a reservation (a build revision or any cancellation that held stock) lowers `stock_reserved` back; and consuming inventory at completion lowers both `stock_on_hand` and `stock_reserved` by the same amount, so `stock_available` is unchanged by the consumption step itself. Restocking raises `stock_on_hand`. Any sufficiency check compares the requested quantity against `stock_available`, and a shortfall is rejected with `ERR_INSUFFICIENT_STOCK`. A product created with a given `stock_on_hand` starts with `stock_reserved` at 0, so its initial `stock_available` equals its `stock_on_hand`.

### 2.8. Scheduling and Interval Semantics

Three shared resources — service bays, instructors, and rental units — carry calendars, and each uses a deliberately different interval rule.

Lessons on a given instructor use half-open interval semantics on `start_at` and `end_at`: two lessons conflict when their `[start_at, end_at)` ranges overlap, but abutting lessons where one ends exactly when the next begins do not conflict. Only lessons in `BOOKED` or `CONFIRMED` status occupy the calendar; a conflict is rejected with `ERR_INSTRUCTOR_UNAVAILABLE`.

Service orders on a given bay require a setup buffer between slots. A new slot must be separated from every existing `SCHEDULED` or `IN_PROGRESS` slot on the same bay by at least 30 minutes of clearance; if the gap between the new `[slot_start, slot_end)` interval and an existing one is less than 30 minutes (which includes any overlap), the slot is rejected with `ERR_BAY_UNAVAILABLE`. A gap of exactly 30 minutes is acceptable.

Rentals on a given unit use closed inclusive interval semantics on the calendar-date fields `start_date` and `end_date`: two rentals conflict when their `[start_date, end_date]` ranges share any day, including a shared endpoint day. Only rentals in `RESERVED` or `CHECKED_OUT` status occupy the unit; a conflict is rejected with `ERR_UNIT_UNAVAILABLE`. Rental length is also bounded: the inclusive duration in days, counted as the difference between `end_date` and `start_date` plus one, may not exceed 14 days, and a longer request is rejected with `ERR_RENTAL_TOO_LONG`.

### 2.9. Loyalty Points Accrual

Whenever a revenue-bearing workflow finishes — a build handed over, a service order completed, a rental returned, a lesson completed, or a special order fulfilled — the completing member earns loyalty points on the net amount of that transaction. The accrual takes the net amount in cents and divides it by 100, discarding any remainder (floor division), to get a base point figure. That base is multiplied by the member's tier multiplier — 1 for `STANDARD`, 2 for `PRO`, and 3 for `TEAM` — and then doubled again if the completing request set its optional `double_points` flag to true (the flag defaults to false when omitted). The earned points are the product of base times multiplier, but capped at a maximum of 500 points per transaction; the cap is applied after the multiplier, not before. The earned amount is added to the member's `points_balance` and also added to `lifetime_points`, which only ever accumulates and is never decremented.

The net amount that seeds this accrual depends on the workflow: the build's `final_total_cents`, the service order's `total_cents`, the rental's `rental_total_cents` plus `late_fee_cents`, the lesson's `fee_cents`, or the special order's `quoted_price_cents`.

### 2.10. Cascading Consistency and Cancellation

Several operations mutate more than one resource, and every secondary effect is part of the contract. Suspending a member triggers a depth-three cascade: every one of that member's board builds in `DRAFT`, `COMPONENTS_RESERVED`, `ASSEMBLED`, or `SETUP_COMPLETE` is cancelled; each such build cancellation in turn cancels any linked service orders in `SCHEDULED` or `IN_PROGRESS`; and each of those service-order cancellations releases its reserved parts by lowering each part product's `stock_reserved`. Closing an event triggers a depth-two cascade: every `REGISTERED` registration for the event is cancelled, and each cancellation refunds the member's `points_charged` back to their `points_balance` and decrements the event's `registration_count`. Cancelling a lesson cascades to its linked rentals, moving every rental linked to that lesson that is in `RESERVED` or `CHECKED_OUT` to `CANCELLED`.

Each cascade hop is a genuine mutation of the affected resource, refreshing its `updated_at` and advancing its `version`, and any stock released along the way flows through the reconciliation rules of §2.7.

### 2.11. Optimistic Concurrency Control

Quoting a special order is guarded by optimistic concurrency. A quote request must carry `expected_special_order_version`, and the server compares it against the special order's current `version`. If they do not match — because another quote has already advanced the order's version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding a quote it never observed. A successful quote increments the special order's `version` by one, so a client must re-read the order before issuing a further quote. This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.12. The Logical Clock

The server keeps a logical clock that governs all time-of-event stamps (the various `*_at` fields, `reserved_at` through `settled_at`) and all date arithmetic such as rental late-fee day counts and the return date. On startup the clock reads exactly `2026-07-01T00:00:00Z` and never falls back to wall-clock time; until it is advanced it stays at that default. A `ShopManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant, after which all subsequent stamps and date computations read from the new value.

## 3. Business Logic & Workflows

### 3.1. Catalog and Inventory Management

A `ShopManager` authors the catalog. Creating a product requires a unique `sku`, a display `name`, a `category` — one of `DECK`, `TRUCK`, `WHEELS`, `BEARINGS`, `GRIP`, `WAX`, `SURFBOARD`, or `ACCESSORY` — and a `unit_price_cents` that must be zero or greater. Optionally the manager may set `buildable_component` (whether the product may appear as a component in a board build; defaults to false), an initial `stock_on_hand` (defaults to 0), and a `reorder_threshold` (a low-stock reporting level, defaults to 0). A new product begins with `status` of `ACTIVE`, `stock_reserved` at 0, and `stock_available` equal to its opening `stock_on_hand`.

A manager may update a product's `unit_price_cents` or its `status` — moving it to `DISCONTINUED` retires it from new builds — and may restock it by supplying a `quantity` that is added to `stock_on_hand`, with `stock_available` recomputed. Products can be fetched individually or listed with optional `category` and `status` filters. Only `ACTIVE` products may be reserved as build components; naming a `DISCONTINUED` product as a component is rejected with `ERR_PRODUCT_DISCONTINUED`.

### 3.2. Members, Tiers, and Suspension

A `ShopManager` or `Associate` registers a member with a unique `email`, a `full_name`, and an optional loyalty `tier` — one of `STANDARD`, `PRO`, or `TEAM`, defaulting to `STANDARD`. A new member starts `ACTIVE` with `points_balance`, `lifetime_points`, and `store_credit_cents` all at 0. The tier drives both the discount applied to a member's final build price and the multiplier applied when they earn loyalty points, and it is read from the owning member at the moment each of those calculations runs.

A member account moves between `ACTIVE` and `SUSPENDED` and back, forming a cycle. Only a `ShopManager` may suspend an `ACTIVE` member or reinstate a `SUSPENDED` one. Suspension is not a quiet flag flip: it drives the depth-three cascade described in §2.10, unwinding the member's open builds, their linked service orders, and the parts those orders had reserved. Reinstatement simply returns the member to `ACTIVE` and refreshes `updated_at`. Two operations demand an `ACTIVE` member and reject a suspended one with `ERR_MEMBER_SUSPENDED`: completing (handing over) a board build, and registering for an event.

### 3.3. Custom Board Builds

A board build assembles catalog components into a finished board for a member. A `ShopManager` or `Associate` opens a build in `DRAFT` by supplying the `member_id` and `component_lines`, a list where each line names a `product_id` and a `qty` greater than zero; every referenced product must be flagged `buildable_component` true, and a line naming a non-buildable product is a malformed request rejected with `ERR_VALIDATION`. Builds can be fetched individually or listed by `member_id` and `status`.

The build lifecycle runs `DRAFT` → `COMPONENTS_RESERVED` → `ASSEMBLED` → `SETUP_COMPLETE` → `COMPLETED`, with a revision loop and cancellation branches. Reserving components is allowed only from `DRAFT`: every component product must be `ACTIVE` (else `ERR_PRODUCT_DISCONTINUED`) and must have `stock_available` at least the line quantity (else `ERR_INSUFFICIENT_STOCK`). On reserve, each component product's `stock_reserved` rises by the line quantity, `reserved_at` is stamped, and the build's `provisional_total_cents` is computed as the plain sum over the component lines of the product's `unit_price_cents` times the line quantity — raw list price, with no discount and no setup fee.

From `COMPONENTS_RESERVED`, assembling the board (allowed only from that state) stamps `assembled_at`. From `ASSEMBLED`, the build can either be revised or set up. Revising returns it to `DRAFT`: this is the compensating action for reserve, so each component product's `stock_reserved` is lowered back by the line quantity, and both `provisional_total_cents` and `assembled_at` are cleared to null. Setting up (allowed only from `ASSEMBLED`) computes the build's `final_total_cents` and stamps `setup_at`. The final price is where the member tier discount and setup fee enter: for each line, take the product's `unit_price_cents`, multiply by one minus the member's tier discount rate (0 for `STANDARD`, 0.10 for `PRO`, 0.20 for `TEAM`), round that discounted per-unit price half-up to a whole cent, then multiply the rounded per-unit price by the line quantity; sum those per-line totals across all lines and add a flat setup fee of 2500 cents. The rounding order is pinned — round the discounted unit price first, then multiply by quantity, then sum.

Completing a build is allowed only from `SETUP_COMPLETE` and only for an `ACTIVE` member (else `ERR_MEMBER_SUSPENDED`). Completion converts reservation to consumption: each component product's `stock_on_hand` and `stock_reserved` are both lowered by the line quantity (leaving `stock_available` unchanged by that step), loyalty is awarded to the member on the `final_total_cents` net amount per §2.9, and `completed_at` is stamped. A build may be cancelled from any non-terminal state; when cancelled from a state that held reservations (`COMPONENTS_RESERVED`, `ASSEMBLED`, or `SETUP_COMPLETE`), each component product's `stock_reserved` is released, and any linked service orders in `SCHEDULED` or `IN_PROGRESS` are cancelled. Cancelling a `DRAFT` build holds no reservation and simply refreshes `updated_at`. `COMPLETED` and `CANCELLED` are terminal.

### 3.4. Bay Service Work

Service orders schedule grip, wheel, or wax work in a service bay. An `Associate` or `ShopManager` schedules an order by supplying the `member_id`, the `bay_id`, a `service_type` of `GRIP`, `WHEEL`, or `WAX`, a `slot_start`, and a `slot_end`, plus an optional `build_id` linking the work to a finished board and an optional `parts_lines` list (each a `product_id` and a `qty` greater than zero; defaults to empty). Scheduling requires the referenced bay to exist and be `OPEN`, the slot's `slot_start` to fall strictly before its `slot_end`, and — when `build_id` is present — the referenced build to be in `SETUP_COMPLETE` or `COMPLETED`, else `ERR_BUILD_NOT_READY`. The bay separation rule of §2.8 applies, and every parts product must have `stock_available` at least the requested quantity, else `ERR_INSUFFICIENT_STOCK`. On a successful schedule the order enters `SCHEDULED` and each parts product's `stock_reserved` rises by its quantity. Orders can be fetched individually or listed by `member_id`, `bay_id`, `build_id`, and `status`.

The order runs `SCHEDULED` → `IN_PROGRESS` → `DONE`. Starting the work (from `SCHEDULED`) stamps `started_at`. Completing it (from `IN_PROGRESS`) computes the charges: `labor_total_cents` is the flat labor rate for the service type — 800 cents for `GRIP`, 1500 cents for `WHEEL`, 500 cents for `WAX`; `parts_total_cents` is the sum over the parts lines of the product's `unit_price_cents` times its quantity; and `total_cents` is the sum of labor and parts. Completion also consumes the reserved parts, lowering each parts product's `stock_on_hand` and `stock_reserved` by its quantity, awards loyalty on the `total_cents` net amount, and stamps `completed_at`. An order may be cancelled from `SCHEDULED` or `IN_PROGRESS`, which releases its reserved parts by lowering each product's `stock_reserved`. `DONE` and `CANCELLED` are terminal.

### 3.5. Lessons, Instructors, and Rentals

Instructors teach lessons and rentals equip customers, and the two are linked. A `ShopManager` creates an instructor with a `full_name`, a `discipline` of `SKATE` or `SURF`, and an optional `status` of `ACTIVE` or `INACTIVE` (defaults to `ACTIVE`). Rental units are created by a `ShopManager` with a `name`, a `kind` of `SKATEBOARD`, `SURFBOARD`, or `WETSUIT`, a `daily_rate_cents`, and an optional `status` of `AVAILABLE` or `RETIRED` (defaults to `AVAILABLE`).

An `Associate` or `ShopManager` books a lesson by supplying the `member_id`, the `instructor_id`, a `discipline` of `SKATE` or `SURF`, a `start_at`, an `end_at`, and a `fee_cents`. Booking requires the instructor to exist and be `ACTIVE`, `start_at` strictly before `end_at`, and no calendar conflict on that instructor per the half-open rule of §2.8 (else `ERR_INSTRUCTOR_UNAVAILABLE`). The lesson runs `BOOKED` → `CONFIRMED` → `COMPLETED`. Confirming a lesson is an `Instructor`-or-`ShopManager` action allowed only from `BOOKED`, and it additionally requires that every rental linked to this lesson be in `RESERVED` or `CHECKED_OUT` status, else `ERR_RENTAL_NOT_READY`; on success `confirmed_at` is stamped. Completing (from `CONFIRMED`) awards loyalty on the `fee_cents` net amount and stamps `completed_at`. Cancelling a lesson from `BOOKED` or `CONFIRMED` cascades to its linked rentals as described in §2.10. Lessons can be fetched or listed by `member_id`, `instructor_id`, and `status`.

An `Associate` or `ShopManager` creates a rental by supplying the `member_id`, the `unit_id`, a `start_date`, an `end_date`, an optional `lesson_id` tying the rental to a lesson (null for a standalone rental), and an optional `deposit_cents` security deposit (defaults to 0). Creation requires the unit to exist and be `AVAILABLE`, `start_date` no later than `end_date`, the inclusive duration within the 14-day limit of §2.8 (else `ERR_RENTAL_TOO_LONG`), no calendar conflict on that unit per the closed-inclusive rule (else `ERR_UNIT_UNAVAILABLE`), and — when `lesson_id` is present — the referenced lesson to exist. The rental runs `RESERVED` → `CHECKED_OUT` → `RETURNED`. Checking out (from `RESERVED`) stamps `checked_out_at`. Returning (from `CHECKED_OUT`) computes charges using the logical clock's current date as the actual return date: `rental_total_cents` is the unit's `daily_rate_cents` times the inclusive rental duration in days (the difference between `end_date` and `start_date`, plus one); the number of late days is the difference between the current clock date and `end_date` but never less than zero; and `late_fee_cents` is that late-day count times 1500 cents per day. Returning also awards loyalty on the sum of `rental_total_cents` and `late_fee_cents`, and records `returned_on` as the clock's current date. A rental may be cancelled from `RESERVED` or `CHECKED_OUT`, stamping `cancelled_at` and freeing the unit for future bookings. Rentals can be fetched or listed by `member_id`, `unit_id`, `lesson_id`, and `status`. Service bays, referenced when scheduling work, are created by a `ShopManager` with a `name` and an optional `status` of `OPEN` or `CLOSED` (defaults to `OPEN`).

### 3.6. Trade-Ins, Buyouts, and Consignment

A trade-in lets a member hand in gear for cash, store credit, or consignment. An `Associate` or `ShopManager` receives a trade-in with the `member_id` and a free-text `description`; it starts in `RECEIVED`. Only a `ShopManager` may appraise a `RECEIVED` trade-in, supplying its `appraised_value_cents` (which is recorded and must be zero or greater) and stamping `appraised_at`, moving it to `APPRAISED`. From `APPRAISED` the workflow forks into two divergent branches.

The buyout branch settles immediately. An `Associate` or `ShopManager` buys out an `APPRAISED` trade-in by supplying a `payout_method` of either `CASH` or `STORE_CREDIT`, which moves it to `CASH_SETTLED` and computes `payout_cents` from the appraised value: a `CASH` payout is 50 percent of `appraised_value_cents`, rounded half-up, and is paid physically with no change to the member's balance; a `STORE_CREDIT` payout is 70 percent of `appraised_value_cents`, rounded half-up, and is added to the member's `store_credit_cents` (so store credit is strictly more generous than cash for the same appraised value). The `payout_method` is recorded and `settled_at` is stamped.

The consignment branch lists the item for sale. An `Associate` or `ShopManager` lists an `APPRAISED` trade-in by supplying a `list_price_cents`, moving it to `LISTED`. Selling a `LISTED` item moves it to `SOLD`, computes `payout_cents` as 70 percent of `list_price_cents` (a 30 percent consignment fee), rounded half-up, records the `payout_method` as `CONSIGNMENT`, adds the payout to the member's `store_credit_cents`, and stamps `settled_at`. A trade-in may instead be returned to the member from `RECEIVED`, `APPRAISED`, or `LISTED`, moving it to `RETURNED`; returning a `LISTED` item clears its `list_price_cents` as it comes off consignment. `CASH_SETTLED`, `SOLD`, and `RETURNED` are terminal. Trade-ins can be fetched or listed by `member_id` and `status`.

### 3.7. Special Orders and Re-Quoting

A special order procures an item not carried in the catalog. A `Member` (for themselves), an `Associate`, or a `ShopManager` requests one by supplying the `member_id`, a free-text `product_name`, and a `qty` greater than zero; it starts in `REQUESTED`. The lifecycle is `REQUESTED` → `QUOTED` → `DEPOSIT_PAID` → `FULFILLED`, with `QUOTED` able to loop on itself for re-quotes. Special orders can be fetched or listed by `member_id` and `status`.

An `Associate` or `ShopManager` quotes the order by supplying a `quoted_price_cents` (zero or greater) together with the `expected_special_order_version` version guard; quoting is allowed while the order is in `REQUESTED` or `QUOTED`, and a re-quote legitimately overwrites the prior `quoted_price_cents`. The concurrency guard of §2.11 applies: a stale `expected_special_order_version` is rejected with `ERR_STALE_VERSION`, and each successful quote records `quoted_at` and advances the order's `version`. Collecting a deposit is allowed only from `QUOTED`, recording the supplied `deposit_cents` and moving the order to `DEPOSIT_PAID`. Fulfilling is allowed only from `DEPOSIT_PAID`; it awards loyalty on the `quoted_price_cents` net amount, stamps `fulfilled_at`, and moves the order to `FULFILLED`. The order may be cancelled from `REQUESTED`, `QUOTED`, or `DEPOSIT_PAID`; a `Member` may cancel their own order, and an `Associate` or `ShopManager` may cancel any. `FULFILLED` and `CANCELLED` are terminal.

### 3.8. Events and Member Registration

Events are shop gatherings that members join with loyalty points. A `ShopManager` creates an event with a `name`, a `capacity` greater than zero, and an optional `entry_points_cost` charged to each registering member (zero or greater, defaults to 0). An event starts `OPEN` with its `registration_count` at 0; this count is a derived tally of `REGISTERED` registrations, incremented on each registration and decremented on each registration cancellation.

Registering is performed by a `Member` for themselves, or by an `Associate` or `ShopManager`, supplying the `member_id`. Registration requires the event to be `OPEN` (else `ERR_EVENT_CLOSED`), the member to be `ACTIVE` (else `ERR_MEMBER_SUSPENDED`), no existing `REGISTERED` registration for the same event and member (else `ERR_DUPLICATE_REGISTRATION`), the `registration_count` to be strictly below `capacity` (else `ERR_EVENT_FULL`), and the member's `points_balance` to be at least the event's `entry_points_cost` (else `ERR_INSUFFICIENT_POINTS`); these are evaluated in that order per §2.5. On success a new registration is created in `REGISTERED`, its `points_charged` is set to the event's `entry_points_cost`, that many points are debited from the member's `points_balance`, and `registration_count` rises by one.

A registration may be cancelled by the owning `Member` or a `ShopManager` from `REGISTERED`, which refunds exactly the `points_charged` back to the member's `points_balance` and decrements the event's `registration_count`. Closing an event is a `ShopManager` action allowed only from `OPEN`; it moves the event to `CLOSED` and drives the depth-two cascade of §2.10, cancelling every `REGISTERED` registration and refunding each member's points. Registrations can be fetched individually or listed by `event_id`, `member_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; all other operations, including state transitions and modifications, return `200 OK`. Read operations are available to all four roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ShopManager |
| POST | `/products` | Create a catalog product | ShopManager |
| GET | `/products/{id}` | Fetch a product | All roles |
| GET | `/products` | List products | All roles |
| PATCH | `/products/{id}` | Update price or status | ShopManager |
| POST | `/products/{id}/restock` | Add physical units | ShopManager |
| POST | `/members` | Create a member | ShopManager, Associate |
| GET | `/members/{id}` | Fetch a member | All roles |
| POST | `/members/{id}/suspend` | Suspend a member (depth-3 cascade) | ShopManager |
| POST | `/members/{id}/reinstate` | Reinstate a suspended member | ShopManager |
| POST | `/instructors` | Create an instructor | ShopManager |
| GET | `/instructors/{id}` | Fetch an instructor | All roles |
| POST | `/service-bays` | Create a service bay | ShopManager |
| GET | `/service-bays/{id}` | Fetch a service bay | All roles |
| POST | `/rental-units` | Create a rental unit | ShopManager |
| GET | `/rental-units/{id}` | Fetch a rental unit | All roles |
| POST | `/board-builds` | Create a board build in DRAFT | ShopManager, Associate |
| GET | `/board-builds/{id}` | Fetch a build | All roles |
| GET | `/board-builds` | List builds | All roles |
| POST | `/board-builds/{id}/reserve` | Reserve components | ShopManager, Associate |
| POST | `/board-builds/{id}/assemble` | Mark assembled | ShopManager, Associate |
| POST | `/board-builds/{id}/revise` | Return to DRAFT, releasing reservations | ShopManager, Associate |
| POST | `/board-builds/{id}/setup` | Complete setup, compute final price | ShopManager, Associate |
| POST | `/board-builds/{id}/complete` | Hand over / sell the build | ShopManager, Associate |
| POST | `/board-builds/{id}/cancel` | Cancel a build | ShopManager, Associate |
| POST | `/service-orders` | Schedule a grip/wheel/wax service | ShopManager, Associate |
| GET | `/service-orders/{id}` | Fetch a service order | All roles |
| GET | `/service-orders` | List service orders | All roles |
| POST | `/service-orders/{id}/start` | Start the work | ShopManager, Associate |
| POST | `/service-orders/{id}/complete` | Complete the work, consume parts | ShopManager, Associate |
| POST | `/service-orders/{id}/cancel` | Cancel a service order | ShopManager, Associate |
| POST | `/rentals` | Create a rental reservation | ShopManager, Associate |
| GET | `/rentals/{id}` | Fetch a rental | All roles |
| GET | `/rentals` | List rentals | All roles |
| POST | `/rentals/{id}/checkout` | Check out a reserved rental | ShopManager, Associate |
| POST | `/rentals/{id}/return` | Return a rental, compute charges | ShopManager, Associate |
| POST | `/rentals/{id}/cancel` | Cancel a rental | ShopManager, Associate |
| POST | `/lessons` | Book a lesson | ShopManager, Associate |
| GET | `/lessons/{id}` | Fetch a lesson | All roles |
| GET | `/lessons` | List lessons | All roles |
| POST | `/lessons/{id}/confirm` | Confirm a lesson | ShopManager, Instructor |
| POST | `/lessons/{id}/complete` | Complete a lesson | ShopManager, Instructor |
| POST | `/lessons/{id}/cancel` | Cancel a lesson (cascades to rentals) | ShopManager, Instructor |
| POST | `/trade-ins` | Receive a trade-in | ShopManager, Associate |
| GET | `/trade-ins/{id}` | Fetch a trade-in | All roles |
| GET | `/trade-ins` | List trade-ins | All roles |
| POST | `/trade-ins/{id}/appraise` | Appraise a received trade-in | ShopManager |
| POST | `/trade-ins/{id}/buyout` | Instant buyout (cash or store credit) | ShopManager, Associate |
| POST | `/trade-ins/{id}/list` | List for consignment | ShopManager, Associate |
| POST | `/trade-ins/{id}/sell` | Sell a listed consignment item | ShopManager, Associate |
| POST | `/trade-ins/{id}/return` | Return the item to the member | ShopManager, Associate |
| POST | `/special-orders` | Request a special order | ShopManager, Associate, Member |
| GET | `/special-orders/{id}` | Fetch a special order | All roles |
| GET | `/special-orders` | List special orders | All roles |
| POST | `/special-orders/{id}/quote` | Quote / re-quote a price (OCC guarded) | ShopManager, Associate |
| POST | `/special-orders/{id}/deposit` | Collect a deposit | ShopManager, Associate |
| POST | `/special-orders/{id}/fulfill` | Fulfill the special order | ShopManager, Associate |
| POST | `/special-orders/{id}/cancel` | Cancel a special order | ShopManager, Associate, Member |
| POST | `/events` | Create a shop event | ShopManager |
| GET | `/events/{id}` | Fetch an event | All roles |
| POST | `/events/{id}/close` | Close an event (cascade cancels registrations) | ShopManager |
| POST | `/events/{id}/register` | Register a member for an event | ShopManager, Associate, Member |
| GET | `/event-registrations/{id}` | Fetch a registration | All roles |
| GET | `/event-registrations` | List registrations | All roles |
| POST | `/event-registrations/{id}/cancel` | Cancel a registration (refunds points) | ShopManager, Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 |
| `ERR_BAY_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_BUILD_NOT_FOUND` | 404 |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 |
| `ERR_RENTAL_NOT_FOUND` | 404 |
| `ERR_LESSON_NOT_FOUND` | 404 |
| `ERR_TRADEIN_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_EVENT_CLOSED` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_BUILD_NOT_READY` | 409 |
| `ERR_RENTAL_NOT_READY` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_EVENT_FULL` | 409 |
| `ERR_RENTAL_TOO_LONG` | 422 |
| `ERR_INSTRUCTOR_UNAVAILABLE` | 409 |
| `ERR_BAY_UNAVAILABLE` | 409 |
| `ERR_UNIT_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 402 |
| `ERR_STALE_VERSION` | 412 |
