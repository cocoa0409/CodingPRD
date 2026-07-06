# Comic Book Shop API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Comic Book & Graphic-Novel Shop API, the operational backbone for a specialty retailer that juggles several intertwined businesses under one roof: weekly pull-lists and standing subscriptions, new-comic-day allocation of scarce distributor stock, a Previews pre-order pipeline with hard order cutoffs, back-issue and graded-book inventory, a grading-submission intake service with a dispute-and-resubmit loop, in-store events and signings, and a consignment desk that pays sellers out of a store-credit wallet.

The recurring tension the system must resolve is scarcity against demand. Copies ordered from a distributor are finite, yet customers reserve freely; the platform therefore has to allocate a limited pool fairly and deterministically, honor a waitlist, and keep its copy counts internally consistent as reservations are released, expired, or cascaded away by a subscription cancellation. Alongside this quota-allocation core runs a ledger-reconciliation concern: store credit, loyalty points, lifetime spend, and loyalty tier all move together at checkout and at consignment payout, and every wallet movement is journaled. The requirements below describe the entities, their lifecycles, the calculations that bind them, and the precise error contract the implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation — or a customer attempts to act on another customer's resource — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `Customer`, `Clerk`, and `Manager`.

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; this role is entity-backed. Ownership checks on any resource that references a `Customer` (through `customer_id`, or `consignor_id` on a consignment) compare that foreign-key field to `X-User-ID`. A `Customer` may act only on their own subscriptions, reservations, pre-orders, event registrations, consignments (as consignor), and grading submissions, and may read only resources scoped to themselves.
- When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `Clerk` runs day-to-day store operations: catalog management, allocation, pulls and sales, grading intake and advancement, events, consignment listing and sale, and checkout.
- When `X-User-Role` is `Manager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A `Manager` is a hierarchical superset of `Clerk` — every operation a `Clerk` may perform, a `Manager` may also perform — plus three fiscal-authority operations reserved exclusively to managers: manual store-credit adjustments, customer bans, and consignment payouts.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Nearly every resource in the system carries a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation, and `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that begins at its initial value and increments by one on every mutation of the resource; it underpins the optimistic-concurrency mechanism described in §2.6.

There is one deliberate exception. A `CreditTransaction` is an append-only ledger event: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because it is never modified after it is written. All other resources — customers, comic series, comic issues, pull subscriptions, reservations, pre-orders, back-issues, grading submissions, events, event registrations, and consignments — carry the full `id` / `created_at` / `updated_at` / `version` set.

Whenever a server-side action mutates a resource — including derived fields such as an issue's `copies_reserved`, `copies_allocated`, or `copies_available`, or a customer's `loyalty_tier` — that counts as a mutation: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Monetary Values, Grades, and Precision

All monetary amounts are stored and returned as integer cents. Copy counts and loyalty points are likewise integers. Two calculations require explicit rounding: consignment payouts round the product of price and the seller's retained fraction to whole cents using the round-half-up method; loyalty-point accrual floors a per-line value before summing, as detailed in §3.8. Allocation arithmetic is purely integer copies and never rounds. A grade value (a book's numeric grade such as 9.8) is a decimal number and is stored as provided.

### 2.6. Optimistic Concurrency Control on Reservations

Creating a reservation is the one write in this system guarded by optimistic concurrency. A reservation-create request must include `expected_comic_issue_version`, carrying the `version` of the target `ComicIssue` that the client last observed. Because a prior reservation-create against the same issue legitimately bumps that issue's `copies_reserved` and therefore its `version`, a client working from an out-of-date read would otherwise silently supersede that change. If `expected_comic_issue_version` does not equal the issue's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and reservation creates without a matching version never proceed.

### 2.7. Inventory Invariants and Copy Accounting

Each comic issue tracks its finite distributor stock through four counters. `copies_ordered` is the total ordered from the distributor and is fixed at creation. `copies_reserved` is soft demand: the running sum of `requested_qty` across all non-terminal reservations, incremented when a reservation is created and decremented when one is released or expired. `copies_allocated` is the sum of `allocated_qty` across reservations in `ALLOCATED`, `PULLED`, or `SOLD` status. `copies_available` is defined as `copies_ordered` minus `copies_allocated`. The system holds one invariant at all times: `copies_available` plus `copies_allocated` equals `copies_ordered`. Any release or reconciliation that would drive `copies_available` or `copies_allocated` below zero is forbidden and rejected with `ERR_NEGATIVE_INVENTORY`.

