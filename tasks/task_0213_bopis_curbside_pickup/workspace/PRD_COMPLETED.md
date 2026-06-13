# Bopis Curbside Pickup API — Product Requirements Document

## 1. Introduction

Buy-Online-Pickup-In-Store (BOPIS) and curbside fulfillment let a shopper place an order online and collect the goods at a physical store, either by walking in or by pulling into a designated curbside space and having an associate load the vehicle. This API is the system of record behind that experience. It tracks per-store inventory availability, manages capacity-constrained pickup time slots, drives the warehouse-floor pick/stage/ready workflow, verifies the customer's identity at hand-over, coordinates curbside arrival check-ins, and reconciles money as units are actually handed over rather than merely ordered.

The domain is unusually rich because several concerns overlap on the same order at once. An order advances along a fulfillment lifecycle (it is drafted, submitted, picked, staged, made ready, and finally collected or expired) while a second, independent payment lifecycle evolves on the very same record (authorization at submission, capture or partial refund at collection, full refund on cancellation or expiry). Inventory is soft-committed when an order is submitted and only physically removed when a picker pulls it from the shelf, so the bookable quantity a shopper sees is a derived figure rather than the raw shelf count. Staged orders are held for a limited window; when that window lapses unclaimed, the goods are restocked, the customer is refunded, and the customer accrues a no-show strike that can eventually block them from booking. Short-picks open a substitution negotiation, and partial pickups split an order's money into a captured portion and a refunded remainder.

This document specifies the complete contract: the global response envelope and pagination rules, the role-based access model, the cross-cutting principles that govern inventory, slot capacity, holds, concurrency, and money precision, and the detailed business workflows for every entity. Engineers implementing the service should treat Section 2 as the precise structural contract and Section 3 as the authoritative narrative for business behavior; Sections 4 and 5 summarize the endpoint surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than customer self-registration and the test-driving clock operations must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present but the supplied role is not permitted to invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Customer self-registration and the clock endpoints are exempt from the authentication requirement.

There are six roles, spelled exactly as follows: `Anonymous`, `Customer`, `StorePicker`, `StoreAssociate`, `StoreManager`, and `PlatformAdmin`.

