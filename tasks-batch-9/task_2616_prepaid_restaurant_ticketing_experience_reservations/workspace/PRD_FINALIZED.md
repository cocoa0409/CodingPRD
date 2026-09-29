# Prepaid Restaurant Ticketing API — Product Requirements Document

## 1. Introduction

Fine-dining rooms that sell their seats the way a theatre sells its stalls face a problem no ordinary booking sheet solves: the seat is the product, the kitchen is the constraint, and the money moves before the guest ever walks through the door. This document specifies the Prepaid Restaurant Ticketing API, the service layer behind a ticketed-seating business in which every cover is inventory, every inventory unit is priced dynamically against the calendar and against its own scarcity, and every prepayment sits in a ledger that must reconcile to the cent through cancellations, transfers, no-shows, goodwill gestures and adjudicated refund exceptions.

The operational pain the platform removes is coordination cost. A restaurant manager currently reconciles four incompatible views of the same evening — a floor plan of tables with their own turn times, a seat-count spreadsheet split by experience package, a payment processor's settlement report, and a kitchen prep list annotated with allergies. When a party of four cancels forty-eight hours out, all four views have to be corrected by hand: the forfeiture percentage has to be looked up in the right cancellation ladder, a rebooking fee has to be banded off the resulting forfeiture, a waitlisted guest has to be offered the freed seats at the right price, and the kitchen has to be told that fifteen minutes of anaphylaxis prep just left the line. The API makes each of those consequences a deterministic, immediate side effect of one authenticated request.

Two design commitments run through everything that follows. First, **money is never estimated**: all monetary figures are whole cents, every percentage is expressed in basis points, and every rounding step is pinned so that two conforming implementations produce byte-identical settlement figures. Second, **guest safety outranks both scheduling and revenue**: an unacknowledged anaphylaxis note blocks a table assignment before the system ever considers whether the table is free or whether the kitchen has capacity. Readers implementing this specification should treat the ordering rules in §2 as binding contracts, not as guidance.

## 2. Global Specifications & System-Wide Principles

This section defines the request contract, the response contract, and the cross-cutting principles that every endpoint obeys regardless of which part of the business it serves.

### 2.1. Operator Identity and Role-Based Access Control

Every request to the API — reads included — must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which that principal is acting. If either header is absent or present but empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request is inspected. If both headers are present but `X-User-Role` is not one of the five recognised role names, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401.

The five roles are `Guest`, `RestaurantManager`, `KitchenLead`, `GuestServices` and `PlatformAdmin`, spelled exactly as shown.

- A `Guest` is a diner who buys tickets, prepays them, appends add-ons, records dietary notes, changes the name on a ticket, transfers it, cancels it, joins waitlists and redeems goodwill credit.
- A `RestaurantManager` is the front-of-house operator who registers tables, publishes the experience catalogue, creates and publishes services, allocates ticket classes, re-tiers demand, runs release runs, and works the floor by assigning tables, seating parties, completing them and declaring no-shows.
- A `KitchenLead` is the back-of-house lead whose only write authority is acknowledging or prep-rejecting dietary notes. This role deliberately cannot seat a party, cannot price anything, and cannot touch money.
- A `GuestServices` operator is the customer-care agent who files, adjudicates and compensates refund exceptions, and who may also take payments, cancel bookings and apply credit on a guest's behalf.
- A `PlatformAdmin` onboards restaurants and guests, drives the hold sweep, and sets the server's logical clock.

If the acting role is not among the roles listed for the endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity is not uniform, and the difference matters for every ownership check in the system:

- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`. Ownership checks on any resource that references a `Guest` compare the resource's guest foreign-key field to `X-User-ID` — a reservation's `guest_id`, a waitlist entry's `guest_id`, a goodwill credit's `guest_id`.
- When `X-User-Role` is `RestaurantManager`, `X-User-ID` is the `id` of the acting `Restaurant`. Ownership checks compare `X-User-ID` to the `restaurant_id` of the target table, experience package, add-on or service, and for reservation-scoped floor operations to the `restaurant_id` of the service the reservation belongs to.
- When `X-User-Role` is `KitchenLead`, `X-User-ID` is likewise the `id` of the acting `Restaurant`, and the same restaurant-ownership comparison applies to the dietary notes and reservations the lead may read or acknowledge.
- When `X-User-Role` is `GuestServices`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `requested_by_user_id` and `decided_by_user_id` on a `RefundException`, and as `issued_by_user_id` on a `GoodwillCredit` — but never compares it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is also an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

An entity-backed role acting on a resource it does not own is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403). Because `GuestServices` and `PlatformAdmin` are opaque, no ownership comparison is performed for them; their reach is platform-wide.


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

Every endpoint that returns a collection accepts two query parameters. `limit` caps the number of rows returned; when it is omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. `offset` is the number of rows to skip before the window begins; when it is omitted it defaults to 0, and a supplied value must be at least 0. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint says otherwise, list results are ordered by the row's own `created_at` timestamp, ascending — oldest first. This applies to the payment ledger listing as well, whose deterministic replay order is exactly that ascending creation order.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the number of rows matching the filter before the window is applied, and `has_more` is true when rows remain beyond the returned window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id`: a UUID string with no type prefix, generated by the server and never supplied by the client. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.