### 2.8. Validation Order and Error Precedence

When more than one rule could reject a request, checks are evaluated in a fixed priority order so that the reported error is deterministic. The order is:

1. **Authentication** — headers present and `X-User-Role` recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the operation and, for an entity-backed customer, the resource is their own, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path id and every foreign-key id in the body resolves to an existing resource, checked left to right, else `ERR_NOT_FOUND` (404).
4. **Well-formedness** — required fields present, enums valid, numbers in range, `ends_at` strictly after `starts_at`, and `commission_pct` at least 0 and strictly below 1, else `ERR_VALIDATION` (400).
5. **State** — the target resource is in a state from which the requested transition or operation is defined, else `ERR_INVALID_STATE` (409).
6. **Temporal windows** — pre-order confirmation before the order cutoff and event registration before the event start, else `ERR_PAST_CUTOFF` or `ERR_EVENT_ALREADY_STARTED` (422).
7. **Referential state** — required linked-entity states (issue on sale, event open, series active, consignor active), yielding `ERR_ISSUE_NOT_ON_SALE`, `ERR_EVENT_CLOSED`, `ERR_SERIES_DISCONTINUED`, or `ERR_CUSTOMER_BANNED` (409).
8. **Capacity, overlap, uniqueness, and allocation limits** — event capacity, event and registration time overlaps, duplicate registration, copy availability, allocation-already-run, dispute limit, and inventory invariants (409 family).
9. **Funds** — a store-credit-only checkout with insufficient balance, `ERR_INSUFFICIENT_STORE_CREDIT` (402).
10. **Concurrency** — the reservation stale-version check of §2.6, `ERR_STALE_VERSION` (412).

A lower-numbered check that fails masks any higher-numbered check that would also have failed.

### 2.9. The Logical Clock and Temporal Rules

All time-window rules evaluate against a logical clock, never the real wall clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an operator moves it. An admin-style test-driving capability sets the clock to a supplied `to_iso8601` instant and reports the new `current_utc`. Two rules depend on this clock: a pre-order may be confirmed only while the clock is strictly before the issue's `order_cutoff_date`, and an event registration may be created only while the clock is strictly before the event's `starts_at`.

### 2.10. Cascade and Reconciliation Principles

Several operations mutate more than one resource in a single, immediately consistent step. Closing an issue, cancelling a subscription, releasing an allocated reservation, cancelling or completing an event, and paying out a consignment all trigger cascades that touch dependent resources. Each such cascade is described with its full effect in §3; the governing principle is that copy counters, wallet balances, loyalty tiers, and registration counts are always reconciled synchronously within the triggering request, and every resource the cascade touches has its `updated_at` and `version` advanced accordingly.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Series and Issues

The catalog begins with a **comic series**, created with a `title` and a `publisher` and starting in `ACTIVE` status. A series may later be discontinued, moving it to `DISCONTINUED`; this is a one-way administrative action available to store staff.

An individual **comic issue** belongs to a series and is created with a `series_id`, an `issue_number` label (for example `"1"` or `"1B"`), a `cover_price_cents` amount that must be zero or greater, an `on_sale_date`, an `order_cutoff_date`, and a `copies_ordered` count that must be zero or greater. A new issue opens in `SOLICITED` status with `copies_reserved` and `copies_allocated` both zero and `copies_available` equal to `copies_ordered`.

An issue advances through its lifecycle by staff-driven transitions carrying a `to_status`. Moving from `SOLICITED` to `ORDERED` is permitted only when the parent series is still `ACTIVE`; if the series has been discontinued, the advance is rejected with `ERR_SERIES_DISCONTINUED`. Moving from `ORDERED` to `ON_SALE` has no precondition and opens the issue for allocation and pulls. The final move from `ON_SALE` to `CLOSED` is the issue's terminal step and carries a reconciliation cascade: every reservation on the issue still in `RESERVED`, `WAITLISTED`, or `ALLOCATED` is transitioned to `EXPIRED`; for each such expired reservation, the issue's `copies_reserved` is reduced by that reservation's `requested_qty`, and if the reservation had a positive `allocated_qty`, the issue's `copies_allocated` is reduced by that `allocated_qty` (so `copies_available` rises by the same amount). `CLOSED` is terminal.

