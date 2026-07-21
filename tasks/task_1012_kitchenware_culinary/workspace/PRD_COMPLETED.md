# Kitchenware & Culinary Store API — Product Requirements Document

## 1. Introduction

The Kitchenware & Culinary Store platform powers the retail and experiential operations of a premium cookware chain in the spirit of a Williams-Sonoma flagship. Beyond a conventional catalog of cookware, knives, coffee equipment, appliances, and tabletop goods, the business blends merchandise sales with in-store experiences — hands-on cooking classes at demonstration stations, knife-sharpening and coffee-service bars, gift registries, and bespoke special orders. The API described here is the transactional backbone that unifies these threads: it must price an order for a loyalty member, reserve physical inventory across a store network, accrue and reverse reward points, honor returns within a policy window, and coordinate the scheduling of finite physical resources such as demo kitchens and service bars.

Two forces shape the design. First, money and points must reconcile exactly: an order priced provisionally at reservation time is re-priced definitively at fulfillment, points earned at one tier must be clawed back at the same tier on return, and a member's loyalty standing must track their trailing spend in real time. Second, the platform juggles parallel state — an order advances along an independent payment axis and fulfillment axis at once, and a special order cycles between staff quotes and member revision requests under optimistic concurrency control. This document specifies the entities, lifecycles, calculations, validations, and access rules that every implementation must honor precisely.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The platform recognizes exactly three roles: `PlatformAdmin`, `StoreAssociate`, and `Member`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The chain/HQ operator manages the catalog, stores, and the logical clock, and may perform every operational action as a superset of the other roles. The server may record the identifier but does not compare it to any entity's `id`.
- When `X-User-Role` is `StoreAssociate`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. Store staff create and fulfill orders, run classes and service tickets, approve or reject returns, issue special-order quotes, and enroll members. The server may record the identifier but does not compare it to any entity's `id`.
- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` entity. Ownership checks on any resource that references a `Member` compare that resource's member foreign-key field to `X-User-ID`.

Ownership matters wherever a `Member` acts in self-service. When the acting role is `Member`, the platform verifies that the member owns the resource being acted upon — that `X-User-ID` equals the resource's `member_id` (or, for a return, the owning order's `member_id`). A member acting on a resource they do not own is rejected with `ERR_FORBIDDEN_OWNERSHIP`. This ownership rule guards the following self-service operations: requesting a return, creating a class registration, cancelling a class registration, requesting a revision on a special order, accepting a special order, cancelling a special order, and redeeming points. Operators acting as `PlatformAdmin` or `StoreAssociate` are not subject to this per-member ownership check.

Validation across the API follows a fixed precedence, and the earliest failing check determines the response. Authentication of the headers is evaluated first (`ERR_UNAUTHENTICATED`, HTTP 401); then role authorization for the operation (`ERR_UNAUTHORIZED`, HTTP 403); then existence of every referenced resource — path identifiers and foreign-key body fields alike — validated left to right, each yielding its own not-found error at HTTP 404; then member ownership (`ERR_FORBIDDEN_OWNERSHIP`, HTTP 403); then optimistic-concurrency version matching (`ERR_STALE_VERSION`, HTTP 412); then state legality of the requested transition (HTTP 409); then time-window rules (HTTP 422); then capacity, overlap, and stock constraints (HTTP 409); and finally fiscal limits on refunds and redemptions (HTTP 422). Later sections attach concrete error identifiers to each of these layers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100 — a supplied `limit` that is non-integer or outside that inclusive range is rejected with `ERR_VALIDATION`. The `offset` parameter is the number of items to skip and defaults to 0; a supplied `offset` that is non-integer or negative is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list responses are sorted by the resource's creation timestamp, `created_at`, in ascending order; because many resources can share an identical `created_at` under a frozen logical clock, ties are broken deterministically by creation order (the order in which the server minted them).

List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in the system — stores, SKUs, members, orders, cooking classes, class registrations, service tickets, returns, special orders, and registries — carries a common set of server-managed properties:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at`: an ISO 8601 UTC timestamp with the same format, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It supports optimistic concurrency control where applicable.

Whenever a computed or derived field changes as a side effect of an operation — for example, a member's tier, an order's totals, or a SKU's available quantity — that change constitutes a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. The Server Logical Clock