Most resources additionally carry two mutation-tracking fields. `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource — including changes to purely derived fields such as a ticket class's seat counters or a reservation's money roll-ups. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource. `Restaurant`, `Guest`, `Table`, `ExperiencePackage`, `AddOn`, `Service`, `TicketClass`, `Reservation`, `ReservationAddOn`, `DietaryNote`, `WaitlistEntry`, `RefundException` and `GoodwillCredit` all carry `updated_at` and `version`.

Every other ISO 8601 UTC instant this system persists and returns is rendered in exactly that same shape — three fractional digits and a trailing `Z` — and is normalised to that rendering when it is written, whatever precision the client supplied for the ones the client supplies. That covers a service's `seating_start_utc` and `seating_end_utc`, a reservation's `hold_expires_at_utc`, `seat_from_utc` and `seat_to_utc`, a waitlist entry's `offer_expires_at_utc`, and a goodwill credit's `expires_at_utc`. A calendar date such as a service's `service_date` is not an instant, and this rendering rule does not reach it.

`PaymentTransaction` is the single exception. Ledger rows are immutable once written: a `PaymentTransaction` carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it entirely. That immutability is what makes the ledger replay deterministic.

All temporal reasoning in this system reads a **logical clock** rather than the host's wall clock. Every deadline, cutoff, expiry, grace period, release window and forfeiture-ladder comparison described in this document compares against that logical clock. Before any request sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to real wall-clock time. A `PlatformAdmin` may advance or rewind it by supplying a `current_utc` instant to the clock-setting capability described in §4; setting the clock mutates no entity and triggers no sweep, offer expiry or automatic transition of any kind — those happen only when the corresponding operation is invoked.

### 2.5. Money, Basis Points and Rounding Discipline

Every monetary figure in this system is an integer number of cents. There are no fractional cents, no decimal strings and no floating-point money fields. Every proportion is expressed in **basis points** — hundredths of a percent — so that 10000 basis points means "the whole amount", 5000 means half of it, and 725 means 7.25 percent.

Applying a basis-point figure to a cent amount means multiplying the amount by the basis-point figure, dividing by 10000, and rounding the result **half up** to a whole cent: a remainder of exactly one half cent rounds away from zero, upward. Every named step in every calculation in this document rounds half up at that step; intermediate basis-point figures are themselves rounded half up before they are used further, and no calculation defers rounding to a later step unless this document explicitly says so.

Two consequences deserve emphasis because they are the most common source of one-cent divergence:

- **Service charge is rounded once per charge line, never once per reservation.** The ticket line and each add-on line are charged independently, each rounded half up on its own, and the rounded per-line figures are then summed. Summing raw subtotals first and rounding the aggregate once is the wrong variant and produces a different total.
- **Seat and minute arithmetic floors rather than rounds.** Where this document says a seat count or a sell-through figure is taken by flooring, the fractional part is discarded downward — a partial seat is never released, and a sell-through of 79.99 percent is not promoted to the 80 percent scarcity step.

Scores used purely for ranking are integers with no rounding at all, and never enter a money figure.

### 2.6. Seat-Pool Accounting and the Precedence Ladder

A ticket class's seat inventory is split across four counters that must always sum to its fixed allocation. `seats_sold` is the covers committed by reservations whose seating side has reached `CONFIRMED`, `SEATED` or `COMPLETED`. `seats_held` is the covers tied up by reservations still in `PENDING`. `seats_released` is a persisted pool of unsold seats that a release run has moved aside for waitlist promotion and that no promotion has yet consumed — it is credited only by a release run and debited only when a release-priced hold draws from it. `seats_available` is what remains sellable at list price, and it is the allocation minus the other three. The invariant is absolute: `seats_allocated` always equals `seats_sold` plus `seats_held` plus `seats_released` plus `seats_available`. `seats_allocated` itself is fixed at creation and never mutated.

Alongside those counters the class publishes `sell_through_bp`, the floor of ten thousand times the sum of `seats_sold` and `seats_held` divided by `seats_allocated`. Note that a mere hold moves it: a `PENDING` reservation counts against sell-through exactly as a confirmed one does, so an unpaid hold can already push the class into a higher scarcity price step.

A reservation that has left the live set — `CANCELLED`, `NO_SHOW` or `EXPIRED` — contributes to no counter, which is precisely how its seats come back to the pool. A transfer is different: the predecessor in `TRANSFERRED_OUT` and the successor it minted together contribute the party's covers exactly once, because the successor is `CONFIRMED` and carries the seats. Transferring a ticket therefore leaves every seat counter on the class untouched.

After **every** seat move on a class — a hold being created, a hold being confirmed, a hold lapsing, a cancellation, a no-show, a release run, a waitlist promotion — the class's `status` is re-derived by walking this pinned precedence ladder in order and stopping at the first rule that applies:

1. A class whose status is `PAUSED` stays `PAUSED`. Only an explicit resume by a `RestaurantManager` leaves that state.
2. A class whose status is `CLOSED` stays `CLOSED`. `CLOSED` is terminal.
3. If `seats_released` is above zero, the class becomes `RELEASED`.
4. Otherwise, if `seats_available` is above zero, the class becomes `OPEN`.
5. Otherwise the class becomes `SOLD_OUT`.

`RELEASED` therefore outranks `OPEN` whenever both pools hold seats. The five legal values of a ticket class's `status` are `OPEN`, `PAUSED`, `SOLD_OUT`, `RELEASED` and `CLOSED`.

Parent-level roll-ups follow the same immediate-consistency discipline. A service's `covers_confirmed` tracks the sum of party sizes over its reservations in `CONFIRMED`, `SEATED` or `COMPLETED`; its `gross_charged_cents` is the sum of inbound ledger magnitudes across its reservations; its `refunded_cents` and `forfeited_cents` are the corresponding outbound sums; and its `net_settled_cents` is `gross_charged_cents` minus `refunded_cents`. Each such reconciliation is a mutation of the parent service in its own right: `updated_at` is refreshed and `version` is incremented, exactly as it would be for a client-driven edit.

### 2.7. The Immutable Money Ledger and the Derived Payment Dimension

All money movement on a reservation is recorded as append-only ledger rows. Each row belongs to one reservation through its `reservation_id`, carries a `kind` that classifies it, an `amount_cents` magnitude that is always at least 1 and always unsigned, a derived `signed_amount_cents`, and a `memo_code` recording why the row was written. Rows are never edited and never deleted; a correction is always a new compensating row.

The eight legal values of `kind` are `DEPOSIT_CHARGE`, `BALANCE_CHARGE`, `GOODWILL_REDEMPTION`, `TRANSFER_IN`, `TRANSFER_OUT`, `REFUND`, `FORFEITURE` and `FORFEITURE_REVERSAL`. The `kind` alone fixes the sign of `signed_amount_cents`: it is the magnitude taken positively for `DEPOSIT_CHARGE`, `BALANCE_CHARGE`, `GOODWILL_REDEMPTION`, `TRANSFER_IN` and `FORFEITURE_REVERSAL`, and the magnitude taken negatively for `TRANSFER_OUT`, `REFUND` and `FORFEITURE`.

The nine legal values of `memo_code` are `GUEST_PREPAY` (a guest's own prepayment of the deposit), `GUEST_BALANCE` (a guest's settlement of the outstanding balance), `CREDIT_APPLIED` (a goodwill credit redemption), `TRANSFER_MOVE` (the paired rows that move cash across a ticket transfer), `GUEST_CANCEL` (settlement of a guest-initiated cancellation), `NO_SHOW` (forfeiture on a declared no-show), `SERVICE_CANCEL` (full refund when the restaurant cancels the service), `HOLD_LAPSE` (refund when an unconfirmed hold expires) and `REFUND_EXCEPTION` (the reversal and refund pair written when an exception is approved).

From those rows, replayed in ascending `created_at` order, four figures on the reservation are derived and re-derived after every write:

- `amount_paid_cents` is the sum of the magnitudes of the `DEPOSIT_CHARGE`, `BALANCE_CHARGE`, `GOODWILL_REDEMPTION` and `TRANSFER_IN` rows. Cents that arrived as goodwill credit are indistinguishable from cash here, and are therefore just as refundable and just as forfeitable.
- `refunded_cents` is the sum of the magnitudes of the `REFUND` rows.
- `forfeited_cents` is the sum of the magnitudes of the `FORFEITURE` rows minus the sum of the magnitudes of the `FORFEITURE_REVERSAL` rows.
- `goodwill_applied_cents` is the sum of the magnitudes of the `GOODWILL_REDEMPTION` rows alone.

Two invariants hold at all times. First, the sum of `signed_amount_cents` across a reservation's rows equals `amount_paid_cents` minus `refunded_cents` minus `forfeited_cents`. Second, once a reservation has fully settled — that is, once its money dimension reads `REFUNDED`, `FORFEITED` or `PARTIALLY_REFUNDED` — `amount_paid_cents` equals `refunded_cents` plus `forfeited_cents` exactly. No rounding ever occurs inside the ledger; every row carries a figure that was already rounded before it was written.

A reservation's `balance_due_cents` is the greater of zero and `grand_total_cents` minus `amount_paid_cents`.

A reservation carries **two independent state dimensions on the same row**, and they advance on different triggers. `fulfillment_status` is the seating side, whose legal values are `PENDING`, `CONFIRMED`, `SEATED`, `COMPLETED`, `CANCELLED`, `NO_SHOW`, `TRANSFERRED_OUT` and `EXPIRED`, starting at `PENDING` and terminating at `COMPLETED`, `CANCELLED`, `NO_SHOW`, `TRANSFERRED_OUT` or `EXPIRED`. `payment_status` is the money side, whose legal values are `UNPAID`, `DEPOSIT_PAID`, `FULLY_PAID`, `PARTIALLY_REFUNDED`, `REFUNDED`, `FORFEITED` and `TRANSFERRED`, starting at `UNPAID` and terminating at `REFUNDED`, `FORFEITED` or `TRANSFERRED`. The two dimensions gate each other only at the pinned crossing points named in §3.

`payment_status` is never set directly. It is re-derived from the ledger after every ledger write, by walking these six rules in this pinned order and stopping at the first that applies:

1. If `fulfillment_status` is `TRANSFERRED_OUT`, the money dimension is `TRANSFERRED`.
2. Otherwise, if `amount_paid_cents` is zero, it is `UNPAID`.
3. Otherwise, if `refunded_cents` plus `forfeited_cents` is zero, it is `FULLY_PAID` when `amount_paid_cents` is at least `grand_total_cents`; failing that, `DEPOSIT_PAID` when `amount_paid_cents` is at least `deposit_due_cents`; failing that, `UNPAID`.
4. Otherwise, if `refunded_cents` equals `amount_paid_cents`, it is `REFUNDED`.
5. Otherwise, if `forfeited_cents` equals `amount_paid_cents`, it is `FORFEITED`.
6. Otherwise it is `PARTIALLY_REFUNDED`.

### 2.8. Stale-View Rejection on Seat, Line and Credit Writes

Three write operations commit against a parent whose derived figures the client has necessarily read in an earlier request. Each of those three requires the client to echo back the `version` it last observed on that parent, as a **non-optional** field in the request body, and each rejects the write when the echoed value does not equal the parent's current `version`. No other endpoint in this API takes a version field of any kind.

- Creating a reservation requires `expected_ticket_class_version`, carrying the client's last observed `version` of the target `TicketClass`. If it does not equal that ticket class's current `version`, the create is rejected with `ERR_STALE_TICKET_CLASS_VERSION` (HTTP 412). The second create is otherwise perfectly legitimate — the class may still have seats, may still be `OPEN`, and the requesting guest may hold no reservation of their own on it — but the price the client is quoting was computed from a seat-pool snapshot that has since crossed a scarcity step, so the stale view must be refreshed before the seats are committed.
- Appending an add-on line requires `expected_reservation_version`, carrying the client's last observed `version` of the target `Reservation`. A mismatch with the reservation's current `version` is rejected with `ERR_STALE_RESERVATION_VERSION` (HTTP 412). Add-on lines are additive and the same add-on may legitimately appear on several lines, so no state rule refuses a second append; the hazard is that the client's picture of `grand_total_cents` and `balance_due_cents` predates another line or a credit redemption, and the per-cover quantity ceiling would then be evaluated against stale totals.
- Redeeming a goodwill credit requires `expected_goodwill_credit_version`, carrying the client's last observed `version` of the target `GoodwillCredit`. A mismatch with the credit's current `version` is rejected with `ERR_STALE_GOODWILL_CREDIT_VERSION` (HTTP 412). Partial redemptions are legitimate and repeatable while the credit still has a remainder, so nothing in the credit's own lifecycle refuses a second redemption; the check exists because the client's picture of the remainder may predate an earlier redemption or a revocation and would otherwise overdraw the credit.

### 2.9. Resource Addressing and Left-to-Right Identifier Validation

Every resource is addressed at the top level of the URL space by its own UUID; templated identifiers in paths are always written literally as `{id}`. Foreign keys are supplied in request bodies rather than encoded as nested write paths, which means that a create request can reference a parent that does not exist. Where a path contains an identifier, and where the body contains foreign keys, identifiers are validated **left to right in the order they appear in the path, and then in the order the body declares them**, and the first identifier that resolves to nothing determines the error. Each entity type has its own dedicated not-found code, all of them HTTP 404: `ERR_RESTAURANT_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`, `ERR_TABLE_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`, `ERR_TICKET_CLASS_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_RESERVATION_ADDON_NOT_FOUND`, `ERR_DIETARY_NOTE_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`, `ERR_PAYMENT_TRANSACTION_NOT_FOUND`, `ERR_REFUND_EXCEPTION_NOT_FOUND` and `ERR_GOODWILL_CREDIT_NOT_FOUND`.

Because writes are flat, every foreign key in the model is nonetheless discoverable by reading. A restaurant exposes reverse indexes over its tables, experience packages, add-ons and services; a reservation exposes a reverse index over its dietary notes; and the collection listings for ticket classes, reservations, add-on lines, ledger rows, waitlist entries, refund exceptions and goodwill credits all accept filters on the foreign keys that point at them.

### 2.10. Segregation of Duties in Refund Adjudication

Compensating a guest is a three-step chain — file, decide, compensate — and no single operator identifier may occupy two adjacent steps of it. Three comparisons enforce this, all of them rejecting with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- The operator deciding a refund exception must have an `X-User-ID` different from the `requested_by_user_id` recorded when the exception was filed.
- The operator issuing a goodwill credit against a decided exception must have an `X-User-ID` different from the `decided_by_user_id` recorded on that exception.
- The operator revoking a goodwill credit must have an `X-User-ID` different from the `issued_by_user_id` recorded on that credit.

These comparisons work precisely because `GuestServices` identity is opaque: the same human operator identifier can be compared across three recorded steps without any of those values being an entity `id`.

### 2.11. The Order in Which a Request Is Rejected

When more than one thing is wrong with a request, only one error is returned, and which one is not a matter of implementation taste. The checks below are evaluated **in the order given**, and the first check that fails is the error the client sees. The ordering rationale is: authentication, then authorization and ownership, then existence, then request shape, then segregation of duties, then stale-view rejection, then state preconditions, then **guest safety**, then temporal conflicts, then referential coherence, then capacity and quota, and money last. Safety precedes every scheduling and money check because an unacknowledged anaphylaxis note is a clinical risk, not an inconvenience.

1. Both `X-User-Role` and `X-User-ID` are present and non-empty on every endpoint — otherwise `ERR_MISSING_AUTH_HEADERS`.
2. `X-User-Role` is one of the five declared roles, on every endpoint — otherwise `ERR_UNKNOWN_ROLE`.
3. The acting role appears in the endpoint's authorized role list, on every endpoint — otherwise `ERR_UNAUTHORIZED`.
4. For the entity-backed roles, the acting `X-User-ID` owns the target, on every guest-scoped and restaurant-scoped endpoint — otherwise `ERR_FORBIDDEN_RESOURCE_OWNER`.
5. Every identifier in the request path exists, validated left to right, on every endpoint that has a path identifier — otherwise the matching not-found code from §2.9.
6. Every foreign key in the request body references an existing row, on every create carrying foreign keys — otherwise the matching not-found code from §2.9.
7. The request body satisfies its declared shape on every endpoint: required fields present, types correct, enum values recognised, integers inside their declared ranges, datetimes well-formed ISO 8601 UTC — otherwise `ERR_VALIDATION`.
8. `limit` and `offset` are inside their permitted ranges, on every list endpoint — otherwise `ERR_INVALID_PAGINATION`.
9. The three segregation-of-duties comparisons of §2.10, on exception decision, goodwill-credit issue and goodwill-credit revocation — otherwise `ERR_SEGREGATION_OF_DUTIES`.
10. `expected_ticket_class_version` equals the ticket class's current `version`, on reservation creation — otherwise `ERR_STALE_TICKET_CLASS_VERSION`.
11. `expected_reservation_version` equals the reservation's current `version`, on add-on line append — otherwise `ERR_STALE_RESERVATION_VERSION`.
12. `expected_goodwill_credit_version` equals the credit's current `version`, on goodwill redemption — otherwise `ERR_STALE_GOODWILL_CREDIT_VERSION`.
13. The owning service is `PUBLISHED`, on reservation creation, waitlist-entry creation, release runs and ticket-class resume — otherwise `ERR_SERVICE_NOT_PUBLISHED`.
14. The service is in the status the operation itself requires — `DRAFT` to publish, `DRAFT` or `PUBLISHED` to cancel, `PUBLISHED` to close — on service publish, service cancel, hold sweep and ticket-class creation — otherwise `ERR_SERVICE_INVALID_STATE`.
15. The ticket class is sellable: `OPEN` or `RELEASED` for a direct reservation, and `OPEN`, `RELEASED` or `SOLD_OUT` for a waitlist claim, with `PAUSED` and `CLOSED` always failing — on reservation creation and waitlist claim — otherwise `ERR_TICKET_CLASS_NOT_SELLABLE`.
16. The ticket class is in the status the operation requires — `OPEN` to pause, `PAUSED` to resume — otherwise `ERR_TICKET_CLASS_INVALID_STATE`.
17. The reservation's `fulfillment_status` permits the operation per the seating state machine, on confirm, payment, add-on append, dietary-note capture, table assignment, seating, completion, no-show declaration, cancellation, name change and transfer — otherwise `ERR_RESERVATION_INVALID_STATE`.
18. For a `PENDING` reservation, the logical clock is strictly before `hold_expires_at_utc`, on confirm, payment and waitlist claim — otherwise `ERR_HOLD_EXPIRED`.
19. `payment_status` is `DEPOSIT_PAID` or `FULLY_PAID` before confirming — otherwise `ERR_DEPOSIT_NOT_SETTLED`.
20. `payment_status` is `FULLY_PAID` before completing — otherwise `ERR_BALANCE_OUTSTANDING`.
21. `payment_status` is `FULLY_PAID` before transferring — otherwise `ERR_TRANSFER_REQUIRES_FULL_PAYMENT`.
22. The waitlist entry is in the status the operation requires — `OFFERED` to claim, `WAITING` or `OFFERED` to withdraw — otherwise `ERR_WAITLIST_ENTRY_INVALID_STATE`.
23. The logical clock is strictly before the entry's `offer_expires_at_utc`, on claim — otherwise `ERR_OFFER_EXPIRED`.
24. The dietary note is in the `ack_status` the operation requires — `PENDING` to acknowledge, `PREP_REJECTED` to amend — otherwise `ERR_DIETARY_NOTE_INVALID_STATE`.
25. The refund exception is still `REQUESTED`, on decision — otherwise `ERR_REFUND_EXCEPTION_ALREADY_DECIDED`.
26. The refund exception is `APPROVED` before a compensating credit may be issued — otherwise `ERR_REFUND_EXCEPTION_NOT_APPROVED`.
27. The goodwill credit is in a status the operation permits, pinned per operation so that this check and the next never shadow each other: to revoke, the credit must be `ISSUED` or `PARTIALLY_REDEEMED`; to redeem, the credit must not be `REVOKED`, and an `EXHAUSTED` credit deliberately falls through to the next check rather than failing here — otherwise `ERR_GOODWILL_CREDIT_INVALID_STATE`.
28. The credit's `remaining_cents` is strictly above zero, on redemption — otherwise `ERR_GOODWILL_CREDIT_EXHAUSTED`.
29. The logical clock is strictly before the credit's `expires_at_utc`, on redemption — otherwise `ERR_GOODWILL_CREDIT_EXPIRED`.
30. Every dietary note on the reservation whose `severity` is `ANAPHYLAXIS` has `ack_status` `ACKED`, on table assignment **and** on seating — otherwise `ERR_DIETARY_ACK_REQUIRED`.
31. No dietary note on the reservation is in `ack_status` `PREP_REJECTED`, on table assignment **and** on seating — otherwise `ERR_DIETARY_NOTE_PREP_REJECTED`.
32. The note's `amend_count` is strictly below 3, on amend — otherwise `ERR_DIETARY_AMEND_LIMIT`.
33. The candidate table occupancy does not overlap an existing occupancy on that table, on table assignment — otherwise `ERR_TABLE_TURN_CONFLICT`.
34. The target table belongs to the same restaurant as the reservation's service, on table assignment — otherwise `ERR_TABLE_RESTAURANT_MISMATCH`.
35. The party size sits inside the table's seat band, on table assignment — otherwise `ERR_TABLE_PARTY_SIZE_MISMATCH`.
36. The experience package referenced by a new ticket class belongs to the same restaurant as the service — otherwise `ERR_PACKAGE_RESTAURANT_MISMATCH`.
37. The add-on belongs to the same restaurant as the reservation's service, on add-on append — otherwise `ERR_ADDON_RESTAURANT_MISMATCH`.
38. The redemption target reservation belongs to the credit's `guest_id` and its service belongs to the credit's `restaurant_id` — otherwise `ERR_GOODWILL_TARGET_MISMATCH`.
39. The aggregate kitchen prep load across touching prep windows stays inside the service's capacity, on table assignment — otherwise `ERR_KITCHEN_PREP_OVERSUBSCRIBED`.
40. The logical clock has reached `seat_from_utc` plus the restaurant's no-show grace, on no-show declaration — otherwise `ERR_NO_SHOW_TOO_EARLY`.
41. The logical clock has reached `seat_from_utc`, on seating — otherwise `ERR_SEATING_TOO_EARLY`.
42. The logical clock is at or before the name-change cutoff instant, on name change — otherwise `ERR_NAME_CHANGE_CUTOFF_PASSED`.
43. The logical clock is at or before the transfer cutoff instant, on transfer — otherwise `ERR_TRANSFER_CUTOFF_PASSED`.
44. The logical clock is at or before the add-on's own order cutoff instant, on add-on append — otherwise `ERR_ADDON_ORDER_CUTOFF_PASSED`.
45. The logical clock has reached the opening of the release window, on a release run — otherwise `ERR_RELEASE_WINDOW_NOT_OPEN`.
46. The logical clock is strictly before `seat_from_utc` when cancelling a `CONFIRMED` reservation — otherwise `ERR_CANCEL_WINDOW_CLOSED`.
47. The reservation's `name_change_count` is strictly below the restaurant's `max_name_changes`, on name change — otherwise `ERR_NAME_CHANGE_LIMIT_REACHED`.
48. The transfer recipient's `is_broker_flagged` is false — otherwise `ERR_RESALE_SUSPECTED`.
49. The reservation's `transferred_from_reservation_id` is null, on transfer — otherwise `ERR_ONWARD_TRANSFER_FORBIDDEN`.
50. The initiating guest's `transfers_initiated_count` is strictly below the restaurant's `max_transfers_per_guest` — otherwise `ERR_TRANSFER_LIMIT_REACHED`.
51. The transfer recipient differs from the current holder — otherwise `ERR_TRANSFER_TO_SELF`.
52. The party size sits inside the ticket class's own band, and a new class's band lies inside its package's band, on reservation creation, ticket-class creation and waitlist-entry creation — otherwise `ERR_PARTY_SIZE_OUT_OF_BAND`.
53. `guest_index` is at least 1 and at most the reservation's `party_size`, on dietary-note capture — otherwise `ERR_GUEST_INDEX_OUT_OF_RANGE`.
54. `qty` is at least 1 and, counting quantities already ordered on other lines for the same add-on, at most the add-on's `max_qty_per_cover` multiplied by the reservation's `party_size` — otherwise `ERR_ADDON_QTY_INVALID`.
55. The sum of `seats_allocated` across the service's ticket classes does not exceed the service's `seats_capacity`, on ticket-class creation **and** on service publication — otherwise `ERR_SERVICE_CAPACITY_EXCEEDED`.
56. The guest holds no other reservation on the same service in `PENDING`, `CONFIRMED` or `SEATED`, on reservation creation — otherwise `ERR_DUPLICATE_ACTIVE_RESERVATION`.
57. The guest has no other waitlist entry on the same service in `WAITING` or `OFFERED`, on waitlist-entry creation — otherwise `ERR_DUPLICATE_WAITLIST_ENTRY`.
58. Offer rounds are not exhausted. This is enforced in two places with two different behaviours: as a promotion-eligibility filter inside a release run and inside cancel-driven and no-show-driven promotion, where an entry that has reached the cap is **silently skipped** rather than errored; and as a hard rejection on waitlist-entry creation when the acting guest already has an `EXPIRED` entry on the same service whose `offer_round` reached the restaurant's `max_offer_rounds`, so that an exhausted guest cannot re-queue for the same service — in which case the error is `ERR_OFFER_ROUNDS_EXHAUSTED`.
59. The drawing pool holds at least `party_size` seats — `seats_available` for a list-priced sale, `seats_released` for a release-priced promotion — on reservation creation and on waitlist promotion — otherwise `ERR_INSUFFICIENT_SEATS`.
60. `amount_cents` does not exceed the reservation's `balance_due_cents`, on payment — otherwise `ERR_PAYMENT_EXCEEDS_BALANCE`.
61. The first payment on a reservation is at least `deposit_due_cents` — otherwise `ERR_PAYMENT_BELOW_DEPOSIT`.
62. `requested_cents` does not exceed `amount_paid_cents` minus `refunded_cents`, on filing a refund exception — otherwise `ERR_REFUND_REQUEST_EXCEEDS_PAID`.
63. `approved_cents` does not exceed the exception's `requested_cents`, on decision — otherwise `ERR_APPROVED_EXCEEDS_REQUESTED`.
64. `approved_cents` does not exceed the reservation's current `forfeited_cents`, on decision, so that a reversal can never manufacture cash — otherwise `ERR_APPROVED_EXCEEDS_FORFEITED`.
65. `issued_cents` does not exceed the smaller of the restaurant's `goodwill_credit_cap_cents` and the exception's `shortfall_cents`, on credit issue — otherwise `ERR_GOODWILL_EXCEEDS_CAP`.
66. `amount_cents` does not exceed the credit's `remaining_cents`, on redemption — otherwise `ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING`.
67. `amount_cents` does not exceed the target reservation's `balance_due_cents`, on redemption — otherwise `ERR_GOODWILL_EXCEEDS_BALANCE_DUE`.

## 3. Business Logic & Workflows

### 3.1. Onboarding, the Experience Catalogue, and Bringing a Service to Market

A `PlatformAdmin` brings a restaurant onto the platform by registering its trading `name` — non-empty, at most 120 characters, and unique across all restaurants — together with the ticketing policy knobs that will govern everything the room later does. Every knob is optional at registration and falls back to a documented default. The kitchen service charge, `service_charge_bp`, defaults to 725 basis points — that is, 7.25 percent applied to each charge line — and may be set anywhere from 0 to 3000. `hold_ttl_minutes` is how long an unconfirmed hold survives and defaults to 20 minutes, with a permitted range of 1 minute to a full day of 1440 minutes. `offer_ttl_minutes` is how long a waitlist offer stays claimable; it defaults to 15 minutes, must be at least 1 minute, and — critically — must never exceed `hold_ttl_minutes`, so that an offer always lapses before the hold reservation it minted. `max_offer_rounds` caps how many times a single waitlist entry may be promoted before it gives up, defaulting to 2 within a range of 1 to 5.

Four knobs govern the resale-prevention rules. `max_name_changes` is the per-reservation ceiling on renaming the ticket and defaults to 1, permitted from 0 up to 5. `name_change_cutoff_minutes` refuses renames inside that many minutes of the seating start and defaults to 240 — four hours — with a permitted range from 0 up to 20160 minutes, a fortnight. `transfer_cutoff_minutes` does the same for transfers and defaults to 1440, a full day out, over the same 0-to-20160 range. `max_transfers_per_guest` caps how many tickets one guest may hand on, defaulting to 2 within a range of 0 to 20.

The remaining four knobs are operational. `no_show_grace_minutes` is how long the room waits past a party's seating instant before a no-show may be declared; it defaults to 30 and ranges from 0 to 240. `goodwill_credit_cap_cents` is the per-issue ceiling on any single goodwill credit and defaults to 20000 cents, with no upper bound beyond being non-negative. `prep_lead_minutes` is the length of the closed kitchen prep window that precedes each seating, defaulting to 45 minutes within a range of 1 to 240. `refund_scrutiny_threshold_cents` is the lifetime-refund figure above which a guest is flagged for scrutiny, defaulting to 30000 cents and required only to be non-negative.

Guests are likewise registered by a `PlatformAdmin`, with an `email` that is non-empty, at most 160 characters and unique across all guests, a `display_name` that is non-empty and at most 120 characters, and an optional `is_broker_flagged` marker that defaults to false. Everything else on a guest is a counter the platform maintains: `no_show_strikes`, `completed_reservations_count`, `transfers_initiated_count` and `lifetime_refunded_cents` all begin at 0, and `refund_scrutiny_flag` begins false. The `email` matters beyond login — it is the final deterministic tie-break key when the waitlist is ranked.

A `RestaurantManager` then lays out the floor. Each **Table** is created against its `restaurant_id` with a `table_code` floor-plan label that is non-empty and unique within that restaurant, a seat band given by `seats_min` and `seats_max` where the minimum is at least 1 and never above the maximum and the maximum never exceeds 20 seats, and a `turn_buffer_minutes` reset interval that defaults to 15 minutes and may run from 0 to 120. That buffer is appended to the service's turn time when the system works out how long the table is actually occupied.

The saleable product is an **ExperiencePackage**: a multi-course experience belonging to one `restaurant_id`, with a `name` that is non-empty and unique within the restaurant, a `course_count` between 1 and 30, and a `base_price_cents` list price per cover of at least 1 cent, quoted before any multiplier is applied. `prepayment_mode` decides whether the guest prepays a deposit or the whole ticket at booking and must be either `DEPOSIT` or `FULL`. When the mode is `DEPOSIT`, the deposit share is `deposit_bp`, expressed in basis points of the reservation's grand total, defaulting to 3000 — thirty percent — and permitted from 1 up to 10000; when the mode is `FULL`, `deposit_bp` is ignored entirely because the deposit simply is the grand total. Two independent policy selectors govern cancellation: `forfeiture_schedule_code` chooses which forfeiture ladder applies and is either `STANDARD` (the default) or `STRICT`, while `forfeiture_basis` chooses which amount the ladder's percentage is applied to and is either `DEPOSIT_BASIS` (the default) or `FULL_TICKET_BASIS`. They are deliberately orthogonal: the same ladder applied to two different bases produces radically different settlements. `release_discount_bp` is the discount applied to release-run inventory offered off the waitlist, defaulting to 1500 basis points — fifteen percent — over a permitted range of 0 to 5000. `kitchen_prep_minutes_per_cover` is the baseline prep time each cover consumes, defaulting to 10 minutes within a range of 0 to 240. Finally `min_party_size` and `max_party_size` bound the bookable party for the experience: the minimum is at least 1 and never above the maximum, and the maximum never exceeds 20.

**AddOn** rows are the optional extras — a caviar supplement, a wine flight — that a guest bolts onto a booking. Each belongs to a `restaurant_id`, carries a `name` that is non-empty and unique within the restaurant, and a unit `price_cents` of at least 1. `prep_minutes_per_unit` is the kitchen time each ordered unit costs the line and defaults to 0 over a range of 0 to 120. `max_qty_per_cover` is the per-cover quantity ceiling, defaulting to 1 and ranging from 1 to 20; the effective ceiling on a booking is that figure multiplied by the reservation's party size. `order_cutoff_minutes` refuses add-on orders inside that many minutes of the seating start, defaulting to 1440 over a 0-to-20160 range. `requires_kitchen_ack` is a marker, defaulting to false, that is copied onto each ordered line at order time. The add-on `name` is also load-bearing for money: it is the primary sort key for the pinned per-line charge accumulation order described in §3.3.

A **Service** is one seating date and one meal period. A `RestaurantManager` creates it against a `restaurant_id` with a `service_date` calendar date in ISO 8601 `YYYY-MM-DD` form, a `meal_period` that is either `LUNCH` or `DINNER`, a `seating_start_utc` that is the earliest legal seating instant, and a `seating_end_utc` that is the latest legal seating instant and must fall strictly after the start. `turn_time_minutes` is how long a party occupies its table before the table's own buffer is added, and must be at least 15 minutes and at most 480. `seats_capacity` is the ceiling on the total seats the service may allocate across all its ticket classes and must be at least 1. `demand_tier` is the demand band feeding the tier price multiplier and is one of `LOW`, `STANDARD`, `HIGH` or `PEAK`, defaulting to `STANDARD`. `unsold_release_bp` is the share of each open class's remaining availability that a release run converts into release inventory, defaulting to 5000 basis points — half of it — over a 0-to-10000 range. `release_lead_minutes` opens the release window that many minutes before the seating start and defaults to 180, permitted from 1 up to 10080 minutes. `waitlist_policy` selects which of the two promotion-ranking variants applies and is either `FAIR_QUEUE` (the default) or `YIELD_WEIGHTED`. `kitchen_prep_capacity_minutes` is the aggregate prep-minute ceiling for any set of reservations whose closed prep windows intersect, defaulting to 600 and required only to be non-negative.

The service's `day_of_week` is never supplied by the client: it is derived from `service_date` on the proleptic Gregorian calendar and reported as one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT` or `SUN`. It is the sole input to the day-of-week price multiplier. A service is born in `status` `DRAFT`, and its nine money-and-inventory roll-ups — `release_run_count`, `seats_released_total`, `last_release_released_count`, `last_release_promoted_count`, `covers_confirmed`, `gross_charged_cents`, `refunded_cents`, `forfeited_cents` and `net_settled_cents` — all begin at 0. The four legal service states are `DRAFT`, `PUBLISHED`, `CLOSED` and `CANCELLED`, with `CLOSED` and `CANCELLED` both terminal.

