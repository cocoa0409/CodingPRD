# Skate & Surf Shop API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a combined skate-and-surf retail and service shop. The business runs several intertwined operations under one roof: it sells catalog gear (decks, trucks, wheels, grip, wax, complete skateboards, surfboards, wetsuits, and accessories), builds custom boards from component parts, services boards at a repair bench, rents equipment by the day, schedules coaching lessons, runs sponsor-backed team events, takes in used gear on trade-in or consignment, and rewards members through a loyalty program. Each of these surfaces touches the same shared inventory and the same member ledger, so the value of the system lies in keeping them consistent with one another rather than in any single workflow.

The API models every business object — products, customers, coaches, rental assets, lessons, rentals, board builds, service tickets, trade-ins, special orders, events, and event entries — as a flat top-level collection. There is no nested URL ownership; children reference their parents by foreign key. The central engineering challenges are (a) finite-inventory bookkeeping, where a unit reserved by a board build must not be double-committed by a special order; (b) temporal scheduling, where a coach cannot teach two overlapping lessons and a physical rental unit cannot be rented to two customers at once; and (c) a loyalty and store-credit ledger that must accrue, reverse, and re-tier customers exactly as spend flows through builds, service, rentals, orders, and events.

The remainder of this document defines the system-wide contracts every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or invalid, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) before any other processing. If the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Four roles exist, spelled exactly as follows: `ShopManager`, `BenchTech`, `SalesAssociate`, and `Customer`.

- `ShopManager` is the operations manager. This role owns the catalog, inventory adjustments, coaches, rental-asset registration, events, trade-in appraisal and consignment sale, special-order quoting and fulfillment, board-build completion, and the logical clock. A `ShopManager` may perform any action the peer staff roles can, acting as a superset over them for the shared operational surfaces.
- `BenchTech` is the bench technician, responsible for board builds and grip/wheel/wax service tickets.
- `SalesAssociate` is front-of-house sales, responsible for customer creation, lessons, rentals, special-order intake and negotiation, trade-in intake, and event registration.
- `Customer` is a loyalty member acting on their own account.

When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `BenchTech` and for `SalesAssociate`: for each of these three staff roles, `X-User-ID` is an opaque operator identifier not bound to any stored entity, and the server does not compare it to any resource's ownership field. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare that resource's customer foreign key to `X-User-ID`.