`Anonymous` represents an unauthenticated caller. Its `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The only thing an anonymous caller may do is register a new customer.

`Customer` is entity-backed: when `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks compare a resource's owning foreign key to `X-User-ID`. Concretely, when a customer acts on an order or on a substitution, the order's `customer_id` (for a substitution, the `customer_id` of the order that owns the substituted line) must equal `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Customers may also read their own resources.

`StorePicker`, `StoreAssociate`, `StoreManager`, and `PlatformAdmin` are all opaque roles: when `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`, and these roles are not subject to per-resource ownership checks. `StorePicker` runs the picking, staging, readying, and substitution-proposal workflow. `StoreAssociate` verifies orders, hands over units, and runs curbside loading. `StoreManager` administers inventory and slots, performs manager-only cancellation and expiry, and may also verify and close orders. `PlatformAdmin` seeds the catalog (stores, products, pickup slots, inventory), drives the logical clock, and may expire holds.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may be at most 100. The `offset` parameter defaults to 0 and has a minimum of 0. List results are always returned in ascending order of `created_at` (oldest first). The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records before pagination and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Most resources also carry three common system fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by one on every mutation of that resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every mutation alongside the version bump. These metadata timestamps (`created_at`, `updated_at`, and the ledger rows' `created_at`) are stamped from the real server wall clock in UTC, not from the test-driving logical clock; the logical clock governs only domain instants such as a hold's `staged_at` and `expires_at` and the slot cutoff and hold-expiry comparisons.

Two entities are deliberately lightweight ledgers and carry only `id` and `created_at`: a `PickupEvent` (the record of one line handed over in one pickup) and an `InventoryMovement` (an append-only inventory ledger entry). Neither of these carries `updated_at` or `version`, because both are immutable once written — they are never updated after creation.

### 2.5. Nested Resource Retrieval and Reference Integrity

Several endpoints address a resource through a path that names a parent and then a child or a sub-collection. Path parameters are validated left to right: each path-referenced resource must exist before the next segment is considered, and the first missing resource yields `ERR_NOT_FOUND` (HTTP 404). Separately, when a request body carries a foreign key — for example the `store_id` and `product_id` on an inventory row, or the `slot_id` on a submission — each referenced resource must exist, and a dangling reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Request bodies are also checked for the presence and type of required fields, valid enum values, and positive quantities where required; a malformed body is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Inventory Availability and the Reservation Model

Store inventory for a given store-and-product pair is the heart of the quota model. Each `StoreInventory` row tracks `on_hand`, the physical units sitting on the shelf or in the backroom; `reserved`, the units soft-committed to non-terminal order lines; and `available`, the derived bookable figure. Availability is recomputed on every reservation, release, pick, or restock that affects the row, and it equals `on_hand` minus `reserved`, floored so it never drops below zero — in other words, the larger of zero and the difference between on-hand and reserved units. The figure is always whole units; there is no rounding.

A crucial distinction governs which figure each step reads. The reserve-blocking check that runs when an order is submitted (and again when a substitute is accepted) reads `available`, not `on_hand`: a line ordering some quantity is reservable only when `available` is at least that requested quantity. Reserving increments `reserved` and recomputes `available`, but it leaves `on_hand` untouched — the physical units are not removed from the shelf until a picker actually pulls them. By contrast, the physical pick step reads `on_hand` directly: a pick of some quantity requires `on_hand` to be at least that picked quantity. Because the units being picked are already counted in `reserved`, the pick step does not re-check `available`.

Every inventory mutation is journaled. An `InventoryMovement` row records the affected `store_inventory_id`, a `movement_type` that is one of `RESTOCK`, `RESERVE`, `RELEASE`, or `PICK_REMOVE`, a signed `delta_on_hand` (positive for restocks, negative for physical pick removals, zero otherwise), a signed `delta_reserved` (positive when reserving, negative when releasing or removing reserved units on a pick, zero otherwise), and a `reason` string. The `reason` is a polymorphic origin reference: it reads `ORDER:<id>` when the movement originates from an order action, `HOLD:<id>` when it originates from a hold's expiry, or `MANUAL` for a manual restock. The ledger is append-only and ordered by `created_at`.

### 2.7. Slot Capacity and Fill Status

A `PickupSlot` belongs to one store and defines a pickup window with an inclusive `window_start` and an exclusive `window_end` (the end must be strictly after the start). It carries a `capacity` (the maximum number of orders that may book it, which must be greater than zero) and a `cutoff_offset_minutes` (the number of minutes before the window start after which booking is no longer allowed; this defaults to 30 and must be at least zero). The slot tracks `booked_count`, the number of orders currently holding the slot, which is recomputed whenever a booking is added or released and is never negative nor greater than capacity. The derived `fill_status` is `FULL` when `booked_count` is greater than or equal to `capacity`, and `OPEN` otherwise; it is recomputed whenever `booked_count` changes. Booking is permitted only while the slot is `OPEN` — that is, while `booked_count` is strictly less than `capacity`. When `booked_count` is one below capacity the slot is still `OPEN` (one space left); when `booked_count` equals capacity the slot is `FULL` and further booking is refused.

### 2.8. Holds, the Pickup Window, and the Logical Clock

The system runs on a logical clock that test-driving operators can set to an absolute UTC instant or advance to a later instant. The clock endpoints require no authentication headers; however, if an `X-User-Role` header is supplied it must be `PlatformAdmin`, otherwise the request is rejected with `ERR_UNAUTHORIZED`. When a staged order is made ready, a `Hold` is created to represent the staged goods awaiting collection. The hold records the `order_id` and `store_id`, a `staged_at` timestamp set to the clock value at the moment of readying, an `expires_at` deadline, and a `hold_status` that is one of `ACTIVE`, `RELEASED`, or `EXPIRED` (it begins `ACTIVE`). There is exactly one hold per order.

The expiry deadline is computed when the hold is created: `expires_at` is the `staged_at` instant plus the parent store's `hold_window_minutes`. A hold is eligible to expire only while the clock is at or after `expires_at` — the comparison is inclusive at the deadline. Precisely: at the instant the clock equals `expires_at`, the hold is expirable; one minute earlier, it is not.

### 2.9. No-Show Standing and the Risk Gate

Each customer carries a `no_show_strikes` counter and a derived `pickup_standing`. The strike counter starts at zero and is incremented by one each time one of that customer's orders expires unclaimed while awaiting pickup; it is never decremented. The standing is recomputed from the strike count using inclusive thresholds: when strikes are at least 4 the standing is `BLOCKED`; otherwise when strikes are at least 2 (but fewer than 4) the standing is `WATCH`; otherwise (fewer than 2 strikes) the standing is `GOOD`. The boundary cases are exact: at exactly 2 strikes the standing is `WATCH`, and at exactly 4 strikes the standing is `BLOCKED`. A `BLOCKED` customer cannot submit new orders; a `WATCH` customer is permitted to submit but is flagged with the distinct posture.

### 2.10. Money Precision

All monetary amounts are stored and computed in integer cents, and prices in the catalog (`unit_price_cents`) are always positive integer cents. Authorization and refund totals involve no rounding because their inputs are already whole cents. The capture calculation specifies a rounding step for the effective per-unit price using round-half-up; because the effective unit price is itself already an integer this rounding is a no-op, but the order of operations is pinned (round the per-unit price first, then multiply by the handed-over quantity, then sum across lines) so that implementations remain consistent with the authorization path. Wherever rounding is invoked it is round-half-up.

### 2.11. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent entity's `version`, so that a client cannot apply a change on top of a stale snapshot of capacity or stock.

Submitting an order books one unit of a pickup slot's capacity, and the submission must carry `expected_slot_version` matching the target slot's current `version`. If the slot's version has advanced since the client last observed it — because another submission has already booked a unit and consumed capacity — the submission is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412). This prevents a booking made against an outdated view of remaining capacity from superseding the change the client never saw.

Restocking an inventory row adjusts `on_hand` by a signed integer `delta_on_hand` against the prior availability snapshot (a `RESTOCK` movement carrying that `delta_on_hand` and reason `MANUAL` is appended); a `delta_on_hand` that would drive `on_hand` below zero is rejected with `ERR_INVALID_REQUEST`. The restock request must carry `expected_inventory_version` matching the target inventory row's current `version`. If the inventory version has advanced since the client read it — because a reservation, a pick, or a prior restock already moved `on_hand` or `reserved` — the restock is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412) rather than being applied on top of an outdated baseline. No other endpoint takes a version field.

### 2.12. Validation Precedence

When several checks apply to a single request, they are evaluated in a fixed precedence so that the earliest applicable failure is the one reported. Authentication is checked first (presence of both headers, `ERR_UNAUTHENTICATED`), then authorization by role (`ERR_UNAUTHORIZED`), then resource ownership for customer-owned order and substitution mutations (`ERR_NOT_RESOURCE_OWNER`). Existence checks follow: path-referenced resources are validated left to right (`ERR_NOT_FOUND`), then body foreign keys (`ERR_REFERENCE_NOT_FOUND`). Next comes request well-formedness (`ERR_INVALID_REQUEST`), then the inventory-uniqueness constraint on inventory creation (`ERR_DUPLICATE_INVENTORY`). After those come the state guard — that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`) — followed by the optimistic-concurrency version check (`ERR_STALE_SLOT_VERSION` for submission, `ERR_STALE_INVENTORY_VERSION` for restock). The remaining business rules then apply in this order: slot-store match (`ERR_SLOT_STORE_MISMATCH`), substitution-group match (`ERR_SUBSTITUTION_GROUP_MISMATCH`), the slot booking cutoff (`ERR_SLOT_CUTOFF_PASSED`), hold expirability (`ERR_HOLD_NOT_EXPIRABLE`), the customer no-show gate (`ERR_CUSTOMER_BLOCKED`), curbside capacity (`ERR_CURBSIDE_FULL`), the duplicate active check-in guard (`ERR_DUPLICATE_CHECKIN`), the order-verified requirement (`ERR_ORDER_NOT_VERIFIED`), the per-line hand-over ceiling (`ERR_OVER_HANDOVER`), the on-hand requirement at pick (`ERR_INSUFFICIENT_ON_HAND`), the staging readiness rule (`ERR_STAGE_NOT_READY`), slot capacity (`ERR_SLOT_FULL`), and finally availability of inventory (`ERR_INSUFFICIENT_AVAILABILITY`). This ordering matters: for instance, on a submission, a stale slot version surfaces before the slot-store match, which surfaces before the cutoff check, the blocked-customer gate, the capacity check, and the availability check.