While the service is still `DRAFT`, the manager carves its capacity into **ticket classes**. Each class names the `service_id` whose seats it sells and the `package_id` whose experience it packages, fixes a `seats_allocated` pool of at least 1 seat that is never mutated afterwards, and narrows the bookable party band with its own `min_party_size` and `max_party_size`. Those two default to the package's own band when omitted, and the class band must sit inside the package band — the class minimum at or above the package minimum, the class maximum at or below the package maximum. Allocating a class requires the owning service to still be `DRAFT`; attempting it against a service that has moved on is rejected with `ERR_SERVICE_INVALID_STATE`. The package must belong to the same restaurant as the service, or the allocation fails with `ERR_PACKAGE_RESTAURANT_MISMATCH`. On creation the class's `seats_available` is initialised to the whole of `seats_allocated`, `seats_sold`, `seats_held` and `seats_released` all start at 0, `status` starts at `OPEN`, and both `list_price_per_cover_cents` and `release_price_per_cover_cents` are computed immediately from the pricing rules of §3.2.

Publication is the gate between configuration and trade. Moving a service `DRAFT → PUBLISHED` is a `RestaurantManager` action and requires four things at once: the service is still `DRAFT`; at least one ticket class exists for it; the sum of `seats_allocated` across those classes does not exceed `seats_capacity`; and `seating_start_utc` lies strictly after the logical clock. Publication re-evaluates every ticket class of the service against the seat-pool precedence ladder — a freshly allocated class with availability lands on `OPEN` — and from that instant reservations may be created against the service. Before publication they cannot: a create against a `DRAFT`, `CLOSED` or `CANCELLED` service is refused with `ERR_SERVICE_NOT_PUBLISHED`.

Re-tiering is the manager's demand-side lever. Supplying a new `demand_tier` for a published service re-runs the per-cover pricing calculation for every one of its ticket classes, refreshing `list_price_per_cover_cents` and `release_price_per_cover_cents` across the board. Reservations that have already locked a price are untouched — a locked `price_locked_per_cover_cents` is never re-priced, no matter how the tier subsequently moves.

Two paths lead out of trade. A manager may cancel a service outright, optionally recording a `reason_code`. From `DRAFT` the cancellation is quiet: the service moves `DRAFT → CANCELLED` and every one of its ticket classes moves to `CLOSED`, and nothing else happens because nothing has been sold. From `PUBLISHED` the same cancellation is a full unwind, detailed in §3.7. The other path is closure at the end of the evening, driven by a `PlatformAdmin` sweep with the `close_service` flag set to true, which is likewise detailed in §3.7.

