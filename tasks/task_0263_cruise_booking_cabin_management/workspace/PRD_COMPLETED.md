# Cruise Booking & Cabin Management API — Product Requirements Document

## 1. Introduction

This document specifies the Cruise Booking & Cabin Management API, a back-office and guest-facing system that governs the sale of cabin inventory aboard scheduled voyages. The platform answers a deceptively simple-looking commercial question — *which guests occupy which cabins on which sailing, at what price, and under what payment and cancellation terms* — but the answer touches a finite physical resource (a fixed pool of cabins per category), a multi-stage pricing engine (per-guest fare, occupancy tiering, group discounts, taxes and port fees), a deposit-and-final-payment schedule, and a layered cancellation policy that can return value as cash or as future cruise credit.

Several forces make the domain unusually demanding. Cabin inventory is scarce and shared: the same pool feeds individual bookings and negotiated group blocks, so the system must allocate, hold, block, and release cabins without ever over-committing the physical ship. Concurrency compounds this — two reservation flows reading the same sailing must not both believe a cabin is free — which the system resolves with optimistic concurrency control keyed on the sailing's inventory epoch. Money flows are equally exacting: fares are computed per guest in integer cents with deterministic rounding, deposits are floored per guest, and a cancellation can branch into two arithmetically distinct settlements depending on whether the guest elects a cash refund or a future-cruise credit. The sections that follow define the global contract every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that every endpoint inherits.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes five roles by these exact names: `RevenueManager`, `ReservationsAgent`, `GuestUser`, `PortAgent`, and `system`. When a caller presents a well-formed role that is not authorized for the targeted operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `GuestUser`, the role is entity-backed by the booking it owns: `X-User-ID` is the value stored as `owner_user_id` on any `Booking` the user owns, and ownership checks on a booking compare the booking's `owner_user_id` to `X-User-ID`. A `GuestUser` acting on a booking that is not theirs is rejected with `ERR_NOT_BOOKING_OWNER`. The remaining roles carry opaque identities: when `X-User-Role` is `RevenueManager`, `ReservationsAgent`, `PortAgent`, or `system`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier for audit, but it does not compare it to any entity's `id`. The `system` role names the automation actor that performs cascaded transitions — sailing-cancellation propagation, clock-driven expiry and block release, and the embark cascade — and is not a role a human caller presents to mutate resources directly.

`RevenueManager` manages sailings, inventory (cabin categories and cabins), and group blocks, and is the only role permitted to set the simulated clock. `ReservationsAgent` acts on behalf of guests across the booking, guest-roster, add-on, dining, and payment surfaces, and exclusively owns payment failure and refund processing. `GuestUser` owns and manages only their own bookings and everything hanging off them. `PortAgent` is the onboard and terminal operator: it departs sailings, embarks and settles bookings, and posts and reverses folio charges. All four human roles may read via the `GET` endpoints.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items skipped before the page begins and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Every entity in this system additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by 1 on each subsequent mutation. There are no exceptions in this domain — all of `Sailing`, `CabinCategory`, `Cabin`, `GroupBlock`, `Booking`, `Guest`, `AddOn`, `DiningReservation`, `Payment`, `Folio`, and `FolioCharge` carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