### 3.2. Pull Subscriptions and Weekly Reservations

A **pull subscription** is a standing order linking a customer to a series. It is created with a `customer_id` and a `series_id` and opens in `ACTIVE` status. A customer may pause an active subscription, moving it to `PAUSED`, and resume a paused one back to `ACTIVE`; this pause/resume oscillation may repeat any number of times. A subscription may also be cancelled from either `ACTIVE` or `PAUSED`, which is terminal and identical in effect from both states.

Cancelling a subscription triggers a three-stage cascade. First, every reservation linked to that subscription (that is, whose `subscription_id` equals the cancelled subscription) still in `RESERVED`, `WAITLISTED`, or `ALLOCATED` is transitioned to `RELEASED`. Second, each released reservation reduces its issue's `copies_reserved` by that reservation's `requested_qty`, and if the reservation had a positive `allocated_qty`, the issue's `copies_allocated` is reduced by that `allocated_qty` (so `copies_available` rises by the same amount). Third, for each issue whose `copies_available` has risen above zero as a result, the earliest-created reservation on that issue currently in `WAITLISTED` status — ordered by `created_at` ascending — is promoted to `ALLOCATED`, receiving an `allocated_qty` equal to the smallest of its `requested_qty`, the issue's current `copies_available`, and the customer's tier cap; that promotion decrements the issue's `copies_available` (by raising `copies_allocated`).

A **reservation** is a weekly pull-box entry against a single issue. It is created with a `customer_id`, an `issue_id`, an optional `subscription_id` (null for a one-off weekly reservation), an optional `requested_qty` that defaults to 1 and must be at least 1, and the `expected_comic_issue_version` required by §2.6. A new reservation opens in `RESERVED` status with `allocated_qty` at 0 and `unit_price_cents` at 0; creating it raises the issue's `copies_reserved` by `requested_qty` and increments the issue's `version` by one. A customer may release a reservation while it is in `RESERVED` or `WAITLISTED`, which moves it to `RELEASED` and reduces the issue's `copies_reserved` by that reservation's `requested_qty`.

### 3.3. New-Comic-Day Allocation

Allocation distributes an issue's finite stock across outstanding demand. Running allocation is a staff capability that may be invoked only while the issue is `ON_SALE`; invoking it against an issue not on sale is rejected with `ERR_ISSUE_NOT_ON_SALE`. If there are no reservations left in `RESERVED` status to allocate and allocation has already been executed once for that issue, the request is rejected with `ERR_ALLOCATION_ALREADY_RUN`.

The candidate set is every reservation on the issue currently in `RESERVED` status. Candidates are processed in a strictly deterministic order: first by the reserving customer's loyalty tier from highest to lowest, treating `GOLD` as rank 3, `SILVER` as rank 2, and `BRONZE` as rank 1, and within the same tier by the reservation's `created_at` ascending (earliest first). Ordering never uses the reservation `id`. A running "remaining" figure starts at the issue's `copies_available`. For each candidate in turn, a tier cap is looked up — `BRONZE` caps at 1 copy, `SILVER` at 2, and `GOLD` at 3 — and the grant is the smallest of the reservation's `requested_qty`, the current remaining figure, and that tier cap. If the grant is at least 1, the reservation's `allocated_qty` is set to the grant, the reservation moves to `ALLOCATED`, the issue's `copies_allocated` rises by the grant, and remaining falls by the grant. If the grant would be 0 — which happens precisely when remaining has reached 0 — the reservation is instead moved to `WAITLISTED` and receives no copies.

A waitlisted reservation is promoted to `ALLOCATED` when copies later free up, either through the subscription-cancel cascade of §3.2 or through a subsequent allocation run, provided the issue's `copies_available` is at least 1 at that moment; the promotion grants an `allocated_qty` equal to the smallest of the reservation's `requested_qty`, the issue's `copies_available`, and the customer's tier cap, and raises `copies_allocated` accordingly.

Once a reservation is `ALLOCATED`, staff may pull it, advancing it to `PULLED`; this is permitted only while the issue is `ON_SALE`. A pulled reservation is then sold, advancing it to `SOLD`, at which point its `unit_price_cents` is set from the issue's `cover_price_cents`. `SOLD`, `RELEASED`, and `EXPIRED` are the terminal states of a reservation.