### 3.2. What a Cover Costs: Calendar, Demand Tier and Scarcity

A cover's price is never stored on the package alone. It is re-derived from five ordered steps every time a client asks a ticket class for a quote, and derived once more — from exactly the same steps — inside reservation creation, where the result is frozen onto the reservation as `price_locked_per_cover_cents` and never revisited.

**Step one combines the calendar factor with the demand factor, multiplicatively.** The day-of-week factor is read off the service's derived `day_of_week`: Monday, Tuesday and Wednesday each carry 9500 basis points — a five percent discount on list; Thursday is neutral at 10000; Friday carries 11500; Saturday is the strongest day at 12500; and Sunday sits at 11000. The demand-tier factor is read off the service's `demand_tier`: `LOW` is 9000, `STANDARD` is 10000, `HIGH` is 12000, and `PEAK` is 14500. The two are combined by multiplying the day-of-week factor by the demand-tier factor, dividing the product by 10000, and rounding that basis-point intermediate half up to a whole basis point.

**Step two clamps the combined factor, floor first and cap second.** The floor is 8500 basis points and the cap is 18000. The combined factor is first raised to the floor if it fell below it, and the result of that is then lowered to the cap if it rose above it. The ordering is not decorative: a configuration that crosses both bounds resolves to the cap, because the floor has already been applied by the time the cap is tested.

**Step three turns the clamped factor into money.** The package's `base_price_cents` is multiplied by the clamped factor, divided by 10000, and rounded half up to whole cents. Call that figure the list price for the cover.

**Step four applies the scarcity step, keyed on the class's own sell-through.** The class's `sell_through_bp` is the floor of ten thousand times the sum of `seats_sold` and `seats_held`, divided by `seats_allocated`. Where that figure has reached 8000 basis points — eighty percent of the allocation committed, holds included — the scarcity step is 1500 basis points. Where it has not reached 8000 but has reached 5000, the step is 800 basis points. Below 5000 there is no step at all. The list price from step three is then multiplied by 10000 plus the scarcity step, divided by 10000, and rounded half up.

**Step five discounts release inventory, and only release inventory.** When the seats being priced are drawn from the released pool rather than from ordinary availability, the figure produced by step four is multiplied by 10000 minus the package's `release_discount_bp`, divided by 10000, and rounded half up. The discount therefore comes off the scarcity-adjusted figure, never off the pre-scarcity list price.

Two subtleties govern which seat counts the calculation sees. First, the only inputs are the class's own `seats_sold` and `seats_held`, read **before** the current write credits its own seats — a reservation never prices itself into a higher scarcity step. Second, reservations in `CANCELLED`, `NO_SHOW`, `EXPIRED` or `TRANSFERRED_OUT` have already been removed from those counters by the seat-pool accounting of §2.6 and are therefore excluded automatically.

A ticket class publishes both prices side by side. `list_price_per_cover_cents` is the outcome of steps one through four with ordinary availability as the drawing pool — that is, without the release discount. `release_price_per_cover_cents` is that same figure carried through step five with the package's release discount applied. A quote request re-derives `sell_through_bp`, `list_price_per_cover_cents` and `release_price_per_cover_cents` from the current seat pool and returns the refreshed class; it persists no other change and moves no seat.

Whether a given reservation was priced from released inventory is recorded permanently on it as `is_release_priced`, true only when the reservation was minted from the released pool by a release run, and false for every ordinary purchase.

### 3.3. Holding Seats, Ordering Add-Ons, and Prepaying the Ticket

A `Guest` buys by creating a reservation, naming the `ticket_class_id` whose pool the seats come from, the `guest_id` who will own the ticket, the `party_size` in covers, the `primary_guest_name` to be printed on the ticket — non-empty and at most 120 characters — and the `expected_ticket_class_version` demanded by §2.8. The reservation's `service_id` is never supplied: it is copied from the ticket class at creation and never changes afterwards. The party size must sit inside the class's own band, or the create fails with `ERR_PARTY_SIZE_OUT_OF_BAND`. A guest may hold only one live booking per service, so a create is refused with `ERR_DUPLICATE_ACTIVE_RESERVATION` when that guest already has a reservation on the same service in `PENDING`, `CONFIRMED` or `SEATED`. And the drawing pool must actually hold the seats: fewer than `party_size` seats available yields `ERR_INSUFFICIENT_SEATS`.

Creation does a great deal at once. The per-cover price is locked into `price_locked_per_cover_cents`. The full charge breakdown is computed, setting `ticket_subtotal_cents`, `service_charge_cents`, `grand_total_cents` and `deposit_due_cents`. `party_size` seats move out of `seats_available` and into `seats_held`, after which the class's status is re-derived against the precedence ladder and the class's `version` advances by one. `hold_expires_at_utc` is set to the logical clock plus the restaurant's `hold_ttl_minutes`. The reservation lands in `fulfillment_status` `PENDING` and `payment_status` `UNPAID`, with `assigned_table_id`, `transferred_from_reservation_id`, `seat_from_utc`, `seat_to_utc` and `cancel_settlement_basis` all null, `is_release_priced` and `deposit_frozen` both false, `name_change_count` at 0, and every money roll-up other than the ones just named at 0.

**The charge breakdown is where the rounding discipline of §2.5 bites.** `ticket_subtotal_cents` is `price_locked_per_cover_cents` multiplied by `party_size`. The ticket's own service charge is that subtotal multiplied by the restaurant's `service_charge_bp`, divided by 10000, rounded half up. Each add-on line is then processed **in a pinned order** — ascending by the add-on's `name`, and within a shared name ascending by the line's own `created_at` — and for each line the `line_subtotal_cents` is `unit_price_cents_locked` multiplied by `qty`, and the `line_service_charge_cents` is that line subtotal multiplied by `service_charge_bp`, divided by 10000, **rounded half up on that line alone**. `add_on_total_cents` accumulates the line subtotals; `service_charge_cents` accumulates the ticket's charge plus every rounded per-line charge. `grand_total_cents` is `ticket_subtotal_cents` plus `add_on_total_cents` plus `service_charge_cents`. Summing the raw subtotals first and rounding the service charge once at the end is the wrong variant and diverges by cents; the per-line rounding is normative. Add-on lines are never soft-deleted, so every line ever appended participates in every subsequent recomputation.

`deposit_due_cents` is the amount the guest must put down before the hold can be confirmed. When the package's `prepayment_mode` is `FULL`, it simply equals `grand_total_cents`. When the mode is `DEPOSIT` and the deposit has not yet been frozen, it is `grand_total_cents` multiplied by the package's `deposit_bp`, divided by 10000, rounded half up. Once the deposit is frozen it retains its frozen value and stops tracking the grand total altogether. `deposit_frozen` becomes true as soon as the first `DEPOSIT_CHARGE` row lands on the reservation, and confirmation likewise guarantees it is true; from that point on, appending further add-on lines raises `grand_total_cents` and `balance_due_cents` but leaves `deposit_due_cents` exactly where it was.

Appending an add-on line is a `Guest` action naming the `add_on_id`, the `qty` of units, and the `expected_reservation_version` of §2.8. The add-on must belong to the same restaurant as the reservation's service, failing which the append is rejected with `ERR_ADDON_RESTAURANT_MISMATCH`. The order must arrive at or before the add-on's own cutoff — the service's `seating_start_utc` less the add-on's `order_cutoff_minutes` — or it is refused with `ERR_ADDON_ORDER_CUTOFF_PASSED`. The quantity must be at least 1 and, counting quantities already ordered on other lines for the same add-on, at most `max_qty_per_cover` multiplied by the reservation's `party_size`; a breach yields `ERR_ADDON_QTY_INVALID`. On success the line freezes `unit_price_cents_locked` from the add-on's current `price_cents`, so that later catalogue price edits never disturb an existing booking; copies `requires_kitchen_ack` onto the line as `ack_required`; derives `line_subtotal_cents`, `line_service_charge_cents` and `line_prep_minutes` — the last being the add-on's `prep_minutes_per_unit` multiplied by `qty`; re-runs the whole charge breakdown with per-line rounding; re-runs the kitchen prep aggregation of §3.4; and advances the reservation's `version` by one.

Money arrives through payments taken by a `Guest` or, on the guest's behalf, by a `GuestServices` operator, each carrying only an `amount_cents`. A payment may never exceed the reservation's `balance_due_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`), and the very first payment on a reservation must be at least `deposit_due_cents` (`ERR_PAYMENT_BELOW_DEPOSIT`). A payment on a still-unpaid reservation that brings the cumulative `amount_paid_cents` to at least `deposit_due_cents` but leaves it strictly below `grand_total_cents` writes a `DEPOSIT_CHARGE` row with `memo_code` `GUEST_PREPAY` and moves the money dimension `UNPAID → DEPOSIT_PAID`, with `balance_due_cents` recomputed as `grand_total_cents` less `amount_paid_cents`. A payment that takes the cumulative figure to at least `grand_total_cents` in one go moves the money dimension `UNPAID → FULLY_PAID`, writing a `DEPOSIT_CHARGE` row when the reservation had paid nothing at all beforehand and a `BALANCE_CHARGE` row otherwise, and drives `balance_due_cents` to 0. A later payment that clears the remainder of a deposit-paid reservation moves it `DEPOSIT_PAID → FULLY_PAID`, writing a `BALANCE_CHARGE` row with `memo_code` `GUEST_BALANCE`, driving `balance_due_cents` to 0 and thereby unblocking both completion and transfer. Payments are refused entirely once the seating side has reached `CANCELLED`, `NO_SHOW`, `EXPIRED`, `TRANSFERRED_OUT` or `COMPLETED`, and are refused on a `PENDING` reservation whose hold has already lapsed with `ERR_HOLD_EXPIRED`.

Confirmation is the `Guest` action that turns a paid hold into a real booking, advancing the seating dimension `PENDING → CONFIRMED`. It requires the reservation to still be `PENDING`, the logical clock to be strictly before `hold_expires_at_utc`, the money dimension to read `DEPOSIT_PAID` or `FULLY_PAID` — a still-`UNPAID` reservation is refused with `ERR_DEPOSIT_NOT_SETTLED` — and the owning ticket class not to be `CLOSED`. Confirming clears `hold_expires_at_utc` to null, sets `deposit_frozen` to true and so freezes `deposit_due_cents` against every later add-on or price change, debits `party_size` from the class's `seats_held` and credits the same count to `seats_sold` so that the pool total is unchanged, credits `party_size` to the service's `covers_confirmed`, and advances the reservation's `version` by one.

### 3.4. Dietary Notes, Kitchen Acknowledgement and Prep Load

Dietary information is captured per cover, not per booking. A `Guest` records a note against a reservation by naming the `guest_index` — which cover in the party the note applies to, counted from 1 — together with a `restriction_code`, a clinical `severity`, and optional free-text `note_text` for the kitchen that defaults to the empty string and may run to 500 characters. The index must be at least 1 and at most the reservation's `party_size`, or the capture is refused with `ERR_GUEST_INDEX_OUT_OF_RANGE`. The `restriction_code` is one of `GLUTEN`, `DAIRY`, `SHELLFISH`, `NUT`, `SOY`, `VEGAN`, `PESCATARIAN` or `OTHER`. The `severity` is one of `INFO`, `ALLERGY` or `ANAPHYLAXIS`, and it is the sole input both to the note's prep cost and to the acknowledgement gate.

Each note carries a derived `prep_minutes` read straight off its severity: an `INFO` note costs the kitchen nothing, an `ALLERGY` note costs 6 minutes, and an `ANAPHYLAXIS` note costs 15. A new note begins with `ack_status` `PENDING`, `reject_reason_code` null, `amend_count` at 0 and `acked_by_user_id` null. The three legal acknowledgement states are `PENDING`, `ACKED` and `PREP_REJECTED`, of which only `ACKED` is terminal.

A `KitchenLead` decides a note by supplying a `decision` of either `ACCEPT` or `REJECT`. Accepting moves the note `PENDING → ACKED` and requires three things: the note is still `PENDING`, the owning reservation's seating dimension reads `CONFIRMED`, and the logical clock is strictly before the service's `seating_start_utc`. Acceptance records the acting lead's `X-User-ID` as `acked_by_user_id` and re-derives the reservation's `prep_minutes_total`, which in turn re-tests the service's kitchen-prep capacity window. Rejecting moves the note `PENDING → PREP_REJECTED` and requires the note to be `PENDING` and a `reject_reason_code` to be supplied — one of `CROSS_CONTAMINATION_RISK`, `INGREDIENT_UNAVAILABLE` or `DETAIL_INSUFFICIENT`. The reason code is stored on the note, and from that moment both table assignment and seating for the whole reservation are blocked with `ERR_DIETARY_NOTE_PREP_REJECTED` until the note is amended. Acknowledging a note that is not `PENDING` is refused with `ERR_DIETARY_NOTE_INVALID_STATE`.

The guest's answer to a rejection is an amendment, which moves the note `PREP_REJECTED → PENDING` and may revise the `restriction_code`, the `severity` and the `note_text`. It is permitted only while the note is `PREP_REJECTED` and only while `amend_count` is strictly below 3 — a fourth attempt is refused with `ERR_DIETARY_AMEND_LIMIT`. A successful amendment credits `amend_count` by 1, clears both `reject_reason_code` and `acked_by_user_id` back to null, and re-derives `prep_minutes` from the amended severity. The `PENDING → PREP_REJECTED → PENDING` loop is therefore a genuine cycle, capped at three amendments per note.

The kitchen's real constraint is minutes, and those are aggregated on the reservation as `prep_minutes_total`. It is the sum of three terms: a baseline of the reservation's `party_size` multiplied by the package's `kitchen_prep_minutes_per_cover`; plus the severity minutes of every one of the reservation's dietary notes, counted **regardless of `ack_status`**, because a still-pending allergy consumes kitchen time exactly as an acknowledged one does; plus, over every add-on line on the reservation, the add-on's `prep_minutes_per_unit` multiplied by that line's `qty`. The result is whole minutes with no rounding of any kind. It is recomputed whenever a note is created, acknowledged or amended, whenever an add-on line is appended, and again whenever a table is assigned.