Read operations (all listing and single-resource retrieval endpoints) are available to every role. Write operations are gated per the endpoint catalogue in Section 4; the "Authorized Role(s)" column there is authoritative for each individual endpoint.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a requested limit above 100 is capped at 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` ascending (oldest first). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — a UUID with no type prefix — at creation, and carries a `created_at` timestamp (ISO 8601 UTC, three fractional digits) recording when it was created. All entities in this system also carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 on creation and increments by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the logical clock time on each such mutation. When a state transition or side effect changes a resource, both its `updated_at` and its `version` advance. There are no version-less or timestamp-less entities in this version of the system.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation multiplies a base amount by a rate or discount and the result must be reduced to whole cents, the system rounds half up (a fractional remainder of exactly one-half cent rounds away from zero to the next whole cent). Several calculations round at the level of an individual line item before summing lines; the per-line rounding order is authoritative and is specified with each calculation in Section 3. Counts that are inherently whole — inventory units, loyalty points, day counts — are integers throughout; day counts derived from time windows always round up to a whole day, and loyalty point results apply a single floor at the very end of their computation.

### 2.6. Inventory Reservation and Availability Reconciliation

Each `Product` tracks three inventory quantities: `on_hand_qty` (units physically in stock), `reserved_qty` (units committed to board builds currently in `RESERVED` status), and `available_qty` (units free to promise). Availability is a derived field, reconciled on every mutation of its inputs as `available_qty` equal to `on_hand_qty` minus `reserved_qty`. Whenever `on_hand_qty` or `reserved_qty` changes — through an inventory adjustment, a board-build reservation, a board-build completion or cancellation, or a special-order fulfillment — `available_qty` is recomputed immediately. Under valid transitions `reserved_qty` and `available_qty` never go negative. A newly created product starts with `on_hand_qty`, `reserved_qty`, and `available_qty` all at 0. Availability is expressed in whole integer units.

### 2.7. Loyalty Ledger, Store Credit, and Tier Reconciliation

Each `Customer` carries four ledger fields: `loyalty_points` (a running point balance, floored at 0), `lifetime_spend_cents` (cumulative spend that only ever increases), `store_credit_cents` (a store-credit balance funded by trade-in and consignment payouts), and `tier` (one of `BRONZE`, `SILVER`, or `GOLD`). A newly created customer starts at `loyalty_points` 0, `lifetime_spend_cents` 0, `store_credit_cents` 0, and `tier` `BRONZE`, with `status` `ACTIVE` (the only customer status in this version).

Loyalty points accrue whenever spend is recorded against a customer. The accrual takes the transaction amount in cents, divides by 100, and floors it to yield one base point per whole dollar. That base-point figure is then multiplied by the customer's tier multiplier and, for event registrations only, an event bonus multiplier; a single floor is applied to the product at the very end, never to any intermediate factor, and the floored result is added to `loyalty_points`. The tier multiplier is 1.0 for `BRONZE`, 1.25 for `SILVER`, and 1.5 for `GOLD`. The event bonus multiplier is 2.0 and applies only to event-entry accrual; every other accrual uses a multiplier of 1.0 in that position. Critically, the tier multiplier is read from the customer's tier as it stands *before* the current transaction's spend is applied — the tier snapshot precedes the spend, not follows it.

Tier is reconciled after any increase to `lifetime_spend_cents`. A customer whose lifetime spend is at least 100000 cents is `GOLD`; a customer at least 50000 cents but below that is `SILVER`; anyone below 50000 cents is `BRONZE`. Both thresholds are inclusive lower bounds. Because spend only ever rises, a customer never drops a tier.

### 2.8. Optimistic Concurrency on Special-Order Revision

Revising a special order is guarded by optimistic concurrency control. A revise request must include `expected_special_order_version` carrying the client's last observed `version` of the target `SpecialOrder`. Before the revision is applied, the server compares `expected_special_order_version` against the special order's current `version`. If another writer has re-quoted or revised the order since the client last read it — advancing the order's `version` — the submitted value is stale and the revise is rejected with `ERR_STALE_VERSION` (HTTP 412). This is resolved purely by comparing the expected version to the live version; it does not depend on any assumption about request timing. Only the revise operation carries this version field; no other endpoint takes an expected-version input.

### 2.9. Temporal Scheduling and the Logical Clock

Time-sensitive behavior is governed by a logical clock rather than real wall-clock time. On server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly set it continues to read that default. A `ShopManager` may advance the clock by supplying a target instant in the `to_iso8601` field; the clock then reports that instant for all subsequent time reads, most notably the capture of a rental's `returned_at` and the resulting late-fee computation.

Scheduling windows for lessons and rentals are treated as half-open intervals `[start_at, end_at)`, so a window that ends exactly when another begins does not overlap it. Coach scheduling additionally enforces a setup buffer between consecutive lessons on the same coach: consecutive lessons on one coach must be separated by at least the setup buffer of 15 minutes, whereas rentals on a physical asset require no buffer and allow exact adjacency. The concrete overlap and buffer rules are stated with the lesson and rental workflows in Section 3.

### 2.10. Cascading State Propagation and Referential Integrity

Several operations mutate more than one entity in a single call, and every such cascade is specified in full with its workflow in Section 3. Cancelling a lesson releases its linked reserved rentals, which in turn refund deposits and free the underlying rental assets. Cancelling an event cancels all of its registered entries, which in turn reverse each entry's loyalty accrual and decrement the event's entry count. Returning, releasing, checking out, and reserving rentals move the associated rental asset through its own status. In every case the affected entities each advance their own `version` and `updated_at`.

Referenced resources are validated left to right: any resource named by a path parameter is checked to exist before foreign keys carried in the request body are checked, and each missing reference yields the not-found error for its specific entity type (for example `ERR_PRODUCT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_COACH_NOT_FOUND`, `ERR_RENTAL_ASSET_NOT_FOUND`, `ERR_LESSON_NOT_FOUND`, `ERR_RENTAL_NOT_FOUND`, `ERR_BOARD_BUILD_NOT_FOUND`, `ERR_SERVICE_TICKET_NOT_FOUND`, `ERR_TRADE_IN_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_EVENT_ENTRY_NOT_FOUND`). The order in which the system evaluates checks across every write is fixed: authentication first (`ERR_MISSING_AUTH_CONTEXT`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of referenced resources (the not-found errors), then body well-formedness (`ERR_VALIDATION` — required fields present, types and enums valid, `end_at` strictly after `start_at`, and quantities or amounts within their allowed ranges), then the target resource being in a state that permits the requested transition (the per-entity invalid-state errors, HTTP 409), and only then the domain-specific business rules described below. A well-formedness failure — a missing required field, a bad type or enum value, an `end_at` that is not strictly greater than `start_at`, or a non-positive quantity or amount where a positive one is required — is always reported as `ERR_VALIDATION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Catalog, Inventory, and Rental Assets