## 3. Business Logic & Workflows

### 3.1. Catalog and Store Seeding

Before any shopping can happen, an operator seeds the system. A `PlatformAdmin` creates stores, each requiring a display `name`, a two-letter US `state_code` (exactly two characters), a `curbside_spaces` count of at least one (the cap on concurrently active curbside check-ins), and an optional `hold_window_minutes` that defaults to 120 and must be at least one. A newly created store begins with its `active_curbside_count` at zero.

A `PlatformAdmin` also creates catalog products, each with a `sku` (a stock-keeping unit that is unique among products; a duplicate `sku` is rejected with `ERR_INVALID_REQUEST`), a display `name`, a positive `unit_price_cents`, and an optional `substitution_group`. The substitution group is a non-empty group key when present and defaults to null; a null group disables substitution for that product, while a non-null group is the only way a substitute can be offered for it later.

Inventory for a store-and-product pair is created by a `PlatformAdmin` or a `StoreManager`, supplying `store_id`, `product_id`, and an initial `on_hand` (a non-negative integer; zero is permitted). The pair is unique: a second attempt to create inventory for the same `store_id` and `product_id` is rejected with `ERR_DUPLICATE_INVENTORY`. On creation the row's `reserved` is zero and `available` equals `on_hand`, and an initial `RESTOCK` `InventoryMovement` is appended to the ledger.

Pickup slots are created by a `PlatformAdmin` or a `StoreManager` against a store, supplying `store_id`, `window_start`, `window_end`, a positive `capacity`, and an optional `cutoff_offset_minutes`. A new slot starts with `booked_count` at zero and `fill_status` `OPEN`.

### 3.2. Customer Registration and the Risk Posture

Anyone — an anonymous caller or a `PlatformAdmin` — may register a `Customer` by supplying a unique, non-empty `email`, a non-empty `full_name`, and a non-empty `phone`. A registration whose `email` duplicates an existing customer's is rejected with `ERR_INVALID_REQUEST`. The endpoint requires no authentication headers; however, if an `X-User-Role` header is supplied it must be `Anonymous` or `PlatformAdmin`, otherwise the request is rejected with `ERR_UNAUTHORIZED`. The phone is later used to match the customer at curbside arrival. A freshly registered customer starts with `no_show_strikes` at zero and `pickup_standing` `GOOD`. Both of these are derived rather than client-set: the strike counter is driven entirely by the hold-expiry path described in Section 3.7, and the standing is always recomputed from it. A customer who repeatedly fails to collect staged orders drifts from `GOOD` to `WATCH` and ultimately to `BLOCKED`, which closes off new submissions.

### 3.3. Building and Submitting an Order

A `Customer` opens a basket by creating an order, supplying the `customer_id` (which must be their own) and the fulfilling `store_id`. A new order starts in `DRAFT` fulfillment with `payment_status` `UNAUTHORIZED` and `verified` false. While the order is in `DRAFT`, the customer adds order lines, each carrying a `product_id` and a positive `qty_ordered`; a new line starts `PENDING` with `qty_reserved` at zero.