Two gates protect the guest, and both are evaluated on table assignment **and** again on seating. First, every note on the reservation whose `severity` is `ANAPHYLAXIS` must have reached `ack_status` `ACKED`; a single still-pending anaphylaxis note refuses both operations with `ERR_DIETARY_ACK_REQUIRED`. Second, no note on the reservation may be sitting in `PREP_REJECTED`; if one is, both operations are refused with `ERR_DIETARY_NOTE_PREP_REJECTED`. Notes at `INFO` or `ALLERGY` severity do not require acknowledgement to seat — they simply cost minutes.

### 3.5. Working the Floor: Tables, Turns, the Prep Line and the Party That Never Came

Assigning a table is a `RestaurantManager` action carrying a `table_id` and a `seat_from_utc` seating instant. It writes `assigned_table_id` and `seat_from_utc` onto the reservation, advances the reservation's `version` by one, and re-runs the kitchen prep aggregation. Before any of that, four checks fire in the order fixed by §2.11: the safety gates of §3.4 come first, then the table turn interval, then the table's provenance and seat band, then the kitchen's aggregate load.

**Table occupancy is a half-open interval, so adjacency is legal.** The candidate occupancy begins at the proposed `seat_from_utc` and ends at that instant plus the service's `turn_time_minutes` plus the table's own `turn_buffer_minutes`, and the end instant is **excluded** from the interval. Every other reservation already assigned to the same table whose seating dimension reads `CONFIRMED` or `SEATED` occupies an interval computed the same way, from its own `seat_from_utc` plus its service's `turn_time_minutes` plus the table's `turn_buffer_minutes`. The candidate collides with an existing occupancy when the candidate's start falls strictly before that occupancy's end **and** that occupancy's start falls strictly before the candidate's end; any collision is refused with `ERR_TABLE_TURN_CONFLICT`. Because both comparisons are strict, a party starting at exactly the instant another party's occupancy ends does not collide — a table freed at 00:45 may be re-seated at 00:45, but not at 00:44. Reservations that have gone to `CANCELLED`, `NO_SHOW`, `EXPIRED`, `TRANSFERRED_OUT` or `COMPLETED` have released their occupancy and are excluded from the comparison entirely.

The table must also belong to the same restaurant as the reservation's service, failing which the assignment is rejected with `ERR_TABLE_RESTAURANT_MISMATCH`, and the reservation's `party_size` must fall within the table's `seats_min` and `seats_max` inclusive, failing which the rejection is `ERR_TABLE_PARTY_SIZE_MISMATCH`.

**The kitchen prep window is a closed interval, so touching endpoints do collide** — the opposite semantics from the table, and deliberately so, because a prep pass that finishes exactly as another begins still shares the same pass on the line. The candidate's prep window runs from the proposed `seat_from_utc` less the restaurant's `prep_lead_minutes` up to and including that `seat_from_utc`. The aggregate load starts as the candidate's own `prep_minutes_total` and then adds the `prep_minutes_total` of every other reservation **of the same service** that already holds a table assignment and whose seating dimension reads `CONFIRMED` or `SEATED`, provided that reservation's own closed prep window touches or overlaps the candidate's — that is, provided the candidate's window start is at or before the other's window end, and the other's window start is at or before the candidate's window end. If the resulting aggregate is **strictly greater** than the service's `kitchen_prep_capacity_minutes`, the assignment is refused with `ERR_KITCHEN_PREP_OVERSUBSCRIBED`; a load exactly equal to capacity is accepted. Note carefully that the resource being rationed here is the service's kitchen line, an entirely different resource from the table rationed by the turn-interval check, and the two constraints are evaluated independently.

Seating advances the reservation `CONFIRMED → SEATED` and is a `RestaurantManager` action taking no payload. It requires the reservation to be `CONFIRMED`, `assigned_table_id` to be non-null, every `ANAPHYLAXIS` note to be `ACKED`, no note to be in `PREP_REJECTED`, and the logical clock to have reached `seat_from_utc` — an attempt before that instant is refused with `ERR_SEATING_TOO_EARLY`. Seating pins `seat_to_utc` to `seat_from_utc` plus the service's `turn_time_minutes`; until the party is seated, `seat_to_utc` is null.

Completion advances the reservation `SEATED → COMPLETED` and is the point at which the money dimension gates the seating dimension: the reservation must read `FULLY_PAID`, and any outstanding balance refuses the operation with `ERR_BALANCE_OUTSTANDING`. Completing credits the guest's `completed_reservations_count` by 1 — which lifts that guest's waitlist standing everywhere, as §3.8 explains — reconciles the service's `gross_charged_cents` against the reservation's ledger, and advances the reservation's `version` by one.

A party that never arrives is dealt with by a no-show declaration, which advances the reservation `CONFIRMED → NO_SHOW`. It is a `RestaurantManager` action and may not be declared until the logical clock has reached `seat_from_utc` plus the restaurant's `no_show_grace_minutes`; declaring earlier is refused with `ERR_NO_SHOW_TOO_EARLY`. The declaration is expensive for the guest and cascades widely. `cancel_settlement_basis` is set to `NO_SHOW_FULL` and the whole of `amount_paid_cents` is forfeited by writing a single `FORFEITURE` row with `memo_code` `NO_SHOW`, which drives the money dimension to `FORFEITED`. The guest's `no_show_strikes` is credited by 1, depressing that guest's waitlist score on every service, everywhere. `party_size` seats are debited from the class's `seats_sold` and returned to `seats_available`, after which the precedence ladder is re-evaluated; if that re-evaluation moves the class `SOLD_OUT → OPEN`, the highest-ranked eligible waitlist entry is promoted onto the freed seats. The service's `covers_confirmed` is debited by `party_size` and its `forfeited_cents` credited. The reservation's `version` advances by one.

### 3.6. Changing the Name on the Ticket, Handing It On, and Keeping Brokers Out

A prepaid ticket names a guest, and two quite different operations can change who that guest is. A name change edits `primary_guest_name` in place and leaves ownership, money and seats exactly where they were. A transfer mints a whole new reservation for a different `Guest` and moves the cash across. Both are `Guest` actions, both are capped, and both close before the service starts — because both are the doors through which a secondary market would walk if it could.

A name change takes a single `primary_guest_name` and is allowed only while the logical clock is at or before the service's `seating_start_utc` less the restaurant's `name_change_cutoff_minutes`; inside that window the request is refused with `ERR_NAME_CHANGE_CUTOFF_PASSED`. It is further allowed only while the reservation's `name_change_count` is strictly below the restaurant's `max_name_changes`, so a restaurant configured with `max_name_changes` of 2 permits exactly two renames and refuses the third with `ERR_NAME_CHANGE_LIMIT_REACHED`. A successful rename credits `name_change_count` by 1 and advances the reservation's `version` by one. Nothing else moves: no ledger row is written, no seat counter changes, no roll-up is touched.

A transfer is the heavier instrument. It takes a `recipient_guest_id` naming the guest who is to receive the ticket, and an optional `recipient_guest_name` for the name to print on the successor ticket; when `recipient_guest_name` is omitted it defaults to the recipient guest's own `display_name`. Six preconditions guard it, and each has its own refusal:

1. The reservation's seating dimension must read `CONFIRMED`, otherwise `ERR_RESERVATION_INVALID_STATE`.
2. The reservation's money dimension must read `FULLY_PAID` — a deposit-only ticket cannot be handed on — otherwise `ERR_TRANSFER_REQUIRES_FULL_PAYMENT`.
3. The logical clock must be at or before the service's `seating_start_utc` less the restaurant's `transfer_cutoff_minutes`, otherwise `ERR_TRANSFER_CUTOFF_PASSED`. Note that `transfer_cutoff_minutes` and `name_change_cutoff_minutes` are independent knobs: a restaurant may close transfers a week out while still permitting renames an hour before service, or the reverse.
4. The recipient guest's `is_broker_flagged` must be false, otherwise `ERR_RESALE_SUSPECTED`. This is the resale brake, and it is applied to the **recipient**, not the initiator.
5. The reservation's own `transferred_from_reservation_id` must be null, otherwise `ERR_ONWARD_TRANSFER_FORBIDDEN`. A ticket that arrived by transfer is a terminus; chains of length greater than one are structurally impossible, which is what stops a broker from laundering a ticket through intermediaries.
6. The initiating guest's `transfers_initiated_count` must be strictly below the restaurant's `max_transfers_per_guest`, otherwise `ERR_TRANSFER_LIMIT_REACHED`. This counter is lifetime and per guest, not per service.

The recipient must additionally differ from the current holder; naming oneself is refused with `ERR_TRANSFER_TO_SELF`.

A successful transfer advances the predecessor `CONFIRMED → TRANSFERRED_OUT` on the seating dimension and `FULLY_PAID → TRANSFERRED` on the money dimension, and produces six effects. A successor `Reservation` is created for the recipient guest, already in `fulfillment_status` `CONFIRMED` and `payment_status` `FULLY_PAID`, with `transferred_from_reservation_id` pointing back at the predecessor and with an identical `party_size`, an identical `price_locked_per_cover_cents`, an identical set of add-on lines and identical `subtotal_cents`, `service_charge_cents` and `grand_total_cents` — the successor pays what the predecessor paid, not what the class costs today. A `TRANSFER_OUT` `PaymentTransaction` for the full `amount_paid_cents` is written against the predecessor and a matching `TRANSFER_IN` row against the successor, both carrying `memo_code` `TRANSFER_MOVE`, so that cash is conserved exactly across the pair and neither the restaurant nor the platform gains or loses a cent. Every `DietaryNote` on the predecessor is copied to the successor with its `ack_status` reset to `PENDING`, because the kitchen has never seen the new party and must acknowledge afresh. The initiator's `transfers_initiated_count` is credited by 1. The successor's `name_change_count` starts at 0, so a transfer restores a fresh rename budget. And the `TicketClass` seat counters are left entirely untouched — the seats travel with the successor rather than returning to the pool, so `seats_sold` neither rises nor falls and the precedence ladder is not re-evaluated. The predecessor's `version` advances by one.

The response body of a transfer is the **successor** reservation, and that is the only way a caller learns the successor's `id`; the predecessor may afterwards be fetched on its own. Seat-pool reconciliation deliberately counts the successor and excludes the `TRANSFERRED_OUT` predecessor, so the party is counted once rather than twice.

### 3.7. Unwinding a Booking: the Forfeiture Ladder, the Rebooking Fee, the Hold Sweep and the Cancelled Service

Everything that undoes a booking runs through one settlement procedure. A guest cancellation, a no-show declaration, a service cancellation and a lapsed hold all call it, and it is the single place where the platform decides how much of what a guest paid the restaurant keeps. Its evaluation order is pinned, and each step consumes the result of the one before it.

**Step 1 — choose the settlement basis code.** A service cancellation always settles as `RESTAURANT_INITIATED`. A no-show declaration always settles as `NO_SHOW_FULL`. Every other trigger settles on the package's own `forfeiture_basis`, which is either `DEPOSIT_BASIS` or `FULL_TICKET_BASIS`. Whichever code is chosen is recorded on the reservation as `cancel_settlement_basis`, which is null until the reservation settles.

**Step 2 — the short-circuit arms, which bypass the ladder entirely.** If the basis code is `RESTAURANT_INITIATED`, or the trigger is a lapsed hold, or the reservation's `fulfillment_status` is `PENDING`, then the band is 0 basis points, the rebooking fee is 0 cents, the retained amount is 0 cents and the refund is the whole of `amount_paid_cents`. A restaurant-initiated cancellation therefore never forfeits a cent no matter what the package's `forfeiture_schedule_code` says or how close to service it happens; and a still-`PENDING` hold is always settled at zero forfeiture regardless of hours to service, because its seats were never sold. Separately, if the basis code is `NO_SHOW_FULL`, the band is 10000 basis points, the rebooking fee is 0 cents, the retained amount is the whole of `amount_paid_cents` and the refund is 0 cents. Both arms return immediately; steps 3 through 7 do not run.

**Step 3 — hours to service, as an exact decimal.** Subtract the logical clock from the service's `seating_start_utc` and divide by 3600 seconds. This value is compared as an exact decimal and is never truncated or rounded to whole hours: 71.9 hours is inside the 24-hour band of the `STANDARD` ladder, not on the 72-hour edge.

**Step 4 — look up the band, selected by the package's `forfeiture_schedule_code`.** Each ladder is a list of rows tried top to bottom, and the first row whose minimum-hours threshold is met by an at-or-above comparison wins, so an exact band edge always takes the **cheaper** band. The `STANDARD` ladder has three rows: at 72 hours or more the band is 0 basis points; at 24 hours or more it is 5000 basis points; at 0 hours or more it is 10000 basis points. The `STRICT` ladder has four rows: at 168 hours or more the band is 0 basis points; at 72 hours or more it is 5000 basis points; at 24 hours or more it is 8000 basis points; at 0 hours or more it is 10000 basis points. A cancellation at exactly 72.0 hours therefore forfeits nothing under `STANDARD` and half under `STRICT`.

**Step 5 — the basis amount, selected by the package's independent `forfeiture_basis`.** Under `DEPOSIT_BASIS` the basis is the reservation's `deposit_due_cents`; under `FULL_TICKET_BASIS` it is the reservation's `grand_total_cents`. The raw forfeiture is the basis multiplied by the band in basis points, divided by 10000, rounded half up to whole cents. Note that `forfeiture_schedule_code` and `forfeiture_basis` are two independent package knobs: the schedule picks *what fraction*, the basis picks *of what*.

**Step 6 — the rebooking fee, keyed on the forfeiture amount.** The fee band is read off the **raw forfeiture computed in step 5** — not off the basis, not off the band in basis points, and not off the hours to service. The bands are: a raw forfeiture of exactly 0 cents attracts a fee of 0 cents; a raw forfeiture of 9999 cents or less attracts 500 cents; a raw forfeiture of 39999 cents or less attracts 1500 cents; anything above that attracts 3000 cents. Because the fee depends on the output of step 5, it cannot be read off the calendar, and two reservations cancelled at the same hour can attract different fees.

