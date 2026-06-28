# Trading Card Store API — Product Requirements Document

## 1. Introduction

This document specifies the back-office and storefront API for a Trading Card & Hobby Game Store — a business whose operational surface is unusually wide for its size. A single shop runs a singles-and-sealed inventory with per-card condition grading, buys cards back from the public against either cash or store credit, runs sanctioned organized-play tournaments with cyclic pairing rounds and WPN-style standings, takes pre-orders against limited release allocations, intakes raw cards for third-party grading, and brokers consignment sales on behalf of customers. Every one of these activities touches the same two ledgers — a customer's store-credit balance and their lifetime spend — and the same physical inventory counts, so the system's chief job is keeping money and units reconciled while many independent workflows mutate them.

The API is built around a small number of operational roles and one customer-facing role, with store credit acting as the universal settlement instrument that ties the lifecycles together: a buylist payout becomes credit a customer can spend on an event entry, an event refund returns credit, a consignment sale pays out credit, and a pre-order deposit draws it down. Because allocation pools, event capacity, and play-table counts are all scarce, the system must enforce hard quota and overlap constraints, reject stale writes against concurrently-edited release products, and unwind side effects exactly when a workflow is voided or cancelled. The sections below define the global contract (authentication, response envelope, pagination, money and consistency rules) and then the business workflows in detail.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Where a rule below references a calculation, threshold, or state transition, the precise business meaning is developed further in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the principal's operational capacity. If either header is missing, or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation — or a customer attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `Customer`, `StoreManager`, and `JudgeStaff`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. This role is entity-backed: ownership checks on any resource that references a customer compare the resource's customer foreign key (for example, the `customer_id` carried by a buylist submission, registration, pre-order, consignment case, grading submission, or ledger row) to `X-User-ID`. A customer may read and act only on resources whose customer reference equals their own `X-User-ID`; an attempt to read or mutate another customer's resource is an `ERR_UNAUTHORIZED` failure.

When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The store manager is the operational superset over store operations — catalog management, buylist acceptance, pre-order allocation and fulfillment, grading intake and lifecycle, consignment settlement, the customer lifecycle, the event lifecycle around scheduling and cancellation, and the logical clock — and the server does not compare its `X-User-ID` to any entity's `id`. Likewise, when `X-User-Role` is `JudgeStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; judge staff run the tournament floor (starting events, advancing and completing rounds, creating pairings, and reporting results) and the server records but does not own-check this identifier against any entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. The one documented departure from this default is the WPN standings report, whose ordering is described in Section 3.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Topology and Nested Path Validation

The catalog is flat: customers, inventory items, buylist submissions and lines, release products, pre-orders, events, registrations, pairings, grading submissions, consignment cases, and store-credit ledger rows are all peer collections addressed at the root. Relationships between them are expressed through foreign-key fields carried in request bodies, not through nested ownership URLs.

A handful of read endpoints expose a resource's children by walking back through a foreign key (for example, listing the registrations, the ledger rows, or the pairings that reference a given parent). For any request whose path contains more than one identifier, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource, before evaluating any deeper identifier or applying business rules. Foreign-key references supplied in a request body are validated the same way: every referenced resource must exist, or the request fails with `ERR_NOT_FOUND`.

### 2.5. Common Resource Properties

Most entities carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — a system-managed integer that starts at its initial value on creation and increments by one on every mutation. It is the basis for the optimistic concurrency mechanism described in Section 2.7.

The single exception is the store-credit ledger, which is an append-only event log. A ledger row carries only `id` and `created_at`; it has no `updated_at` and no `version`, because rows are never modified after they are written. All other entities — customers, inventory items, buylist submissions, buylist lines, release products, pre-orders, events, registrations, pairings, grading submissions, and consignment cases — carry the full set of four common fields.

