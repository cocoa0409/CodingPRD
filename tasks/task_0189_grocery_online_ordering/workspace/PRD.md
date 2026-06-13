# Grocery Online Ordering & Fulfillment API — Product Requirements Document

## 1. Introduction

This document specifies the Grocery Online Ordering & Fulfillment API, the back-end service that carries a grocery order from the moment a customer reserves a delivery or pickup slot through to the instant the bagged goods are handed to them. The domain is unusually rich because two things vary between the moment an order is placed and the moment it is fulfilled: the *contents* of the basket (an item the customer wanted may be out of stock, or may be swapped for an acceptable substitute) and the *price* of weighted goods (a head of lettuce billed by the kilogram weighs whatever it weighs when it reaches the scale, not what the catalog estimated). The system must therefore maintain two parallel pricing views — an estimated total pinned when the order is placed, and a final total reconciled as the picker actually works the basket — and it must keep payment, refunds, and the customer's SNAP/EBT balance perfectly consistent with whatever the basket finally contained.

Beyond pricing, the platform models the operational realities of a grocery fulfillment floor: a finite number of orders can be booked into any delivery or pickup window, perishable cold-chain goods cannot sit staged indefinitely, alcohol and other age-restricted goods require an in-person identity check before they leave the building, and government SNAP/EBT benefits may only be applied to eligible food and never to a tip. The API serves four kinds of actors — the ordering customer, the in-store picker who assembles the basket, the store back-office operator, and the platform administrator who provisions the system — each of whom sees and drives a different slice of the order lifecycle. The sections that follow define the global contract every endpoint honors (§2), the business workflows and their scattered rules (§3), the endpoint surface (§4), and the canonical error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contract, and cross-cutting principles that apply across every endpoint. The whole API is mounted under the `/v1` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malforming either header is rejected with `ERR_MISSING_USER_CONTEXT`. When the headers are present but the declared role is not permitted to perform the requested operation — or when an ownership check fails — the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `StoreOps`, `Customer`, and `Picker`.