All time-sensitive rules in the system — registration deadlines, return windows, the trailing spend window, and fulfillment timestamps — are evaluated against a server-maintained **logical clock**, never against wall-clock time. The `created_at` and `updated_at` stamps on every resource are likewise read from this logical clock (so a resource created or mutated while the clock is set to a given instant carries that instant), whereas the `api_request_timestamp` in the response envelope alone reflects the server's real wall-clock time. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any call is made it holds precisely this default and never falls back to real time. An administrative test-driving capability sets the clock to a supplied instant, provided in the `to_iso8601` field. Once set, subsequent time comparisons use the new value.

### 2.6. Nested Reference Validation and Ownership Ordering

Many operations reference other resources — an order names a `member_id` and a `store_id`, a return names an `order_id` and a target `line_id`, a registration names a `class_id` and a `member_id`. The existence of every referenced resource is validated before any business rule runs, and references are checked left to right. The first reference that resolves to nothing produces the corresponding not-found error: `ERR_STORE_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_SERVICE_TICKET_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`, `ERR_REGISTRY_NOT_FOUND`, or — when a return names a line that is absent from its order — `ERR_LINE_NOT_FOUND`. Only after all references resolve does the ownership check (§2.1) and then the business logic proceed. Malformed bodies, missing required fields, and invalid enum or type values are rejected up front with `ERR_VALIDATION`.

### 2.7. Monetary and Points Precision

All monetary amounts are integers denominated in cents, and all loyalty points are integers. Wherever a calculation produces a fractional cent or a fractional point — a percentage discount, a tax figure, or a points accrual — the result is rounded using the **round half up** method to a whole integer. Two rounding disciplines are pinned and must not be swapped:

- In tiered order pricing, the tier discount and the tax are each rounded half up to whole cents independently.
- In loyalty points accrual, rounding is applied **per line, before the lines are summed** — each line's point contribution is rounded to a whole number and only then are the per-line results added together. Summing raw fractional contributions and rounding once at the end is incorrect and would produce different totals.

### 2.8. Inventory Invariants

Each SKU tracks three quantities that must stay mutually consistent at all times. The `on_hand_qty` is the physical count of units held across the store network. The `reserved_qty` is a derived figure: the sum of the quantities of all order lines that are currently in the `RESERVED` line state and reference this SKU, across every order. The `available_qty` is derived as the on-hand count minus the reserved count, floored at zero so it is never negative. The governing invariant is that available quantity plus reserved quantity always equals on-hand quantity. On-hand quantity changes only in two situations: it decreases by the fulfilled quantity when order lines are fulfilled, and it increases by the returned quantity when a return is approved and the goods are restocked. Reservations rise when an order is created and fall when lines are voided at cancellation or fulfillment.

### 2.9. Loyalty Standing and Tier Reconciliation

A member's loyalty tier is a derived reflection of their trailing spend and is never set directly. The `annual_spend_cents` figure is the sum, over the member's orders whose `fulfillment_status` is `FULFILLED` and whose `fulfilled_at` falls within the trailing spend window ending at the current logical clock, of that order's fulfilled-line gross less the gross of any approved returns against that order. The window spans the most recent 365 days. This figure is maintained incrementally — it increases by fulfilled-line gross at fulfillment and decreases by returned-line gross when a return is approved — and it is never allowed to fall below zero.

Whenever annual spend changes, the tier is recomputed against two thresholds: a member whose annual spend is at least 150,000 cents is `GOLD`; a member whose annual spend is at least 50,000 cents but below the gold threshold is `SILVER`; any member below the silver threshold is `STANDARD`. Both boundaries are inclusive at the lower edge — spend exactly equal to a threshold lands in the higher tier. Because a return can reduce spend, an approved return may downgrade a member's tier as a downstream consequence.

### 2.10. Cascading State Propagation

Several operations mutate more than one resource in a single logical step, and every secondary effect is part of the contract. Cancelling an order voids each of its reserved lines and, because those lines become void, releases the reservations they held back to the referenced SKUs. Cancelling a cooking class cancels each of its still-booked registrations. Approving a return marks the target line returned, and that single change ripples outward: it reverses the member's annual spend and earned points, which in turn triggers a tier recomputation that may downgrade the member, while also restocking the SKU. Each affected resource is independently mutated — its `updated_at` refreshed and its `version` incremented — as part of the operation.