Submitting the order is the pivotal transition. The customer provides the `slot_id` to book and the `expected_slot_version` for the optimistic-concurrency check. Submission moves the order's `fulfillment_status` from `DRAFT` to `SUBMITTED` and is permitted only when every one of the following holds: the order has at least one order line (an order with no lines is rejected with `ERR_INVALID_STATE`); the supplied slot exists and its `store_id` equals the order's `store_id` (otherwise `ERR_SLOT_STORE_MISMATCH`); the slot is `OPEN`, meaning `booked_count` is strictly less than `capacity` (otherwise `ERR_SLOT_FULL`); the booking is before the slot's cutoff, meaning the clock is strictly earlier than `window_start` minus `cutoff_offset_minutes` (otherwise `ERR_SLOT_CUTOFF_PASSED`); the acting customer's `pickup_standing` is not `BLOCKED` (otherwise `ERR_CUSTOMER_BLOCKED`); and, for every order line, the `available` quantity of the store-and-product inventory row is at least that line's `qty_ordered` (otherwise `ERR_INSUFFICIENT_AVAILABILITY`). The `expected_slot_version` must also match the slot's current `version`, as described under optimistic concurrency.

When submission succeeds, several effects fire together. For each order line, the line's `qty_ordered` is reserved against its store-and-product inventory: the inventory's `reserved` rises by `qty_ordered`, `available` is recomputed, a `RESERVE` movement is appended, and the line moves to `RESERVED` with `qty_reserved` equal to `qty_ordered`. The booked slot's `booked_count` rises by one, its `fill_status` is recomputed, and its `version` increments by one. The order's `authorized_total_cents` is pinned (see Section 3.9) and its `payment_status` advances from `UNAUTHORIZED` to `AUTHORIZED`. Finally the order's `version` increments by one.

A `Customer` may cancel their own order while it is still in `DRAFT` or `SUBMITTED`; the details of cancellation effects are in Section 3.8.

### 3.4. Picking, Short-Picking, and Staging

Once an order is `SUBMITTED`, a `StorePicker` begins picking, advancing the order's `fulfillment_status` from `SUBMITTED` to `PICKING`; this simply requires the order to currently be `SUBMITTED` and bumps the order's `version`.

With the order in `PICKING`, the picker works each line. Picking a line supplies a `qty_picked` figure. A full pick — where the supplied `qty_picked` equals the line's `qty_ordered` and the inventory's `on_hand` is at least that quantity — moves the line from `RESERVED` to `PICKED`. The effects: `qty_picked` is set to `qty_ordered`, the inventory's `on_hand` falls by that quantity, its `reserved` falls by the same quantity, the line's `qty_reserved` becomes zero, `available` is recomputed, a `PICK_REMOVE` movement is appended, and the line's `version` increments by one. A short pick — where the supplied `qty_picked` is at least zero but strictly less than `qty_ordered`, with `on_hand` at least the supplied `qty_picked` — moves the line from `RESERVED` to `SHORT_PICKED`. In that case `qty_picked` is set to the supplied figure, `on_hand` falls by `qty_picked`, the not-picked portion of the reservation is released (the inventory's `reserved` falls by the difference between `qty_ordered` and `qty_picked`), the line's `qty_reserved` becomes the picked quantity, `available` is recomputed, both a `PICK_REMOVE` and a `RELEASE` movement are appended, and the line's `version` increments by one. A physical pick whose `qty_picked` exceeds the inventory's `on_hand` is rejected with `ERR_INSUFFICIENT_ON_HAND`. A `qty_picked` greater than the line's `qty_ordered` is rejected with `ERR_INVALID_REQUEST`. Picking is permitted only while the parent order is `PICKING` and the line is `RESERVED`; otherwise the request is rejected with `ERR_INVALID_STATE`.