Whenever the system recomputes a derived field on an entity (a customer's balance or tier, an event's seated count or current round, a release product's allocation count, and so on), that recomputation is itself a mutation: it refreshes the entity's `updated_at` and increments its `version`.

### 2.6. Monetary Values, Rounding, and Integer Counts

All money in this system is expressed in integer cents; there are no fractional-cent values stored or returned. Where a calculation multiplies a cent amount by a rate or a basis-point fraction and the result is not a whole number of cents, the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The precise point in each formula at which rounding is applied is load-bearing and is specified per calculation in Section 3; in particular, several formulas round an intermediate per-line or per-unit amount before a later sum or multiplication, and reordering those steps would produce a different total.

Quantity, count, point-score, and round-index fields are integers. A customer's `store_credit_balance_cents` is never permitted to be negative, and several inventory counts are bounded (a reserved count never exceeds the on-hand count, an allocation count never exceeds its pool, a seated count never exceeds capacity); the workflows that maintain these invariants and the errors that guard them appear in Section 3.

### 2.7. Optimistic Concurrency on Release Allocation

Allocating units to a pre-order is guarded by optimistic concurrency control against the parent release product's `version`. A request to allocate a pre-order must carry `expected_release_product_version`, a non-optional field whose value is the `version` of the target `ReleaseProduct` that the client last observed. If that value does not equal the release product's current `version` — which happens when another writer has allocated against the same release product since the client last read it, advancing its version — the allocation is rejected with `ERR_STALE_VERSION` (HTTP 412). The intent is that a prior allocation has already drawn down the shared allocation pool, so the current writer's view of remaining capacity is stale and must be refreshed before re-allocating. This is the only endpoint that takes a version field; no other write requires or accepts one.

### 2.8. Store Credit as the Settlement Ledger

Store credit is the system's single settlement instrument, and a customer's balance is never stored as a free-standing mutable number. Instead, every movement of credit appends one row to the append-only store-credit ledger, and the balance is always the running sum of that customer's rows. Each ledger row records the owning `customer_id`, a signed `delta_cents` (positive for credit granted, negative for credit drawn down), a `reason` drawn from the set `BUYLIST_PAYOUT`, `EVENT_REFUND`, `CONSIGNMENT_PAYOUT`, `PREORDER_DEPOSIT`, `EVENT_CHARGE`, `PREORDER_FULFILL`, and `MANUAL_ADJUSTMENT`, and an optional `source_entity_id` naming the entity that produced the row for audit purposes. Whenever a row is appended, the owning customer's `store_credit_balance_cents` is recomputed as the sum of `delta_cents` across all of that customer's rows, taken in creation order, and the customer's `updated_at` and `version` advance accordingly. The detailed rules for which workflow appends which `reason`, and for the lifetime-spend and loyalty-tier figures derived from these rows, are developed in Section 3.

### 2.9. Validation Ordering

When several validation conditions apply to one operation, they are evaluated in a fixed priority order so that the same input always produces the same error. Authentication is checked first: a request lacking valid headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is checked next — role permission and, for a customer, ownership of the target — failing with `ERR_UNAUTHORIZED`. The system then confirms that every path identifier and every foreign-key-referenced resource exists, failing with `ERR_NOT_FOUND`. Only then does it check that the target resource is in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE` (HTTP 409); for check-in specifically, the customer-banned check (`ERR_CUSTOMER_BANNED`, HTTP 409) is applied as part of this state stage. After state, the request body is validated for required, well-typed, valid-enum fields, failing with `ERR_INVALID_REQUEST` (HTTP 400); quantity-minimum checks then fail with `ERR_INVALID_QUANTITY` (HTTP 422), and the grade-range check fails with `ERR_INVALID_GRADE` (HTTP 422). The remaining business constraints — schedule conflict, venue overlap, empty buylist, reserved-inventory protection, allocation overflow, event capacity, the stale-version OCC check, and the insufficient-credit check — are applied after the foregoing, each carrying its own error as listed in Section 5. In short: authentication, then authorization, then existence, then state (including the banned check for check-in), then request well-formedness, then quantity and grade bounds, then the domain-specific business constraints.

## 3. Business Logic & Workflows

### 3.1. Customers, Store Credit, and the Loyalty Ladder

A store manager onboards a new patron by supplying a `display_name` and an `email`; the email is unique across customers. A newly created customer starts with `store_credit_balance_cents` of 0, `lifetime_spend_cents` of 0, a `loyalty_tier` of `BRONZE`, and a `status` of `ACTIVE`. Because store credit is the only way to pay for anything, a store manager seeds a customer's wallet by recording a credit adjustment, which appends a ledger row with `reason` `MANUAL_ADJUSTMENT` and a signed `delta_cents`, then recomputes the balance. A customer (or a store manager) may read a customer's own ledger rows and registrations through the reverse-lookup list endpoints.

A customer's `lifetime_spend_cents` is a narrower figure than the balance: it is the sum of the negated `delta_cents` of only those ledger rows whose `reason` is `EVENT_CHARGE` or `PREORDER_FULFILL` — the two true purchase debits. Deposits, refunds, buylist and consignment payouts, and manual adjustments never move lifetime spend; only money actually spent on event entry and pre-order fulfillment counts. Each time lifetime spend changes, the loyalty tier is re-derived against two thresholds expressed in cents: a customer at or above 200000 cents of lifetime spend is `GOLD`; otherwise a customer at or above 50000 cents is `SILVER`; otherwise the customer is `BRONZE`. The boundaries are inclusive — reaching a threshold exactly promotes the customer.

A store manager may ban a customer, which sets `status` to `BANNED`. A banned customer cannot register for events or check in; the customer lifecycle is otherwise unaffected. The banned check surfaces specifically at check-in as `ERR_CUSTOMER_BANNED`.

### 3.2. Inventory, Buylist Intake, and Trade-In Valuation

The catalog holds inventory items, each created by a store manager with a `title`, a `product_kind` of either `SINGLE` or `SEALED`, an optional `condition`, and a `market_price_cents` reference price. Condition is one of `MINT`, `NEAR_MINT`, `LIGHTLY_PLAYED`, `MODERATELY_PLAYED`, or `DAMAGED`, and defaults to `NEAR_MINT` when omitted. Every item tracks two counts that begin at 0: `quantity_on_hand`, the physical units the store owns, and `quantity_reserved`, the units committed to undelivered orders or grading holds. The reserved count is never allowed to exceed the on-hand count.

A customer brings cards to the store through a buylist submission, created with the customer's own `customer_id` and a `payout_method` of either `STORE_CREDIT` or `CASH`, which fixes the valuation variant for the whole submission. A fresh submission is in `DRAFT` with `offered_total_cents` of 0. The customer adds one or more buylist lines, each naming its parent `buylist_submission_id`, the `inventory_item_id` the card maps to, and a `quantity` of at least 1; a line begins with `line_payout_cents` of 0, which stays 0 until acceptance. Submitting the draft moves it from `DRAFT` to `SUBMITTED`, but only if at least one line exists — an empty submission is rejected with `ERR_EMPTY_BUYLIST` — and only if every line's quantity is at least 1, which otherwise fails with `ERR_INVALID_QUANTITY`.

A store manager reviews a `SUBMITTED` buylist and either rejects it (moving it to `REJECTED`, with no further effect) or accepts it. Acceptance is the consequential transition, and it is defined only from `SUBMITTED`; attempting it from any other state fails with `ERR_INVALID_STATE`. On acceptance, each line is valued and then several cascades fire. The per-line valuation works as follows: for a line, the base is the mapped inventory item's `market_price_cents` multiplied by the line's quantity; that base is multiplied by a rate determined by the submission's payout method — 0.70 (70%) when the method is `STORE_CREDIT`, and 0.50 (50%) when the method is `CASH`; the result is rounded half-up to a whole number of cents and pinned as that line's `line_payout_cents`. The submission's `offered_total_cents` is then the sum of the pinned per-line payouts. Rounding happens per line first, and the sum is taken afterward; this order is fixed. Beyond valuation, acceptance adds each accepted line's quantity to the mapped inventory item's `quantity_on_hand`. Finally, only when the payout method is `STORE_CREDIT`, acceptance appends a ledger row with `reason` `BUYLIST_PAYOUT` and `delta_cents` equal to the positive `offered_total_cents`, then recomputes the customer's balance; when the method is `CASH`, no ledger row is appended because cash is handled out of band.

An accepted buylist can be voided by a store manager, moving it from `ACCEPTED` to `VOIDED`, defined only from `ACCEPTED` (otherwise `ERR_INVALID_STATE`), to reverse those effects symmetrically. Voiding first checks that for every line, subtracting the line's quantity from the mapped item's `quantity_on_hand` would still leave the on-hand count at or above the item's `quantity_reserved`; if any line would drive on-hand below reserved, the void is rejected with `ERR_INVENTORY_RESERVED`. When the check passes, each line's quantity is subtracted back out of the item's `quantity_on_hand`, restoring the inventory-units invariant. If the original payout method was `STORE_CREDIT`, the void appends a compensating ledger row with `reason` `BUYLIST_PAYOUT` and `delta_cents` equal to the negated `offered_total_cents`, then recomputes the balance, restoring the store-credit invariant; the net store-credit effect of an accept-then-void pair is zero.

### 3.3. Releases, Pre-Order Priority, and Allocation

A store manager publishes an upcoming product as a release product with a `title`, a `street_date`, an `allocation_pool` of total units available to pre-orders, a `unit_price_cents` charged at fulfillment, and a non-refundable `deposit_required_cents`. A release product opens in `PRE_ORDER_OPEN` with `quantity_allocated` of 0, the count of units committed to allocated or fulfilled pre-orders, which is never permitted to exceed the allocation pool. When the street date arrives, the store manager marks the product live, moving it from `PRE_ORDER_OPEN` to `RELEASED`.

A customer places a pre-order against an open release with their own `customer_id`, the target `release_product_id`, a `requested_quantity` of at least 1, and a `deposit_paid_cents` amount paid up front in store credit. A new pre-order is `REQUESTED`. Creation appends a ledger row with `reason` `PREORDER_DEPOSIT` and `delta_cents` equal to the negated `deposit_paid_cents`, then recomputes the customer's balance, and computes the pre-order's `priority_score`.

The priority score ranks competing `REQUESTED` pre-orders on the same release and is the sum of three integer components. The first is a tier component worth 0 points for a `BRONZE` customer, 20 points for `SILVER`, and 40 points for `GOLD`. The second is a deposit component: the deposit paid is divided by 500 cents, the quotient is taken as a whole number (discarding any remainder), and that count of points is capped at a maximum of 30. The third is a recency component: rank the release's `REQUESTED` pre-orders by `created_at` ascending, so the earliest is rank 1, the next is rank 2, and so on (the rank never uses the `id`); the component is 25 minus 5 for each rank position past the first — that is, 25 for rank 1, 20 for rank 2, and so on — but never less than 0. The three components are summed into `priority_score`; a higher score allocates first.

Allocating a pre-order is a store-manager action defined only from `REQUESTED`. The parent release product must be in `PRE_ORDER_OPEN`, or the request fails with `ERR_INVALID_STATE`. Allocation must not push the release's `quantity_allocated` plus this pre-order's `requested_quantity` past the `allocation_pool`; exceeding it fails with `ERR_ALLOCATION_EXCEEDED`. The request must also carry `expected_release_product_version` matching the release product's current version, failing with `ERR_STALE_VERSION` as described in Section 2.7. When allocation succeeds, the pre-order moves to `ALLOCATED`, the release's `quantity_allocated` increases by the requested quantity, and the release product's `version` increments by one. A store manager may instead move a `REQUESTED` pre-order to `WAITLISTED` (again only while the release is `PRE_ORDER_OPEN`), which has no further side effects.

Fulfillment is a store-manager action defined only from `ALLOCATED`. The parent release product must be `RELEASED`, or the request fails with `ERR_RELEASE_NOT_LIVE`. The remaining balance owed is the release's `unit_price_cents` multiplied by the pre-order's `requested_quantity`, minus the `deposit_paid_cents` already paid; the customer's `store_credit_balance_cents` must be at least this remaining balance, or fulfillment fails with `ERR_INSUFFICIENT_STORE_CREDIT`. On success the pre-order moves to `FULFILLED`, a ledger row with `reason` `PREORDER_FULFILL` and `delta_cents` equal to the negated remaining balance is appended, and the customer's balance and lifetime spend are recomputed.

A customer may cancel a pre-order. Cancellation from `REQUESTED` simply moves it to `CANCELLED` with no side effects. Cancellation of an `ALLOCATED` pre-order also moves it to `CANCELLED`, but additionally frees the allocation: the release product's `quantity_allocated` decreases by the pre-order's requested quantity and its `version` increments by one.

### 3.4. Events, Registration, and Parallel Status Dimensions

A store manager creates an event with a `title`, a `format` of `STANDARD`, `MODERN`, `COMMANDER`, or `DRAFT`, a `starts_at`, an `ends_at` that must be later than `starts_at`, a `capacity`, an `entry_fee_cents`, and a `tables_required` count of play tables the event occupies. A new event is `SCHEDULED` with `seated_count` of 0 and `current_round` of 0. The seated count is the number of registrations whose check-in status is not `WITHDRAWN`, and it is never allowed to exceed capacity.

A registration carries an `event_id` and a `customer_id` and tracks two independent status dimensions that evolve separately. The payment dimension, `payment_status`, moves through `UNPAID`, `PAID`, and `REFUNDED`; the check-in dimension, `checkin_status`, moves through `PENDING`, `CHECKED_IN`, and `WITHDRAWN`. A registration begins `UNPAID` and `PENDING`. Two fee figures are pinned at different moments: `quoted_fee_cents` is pinned provisionally when the customer registers, and `charged_fee_cents` is pinned finally at check-in. A registration also carries `match_points`, accumulated WPN points starting at 0 (see Section 3.5).

A customer registers themselves for an event with their own `customer_id`. Registration may not be created if it would push the event's seated/registered count past `capacity`, which fails with `ERR_EVENT_FULL`. A customer also may not hold two non-`WITHDRAWN` registrations for events whose `[starts_at, ends_at)` intervals overlap; the interval is half-open, so two events that merely touch at a shared endpoint (one ending exactly when another begins) do not conflict, but any true overlap is rejected with `ERR_SCHEDULE_CONFLICT`. On successful registration the `quoted_fee_cents` is pinned using the provisional variant of the entry-fee calculation.

The entry-fee calculation has two variants over a single event and the acting customer. Both start from the event's `entry_fee_cents` as the base and apply a loyalty discount expressed in basis points: 0 basis points for `BRONZE`, 500 (5%) for `SILVER`, and 1000 (10%) for `GOLD`, where a basis-point figure is converted to a fraction by dividing by 10000. The provisional variant, computed at registration before the early-bird window is known, applies only the loyalty discount: the quoted fee is the base multiplied by one minus the loyalty fraction, rounded half-up to whole cents. The final variant, computed at check-in and clock-aware, adds an early-bird component: the registration is early if the current logical clock time is at or before the event's `starts_at` minus 86400 seconds (that is, at least 24 hours before start); when early, an additional 1000 basis points (10%) is added to the loyalty discount fraction. The combined effective discount fraction is then capped so that it never exceeds 2000 basis points (20%); the charged fee is the base multiplied by one minus the capped effective fraction, rounded half-up to whole cents.

Paying a registration is a customer action that moves `payment_status` from `UNPAID` to `PAID`. It is rejected if the registration's check-in status is already `WITHDRAWN` (`ERR_INVALID_STATE`), and the customer's `store_credit_balance_cents` must be at least the registration's `quoted_fee_cents`, otherwise it fails with `ERR_INSUFFICIENT_STORE_CREDIT`. On payment, a ledger row with `reason` `EVENT_CHARGE` and `delta_cents` equal to the negated `quoted_fee_cents` is appended, and the customer's balance and lifetime spend are recomputed.

Checking in is a store-manager action that moves `checkin_status` from `PENDING` to `CHECKED_IN`. Check-in requires that the registration's `payment_status` is `PAID` (otherwise `ERR_REGISTRATION_NOT_PAID`), that the customer's `status` is `ACTIVE` (otherwise `ERR_CUSTOMER_BANNED`), and that the parent event is `OPEN` or `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`). Check-in pins the registration's `charged_fee_cents` via the final fee variant and increments the event's `seated_count`.

Withdrawing is a customer action defined only from a `checkin_status` of `PENDING`, which it moves to `WITHDRAWN`; a registration whose `checkin_status` is already `CHECKED_IN` (or `WITHDRAWN`) cannot be withdrawn directly and the attempt fails with `ERR_INVALID_STATE`. Direct withdrawal is further permitted only while the parent event is not `COMPLETE` (otherwise `ERR_INVALID_STATE`). If the registration's payment status is `PAID` at the time of withdrawal, withdrawing also drives the payment dimension from `PAID` to `REFUNDED`. The refund transition is defined only when payment status is `PAID` (otherwise `ERR_INVALID_STATE`): it appends a ledger row with `reason` `EVENT_REFUND` whose `delta_cents` is the positive `charged_fee_cents` if the registration was checked in, or the positive `quoted_fee_cents` if it was not, and then recomputes the customer's balance. This same refund transition is shared with the §3.5 event-cancel cascade; because direct withdrawal is reachable only from `PENDING`, the `charged_fee_cents` (checked-in) branch is exercised only when the refund is driven by that cascade for a `CHECKED_IN` registration, whereas a direct withdrawal always refunds the `quoted_fee_cents`. The pay-then-refund pair is designed to net to zero store-credit movement.

### 3.5. The Tournament Floor: Rounds, Pairings, and WPN Standings

Opening an event for registration is a store-manager action that moves it from `SCHEDULED` to `OPEN`. It requires the event's `capacity` to be at least 1 (otherwise `ERR_INVALID_EVENT_CAPACITY`) and a venue-overlap check. The venue check protects a fixed total of 8 play tables across the store: opening must not cause concurrent play-table usage to exceed 8 tables over the event's window padded by a 30-minute buffer on each side — that is, the window from 30 minutes before `starts_at` to 30 minutes after `ends_at`. The buffer-padded window is treated strictly, so adjacency within the buffer is not allowed; any other non-terminal event whose padded window overlaps this one, such that their combined `tables_required` would exceed 8 concurrent tables, blocks the open with `ERR_VENUE_OVERLAP`.

Starting an event is a judge-staff action that moves it from `OPEN` to `IN_PROGRESS`. It requires the event's `seated_count` to be at least 1 (otherwise `ERR_NO_SEATED_PLAYERS`) and sets `current_round` to 1. Judge staff then create pairings for the current round of an in-progress event. A pairing carries an `event_id`, a `registration_a_id` for the first seated player, and an optional `registration_b_id` for the second seated player, which is left absent to denote a bye. Each pairing is stamped with `round_number` equal to the event's current round and starts with a `result` of `PENDING`.

Reporting a result is a judge-staff action that requires the parent event to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and moves the pairing's `result` out of `PENDING`. The supplied `result` selects the outcome and its match-point side effect. For a two-player pairing (where the second player is present), reporting `A_WINS` adds 3 to player A's registration `match_points`; reporting `B_WINS` adds 3 to player B's `match_points`; and reporting `DRAW` adds 1 to player A's `match_points` and 1 to player B's `match_points`. Each of these two-player outcomes requires that the second player is present; if the pairing has no second player, the outcome is rejected with `ERR_INVALID_STATE`. The bye outcome `BYE_A` is the symmetric case: it is valid only when the second player is absent (otherwise `ERR_INVALID_STATE`) and awards a win by adding 3 to player A's `match_points`.

Advancing to the next round is a judge-staff action and a cyclic self-transition: it keeps the event `IN_PROGRESS` while incrementing `current_round` by one, opening a new round for pairing. It requires that every pairing in the event's current round has a result other than `PENDING` (otherwise `ERR_ROUND_NOT_COMPLETE`) and that the current round is below the cap of 5 rounds (otherwise `ERR_MAX_ROUNDS_REACHED`). Completing an event is a judge-staff action that moves it from `IN_PROGRESS` to `COMPLETE`, again requiring that every pairing in the current round is no longer `PENDING` (otherwise `ERR_ROUND_NOT_COMPLETE`); once complete, the event is eligible for WPN reporting. The computed WPN organized-play report returns the event's standings ordered by `match_points` descending, with ties broken by `created_at` ascending.

Cancelling an event is a store-manager action available from `SCHEDULED` or `OPEN`, with no precondition, and it cascades. Every non-`WITHDRAWN` registration on the event has its `checkin_status` set to `WITHDRAWN`; and any such registration whose `payment_status` is `PAID` is driven to `REFUNDED`, which in turn appends an `EVENT_REFUND` ledger row and recomputes that customer's `store_credit_balance_cents`. This is a depth-three cascade: the event's cancellation forces each paid registration to refund, and each refund writes a ledger row and reconciles the owning customer's balance.

### 3.6. Grading Intake: Fork to Graded or Rejected

A store manager intakes a raw single for third-party grading by creating a grading submission with the owning `customer_id`, the `inventory_item_id` of the raw single, a `declared_value_cents` used to size the fee, and a `service_tier` of `ECONOMY`, `STANDARD`, or `EXPRESS`. A new submission is `INTAKE` with `grading_fee_cents` of 0 and `assigned_grade` left null.

Sending the card to the grader is defined only from `INTAKE` (otherwise `ERR_INVALID_STATE`) and requires that holding one unit will not over-commit inventory: subtracting one from the item's `quantity_on_hand` must still leave it at or above the item's `quantity_reserved`, or the send is rejected with `ERR_INVENTORY_RESERVED`. On send, the submission moves to `AT_GRADER`, the grading fee is pinned, and the item's `quantity_reserved` increases by one because the grader holds the raw single. The fee is computed over the single submission: the base is 1500 cents; a value surcharge is the `declared_value_cents` multiplied by 100 basis points (1%, that is, divided by 10000) and rounded half-up to whole cents; the sum of the base and the value surcharge is then multiplied by a service-tier multiplier — 1.0 for `ECONOMY`, 1.5 for `STANDARD`, and 2.5 for `EXPRESS` — and the product is rounded half-up to whole cents and pinned as `grading_fee_cents`.

Recording the grader's result is defined only from `AT_GRADER` (otherwise `ERR_INVALID_STATE`) and forks on whether a grade is supplied. When the body provides an `assigned_grade`, the result must lie between 1 and 10 inclusive (otherwise `ERR_INVALID_GRADE`); the submission moves to `GRADED` and the numeric grade is stored on `assigned_grade`. When the body omits `assigned_grade` — the grader could not encapsulate the card — the submission moves to `REJECTED` and `assigned_grade` stays null. Both forks are released back to the customer the same way: releasing is defined from either `GRADED` or `REJECTED`, moves the submission to `RETURNED`, and decrements the item's `quantity_reserved` by one as the card leaves the store's hold — the graded card in the `GRADED` case, the raw card in the `REJECTED` case.

### 3.7. Consignment: List, Sell, Settle

A customer places an item for sale on consignment by creating a consignment case with their own `customer_id`, the `inventory_item_id` being sold, a `quantity` of at least 1, a per-unit `ask_price_cents`, and a `commission_rate_bps` store commission in basis points between 0 and 10000 inclusive. A new case is `LISTED` with `payout_total_cents` of 0.

Marking a case sold is a store-manager action defined only from `LISTED` (otherwise `ERR_INVALID_STATE`); it pins the consignor's payout. The payout is computed per unit and then scaled: the per-unit commission is the `ask_price_cents` multiplied by the `commission_rate_bps` divided by 10000, rounded half-up to whole cents; the per-unit net is the ask price minus that per-unit commission; and `payout_total_cents` is the per-unit net multiplied by the case `quantity`. The order is fixed — commission is rounded per unit first, and the multiplication by quantity happens afterward — because computing commission on the full gross and rounding once would yield a different cent total.

Settling a sold case is a store-manager action defined only from `SOLD` (otherwise `ERR_INVALID_STATE`); it moves the case to `SETTLED`, appends a ledger row with `reason` `CONSIGNMENT_PAYOUT` and `delta_cents` equal to the positive `payout_total_cents`, and recomputes the customer's `store_credit_balance_cents`. A consignment payout credits the wallet but does not count toward lifetime spend, so it leaves `lifetime_spend_cents` unchanged. Alternatively, a customer may withdraw a still-listed case, moving it from `LISTED` to `WITHDRAWN` with no side effects.

### 3.8. The Logical Clock

The system runs on a logical clock rather than wall-clock time, so that time-gated rules — chiefly the early-bird window in the final entry-fee variant — are deterministic. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until a store manager sets it the clock holds at that default and never falls back to the host's wall clock. A store manager may advance the clock by supplying a `to_iso8601` instant, after which every subsequent time-gated rule reads the supplied instant as "now."

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — every state transition, every lifecycle action, the clock setter, and the read endpoints — return `200 OK`. To reconstruct the full request body and side effects of any endpoint below, refer back to the workflow narratives in Section 3; this table lists only the route, its purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager |
| POST | `/customers` | Register a new customer | StoreManager |
| GET | `/customers/{id}` | Get a customer | Customer, StoreManager, JudgeStaff |
| GET | `/customers` | List customers (optional email filter) | StoreManager, JudgeStaff |
| POST | `/customers/{id}/ban` | Ban a customer | StoreManager |
| POST | `/customers/{id}/credit-adjustments` | Adjust a customer's store credit | StoreManager |
| GET | `/customers/{id}/ledger` | List a customer's store-credit ledger rows | Customer, StoreManager |
| GET | `/customers/{id}/registrations` | List a customer's registrations | Customer, StoreManager |
| POST | `/inventory-items` | Create an inventory catalog item | StoreManager |
| GET | `/inventory-items/{id}` | Get an inventory item | Customer, StoreManager, JudgeStaff |
| GET | `/inventory-items` | List inventory items | Customer, StoreManager, JudgeStaff |
| POST | `/buylist-submissions` | Create a draft buylist submission | Customer |
| GET | `/buylist-submissions/{id}` | Get a buylist submission | Customer, StoreManager |
| GET | `/buylist-submissions` | List buylist submissions | Customer, StoreManager |
| POST | `/buylist-lines` | Add a line to a draft buylist submission | Customer |
| GET | `/buylist-lines/{id}` | Get a buylist line | Customer, StoreManager |
| GET | `/buylist-lines` | List buylist lines | Customer, StoreManager |
| POST | `/buylist-submissions/{id}/submit` | Submit a draft buylist for review | Customer |
| POST | `/buylist-submissions/{id}/accept` | Accept a submitted buylist | StoreManager |
| POST | `/buylist-submissions/{id}/reject` | Reject a submitted buylist | StoreManager |
| POST | `/buylist-submissions/{id}/void` | Void an accepted buylist | StoreManager |
| POST | `/release-products` | Create a release product with an allocation pool | StoreManager |
| GET | `/release-products/{id}` | Get a release product | Customer, StoreManager |
| GET | `/release-products` | List release products | Customer, StoreManager |
| POST | `/release-products/{id}/release` | Mark a release product live | StoreManager |
| POST | `/pre-orders` | Create a pre-order against a release product | Customer |
| GET | `/pre-orders/{id}` | Get a pre-order | Customer, StoreManager |
| GET | `/pre-orders` | List pre-orders | Customer, StoreManager |
| POST | `/pre-orders/{id}/allocate` | Allocate units to a pre-order (OCC-guarded) | StoreManager |
| POST | `/pre-orders/{id}/waitlist` | Move a pre-order to the waitlist | StoreManager |
| POST | `/pre-orders/{id}/fulfill` | Fulfill an allocated pre-order after release | StoreManager |
| POST | `/pre-orders/{id}/cancel` | Cancel a pre-order | Customer |
| POST | `/events` | Create a tournament/event | StoreManager |
| GET | `/events/{id}` | Get an event | Customer, StoreManager, JudgeStaff |
| GET | `/events` | List events | Customer, StoreManager, JudgeStaff |
| GET | `/events/{id}/registrations` | List registrations for an event | Customer, StoreManager, JudgeStaff |
| GET | `/events/{id}/pairings` | List pairings for an event | Customer, StoreManager, JudgeStaff |
| GET | `/events/{id}/wpn-report` | Get the computed WPN standings report | StoreManager, JudgeStaff |
| POST | `/events/{id}/open` | Open an event for registration | StoreManager |
| POST | `/events/{id}/start` | Start the event (round 1) | JudgeStaff |
| POST | `/events/{id}/advance-round` | Advance to the next pairing round | JudgeStaff |
| POST | `/events/{id}/complete` | Complete the event | JudgeStaff |
| POST | `/events/{id}/cancel` | Cancel an event (cascades withdrawals and refunds) | StoreManager |
| POST | `/registrations` | Register a customer for an event | Customer |
| GET | `/registrations/{id}` | Get a registration | Customer, StoreManager, JudgeStaff |
| POST | `/registrations/{id}/pay` | Pay the registration fee with store credit | Customer |
| POST | `/registrations/{id}/check-in` | Check a paid registration in at the event | StoreManager |
| POST | `/registrations/{id}/withdraw` | Withdraw a registration (refunds if paid) | Customer |
| POST | `/pairings` | Create a pairing for the current round | JudgeStaff |
| GET | `/pairings/{id}` | Get a pairing | Customer, StoreManager, JudgeStaff |
| GET | `/pairings` | List pairings | Customer, StoreManager, JudgeStaff |
| POST | `/pairings/{id}/report` | Report a pairing result | JudgeStaff |
| POST | `/grading-submissions` | Intake a card for grading | StoreManager |
| GET | `/grading-submissions/{id}` | Get a grading submission | Customer, StoreManager |
| GET | `/grading-submissions` | List grading submissions | Customer, StoreManager |
| POST | `/grading-submissions/{id}/send` | Send the card to the grader | StoreManager |
| POST | `/grading-submissions/{id}/return-result` | Record the grader's result | StoreManager |
| POST | `/grading-submissions/{id}/release` | Return the card to the customer | StoreManager |
| POST | `/consignment-cases` | List an item on consignment | Customer |
| GET | `/consignment-cases/{id}` | Get a consignment case | Customer, StoreManager |
| GET | `/consignment-cases` | List consignment cases | Customer, StoreManager |
| POST | `/consignment-cases/{id}/sell` | Mark a consigned case sold | StoreManager |
| POST | `/consignment-cases/{id}/settle` | Settle a sold case (credits the consignor) | StoreManager |
| POST | `/consignment-cases/{id}/withdraw` | Withdraw a listed consignment case | Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_INVALID_GRADE` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CUSTOMER_BANNED` | 409 Conflict |
| `ERR_INVALID_EVENT_CAPACITY` | 422 Unprocessable Entity |
| `ERR_NO_SEATED_PLAYERS` | 409 Conflict |
| `ERR_ROUND_NOT_COMPLETE` | 409 Conflict |
| `ERR_MAX_ROUNDS_REACHED` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_VENUE_OVERLAP` | 409 Conflict |
| `ERR_EMPTY_BUYLIST` | 422 Unprocessable Entity |
| `ERR_INVENTORY_RESERVED` | 409 Conflict |
| `ERR_ALLOCATION_EXCEEDED` | 409 Conflict |
| `ERR_RELEASE_NOT_LIVE` | 409 Conflict |
| `ERR_REGISTRATION_NOT_PAID` | 409 Conflict |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
</content>
</invoke>