Each lifecycle transition is legal only from the states its workflow names. Where a more specific state error is not called out for a transition, an attempt to drive a resource from a state that does not permit the requested transition — for example, opening a class that is not `DRAFT`, completing a ticket that is not `SCHEDULED`, requesting a revision on a special order that is not `QUOTED`, or accepting one that is not `QUOTED` — is rejected with `ERR_INVALID_STATE`.

### 2.11. Optimistic Concurrency Control

Special-order quoting is guarded by optimistic concurrency control to prevent a stale quote from silently overwriting a newer one. A `POST /special-orders/{id}/quote` request must carry the field `expected_special_order_version`, holding the client's last observed `version` of the target special order. If that value does not match the special order's current `version` — because a prior quote or a member's revision request has already advanced the version since the client last read it — the request is rejected with `ERR_STALE_VERSION` at HTTP 412, and the newer quote is preserved. This is the only endpoint that takes a version field; every other mutation in the system proceeds without an expected-version input.

## 3. Business Logic & Workflows

### 3.1. Catalog: Stores, SKUs, and Bundles

The catalog rests on two administrator-owned foundations. A store is created with a display `name`, a `state_code` that fixes its tax jurisdiction — one of `CA`, `OR`, or `NY` — and an optional operational `status` that defaults to `OPEN` and may otherwise be `CLOSED`. A store's operational status later gates order fulfillment.

Merchandise is modeled as SKUs. A SKU is created with a `name`, a `category` drawn from `COOKWARE`, `KNIVES`, `COFFEE`, `APPLIANCE`, or `TABLETOP`, a `list_price_cents` unit price that must be zero or greater, and an `on_hand_qty` count of units held. On creation the reserved quantity begins at zero, the available quantity equals the on-hand quantity, and the catalog `status` defaults to `ACTIVE`, the alternative being `DISCONTINUED`. A SKU may instead be a gift bundle when `is_bundle` is set true; a bundle carries a `component_sku_ids` array listing its component SKU identifiers (recorded as given and not foreign-key checked, validated only at creation) and a fixed `bundle_price_cents`. For ordinary non-bundle SKUs, `is_bundle` defaults to false, `component_sku_ids` defaults to an empty array, and `bundle_price_cents` is null. When an order line references a bundle SKU, its unit price is taken from the bundle price; otherwise the unit price is the SKU's list price. The derived `reserved_qty` and `available_qty` behave as described under the inventory invariants.

### 3.2. Loyalty Members, Points Wallet, and Redemption

A member is enrolled with a unique `email`, a `full_name`, and a `home_store_id` naming their home store. Enrollment sets the member up at the entry tier: `tier` is `STANDARD`, `annual_spend_cents` is zero, `pending_points` is zero, `earned_points` is zero, and `wallet_credit_cents` is zero. The `tier` and `annual_spend_cents` fields are derived and evolve only through the fulfillment and return flows described elsewhere. Members can be listed and optionally narrowed by `home_store_id`.

A member accumulates loyalty points in two buckets. The `pending_points` bucket holds provisional points from orders that are reserved but not yet fulfilled; the `earned_points` bucket holds posted points from fulfilled orders, net of any reversals from approved returns. Separately, `wallet_credit_cents` is a store-credit balance in cents. A member may redeem earned points for wallet credit at a rate of one point per one cent by supplying a positive integer `points` amount (a `points` value below 1 is rejected up front with `ERR_VALIDATION`). Redemption requires that the requested points not exceed the member's earned-points balance; a request for more than is available is rejected with `ERR_INSUFFICIENT_POINTS`. On a valid redemption, the earned-points balance decreases by the redeemed points and the wallet-credit balance increases by the same number of cents. A member may redeem only their own points; a store associate may also perform the redemption.

### 3.3. The Order Lifecycle: Reservation, Payment, Fulfillment, Cancellation