**Step 7 — cap the retention at what the guest actually paid.** The retained amount is the lesser of `amount_paid_cents` and the sum of the raw forfeiture and the rebooking fee; the shortfall is never chased. The refund is `amount_paid_cents` less the retained amount. The retained amount is then credited to the reservation's `forfeited_cents` and the refund to its `refunded_cents`. The input set is the single reservation being settled, and its `amount_paid_cents` already includes any `GOODWILL_REDEMPTION` cents, which are therefore refundable and forfeitable exactly like cash.

The two package bases diverge sharply, and both behaviours are normative. Under `DEPOSIT_BASIS` the band bites only on the deposit, so a mid-ladder cancellation usually still leaves the guest a refund. Under `FULL_TICKET_BASIS` the band bites on the whole `grand_total_cents`, and with a deposit of only a few thousand basis points even the 5000-basis-point band computes a forfeiture larger than everything the guest has actually paid — so the step-7 cap binds, retention saturates at `amount_paid_cents`, and the refund collapses to zero. Worked concretely: two packages identical but for `forfeiture_basis`, a reservation that has paid 11583 cents of a 38610-cent grand total, cancelled at exactly 48.0 hours on the `STANDARD` ladder. Under `DEPOSIT_BASIS` the raw forfeiture is 5792 cents, the fee 500 cents, the retention 6292 cents and the refund 5291 cents, leaving the money dimension `PARTIALLY_REFUNDED`. Under `FULL_TICKET_BASIS` the raw forfeiture is 19305 cents, the fee 1500 cents, the retention caps at 11583 cents and the refund is 0, leaving the money dimension `FORFEITED`. The same reservation cancelled at exactly 72.0 hours on `STANDARD` takes the 0-basis-point band, a 0-cent fee, 0 retention and an 11583-cent refund, leaving it `REFUNDED`.

Those three outcomes are exactly the three money-dimension cancellation transitions, and each may be reached from either state the reservation could have been paid up to — so the edges are `DEPOSIT_PAID → PARTIALLY_REFUNDED` and `FULLY_PAID → PARTIALLY_REFUNDED`, `DEPOSIT_PAID → REFUNDED` and `FULLY_PAID → REFUNDED`, `DEPOSIT_PAID → FORFEITED` and `FULLY_PAID → FORFEITED`. When the settlement yields a refund strictly above zero **and** a retention strictly above zero, the reservation moves to `PARTIALLY_REFUNDED` and exactly one `FORFEITURE` row and one `REFUND` row are written, with `refunded_cents` plus `forfeited_cents` equal to `amount_paid_cents`. When the settlement yields a retention of exactly zero — a 0-basis-point cancellation, a service cancellation, or a lapsed hold — the reservation moves to `REFUNDED`, a single `REFUND` row for the whole of `amount_paid_cents` is written, and `forfeited_cents` stays at 0. When the settlement yields a refund of exactly zero, so that retention has consumed everything paid, the reservation moves to `FORFEITED`, a single `FORFEITURE` row for the whole of `amount_paid_cents` is written, and `refunded_cents` stays at 0. A no-show reaches `FORFEITED` by the same route.

Guest cancellation itself comes in two forms on the seating dimension. `PENDING → CANCELLED` requires only that the reservation still be `PENDING`; it runs the settlement (which short-circuits to zero forfeiture), debits `party_size` from the class's `seats_held` and returns those seats to whichever pool they came from, and moves any linked `WaitlistEntry` to `WITHDRAWN`. `CONFIRMED → CANCELLED` additionally requires the logical clock to be strictly before the reservation's `seat_from_utc` — cancelling at or after the seating instant is refused with `ERR_CANCEL_WINDOW_CLOSED` — and runs the full ladder on the package's `forfeiture_basis` and `forfeiture_schedule_code`, writing at most one `FORFEITURE` row and at most one `REFUND` row, both with `memo_code` `GUEST_CANCEL`. It debits `party_size` from `seats_sold`, returns the seats to `seats_available`, re-evaluates the precedence ladder and promotes the highest-ranked eligible waitlist entry on a `SOLD_OUT → OPEN` transition, debits the service's `covers_confirmed`, credits the service's `refunded_cents` and `forfeited_cents`, recomputes `net_settled_cents`, and advances the reservation's `version` by one. Cancellation is available to the `Guest` who holds the ticket and to `GuestServices` acting on that guest's behalf.

Unclaimed holds are reaped by a sweep, which a `PlatformAdmin` runs against a service and which optionally carries `close_service`. The sweep advances every `PENDING` reservation whose `hold_expires_at_utc` the logical clock has reached along `PENDING → EXPIRED`. For each swept reservation it debits `party_size` from `seats_held` and returns those seats **to the pool they came from** — to `seats_released` when the reservation's `is_release_priced` is true, and to `seats_available` otherwise, which is the whole reason that flag is persisted on the reservation. It re-evaluates the precedence ladder, but — unlike a cancellation or a no-show — it triggers **no waitlist promotion whatsoever**, so seats recovered by a sweep sit in the pool until someone buys them or a release run offers them. Anything the guest had paid is refunded in full with `memo_code` `HOLD_LAPSE`. And when the swept reservation was itself minted by a waitlist offer, that `WaitlistEntry` returns to `WAITING` with its `offer_round` credited by 1, or moves to `EXPIRED` instead once `offer_round` has reached the restaurant's `max_offer_rounds`.

Passing `close_service` as true additionally moves the service `PUBLISHED → CLOSED`. That requires the service to be `PUBLISHED`, the logical clock to be at or after the service's `seating_end_utc`, and no reservation of the service to remain in `PENDING` — which is why the sweep runs first, in the same call. Closing moves every `TicketClass` of the service to `CLOSED` and recomputes the service's `net_settled_cents` as `gross_charged_cents` less `refunded_cents`.

Cancelling a service is a `RestaurantManager` action that optionally records a `reason_code`. From `DRAFT` it merely moves every `TicketClass` of the service to `CLOSED`. From `PUBLISHED` — the `PUBLISHED → CANCELLED` edge — it unwinds everything: every reservation in `PENDING` or `CONFIRMED` moves to `CANCELLED` with `cancel_settlement_basis` set to `RESTAURANT_INITIATED`; each such reservation is refunded in full by a `REFUND` row for `amount_paid_cents` less any `refunded_cents` already recorded, with `memo_code` `SERVICE_CANCEL`, and its `forfeited_cents` stays at 0; every `WaitlistEntry` in `WAITING` or `OFFERED` moves to `WITHDRAWN`; every `TicketClass` moves to `CLOSED`; and the service's `refunded_cents` and `net_settled_cents` are recomputed. Both `CLOSED` and `CANCELLED` are terminal for a service.

Refunds leave a permanent mark on the guest. After **every** `REFUND` row is written — from any trigger, at any restaurant — the refunded amount is credited to that guest's `lifetime_refunded_cents`. If the running lifetime total then stands **strictly greater than** the restaurant's `refund_scrutiny_threshold_cents`, the guest's `refund_scrutiny_flag` is raised to true, and every one of that guest's waitlist entries **whose status is `WAITING` at that moment** has its `priority_penalty_applied` set to true and its `priority_score` re-derived. The comparison is strict: a lifetime total exactly equal to the threshold does not raise the flag. The flag is one-way and is never cleared. `FORFEITURE` and `FORFEITURE_REVERSAL` rows do not move `lifetime_refunded_cents` at all, and entries already `OFFERED`, `CLAIMED`, `EXPIRED` or `WITHDRAWN` when the threshold is crossed are never penalised retroactively.

### 3.8. The Waitlist: Ranking, Release Runs, Offers and Claims

A `Guest` joins a waitlist by naming a `service_id`, a `guest_id` and a `party_size` between 1 and 20, and may optionally narrow the request to a single `requested_package_id`, in which case the entry is only ever eligible for ticket classes of that package; left null, the entry is eligible for any class of the service. A new entry starts `WAITING` with `offer_round` at 0, `offered_reservation_id` and `offer_expires_at_utc` null, and its `priority_score` computed immediately. Its `priority_penalty_applied` is seeded from the joining guest's **current** `refund_scrutiny_flag`, so a guest who is already under scrutiny joins pre-penalised. `WAITING` and `OFFERED` are the live states; `CLAIMED`, `EXPIRED` and `WITHDRAWN` are terminal.

The `priority_score` is a pure ranking key that never enters a money figure. It starts from a base of 1000, adds 50 per cover of the entry's `party_size`, adds 25 for each of the guest's `completed_reservations_count` **capped at 8** so that a hundred past dinners count no more than eight, subtracts 300 for each of the guest's `no_show_strikes`, subtracts 200 if the entry's `priority_penalty_applied` is true, and subtracts 100 for each `offer_round` the entry has already burned through. The result is floored at 0, so a heavily penalised entry bottoms out rather than going negative. It is an integer with no rounding, and it is recomputed on entry creation, on every offer-round change, whenever the owning guest's counters move, and whenever a promotion candidate set is ranked. For a party of 2 with a clean record the score is 1100; one no-show strike takes it to 800; one burned offer round takes it to 1000; a scrutiny penalty takes it to 900.

Which entries are even considered is fixed: only entries whose `status` is `WAITING`, whose `party_size` fits the candidate ticket class's `min_party_size` to `max_party_size` band, and whose `requested_package_id` is null or equal to the candidate class's `package_id`. Entries in `OFFERED`, `CLAIMED`, `EXPIRED` or `WITHDRAWN` are excluded from every candidate set.

How that candidate set is then ordered depends on the service's `waitlist_policy`, and the two policies must be implemented with equal care because they routinely disagree. Under `FAIR_QUEUE` the `priority_score` is still computed and still persisted on the entry, but it is **entirely ignored for ordering**: candidates are ranked by the entry's `created_at` ascending, and ties broken by the guest's `email` ascending. Under `YIELD_WEIGHTED` candidates are ranked by `priority_score` descending, then by the entry's `created_at` ascending, then by the guest's `email` ascending. Concretely, two `WAITING` entries on one service where the first-created entry has a `party_size` of 2 and so a score of 1100 and the second-created entry has a `party_size` of 3 and so a score of 1150, competing for a pool of 3 seats: `FAIR_QUEUE` promotes the earlier entry, `YIELD_WEIGHTED` promotes the larger one. Ordering never consults a random identifier; `created_at` then `email` are the only tie-breaks under either policy.

A release run is a `RestaurantManager` action against a service that dumps unsold inventory into a discounted pool and works the waitlist onto it. It is legal only while the service is `PUBLISHED` and only once the logical clock has reached the service's `seating_start_utc` less its `release_lead_minutes`; firing earlier is refused with `ERR_RELEASE_WINDOW_NOT_OPEN`. The run has **two distinct passes, and the separation is normative**.

The release pass walks the service's ticket classes whose `status` is `OPEN` or `SOLD_OUT`, in `created_at` ascending order. For each, it computes the number of seats to release as the floor of that class's `seats_available` multiplied by the service's `unsold_release_bp`, divided by 10000 — a partial seat is never released — debits that count from `seats_available`, credits it to `seats_released`, adds it to the run's release total, and re-evaluates the class against the precedence ladder. Classes whose `status` is `PAUSED` or `CLOSED` are **skipped entirely** and their `seats_available` is left untouched.

Only once every class has finished releasing does the promotion pass begin, again in `created_at` ascending order. For each class, while its `seats_released` is above zero, the highest-ranked eligible `WAITING` entry under the service's `waitlist_policy` is picked and promoted; the pass stops on that class as soon as no eligible entry fits. The reason the passes are separate rather than interleaved is precisely that an early class must not be able to consume a later class's inventory: if the release and promotion were folded into one loop, the first class would draw the whole waitlist onto its own seats before the later classes had released anything at all.

At the end of the run the service's `release_run_count` is credited by 1, its `seats_released_total` is credited by the run's release total, its `last_release_released_count` is set to that total, and its `last_release_promoted_count` is set to the number of entries promoted. A class that released seats moves `OPEN → RELEASED` or `SOLD_OUT → RELEASED`, and if the promotion pass then draws the whole released pool into holds the same class moves `RELEASED → SOLD_OUT` inside the same request. Worked concretely: a class with `seats_allocated` of 6 carrying one confirmed party of 2, so `seats_sold` 2 and `seats_available` 4, on a service with `unsold_release_bp` of 10000, releases 4 seats and moves `OPEN → RELEASED`; two `WAITING` entries of `party_size` 2 are then both promoted, taking `seats_held` to 4 and `seats_released` back to 0, which drives the class `RELEASED → SOLD_OUT` before the response is written.

Promotion itself moves an entry `WAITING → OFFERED` and is a system action with no endpoint of its own — it fires from a release run, or from a cancel-driven or no-show-driven `SOLD_OUT → OPEN` transition. It requires the entry to be `WAITING`, its `party_size` to fit the candidate class's band, the candidate class to hold enough seats in the drawing pool for the whole party, the `requested_package_id` to be null or matching, and the entry's `offer_round` to be strictly below the restaurant's `max_offer_rounds`. It mints a `PENDING` `Reservation` for the entry's guest, stores its id on `offered_reservation_id`, credits `party_size` to the class's `seats_held`, debits the same count from the drawing pool, and sets `offer_expires_at_utc` to the logical clock plus the restaurant's `offer_ttl_minutes`.

**Which pool the seats are drawn from is pinned, and it decides the price the guest will pay.** A release-run promotion draws **only** from `seats_released` and mints a hold with `is_release_priced` true, so the guest is quoted the discounted `release_price_per_cover_cents`. A cancel-driven or no-show-driven promotion draws **only** from `seats_available` and mints a hold with `is_release_priced` false, so the guest is quoted the full `list_price_per_cover_cents`. A release-run promotion never reaches into `seats_available`, and a cancellation-driven promotion never reaches into `seats_released`. Because `offer_ttl_minutes` is constrained to be at or below `hold_ttl_minutes`, the offer always lapses before the hold reservation it minted.