The catalog is the shop's source of truth for what it sells and rents. A `ShopManager` creates a product by supplying its `sku`, `name`, `category`, and `unit_price_cents`, and may optionally supply a `rental_day_rate_cents` and an `is_rentable` flag. The `sku` is the stock-keeping unit and must be unique across all products; an attempt to create a product whose `sku` already exists is rejected with `ERR_DUPLICATE_SKU`. The `category` must be one of nine values: `DECK`, `TRUCKS`, `WHEELS`, `GRIP`, `WAX`, `COMPLETE`, `SURFBOARD`, `WETSUIT`, or `ACCESSORY`. The `unit_price_cents` is the integer-cents retail price and may not be negative. The `rental_day_rate_cents` is the per-day rental charge in cents, defaulting to 0 and used only when the product is rentable; `is_rentable` defaults to false and governs whether physical rental units may be registered against the product. A new product opens in `status` `ACTIVE`.

Stock levels are moved by inventory adjustments. A `ShopManager` records a receipt or a shrink by supplying `delta_on_hand`, a signed integer that is added to the product's `on_hand_qty`, after which `available_qty` is reconciled per Section 2.6. A `ShopManager` may also discontinue a product, moving it from `ACTIVE` to `DISCONTINUED`; a product that is not `ACTIVE` cannot be discontinued again. A discontinued product remains queryable and keeps its inventory figures, but it may no longer be used as a board-build component or as a special-order target.

Physical rental units are registered separately as rental assets. A `ShopManager` creates a rental asset by supplying the `product_id` of the rentable SKU it instantiates, an `asset_tag` that must be unique across all rental assets, and an optional `condition` that is one of `GOOD` (the default), `FAIR`, or `NEEDS_SERVICE`. A duplicate `asset_tag` is rejected with `ERR_DUPLICATE_ASSET_TAG`. A rental asset begins life in `status` `AVAILABLE` and moves through `RESERVED` and `OUT` as rentals are placed against it, as described in Section 3.4. Rental assets can be listed and filtered by their `product_id`.

### 3.2. Membership, Loyalty, and Store Credit

A member record is created by a `ShopManager` or a `SalesAssociate`, who supplies the customer's `email` (unique across customers) and `full_name`. The member's ledger — `loyalty_points`, `lifetime_spend_cents`, `store_credit_cents`, and `tier` — is initialized as described in Section 2.7 and thereafter maintained automatically as the member transacts.

Beyond the automatic accruals that flow from builds, service, rentals, orders, and events, staff may adjust a member's loyalty balance directly. A loyalty adjustment carries a `kind` of either `EARN` or `REDEEM`. An `EARN` adjustment supplies `spend_cents`: that amount is added to `lifetime_spend_cents`, loyalty points are accrued from it using the standard accrual (with no event bonus), and the member's `tier` is reconciled. A `REDEEM` adjustment supplies `points`: that many points are subtracted from `loyalty_points`, which may not be driven below zero — a redemption exceeding the member's available `loyalty_points` is refused with `ERR_INSUFFICIENT_POINTS`. Only a `ShopManager` or a `SalesAssociate` may record loyalty adjustments.

Store credit is a separate balance from loyalty points. It is never adjusted directly; it grows only through trade-in store-credit payouts and consignment sales, as described in Section 3.7.

### 3.3. Lessons and Coach Scheduling

Coaches are the scheduling resource for lessons. A `ShopManager` registers a coach with a `name` and a `discipline` of either `SURF` or `SKATE`, and the coach opens in `status` `ACTIVE`.

A `SalesAssociate` or `ShopManager` books a lesson by supplying the `coach_id`, the `customer_id`, the lesson `discipline`, and the `start_at` and `end_at` bounding the session (ISO 8601 UTC, with `end_at` required to be strictly after `start_at`). The lesson's `discipline` must match the coach's own discipline. A booked lesson opens in `status` `SCHEDULED`.