An order occupies two independent state axes at once. Its payment dimension, `payment_status`, moves among `UNPAID`, `PAID`, and `REFUNDED`; its fulfillment dimension, `fulfillment_status`, moves among `RESERVED`, `FULFILLED`, and `CANCELED`. The two axes evolve on separate transitions, and an order is terminal once fulfillment reaches `FULFILLED` or `CANCELED`.

**Creating an order.** A store associate opens an order by naming the purchasing `member_id`, the fulfilling `store_id`, a `fulfillment_type` of `BOPIS`, `SHIP_FROM_STORE`, or `IN_STORE`, and a `lines` array. Each supplied line names a `sku_id`, a `qty`, and an optional `is_gift` flag; the server mints each line's `line_id`, sets each line's `unit_price_cents`, and sets each line's `line_status`. Two preconditions guard creation, and they are evaluated in that order: every referenced SKU must exist and be `ACTIVE`, or the order is rejected with `ERR_DISCONTINUED_SKU`; and for each line the SKU's available quantity must be at least the requested quantity, or the order is rejected with `ERR_INSUFFICIENT_STOCK`. When several lines reference the same SKU, availability is judged cumulatively — the lines are walked left to right and each line's quantity is added to the running total already claimed for that SKU, so the check fails as soon as that running total exceeds the SKU's available quantity. On success, every line is set to `RESERVED` line status and priced from its SKU — a bundle line at the bundle price, an ordinary line at the list price. Each referenced SKU's reserved quantity rises by the line quantity and its available quantity is recomputed. The order snapshots the member's current tier into `tier_at_pricing`, which thereafter drives both the discount and the points multiplier for this order. The system then computes the provisional pricing over all lines and the provisional points, and adds the order's pending points to the member's pending-points balance. The order begins at `UNPAID` payment status and `RESERVED` fulfillment status.

**Provisional pricing at creation.** The order's `subtotal_cents` is the sum, over every line, of that line's unit price multiplied by its quantity. The tier discount percentage is 0% for a `STANDARD` order, 5% for a `SILVER` order, and 10% for a `GOLD` order, keyed off the order's snapshotted tier. The `tier_discount_cents` is that percentage of the subtotal, rounded half up to whole cents, then capped so it never exceeds 20,000 cents. The taxable base is the subtotal less the tier discount. The tax rate is determined by the fulfilling store's jurisdiction: 8.75% for `CA`, 0% for `OR`, and 8% for `NY`. The `tax_cents` is the tax rate applied to the taxable base, rounded half up to whole cents. The `total_cents` is the subtotal minus the tier discount plus the tax. These figures are provisional because they cover every ordered line, some of which may later be excluded at fulfillment.

**Provisional points at creation.** The points multiplier is 1.00 for a `STANDARD` order, 1.25 for a `SILVER` order, and 1.50 for a `GOLD` order, again keyed off the snapshotted tier. For each line, the point contribution is the line's unit price times its quantity, divided by 100, multiplied by the tier multiplier, rounded half up to a whole number. The order's `pending_points` is the sum of these per-line contributions, rounded per line before summation as described in §2.7. At creation the order's `earned_points` is zero and remains so until fulfillment.

**Paying an order.** Payment moves an order from `UNPAID` to `PAID`. Payment is permitted only while fulfillment status is `RESERVED` and payment status is still `UNPAID`; an attempt to pay an order that is already `PAID`/`REFUNDED` or no longer `RESERVED` is rejected with `ERR_INVALID_STATE`.

**Fulfilling an order.** Fulfillment advances the order from `RESERVED` to `FULFILLED`. Two preconditions apply: the order's payment status must be `PAID`, or the request is rejected with `ERR_PAYMENT_REQUIRED`; and the fulfilling store must be `OPEN`, or the request is rejected with `ERR_STORE_CLOSED`. A store associate may optionally supply an `exclude_line_ids` list of lines to drop — for instance, lines that turned out to be out of stock. Each excluded line is set to `VOID` line status and its reservation is released back to its SKU (reserved quantity decreases by that line's quantity) without any sale occurring. Every remaining reserved line is set to `FULFILLED` line status, and for each such line the referenced SKU's on-hand quantity and reserved quantity both decrease by the line's quantity. The order's subtotal, tax, and total are then recomputed in their final form, but this time over the fulfilled lines only, so void lines drop out and the final subtotal, tax, and total generally differ from the provisional figures. The earned points are computed over the fulfilled lines using the same per-line, round-then-sum discipline and the order's snapshotted tier multiplier; the order's earned points are added to the member's earned-points balance, and the order's pending points are subtracted from the member's pending-points balance. The gross of the fulfilled lines is added to the member's annual spend **before** the tier is recomputed, and only then is the member's tier recomputed against the spend thresholds. Finally, `fulfilled_at` is stamped with the current logical clock and the fulfillment status becomes `FULFILLED`.