`PlatformAdmin` and `StoreOps` are operator roles whose identities are opaque. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `StoreOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record such an operator identifier where a workflow captures it (for example, the `verifier_user_id` written onto an `AgeCheck`), but it does not compare it to any entity's `id`.

`Customer` and `Picker` are entity-backed roles. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. A customer may place, edit, cancel, and decide substitutions only on their own orders — that is, orders whose `customer_id` equals their `X-User-ID`. When `X-User-Role` is `Picker`, `X-User-ID` is the `id` of the acting `Picker`; ownership and eligibility checks compare the relevant picker foreign key to `X-User-ID`. In particular, a picker may only claim an order at a store where that picker is registered (the claiming picker's `id` must be a `Picker` of the order's store).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Values outside these bounds are treated as a malformed request.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Every resource is addressed by an `id` that the server mints as a UUID with no type prefix. The system also stamps each resource with a `created_at` timestamp, recorded as an ISO 8601 UTC value with three fractional digits, captured when the resource is first created.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current time on every mutation of the resource, and `version` starts at the resource's creation value and increments by one on every mutation. The `version` field underpins optimistic concurrency control (see §2.8). The single exception is the `Refund` resource: a refund is an append-only event record that carries only `id` and `created_at` — it has no `updated_at` and no `version`, because once written it is never modified.

### 2.5. Hierarchical Reconciliation and Derived Fields

Several fields are *derived*: the server computes them from other state rather than accepting them as input, and it keeps them current automatically whenever the state they depend on changes. An `Order`'s totals (`estimated_total_cents`, `estimated_ebt_eligible_cents`, `final_total_cents`, `final_ebt_eligible_cents`, `ebt_charged_cents`, `card_charged_cents`, `refunded_total_cents`, `net_captured_cents`, and the `requires_age_check` flag) are all derived in this way, as are an `OrderLine`'s `estimated_line_cents` and `final_line_cents`, a `Substitution`'s `substitute_line_cents`, a `FulfillmentSlot`'s `booked_count` and `status`, and an `AgeCheck`'s `outcome`. Whenever a child mutation changes a value that an order total depends on — a line is picked, substituted, marked out of stock, or cancelled — the server recomputes the affected order totals as part of the same operation, refreshing the order's `updated_at` and incrementing its `version`. Recomputing a derived field is itself a mutation and obeys the versioning rules in §2.4.

Because all monetary fields are integer cents, the system never carries fractional currency. Where a calculation produces a fractional intermediate (only weighted pricing does this — see §3.4), the system rounds that single product to the nearest whole cent using round-half-up, then treats every later aggregation as an exact integer sum. Order and payment totals are formed by rounding each line to whole cents first and then summing the already-rounded line charges; the system never sums fractional products and rounds once at the end.

### 2.6. Slot and Picker Capacity Discipline

A `FulfillmentSlot` represents one bookable delivery or pickup window with a finite `capacity`. Its `booked_count` is the number of orders referencing the slot whose `fulfillment_status` is one of `PLACED`, `PICKING`, `STAGED`, or `HANDED_OFF`; cancelled orders do not count toward it. The slot's `status` is `OPEN` while it can still take bookings, becomes `FULL` the moment its `booked_count` equals its `capacity`, and is `CLOSED` only when an operator manually closes it.

Capacity is enforced strictly at placement: a new order is admitted only when the slot's `booked_count` is strictly less than `capacity` before the booking is recorded; otherwise the placement is refused with `ERR_SLOT_FULL`. A successful placement increases `booked_count` by one, and if that brings `booked_count` up to `capacity` the slot transitions `OPEN → FULL`. When an order against the slot is cancelled, `booked_count` decreases by one, and if the slot was `FULL` and `booked_count` is now below `capacity` it transitions `FULL → OPEN`.

Pickers carry their own capacity discipline through a per-picker cooldown buffer, `window_cooldown_minutes`, which sets the minimum gap a picker must keep between the pick windows they hold. The detailed conflict rule lives with the claim workflow in §3.2.

### 2.7. Slot Window Integrity and Nested Lookups

Because the entity topology is flat, related resources are referenced by foreign-key fields carried in request bodies rather than by nested URL paths; a request that names a resource by its `id` in the path is validated for existence before any business rule runs. When an operation references several resources, the server resolves them in a sensible order and reports the first failure: a path identifier that does not correspond to an existing resource yields the matching not-found error — `ERR_STORE_NOT_FOUND` for an unknown store, `ERR_CUSTOMER_NOT_FOUND` for an unknown customer, `ERR_PRODUCT_NOT_FOUND` for an unknown product, `ERR_SLOT_NOT_FOUND` for an unknown slot, `ERR_PICKER_NOT_FOUND` for an unknown picker, `ERR_ORDER_NOT_FOUND` for an unknown order, `ERR_LINE_NOT_FOUND` for an unknown line, and `ERR_SUBSTITUTION_NOT_FOUND` for an unknown substitution — before any body-level referential or state check is attempted.

Fulfillment windows themselves must not overlap. A `FulfillmentSlot` is created with a `window_start` and a `window_end`, both ISO 8601 UTC instants, where `window_end` must be strictly after `window_start`. The window is treated as half-open — it includes its start instant and excludes its end instant. When a new slot is created, the system rejects it with `ERR_SLOT_WINDOW_OVERLAP` if its window overlaps that of any existing slot belonging to the same store and having the same `slot_type`.

### 2.8. Optimistic Concurrency on Slot Booking

Placing an order books a slot, and that booking is guarded by optimistic concurrency control on the slot. A placement request must carry `expected_slot_version`, a non-optional field holding the `version` of the target `FulfillmentSlot` that the client last observed. The server compares it against the slot's current `version`; if they do not match, the placement is rejected with `ERR_SLOT_VERSION_STALE` (HTTP 412). The intent is concrete: when a previous placement legitimately consumed the last remaining unit of capacity — driving `booked_count` up to `capacity`, flipping the slot to `FULL`, and advancing the slot's `version` — a later request still carrying the pre-booking version is operating on a stale view of remaining capacity, and is rejected on the stale-version check rather than being allowed to overbook. Placement is the only endpoint that takes a version field; no other operation requires `expected_slot_version` or any other expected-version input.

### 2.9. The SNAP/EBT Tender Principle

The platform supports split-tender payment between a government SNAP/EBT benefit and a payment card. Three rules are invariant across the system. First, only products explicitly flagged `ebt_eligible` may draw on the EBT benefit; ineligible goods and the customer's `tip_cents` are never EBT-eligible and always fall to the card. Second, a store participates in EBT only when its `ebt_enabled` flag is true; a store with `ebt_enabled` false may not capture an order that carries any EBT-eligible value. Third, the customer's `snap_ebt_balance_cents` is a hard ceiling on how much EBT can be applied, and in this version of the platform refunds do not refill that balance. The precise allocation arithmetic and capture preconditions are given with the capture workflow in §3.6.

### 2.10. Validation Ordering

When a single request could fail several checks, the system evaluates them in a fixed priority order so that the reported error is deterministic. The order is: (1) authentication — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_MISSING_USER_CONTEXT`; (2) authorization — the role must be permitted for the operation and, for the entity-backed `Customer` and `Picker` roles, must own the targeted resource, else `ERR_FORBIDDEN_ROLE`; (3) existence — every resource named by a path identifier must exist, else the corresponding not-found error; (4) referential integrity — body foreign keys must resolve, must belong to the same store, and the referenced product, customer, and store must each be in an acceptable status (these checks back `POST /v1/orders`, `POST /v1/order-lines`, and `POST /v1/substitutions`); (5) state — the target resource must be in the correct state for the requested transition; (6) business constraints such as slot concurrency, slot capacity, window overlap, picker window overlap, stage readiness, and pick quantity; (7) age-verification safety on handoff; (8) the cold-chain temporal window on handoff; and (9) fiscal preconditions at capture and the substitution price ceiling. Within an endpoint, a check earlier in this ordering always preempts a later one, so for example a malformed user context is reported before any state problem, and a state problem is reported before a capacity problem. Malformed bodies, missing required fields, and invalid enum or type values surface as `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Catalog: Stores, Customers, Pickers, Products, and Slots

Before any order can exist, a `PlatformAdmin` provisions the platform's foundational records, with `StoreOps` sharing several of the catalog operations. A store is created with a `name`, an optional `timezone` (an IANA label that defaults to `UTC` and is informational only), an optional `ebt_enabled` flag that defaults to true and declares whether the store accepts SNAP/EBT tender, and an optional `cold_chain_hold_minutes` value that defaults to 120 and sets how long a staged order containing perishable goods may wait before handoff is refused. A store begins life `ACTIVE`. A `PlatformAdmin` may move a store from `ACTIVE` to `CLOSED`; a `CLOSED` store refuses new orders with `ERR_STORE_CLOSED`.

Customers are created by a `PlatformAdmin` with an `email` (which must be unique), a `full_name`, a `date_of_birth` (an ISO 8601 date used for age-restricted line checks), and an optional opening `snap_ebt_balance_cents` benefit balance that defaults to 0. A customer begins `ACTIVE`. A `PlatformAdmin` may move a customer from `ACTIVE` to `SUSPENDED` and back from `SUSPENDED` to `ACTIVE`; a `SUSPENDED` customer is refused at order placement with `ERR_CUSTOMER_SUSPENDED`.

A picker is created — by a `PlatformAdmin` or `StoreOps` — bound to a store through `store_id`, with a `full_name` and an optional `window_cooldown_minutes` buffer that defaults to 15. A picker begins `AVAILABLE`; a picker who is `OFF_SHIFT` cannot claim orders.

Products live in a store's catalog and are created with the store's `store_id`, a `sku` (unique within the store), a display `name`, a `pricing_mode`, a `unit_price_cents`, and a handful of optional flags. The `pricing_mode` is either `UNIT` (priced per each) or `WEIGHT` (priced per kilogram), and `unit_price_cents` is the price per each for a `UNIT` product or the price per kilogram for a `WEIGHT` product, in cents, and must be at least 0. The optional flags are `ebt_eligible` (defaults to false; whether the product may be paid with SNAP/EBT), `age_restricted` (defaults to false; whether sale requires an adult age verification at handoff), `cold_chain` (defaults to false; whether the product is a perishable subject to the staged-hold window), and `on_hand_qty` (defaults to 0; an informational stock signal counted in units for `UNIT` products or kilograms for `WEIGHT` products). A product begins `ACTIVE`. A `PlatformAdmin` or `StoreOps` may move a product from `ACTIVE` to `DISCONTINUED`; a `DISCONTINUED` product cannot be added to a new line nor proposed as a substitute, and an attempt to do so is rejected with `ERR_PRODUCT_DISCONTINUED`.

Fulfillment slots are created by a `PlatformAdmin` or `StoreOps` with the store's `store_id`, a `slot_type` of either `DELIVERY` or `PICKUP`, a `window_start`, a `window_end`, and a `capacity` of at least 1. A freshly created slot opens with `status` `OPEN` and a `booked_count` of 0. The non-overlap rule of §2.7 applies on creation. Either operator role may later close a slot, moving it from `OPEN` or `FULL` to `CLOSED`; a `CLOSED` slot refuses all new placements with `ERR_SLOT_CLOSED`, while orders already booked against it are unaffected.

### 3.2. Placing an Order and Working the Basket

A `Customer` (acting on their own behalf, so that `X-User-ID` equals the `customer_id`) or a `StoreOps` operator places an order. The placement payload carries the `store_id` of the fulfilling store, the `customer_id` of the ordering customer, the `slot_id` of the chosen fulfillment slot, the `expected_slot_version` discussed in §2.8, an initial set of `lines`, and an optional `tip_cents` that defaults to 0 and must be at least 0. Each entry in `lines` describes a desired product. Placement first satisfies the referential checks of §2.10 — the customer, slot, and every product must exist; the slot, products, and (where applicable) picker must belong to the same store as `store_id`, or the request is rejected with `ERR_CROSS_STORE_REFERENCE`; the store must be `ACTIVE`; the customer must be `ACTIVE`; no referenced product may be `DISCONTINUED`. It then satisfies the slot version check and the capacity check of §2.6. On success the server creates one `OrderLine` per entry in `lines`, computes each line's `estimated_line_cents`, computes the order's `estimated_total_cents` and `estimated_ebt_eligible_cents`, sets `fulfillment_status` to `PLACED` and `payment_status` to `AUTHORIZED`, increases the slot's `booked_count` by one and increments the slot's `version` by one (flipping the slot to `FULL` if `booked_count` now equals `capacity`).

An order carries two independent status dimensions. The fulfillment dimension, `fulfillment_status`, walks `PLACED → PICKING → STAGED → HANDED_OFF`, with `CANCELLED` reachable from `PLACED`, `PICKING`, or `STAGED`; `HANDED_OFF` and `CANCELLED` are terminal. The payment dimension, `payment_status`, walks `AUTHORIZED → CAPTURED` and may then evolve to `PARTIALLY_REFUNDED`, `REFUNDED`, or `VOIDED`; the two dimensions advance independently. The order also exposes a `picker_id` (the picker who claimed it, null until claimed) and a `staged_at` timestamp (null until the order is staged).

While an order is still `PLACED` and before it is claimed, the basket may be edited: a `Customer` or `StoreOps` adds a line by supplying the parent `order_id`, the `product_id`, a `requested_qty`, an optional `estimated_weight_kg`, and an optional `substitution_policy`. The `requested_qty` is the requested each-count for a `UNIT` product and must be greater than 0 (use 1 for a `WEIGHT` product). The `estimated_weight_kg` is the estimated kilograms for a `WEIGHT` product; it is required when the product's `pricing_mode` is `WEIGHT` and is ignored for a `UNIT` product. Adding a line computes its `estimated_line_cents` and recomputes the order's estimated totals. Each created line begins `PENDING`, references its parent through `order_id` and its product through `product_id`, and records its chosen `substitution_policy`, which defaults to `NO_SUBSTITUTION`.

A `Picker` claims a `PLACED` order to begin work, which advances `fulfillment_status` from `PLACED` to `PICKING` and records the acting picker on `picker_id`. The claim payload supplies the `window_start` and `window_end` of the pick window the picker is taking on. Claiming is permitted only when the order is `PLACED` (otherwise `ERR_INVALID_ORDER_STATE`) and the acting picker is `AVAILABLE`. The claim also enforces the picker's cooldown: the new pick window `[window_start, window_end)` must not overlap any window the picker already holds once each held window is extended by the picker's `window_cooldown_minutes` buffer on each side; if the new window collides with an existing window within that buffer, the claim is rejected with `ERR_PICKER_WINDOW_CONFLICT`.

### 3.3. Resolving Each Line: Pick, Out-of-Stock, and Substitution

Each `OrderLine` is resolved by the picker while the parent order is `PICKING`. A line's `status` moves out of `PENDING` along one of three branches — `PICKED`, `SUBSTITUTED`, or `OUT_OF_STOCK` — and `CANCELLED` is reached only when the parent order is cancelled. `PICKED`, `SUBSTITUTED`, `OUT_OF_STOCK`, and `CANCELLED` are all terminal for a line.

To pick a line, a `Picker` records the actual pick on a `PENDING` line whose parent order is `PICKING`, advancing the line from `PENDING` to `PICKED`. The pick payload supplies `picked_qty` for a `UNIT` product and `actual_weight_kg` for a `WEIGHT` product. For a `UNIT` product, `picked_qty` must be present and greater than 0; for a `WEIGHT` product, `actual_weight_kg` must be present and greater than 0; a missing or non-positive quantity is rejected with `ERR_INVALID_PICK_QUANTITY`. Picking recomputes the line's `final_line_cents` from the recorded `picked_qty` or `actual_weight_kg`. A pick attempted on a line that is not `PENDING` is rejected with `ERR_LINE_NOT_PENDING`, and a pick attempted while the parent order is not `PICKING` is rejected with `ERR_ORDER_NOT_PICKING`.

When an item simply cannot be found while picking, a `Picker` marks a `PENDING` line `OUT_OF_STOCK`, again only while the parent order is `PICKING` (otherwise `ERR_LINE_NOT_PENDING` for a non-pending line, `ERR_ORDER_NOT_PICKING` for the wrong order state). This pre-capture out-of-stock simply sets the line's `final_line_cents` to 0 so that the line contributes nothing to the final total at stage; because payment is still `AUTHORIZED`, no `Refund` is created. The post-capture variant of going out of stock — for a line that was already `PICKED` on a staged, captured order — is a different transition with a refund cascade, and is described in §3.7.

When a desired product is unavailable but an acceptable replacement exists, a `Picker` proposes a substitution by supplying the `order_line_id` of the line being replaced, the `substitute_product_id`, a `substitute_qty` (the each-count of the substitute for a `UNIT` substitute, greater than 0, or 1 for a `WEIGHT` substitute), and an optional `substitute_weight_kg` (the actual kilograms, required when the substitute product's pricing is `WEIGHT`). Proposing computes the substitute's `substitute_line_cents` using the same per-line charge rule that produces `final_line_cents`, applied to the substitute product, and the substitution begins `PROPOSED`. A substitution is then decided by a `Customer` or a `Picker`. Accepting a substitution advances it from `PROPOSED` to `ACCEPTED` and advances the parent line from `PENDING` to `SUBSTITUTED`, copying the substitution's `substitute_line_cents` onto the line's `final_line_cents`. Acceptance requires that the substitution is still `PROPOSED` (otherwise `ERR_SUBSTITUTION_NOT_PROPOSED`), that the parent line is still `PENDING` (otherwise `ERR_LINE_NOT_PENDING`), that the parent order is `PICKING` (otherwise `ERR_ORDER_NOT_PICKING`), and that the line's `substitution_policy` is not `NO_SUBSTITUTION` (otherwise `ERR_SUBSTITUTION_NOT_ALLOWED`); additionally, when the policy is `SAME_PRICE_OR_LESS`, the substitute's `substitute_line_cents` must be less than or equal to the line's `estimated_line_cents`, or the acceptance is rejected with `ERR_SUBSTITUTION_PRICE_EXCEEDED`. A `SHOPPER_CHOICE` policy carries no price ceiling. Rejecting a substitution advances it from `PROPOSED` to `REJECTED` and requires only that it was still `PROPOSED` (otherwise `ERR_SUBSTITUTION_NOT_PROPOSED`); a rejection leaves the parent line untouched and still `PENDING`, so it remains pickable or markable out of stock.

### 3.4. Pricing a Line: Estimated and Final

Each line is priced twice, by one rule applied to two different quantities. For a `UNIT` product the charge is `unit_price_cents` multiplied by the quantity (a whole each-count). For a `WEIGHT` product the charge is `unit_price_cents` multiplied by the weight in kilograms, with that single product rounded half-up to a whole number of cents. The estimated charge, `estimated_line_cents`, is computed at line creation using the `requested_qty` for a `UNIT` product or the `estimated_weight_kg` for a `WEIGHT` product. The final charge, `final_line_cents`, is computed when the line is actually resolved, using the `picked_qty` for a `UNIT` product or the `actual_weight_kg` for a `WEIGHT` product; for a substituted line the final charge is the substitute's `substitute_line_cents`, and for an out-of-stock or cancelled line the final charge is 0. The estimated and final charges diverge precisely when a weighted item hits the scale at a different weight than was estimated, or when a line goes out of stock.

### 3.5. Staging and Order Totals

Once the basket is fully worked, a `Picker` stages the order, advancing `fulfillment_status` from `PICKING` to `STAGED`. Staging is admitted only when the order is `PICKING` (otherwise `ERR_INVALID_ORDER_STATE`), when every line has reached a terminal state — none may still be `PENDING`, or the stage is rejected with `ERR_LINES_NOT_RESOLVED` — and when at least one line is `PICKED` or `SUBSTITUTED`, or the stage is rejected with `ERR_NOTHING_TO_STAGE`. Staging sets `staged_at` to the current clock and recomputes the order's `final_total_cents`, `final_ebt_eligible_cents`, and `requires_age_check`.

The estimated totals are pinned at placement. The `estimated_total_cents` is the sum of `estimated_line_cents` over all of the order's lines, plus the order's `tip_cents`. The `estimated_ebt_eligible_cents` is the sum of `estimated_line_cents` over only those lines whose product is `ebt_eligible`, and it excludes the tip. The final totals are reconciled at stage and refreshed again at capture and on an out-of-stock refund. The `final_total_cents` is the sum of `final_line_cents` over only the lines whose status is `PICKED` or `SUBSTITUTED`, plus the order's `tip_cents`; lines that are `OUT_OF_STOCK` or `CANCELLED` contribute 0. The `final_ebt_eligible_cents` is the sum of `final_line_cents` over the `PICKED` or `SUBSTITUTED` lines whose *effective* product is `ebt_eligible`, excluding the tip — and for a `SUBSTITUTED` line the effective product is the substitute product, not the original. Both estimated and final totals are formed by rounding each line to whole cents first and then summing the already-rounded line charges, exactly as §2.5 requires. The `requires_age_check` flag is true when any `PICKED` or `SUBSTITUTED` line's effective product is `age_restricted`.

### 3.6. Capturing Payment and the Split-Tender Allocation

A `StoreOps` operator captures payment on a staged order, advancing `payment_status` from `AUTHORIZED` to `CAPTURED`. Capture is admitted only when the payment is `AUTHORIZED` (otherwise `ERR_INVALID_ORDER_STATE`) and the order is `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`). One further fiscal gate applies: if the store's `ebt_enabled` is false, the order's `final_ebt_eligible_cents` must be 0, or the capture is rejected with `ERR_EBT_NOT_ACCEPTED`.

Capture runs a two-bucket waterfall allocation against three inputs — the order's `final_ebt_eligible_cents` (the EBT-eligible portion), the customer's `snap_ebt_balance_cents` (the available benefit), and the order's `final_total_cents` (the grand total). The EBT bucket is filled first: `ebt_charged_cents` is the smaller of `final_ebt_eligible_cents` and the customer's `snap_ebt_balance_cents`. The card bucket then takes the remainder: `card_charged_cents` is `final_total_cents` minus `ebt_charged_cents`, which absorbs the tip, all ineligible goods, and any EBT-eligible value that exceeded the benefit balance. By construction the two buckets always sum to `final_total_cents`, the EBT bucket never exceeds the benefit balance, and the EBT bucket never exceeds the eligible portion. Because any uncovered EBT-eligible remainder simply spills to the card, capture never fails for a low EBT balance — the shortfall lands on the card instead.

Capture then commits its side effects: it debits the customer's `snap_ebt_balance_cents` by `ebt_charged_cents` (this benefit is not refilled by later refunds in this version), creates exactly one `Payment` record, and sets the order's `net_captured_cents` to the order's `final_total_cents`. The `Payment` record is a split-tender capture record referencing its parent through `order_id`; it records `ebt_amount_cents` (equal to the order's `ebt_charged_cents` at capture), `card_amount_cents` (equal to the order's `card_charged_cents`), and `grand_total_cents` (their sum, equal to the order's `final_total_cents`). A `Payment` is created with `status` `CAPTURED` and is immutable once created. Before capture, the order's `ebt_charged_cents`, `card_charged_cents`, and `net_captured_cents` are all 0, as is its `refunded_total_cents`.

### 3.7. Handoff: Age and Cold-Chain Gates

A `StoreOps` operator hands off a staged, captured order, advancing `fulfillment_status` from `STAGED` to `HANDED_OFF`. Handoff requires the order to be `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`) and its `payment_status` to be `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`). Two further gates protect the handoff.

The age gate applies when the order's `requires_age_check` is true, meaning at least one `PICKED` or `SUBSTITUTED` line's effective product is `age_restricted`. In that case the order must have a `PASS` `AgeCheck` on record, or the handoff is refused with `ERR_AGE_VERIFICATION_REQUIRED`; and if the order's `AgeCheck` outcome is `FAIL`, the handoff is blocked with `ERR_AGE_VERIFICATION_FAILED`. An age verification is recorded by a `StoreOps` operator, who supplies the parent `order_id`, an opaque `verifier_user_id` identifying the person who performed the in-person ID check, and the `verified_birth_date` read from the presented government ID. The check's `outcome` is computed by the completed-birthday rule: take the reference date as the UTC date component of the parent order's fulfillment slot `window_start`, compute the whole completed years from `verified_birth_date` to that reference date, and record `PASS` when that age is at least 21 years — the legal minimum for the platform's age-restricted goods — and `FAIL` otherwise. The boundary is inclusive: a birth date that makes the customer exactly 21 years old on the reference date yields `PASS`.

The cold-chain gate applies when any `PICKED` or `SUBSTITUTED` line's product is `cold_chain`. Such an order may only be handed off before its staged-hold window expires — that is, while the current clock is strictly earlier than the order's `staged_at` plus the store's `cold_chain_hold_minutes` (the store-configured limit, two hours by default). A handoff attempted at or after that expiry instant is refused with `ERR_COLD_CHAIN_EXPIRED`.

The post-capture out-of-stock correction is the system's deepest cascade. A `Picker` or `StoreOps` operator may mark a line that is currently `PICKED` as `OUT_OF_STOCK` when the parent order is `STAGED` (otherwise `ERR_ORDER_NOT_STAGED`) and its payment is `CAPTURED` or `PARTIALLY_REFUNDED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`); a line that is not `PICKED` is rejected with `ERR_LINE_NOT_PICKED`. The correction reads the line's current `final_line_cents` — the amount that was captured for that line — as the refund amount, then sets the line's `final_line_cents` to 0. It creates a `Refund` whose `amount_cents` equals that captured amount, whose `order_id` and `order_line_id` point at the order and the out-of-stock line, and whose `reason` is `OUT_OF_STOCK`; refunds are append-only event records processed in creation order. It then increases the order's `refunded_total_cents` by the refunded amount (so `refunded_total_cents` is always the sum of `amount_cents` across the order's refund records) and recomputes the order's `final_total_cents` with the now-out-of-stock line contributing 0. Finally it cascades the payment dimension and the `net_captured_cents` as described next.

### 3.8. Refund Reconciliation and Cancellation

The payment dimension reconciles automatically as refunds accrue. The order's `net_captured_cents` is its `ebt_charged_cents` plus its `card_charged_cents` minus its `refunded_total_cents`. After a post-capture out-of-stock refund, the system moves `payment_status` from `CAPTURED` to `PARTIALLY_REFUNDED` while some captured value remains — that is, while `refunded_total_cents` is greater than 0 but still strictly less than the captured total `ebt_charged_cents` plus `card_charged_cents`, leaving `net_captured_cents` above 0 — and recomputes `net_captured_cents` accordingly. When `refunded_total_cents` reaches the full captured total `ebt_charged_cents` plus `card_charged_cents`, the order moves to `REFUNDED` and `net_captured_cents` becomes 0. These payment transitions are driven by the system as a consequence of recording the refund, not by a separate client request.

Cancellation unwinds an order. A `Customer` (on their own order) or a `StoreOps` operator cancels an order whose `fulfillment_status` is `PLACED`, `PICKING`, or `STAGED`; an order that is already `HANDED_OFF` cannot be cancelled and the attempt is rejected with `ERR_ORDER_ALREADY_HANDED_OFF`. Cancellation transitions `fulfillment_status` to `CANCELLED` and produces three cascading effects. First, every non-terminal line — every line still `PENDING`, `PICKED`, or `SUBSTITUTED` — is moved to `CANCELLED` and its `final_line_cents` is set to 0. Second, the booked slot is released: the slot's `booked_count` decreases by one and the slot's `version` increases by one, and if the slot was `FULL` it returns to `OPEN`. Third, payment is unwound according to where it stood: if `payment_status` was `CAPTURED` or `PARTIALLY_REFUNDED`, the payment moves to `REFUNDED` and `net_captured_cents` is set to 0; otherwise (payment still `AUTHORIZED`) the payment moves to `VOIDED`.

### 3.9. Discovering Payments, Refunds, and Age Checks

Capture records, refund events, and age verifications are all retrievable so that customers and operators can audit an order's financial and compliance history. Payment capture records may be listed and filtered by `order_id`, or fetched individually. Refund records may be listed and filtered by `order_id` or by `order_line_id`, or fetched individually, and read back in creation order they reconstruct the chronological refund history that drives the order's `refunded_total_cents`. Age checks may be listed and filtered by `order_id`, or fetched individually, exposing the recorded `verifier_user_id`, `verified_birth_date`, and computed `outcome`. For deterministic testing of the staged-hold window and the age reference date, a `PlatformAdmin` may drive the server's logical clock: an administrative test-driving capability sets the server's current UTC instant to a supplied `to_iso8601` value, and that clock is what the system reads when stamping `staged_at` and when evaluating the cold-chain expiry.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that retrieve a resource or drive a state transition or other modification return `200 OK`. The clock test-driving capability returns `200 OK` with no resource body. Every endpoint is mounted under the `/v1` prefix (the clock endpoint excepted), and the request and response bodies are reconstructed from the §3 narratives rather than tabulated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/stores` | Create a store | PlatformAdmin |
| GET | `/v1/stores` | List stores | PlatformAdmin, StoreOps, Customer, Picker |
| GET | `/v1/stores/{storeId}` | Get a store | PlatformAdmin, StoreOps, Customer, Picker |
| POST | `/v1/stores/{storeId}/close` | Close a store (blocks new orders) | PlatformAdmin |
| POST | `/v1/customers` | Create a customer | PlatformAdmin |
| GET | `/v1/customers` | List customers (filterable by email) | PlatformAdmin, StoreOps |
| GET | `/v1/customers/{customerId}` | Get a customer | PlatformAdmin, StoreOps, Customer |
| POST | `/v1/customers/{customerId}/suspend` | Suspend a customer (blocks new orders) | PlatformAdmin |
| POST | `/v1/customers/{customerId}/reinstate` | Reinstate a suspended customer | PlatformAdmin |
| POST | `/v1/pickers` | Create a picker bound to a store | PlatformAdmin, StoreOps |
| GET | `/v1/pickers` | List pickers (filterable by store_id) | PlatformAdmin, StoreOps, Picker |
| GET | `/v1/pickers/{pickerId}` | Get a picker | PlatformAdmin, StoreOps, Picker |
| POST | `/v1/products` | Create a product in a store catalog | PlatformAdmin, StoreOps |
| GET | `/v1/products` | List products (filterable by store_id, sku) | PlatformAdmin, StoreOps, Customer, Picker |
| GET | `/v1/products/{productId}` | Get a product | PlatformAdmin, StoreOps, Customer, Picker |
| POST | `/v1/products/{productId}/discontinue` | Discontinue a product | PlatformAdmin, StoreOps |
| POST | `/v1/slots` | Create a fulfillment slot | PlatformAdmin, StoreOps |
| GET | `/v1/slots` | List slots (filterable by store_id, slot_type) | PlatformAdmin, StoreOps, Customer |
| GET | `/v1/slots/{slotId}` | Get a slot | PlatformAdmin, StoreOps, Customer |
| POST | `/v1/slots/{slotId}/close` | Close a slot (blocks new placements) | PlatformAdmin, StoreOps |
| POST | `/v1/orders` | Place an order (books a slot under OCC, creates lines, computes estimated totals) | Customer, StoreOps |
| GET | `/v1/orders` | List orders (filterable by store_id, customer_id, slot_id, picker_id) | PlatformAdmin, StoreOps, Customer, Picker |
| GET | `/v1/orders/{orderId}` | Get an order | PlatformAdmin, StoreOps, Customer, Picker |
| POST | `/v1/orders/{orderId}/claim` | Picker claims an order for picking | Picker |
| POST | `/v1/orders/{orderId}/stage` | Stage a picked order | Picker |
| POST | `/v1/orders/{orderId}/capture` | Capture payment with split-tender allocation | StoreOps |
| POST | `/v1/orders/{orderId}/handoff` | Hand off a staged, captured order | StoreOps |
| POST | `/v1/orders/{orderId}/cancel` | Cancel an order | Customer, StoreOps |
| POST | `/v1/order-lines` | Add a line to a placed order (cart edit) | Customer, StoreOps |
| GET | `/v1/order-lines` | List order lines (filterable by order_id, product_id) | PlatformAdmin, StoreOps, Customer, Picker |
| GET | `/v1/order-lines/{lineId}` | Get an order line | PlatformAdmin, StoreOps, Customer, Picker |
| POST | `/v1/order-lines/{lineId}/pick` | Mark a line picked | Picker |
| POST | `/v1/order-lines/{lineId}/out-of-stock` | Mark a line out of stock | Picker, StoreOps |
| POST | `/v1/substitutions` | Propose a substitute product for a pending line | Picker |
| GET | `/v1/substitutions` | List substitutions (filterable by order_line_id, substitute_product_id) | PlatformAdmin, StoreOps, Customer, Picker |
| GET | `/v1/substitutions/{subId}` | Get a substitution | PlatformAdmin, StoreOps, Customer, Picker |
| POST | `/v1/substitutions/{subId}/accept` | Accept a proposed substitution | Customer, Picker |
| POST | `/v1/substitutions/{subId}/reject` | Reject a proposed substitution | Customer, Picker |
| GET | `/v1/payments` | List payment capture records (filterable by order_id) | PlatformAdmin, StoreOps, Customer |
| GET | `/v1/payments/{paymentId}` | Get a payment capture record | PlatformAdmin, StoreOps, Customer |
| GET | `/v1/refunds` | List refund records (filterable by order_id, order_line_id) | PlatformAdmin, StoreOps, Customer |
| GET | `/v1/refunds/{refundId}` | Get a refund record | PlatformAdmin, StoreOps, Customer |
| POST | `/v1/age-checks` | Record an in-person age verification | StoreOps |
| GET | `/v1/age-checks` | List age checks (filterable by order_id) | PlatformAdmin, StoreOps, Customer |
| GET | `/v1/age-checks/{ageCheckId}` | Get an age check | PlatformAdmin, StoreOps, Customer |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's deterministic current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_PICKER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSTITUTION_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_STORE_REFERENCE` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_STORE_CLOSED` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_PICKING` | 409 Conflict |
| `ERR_ORDER_NOT_STAGED` | 409 Conflict |
| `ERR_ORDER_ALREADY_HANDED_OFF` | 409 Conflict |
| `ERR_LINE_NOT_PENDING` | 409 Conflict |
| `ERR_LINE_NOT_PICKED` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_PROPOSED` | 409 Conflict |
| `ERR_SLOT_CLOSED` | 409 Conflict |
| `ERR_SLOT_VERSION_STALE` | 412 Precondition Failed |
| `ERR_SLOT_FULL` | 409 Conflict |
| `ERR_SLOT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PICKER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LINES_NOT_RESOLVED` | 409 Conflict |
| `ERR_NOTHING_TO_STAGE` | 409 Conflict |
| `ERR_INVALID_PICK_QUANTITY` | 400 Bad Request |
| `ERR_AGE_VERIFICATION_REQUIRED` | 403 Forbidden |
| `ERR_AGE_VERIFICATION_FAILED` | 403 Forbidden |
| `ERR_COLD_CHAIN_EXPIRED` | 409 Conflict |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_EBT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 409 Conflict |
| `ERR_SUBSTITUTION_PRICE_EXCEEDED` | 409 Conflict |