A `SHORT_PICKED` line offers two further paths. If nothing at all was picked for it — `qty_picked` equal to zero — a `StorePicker` may abandon it, releasing the residual reservation (the inventory's `reserved` falls by `qty_reserved`, `qty_reserved` becomes zero, `available` is recomputed, a `RELEASE` movement is appended), moving the line from `SHORT_PICKED` to `NOT_FULFILLED`, and bumping the line's `version`. Abandoning a line that is not `SHORT_PICKED`, or a `SHORT_PICKED` line whose `qty_picked` is not zero, is rejected with `ERR_INVALID_STATE`. Alternatively the short quantity can be covered by a substitution, described in Section 3.5.

Staging the order moves its `fulfillment_status` from `PICKING` to `STAGED`. This is permitted only when every order line is in one of the staging-terminal states `PICKED`, `SUBSTITUTED`, or `NOT_FULFILLED` — that is, no line is still `PENDING`, `RESERVED`, `SHORT_PICKED`, or `SUBSTITUTION_PROPOSED` — and at least one line is `PICKED` or `SUBSTITUTED` so that an entirely-unfulfilled order cannot be staged. A staging attempt that violates either condition is rejected with `ERR_STAGE_NOT_READY`. Staging bumps the order's `version`.

### 3.5. Substitution Negotiation

When a line is `SHORT_PICKED` and its product belongs to a substitution group, a `StorePicker` may propose a substitute to cover the short quantity. A proposal supplies the `order_line_id`, the `substitute_product_id`, and a positive `substitute_qty` (the short quantity). The proposal is allowed only when the original line is `SHORT_PICKED`, the original product's `substitution_group` is non-null, and the substitute product shares that exact same group key; a mismatched or null group is rejected with `ERR_SUBSTITUTION_GROUP_MISMATCH`. A successful proposal creates a `Substitution` with `decision_status` `PROPOSED`, moves the line from `SHORT_PICKED` to `SUBSTITUTION_PROPOSED`, and bumps the line's `version`.

The substitution lifecycle is cyclic, and the customer who owns the parent order drives the decision. The acting `Customer` may accept, moving the substitution from `PROPOSED` to `ACCEPTED`; acceptance requires that the substitution still be `PROPOSED`, that the acting customer own the parent order, and that the substitute's store-and-product inventory have `available` at least the `substitute_qty` (otherwise `ERR_INSUFFICIENT_AVAILABILITY`). On acceptance, the `price_delta_cents` is computed and pinned (see Section 3.9), the substitute inventory is reserved (its `reserved` rises by `substitute_qty`, a `RESERVE` movement is appended, and `available` is recomputed), the line moves from `SUBSTITUTION_PROPOSED` to `SUBSTITUTED` (its already-picked units plus the substitute units are treated as picked for staging; concretely the line's `qty_picked` is increased by `substitute_qty`, so it becomes the already-picked quantity plus the substitute quantity, and this combined `qty_picked` is the figure that the Section 3.6 per-line hand-over ceiling compares against), the order's `authorized_total_cents` rises by the `price_delta_cents` to re-authorize the difference, and both the order's `version` and the line's `version` increment.

The customer may instead decline, and the picker may instead withdraw; both return the line to `SHORT_PICKED` so a fresh substitute may be proposed. A decline (by the owning `Customer`) sets the substitution's `decision_status` to `DECLINED`; a withdrawal (by a `StorePicker`) sets it to `WITHDRAWN`. Either way the parent line moves from `SUBSTITUTION_PROPOSED` back to `SHORT_PICKED` and the line's `version` bumps. Both decline and withdraw require the substitution to currently be `PROPOSED`.

### 3.6. Readiness, Verification, Curbside Arrival, and Hand-Over

Marking a `STAGED` order ready advances its `fulfillment_status` from `STAGED` to `AWAITING_PICKUP` and creates the `Hold` for the order with `staged_at` set to the current clock, `expires_at` computed as described in Section 2.8, and `hold_status` `ACTIVE`; the order's `version` bumps.

Before any units change hands, the order must be verified. A `StoreAssociate` or `StoreManager` verifies an order by supplying the `presented_name` and `presented_phone` (both non-empty strings) offered by the person collecting; the supplied values are not matched against any stored field — verification simply sets the order's `verified` flag to true and bumps the order's `version`, and is accepted in any fulfillment state (it imposes no state guard). An attempt to hand over units, or to begin curbside loading, before the order is verified is rejected with `ERR_ORDER_NOT_VERIFIED`.

A `Customer` who arrives curbside checks in by supplying the `order_id`, the `store_id` of arrival, and a free-text `vehicle_description`. A check-in is created with its `checkin_status` set to `ARRIVED`, and creating it raises the store's `active_curbside_count` by one. A check-in is refused with `ERR_CURBSIDE_FULL` when the store's `active_curbside_count` is already at or above its `curbside_spaces` capacity, and refused with `ERR_DUPLICATE_CHECKIN` when the order already has an active check-in (one already in `ARRIVED` or `BEING_LOADED`). Both `ARRIVED` and `BEING_LOADED` check-ins count toward `active_curbside_count`. A `StoreAssociate` starts loading, moving the check-in from `ARRIVED` to `BEING_LOADED`, but only when the parent order is verified (otherwise `ERR_ORDER_NOT_VERIFIED`); this bumps the check-in's `version`. The associate completes loading, moving the check-in from `BEING_LOADED` to `COMPLETED`, only when the parent order's `fulfillment_status` is `COMPLETED` or `PARTIALLY_PICKED_UP`; completion lowers the store's `active_curbside_count` by one and bumps the check-in's `version`. A check-in may also be cancelled from either `ARRIVED` or `BEING_LOADED` (by a `StoreAssociate`, or by the owning `Customer`), moving it to `CANCELLED`, which likewise lowers `active_curbside_count` by one and bumps its `version`.