An offer that lapses does not necessarily end the entry's chances. The sweep of §3.7 handles both outcomes, and which one applies is decided arithmetically. When the entry is `OFFERED`, the logical clock has reached `offer_expires_at_utc`, and `offer_round` plus one is **strictly below** the restaurant's `max_offer_rounds`, the entry cycles `OFFERED → WAITING`: its `offer_round` is credited by 1, its `offered_reservation_id` and `offer_expires_at_utc` are cleared to null, and its `priority_score` is re-derived — falling by 100 per elapsed round, which under `YIELD_WEIGHTED` steadily demotes an entry that keeps failing to claim while under `FAIR_QUEUE` it changes nothing about that entry's place in line. This is the cycle edge, and an entry may loop `WAITING → OFFERED → WAITING` repeatedly. When instead `offer_round` plus one **equals** `max_offer_rounds`, the entry terminates `OFFERED → EXPIRED`: `offer_round` is credited by 1 and the entry permanently stops being an eligible promotion target. Unlike the cycle branch, the termination branch clears nothing: `offered_reservation_id` keeps pointing at the hold that just lapsed and `offer_expires_at_utc` keeps the instant that offer expired at, both left exactly as they stood. That is the cycle's termination condition.

Claiming is the `Guest` action that secures an outstanding offer, moving the entry `OFFERED → CLAIMED`. It requires the entry to be `OFFERED`, the logical clock to be strictly before `offer_expires_at_utc` — otherwise `ERR_OFFER_EXPIRED` — the offered reservation to still be `PENDING`, and the offered reservation's ticket class to be in `OPEN`, `RELEASED` or `SOLD_OUT`. A claim is not one of the operations §2.11 item 17 guards, so the offered reservation's own `fulfillment_status` is tested **after** the entry-status and offer-expiry checks rather than at item 17's rung, and an offered reservation that has left `PENDING` is refused with `ERR_RESERVATION_INVALID_STATE`. The class-sellability check of item 15 and the hold-expiry check of item 18 keep their own rungs, the latter — as item 18 states — only reaching a reservation that is still `PENDING`. A `PAUSED` class refuses the claim with `ERR_TICKET_CLASS_NOT_SELLABLE`; `SOLD_OUT` is deliberately claimable, because the offer's own hold is what exhausted the pool in the first place and refusing it would make the offer worthless. Claiming clears `offer_expires_at_utc` and — importantly — leaves the offered reservation `PENDING`: the guest must still pay the deposit and confirm before `hold_expires_at_utc`, and if they do not, the sweep will expire the hold like any other.

Withdrawal is available to the `Guest` from either live state and is also driven by a service cancellation. The `WAITING → WITHDRAWN` edge simply moves the entry to `WITHDRAWN` with no other effect. The `OFFERED → WITHDRAWN` edge additionally cancels the offered `PENDING` reservation and returns its held seats to their originating pool.

### 3.9. Contesting a Settlement: Refund Exceptions, Goodwill Credit and the Two-Person Rule

The forfeiture ladder is deliberately unsentimental, so there is a second, human channel above it. A guest who believes a settlement was wrong files a refund exception; a `GuestServices` operator adjudicates it; and where the operator agrees but cannot release the whole amount asked for, a compensating goodwill credit closes the gap. Every step of that channel is governed by segregation of duties: whoever files may not decide, and whoever decides may not issue.

An exception is filed against a settled reservation by a `Guest` or by `GuestServices` on that guest's behalf. It names the `reservation_id`, a `reason_code` — one of `MEDICAL`, `TRAVEL_DISRUPTION`, `KITCHEN_ERROR`, `WEATHER` or `OTHER` — and `requested_cents`, the additional refund asked for **on top of** whatever `refunded_cents` has already been returned. The request must be at least 1 cent and may not exceed the reservation's `amount_paid_cents` less its `refunded_cents`, which is the money still sitting with the restaurant; asking for more is refused with `ERR_REFUND_REQUEST_EXCEEDS_PAID`. Filing records the acting operator's `X-User-ID` as `requested_by_user_id`, which is precisely the id that is thereafter barred from deciding it. A new exception starts in `REQUESTED` with `decided_by_user_id` null, `approved_cents` 0, `shortfall_cents` 0 and `decision_note_code` null. `APPROVED` and `DENIED` are both terminal.

Adjudication is a `GuestServices` action carrying a `decision` of `APPROVED` or `DENIED`, a `decision_note_code` — one of `POLICY_EXCEPTION`, `PARTIAL_GOODWILL`, `EVIDENCE_INSUFFICIENT` or `OUT_OF_POLICY` — and, on approval, an `approved_cents` amount. Both arms require the exception to still be `REQUESTED`, otherwise `ERR_REFUND_EXCEPTION_ALREADY_DECIDED`, and both require the acting `X-User-ID` to differ from `requested_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The two arms then diverge completely, and the asymmetry is intentional: approval touches three entities, denial touches none.

The `REQUESTED → APPROVED` arm additionally requires `approved_cents` to be strictly above 0 and at most `requested_cents` — more is refused with `ERR_APPROVED_EXCEEDS_REQUESTED` — and at most the reservation's current `forfeited_cents`, so that a reversal can never manufacture cash that was never retained; more is refused with `ERR_APPROVED_EXCEEDS_FORFEITED`. On approval, `approved_cents` and `decision_note_code` are stored and `shortfall_cents` is derived as `requested_cents` less `approved_cents`. The reservation is credited a `FORFEITURE_REVERSAL` row of `approved_cents` and debited a `REFUND` row of the same `approved_cents`, both with `memo_code` `REFUND_EXCEPTION`, which keeps the signed ledger sum aligned with `amount_paid_cents` less `refunded_cents` less `forfeited_cents`; the reservation's `forfeited_cents` is debited and its `refunded_cents` credited by `approved_cents`. Because a `REFUND` row was written, the guest's `lifetime_refunded_cents` is credited and the scrutiny threshold of §3.7 is re-tested, which may raise `refund_scrutiny_flag` and cascade into that guest's `WAITING` waitlist entries. And when `shortfall_cents` lands above 0, a goodwill credit becomes issuable up to that amount.

The `REQUESTED → DENIED` arm requires nothing beyond the state check and the segregation check. On denial, `approved_cents` stays at 0 and `shortfall_cents` becomes the whole of `requested_cents`. No `PaymentTransaction` row of any kind is written, no reservation field moves, no guest counter moves, and — despite the non-zero `shortfall_cents` — no goodwill credit may be issued at all, because issuance requires an `APPROVED` exception and a `DENIED` one is refused with `ERR_REFUND_EXCEPTION_NOT_APPROVED`. The denial arm's `shortfall_cents` is a record of what was asked and refused, not a spendable balance.

Approval is also the only mechanism in the whole API that re-opens a terminal money state, and it does so through two compensating transitions on the reservation's payment dimension. `FORFEITED → PARTIALLY_REFUNDED` fires when the approval covers only part of what was forfeited, that is when `approved_cents` sits strictly between 0 and `forfeited_cents`. `PARTIALLY_REFUNDED → REFUNDED` fires when `approved_cents` equals `forfeited_cents` exactly, at which point `forfeited_cents` becomes 0 and `refunded_cents` becomes the whole of `amount_paid_cents`.

A goodwill credit is issued by `GuestServices` against a decided exception, naming the `refund_exception_id`, an `issued_cents` face value and an `expires_at_utc`. The exception must be in `APPROVED`. The `issued_cents` must be at least 1 and may not exceed the **smaller** of the restaurant's `goodwill_credit_cap_cents` and the exception's `shortfall_cents`; exceeding either is refused with `ERR_GOODWILL_EXCEEDS_CAP`. The `expires_at_utc` must be strictly after the logical clock at issue time. Issuance copies `guest_id` and `restaurant_id` from the exception's reservation and its service, so a credit is scoped to one guest at one restaurant; records the acting `X-User-ID` as `issued_by_user_id`, which must differ from the exception's `decided_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; and initialises `remaining_cents` to `issued_cents` with `redeemed_cents` and `revoked_cents` at 0 and `status` at `ISSUED`.

A credit's four money figures are kept coherent by one derivation. `redeemed_cents` is the sum of `amount_cents` over `PaymentTransaction` rows whose `kind` is `GOODWILL_REDEMPTION` and whose `goodwill_credit_id` is this credit — redemptions against other credits of the same guest are excluded. `remaining_cents` is `issued_cents` less `redeemed_cents` less `revoked_cents`. **Invariant I3** holds at all times: `issued_cents` equals `redeemed_cents` plus `revoked_cents` plus `remaining_cents`. The `status` is then chosen by a **pinned precedence order**, evaluated top to bottom, first match winning: `REVOKED` if `revoked_cents` is above 0; otherwise `EXHAUSTED` if `remaining_cents` is 0; otherwise `PARTIALLY_REDEEMED` if `redeemed_cents` is strictly between 0 and `issued_cents`; otherwise `ISSUED`. The order matters: a credit that was half redeemed and then revoked reads `REVOKED`, not `PARTIALLY_REDEEMED`, because the revocation test runs first. Worked concretely: an exception requests 6292 cents and 3000 are approved, leaving a `shortfall_cents` of 3292; a 3292-cent credit is issued, carrying a 3292-cent liability; revoking it in full sets `revoked_cents` to 3292 and `remaining_cents` to 0, giving `status` `REVOKED` and a liability back at 0. `EXHAUSTED` and `REVOKED` are terminal.

Redeeming a credit is done by the `Guest` or by `GuestServices`, naming the target `reservation_id`, an `amount_cents` and an `expected_goodwill_credit_version`. The credit must not be `REVOKED` — a redemption against a revoked credit is refused with `ERR_GOODWILL_CREDIT_INVALID_STATE`, while an exhausted credit instead falls through to the dedicated `ERR_GOODWILL_CREDIT_EXHAUSTED`, which fires whenever `remaining_cents` is not strictly above 0. The logical clock must be strictly before the credit's `expires_at_utc`, otherwise `ERR_GOODWILL_CREDIT_EXPIRED`. The target reservation must belong to the credit's `guest_id` and its service must belong to the credit's `restaurant_id`, otherwise `ERR_GOODWILL_TARGET_MISMATCH` — credit does not travel between guests or between restaurants. The `amount_cents` may not exceed `remaining_cents`, otherwise `ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING`, and may not exceed the target reservation's `balance_due_cents`, otherwise `ERR_GOODWILL_EXCEEDS_BALANCE_DUE`, so credit can settle a bill but never overpay one. A successful redemption writes a `GOODWILL_REDEMPTION` `PaymentTransaction` of `amount_cents` on the target reservation with `memo_code` `CREDIT_APPLIED` and `goodwill_credit_id` set, credits `redeemed_cents` and debits `remaining_cents`, raises the reservation's `amount_paid_cents` — possibly advancing its `payment_status` all the way to `FULLY_PAID` — and advances the credit's `version` by one. Redeeming strictly less than `remaining_cents` moves the credit `ISSUED → PARTIALLY_REDEEMED`; redeeming exactly `remaining_cents` moves it `ISSUED → EXHAUSTED` or `PARTIALLY_REDEEMED → EXHAUSTED`. Note that because redeemed credit lands in `amount_paid_cents` like cash, it is subsequently refundable and forfeitable like cash.