Releasing an already-allocated reservation is a customer action available from `ALLOCATED`, but it is guarded: the release must not drive the issue's `copies_available` or `copies_allocated` below zero, and a release that would violate that invariant is rejected with `ERR_NEGATIVE_INVENTORY`. A permitted release reduces the issue's `copies_reserved` by the reservation's `requested_qty` and reduces `copies_allocated` by the reservation's `allocated_qty` (so `copies_available` rises by that `allocated_qty`); it then promotes the earliest-created `WAITLISTED` reservation on that issue to `ALLOCATED` if `copies_available` is now at least 1. The `ERR_INSUFFICIENT_COPIES` code is reserved for a mandatory-grant boundary at allocation where reserved copies cannot be satisfied.

### 3.4. Previews Pre-Orders

A **pre-order** captures advance demand for an issue before its distributor cutoff. It is created with a `customer_id`, an `issue_id`, and an optional `quantity` that defaults to 1 and must be at least 1. At creation the pre-order opens in `PENDING` status and its `estimated_total_cents` is fixed to `quantity` multiplied by the issue's `cover_price_cents`.

Confirming a pre-order advances it from `PENDING` to `CONFIRMED` and carries two preconditions evaluated together: the logical clock must be strictly before the issue's `order_cutoff_date`, else the confirmation is rejected with `ERR_PAST_CUTOFF`; and the issue's status must be `SOLICITED` or `ORDERED`, else — because the issue has already gone on sale or closed — it is rejected with `ERR_ISSUE_ALREADY_ON_SALE`. A successful confirmation recomputes the customer's loyalty tier under the forward-looking rule of §3.8, since a confirmed pre-order now counts toward forward spend. A confirmed pre-order may be fulfilled, advancing it to `FULFILLED`, only while the issue is `ON_SALE`. A pre-order may also be cancelled by the customer from either `PENDING` or `CONFIRMED`, moving it to `CANCELLED`; cancellation likewise recomputes the customer's loyalty tier, because a cancelled pre-order no longer contributes to forward spend. `FULFILLED` and `CANCELLED` are terminal.

### 3.5. Back-Issue Inventory and the Grading Desk

A **back-issue** is a single physical copy held in inventory, created with a `series_id`, an `issue_number` label, a `condition` of either `RAW` or `GRADED`, an optional `grade_value` (the numeric grade, such as 9.8, supplied when graded and null when raw), and a `price_cents` amount of zero or greater. A back-issue opens `IN_STOCK`. Staff may move it between `IN_STOCK` and `RESERVED` in either direction, and may sell it (to `SOLD`) from either `IN_STOCK` or `RESERVED`. `SOLD` is terminal.

The **grading desk** accepts a customer's book for third-party grading. A grading submission is created with a `customer_id`, a free-text `description`, and a `declared_value_cents` amount of zero or greater; it opens in `INTAKE` with `dispute_count` at 0 and no `grade_result`. Staff advance it from `INTAKE` to `SUBMITTED`, but only when the owning customer is `ACTIVE` — a banned customer's submission cannot be advanced and is rejected with `ERR_CUSTOMER_BANNED`. From `SUBMITTED` it moves to `AT_GRADER`, and from `AT_GRADER` back to `RETURNED`, which requires a `grade_result` to be supplied and records it on the submission.

Once returned, the owner may dispute the grade, which sends the book back to `AT_GRADER` for regrading and increments `dispute_count` by one; this resubmit loop is bounded, and a dispute attempted when `dispute_count` has already reached the limit of 3 is rejected with `ERR_DISPUTE_LIMIT_REACHED`. Alternatively, staff move a returned submission to `READY_FOR_PICKUP` and finally to `PICKED_UP`, the terminal state.

### 3.6. Events and Signings

An **event** (a signing or in-store appearance) is created with a `name`, a `store_location` venue identifier, a `starts_at`, an `ends_at` that must be strictly later than `starts_at`, and a `capacity` of zero or greater. It opens in `DRAFT` with `registered_count` at 0. Two events at the same `store_location` may not overlap in time: creating an event whose window overlaps a non-cancelled event at the same location — treating each window as the half-open interval from `starts_at` up to but not including `ends_at` — is rejected with `ERR_EVENT_TIME_CONFLICT`.