The hand-over itself is performed by a `StoreAssociate` on an `AWAITING_PICKUP` order, supplying a set of `handovers` — for each line being collected, the units handed over. The `handovers` value must be a non-empty list of objects, each carrying a non-empty `order_line_id` and a positive-integer `qty_handed_over`, otherwise the request is rejected with `ERR_INVALID_REQUEST`; a referenced `order_line_id` that does not belong to this order is rejected with `ERR_REFERENCE_NOT_FOUND`. Hand-over requires the order to be verified, and for each requested line the handed-over quantity must not exceed that line's `qty_picked` (otherwise `ERR_OVER_HANDOVER`); the ceiling is checked cumulatively — a line's already-recorded `qty_handed_over` plus the quantity requested for it now (summed across any repeated entries for the same line in this request) must not exceed its `qty_picked`. The outcome depends on how much is collected. If the sum of handed-over units across the request is greater than zero but strictly less than the sum of all lines' `qty_picked`, the order moves from `AWAITING_PICKUP` to `PARTIALLY_PICKED_UP`: a `PickupEvent` is created for each handed line recording the `order_id`, the `order_line_id`, the `qty_handed_over` for that event, and the `captured_cents` for that event; each line's `qty_handed_over` rises by the event quantity and a line becomes `HANDED_OVER` once fully handed over; the order's `captured_total_cents` is recomputed and its `payment_status` becomes `CAPTURED`; the order's `version` bumps. If the sum of handed-over units equals the sum of all lines' `qty_picked`, the order moves from `AWAITING_PICKUP` straight to `COMPLETED`: pickup events are created, every fully-handed line becomes `HANDED_OVER`, any residual reservation on short or unfulfilled lines is released (the inventory's `reserved` falls by the residual `qty_reserved`, `available` is recomputed, a `RELEASE` movement is appended, and `qty_reserved` becomes zero), the `captured_total_cents` and `refunded_total_cents` are recomputed, the `payment_status` becomes `CAPTURED` when nothing was refunded or `PARTIALLY_REFUNDED` when a refund was due, the order's hold moves to `RELEASED`, the booked slot's `booked_count` drops by one with its `fill_status` recomputed and its `version` bumped, and the order's `version` bumps.