**Cancelling an order.** Cancellation is permitted only while fulfillment status is `RESERVED` and not yet fulfilled, and it advances fulfillment to `CANCELED`. The cancellation cascades: every reserved line becomes `VOID`, and because each line becomes void, the reservation it held is released — the referenced SKU's reserved quantity decreases by that line's quantity and its available quantity is recomputed. The order's pending points are subtracted from the member's pending-points balance. If the order had already been paid, the full total is refunded to the member's wallet-credit balance, the order's `refunded_cents` increases by the total, and the payment status becomes `REFUNDED`. Orders can be listed and optionally filtered by `member_id` and/or `store_id`.

### 3.4. Returns and Refunds

A return targets a single fulfilled line of a fulfilled order. A member (or a store associate acting on their behalf) requests a return by naming the `order_id`, the returning `member_id`, the target `line_id`, a `return_qty`, a `reason` of `DEFECTIVE`, `UNWANTED`, or `WRONG_ITEM`, and a `refund_destination` of either `ORIGINAL` or `WALLET`. Three preconditions guard the request: the order's fulfillment status must be `FULFILLED`, or the request is rejected with `ERR_ORDER_NOT_FULFILLED`; the current logical clock must be no later than the order's fulfillment timestamp plus the return window of 30 days, or the request is rejected with `ERR_RETURN_WINDOW_EXPIRED`; and the target line must exist (else `ERR_LINE_NOT_FOUND`) with a fulfilled line status — a line that is not `FULFILLED` is rejected with `ERR_INVALID_STATE` — while the return quantity lies between 1 and the line's own quantity inclusive, a `return_qty` below 1 or above the line's quantity being rejected with `ERR_VALIDATION`. A newly requested return begins in `REQUESTED` status, with the refund amount and points reversal deferred until approval.