The `version` field is more than an audit counter. When a computed field is recomputed as a side effect — a category's cabin counts shifting, a booking's totals being re-derived, a folio balance being refreshed — that recomputation refreshes `updated_at` on the resource that changed, and the financial roll-ups (a booking's totals and a folio's balance, along with a guest's recomputed fares) additionally increment that resource's `version`. The derived cabin-count roll-ups on a `CabinCategory` and the rolled-up totals on a `Sailing`, and the `blocked_count`/`materialized_count` on a `GroupBlock`, refresh `updated_at` but do not increment `version`: their `version` advances only on a direct mutation of that resource (a created/edited field or a state transition). The `version` field on `Sailing` additionally plays a contractual role in concurrency control, described in Section 2.7.

### 2.5. Nested Identifier Resolution and Referential Integrity

Resources in this domain are peers linked by foreign-key fields carried in request bodies rather than nested in URL paths; a path therefore contains at most one resource identifier. When a request references resources — both the `{id}` in the path and any foreign-key field in the body, such as `sailing_id`, `cabin_category_id`, `booking_id`, `guest_id`, `folio_id`, or `group_block_id` — the system validates their existence in left-to-right order: the path identifier first, then the body foreign keys in the order they appear. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined and before any business rule runs.

The order in which the system evaluates a request is fixed and shared across all endpoints. Header well-formedness is checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then, for a `GuestUser` acting on a booking, ownership (`ERR_NOT_BOOKING_OWNER`), then the legality of the requested state transition (`ERR_INVALID_STATE`), then cross-entity status gating such as the parent sailing being in a bookable status (`ERR_SAILING_NOT_BOOKABLE`), then domain business constraints such as occupancy and uniqueness (`ERR_OCCUPANCY_EXCEEDED` and the uniqueness errors), then temporal-conflict checks (`ERR_TIME_WINDOW_CONFLICT`), then the inventory-sufficiency check (`ERR_INSUFFICIENT_INVENTORY`), then the deposit and balance gates (`ERR_BALANCE_OUTSTANDING` and its siblings), and finally the optimistic-concurrency check on booking creation (`ERR_STALE_SAILING_VERSION`). Earlier checks strictly precede later ones; a failure surfaces the earliest applicable error rather than being masked by a later one.

### 2.6. Hierarchical Consistency and Cascades

State changes propagate down the resource hierarchy atomically within the triggering request — every cascade described in Section 3 completes, or the whole request fails, with no partially applied intermediate state visible to clients. Cabin-count fields on a `CabinCategory` (`total_cabins`, `available_cabins`, `held_cabins`, `assigned_cabins`, `blocked_cabins`) and the rolled-up `total_cabins` and `available_cabins` on a `Sailing` are derived from the cabins beneath them and are kept consistent whenever a cabin's `status` changes. Likewise `blocked_count` and `materialized_count` on a `GroupBlock`, and the financial roll-ups on a `Booking` and `Folio`, are recomputed whenever an event beneath them warrants it. Each such recomputation refreshes the affected resource's `updated_at`; per Section 2.4 it additionally increments `version` only for the `Booking` and `Folio` financial roll-ups (and a guest's recomputed fares), while the `CabinCategory`, `Sailing`, and `GroupBlock` count roll-ups leave `version` unchanged.

### 2.7. Optimistic Concurrency on the Cabin Pool

Cabin inventory is finite, and the act of creating a booking against a sailing must not proceed on a stale view of that sailing's inventory epoch. A request to create a `Booking` therefore must carry `expected_sailing_version`, the `version` of the target `Sailing` that the client last observed. If `expected_sailing_version` does not equal the sailing's current `version` at the moment of creation, the request is rejected with `ERR_STALE_SAILING_VERSION` and HTTP status 412. Because opening, closing, re-opening, departing, or cancelling a sailing each increments `Sailing.version`, a non-matching value means another writer has changed the sailing's lifecycle epoch since the client read it and the client's assumptions about available inventory can no longer be trusted. These five lifecycle transitions are the only operations that advance `Sailing.version`; adding a cabin or holding a deposit adjusts the sailing's derived cabin totals and refreshes its `updated_at` without bumping `version`, so a sailing read after such an inventory change still presents the same `version` the client supplies on booking creation. The `expected_sailing_version` field is mandatory on booking creation; this is the only endpoint that carries a version field, and no other write endpoint takes one. The value supplied at creation is retained on the `Booking` as an `expected_sailing_version` field and echoed back in the booking's representation.

### 2.8. Monetary Values, Tiers, and Rounding

All monetary amounts in this system are integer counts of cents — fares, taxes, port fees, deposits, refunds, credits, charges, and gratuities alike. There are no fractional-cent values stored or returned. Wherever a percentage or fractional factor is applied, the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly at the half rounds up). Rounding is applied at each per-guest step rather than once at the end: per-guest fares and per-guest taxes are each rounded as they are computed, and the booking totals are formed by summing the already-rounded per-guest amounts without any further rounding. The order is contractual — taxes are rounded per guest and then summed; summing first and rounding once is not permitted. Several thresholds in this domain are keyed on whole days or on counts; these are introduced in the workflow narratives of Section 3 where they apply.

### 2.9. Group Discount and Add-On Bounds

A group block carries a `group_discount_pct` expressed as a fraction between 0 and 0.5 inclusive, defaulting to 0.15 when omitted at creation; renegotiation must keep it within the same bounds. The discount only materializes onto guest fares under the conditions described in Section 3.4. An excursion add-on price (`price_cents`) must be zero or greater, and a payment amount (`amount_cents`) and folio-charge amount (`amount_cents`) must each be strictly greater than zero. These input-shape rules, when violated, surface as `ERR_INVALID_REQUEST`; the occupancy and uniqueness rules that are domain constraints rather than shape errors carry their own codes as described in Section 3.

## 3. Business Logic & Workflows

### 3.1. Sailings and the Inventory Foundation

A voyage begins with a `Sailing`, created by a `RevenueManager` in `DRAFT` status. Creation captures the `ship_name`, an `itinerary_code` such as a route designator, the `embark_date` and `disembark_date` (both ISO 8601 UTC), and the number of `nights`. The `disembark_date` must be strictly after the `embark_date`, and `nights` must be at least 1; `nights` is taken as supplied and is not independently cross-checked against the span between the embark and disembark dates. A `disembark_date` not strictly after `embark_date`, or a `nights` below 1, is rejected with `ERR_INVALID_REQUEST`. A fresh sailing reports `total_cabins` and `available_cabins` of 0; both are roll-ups summed across the sailing's cabin categories and grow as inventory is added.

Within a sailing, a `RevenueManager` defines one or more cabin categories. A `CabinCategory` is created against its `sailing_id` and carries a `code` drawn from `INTERIOR`, `OCEANVIEW`, `BALCONY`, or `SUITE`; the code must be unique among the categories of that sailing, and a repeat is rejected with `ERR_DUPLICATE_CATEGORY_CODE`. A category spans a contiguous band of decks bounded by `deck_low` and `deck_high`, where `deck_high` must be at least `deck_low`. It records a `base_fare_per_guest_cents` — the full per-guest fare for the first and second occupants of a cabin, which must be greater than zero — and a `max_occupancy` capping guests per cabin in that category, which must be between 1 and 4 inclusive (in practice 2, 3, or 4). A new category reports `total_cabins`, `available_cabins`, `held_cabins`, `assigned_cabins`, and `blocked_cabins` all at 0; these are counts of the category's cabins partitioned by cabin `status`.

Individual cabins are then added by a `RevenueManager`. A `Cabin` is created under its `cabin_category_id` with a `cabin_number` and a `deck`. The `cabin_number` must be unique across the whole sailing — a collision yields `ERR_DUPLICATE_CABIN_NUMBER` — and the `deck` must fall within the owning category's `deck_low`-to-`deck_high` band inclusive, with an out-of-band value rejected as `ERR_DECK_OUT_OF_RANGE`. On creation the cabin enters `AVAILABLE` status, its `sailing_id` is denormalized from the parent category for filtering, and its `group_block_id` and `booking_id` both start null. Adding a cabin increments the owning category's `total_cabins` and `available_cabins` and the sailing's `total_cabins` and `available_cabins`.

A sailing advances through `DRAFT`, `OPEN`, `CLOSED`, `SAILED`, and `CANCELLED`, where `SAILED` and `CANCELLED` are terminal. Opening a sailing — transitioning it `DRAFT → OPEN` — is performed by a `RevenueManager` and requires that the sailing already hold at least one cabin category that itself holds at least one cabin; opening an empty sailing is rejected with `ERR_NO_INVENTORY`. A `RevenueManager` may later close a sailing (`OPEN → CLOSED`), which stops new bookings from reaching `DEPOSIT_HELD` while letting bookings already in flight continue, and may re-open a closed sailing (`CLOSED → OPEN`) as many times as needed — this re-open loop is a deliberate cycle in the sailing lifecycle. Each of opening, closing, and re-opening increments the sailing's `version` by 1.

A `PortAgent` departs the sailing once the voyage day arrives. Departing is permitted from either `OPEN` or `CLOSED` and moves the sailing to `SAILED`, but only when the current clock time has reached or passed the `embark_date`; an early attempt is rejected with `ERR_SAILING_NOT_DEPARTABLE`. Departure cascades: every `CONFIRMED` booking on the sailing transitions to `EMBARKED`, which opens that booking's folio in provisional gratuity mode as described in Section 3.7. Departure increments `Sailing.version` by 1.

A `RevenueManager` may cancel a sailing. From `DRAFT`, cancellation simply moves the sailing to `CANCELLED` and increments its `version`. From `OPEN` or `CLOSED`, cancellation is a goodwill cascade: every non-terminal booking on the sailing — every booking whose status is not already `CANCELLED`, `EXPIRED`, or `COMPLETED` — is moved to `CANCELLED` with its `cancellation_mode` recorded as `FCC` and a full-value future cruise credit minted, with no penalty applied because the line, not the guest, cancelled. That booking-level cancellation in turn releases the booking's held or assigned cabin and voids the booking's folio, a two-level cascade beneath the sailing cancellation. This cancellation also increments `Sailing.version` by 1.

### 3.2. Group Blocks: Reserving and Materializing Inventory

A `GroupBlock` lets a `RevenueManager` reserve a slice of a category's cabins for a named group ahead of individual sales. A block is created in `NEGOTIATING` status against its `sailing_id`, a `group_name`, the `cabin_category_id` it draws from, a `block_size` (the number of cabins requested, which must be greater than zero), and a `release_cutoff_date` after which still-unsold blocked cabins auto-release. The optional `group_discount_pct` defaults to 0.15 as described in Section 2.9. A fresh block reports `blocked_count` and `materialized_count` of 0; the lifecycle moves through `NEGOTIATING`, `HELD`, `PARTIALLY_MATERIALIZED`, and the terminal `RELEASED`.

While still negotiating, a `RevenueManager` may renegotiate the block in place — a `NEGOTIATING → NEGOTIATING` self-loop — adjusting `block_size`, `group_discount_pct`, or `release_cutoff_date`. The renegotiated values must stay within their bounds, and an out-of-bounds change is rejected with `ERR_INVALID_REQUEST`; a renegotiation increments the block's `version` by 1. Renegotiation is only valid while the block is `NEGOTIATING`, and an attempt to renegotiate a block in any other status is rejected with `ERR_INVALID_STATE`.

Holding a block (`NEGOTIATING → HELD`) reserves the physical cabins. It is permitted while the parent sailing is still being assembled or live — that is, while the sailing is `DRAFT`, `OPEN`, or `CLOSED` — and is rejected with `ERR_SAILING_NOT_BOOKABLE` only when the sailing has reached a terminal status (`SAILED` or `CANCELLED`); it further requires the category's `available_cabins` to be at least `block_size` (otherwise `ERR_INSUFFICIENT_INVENTORY`). On a successful hold, the system selects exactly `block_size` of the category's `AVAILABLE` cabins in `created_at` ascending order and sets each to `BLOCKED` with its `group_block_id` pointing at this block. The category's `available_cabins` decreases by `block_size` while its `blocked_cabins` increases by `block_size`, and the block's `blocked_count` is set to `block_size`.

Two reverse edges return blocked inventory. A `RevenueManager` may recall a block to `NEGOTIATING`; this edge is defined `HELD → NEGOTIATING` only, so the recall is legal solely while the block is still `HELD`, and an attempt to recall a block in any other status — including a `PARTIALLY_MATERIALIZED` block — is rejected at the state-transition-legality stage with `ERR_INVALID_STATE` per the ordering of Section 2.5, before the `materialized_count` business check is reached. After the state check, recall additionally guards on `materialized_count` being 0, rejecting a still-held block that nonetheless carries materialized bookings with `ERR_BLOCK_HAS_BOOKINGS`; because materialization moves a block off `HELD` into `PARTIALLY_MATERIALIZED` (see the materialization paragraph below), in practice a recall that reaches a materialized block surfaces `ERR_INVALID_STATE` rather than `ERR_BLOCK_HAS_BOOKINGS`. On a successful recall every `BLOCKED` cabin bearing this `group_block_id` returns to `AVAILABLE` with its `group_block_id` cleared, the category's `blocked_cabins` falls and `available_cabins` rises by the freed count, and the block's `blocked_count` returns to 0. A `RevenueManager` may instead permanently release a block (`HELD → RELEASED` or `PARTIALLY_MATERIALIZED → RELEASED`); release admits a block that is `HELD` or `PARTIALLY_MATERIALIZED` (any other status is rejected with `ERR_INVALID_STATE`) and then requires `materialized_count` to be 0, rejecting a block that still carries materialized bookings with `ERR_BLOCK_HAS_BOOKINGS`. A successful release frees every still-`BLOCKED` cabin of the block back to `AVAILABLE` and restores the category counts.

A block materializes as guests book against it. When a booking that draws from a block reaches `DEPOSIT_HELD`, the system automatically transitions the block `HELD → PARTIALLY_MATERIALIZED` and increments its `materialized_count` by 1; `materialized_count` is the count of bookings drawn from this block whose status is not `CANCELLED` or `EXPIRED`. While the block is `PARTIALLY_MATERIALIZED`, each further booking from it that reaches `DEPOSIT_HELD` increments `materialized_count` by 1, and each materialized booking that later cancels decrements it by 1, all as `PARTIALLY_MATERIALIZED → PARTIALLY_MATERIALIZED` self-loops driven by the system.

The `release_cutoff_date` provides an automatic terminal release. When the simulated clock advances past a block's `release_cutoff_date`, a block that is `HELD` or `PARTIALLY_MATERIALIZED` transitions to `RELEASED`: every still-`BLOCKED` (unmaterialized) cabin of the block returns to `AVAILABLE` and the category counts are restored, while any cabins already materialized into bookings keep their assignments. Unlike the manual release edge, this automatic cutoff release does not require `materialized_count` to be 0 — it frees only the still-blocked cabins and leaves materialized bookings untouched.

### 3.3. Opening a Booking and Building the Guest Roster

A `Booking` is the guest's contract with a sailing, created in `QUOTE` status by either a `GuestUser` or a `ReservationsAgent`. Creation supplies the `sailing_id`, the requested `cabin_category_id`, the `owner_user_id` identifying the owning guest, and the `expected_sailing_version` that guards the cabin pool per Section 2.7; it may optionally supply a `group_block_id` to draw from a group block. A `GuestUser` may only create a booking whose `owner_user_id` equals their own `X-User-ID`; a mismatch is rejected with `ERR_NOT_BOOKING_OWNER` (checked after resource existence), whereas a `ReservationsAgent` may name any `owner_user_id`. When a `group_block_id` is supplied, the referenced block must be in `HELD` or `PARTIALLY_MATERIALIZED` status, or the creation is rejected with `ERR_GROUP_BLOCK_NOT_HELD`. A new booking starts with `cabin_id` null, with `guest_count` and every monetary total at 0, and with `cancellation_mode` null. The booking's lifecycle runs through `QUOTE`, `DEPOSIT_HELD`, `CONFIRMED`, `EMBARKED`, and `COMPLETED`, with `COMPLETED`, `CANCELLED`, and `EXPIRED` terminal.

Guests are added to a booking only while it is in `QUOTE`; an attempt to add a guest to a booking in any other status is rejected with `ERR_INVALID_STATE`. A `Guest` is created against its `booking_id` with a `full_name` and an `age` in whole years at embarkation, which must be 0 or greater. Each new guest also drives the rejection of an over-large party: adding a guest whose inclusion would push the booking's `guest_count` above the category's `max_occupancy` is rejected with `ERR_OCCUPANCY_EXCEEDED`. As guests are added or removed, each guest is assigned an `occupancy_index` — a 1-based position within the cabin assigned in `created_at` ascending order, so the earliest-added guest is position 1. Removing a guest (permitted only while the booking is `QUOTE`, else `ERR_INVALID_STATE`) re-indexes the remaining guests to keep the positions contiguous. Every guest add or delete recomputes the per-guest fares, the booking totals, and the deposit schedule described in Section 3.4. The booking's `guest_count` is the number of guests currently attached.

### 3.4. Fares, Taxes, Deposits, and Booking Totals

Pricing is per guest and tiered by occupancy position. The category's `base_fare_per_guest_cents` is the full fare. A guest at `occupancy_index` 1 or 2 has a `base_fare_cents` equal to the full base fare; a guest at position 3 or 4 has a `base_fare_cents` equal to the full base fare multiplied by the third-and-fourth-occupant rate of 0.55, rounded half-up to whole cents. Occupancy positions are assigned in `created_at` ascending order, so the third and fourth guests added pay the reduced rate.

Each guest also carries a `final_fare_cents`, which is the fare after any group discount, and a `tax_port_cents`. Whether the group discount applies depends on the booking's stage — this is the provisional-versus-final distinction. While a booking is in `QUOTE` or `DEPOSIT_HELD`, `final_fare_cents` equals `base_fare_cents`; the rack fare stands with no group discount yet applied, even if the booking draws from a block. Once a booking is `CONFIRMED` and carries a `group_block_id`, `final_fare_cents` is recomputed as `base_fare_cents` multiplied by one minus the block's `group_discount_pct`, rounded half-up to whole cents; for the same guest roster this final figure diverges from the provisional one. A confirmed booking with no group block keeps `final_fare_cents` equal to `base_fare_cents`. The per-guest `tax_port_cents` is the port-fee percentage of 0.115 applied to that guest's `final_fare_cents`, rounded half-up to whole cents, plus a flat per-guest port charge of 8900 cents.

The booking's roll-ups follow directly. The `fare_total_cents` is the sum over all guests of their `final_fare_cents`. The `tax_port_total_cents` is the sum over all guests of their already-rounded `tax_port_cents` — rounded per guest first, then summed, never the reverse. The `booking_total_cents` is `fare_total_cents` plus `tax_port_total_cents`. All guests count toward these totals; guests are not independently cancellable, so there is no status filter on the roster.

The deposit schedule is derived from the booking total. The percentage component is `booking_total_cents` multiplied by the deposit rate of 0.20, rounded half-up to whole cents. The floor component is a per-guest deposit minimum of 25000 cents multiplied by `guest_count`. The `deposit_due_cents` is the larger of those two components, so a small booking is protected by the per-guest floor. The `final_due_cents` is `booking_total_cents` minus `deposit_due_cents`, representing the balance owed before confirmation. The booking also tracks an `amount_paid_cents`, which is the sum of `amount_cents` over the booking's `CAPTURED` deposit and final payments, less any `REFUNDED` refunds. The two cancellation-outcome fields, `fcc_credit_cents` and `cancel_refund_cents`, both start at 0 and are populated only at cancellation as described in Section 3.8.

### 3.5. Payments and the Deposit-and-Confirm Sequence

Money is recorded through `Payment` resources. A `Payment` is created in `PENDING` status against its `booking_id` with a `kind` of `DEPOSIT`, `FINAL`, or `REFUND` and an `amount_cents` greater than zero. A payment cannot be created against a booking that is already `CANCELLED` or `EXPIRED`; such an attempt is rejected with `ERR_BOOKING_INACTIVE`. A payment moves through `PENDING`, `CAPTURED`, `FAILED`, and `REFUNDED`. Capturing a pending payment (`PENDING → CAPTURED`), performed by a `ReservationsAgent` or the owning `GuestUser`, is forbidden while the booking is `CANCELLED` or `EXPIRED` (`ERR_BOOKING_INACTIVE`) and, on success, increases the booking's `amount_paid_cents` by the payment's `amount_cents`. A `ReservationsAgent` may instead mark a pending payment failed (`PENDING → FAILED`). Refunding a captured payment (`CAPTURED → REFUNDED`) is restricted to a `ReservationsAgent` and is permitted only when the payment's `kind` is `DEPOSIT` or `FINAL`; refunding anything else is rejected with `ERR_INVALID_STATE`. A refund decreases the booking's `amount_paid_cents` by the refunded `amount_cents`. Captured-payment refunds also occur automatically when a cancellation settles in cash, as described in Section 3.8.

Moving a booking from `QUOTE` to `DEPOSIT_HELD` is the inventory-committing step, performed by a `GuestUser` or `ReservationsAgent`. It is gated by a sequence of preconditions. The parent sailing must be `OPEN` (otherwise `ERR_SAILING_NOT_BOOKABLE`). The booking must have at least one guest (otherwise `ERR_NO_GUESTS`). The current `guest_count` must not exceed the category's `max_occupancy` (otherwise `ERR_OCCUPANCY_EXCEEDED`). Inventory must be available: either the category's `available_cabins` is at least 1, or the booking draws from a `group_block_id` whose status is `HELD` or `PARTIALLY_MATERIALIZED` and which still holds a `BLOCKED` cabin; if neither holds, the request is rejected with `ERR_INSUFFICIENT_INVENTORY`. Finally there must exist a `CAPTURED` `DEPOSIT` payment whose `amount_cents` is at least the minimum acceptable commitment, computed as the lesser of the current `deposit_due_cents` and the per-guest deposit floor (25000 cents multiplied by the current `guest_count`); a single captured deposit at or above that threshold satisfies the gate. Absent such a payment, the request is rejected with `ERR_DEPOSIT_NOT_SATISFIED`.

On a successful deposit hold, the system holds exactly one cabin. For a group-drawing booking it takes a `BLOCKED` cabin of the block in `created_at` ascending order; for an individual booking it takes an `AVAILABLE` cabin of the category in `created_at` ascending order. The chosen cabin moves to `HELD`, its `booking_id` is set to this booking, and the booking's `cabin_id` is set to that cabin. For an individual draw the category's `available_cabins` decreases by 1; for a group draw the category's `blocked_cabins` decreases by 1; in both cases `held_cabins` increases by 1. If the booking draws from a block, the block's `materialized_count` increases by 1 and the block auto-transitions `HELD → PARTIALLY_MATERIALIZED`. The booking moves to `DEPOSIT_HELD`.

A guest who needs to edit the roster after holding a deposit revises the booking (`DEPOSIT_HELD → QUOTE`), performed by a `GuestUser` or `ReservationsAgent` and permitted only while the parent sailing is `OPEN` (otherwise `ERR_SAILING_NOT_BOOKABLE`). Revising releases the held cabin back to its prior pool — to `AVAILABLE` for an individual draw or back to `BLOCKED` for a group draw — clears the cabin's `booking_id` and the booking's `cabin_id`, and, for a group draw, decrements the block's `materialized_count` by 1. The fares, totals, and deposit schedule are recomputed against the new roster, and the booking returns to `QUOTE`. This re-quote loop is the deliberate cycle that lets a guest add or remove guests after a deposit was already held.

Confirming a booking (`DEPOSIT_HELD → CONFIRMED`), performed by a `GuestUser` or `ReservationsAgent`, requires the parent sailing to be `OPEN` or `CLOSED` (otherwise `ERR_SAILING_NOT_BOOKABLE`) and requires the booking's `amount_paid_cents` to be at least the booking total computed under the final-fare variant — that is, the post-confirmation total that already reflects the group discount when the booking carries a `group_block_id` — rather than the provisional `booking_total_cents` still stored on the booking at this point (otherwise `ERR_BALANCE_OUTSTANDING`). For a booking with no group block the two figures coincide. On confirmation, the held cabin moves `HELD → ASSIGNED` with the category's `held_cabins` decreasing and `assigned_cabins` increasing, each guest's `final_fare_cents` is recomputed with the group discount when the booking carries a `group_block_id`, the booking's `fare_total_cents`, `tax_port_total_cents`, and `booking_total_cents` are refreshed under the final-fare variant, and the booking moves to `CONFIRMED`.

### 3.6. Add-Ons and Dining Reservations

A booking may carry ancillary purchases. An `AddOn` is attached to a booking via its `booking_id` with a `kind` of `DINING` or `EXCURSION`, a `title`, and a `price_cents` of 0 or more, and starts in `RESERVED` status. An `EXCURSION` is assigned to a specific guest and scheduled: it requires a `guest_id`, a `window_start`, and a `window_end` (the latter strictly after the former). A `DINING` add-on takes none of those three — supplying a `guest_id`, `window_start`, or `window_end` on a `DINING` add-on, or omitting any of them on an `EXCURSION`, is a shape violation rejected with `ERR_INVALID_REQUEST`. Two excursions assigned to the same guest may not overlap in time: overlap is judged on half-open intervals running from `window_start` up to but not including `window_end`, so an excursion that ends exactly when another begins does not conflict, while any true overlap with another `RESERVED` excursion on that guest is rejected with `ERR_TIME_WINDOW_CONFLICT`. An add-on may later be cancelled (`RESERVED → CANCELLED`); cancelling one that is already `CANCELLED` is rejected with `ERR_INVALID_STATE`.

A `DiningReservation` reserves a seating for the booking via its `booking_id`, a `venue_code` of `MAIN`, `SPECIALTY_A`, or `SPECIALTY_B`, a `seating_start`, and a `party_size`. It starts `BOOKED` and may later be cancelled (`BOOKED → CANCELLED`, with a repeat cancellation rejected as `ERR_INVALID_STATE`). The `party_size` must be at least 1 and must not exceed the booking's `guest_count`; a party larger than the roster is rejected with `ERR_OCCUPANCY_EXCEEDED`. Dining seatings on the same booking may not crowd one another: a new seating that collides with another `BOOKED` seating on the same booking within the dining turnover buffer is rejected with `ERR_TIME_WINDOW_CONFLICT`. Unlike the excursion rule, the dining buffer uses a closed interval expanded by the turnover window, so two seatings that fall within the buffer of one another — even touching at the buffer edge — do conflict. The turnover buffer is a fixed forty-five-minute spacing applied symmetrically around each existing seating.

### 3.7. Departure, Embarkation, the Folio, and Settlement

Once a sailing has departed and reached `SAILED`, its confirmed bookings come aboard. A booking transitions `CONFIRMED → EMBARKED` either automatically as part of the departure cascade or by an explicit action a `PortAgent` performs; in either case the booking's parent sailing must already be `SAILED`, and an embark attempt against a sailing that has not departed is rejected with `ERR_SAILING_NOT_DEPARTED`. Embarkation creates the booking's `Folio` in `OPEN` status with `gratuity_mode` of `PROVISIONAL`, and posts the provisional auto-gratuity onto it. The folio is one-to-one with its booking via `booking_id`, begins with `charges_total_cents`, `gratuity_total_cents`, and `balance_due_cents` at 0 before the gratuity is posted, and moves through `OPEN`, `SETTLED`, and `VOID`.

The auto-gratuity is a per-guest-per-night charge: `gratuity_total_cents` is the gratuity rate of 1800 cents multiplied by the booking's `guest_count` and by the sailing's `nights`. The folio's `charges_total_cents` is the sum of `amount_cents` over the folio's `POSTED` folio charges, and its `balance_due_cents` is `charges_total_cents` plus `gratuity_total_cents` minus the folio payments already applied — and because this domain exposes no folio-payment surface, that applied-payments term is always 0, so `balance_due_cents` equals `charges_total_cents` plus `gratuity_total_cents`. The provisional gratuity is computed at embark from the guest count then; the final gratuity is recomputed at settlement against the final guest count and nights using the same formula.

Onboard charges are posted by a `PortAgent`. A `FolioCharge` is created against its `folio_id` with a `description` and an `amount_cents` greater than zero, and may name the `guest_id` who incurred it (or leave it null for a booking-level charge); it starts `POSTED`. A charge may be posted only while the folio is `OPEN` (otherwise `ERR_INVALID_STATE`) and only while the owning booking is `EMBARKED` (otherwise `ERR_SAILING_NOT_BOOKABLE`). Posting a charge refreshes the folio's `charges_total_cents` and `balance_due_cents`. A `PortAgent` may reverse a posted charge (`POSTED → REVERSED`, with a repeat reversal rejected as `ERR_INVALID_STATE`), which recomputes the folio totals.

Settling the folio completes the booking (`EMBARKED → COMPLETED`), performed by a `PortAgent`. It requires the folio's `balance_due_cents` to be exactly 0; a non-zero balance is rejected with `ERR_FOLIO_OUTSTANDING`. On settlement the folio's `gratuity_mode` moves to `FINAL` with the gratuity recomputed at disembark, the folio moves `OPEN → SETTLED`, the booking's assigned cabin moves `ASSIGNED → AVAILABLE` with the category's `assigned_cabins` decreasing and `available_cabins` increasing, and the booking moves to `COMPLETED`. Separately, the folio is voided (`OPEN → VOID`) as a cascade whenever the owning booking or its sailing is cancelled: all `POSTED` folio charges are set to `REVERSED`, `charges_total_cents` falls to 0, and the folio moves to `VOID`.

### 3.8. Cancellation, Penalty Tiers, and the Cash-versus-FCC Split

A booking can be cancelled by a `GuestUser` or `ReservationsAgent`, and the cancel request carries a `cancellation_mode` of `CASH` or `FCC` that selects which settlement applies. Cancelling from `QUOTE` is penalty-free: no cabin was ever held so there is nothing to release, the chosen `cancellation_mode` is recorded, and any captured deposit payment is either fully refunded in cash or converted to credit per the requested mode. Cancelling a still-`QUOTE` booking simply moves it to `CANCELLED`. A `QUOTE` booking also expires on its own: when the simulated clock advances past the sailing's `embark_date` while the booking is still `QUOTE`, the system moves it `QUOTE → EXPIRED`; because no cabin was held, nothing is released.

Cancelling from `DEPOSIT_HELD` or `CONFIRMED` runs the penalty calculation and the cabin-release cascade. The penalty tier is keyed on the whole number of days between the sailing's `embark_date` and the current clock, truncated toward zero (the fractional remainder of the final day is dropped). When that day count is 90 or more, the penalty fraction is 0.00; when it is at least 60 but fewer than 90, the fraction is 0.25; when it is at least 30 but fewer than 60, the fraction is 0.50; when it is at least 15 but fewer than 30, the fraction is 0.75; and when it is fewer than 15, the fraction is 1.00. The base penalty amount is `booking_total_cents` multiplied by that fraction, rounded half-up to whole cents.

The two settlement variants then diverge for identical inputs. Under the `CASH` variant, an administrative fee of 5000 cents applies only when the penalty fraction is exactly 0.00 (the no-penalty tier) and is otherwise zero; the `cancel_refund_cents` is the booking's `amount_paid_cents` minus the base penalty minus that admin fee, floored at 0, and `fcc_credit_cents` stays 0. A cash settlement mints a `REFUND` payment for the refunded amount. Under the `FCC` variant, no admin fee ever applies; the FCC penalty is the base penalty multiplied by the FCC penalty factor of 0.50, rounded half-up to whole cents — that is, only half the cash-tier penalty is charged — and `fcc_credit_cents` is `amount_paid_cents` minus that halved penalty, floored at 0, while `cancel_refund_cents` stays 0. The booking records whichever of `cancel_refund_cents` or `fcc_credit_cents` applies, records the `cancellation_mode`, and moves to `CANCELLED`.

The cabin-release cascade has three levels. The booking's held or assigned cabin is released — a `HELD` or `ASSIGNED` cabin returns to `AVAILABLE` for an individual draw or to `BLOCKED` for a group draw — which in turn restores the category's `available_cabins` or `blocked_cabins` (and decrements `held_cabins` or `assigned_cabins` accordingly), which in turn, for a group draw, decrements the owning block's `materialized_count`, relaxing a `PARTIALLY_MATERIALIZED` block back toward held semantics. If the booking already had a folio, that folio is voided as part of the same cancellation. A cash settlement's `REFUND` payment is minted as a captured-equivalent record so the booking's `amount_paid_cents` reflects the returned money.

### 3.9. The Simulated Clock

Because expiry and auto-release are time-driven, a `RevenueManager` can advance a simulated current-UTC clock to a supplied `to_iso8601` instant; this capability is the system's only time control and is reserved to the `RevenueManager`. Until the clock has been set at least once, any time-gated comparison (departability, expiry, cutoff release, and cancellation penalty tiering) reads the server's real wall-clock UTC. A non-ISO-8601 `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. Advancing the clock fires two families of time-gated transitions in the same request. Every still-`QUOTE` booking whose sailing's `embark_date` is at or before the new clock value moves to `EXPIRED`. Every `HELD` or `PARTIALLY_MATERIALIZED` group block whose `release_cutoff_date` is now earlier than the clock moves to `RELEASED`, freeing its still-`BLOCKED` cabins as described in Section 3.2. These automatic transitions are attributed to the `system` actor.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read a resource or list, or that drive a state transition or otherwise modify an existing resource, return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in Section 2.1, and the request body and response body for each operation must be reconstructed from the workflow narratives in Section 3 — the table below lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the simulated current UTC clock; fires time-gated expiry and block release | RevenueManager |
| POST | `/sailings` | Create a sailing in DRAFT | RevenueManager |
| GET | `/sailings/{id}` | Get a sailing | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/sailings` | List sailings | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/sailings/{id}/open` | Open or re-open a sailing for booking | RevenueManager |
| POST | `/sailings/{id}/close` | Close a sailing to new deposit holds | RevenueManager |
| POST | `/sailings/{id}/depart` | Depart the sailing and embark confirmed bookings | PortAgent |
| POST | `/sailings/{id}/cancel` | Cancel the sailing | RevenueManager |
| POST | `/cabin-categories` | Create a cabin category on a sailing | RevenueManager |
| GET | `/cabin-categories/{id}` | Get a cabin category | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/cabin-categories` | List cabin categories | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/cabins` | Create a cabin in a category | RevenueManager |
| GET | `/cabins/{id}` | Get a cabin | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/cabins` | List cabins | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/group-blocks` | Create a group block in NEGOTIATING | RevenueManager |
| GET | `/group-blocks/{id}` | Get a group block | RevenueManager, ReservationsAgent, GuestUser |
| GET | `/group-blocks` | List group blocks | RevenueManager, ReservationsAgent, GuestUser |
| PATCH | `/group-blocks/{id}` | Renegotiate a group block while NEGOTIATING | RevenueManager |
| POST | `/group-blocks/{id}/hold` | Hold cabins for the block | RevenueManager |
| POST | `/group-blocks/{id}/recall` | Recall a held block back to NEGOTIATING | RevenueManager |
| POST | `/group-blocks/{id}/release` | Permanently release the block | RevenueManager |
| POST | `/bookings` | Create a booking in QUOTE (OCC-guarded) | GuestUser, ReservationsAgent |
| GET | `/bookings/{id}` | Get a booking | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/bookings` | List bookings | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/bookings/{id}/hold-deposit` | Move QUOTE to DEPOSIT_HELD, holding a cabin | GuestUser, ReservationsAgent |
| POST | `/bookings/{id}/revise` | Drop DEPOSIT_HELD to QUOTE to edit the roster | GuestUser, ReservationsAgent |
| POST | `/bookings/{id}/confirm` | Move DEPOSIT_HELD to CONFIRMED | GuestUser, ReservationsAgent |
| POST | `/bookings/{id}/embark` | Move CONFIRMED to EMBARKED | PortAgent |
| POST | `/bookings/{id}/settle-folio` | Move EMBARKED to COMPLETED, settling the folio | PortAgent |
| POST | `/bookings/{id}/cancel` | Cancel a booking with CASH or FCC settlement | GuestUser, ReservationsAgent |
| POST | `/guests` | Add a guest to a QUOTE booking | GuestUser, ReservationsAgent |
| DELETE | `/guests/{id}` | Remove a guest from a QUOTE booking | GuestUser, ReservationsAgent |
| GET | `/guests/{id}` | Get a guest | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/guests` | List guests | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/add-ons` | Attach a DINING or EXCURSION add-on | GuestUser, ReservationsAgent |
| GET | `/add-ons/{id}` | Get an add-on | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/add-ons` | List add-ons | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/add-ons/{id}/cancel` | Cancel an add-on | GuestUser, ReservationsAgent |
| POST | `/dining-reservations` | Book a dining seating | GuestUser, ReservationsAgent |
| GET | `/dining-reservations/{id}` | Get a dining reservation | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/dining-reservations` | List dining reservations | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/dining-reservations/{id}/cancel` | Cancel a dining seating | GuestUser, ReservationsAgent |
| POST | `/payments` | Create a DEPOSIT, FINAL, or REFUND payment in PENDING | GuestUser, ReservationsAgent |
| GET | `/payments/{id}` | Get a payment | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/payments` | List payments | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/payments/{id}/capture` | Capture a pending payment | GuestUser, ReservationsAgent |
| POST | `/payments/{id}/fail` | Mark a pending payment failed | ReservationsAgent |
| POST | `/payments/{id}/refund` | Refund a captured DEPOSIT or FINAL payment | ReservationsAgent |
| GET | `/folios/{id}` | Get a folio | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/folios` | List folios | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/folios/{id}/charges` | Post an onboard charge to a folio | PortAgent |
| GET | `/folio-charges/{id}` | Get a folio charge | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| GET | `/folio-charges` | List folio charges | RevenueManager, ReservationsAgent, PortAgent, GuestUser |
| POST | `/folio-charges/{id}/reverse` | Reverse a posted folio charge | PortAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_BOOKING_OWNER` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SAILING_NOT_BOOKABLE` | 409 Conflict |
| `ERR_SAILING_NOT_DEPARTABLE` | 409 Conflict |
| `ERR_SAILING_NOT_DEPARTED` | 409 Conflict |
| `ERR_NO_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_NO_GUESTS` | 409 Conflict |
| `ERR_OCCUPANCY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_NOT_SATISFIED` | 402 Payment Required |
| `ERR_BALANCE_OUTSTANDING` | 402 Payment Required |
| `ERR_BOOKING_INACTIVE` | 409 Conflict |
| `ERR_GROUP_BLOCK_NOT_HELD` | 409 Conflict |
| `ERR_BLOCK_HAS_BOOKINGS` | 409 Conflict |
| `ERR_TIME_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_FOLIO_OUTSTANDING` | 402 Payment Required |
| `ERR_DUPLICATE_CATEGORY_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CABIN_NUMBER` | 409 Conflict |
| `ERR_DECK_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_STALE_SAILING_VERSION` | 412 Precondition Failed |