Revoking a credit claws back only the unredeemed remainder. It is a `GuestServices` action that may optionally record a `reason_code`, and it requires the credit to be in `ISSUED` or `PARTIALLY_REDEEMED` — attempting it on an already `EXHAUSTED` or `REVOKED` credit is refused with `ERR_GOODWILL_CREDIT_INVALID_STATE` — and requires the acting `X-User-ID` to differ from `issued_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Revocation sets `revoked_cents` to whatever `remaining_cents` stood at and sets `remaining_cents` to 0, so invariant I3 still holds, and moves the credit along `ISSUED → REVOKED` or `PARTIALLY_REDEEMED → REVOKED` as its prior state dictates. It writes **no** `PaymentTransaction` row at all: cents the guest has already spent stay spent, on the reservations they were spent against.

### 3.10. Suspending Sales, Resuming Them, and the Status Moves Nobody Requests

A ticket class's `status` moves for two different reasons, and both must be implemented. Some moves are requested outright by a `RestaurantManager`; the rest are consequences of the precedence ladder of §2.6 firing after a seat moved, with no endpoint of their own.

Pausing is the requested suspension. It advances the class `OPEN → PAUSED`, requires the class to be `OPEN` — any other status is refused with `ERR_TICKET_CLASS_INVALID_STATE` — and takes no payload. A paused class stops accepting new reservations and stops being an eligible waitlist promotion target, and it is skipped entirely by a release run. Crucially, pausing **releases nothing**: `seats_available`, `seats_held`, `seats_sold` and `seats_released` all stand exactly as they were, which is what makes `PAUSED` sticky at the top of the ladder rather than a state the arithmetic can fall out of.

Resuming requires the class to be `PAUSED` and the owning service to be `PUBLISHED` — a class of a service that has since left `PUBLISHED` cannot be resumed, and the attempt is refused with `ERR_SERVICE_NOT_PUBLISHED`. Resuming writes no seat counter of its own; it simply lets the ladder run again, and the class lands on exactly one of three states according to the pools as they stand at that moment. When `seats_released` is above 0 the class takes `PAUSED → RELEASED`. When `seats_released` is 0 and `seats_available` is above 0 it takes `PAUSED → OPEN`. When both are 0 it takes `PAUSED → SOLD_OUT`. A class paused while it still held released inventory therefore comes back as `RELEASED`, not as `OPEN`, exactly as the ladder's precedence dictates.

The remaining moves are system-driven, fired by the ladder after every seat move on the class, and no caller ever asks for them directly. `OPEN → SOLD_OUT` fires after any seat-consuming write — a direct reservation, a waitlist claim, a release-run promotion — that leaves `seats_available` at 0 and `seats_released` at 0; from then on, attempts to hold seats on the class fail with `ERR_TICKET_CLASS_NOT_SELLABLE`. `RELEASED → SOLD_OUT` fires on the same condition when the class was sitting on released inventory that a promotion or a sale has now drained, and it can happen inside the same release-run request that created that inventory; the class merely stops being an eligible promotion target. Going the other way, `SOLD_OUT → OPEN` fires after any seat-restoring write that leaves `seats_available` above 0 and `seats_released` at 0 — and this is the edge that carries the promotion asymmetry of §3.8: when the restoring write was a cancellation or a no-show the highest-ranked eligible waitlist entry is promoted onto the freed seats, whereas when it was a hold expiry nothing is promoted at all. `RELEASED → OPEN` fires after a seat-restoring write that leaves `seats_released` at 0 and `seats_available` above 0, and its consequence is a pricing one: subsequent sales revert to list price, minting holds with `is_release_priced` false. `OPEN → RELEASED` and `SOLD_OUT → RELEASED` are the release-run edges of §3.8, and both require `seats_released` to stand above 0 once the run's release pass has finished.

Finally, every live status funnels into the one terminal state when the owning service stops trading. `OPEN → CLOSED`, `PAUSED → CLOSED`, `SOLD_OUT → CLOSED` and `RELEASED → CLOSED` all fire as system consequences of a service cancellation, or of a hold sweep called with `close_service` true, and each carries no side effect of its own beyond the status change itself — the money and seat consequences belong to the service-level unwind described in §3.7. Note that `PAUSED → CLOSED` exists, so `PAUSED` is sticky against everything except an explicit resume and the death of its service. `CLOSED` is terminal: a closed class never sells, never promotes and never reopens.

## 4. Endpoint Definitions

Every endpoint below is served under the API root with no version or namespace prefix. Endpoints that bring a new resource into existence answer with HTTP 201; endpoints that read or modify an existing resource answer with HTTP 200. The response body always follows the envelope of §2.2, and unless a section above says otherwise the `data` field carries the created or updated resource. Note the deliberate exceptions: a transfer returns the **successor** reservation rather than the reservation it was called on, a goodwill redemption returns the ledger row it wrote rather than the credit, and the clock endpoint returns an empty object. All list endpoints accept the `limit` and `offset` query parameters of §2.3, and every filter listed in a list endpoint's description is an optional query parameter that narrows the result set; combining several filters narrows it further, and each filter also serves as the reverse index by which children of a parent are discovered.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/restaurants` | register a restaurant and its ticketing policy knobs | PlatformAdmin |
| GET | `/restaurants/{id}` | read one restaurant | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/restaurants` | list restaurants | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/restaurants/{id}/tables` | list the tables of a restaurant (reverse index for Table.restaurant_id) | PlatformAdmin, RestaurantManager, KitchenLead |
| GET | `/restaurants/{id}/experience-packages` | list the experience packages of a restaurant (reverse index for ExperiencePackage.restaurant_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/restaurants/{id}/add-ons` | list the add-ons of a restaurant (reverse index for AddOn.restaurant_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/restaurants/{id}/services` | list the services of a restaurant (reverse index for Service.restaurant_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/tables` | create a table with its seat band and turn buffer | RestaurantManager |
| GET | `/tables/{id}` | read one table | PlatformAdmin, RestaurantManager, KitchenLead |
| POST | `/experience-packages` | create a multi-course experience package with its prepayment and forfeiture policy | RestaurantManager |
| GET | `/experience-packages/{id}` | read one experience package | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/add-ons` | create a bookable add-on with its prep cost and order cutoff | RestaurantManager |
| GET | `/add-ons/{id}` | read one add-on | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/guests` | register a guest | PlatformAdmin |
| GET | `/guests/{id}` | read one guest, including the counters that feed waitlist ranking | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| GET | `/guests` | list guests | PlatformAdmin, RestaurantManager, GuestServices |
| POST | `/services` | create a service (one seating date and meal period) in DRAFT | RestaurantManager |
| GET | `/services/{id}` | read one service, including its money rollups and release-run counters | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/services` | list services | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/services/{id}/publish` | move a DRAFT service to PUBLISHED, opening its ticket classes for sale | RestaurantManager |
| POST | `/services/{id}/demand-tier` | re-tier a service, which re-prices every unsold cover on every one of its ticket classes | RestaurantManager |
| POST | `/services/{id}/cancel` | cancel a service; every live reservation is refunded in full and every live waitlist entry is withdrawn | RestaurantManager |
| POST | `/services/{id}/release-run` | release unsold inventory close to service and promote waitlist entries onto the released seats | RestaurantManager |
| POST | `/services/{id}/hold-sweep` | expire every lapsed PENDING hold on the service, recycle the seats, and optionally close the service | PlatformAdmin |
| POST | `/ticket-classes` | allocate seats of a service to an experience package as a sellable ticket class | RestaurantManager |
| GET | `/ticket-classes/{id}` | read one ticket class, including the full seat pool breakdown | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/ticket-classes` | list ticket classes (reverse index for TicketClass.service_id and TicketClass.package_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/ticket-classes/{id}/price-quote` | re-derive and return the class with a freshly computed sell_through_bp, list_price_per_cover_cents and release_price_per_cover_cents | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| POST | `/ticket-classes/{id}/pause` | suspend sales on a ticket class without releasing its seats | RestaurantManager |
| POST | `/ticket-classes/{id}/resume` | resume sales on a paused ticket class, re-deriving its status from the seat pool | RestaurantManager |
| POST | `/reservations` | hold seats on a ticket class, locking the quoted per-cover price | Guest |
| GET | `/reservations/{id}` | read one reservation with both state dimensions and the full money breakdown | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/reservations` | list reservations (reverse index for service_id, ticket_class_id, guest_id, assigned_table_id and transferred_from_reservation_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/reservations/{id}/dietary-notes` | list the dietary notes of a reservation (reverse index for DietaryNote.reservation_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/reservations/{id}/payments` | take a prepayment (deposit or balance) against the reservation | Guest, GuestServices |
| POST | `/reservations/{id}/confirm` | convert a paid hold into a confirmed booking and freeze the deposit | Guest |
| POST | `/reservations/{id}/add-ons` | append an add-on line to the reservation, re-running the per-line service charge | Guest |
| POST | `/reservations/{id}/dietary-notes` | capture a dietary note for one cover in the party | Guest |
| POST | `/reservations/{id}/assign-table` | assign a table and a seating instant, testing both the table turn interval and the aggregate kitchen prep window | RestaurantManager |
| POST | `/reservations/{id}/seat` | seat the party, pinning the end of its turn | RestaurantManager |
| POST | `/reservations/{id}/complete` | complete a seated reservation; refused while any balance is outstanding | RestaurantManager |
| POST | `/reservations/{id}/no-show` | declare a no-show after the grace period, forfeiting everything paid | RestaurantManager |
| POST | `/reservations/{id}/cancel` | cancel a hold or a confirmed booking, running the forfeiture ladder and the rebooking-fee band | Guest, GuestServices |
| POST | `/reservations/{id}/name-change` | change the primary guest name on a ticket, subject to the per-reservation cap and the cutoff | Guest |
| POST | `/reservations/{id}/transfer` | transfer a fully paid ticket to another guest, minting a successor reservation and moving the cash | Guest |
| GET | `/reservation-add-ons/{id}` | read one add-on line with its independently rounded service charge | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/reservation-add-ons` | list add-on lines (reverse index for ReservationAddOn.reservation_id and add_on_id) | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| GET | `/dietary-notes/{id}` | read one dietary note | PlatformAdmin, RestaurantManager, KitchenLead, GuestServices, Guest |
| POST | `/dietary-notes/{id}/ack` | kitchen acknowledgement of a dietary note, either accepting it or rejecting it back to the guest | KitchenLead |
| POST | `/dietary-notes/{id}/amend` | amend a prep-rejected note and send it back to the kitchen | Guest |
| GET | `/payment-transactions/{id}` | read one immutable ledger row | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| GET | `/payment-transactions` | list ledger rows in created_at order (reverse index for PaymentTransaction.reservation_id and goodwill_credit_id) | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| POST | `/waitlist-entries` | join the waitlist for a service, optionally restricted to one experience package | Guest |
| GET | `/waitlist-entries/{id}` | read one waitlist entry with its current offer round and score | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| GET | `/waitlist-entries` | list waitlist entries (reverse index for service_id, guest_id, requested_package_id and offered_reservation_id) | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| POST | `/waitlist-entries/{id}/claim` | claim an outstanding offer, keeping its hold reservation alive for payment | Guest |
| POST | `/waitlist-entries/{id}/withdraw` | leave the waitlist, cancelling any outstanding offer hold | Guest |
| POST | `/refund-exceptions` | file a refund exception against a settled reservation | Guest, GuestServices |
| GET | `/refund-exceptions/{id}` | read one refund exception | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| GET | `/refund-exceptions` | list refund exceptions (reverse index for RefundException.reservation_id) | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| POST | `/refund-exceptions/{id}/decide` | approve or deny a refund exception; approval partially reverses the forfeiture | GuestServices |
| POST | `/goodwill-credits` | issue a goodwill credit against the unapproved shortfall of a decided exception | GuestServices |
| GET | `/goodwill-credits/{id}` | read one goodwill credit with its issued/redeemed/revoked/remaining breakdown | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| GET | `/goodwill-credits` | list goodwill credits (reverse index for guest_id, restaurant_id and refund_exception_id) | PlatformAdmin, RestaurantManager, GuestServices, Guest |
| POST | `/goodwill-credits/{id}/redemptions` | redeem part or all of a goodwill credit against a reservation balance | Guest, GuestServices |
| POST | `/goodwill-credits/{id}/revoke` | claw back the unredeemed remainder of a goodwill credit | GuestServices |
| POST | `/_clock/set_current_utc` | set the server's logical clock, which every deadline, cutoff, expiry and forfeiture-ladder comparison reads | PlatformAdmin |

## 5. Error Code Catalogue

Every rejection returns the error envelope of §2.2 with the `error_id` set to one of the identifiers below and the HTTP status shown beside it. Where several checks could reject the same request, the one that fires is fixed by the priority ladder of §2.11.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RESTAURANT_NOT_FOUND` | 404 |
| `ERR_GUEST_NOT_FOUND` | 404 |
| `ERR_TABLE_NOT_FOUND` | 404 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_SERVICE_NOT_FOUND` | 404 |
| `ERR_TICKET_CLASS_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_RESERVATION_ADDON_NOT_FOUND` | 404 |
| `ERR_DIETARY_NOTE_NOT_FOUND` | 404 |
| `ERR_WAITLIST_ENTRY_NOT_FOUND` | 404 |
| `ERR_PAYMENT_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_REFUND_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_GOODWILL_CREDIT_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_STALE_TICKET_CLASS_VERSION` | 412 |
| `ERR_STALE_RESERVATION_VERSION` | 412 |
| `ERR_STALE_GOODWILL_CREDIT_VERSION` | 412 |
| `ERR_SERVICE_NOT_PUBLISHED` | 409 |
| `ERR_SERVICE_INVALID_STATE` | 409 |
| `ERR_TICKET_CLASS_NOT_SELLABLE` | 409 |
| `ERR_TICKET_CLASS_INVALID_STATE` | 409 |
| `ERR_RESERVATION_INVALID_STATE` | 409 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_DEPOSIT_NOT_SETTLED` | 409 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_TRANSFER_REQUIRES_FULL_PAYMENT` | 409 |
| `ERR_WAITLIST_ENTRY_INVALID_STATE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_DIETARY_NOTE_INVALID_STATE` | 409 |
| `ERR_REFUND_EXCEPTION_ALREADY_DECIDED` | 409 |
| `ERR_REFUND_EXCEPTION_NOT_APPROVED` | 409 |
| `ERR_GOODWILL_CREDIT_INVALID_STATE` | 409 |
| `ERR_GOODWILL_CREDIT_EXHAUSTED` | 409 |
| `ERR_GOODWILL_CREDIT_EXPIRED` | 409 |
| `ERR_INSUFFICIENT_SEATS` | 409 |
| `ERR_TABLE_TURN_CONFLICT` | 409 |
| `ERR_DIETARY_ACK_REQUIRED` | 422 |
| `ERR_DIETARY_NOTE_PREP_REJECTED` | 422 |
| `ERR_DIETARY_AMEND_LIMIT` | 422 |
| `ERR_TABLE_RESTAURANT_MISMATCH` | 422 |
| `ERR_TABLE_PARTY_SIZE_MISMATCH` | 422 |
| `ERR_PACKAGE_RESTAURANT_MISMATCH` | 422 |
| `ERR_ADDON_RESTAURANT_MISMATCH` | 422 |
| `ERR_GOODWILL_TARGET_MISMATCH` | 422 |
| `ERR_NO_SHOW_TOO_EARLY` | 422 |
| `ERR_SEATING_TOO_EARLY` | 422 |
| `ERR_NAME_CHANGE_CUTOFF_PASSED` | 422 |
| `ERR_TRANSFER_CUTOFF_PASSED` | 422 |
| `ERR_ADDON_ORDER_CUTOFF_PASSED` | 422 |
| `ERR_RELEASE_WINDOW_NOT_OPEN` | 422 |
| `ERR_CANCEL_WINDOW_CLOSED` | 422 |
| `ERR_NAME_CHANGE_LIMIT_REACHED` | 422 |
| `ERR_RESALE_SUSPECTED` | 422 |
| `ERR_ONWARD_TRANSFER_FORBIDDEN` | 422 |
| `ERR_TRANSFER_LIMIT_REACHED` | 422 |
| `ERR_TRANSFER_TO_SELF` | 422 |
| `ERR_PARTY_SIZE_OUT_OF_BAND` | 422 |
| `ERR_GUEST_INDEX_OUT_OF_RANGE` | 422 |
| `ERR_ADDON_QTY_INVALID` | 422 |
| `ERR_SERVICE_CAPACITY_EXCEEDED` | 422 |
| `ERR_DUPLICATE_ACTIVE_RESERVATION` | 422 |
| `ERR_DUPLICATE_WAITLIST_ENTRY` | 422 |
| `ERR_OFFER_ROUNDS_EXHAUSTED` | 422 |
| `ERR_KITCHEN_PREP_OVERSUBSCRIBED` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 402 |
| `ERR_PAYMENT_BELOW_DEPOSIT` | 402 |
| `ERR_REFUND_REQUEST_EXCEEDS_PAID` | 402 |
| `ERR_APPROVED_EXCEEDS_REQUESTED` | 402 |
| `ERR_APPROVED_EXCEEDS_FORFEITED` | 402 |
| `ERR_GOODWILL_EXCEEDS_CAP` | 402 |
| `ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING` | 402 |
| `ERR_GOODWILL_EXCEEDS_BALANCE_DUE` | 402 |