Approval of a return is performed by a store associate and drives it from `REQUESTED` to `APPROVED`. Two preconditions apply: the target line must be fulfilled and not already returned, or the request is rejected with `ERR_LINE_ALREADY_RETURNED`; and the computed refund must not exceed the order's paid amount not yet refunded — concretely, the order's `total_cents` less the sum of `refund_amount_cents` across every already-`APPROVED` return on that order (regardless of each return's refund destination) — or the request is rejected with `ERR_REFUND_EXCEEDS_PAID`. The `refund_amount_cents` is the target line's unit price multiplied by the returned quantity — the line gross, with no re-proration of any order-level discount. The `points_reversed` is that same line gross, divided by 100, multiplied by the order's snapshotted tier multiplier (1.00 for `STANDARD`, 1.25 for `SILVER`, 1.50 for `GOLD`), rounded half up to a whole number; using the order's original tier snapshot guarantees that points earned and points reversed use the same multiplier. Approval then triggers the full cascade: the target line becomes `RETURNED`; because the line is returned, the member's annual spend decreases by the returned line gross (floored at zero, never negative) and the member's earned points decrease by the points reversed (likewise floored at zero); the spend reduction triggers a tier recomputation that may downgrade the member; and the returned line restocks its SKU, raising the SKU's on-hand quantity by the returned quantity. The refund is then delivered according to its destination: a `WALLET` refund adds the refund amount to the member's wallet-credit balance, while an `ORIGINAL` refund adds it to the order's `refunded_cents`. The return then rests at `APPROVED`.

Alternatively, a store associate may reject a still-requested return, moving it from `REQUESTED` to `REJECTED`. A rejection posts no refund, reverses no points, and triggers no cascade. Returns can be listed and optionally filtered by `order_id` and `member_id`.

### 3.5. Cooking Classes and Registrations

Cooking classes occupy finite demonstration stations and progress through `DRAFT`, `OPEN`, `COMPLETED`, and `CANCELED`. A store associate schedules a class with a hosting `store_id`, a `title`, a `station` of either `DEMO_KITCHEN` or `HEARTH_BAR`, a `start_at` (inclusive) and `end_at` (exclusive) that must satisfy end strictly after start, a `capacity` of at least one booked registration, and a per-seat `price_cents`. The station is a physical resource that cannot host two classes at once: if any other non-canceled class at the same store and station has a time interval that overlaps the proposed one, the request is rejected with `ERR_CLASS_STATION_CONFLICT`. Overlap is judged on half-open intervals, so a class that starts exactly when another ends does not conflict. A newly scheduled class begins in `DRAFT` with a `registered_count` of zero. Opening a class advances it from `DRAFT` to `OPEN`, after which registrations are accepted. Completing a class advances it from `OPEN` to `COMPLETED`. Cancelling a class is permitted while it is `DRAFT` or `OPEN`: every still-booked registration on the class is moved to `CANCELED`, and the class itself becomes `CANCELED`. A class's registered count is always the number of registrations on it that are currently in `BOOKED` status. Classes can be listed and optionally filtered by `store_id`.

A registration ties a member to a class and progresses through `BOOKED`, `ATTENDED`, `NO_SHOW`, and `CANCELED`. A member (or staff on their behalf) registers by naming the `class_id`, the `member_id`, and optionally an `order_id` linking a purchase; the linked order defaults to null when the member books directly. Three preconditions guard registration: the class must be `OPEN`, or the request is rejected with `ERR_CLASS_NOT_OPEN`; the current logical clock must be strictly before the class's start time, or the request is rejected with `ERR_REGISTRATION_CLOSED`; and the class's registered count must be strictly below its capacity, or the request is rejected with `ERR_CLASS_FULL`. On success the registration snapshots the class's per-seat price into `seat_price_cents`, enters `BOOKED` status, and the class's registered count is recomputed. A store associate marks attendance by supplying an `attended` flag: a true value moves the registration from `BOOKED` to `ATTENDED`, while a false value moves it to `NO_SHOW`; either way the class's registered count is recomputed. A member may cancel their own booked registration, moving it from `BOOKED` to `CANCELED` and freeing the seat, which likewise recomputes the class's registered count. Registrations can be listed and optionally filtered by `class_id`, `member_id`, and `order_id`.

### 3.6. Knife and Coffee Service Appointments

The service bars offer knife sharpening and coffee service by appointment. A service ticket is booked with a servicing `store_id`, a `service_type` of `KNIFE_SHARPENING` or `COFFEE_SERVICE`, a `start_at` and an `end_at` with end strictly after start, a `price_cents`, and an optional owning `member_id` that defaults to null for a walk-in. A service resource cannot be double-booked or crowded: if any other non-canceled ticket at the same store and service type falls within the service buffer of the proposed interval, the request is rejected with `ERR_SERVICE_SLOT_CONFLICT`. The buffer is applied as a padding on both ends of the closed appointment interval, spanning 30 buffer minutes on each side. The padded boundary is treated as strictly interior: a ticket booked exactly the buffer apart — so that the gap between the two appointment intervals is exactly 30 minutes — merely touches the padded boundary without overlapping it and is accepted, whereas a ticket whose gap is strictly less than 30 minutes (including a back-to-back booking with no gap) falls within the buffer and is rejected. A booked ticket begins `SCHEDULED`, and its lifecycle runs to `COMPLETED` or `CANCELED`. Completing a ticket moves it from `SCHEDULED` to `COMPLETED`. A member may cancel their own scheduled ticket, moving it from `SCHEDULED` to `CANCELED`. Service tickets can be listed and optionally filtered by `store_id` and `member_id`.

### 3.7. Special Orders and the Quote–Revision Cycle

Special orders capture bespoke or custom requests and follow a cyclic lifecycle through `DRAFT`, `QUOTED`, `REVISION_REQUESTED`, `ACCEPTED`, and `CANCELED`, with acceptance and cancellation terminal. A member opens a request by naming the requesting `member_id`, the fulfilling `store_id`, a free-text `description` of the custom item, and an `estimated_cost_cents` budget. A new request begins in `DRAFT` with `quote_revision` at zero and `version` at one; `quoted_total_cents`, `deposit_cents`, and the staff quote are not yet populated.

A store associate issues a quote, which moves a `DRAFT` request to `QUOTED`. The quote carries the required `expected_special_order_version` for the concurrency check described in §2.11, a `quoted_total_cents`, and an optional `deposit_cents`. On a successful quote, the quoted total and deposit are recorded — the `deposit_cents` field taking the supplied value, or null when the request omits it — the `quote_revision` counter increases by one, the version increments by one, and the status becomes `QUOTED`. From `QUOTED`, the member may request a revision, which moves the request to `REVISION_REQUESTED` and increments the version by one. A store associate then re-quotes the revision-requested order — the heart of the cycle — which returns it from `REVISION_REQUESTED` back to `QUOTED`: the quoted total and deposit are updated — the deposit again taken from the request, or reset to null when omitted, rather than retaining the prior deposit — the quote revision counter again increases by one, and the version again increments by one. This re-quote is likewise guarded by the expected-version concurrency check. From `QUOTED`, the member may instead accept, which moves the request to the terminal `ACCEPTED` state and increments the version. At any non-accepted point — from `DRAFT`, `QUOTED`, or `REVISION_REQUESTED` — the member may cancel, provided the request is not already accepted, which moves it to the terminal `CANCELED` state and increments the version. The only state that blocks cancellation is `ACCEPTED` (rejected with `ERR_INVALID_STATE`); a cancel issued against an already-`CANCELED` request is not treated as an error but simply re-applies the terminal `CANCELED` state and increments the version. Special orders can be listed and optionally filtered by `member_id` and `store_id`.

### 3.8. Gift Registries

A gift registry lets a member curate a wish list for an occasion. A registry is created with the owning `member_id`, an `event_type` of `WEDDING`, `HOUSEWARMING`, or `BIRTHDAY`, an `event_date`, and an optional `items` array in which each entry names a `sku_id` (recorded as given and not foreign-key checked) and a `desired_qty` (which must be at least 1). Registries are created in `ACTIVE` status — the only status this version supports, with no close lifecycle — and each item's `purchased_qty` is server-maintained, starting at zero. Recording a gift purchase against a registry supplies a `sku_id` and a `qty`; the matching item's purchased quantity increases by that quantity, capped so it never exceeds the item's desired quantity. If the supplied `sku_id` matches no item on the registry, the purchase is rejected with `ERR_VALIDATION`. Registries can be listed and optionally filtered by `member_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and actions that adjust an internal collection — return `200 OK`. Read operations return `200 OK`. The complete request and response semantics for each endpoint are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/stores` | Create a store | PlatformAdmin |
| GET | `/stores/{id}` | Get a store | PlatformAdmin, StoreAssociate, Member |
| POST | `/skus` | Create a SKU or bundle | PlatformAdmin |
| GET | `/skus/{id}` | Get a SKU | PlatformAdmin, StoreAssociate, Member |
| POST | `/members` | Enroll a loyalty member | PlatformAdmin, StoreAssociate |
| GET | `/members/{id}` | Get a member | PlatformAdmin, StoreAssociate, Member |
| GET | `/members` | List members, optionally by home store | PlatformAdmin, StoreAssociate |
| POST | `/members/{id}/redeem` | Redeem earned points for wallet credit | Member, StoreAssociate |
| POST | `/orders` | Create an order | StoreAssociate, PlatformAdmin |
| GET | `/orders/{id}` | Get an order | PlatformAdmin, StoreAssociate, Member |
| GET | `/orders` | List orders, optionally by member and/or store | PlatformAdmin, StoreAssociate |
| POST | `/orders/{id}/pay` | Mark an order paid | StoreAssociate, PlatformAdmin |
| POST | `/orders/{id}/fulfill` | Fulfill an order | StoreAssociate, PlatformAdmin |
| POST | `/orders/{id}/cancel` | Cancel an unfulfilled order | StoreAssociate, PlatformAdmin |
| POST | `/cooking-classes` | Schedule a cooking class | StoreAssociate, PlatformAdmin |
| GET | `/cooking-classes/{id}` | Get a cooking class | PlatformAdmin, StoreAssociate, Member |
| GET | `/cooking-classes` | List cooking classes, optionally by store | PlatformAdmin, StoreAssociate, Member |
| POST | `/cooking-classes/{id}/open` | Open a class for registration | StoreAssociate, PlatformAdmin |
| POST | `/cooking-classes/{id}/complete` | Complete a class | StoreAssociate, PlatformAdmin |
| POST | `/cooking-classes/{id}/cancel` | Cancel a class | StoreAssociate, PlatformAdmin |
| POST | `/class-registrations` | Register a member for a class | Member, StoreAssociate, PlatformAdmin |
| GET | `/class-registrations/{id}` | Get a registration | PlatformAdmin, StoreAssociate, Member |
| GET | `/class-registrations` | List registrations, optionally by class/member/order | PlatformAdmin, StoreAssociate, Member |
| POST | `/class-registrations/{id}/mark-attendance` | Mark a registration attended or no-show | StoreAssociate, PlatformAdmin |
| POST | `/class-registrations/{id}/cancel` | Cancel a booked registration | Member, StoreAssociate, PlatformAdmin |
| POST | `/service-tickets` | Book a service appointment | Member, StoreAssociate, PlatformAdmin |
| GET | `/service-tickets/{id}` | Get a service ticket | PlatformAdmin, StoreAssociate, Member |
| GET | `/service-tickets` | List service tickets, optionally by store/member | PlatformAdmin, StoreAssociate, Member |
| POST | `/service-tickets/{id}/complete` | Complete a service ticket | StoreAssociate, PlatformAdmin |
| POST | `/service-tickets/{id}/cancel` | Cancel a service ticket | Member, StoreAssociate, PlatformAdmin |
| POST | `/returns` | Request a return against a fulfilled line | Member, StoreAssociate, PlatformAdmin |
| GET | `/returns/{id}` | Get a return | PlatformAdmin, StoreAssociate, Member |
| GET | `/returns` | List returns, optionally by order/member | PlatformAdmin, StoreAssociate, Member |
| POST | `/returns/{id}/approve` | Approve a return | StoreAssociate, PlatformAdmin |
| POST | `/returns/{id}/reject` | Reject a return | StoreAssociate, PlatformAdmin |
| POST | `/special-orders` | Open a special-order request | Member, StoreAssociate, PlatformAdmin |
| GET | `/special-orders/{id}` | Get a special order | PlatformAdmin, StoreAssociate, Member |
| GET | `/special-orders` | List special orders, optionally by member/store | PlatformAdmin, StoreAssociate, Member |
| POST | `/special-orders/{id}/quote` | Issue or re-issue a quote | StoreAssociate, PlatformAdmin |
| POST | `/special-orders/{id}/request-revision` | Request a revised quote | Member, StoreAssociate, PlatformAdmin |
| POST | `/special-orders/{id}/accept` | Accept the current quote | Member, StoreAssociate, PlatformAdmin |
| POST | `/special-orders/{id}/cancel` | Cancel a non-accepted special order | Member, StoreAssociate, PlatformAdmin |
| POST | `/registries` | Create a gift registry | Member, StoreAssociate, PlatformAdmin |
| GET | `/registries/{id}` | Get a registry | PlatformAdmin, StoreAssociate, Member |
| GET | `/registries` | List registries, optionally by member | PlatformAdmin, StoreAssociate, Member |
| POST | `/registries/{id}/purchase` | Record a gift purchase against a registry item | Member, StoreAssociate, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_STORE_NOT_FOUND` | 404 |
| `ERR_SKU_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_CLASS_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_SERVICE_TICKET_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_REGISTRY_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_FULFILLED` | 409 |
| `ERR_STORE_CLOSED` | 409 |
| `ERR_PAYMENT_REQUIRED` | 409 |
| `ERR_CLASS_NOT_OPEN` | 409 |
| `ERR_LINE_ALREADY_RETURNED` | 409 |
| `ERR_DISCONTINUED_SKU` | 409 |
| `ERR_REGISTRATION_CLOSED` | 422 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_CLASS_FULL` | 409 |
| `ERR_CLASS_STATION_CONFLICT` | 409 |
| `ERR_SERVICE_SLOT_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_REFUND_EXCEEDS_PAID` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