A `PARTIALLY_PICKED_UP` order is finalized by closing it, which a `StoreAssociate` or `StoreManager` performs to move the order from `PARTIALLY_PICKED_UP` to `COMPLETED`. On close, for each line whose `qty_picked` exceeds its `qty_handed_over`, the not-taken picked units are returned to stock (the inventory's `on_hand` rises by the difference between `qty_picked` and `qty_handed_over`), any residual reservation is released, a restocking movement is appended, and `available` is recomputed. The order's `refunded_total_cents` is recomputed; the `payment_status` becomes `PARTIALLY_REFUNDED` when the refunded total is greater than zero, or `CAPTURED` otherwise. The order's hold moves to `RELEASED`, the booked slot's `booked_count` drops by one with `fill_status` recomputed and `version` bumped, and the order's `version` bumps.

### 3.7. The No-Show Sweep and Hold Expiry

A staged, ready order that is never collected eventually lapses. There are two routes to expiry, both requiring the order to be `AWAITING_PICKUP` and the clock to be at or after the hold's `expires_at`. A `StoreManager` or `PlatformAdmin` may explicitly expire a single order; if the clock has not yet reached the hold's `expires_at`, that request is rejected with `ERR_HOLD_NOT_EXPIRABLE`. Alternatively, an admin-only test-driving capability advances the logical clock to a supplied instant and runs a sweep that, for every hold currently `ACTIVE` whose `expires_at` the new clock has reached, fires the same expiry cascade. A separate admin-only capability sets the clock to a supplied absolute instant without running any sweep.

Expiry transitions the order's `fulfillment_status` from `AWAITING_PICKUP` to `EXPIRED` and is heavy with side effects. For each order line, the picked units are returned to the shelf — the inventory's `on_hand` rises by `qty_picked` (for substituted lines the substitute product's stock is restocked instead) and a `RESTOCK` movement is appended — and the line's `line_status` becomes `NOT_FULFILLED`. Then, for each line, any residual reservation is released: the inventory's `reserved` falls by `qty_reserved`, `qty_reserved` becomes zero, `available` is recomputed, and a `RELEASE` movement is appended. The order's `refunded_total_cents` is set to the full `authorized_total_cents` and the `payment_status` becomes `REFUNDED`. The order's hold moves to `EXPIRED`. The booked slot's `booked_count` drops by one with its `fill_status` recomputed and its `version` bumped. The owning customer's `no_show_strikes` rises by one and their `pickup_standing` is recomputed against the thresholds in Section 2.9. Finally the order's `version` bumps.

### 3.8. Cancellation Paths

Cancellation is available at several lifecycle points, with the actor depending on the stage. A `Customer` may cancel their own order while it is `DRAFT` or `SUBMITTED`; a `StoreManager` may cancel an order while it is `PICKING`. Cancelling a `DRAFT` order simply moves it from `DRAFT` to `CANCELLED` and bumps the order's `version`; nothing was reserved in `DRAFT`, so there is no inventory or slot to release.

Cancelling a `SUBMITTED` order moves it from `SUBMITTED` to `CANCELLED` and unwinds the submission: for each line the inventory's `reserved` falls by `qty_reserved`, `available` is recomputed, a `RELEASE` movement is appended, `qty_reserved` becomes zero, and the line becomes `NOT_FULFILLED`; the booked slot's `booked_count` drops by one with its `fill_status` recomputed and its `version` bumped; the order's `refunded_total_cents` is set to the full `authorized_total_cents` and `payment_status` becomes `REFUNDED`; and the order's `version` bumps. Cancelling a `PICKING` order moves it from `PICKING` to `CANCELLED` and additionally returns any already-picked units to stock: for each line the inventory's `on_hand` rises by `qty_picked`, its `reserved` falls by `qty_reserved`, `available` is recomputed, a `RELEASE` movement is appended, `qty_reserved` and `qty_picked` both become zero, and the line becomes `NOT_FULFILLED`; the booked slot's `booked_count` drops by one with `fill_status` recomputed and `version` bumped; the `refunded_total_cents` is set to the full `authorized_total_cents`, `payment_status` becomes `REFUNDED`, and the order's `version` bumps.

### 3.9. Money: Authorization, Capture, Refund, and the Payment Axis

An order's money lives on three computed totals — `authorized_total_cents`, `captured_total_cents`, and `refunded_total_cents` — and a `payment_status` that is a parallel lifecycle on the same record, evolving as one of `UNAUTHORIZED`, `AUTHORIZED`, `CAPTURED`, `REFUNDED`, or `PARTIALLY_REFUNDED`.

The authorized total is pinned at submission. It is computed by first taking each line's subtotal — the product's `unit_price_cents` multiplied by that line's `qty_ordered` — and then summing those per-line subtotals across all the order's reserved lines. The per-line-then-sum order is fixed even though no rounding occurs here, so that the authorization path mirrors the capture path. When a substitution is accepted, the accepted substitution's `price_delta_cents` is added to `authorized_total_cents`; that delta is the substitute product's `unit_price_cents` minus the original product's `unit_price_cents`, multiplied by the `substitute_qty`. The delta is a signed figure and is negative when the substitute is cheaper.

The captured total is recomputed at each pickup transition from the units actually handed over. For each line with a positive `qty_handed_over`, the effective unit price is the original product's `unit_price_cents` for a normal line, or the substitute product's `unit_price_cents` for a `SUBSTITUTED` line. The captured contribution of a line is that effective unit price, rounded half-up to a whole cent, multiplied by the line's `qty_handed_over`; the captured total is the sum of those contributions across all lines. The rounding step on the per-unit price comes before the multiplication, and the multiplication before the sum — this order is pinned, never sum-then-round. On a full pickup with no substitution and no shortfall, the captured total equals the authorized total; on a partial pickup the captured total covers only the handed-over units, and the remainder is refunded.

The refunded total is recomputed at the terminal fulfillment transitions. When an order ends in `CANCELLED` or `EXPIRED`, the refunded total equals the full `authorized_total_cents` and the captured total stays zero. When an order ends in `COMPLETED` (whether reached directly or through a close after a partial pickup), the refunded total equals `authorized_total_cents` minus `captured_total_cents` — the not-handed-over remainder. This preserves the compensating invariant that for any completed order, captured plus refunded equals authorized.

The payment axis is driven entirely by the fulfillment transitions rather than by independent endpoints. At submission it moves from `UNAUTHORIZED` to `AUTHORIZED` with the authorization pinned. When fulfillment reaches `COMPLETED` with nothing refunded, it moves from `AUTHORIZED` to `CAPTURED`; when fulfillment reaches `COMPLETED` (directly or via a partial-pickup close) with a refund greater than zero but strictly less than the authorized amount, it moves from `AUTHORIZED` to `PARTIALLY_REFUNDED`. When fulfillment reaches `CANCELLED` or `EXPIRED`, it moves from `AUTHORIZED` to `REFUNDED` with the refunded total set to the full authorization.

### 3.10. Reading Back the State

Each entity can be fetched and listed for verification and operations. A customer fetch returns the derived `no_show_strikes` and `pickup_standing`; a store fetch returns the computed `active_curbside_count`; an inventory fetch returns the computed `reserved` and `available`; a slot fetch returns the computed `booked_count` and `fill_status`; an order fetch returns all the computed totals together with both the `fulfillment_status` and `payment_status` axes; an order-line fetch returns the computed quantity fields and `line_status`; and a substitution fetch returns its `decision_status` and `price_delta_cents`. List endpoints support reverse navigation from a parent to its children — a customer's orders, a store's pickup slots, inventory rows, curbside check-ins, and holds, an order's lines, pickup events, holds, and curbside check-ins, a line's pickup events and substitutions, and an inventory row's movements — and several flat lists accept filter query parameters such as `store_id`, `product_id`, `slot_id`, `customer_id`, and `order_id` alongside the standard `limit` and `offset`. The clock-setting and clock-advancing operations both take a `to_iso8601` instant.

## 4. Endpoint Definitions

All endpoints return their result inside the standard envelope of Section 2.2. Creating a new resource returns HTTP 201 with the created resource in `data`. State transitions and other modifications that act on an existing resource return HTTP 200 with the updated resource (or, for the clock operations, an empty object). Read endpoints return HTTP 200. The request and response payloads for each endpoint are described in the Section 3 narratives; the table below is only a routing summary.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /customers | Register a customer | Anonymous, PlatformAdmin |
| GET | /customers/{id} | Fetch a customer | Customer, StoreManager, PlatformAdmin |
| GET | /customers/{id}/orders | List a customer's orders | Customer, StoreManager, PlatformAdmin |
| POST | /stores | Create a store | PlatformAdmin |
| GET | /stores/{id} | Fetch a store | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /stores/{id}/pickup-slots | List a store's pickup slots | Customer, StorePicker, StoreManager, PlatformAdmin |
| GET | /stores/{id}/inventory | List a store's inventory rows | Customer, StorePicker, StoreManager, PlatformAdmin |
| GET | /stores/{id}/curbside-checkins | List a store's curbside check-ins | StoreAssociate, StoreManager, PlatformAdmin |
| GET | /stores/{id}/holds | List a store's staged holds | StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /products | Create a catalog product | PlatformAdmin |
| GET | /products/{id} | Fetch a product | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /store-inventory | Create a store/product inventory row | PlatformAdmin, StoreManager |
| GET | /store-inventory | Filtered list of inventory rows | Customer, StorePicker, StoreManager, PlatformAdmin |
| GET | /store-inventory/{id} | Fetch an inventory row | Customer, StorePicker, StoreManager, PlatformAdmin |
| GET | /store-inventory/{id}/movements | List inventory movements for a row | StoreManager, PlatformAdmin |
| POST | /store-inventory/{id}/restock | Adjust on-hand by a delta (OCC-guarded) | PlatformAdmin, StoreManager |
| POST | /pickup-slots | Create a pickup slot for a store | PlatformAdmin, StoreManager |
| GET | /pickup-slots/{id} | Fetch a pickup slot | Customer, StorePicker, StoreManager, PlatformAdmin |
| POST | /orders | Create a DRAFT order | Customer |
| GET | /orders | Filtered list of orders | StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /orders/{id} | Fetch an order | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /orders/{id}/lines | Add an order line to a DRAFT order | Customer |
| GET | /orders/{id}/lines | List an order's lines | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /orders/{id}/pickup-events | List an order's pickup events | Customer, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /orders/{id}/holds | List the order's hold | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /orders/{id}/curbside-checkins | List the order's curbside check-ins | Customer, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /orders/{id}/submit | Submit a DRAFT order (book slot, reserve, authorize) | Customer |
| POST | /orders/{id}/start-picking | Begin picking | StorePicker |
| POST | /orders/{id}/stage | Stage the order | StorePicker |
| POST | /orders/{id}/ready | Mark ready and create the hold | StorePicker |
| POST | /orders/{id}/verify | Identity/order verification at the store | StoreAssociate, StoreManager |
| POST | /orders/{id}/pickup | Hand over units | StoreAssociate |
| POST | /orders/{id}/close | Close a partially-picked-up order | StoreAssociate, StoreManager |
| POST | /orders/{id}/cancel | Cancel an order | Customer, StoreManager |
| POST | /orders/{id}/expire | Expire a hold past its deadline | StoreManager, PlatformAdmin |
| GET | /order-lines | Filtered list of order lines | StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /order-lines/{id} | Fetch an order line | Customer, StorePicker, StoreAssociate, StoreManager, PlatformAdmin |
| GET | /order-lines/{id}/pickup-events | List pickup events for a line | Customer, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /order-lines/{id}/pick | Physically pick a line | StorePicker |
| POST | /order-lines/{id}/abandon | Abandon a short line with nothing picked | StorePicker |
| GET | /order-lines/{id}/substitutions | List substitutions for a line | Customer, StorePicker, StoreManager, PlatformAdmin |
| POST | /substitutions | Propose a substitute for a short-picked line | StorePicker |
| GET | /substitutions | Filtered list of substitutions | StorePicker, StoreManager, PlatformAdmin |
| GET | /substitutions/{id} | Fetch a substitution | Customer, StorePicker, StoreManager, PlatformAdmin |
| POST | /substitutions/{id}/accept | Customer accepts the substitute | Customer |
| POST | /substitutions/{id}/decline | Customer declines the substitute | Customer |
| POST | /substitutions/{id}/withdraw | Picker withdraws the proposal | StorePicker |
| POST | /curbside-checkins | Customer arrives curbside | Customer |
| GET | /curbside-checkins/{id} | Fetch a curbside check-in | Customer, StoreAssociate, StoreManager, PlatformAdmin |
| POST | /curbside-checkins/{id}/start-loading | Associate begins loading | StoreAssociate |
| POST | /curbside-checkins/{id}/complete | Associate completes loading | StoreAssociate |
| POST | /curbside-checkins/{id}/cancel | Cancel a curbside check-in | StoreAssociate, Customer |
| POST | /_clock/set | Set the system clock (test-driving) | PlatformAdmin |
| POST | /_clock/advance | Advance the clock and run the hold-expiry sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_INVENTORY | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_SLOT_VERSION | 412 |
| ERR_STALE_INVENTORY_VERSION | 412 |
| ERR_SLOT_CUTOFF_PASSED | 409 |
| ERR_HOLD_NOT_EXPIRABLE | 409 |
| ERR_SLOT_STORE_MISMATCH | 409 |
| ERR_SUBSTITUTION_GROUP_MISMATCH | 409 |
| ERR_ORDER_NOT_VERIFIED | 409 |
| ERR_OVER_HANDOVER | 409 |
| ERR_CURBSIDE_FULL | 409 |
| ERR_DUPLICATE_CHECKIN | 409 |
| ERR_SLOT_FULL | 409 |
| ERR_INSUFFICIENT_AVAILABILITY | 409 |
| ERR_CUSTOMER_BLOCKED | 409 |
| ERR_INSUFFICIENT_ON_HAND | 409 |
| ERR_STAGE_NOT_READY | 409 |