Staff open an event (to `OPEN`), close it (to `CLOSED`), and complete it (from `CLOSED` to `COMPLETED`). Completion transitions every registration still in `REGISTERED` to `NO_SHOW`. An event may be cancelled from `OPEN`, which transitions every registration in `REGISTERED` or `CHECKED_IN` to `CANCELLED` and sets `registered_count` to 0; it may also be cancelled directly from `DRAFT` with no registrations to resolve. `COMPLETED` and `CANCELLED` are terminal.

An **event registration** links a `customer_id` to an `event_id` and opens in `REGISTERED`, raising the event's `registered_count` by one. Registration is subject to several checks: the event must be `OPEN` (else `ERR_EVENT_CLOSED`); the logical clock must be strictly before the event's `starts_at` (else `ERR_EVENT_ALREADY_STARTED`); the customer must not already hold a `REGISTERED` or `CHECKED_IN` registration for the same event (else `ERR_DUPLICATE_REGISTRATION`); the event must not be full, meaning `registered_count` has reached `capacity` (else `ERR_EVENT_FULL`); and the customer must not already be registered for another event whose window, expanded by a 30-minute buffer on each side, overlaps this event's window (else `ERR_REGISTRATION_TIME_CONFLICT`). Staff check a registrant in, moving `REGISTERED` to `CHECKED_IN`, but only while the event is `OPEN` (else `ERR_EVENT_CLOSED`). A customer may cancel their own registration from `REGISTERED`, moving it to `CANCELLED` and reducing the event's `registered_count` by one; staff may mark a checked-in registrant as a no-show, moving `CHECKED_IN` to `NO_SHOW`, which also reduces `registered_count` by one. `CANCELLED` and `NO_SHOW` are terminal.

### 3.7. The Consignment Desk

A **consignment** lets a customer sell an item through the shop. It is created with a `consignor_id`, a `description`, an `asking_price_cents` amount of zero or greater, and an optional `commission_pct` — the shop's commission fraction, which defaults to 0.30 and must be at least 0 and strictly below 1. A new consignment opens in `RECEIVED`.

Listing a consignment advances it from `RECEIVED` to `LISTED`, permitted only while the consignor is `ACTIVE` (else `ERR_CUSTOMER_BANNED`). Listing computes a `provisional_payout_cents`: the `asking_price_cents` multiplied by one minus the `commission_pct`, rounded half-up to whole cents — an estimate of what the consignor would receive before a buyer is found.

From `LISTED` the consignment forks. If it sells, it advances to `SOLD`, which requires a `sale_price_cents` to be supplied (else `ERR_SALE_PRICE_REQUIRED`) and computes `final_payout_cents` as the `sale_price_cents` multiplied by one minus the `commission_pct`, rounded half-up to whole cents; because the sale price may differ from the asking price, this final figure can diverge from the provisional estimate. Alternatively the item is returned to its owner, advancing to `RETURNED_TO_CONSIGNOR`; this branch produces no payout, writes no credit transaction, and makes no change to store credit. `RETURNED_TO_CONSIGNOR` is terminal.

Paying out a sold consignment is a manager-only action that advances it from `SOLD` to `PAID_OUT`. It runs a two-hop cascade: first it writes a credit transaction with reason `CONSIGNMENT_PAYOUT` and an `amount_cents` equal to the consignment's `final_payout_cents`, and raises the consignor's `store_credit_cents` by that `final_payout_cents`; then it recomputes the consignor's loyalty tier. `PAID_OUT` is terminal.

### 3.8. Customers, Loyalty, Store Credit, and Checkout

A **customer** is created with an `email` (unique per customer) and a `full_name`, and opens with `loyalty_tier` at `BRONZE`, `store_credit_cents` at 0, `loyalty_points_balance` at 0, `lifetime_spend_cents` at 0, and `status` at `ACTIVE`. A manager may ban a customer, setting `status` to `BANNED`, which blocks operations that require an active customer as described elsewhere.

A manager may also make a manual store-credit adjustment, which writes a credit transaction carrying a signed `amount_cents` (positive to credit, negative to debit) and a `reason`, raises the customer's `store_credit_cents` by that `amount_cents`, records the resulting `balance_after_cents` on the transaction, and recomputes the customer's loyalty tier. Every credit transaction records the affected `customer_id`, its signed `amount_cents`, its `reason` — one of `CONSIGNMENT_PAYOUT`, `REFUND`, `ADJUSTMENT`, or `REDEMPTION` — and the `balance_after_cents`, the wallet balance immediately after the transaction was applied.