Coach availability is enforced at booking time against the coach's existing `SCHEDULED` lessons, treating each lesson as the half-open interval from its `start_at` up to but not including its `end_at`. A new lesson is refused with `ERR_COACH_UNAVAILABLE` when it collides with an existing `SCHEDULED` lesson on the same coach — that is, when the new lesson's window overlaps an existing one, or when the two are not separated by at least the setup buffer of 15 minutes (a new lesson whose `start_at` falls earlier than an existing lesson's `end_at` plus that 15-minute buffer, and whose interval collides with the buffered window, is rejected). Lessons on different coaches never conflict with one another.

A `SalesAssociate` or `ShopManager` closes out a scheduled lesson in one of two ways. Completing the lesson supplies an `outcome`: an `outcome` of `COMPLETED` (the default when none is given) moves the lesson from `SCHEDULED` to `COMPLETED`, while an `outcome` of `NO_SHOW` moves it from `SCHEDULED` to `NO_SHOW`. Alternatively, the lesson may be cancelled, moving it from `SCHEDULED` to `CANCELLED`. Any of these three closures requires the lesson to currently be `SCHEDULED`; attempting them from any other state is rejected with `ERR_LESSON_INVALID_STATE`.

Cancelling a lesson cascades to its linked rentals. Every rental whose `lesson_id` points at the cancelled lesson and whose fulfillment is still `RESERVED` is released as part of the cancellation (the first hop of the cascade): each such rental's `fulfillment_status` moves from `RESERVED` to `RELEASED`. That release in turn (the second hop) sets the rental's `payment_status` from `DEPOSIT_HELD` to `DEPOSIT_REFUNDED` and transitions its rental asset from `RESERVED` back to `AVAILABLE`. Rentals linked to the lesson that are no longer `RESERVED` are left untouched.

### 3.4. Rentals

A rental books a physical asset to a member for a window. A `SalesAssociate` or `ShopManager` creates one by supplying the `customer_id`, the `rental_asset_id` of the unit being rented, the `start_at` and `end_at` of the window (half-open, with `end_at` strictly after `start_at`), and the `deposit_cents` security deposit held in cents (which may not be negative). An optional `lesson_id` links the rental to a lesson; it is null for a standalone rental. On creation the rental opens with `fulfillment_status` `RESERVED` and `payment_status` `DEPOSIT_HELD`, the underlying rental asset moves from `AVAILABLE` to `RESERVED`, and the rental fee is computed. Rentals can be listed and filtered by `customer_id`, `rental_asset_id`, or `lesson_id`.

Asset availability is enforced when the rental is created. A new rental is refused with `ERR_ASSET_UNAVAILABLE` if its window overlaps an existing non-terminal rental — one whose fulfillment is `RESERVED` or `PICKED_UP` — on the same asset. Overlap uses the same half-open convention `[start_at, end_at)`, so exact adjacency is permitted: a new rental whose `start_at` equals an existing rental's `end_at` is accepted, and no separation buffer is applied between rentals on an asset.

The rental fee is the number of whole rental days multiplied by the product's `rental_day_rate_cents`. The day count is obtained by taking the elapsed time from `start_at` to `end_at` in seconds, dividing by 86400, and rounding up to the next whole day, so any partial day counts as a full day; the resulting `rental_fee_cents` is stored at creation.

A rental's two status dimensions evolve independently. Fulfillment tracks the physical lifecycle (`RESERVED`, `PICKED_UP`, `RETURNED`, `RELEASED`), while payment tracks the deposit (`DEPOSIT_HELD`, `DEPOSIT_CAPTURED`, `DEPOSIT_REFUNDED`).

Checking out a reserved rental (a `SalesAssociate` or `ShopManager` action) requires the rental's `fulfillment_status` to be `RESERVED`, failing which the request is rejected with `ERR_RENTAL_INVALID_STATE`. Additionally, if the rental carries a `lesson_id`, the linked lesson must currently be `SCHEDULED`; if it is not, checkout is refused with `ERR_LESSON_NOT_SCHEDULED`. On checkout the fulfillment moves from `RESERVED` to `PICKED_UP` while the payment dimension stays `DEPOSIT_HELD`, and the rental asset moves from `RESERVED` to `OUT`.

Returning a picked-up rental requires the fulfillment to be `PICKED_UP`, else `ERR_RENTAL_INVALID_STATE`. On return the current logical-clock instant is captured into `returned_at`, and the late fee is computed: if `returned_at` is at or before `end_at` the `late_fee_cents` is 0 (an on-time return, with the boundary inclusive), otherwise the number of late days is the elapsed time from `end_at` to `returned_at` in seconds divided by 86400 and rounded up to a whole day, multiplied by a late fee of 1000 cents per day. Fulfillment then moves from `PICKED_UP` to `RETURNED`. The payment dimension resolves independently: it becomes `DEPOSIT_CAPTURED` when the computed `late_fee_cents` is greater than zero, and `DEPOSIT_REFUNDED` when it is zero. The rental asset moves from `OUT` back to `AVAILABLE`. Finally the member's `lifetime_spend_cents` is increased by the sum of `rental_fee_cents` and `late_fee_cents`, loyalty is accrued on that combined amount (with no event bonus), and the member's `tier` is reconciled.

Releasing a still-reserved rental (available to a `SalesAssociate` or `ShopManager`, and also performed automatically when a linked lesson is cancelled) requires the fulfillment to be `RESERVED`, else `ERR_RENTAL_INVALID_STATE`. On release the fulfillment moves from `RESERVED` to `RELEASED`, the payment dimension moves from `DEPOSIT_HELD` to `DEPOSIT_REFUNDED`, and the rental asset moves from `RESERVED` back to `AVAILABLE`. `RETURNED` and `RELEASED` are the terminal fulfillment states.

### 3.5. Board Builds

A board build assembles a custom board from catalog components. A `BenchTech` or `ShopManager` opens a build by supplying the `customer_id` it is for and a `components` array; each component is a line item of a `product_id` and an integer `qty` of at least 1. A new build opens in `status` `DRAFT` with its `provisional_cost_cents` and `final_cost_cents` both 0.

Reserving a draft build (a `BenchTech` or `ShopManager` action) requires the build to be `DRAFT`, else `ERR_BUILD_INVALID_STATE`. Two business rules then gate the reservation. First, no component product may be `DISCONTINUED`; if any is, the reservation is refused with `ERR_COMPONENT_INCOMPATIBLE`. Second, every component must have sufficient stock — each component's product `available_qty` must be greater than or equal to that component's line `qty`; if any falls short, the reservation is refused with `ERR_INSUFFICIENT_STOCK`. When both hold, the build moves from `DRAFT` to `RESERVED`, its provisional cost is computed, and for each component the product's `reserved_qty` is increased by the line `qty` and its `available_qty` is reconciled.

The provisional cost, set at reservation, is the plain list-price sum with no bundle discount: for each component the product's `unit_price_cents` is multiplied by its `qty`, those line amounts are summed, and a fixed build labor charge of 2500 cents is added. No rounding is needed here because the inputs are already whole cents.

Completing a reserved build (a `BenchTech` or `ShopManager` action) requires the build to be `RESERVED`, else `ERR_BUILD_INVALID_STATE`. On completion the final cost is computed, and for each component the product's `reserved_qty` and `on_hand_qty` are both reduced by the line `qty`, with `available_qty` reconciled. The member's `lifetime_spend_cents` is then increased by the `final_cost_cents`, loyalty is accrued on that amount (no event bonus), and the member's `tier` is reconciled. The final cost applies a 10% per-line bundle discount in a pinned order: for each component, multiply the product's `unit_price_cents` by the line `qty` and by nine-tenths (one minus the 10% bundle discount), round that line half up to whole cents, then sum the rounded lines, and finally add the same 2500-cent labor charge (labor is neither discounted nor taxed). The per-line rounding before summing is authoritative, so the final cost may differ from the provisional cost for the identical set of components. The product prices used in both variants are read at the moment of the respective transition.

Cancelling a build (a `BenchTech` or `ShopManager` action) is permitted while the build is `DRAFT` or `RESERVED`; from any other state it is rejected with `ERR_BUILD_INVALID_STATE`. The build moves to `CANCELLED`. If the build was `RESERVED` at the time of cancellation, the reservation is compensatingly released: for each component the product's `reserved_qty` is decreased by the line `qty` and `available_qty` is reconciled, while `on_hand_qty` is left unchanged. Cancelling a build that was still `DRAFT` releases nothing, since no stock was ever reserved. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Service Tickets

A service ticket captures a grip, wheel, or wax job at the bench. A `BenchTech` or `ShopManager` opens one with the `customer_id`, a free-text `board_description` of the board being serviced, a `parts` array, and a `labor_cents` charge (before tax, non-negative). Each entry in `parts` is a line of `product_id`, an integer `qty`, and the `unit_price_cents` charged for that part on this ticket. A new ticket opens in `status` `INTAKE`.

Marking a ticket ready (a `BenchTech` or `ShopManager` action) requires it to be `INTAKE`, else `ERR_SERVICE_INVALID_STATE`. On the transition to `READY` the ticket total is computed with tax applied per line in a pinned order. Each part line's `unit_price_cents` is multiplied by its `qty` and by one plus the tax rate of 0.0725, and that line is rounded half up to whole cents; the taxed part lines are then summed. Separately, the `labor_cents` is multiplied by one plus the same tax rate and rounded half up to whole cents to form the labor line. The `total_cents` is the sum of the taxed part-line total and the taxed labor line. The per-line taxing-and-rounding order is authoritative — the total is not computed by summing raw subtotals and taxing once at the end.

Picking up a ready ticket (a `BenchTech` or `ShopManager` action) requires it to be `READY`, else `ERR_SERVICE_INVALID_STATE`. On pickup the ticket moves to `PICKED_UP`, the member's `lifetime_spend_cents` is increased by the ticket `total_cents`, loyalty is accrued on that amount (no event bonus), and the member's `tier` is reconciled. A ticket may instead be cancelled from either `INTAKE` or `READY`, moving it to `CANCELLED`; cancelling from any other state is rejected with `ERR_SERVICE_INVALID_STATE`, and cancellation records no spend. `PICKED_UP` and `CANCELLED` are terminal.

### 3.7. Trade-Ins and Consignment

The shop takes in used gear through a single intake that branches on mode. A `SalesAssociate`, `ShopManager`, or `Customer` opens a trade-in with the `customer_id` of the consignor, an `item_description`, a `mode` of either `TRADE_IN` or `CONSIGNMENT`, and, for consignment intake, a `list_price_cents` listing price. A new record opens in `status` `RECEIVED`.

A `ShopManager` appraises a received item by supplying its `appraised_value_cents`, which requires the record to be `RECEIVED`, else `ERR_TRADE_IN_INVALID_STATE`. Appraisal moves the record to `APPRAISED`, stores the appraised value, and computes both standing offers from it: the `cash_offer_cents` is the appraised value multiplied by 0.50 and rounded half up to whole cents, and the `store_credit_offer_cents` is the appraised value multiplied by 0.70 and rounded half up to whole cents. The store-credit offer is deliberately the more generous of the two for identical appraised input.

From `APPRAISED`, the consignor decides. Accepting an appraised record (a `Customer`, `SalesAssociate`, or `ShopManager` action) branches on the record's `mode`. For a `TRADE_IN`, acceptance requires a `payout_choice` of either `CASH` or `STORE_CREDIT` and moves the record to `ACCEPTED`; if the choice is `STORE_CREDIT`, the member's `store_credit_cents` is increased by the `store_credit_offer_cents`, whereas a `CASH` choice pays out externally and adds no store credit. For a `CONSIGNMENT`, acceptance requires the `list_price_cents` to be greater than zero and moves the record to `LISTED`, putting the item up for consignment sale at its listing price. Alternatively the appraised offer may be rejected (again by a `Customer`, `SalesAssociate`, or `ShopManager`), moving the record to `REJECTED` with no payout; rejection requires the record to be `APPRAISED`, else `ERR_TRADE_IN_INVALID_STATE`.

When a listed consignment item sells, a `ShopManager` records the sale by supplying the `sold_price_cents`, which requires the record to be `LISTED`, else `ERR_TRADE_IN_INVALID_STATE`. The record moves to `SOLD`, the consignor credit is computed as the `sold_price_cents` multiplied by 0.60 and rounded half up to whole cents, and that `consignor_credit_cents` is added to the member's `store_credit_cents`. `REJECTED` and `SOLD` are terminal.

### 3.8. Special Orders

A special order requests a SKU the shop does not stock on hand. A `SalesAssociate`, `ShopManager`, or `Customer` opens one with the `customer_id`, the `product_id` of the SKU wanted, and a `quantity` of at least 1. A new order opens in `status` `DRAFT` with `quoted_price_cents` 0 and `revision_count` 0. Orders can be listed and filtered by `customer_id` or `product_id`.

A `ShopManager` quotes the order by supplying the `quoted_price_cents`. Quoting is permitted from `DRAFT` or from `CUSTOMER_REVIEW` (a re-quote after a revision round), else `ERR_ORDER_INVALID_STATE`; it moves the order to `QUOTED`, records the quoted price, and advances the order's `version` by 1.

From `QUOTED`, three paths are open. A `SalesAssociate` or `ShopManager` may open a revision round, which requires the order to be `QUOTED` (else `ERR_ORDER_INVALID_STATE`) and is additionally guarded by the optimistic-concurrency check of Section 2.8: the request must carry `expected_special_order_version` matching the order's live `version`, or it is rejected with `ERR_STALE_VERSION`. A successful revision moves the order from `QUOTED` to `CUSTOMER_REVIEW`, increments `revision_count` by 1, and advances the order's `version` by 1; the negotiation then cycles back to `QUOTED` via a fresh quote. Alternatively, a `Customer`, `SalesAssociate`, or `ShopManager` may approve the current quote, moving the order from `QUOTED` to `APPROVED`.

A `ShopManager` fulfills an approved order, which requires it to be `APPROVED`, else `ERR_ORDER_INVALID_STATE`. Fulfillment additionally requires sufficient stock: the target product's `available_qty` must be at least the order `quantity`, or the request is refused with `ERR_INSUFFICIENT_STOCK`. On fulfillment the product's `on_hand_qty` is reduced by the `quantity` and its `available_qty` is reconciled, the order moves to `FULFILLED`, the member's `lifetime_spend_cents` is increased by the `quoted_price_cents`, loyalty is accrued on that amount (no event bonus), and the member's `tier` is reconciled. A special order may be cancelled by a `SalesAssociate`, `ShopManager`, or `Customer` from any non-terminal state (`DRAFT`, `QUOTED`, `CUSTOMER_REVIEW`, or `APPROVED`), moving it to `CANCELLED`; cancelling an order that is already terminal is rejected with `ERR_ORDER_INVALID_STATE`. `FULFILLED` and `CANCELLED` are terminal.

### 3.9. Events and Entries

The shop runs sponsor-backed events. A `ShopManager` creates one with a `name`, a `sponsor` brand or team, a `venue`, a `start_at`, a `capacity` (the maximum number of registered entries, at least 1), and an `entry_fee_cents` per-entry fee (non-negative), which also drives the loyalty accrual for each registration. A new event opens in `status` `DRAFT` with `entry_count` 0.

A `ShopManager` publishes a draft event, moving it from `DRAFT` to `PUBLISHED` and opening it to registrations; publishing requires the event to be `DRAFT`, else `ERR_EVENT_INVALID_STATE`. A `ShopManager` may also cancel an event from either `DRAFT` or `PUBLISHED` (else `ERR_EVENT_INVALID_STATE`), moving it to `CANCELLED`. Cancelling an event cascades: every `REGISTERED` entry for the event is moved to `CANCELLED` (the first hop), and each of those entry cancellations (the second hop) reverses that entry's awarded points from the member's `loyalty_points` and decrements the event's `entry_count`.

Registering an entry is done by a `Customer`, `SalesAssociate`, or `ShopManager` with the `event_id`, the `customer_id` of the participant, and an optional `role` of either `TEAM_RIDER` or `PUBLIC` (defaulting to `PUBLIC`). Registration is subject to two gates: the event must be `PUBLISHED`, or the entry is refused with `ERR_EVENT_NOT_OPEN`; and the event's `entry_count` must be strictly below its `capacity`, or the entry is refused with `ERR_EVENT_FULL`. A successful entry opens in `status` `REGISTERED` and increments the event's `entry_count` by 1. Loyalty accrues for the entry using the event bonus: the `points_awarded` is computed from the event's `entry_fee_cents` against the member's current tier snapshot with the event bonus multiplier applied, and that amount is added to the member's `loyalty_points`. The member's `lifetime_spend_cents` is also increased by the `entry_fee_cents` and the member's `tier` reconciled.

An entry may be cancelled by a `Customer`, `SalesAssociate`, or `ShopManager` (and is also cancelled automatically when its parent event is cancelled), which requires the entry to be `REGISTERED`, else `ERR_ENTRY_INVALID_STATE`. Cancelling an entry decrements the event's `entry_count` by 1 and reverses exactly the entry's `points_awarded` from the member's `loyalty_points`, restoring the pre-entry balance. `CANCELLED` is terminal for an entry.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2 and the authentication rules of Section 2.1. Creating a new resource returns HTTP 201; retrievals, listings, and state-changing actions on existing resources return HTTP 200. Request bodies, response bodies, and side effects for each endpoint are described in the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /products | Create a product/SKU | ShopManager |
| GET | /products | List products | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /products/{id} | Get a product | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /products/{id}/inventory-adjustments | Adjust on-hand stock | ShopManager |
| POST | /products/{id}/discontinue | Discontinue a product | ShopManager |
| POST | /customers | Create a loyalty customer | ShopManager, SalesAssociate |
| GET | /customers | List customers | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /customers/{id} | Get a customer | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /customers/{id}/loyalty-adjustments | Accrue (EARN) or redeem (REDEEM) points | ShopManager, SalesAssociate |
| POST | /coaches | Create a coach | ShopManager |
| GET | /coaches | List coaches | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /coaches/{id} | Get a coach | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /rental-assets | Create a physical rental unit | ShopManager |
| GET | /rental-assets | List rental assets (filter by product_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /rental-assets/{id} | Get a rental asset | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /lessons | Book a lesson on a coach | SalesAssociate, ShopManager |
| GET | /lessons | List lessons (filter by coach_id, customer_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /lessons/{id} | Get a lesson | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /lessons/{id}/complete | Complete or mark no-show | SalesAssociate, ShopManager |
| POST | /lessons/{id}/cancel | Cancel a scheduled lesson | SalesAssociate, ShopManager |
| POST | /rentals | Reserve a rental asset for a window | SalesAssociate, ShopManager |
| GET | /rentals | List rentals (filter by customer_id, rental_asset_id, lesson_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /rentals/{id} | Get a rental | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /rentals/{id}/checkout | Pick up a reserved rental | SalesAssociate, ShopManager |
| POST | /rentals/{id}/return | Return a picked-up rental | SalesAssociate, ShopManager |
| POST | /rentals/{id}/release | Release a still-reserved rental | SalesAssociate, ShopManager |
| POST | /board-builds | Create a draft board build | BenchTech, ShopManager |
| GET | /board-builds | List board builds (filter by customer_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /board-builds/{id} | Get a board build | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /board-builds/{id}/reserve | Reserve component stock and price provisionally | BenchTech, ShopManager |
| POST | /board-builds/{id}/complete | Complete build, consume stock, finalize price | BenchTech, ShopManager |
| POST | /board-builds/{id}/cancel | Cancel a build (release any reservation) | BenchTech, ShopManager |
| POST | /service-tickets | Open a grip/wheel/wax service ticket | BenchTech, ShopManager |
| GET | /service-tickets | List service tickets (filter by customer_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /service-tickets/{id} | Get a service ticket | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /service-tickets/{id}/ready | Mark service ready (compute total) | BenchTech, ShopManager |
| POST | /service-tickets/{id}/pickup | Customer picks up (record spend) | BenchTech, ShopManager |
| POST | /service-tickets/{id}/cancel | Cancel a service ticket | BenchTech, ShopManager |
| POST | /trade-ins | Intake a trade-in or consignment item | SalesAssociate, ShopManager, Customer |
| GET | /trade-ins | List trade-ins (filter by customer_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /trade-ins/{id} | Get a trade-in | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /trade-ins/{id}/appraise | Set appraised value and compute offers | ShopManager |
| POST | /trade-ins/{id}/accept | Accept offer (trade-in payout or consignment listing) | Customer, SalesAssociate, ShopManager |
| POST | /trade-ins/{id}/reject | Reject the appraisal offer | Customer, SalesAssociate, ShopManager |
| POST | /trade-ins/{id}/sell | Record a consignment sale | ShopManager |
| POST | /special-orders | Open a special order for a SKU | SalesAssociate, ShopManager, Customer |
| GET | /special-orders | List special orders (filter by customer_id, product_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /special-orders/{id} | Get a special order | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /special-orders/{id}/quote | Quote (or re-quote) the order price | ShopManager |
| POST | /special-orders/{id}/revise | Open a revision round (OCC-guarded) | SalesAssociate, ShopManager |
| POST | /special-orders/{id}/approve | Customer approves the current quote | Customer, SalesAssociate, ShopManager |
| POST | /special-orders/{id}/fulfill | Fulfill from stock | ShopManager |
| POST | /special-orders/{id}/cancel | Cancel a non-terminal special order | SalesAssociate, ShopManager, Customer |
| POST | /events | Create a sponsor/team event | ShopManager |
| GET | /events | List events | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /events/{id} | Get an event | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /events/{id}/publish | Publish an event (opens entries) | ShopManager |
| POST | /events/{id}/cancel | Cancel an event (cascade cancel entries) | ShopManager |
| POST | /event-entries | Register a customer for a published event | Customer, SalesAssociate, ShopManager |
| GET | /event-entries | List entries (filter by event_id, customer_id) | ShopManager, BenchTech, SalesAssociate, Customer |
| GET | /event-entries/{id} | Get an entry | ShopManager, BenchTech, SalesAssociate, Customer |
| POST | /event-entries/{id}/cancel | Cancel an entry (reverse loyalty accrual) | Customer, SalesAssociate, ShopManager |
| POST | /_clock/set_current_utc | Set the logical clock | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_AUTH_CONTEXT | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_VALIDATION | 400 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_COACH_NOT_FOUND | 404 |
| ERR_RENTAL_ASSET_NOT_FOUND | 404 |
| ERR_LESSON_NOT_FOUND | 404 |
| ERR_RENTAL_NOT_FOUND | 404 |
| ERR_BOARD_BUILD_NOT_FOUND | 404 |
| ERR_SERVICE_TICKET_NOT_FOUND | 404 |
| ERR_TRADE_IN_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_EVENT_ENTRY_NOT_FOUND | 404 |
| ERR_DUPLICATE_SKU | 409 |
| ERR_DUPLICATE_ASSET_TAG | 409 |
| ERR_LESSON_INVALID_STATE | 409 |
| ERR_RENTAL_INVALID_STATE | 409 |
| ERR_BUILD_INVALID_STATE | 409 |
| ERR_SERVICE_INVALID_STATE | 409 |
| ERR_TRADE_IN_INVALID_STATE | 409 |
| ERR_ORDER_INVALID_STATE | 409 |
| ERR_EVENT_INVALID_STATE | 409 |
| ERR_ENTRY_INVALID_STATE | 409 |
| ERR_COMPONENT_INCOMPATIBLE | 422 |
| ERR_COACH_UNAVAILABLE | 409 |
| ERR_ASSET_UNAVAILABLE | 409 |
| ERR_LESSON_NOT_SCHEDULED | 409 |
| ERR_EVENT_NOT_OPEN | 409 |
| ERR_EVENT_FULL | 409 |
| ERR_INSUFFICIENT_STOCK | 402 |
| ERR_INSUFFICIENT_POINTS | 402 |
| ERR_STALE_VERSION | 412 |