**Loyalty tier** is recomputed whenever spend or forward commitments change — at checkout, on pre-order confirmation or cancellation, and on consignment payout. The system computes a settled figure equal to the customer's `lifetime_spend_cents`, then a forward-looking figure equal to that settled figure plus the sum of `estimated_total_cents` across the customer's pre-orders currently in `CONFIRMED` status. The tier the system persists uses the forward-looking figure: if it is at least 150000 cents the tier is `GOLD`; otherwise if it is at least 50000 cents the tier is `SILVER`; otherwise the tier is `BRONZE`. Both thresholds are inclusive. The forward-looking figure (which counts confirmed but not-yet-fulfilled pre-orders) is the variant that drives allocation tier caps and point multipliers; a settled-only figure — using `lifetime_spend_cents` alone and excluding confirmed pre-orders — serves as a chronological audit basis and can yield a lower tier than the forward-looking one for the same customer.

**Checkout** settles a point-of-sale sale. It takes a `customer_id`, a `line_items` array, and an optional `pay_with_store_credit_only` flag. Each entry in `line_items` carries a per-line `unit_price_cents` and `quantity`. The amount due (`amount_due_cents`) is the sum over the line items of each line's `unit_price_cents` multiplied by its `quantity`. If `pay_with_store_credit_only` is true and the customer's `store_credit_cents` is less than the amount due, the checkout is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`. Otherwise the store credit applied (`store_credit_applied_cents`) is the smaller of the customer's `store_credit_cents` and the amount due, and the amount charged (`charge_cents`) is the amount due minus the applied credit — exactly 0 when credit fully covers the sale.

Checkout then commits several effects. The customer's `store_credit_cents` is reduced by the applied credit; if the applied credit is greater than 0, a credit transaction with reason `REDEMPTION` and an `amount_cents` equal to the negative of the applied credit is written. The customer's `lifetime_spend_cents` is increased by the amount due. Loyalty points are accrued into `loyalty_points_balance`: using a per-tier multiplier — 1.0 for `BRONZE`, 1.25 for `SILVER`, and 1.5 for `GOLD` — the system computes, for each line item independently, the line's total in cents divided by 100 and multiplied by the multiplier, takes the floor of that per-line value, and sums those floored per-line values into a single integer `loyalty_points_earned`. The flooring is applied per line item and only then summed; summing the raw cents first and flooring once would yield a different total, so the per-line order is mandatory. These points are accrued only and are never spent by this system. Finally the customer's loyalty tier is recomputed. The checkout response reports `amount_due_cents`, `store_credit_applied_cents`, `charge_cents`, and `loyalty_points_earned`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all lifecycle transitions, bans, discontinuations, allocation runs, and checkout — return `200 OK`. The manual store-credit adjustment writes a new `CreditTransaction` and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/customers` | Create a customer | Clerk, Manager |
| GET | `/api/customers/{id}` | Get a customer | Customer, Clerk, Manager |
| GET | `/api/customers` | List customers | Clerk, Manager |
| POST | `/api/customers/{id}/credit-adjustments` | Adjust a customer's store credit | Manager |
| POST | `/api/customers/{id}/ban` | Ban a customer | Manager |
| GET | `/api/credit-transactions/{id}` | Get a credit transaction | Customer, Clerk, Manager |
| GET | `/api/credit-transactions` | List credit transactions | Customer, Clerk, Manager |
| POST | `/api/comic-series` | Create a comic series | Clerk, Manager |
| GET | `/api/comic-series/{id}` | Get a comic series | Customer, Clerk, Manager |
| GET | `/api/comic-series` | List comic series | Customer, Clerk, Manager |
| POST | `/api/comic-series/{id}/discontinue` | Discontinue a series | Clerk, Manager |
| POST | `/api/comic-issues` | Create a comic issue | Clerk, Manager |
| GET | `/api/comic-issues/{id}` | Get a comic issue | Customer, Clerk, Manager |
| GET | `/api/comic-issues` | List comic issues | Customer, Clerk, Manager |
| POST | `/api/comic-issues/{id}/transition` | Advance a comic issue's lifecycle state | Clerk, Manager |
| POST | `/api/comic-issues/{id}/run-allocation` | Run new-comic-day allocation for an issue | Clerk, Manager |
| POST | `/api/pull-subscriptions` | Create a pull subscription | Customer, Clerk, Manager |
| GET | `/api/pull-subscriptions/{id}` | Get a pull subscription | Customer, Clerk, Manager |
| GET | `/api/pull-subscriptions` | List pull subscriptions | Customer, Clerk, Manager |
| POST | `/api/pull-subscriptions/{id}/transition` | Pause, resume, or cancel a subscription | Customer, Clerk, Manager |
| POST | `/api/reservations` | Create a weekly reservation / pull-box entry | Customer, Clerk, Manager |
| GET | `/api/reservations/{id}` | Get a reservation | Customer, Clerk, Manager |
| GET | `/api/reservations` | List reservations | Customer, Clerk, Manager |
| POST | `/api/reservations/{id}/transition` | Release, pull, or sell a reservation | Customer, Clerk, Manager |
| POST | `/api/pre-orders` | Create a Previews pre-order | Customer, Clerk, Manager |
| GET | `/api/pre-orders/{id}` | Get a pre-order | Customer, Clerk, Manager |
| GET | `/api/pre-orders` | List pre-orders | Customer, Clerk, Manager |
| POST | `/api/pre-orders/{id}/transition` | Confirm, fulfill, or cancel a pre-order | Customer, Clerk, Manager |
| POST | `/api/back-issues` | Add a back-issue inventory item | Clerk, Manager |
| GET | `/api/back-issues/{id}` | Get a back-issue | Customer, Clerk, Manager |
| GET | `/api/back-issues` | List back-issues | Customer, Clerk, Manager |
| POST | `/api/back-issues/{id}/transition` | Reserve, restock, or sell a back-issue | Clerk, Manager |
| POST | `/api/grading-submissions` | Intake a book for grading | Customer, Clerk, Manager |
| GET | `/api/grading-submissions/{id}` | Get a grading submission | Customer, Clerk, Manager |
| GET | `/api/grading-submissions` | List grading submissions | Customer, Clerk, Manager |
| POST | `/api/grading-submissions/{id}/transition` | Advance grading lifecycle | Customer, Clerk, Manager |
| POST | `/api/events` | Create an event / signing | Clerk, Manager |
| GET | `/api/events/{id}` | Get an event | Customer, Clerk, Manager |
| GET | `/api/events` | List events | Customer, Clerk, Manager |
| POST | `/api/events/{id}/transition` | Open, close, complete, or cancel an event | Clerk, Manager |
| POST | `/api/event-registrations` | Register a customer for an event | Customer, Clerk, Manager |
| GET | `/api/event-registrations/{id}` | Get an event registration | Customer, Clerk, Manager |
| GET | `/api/event-registrations` | List event registrations | Customer, Clerk, Manager |
| POST | `/api/event-registrations/{id}/transition` | Check in, cancel, or mark no-show | Customer, Clerk, Manager |
| POST | `/api/consignments` | Intake a consigned item | Customer, Clerk, Manager |
| GET | `/api/consignments/{id}` | Get a consignment | Customer, Clerk, Manager |
| GET | `/api/consignments` | List consignments | Customer, Clerk, Manager |
| POST | `/api/consignments/{id}/transition` | List, sell, return, or pay out a consignment | Clerk, Manager (PAID_OUT: Manager only) |
| POST | `/api/checkout` | Settle a point-of-sale checkout | Clerk, Manager |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | Clerk, Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CUSTOMER_BANNED` | 409 |
| `ERR_SERIES_DISCONTINUED` | 409 |
| `ERR_PAST_CUTOFF` | 422 |
| `ERR_ISSUE_NOT_ON_SALE` | 409 |
| `ERR_ISSUE_ALREADY_ON_SALE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ALLOCATION_ALREADY_RUN` | 409 |
| `ERR_INSUFFICIENT_COPIES` | 409 |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 402 |
| `ERR_EVENT_FULL` | 409 |
| `ERR_EVENT_CLOSED` | 409 |
| `ERR_EVENT_TIME_CONFLICT` | 409 |
| `ERR_REGISTRATION_TIME_CONFLICT` | 409 |
| `ERR_EVENT_ALREADY_STARTED` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_SALE_PRICE_REQUIRED` | 422 |
| `ERR_DISPUTE_LIMIT_REACHED` | 409 |
| `ERR_NEGATIVE_INVENTORY` | 409 |
