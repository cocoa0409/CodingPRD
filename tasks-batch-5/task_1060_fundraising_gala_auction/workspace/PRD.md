# Fundraising Gala & Auction API — Product Requirements Document

## 1. Introduction

A nonprofit's annual gala is, financially speaking, five businesses running at once in a single ballroom over four hours. Tables and seats are sold weeks in advance; corporate sponsors commit dollars and submit artwork for the printed program; a silent auction runs on guests' phones while a live auction runs from the stage; the emcee calls a paddle-raise appeal against a challenge donor's matching gift; and a handful of guests promise multi-installment pledges they will pay over the following year. Every one of those channels eventually lands on a per-guest checkout invoice at the exit table, and the development director wants a single reconciled number by Monday morning.

This document specifies the REST API backing that operation. The service is mounted under `/api` and stores gala events, ticket tables and their holds, registered bidders, sponsors and their program ads, auction lots and bids, paddle-raise gifts, pledges, checkout invoices, payment transactions, donor tax receipts, and reconciliation runs. Two design pressures shape almost every rule that follows. The first is that money must be conserved: a captured payment cascades settlement status down to every lot, ticket and appeal gift it paid for, and voiding that payment must unwind exactly what the capture did. The second is that the same underlying data can legitimately yield two different totals — a proxy-settled auction valuation versus the literal amount a bidder typed, and an accrual view of pledges versus a cash view — so this specification pins which interpretation applies where, and exposes the alternative only as an explicit read.

Because a gala is a live event with a hard settlement deadline, the event itself carries a derived **posture** that gates what its children may do. Early on, everything is permitted; once settlement begins, no new bidding or ticketing may start; once the books are finalized, the event is frozen entirely. Implementers should treat posture as a precondition consulted on nearly every write, not as a reporting field.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. Five roles exist, spelled exactly as follows: `EventOrganizer`, `AuctionManager`, `FinanceOfficer`, `Bidder`, and `Sponsor`. If either header is absent, or if `X-User-Role` is not one of those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the acting role is not among the roles authorized for the requested endpoint (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `EventOrganizer` runs the gala floor: the event lifecycle, tables, guest registration, sponsor records, program-ad review and placement, ticket orders and seating. The `AuctionManager` runs the auction: creating lots, opening and closing them, retracting bids, and capturing paddle-raise gifts from the stage. The `FinanceOfficer` owns the money surface: sponsor confirmation, invoices, payments, receipts, pledges and reconciliation. When `X-User-Role` is any of `EventOrganizer`, `AuctionManager`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `prepared_by_user_id` or `finalized_by_user_id` on a reconciliation run, or as `captured_by_user_id` or `voided_by_user_id` on a payment transaction, where a transition writes it — but it never compares that value to any entity's `id`.

The two remaining roles are entity-backed. When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the acting registered guest; ownership checks on any resource that references a bidder compare that resource's `bidder_id` to `X-User-ID`. Concretely, a guest placing a bid, opening a table hold, releasing a hold, buying a ticket order, updating their own stored payment method, or paying their own invoice must be acting on their own record — for a payment, the check is against the `bidder_id` of the invoice being paid. When `X-User-Role` is `Sponsor`, `X-User-ID` is the `id` of the acting sponsoring organization; ownership checks on any resource that references a sponsor compare that resource's `sponsor_id` to `X-User-ID`, which governs submitting a program ad and resubmitting one after changes were requested. A violation of any of these ownership checks yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Ownership is enforced on exactly these eight write operations: bid placement, table-hold creation, table-hold release, ticket-order creation, payment capture, payment-method update, program-ad submission, and program-ad resubmission. Read endpoints impose no ownership restriction, though the two reconciliation-run reads are limited to `EventOrganizer` and `FinanceOfficer`.

Within the `FinanceOfficer` role, two operations additionally enforce segregation of duties by `X-User-ID`; those rules are stated in §2.9.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1 and no larger than 100; the `offset` parameter defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Lists are returned sorted by `created_at` in ascending order, so the oldest record appears first. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filter before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Timestamps and Versioning

Every stored resource carries a server-minted `id` that is a UUID string with no type prefix — clients never supply it. Every resource also carries a `created_at` timestamp, and every resource in this system additionally carries an `updated_at` timestamp and an integer `version`. Timestamps are ISO 8601 UTC values rendered with three fractional-second digits. The `version` field begins at 1 when the resource is created and increases by exactly 1 on every mutation of that resource, whether the mutation was requested directly or caused as a downstream side effect of an operation on some other resource; `updated_at` is refreshed on the same occasions. Recomputation of a rollup counter on a parent — for example a table's reserved-seat tally or an event's collected-cash total — is itself a mutation of that parent and advances its `version` accordingly.

Nested paths are validated left to right. When a request addresses a child through its parent, the parent identifier is resolved first and, if no such parent exists, the corresponding not-found error is returned before the child identifier is examined at all. The same left-to-right discipline applies to identifiers carried in the request body: after all path identifiers resolve, body-borne foreign keys are checked in the order the endpoint lists them. Each entity type has its own not-found error — `ERR_EVENT_NOT_FOUND`, `ERR_TABLE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_AD_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_PADDLE_RAISE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and `ERR_RUN_NOT_FOUND` — each returned with HTTP 404.

### 2.5. Order of Evaluation for Rejections

When more than one rule could reject a request, the outcome must be deterministic. Checks are applied in the following strict order, and the first failure decides the response.

1. Authentication: headers present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. Role authorization: the acting role appears on the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. Request shape: required fields present, enum members drawn from the declared sets, integers respecting their non-negativity constraints, `limit` inside 1 through 100, `offset` at least 0, a hold's `hold_end_utc` strictly later than its `hold_start_utc`, and a lot's `close_at_utc` strictly later than its `open_at_utc`. Any violation is `ERR_INVALID_REQUEST`.
4. Existence: every referenced resource resolves, left to right as described in §2.4, else the matching not-found error.
5. Ownership for the entity-backed roles, else `ERR_NOT_RESOURCE_OWNER`.
6. The owning event's posture is not `FROZEN`, else `ERR_EVENT_FROZEN`.
7. The owning event's posture is not `RESTRICTED` on the six posture-restricted creation operations, else `ERR_EVENT_RESTRICTED`.
8. The target resource is in a state from which the requested transition is declared, else `ERR_INVALID_STATE`.
9. Bidding-window state on bid placement and bid retraction, else `ERR_ITEM_NOT_OPEN`.
10. Invoice payability on payment capture and invoice void, else `ERR_INVOICE_NOT_PAYABLE`.
11. Reconciliation-run finalization state on run creation and run finalization, else `ERR_RUN_ALREADY_FINALIZED`.
12. Pledge non-terminality on installment recording and lapse, else `ERR_PLEDGE_TERMINAL`.
13. Receipt uniqueness on receipt issuance and payment void, else `ERR_RECEIPT_ALREADY_ISSUED`.
14. The optimistic-concurrency version check on reconciliation-run creation, else `ERR_STALE_EVENT_VERSION`.
15. Segregation of duties on run finalization and payment void, else `ERR_SEGREGATION_OF_DUTIES`.
16. Sponsor confirmation status on ad approval, else `ERR_SPONSOR_NOT_CONFIRMED`.
17. Absence of unpaid invoices on event close and run finalization, else `ERR_OPEN_INVOICES_REMAIN`.
18. Presence of a finalized run on event close, else `ERR_NO_FINALIZED_RUN`.
19. Absence of open lots on settlement start, else `ERR_OPEN_LOTS_REMAIN`.
20. Absence of billed ticket orders on unpublish, else `ERR_TICKET_ORDERS_EXIST`.
21. The lot's bidding window on lot opening, else `ERR_LOT_WINDOW_CLOSED`.
22. The live-channel window conflict on lot opening, else `ERR_LOT_WINDOW_CONFLICT`.
23. The table-hold turnover buffer, else `ERR_TABLE_HOLD_CONFLICT`.
24. The bid increment floor, else `ERR_BID_TOO_LOW`.
25. The program-ad revision budget, else `ERR_AD_REVISION_LIMIT`.
26. Table seat capacity on ticket-order creation and seat assignment, else `ERR_SEAT_CAPACITY_EXCEEDED`.
27. Paddle-number uniqueness on bidder registration, else `ERR_DUPLICATE_PADDLE_NUMBER`.
28. A stored payment method on the acting guest for bidding and paddle-raising, else `ERR_NO_PAYMENT_METHOD`.
29. The captured amount against the invoice balance, else `ERR_PAYMENT_EXCEEDS_BALANCE`.
30. The material-variance override on run finalization, else `ERR_MATERIAL_VARIANCE`.
31. Full funding of a sponsorship commitment on confirmation, else `ERR_SPONSOR_UNDERFUNDED`.

### 2.6. Event Posture: the Gate Over Every Child

Each gala event exposes a computed `posture` alongside its `status`. Posture is never supplied by a client; it is derived, recomputed on every event transition and on every reconciliation-run finalize or reopen, and consulted on every mutation of a child of the event. The derivation is a short ladder evaluated top to bottom. If the event's `status` is `CLOSED`, the posture is `FROZEN`. Otherwise, if the event has at least one reconciliation run whose `status` is `FINALIZED`, the posture is `FROZEN` — runs in `SUPERSEDED` or `PREPARED` are ignored for this purpose. Otherwise, if the event's `status` is `SETTLING`, the posture is `RESTRICTED`. In all remaining cases the posture is `OPEN`.

A `FROZEN` posture rejects every mutating operation on a child of that event with `ERR_EVENT_FROZEN` (HTTP 409), with two carve-outs: the five event lifecycle transitions (publish, unpublish, go-live, start settlement, close) remain available, and so do the three reconciliation-run operations (preparing a run, finalizing it, and reopening it) — otherwise a frozen event could never be reopened.

A `RESTRICTED` posture is narrower. It rejects exactly six creation operations with `ERR_EVENT_RESTRICTED` (HTTP 409): placing a table hold, creating a ticket order, creating an auction lot, opening an auction lot, placing a bid, and recording a paddle-raise gift. Invoices, payments, receipts, pledges and reconciliation all remain permitted under `RESTRICTED`, because settlement is precisely the phase in which that work happens. An `OPEN` posture applies no gate at all.

### 2.7. Money, Precision and Rounding

All monetary amounts in this system are integer counts of cents. There are no fractional-cent balances, and no field is ever expressed in dollars. Where a calculation multiplies a cent amount by a rate and therefore produces a fractional intermediate, the result is rounded half up to a whole cent — a value exactly halfway between two cents rounds away from zero to the larger cent. Two calculations pin *where* that rounding happens, and the placement changes the answer: ticket pricing rounds the per-unit price before multiplying by the unit count (§3.3), and the processing fee rounds the percentage component before the flat component is added (§3.7). Every other money calculation in this document consumes and produces whole cents already and performs no rounding at all.

### 2.8. The Logical Clock

The server keeps a logical clock rather than reading wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and it never falls back to real time under any circumstance. An operator holding the `EventOrganizer`, `AuctionManager` or `FinanceOfficer` role may advance or rewind it by supplying a `to_iso8601` instant, and the endpoint answers with the resulting `current_utc`. Every temporal evaluation in the system reads this clock: early-bird eligibility on ticket pricing, the bidding window on lot opening, the pledge lapse grace window, and the `issued_at_utc` stamped onto a donor receipt.

### 2.9. Optimistic Concurrency and Segregation of Duties

Preparing a reconciliation run is the single operation in this system guarded by optimistic concurrency. The request that creates a run for an event must carry `expected_event_version`, a non-optional integer field holding the `version` of the gala event as the client last observed it. If that value does not equal the event's current `version`, the create is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). This matters because a new run legitimately supersedes any run already in `PREPARED`, so no state precondition would otherwise stop a client from replacing a run it had never seen; the version check is what makes the outcome deterministic. No other endpoint in this specification accepts a version field, and no other endpoint performs a version comparison.

Segregation of duties applies to two `FinanceOfficer` operations, and in both cases the comparison is on `X-User-ID`, not on the role. The operator who prepared a reconciliation run — recorded as `prepared_by_user_id` — may not be the operator who finalizes it. The operator who captured a payment — recorded as `captured_by_user_id` — may not be the operator who voids it. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Gala and Walking It Through the Night

An `EventOrganizer` creates a gala by supplying its public `name`, the `event_start_utc` and `event_end_utc` instants that bracket the evening, and optionally a `match_cap_cents` value naming the largest total matching-gift amount the challenge donor is willing to fund across the whole paddle-raise appeal. When `match_cap_cents` is omitted it defaults to 0, meaning no challenge match is in play; it may never be negative. A new event begins with `status` of `DRAFT` and a `posture` of `OPEN`, and its four rollup counters — `match_awarded_cents`, `gross_collected_cents`, `open_lot_count` and `unpaid_invoice_count` — all start at 0. Events may be listed and filtered by `status`, and a single event is readable by any of the five roles, returning its posture and all four rollups.

The event's `status` moves through `DRAFT`, `PUBLISHED`, `LIVE`, `SETTLING` and finally `CLOSED`, which is terminal, and each hop is an organizer-driven transition. Publication, taking the event `DRAFT → PUBLISHED`, requires that the event currently sit in `DRAFT` and that at least one ticket table already exist for it — a gala with no tables is not sellable. Publication recomputes posture, which remains `OPEN`, and advances the event's `version`.

Publication is reversible, and this is the one backwards edge in the event machine. Unpublishing takes the event `PUBLISHED → DRAFT`, and is permitted only while the event is in `PUBLISHED` and while no ticket order of the event has a `payment_status` of either `INVOICED` or `PAID`; if any billed order exists, the reversal is refused with `ERR_TICKET_ORDERS_EXIST`. Reverting the event cascades: every table hold whose table belongs to this event and whose `status` is `HELD` moves to `RELEASED`, each released hold's table then recomputes its `seats_reserved` tally and its `status`, and the event's own `version` advances.

Going live takes the event `PUBLISHED → LIVE` and is the moment the auction floor opens. It requires the event to be in `PUBLISHED` and requires the logical clock to be strictly earlier than `event_end_utc`. As a cascade, every auction lot of this event whose `listing_status` is `DRAFT` and whose bidding window contains the clock — that is, whose `open_at_utc` is at or before the clock and whose `close_at_utc` is strictly after it — is moved to `OPEN`; the event then recomputes `open_lot_count`, recomputes its posture (which stays `OPEN`), and advances its `version`.

Starting settlement takes the event `LIVE → SETTLING`. Beyond requiring the event to be in `LIVE`, it requires that no lot remain open: `open_lot_count` must be exactly 0, and otherwise the request is refused with `ERR_OPEN_LOTS_REMAIN`. The transition recomputes posture, which becomes `RESTRICTED`, and advances the event's `version`.

Closing the event takes it `SETTLING → CLOSED` and is the last word. Three conditions apply: the event must be in `SETTLING`; `unpaid_invoice_count` must be 0, else `ERR_OPEN_INVOICES_REMAIN`; and at least one reconciliation run of this event must be in `FINALIZED`, else `ERR_NO_FINALIZED_RUN`. Closing sweeps the pledge book: every pledge of this event still in `PROMISED` whose grace window has expired — meaning the clock is strictly later than that pledge's `first_due_utc` plus 30 days — moves to `LAPSED`, each such pledge advancing its own `version`. Posture is then recomputed to `FROZEN` and the event's `version` advances.

### 3.2. Tables, Holds and the Turnover Buffer

Tables are added to a published-or-draft gala by an `EventOrganizer` who supplies the placard `table_name`, the `seat_count` physically at the table (at least 1), the `table_price_cents` charged to buy the whole table, and the `seat_price_cents` charged for a single seat; both prices may be zero but never negative. A table tracks `seats_reserved`, the number of seats consumed by ticket orders of that table whose `payment_status` is anything other than `REFUNDED` and whose `seating_status` is anything other than `RELEASED`. Its `status` is derived from that tally: `AVAILABLE` while `seats_reserved` is strictly below `seat_count`, and `SOLD_OUT` once the two are equal. Tables can be listed filtered by `event_id` and by `status`.

Ahead of the sale, an `EventOrganizer` or the guest themself may put a soft occupation hold on a table by supplying `table_id`, `bidder_id`, and the closed interval `hold_start_utc` through `hold_end_utc`, where the end must be strictly after the start. A hold starts in `HELD` and may end in either `CONSUMED` or `RELEASED`, both terminal. Holds may be listed filtered by `table_id`, by `bidder_id`, and by `status`.

Because a table must be cleared and re-dressed between parties, a fifteen-minute turnover buffer separates holds on the same table. A proposed hold conflicts with an existing `HELD` hold on that same table exactly when the new hold's start falls before the existing hold's end plus fifteen minutes *and* the existing hold's start falls before the new hold's end plus fifteen minutes; when both of those are true the request is refused with `ERR_TABLE_HOLD_CONFLICT`. The comparison is strict on both sides, so two holds separated by exactly fifteen minutes of clearance are accepted. Holds already in `CONSUMED` or `RELEASED` never participate in the check.

Releasing a hold moves it `HELD → RELEASED` and is available to the organizer or to the guest who owns it; the hold must be in `HELD`, its table then recomputes its `status`, and the hold's `version` advances. A hold also leaves `HELD` without anyone asking: it becomes `RELEASED` as part of the unpublish cascade described in §3.1 when its table belongs to the event being reverted, again recomputing the table's `status` and advancing the hold's `version`; and it becomes `CONSUMED` when the guest who placed it buys a ticket order against the same table, which requires the hold to still be in `HELD` and to match both the new order's purchasing guest and the new order's table, and which advances the hold's `version`.

### 3.3. Selling Seats: Ticket Pricing, Capacity and the Seating Axis

Registering a guest is the prerequisite for nearly everything a bidder does. An `EventOrganizer` registers a `Bidder` against an event by supplying `event_id`, the `display_name` printed on the bid sheet, a contact `email` for receipts, and a `paddle_number` of at least 1 that must be unique among the guests of that event — a collision is refused with `ERR_DUPLICATE_PADDLE_NUMBER`. The optional `payment_method_on_file` flag defaults to false and records whether a card is stored; a guest or an organizer may later flip it either way by submitting a new `payment_method_on_file` value, which advances the guest's `version`. A guest also carries `outstanding_balance_cents`, the sum of `balance_due_cents` across that guest's invoices whose `status` is `OPEN`, `PENDING_PAYMENT` or `PARTIALLY_PAID`. Guests can be listed filtered by `event_id`.

A ticket order is created by an organizer or by the purchasing guest, and carries `event_id`, `bidder_id`, `table_id`, an `order_type` of either `TABLE` or `SEAT`, and a `seat_count` of at least 1. A `table_id` is required in both cases, because even a single-seat purchase is priced against a specific table. A `TABLE` order buys the whole table and its `seat_count` must equal the table's own `seat_count` exactly; a mismatch, or any order that would push the table's `seats_reserved` plus the requested `seat_count` above the table's `seat_count`, is refused with `ERR_SEAT_CAPACITY_EXCEEDED`. That same capacity rule is re-checked when seats are assigned.

Pricing runs in five steps at creation time and writes `unit_price_cents`, `subtotal_cents`, `benefit_value_cents` and `early_bird_applied` onto the order. First, the early-bird cutoff is the event's `event_start_utc` less 30 days; the order is early-bird eligible, and `early_bird_applied` is set true, exactly when the logical clock is at or before that cutoff instant — the boundary is inclusive, so an order priced at the cutoff to the millisecond still earns the discount. Second, the base price and unit count follow the order type: a `TABLE` order takes the table's `table_price_cents` as its base with a unit count of one, while a `SEAT` order takes the table's `seat_price_cents` as its base with a unit count equal to the order's `seat_count`. Third, the discount rate is zero for any order that is not early-bird eligible, fifteen percent for an early-bird `TABLE` order, and ten percent for an early-bird `SEAT` order. Fourth — and this ordering is pinned, not incidental — the per-unit price is computed first by multiplying the base price by one minus the discount rate and rounding that product half up to a whole cent, giving `unit_price_cents`; only then is `subtotal_cents` obtained by multiplying `unit_price_cents` by the unit count. Rounding happens exactly once, at the per-unit step; the system never computes a discounted whole-order amount and rounds that instead, and the two orders of operation diverge whenever the base price times the rate lands on a fractional cent. Fifth, `benefit_value_cents` records the non-deductible dinner benefit as 7,500 cents per seat multiplied by the order's `seat_count`.

Order creation also reserves the seats — the table recomputes `seats_reserved` and `status` — and consumes any matching hold as described in §3.2.

A ticket order tracks two independent dimensions on one row, and this separation is deliberate. The billing dimension is `payment_status`, moving `UNBILLED → INVOICED → PAID` and reaching the terminal `REFUNDED` on cancellation; the seating dimension is `seating_status`, moving `UNSEATED → SEATED → RELEASED`. Nothing on the billing axis ever changes `seating_status`, and nothing on the seating axis ever changes `payment_status` — with the single exception of cancellation, which moves both. Assigning seats is an organizer-only action that takes the order `UNSEATED → SEATED` at the order's table and advances the order's `version`, leaving `payment_status` untouched.

Cancellation is an organizer action that drives `payment_status` to `REFUNDED` from either `UNBILLED` or `PAID`, sets `seating_status` to `RELEASED`, causes the order's table to recompute `seats_reserved` — which decreases by that order's `seat_count` — and its `status`, and advances the order's `version`. The billing axis otherwise moves only under cascade: an order goes `UNBILLED → INVOICED` and gains an `invoice_id` when the guest's invoice is finalized (§3.7); it goes `INVOICED → PAID` when that invoice is fully paid; and it reverts `INVOICED → UNBILLED` with its `invoice_id` cleared back to null when the invoice is voided. Every one of those cascade hops advances the order's `version`. Ticket orders can be listed filtered by `event_id`, `bidder_id`, `table_id`, `invoice_id` and `payment_status`.

### 3.4. Sponsorships and the Program-Ad Review Cycle

A sponsorship is recorded by an `EventOrganizer` with `event_id`, the sponsoring `org_name`, a `tier` of `GOLD`, `SILVER` or `BRONZE`, and a `commitment_cents` amount of at least 1. It opens in `PENDING` with `paid_amount_cents` at 0 and `placed_ad_count` at 0, and may be listed filtered by `event_id` and `status`.

Confirmation is a `FinanceOfficer` action recording sponsorship cash: the officer submits a `paid_amount_cents` figure, which is added to the sponsor's running `paid_amount_cents`. The sponsor must currently be `PENDING`, and the payment must bring the running total to at least the `commitment_cents` promised — a partial payment that leaves the sponsor short is refused with `ERR_SPONSOR_UNDERFUNDED` and records nothing. On success the sponsor moves `PENDING → CONFIRMED` and its `version` advances. Withdrawal, available to the organizer, moves a `PENDING` sponsor to the terminal `WITHDRAWN`, but only when none of that sponsor's program ads has reached `PLACED`; the withdrawal cascades by moving every one of that sponsor's ads in `SUBMITTED`, `IN_REVIEW`, `CHANGES_REQUESTED` or `APPROVED` to `REJECTED`, and advances the sponsor's `version`.

Program ads are submitted either by the sponsoring organization itself or by an organizer on its behalf, carrying `sponsor_id`, `event_id`, an `ad_size` of `FULL_PAGE`, `HALF_PAGE` or `QUARTER_PAGE`, and an opaque `artwork_ref` pointing at the uploaded asset. An ad opens in `SUBMITTED` with `revision_count` at 0, `page_number` null and `review_notes` null, and ads may be listed filtered by `sponsor_id`, `event_id` and `status`.

The review cycle is driven by an organizer supplying a `decision` — one of `BEGIN_REVIEW`, `REQUEST_CHANGES`, `APPROVE` or `REJECT` — together with optional `notes`. `BEGIN_REVIEW` takes a `SUBMITTED` ad to `IN_REVIEW`. `REQUEST_CHANGES` takes an `IN_REVIEW` ad to `CHANGES_REQUESTED` and requires `notes` to be present and non-empty, storing that text as the ad's `review_notes`. `APPROVE` takes an `IN_REVIEW` ad to `APPROVED`, and additionally requires that the ad's owning sponsor be in `CONFIRMED`; approving an ad whose sponsor has not yet fully funded its commitment is refused with `ERR_SPONSOR_NOT_CONFIRMED`. `REJECT` takes an `IN_REVIEW` ad to the terminal `REJECTED`, and stores `notes` as `review_notes` when notes were supplied. All four decisions advance the ad's `version`.

Changes requested is not a dead end. The sponsoring organization may resubmit, moving the ad `CHANGES_REQUESTED → SUBMITTED` with a fresh `artwork_ref` that replaces the old one, which increases the ad's `revision_count` by one and advances its `version`. The cycle `CHANGES_REQUESTED → SUBMITTED → IN_REVIEW → CHANGES_REQUESTED` may therefore repeat, but only within a budget of two completed resubmissions: a resubmission is permitted only while `revision_count` is strictly less than 2, and a third attempt is refused with `ERR_AD_REVISION_LIMIT`.

Placement is the terminal happy path. An organizer places an `APPROVED` ad onto the printed program by supplying a `page_number`, which is stored on the ad; placement additionally requires the ad's gala event to be in `DRAFT` or `PUBLISHED`, since the program goes to the printer before the doors open. The owning sponsor then recomputes `placed_ad_count`, which increases by one, and the ad's `version` advances as it moves `APPROVED → PLACED`.

### 3.5. The Auction Floor: Lots, Mobile Bidding and Two Valuations

An `AuctionManager` creates a lot with `event_id`, a `title`, an `item_type` of `SILENT` (run on guests' phones) or `LIVE` (run from the stage), a `starting_bid_cents` opening amount, a `min_increment_cents` step of at least 1, an `estimated_fmv_cents` fair market value of the goods, and the bidding window bounded by `open_at_utc` inclusive and `close_at_utc` exclusive, the latter strictly after the former. An optional `live_lot_sequence` names the stage channel slot the lot occupies. A lot opens in `listing_status` of `DRAFT` and `settlement_status` of `UNSETTLED`, with `current_leading_amount_cents` at 0, `hammer_price_cents` null, `winning_bid_id` null and `invoice_id` null. Lots may be listed filtered by `event_id`, `listing_status`, `settlement_status`, `winning_bid_id` and `invoice_id`.

Like a ticket order, a lot carries two independent dimensions. The listing dimension runs `DRAFT → OPEN` and then forks to either `AWARDED` or `PASSED`, both terminal. The settlement dimension runs `UNSETTLED → INVOICED → PAID`, with a compensating edge `INVOICED → UNSETTLED` when the invoice carrying the lot is voided. The two evolve independently on the same row.

Opening a lot is an auction-manager action requiring the lot to be in `DRAFT`, the owning event's `status` to be `PUBLISHED` or `LIVE` (otherwise `ERR_INVALID_STATE`), and the owning event's posture to be `OPEN` — a `RESTRICTED` event refuses with `ERR_EVENT_RESTRICTED` and a `FROZEN` one with `ERR_EVENT_FROZEN`. The clock must lie inside the lot's half-open window, at or after `open_at_utc` and strictly before `close_at_utc`, else `ERR_LOT_WINDOW_CLOSED`. Finally, when the lot has a non-null `live_lot_sequence`, no other lot of the same event sharing that same sequence number and currently in `OPEN` may have a window overlapping this lot's window; overlap is computed on half-open intervals, so a lot starting at exactly the instant another ends does not conflict, while any true overlap is refused with `ERR_LOT_WINDOW_CONFLICT`. Opening increases the event's `open_lot_count` by one and advances the lot's `version`.

Bids arrive from the guest's phone or are keyed in by an auction manager transcribing a paper sheet, carrying `bidder_id`, an `amount_cents` of at least 1, and an optional `proxy_max_cents` ceiling that the mobile-bidding agent may auto-bid up to. `proxy_max_cents` defaults to 0, which means no proxy is in play, and may never be negative. Each bid stores a computed `effective_max_cents` equal to whichever is larger of its `amount_cents` and its `proxy_max_cents`; that is the sort key used to pick a leader. A bid begins in `ACTIVE` and ends in `WON`, `LOST` or `RETRACTED`. Two gates apply before a bid is accepted: the acting guest must have `payment_method_on_file` set to true, else `ERR_NO_PAYMENT_METHOD` (HTTP 402); and the target lot must be in `listing_status` of `OPEN` with the clock inside its window, else `ERR_ITEM_NOT_OPEN`. Bids may be listed filtered by `item_id`, `bidder_id` and `status`.

The increment floor is checked next. When the lot has no `ACTIVE` bids at all, the incoming `amount_cents` must be at least the lot's `starting_bid_cents`. Otherwise it must be at least the lot's current `current_leading_amount_cents` plus its `min_increment_cents`. Both comparisons are inclusive, so a bid landing exactly on the floor is accepted; anything below it is refused with `ERR_BID_TOO_LOW` (HTTP 422).

Valuing a lot considers only its bids in `ACTIVE` status — bids in `RETRACTED`, `WON` or `LOST` never participate. With no active bids the valuation is zero cents and there is no source bid. Otherwise the active bids are ranked by `effective_max_cents` from highest to lowest, ties broken by `created_at` earliest-first, and the top-ranked bid is the leader whose id is reported as the source bid. Two documented interpretations then diverge, and both are exposed on a computed read that echoes back the requested `variant`, the resulting `amount_cents`, the `active_bid_count` considered, and the `source_bid_id` of the leader.

Under the `PROXY_SETTLED` interpretation — the one the system itself uses for `current_leading_amount_cents`, for the increment floor above, and for the price frozen at close — a lone leader with no runner-up is valued at that leader's own `amount_cents`. When a runner-up exists, the proxy agent lifts the leader only as far as one minimum increment above the runner-up's own `effective_max_cents`, but never past the leader's own ceiling: the valuation is whichever is smaller of the leader's `effective_max_cents` and the runner-up's `effective_max_cents` plus the lot's `min_increment_cents`. Under the `PLACED_AMOUNT` interpretation, requested explicitly by asking for that variant, the valuation is always the leader's literal `amount_cents` — the number the guest actually typed, with `proxy_max_cents` disregarded entirely. Whenever a leader leads on its proxy ceiling rather than on its placed amount, `PLACED_AMOUNT` reports the strictly smaller figure. `current_leading_amount_cents` is recomputed under the proxy-settled interpretation on every accepted bid and on every retraction.

Retraction is an auction-manager action taking a bid `ACTIVE → RETRACTED`; it requires the bid to be `ACTIVE` and its lot to still be in `listing_status` of `OPEN`, else `ERR_ITEM_NOT_OPEN`. The lot then recomputes `current_leading_amount_cents` over its remaining `ACTIVE` bids, and the bid's `version` advances.

Closing a lot is where the auction turns into money, and the outcome forks on whether any bid is still `ACTIVE`. If at least one is, the lot goes `OPEN → AWARDED`: `hammer_price_cents` is frozen to the proxy-settled valuation described above, `winning_bid_id` is set to the leading bid's id, that leading bid moves `ACTIVE → WON` while every other `ACTIVE` bid on the lot moves `ACTIVE → LOST` (each bid advancing its own `version`), and the settlement dimension moves `UNSETTLED → INVOICED` in the same request. The cascade then runs four levels deep: the winner's `OPEN` invoice for this event is located — and created if the guest has none — and an `AUCTION_ITEM` line for `hammer_price_cents` is appended to it, with the lot's `invoice_id` set to that invoice; that invoice recomputes `line_subtotal_cents`, `processing_fee_cents`, `total_due_cents` and `balance_due_cents`; and the invoice's guest recomputes `outstanding_balance_cents` from their `PENDING_PAYMENT` and `PARTIALLY_PAID` invoices. Finally the event recomputes `open_lot_count`, which decreases by one, and the lot's `version` advances.

If instead no bid on the lot is `ACTIVE` at close, the lot goes `OPEN → PASSED` and the side-effect set is deliberately different: `hammer_price_cents` stays null, `settlement_status` stays `UNSETTLED`, and no invoice anywhere is created or modified. The event still recomputes `open_lot_count`, which decreases by one, and the lot's `version` still advances.

The settlement dimension later moves `INVOICED → PAID` when the invoice carrying the lot reaches `PAID`, and reverts `INVOICED → UNSETTLED` with `invoice_id` cleared to null when that invoice is voided; both hops advance the lot's `version`.

### 3.6. The Appeal: Paddle Raises and the Challenge Match

When the emcee calls the appeal, an `AuctionManager` or `EventOrganizer` records each raised paddle as a gift carrying `event_id`, `bidder_id` and the `level_cents` called from the stage, which must be at least 1. The donating guest must have `payment_method_on_file` set to true, else the gift is refused with `ERR_NO_PAYMENT_METHOD`. A gift opens with `settlement_status` of `UNSETTLED`, and gifts may be listed filtered by `event_id`, `bidder_id` and `invoice_id`.

Each gift also unlocks challenge-match dollars, allocated as a waterfall against the event's `match_cap_cents`. The remaining cap is the event's `match_cap_cents` less its `match_awarded_cents`, floored at zero so it never goes negative. The raw match this gift would earn is the gift's `level_cents` multiplied by a match ratio of 1.0 — a dollar-for-dollar challenge — rounded half up to a whole cent. The gift's `match_cents` is then whichever is smaller of that raw match and the remaining cap, and that awarded amount is added to the event's `match_awarded_cents`. Because gifts are consumed in `created_at` ascending order, the cap drains chronologically: early donors receive their full match, the gift that straddles the cap receives a partial match, and every gift after it receives `match_cents` of 0. Matching dollars are reported on the event but, as §3.9 makes explicit, they are not part of the reconciled expected total.

A gift's money dimension moves only under cascade. It goes `UNSETTLED → INVOICED` when the donor's invoice is finalized, `INVOICED → PAID` when that invoice is fully paid, and reverts to `UNSETTLED` when the invoice is voided.

### 3.7. Checkout: Invoices, Payments and the Settlement Cascade

An invoice is opened for a guest by a `FinanceOfficer` or an `EventOrganizer` with `event_id`, `bidder_id`, and an optional `cover_processing_fee` flag that defaults to false and records whether the guest has elected to absorb the card-processing fee on top of what they owe. The invoice opens in `status` of `OPEN` with empty `line_items` and all money fields at 0. Its `line_items` array holds objects of `line_type`, `source_id` and `amount_cents`, where `line_type` is one of `AUCTION_ITEM`, `TICKET`, `PADDLE_RAISE` or `PROCESSING_FEE`. Invoices may be listed filtered by `event_id`, `bidder_id` and `status`, and the invoice lifecycle runs `OPEN → PENDING_PAYMENT`, then `PARTIALLY_PAID` and `PAID`, with `VOID` as an alternative terminus.

Finalization is a `FinanceOfficer` action that closes the guest's tab. The invoice must be in `OPEN` and its `line_subtotal_cents` must be strictly greater than zero — finalizing an empty invoice is refused with `ERR_INVALID_STATE`. Finalization sweeps: every ticket order of the same event and guest still in `UNBILLED` moves to `INVOICED`, gains a `TICKET` line on the invoice and has its `invoice_id` set; every paddle-raise gift of the same event and guest still in `UNSETTLED` moves to `INVOICED`, gains a `PADDLE_RAISE` line and has its `invoice_id` set. Totals are then recomputed as described below, the guest recomputes `outstanding_balance_cents`, the event recomputes `unpaid_invoice_count`, and the invoice moves `OPEN → PENDING_PAYMENT` with its `version` advanced. (Auction lines, by contrast, are appended at lot close rather than at finalization, as §3.5 describes.)

Invoice totals are recomputed whenever a line is appended and whenever a payment is captured or voided, and the evaluation order is pinned because it looks circular but is not. First, `line_subtotal_cents` is the sum of the `amount_cents` of every line except the `PROCESSING_FEE` line. Second, the fee tier is selected from that pre-fee subtotal: a subtotal strictly below 50,000 cents takes the 2.9 percent rate; a subtotal at or above 50,000 cents but strictly below 500,000 cents takes the 2.4 percent rate; a subtotal at or above 500,000 cents takes the 1.9 percent rate. Third, `processing_fee_cents` is the subtotal multiplied by the selected rate, rounded half up to a whole cent, plus a flat 30 cents — the rounding is applied once, to the percentage component only, before the flat component is added. Fourth, the fee becomes a real charge only when the guest elected to cover it: when `cover_processing_fee` is true, `total_due_cents` is `line_subtotal_cents` plus `processing_fee_cents` and a `PROCESSING_FEE` line for that amount is present among `line_items`; when it is false, `total_due_cents` is simply `line_subtotal_cents`. The tier and fee are resolved once from the pre-fee subtotal and are never re-derived against the grossed-up total, even when adding the fee would have crossed a tier boundary. Fifth, `amount_paid_cents` is the sum of `amount_cents` across the invoice's payment transactions in `CAPTURED` status, with `VOIDED` transactions excluded, and `balance_due_cents` is `total_due_cents` less `amount_paid_cents`.

A payment is captured by a `FinanceOfficer` or by the guest being billed, supplying `invoice_id`, an `amount_cents` of at least 1, and a `method` of `CARD`, `CASH` or `CHECK`. The invoice must be in a payable state — `PENDING_PAYMENT` or `PARTIALLY_PAID` — else `ERR_INVOICE_NOT_PAYABLE`, and the tendered amount may not exceed the invoice's `balance_due_cents`, else `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422). The transaction is stored in `CAPTURED` status with `captured_by_user_id` set to the acting `X-User-ID`, and with `voided_by_user_id` and `void_reason` both null. Payments may be listed filtered by `invoice_id` and `status`.

Capture then drives the invoice. If the capture leaves `balance_due_cents` above zero while `amount_paid_cents` is above zero, the invoice moves `PENDING_PAYMENT → PARTIALLY_PAID`, recomputing `amount_paid_cents` and `balance_due_cents`, recomputing the guest's `outstanding_balance_cents`, and advancing the invoice's `version`. If the capture clears the balance to exactly zero, the invoice moves to `PAID` — from `PENDING_PAYMENT` directly if this was the only payment, or from `PARTIALLY_PAID` if earlier payments had already landed — and the same full cascade runs in both cases: every auction lot whose `invoice_id` is this invoice moves its `settlement_status` `INVOICED → PAID`, every paddle-raise gift likewise, and every ticket order moves its `payment_status` `INVOICED → PAID`; the event then recomputes `gross_collected_cents` and `unpaid_invoice_count` and re-derives its posture; the guest recomputes `outstanding_balance_cents`; and the invoice's `version` advances. An event's `gross_collected_cents` is at all times the sum of `amount_cents` over `CAPTURED` payment transactions across all of that event's invoices, and its `unpaid_invoice_count` is the number of its invoices in `PENDING_PAYMENT` or `PARTIALLY_PAID`.

Voiding a payment is the compensating operation and is `FinanceOfficer`-only. It requires the transaction to be in `CAPTURED`, requires the acting `X-User-ID` to differ from `captured_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and requires that no receipt has yet been issued for the payment's invoice (else `ERR_RECEIPT_ALREADY_ISSUED`). The caller supplies a `reason`, which is stored as the transaction's `void_reason` alongside `voided_by_user_id`; the transaction moves `CAPTURED → VOIDED` and its `version` advances. The invoice then recomputes `amount_paid_cents` and `balance_due_cents` and follows its own machine. A void that leaves an invoice in `PARTIALLY_PAID` with `amount_paid_cents` back at zero returns it to `PENDING_PAYMENT`, recomputing the guest's `outstanding_balance_cents` and advancing the invoice's `version` — the cycle `PENDING_PAYMENT → PARTIALLY_PAID → PENDING_PAYMENT` is legitimate. A void against a `PAID` invoice that leaves `amount_paid_cents` above zero moves it `PAID → PARTIALLY_PAID` and unwinds the settlement cascade: every auction lot and paddle-raise gift carrying this `invoice_id` moves `settlement_status` `PAID → INVOICED` and every ticket order moves `payment_status` `PAID → INVOICED`, after which the event recomputes `gross_collected_cents` and `unpaid_invoice_count` and the invoice's `version` advances. A void against a `PAID` invoice that leaves `amount_paid_cents` at exactly zero moves it `PAID → PENDING_PAYMENT`, runs the identical settlement unwind, has the event recompute `gross_collected_cents` — which decreases by the voided amount — and `unpaid_invoice_count`, has the guest recompute `outstanding_balance_cents`, and advances the invoice's `version`.

An invoice may also be voided outright by a `FinanceOfficer`, which detaches everything it carried. From `OPEN`, voiding moves the invoice to `VOID` and reverts every auction lot whose `invoice_id` is this invoice from `INVOICED` back to `UNSETTLED` with `invoice_id` cleared, advancing the invoice's `version`. From `PENDING_PAYMENT`, voiding is permitted only while `amount_paid_cents` is exactly zero — an invoice that has already taken money is refused with `ERR_INVOICE_NOT_PAYABLE` — and reverts more: every auction lot and paddle-raise gift carrying this `invoice_id` returns to `UNSETTLED` with `invoice_id` cleared, every ticket order returns to `UNBILLED` with `invoice_id` cleared, the event recomputes `unpaid_invoice_count`, the guest recomputes `outstanding_balance_cents`, and the invoice's `version` advances. `PAID` and `VOID` are terminal for an invoice.

### 3.8. Donor Receipts and Deductibility

Once an invoice is fully paid, a `FinanceOfficer` issues the donor's tax receipt by supplying the `invoice_id`. Exactly one receipt may exist per invoice; a second attempt is refused with `ERR_RECEIPT_ALREADY_ISSUED`. The receipt copies the invoice's `bidder_id`, stamps `issued_at_utc` from the logical clock, and records `total_paid_cents` as the invoice's `amount_paid_cents` at issue time — which, since the invoice is `PAID`, equals its `total_due_cents`. Receipts may be listed filtered by `invoice_id` and `bidder_id`.

Deductibility is computed line by line, accumulating a benefit total and a deductible total that both start at zero. For an `AUCTION_ITEM` line, the donor received goods, so the referenced lot's `estimated_fmv_cents` is added to the benefit total and the line's `amount_cents` less that same fair market value — floored at zero, never negative — is added to the deductible. For a `TICKET` line, the referenced ticket order's `benefit_value_cents` is added to the benefit total and the line's `amount_cents` less that benefit value — again floored at zero — is added to the deductible. For a `PADDLE_RAISE` line the donor received nothing, so the whole line amount is deductible; the same is true of a `PROCESSING_FEE` line. A de-minimis override then applies: if the accumulated benefit total is strictly below 1,500 cents, that token benefit is disregarded entirely — the receipt's `benefit_value_cents` is set to zero and its `tax_deductible_cents` is set to the invoice's full `total_due_cents`. Otherwise the receipt's `benefit_value_cents` and `tax_deductible_cents` carry the accumulated figures. All inputs are whole cents and no rounding occurs anywhere in this calculation.

### 3.9. Reconciling the Night and Reporting It

A `FinanceOfficer` prepares a reconciliation run against an event by supplying `expected_event_version` (see §2.9) and a `revenue_basis` of either `BOOKED` or `CASH_BASIS`. The run is stamped with `prepared_by_user_id` from the acting `X-User-ID`, opens in `PREPARED` with `finalized_by_user_id` null, and any run of that event already in `PREPARED` is moved to the terminal `SUPERSEDED`, advancing that older run's `version`. A new run may not be prepared at all while a `FINALIZED` run already exists for the event; that, and finalizing a run not currently in `PREPARED`, are both refused with `ERR_RUN_ALREADY_FINALIZED`. Preparing a run advances the event's `version`. Runs may be read individually or listed per event filtered by `status`, in both cases only by an `EventOrganizer` or `FinanceOfficer`.

The run computes five channel figures, each filtered on an explicit status set. The tickets channel sums `subtotal_cents` over the event's ticket orders whose `payment_status` is `INVOICED` or `PAID`, so `UNBILLED` and `REFUNDED` orders contribute nothing. The auction channel sums `hammer_price_cents` over the event's lots whose `listing_status` is `AWARDED`, so `PASSED` lots contribute nothing. The paddle channel sums `level_cents` over the event's appeal gifts whose `settlement_status` is `INVOICED` or `PAID`, so `UNSETTLED` gifts contribute nothing. The sponsorship channel sums `paid_amount_cents` over the event's sponsors whose `status` is `CONFIRMED`, so `PENDING` and `WITHDRAWN` sponsors contribute nothing. The pledge channel depends on the run's `revenue_basis` and is described next.

Under the `BOOKED` basis — the accrual view the board report uses — the pledge channel sums `total_amount_cents` over every pledge of the event whose `status` is `PROMISED`, `PARTIALLY_FULFILLED` or `FULFILLED`; pledges in `LAPSED` are excluded outright, and the full promised amount is recognized the night it is promised regardless of how much cash has arrived. Under the `CASH_BASIS` basis — the treasurer's bank tie-out — the pledge channel instead sums `received_amount_cents` over every pledge of the event in `PROMISED`, `PARTIALLY_FULFILLED`, `FULFILLED` or `LAPSED`; every pledge including the lapsed ones contributes, but only cash actually received counts.

Those five figures are emitted as `channel_breakdown`, an array of objects of `channel` and `expected_cents` in the fixed order `TICKETS`, `AUCTION`, `PADDLE`, `PLEDGE`, `SPONSORSHIP`. Their sum is `expected_total_cents`. The run's `collected_total_cents` is the event's `gross_collected_cents` at run time, and `variance_cents` is `expected_total_cents` less `collected_total_cents` — a figure that may be negative. The run is flagged with `is_material_variance` set true when the absolute value of `variance_cents` is at or above 5,000 cents; the comparison is inclusive, so a variance of exactly 5,000 cents in either direction is material. Note that challenge-match dollars are deliberately outside this arithmetic: `match_awarded_cents` is reported on the event but contributes to no channel and to no expected total, because a matching gift is not revenue the gala itself collected at the door.

Finalizing a run is what closes the books, and it is guarded four ways. The run must be in `PREPARED`; the acting `X-User-ID` must differ from `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; the event must have `unpaid_invoice_count` of 0, else `ERR_OPEN_INVOICES_REMAIN`; and if `is_material_variance` is true, the caller must supply a `variance_override_note` that is present and non-empty, else `ERR_MATERIAL_VARIANCE`. A run with no material variance needs no note. On success `finalized_by_user_id` is set to the acting user, the run moves `PREPARED → FINALIZED`, the event recomputes its posture — which becomes `FROZEN` — and the run's `version` advances.

Finalization is reversible. Reopening moves a `FINALIZED` run back to `PREPARED`, and is refused with `ERR_INVALID_STATE` when the run's event has already reached `CLOSED`. Reopening clears `finalized_by_user_id` back to null, recomputes `expected_total_cents`, `collected_total_cents`, `variance_cents`, `is_material_variance` and `channel_breakdown` from current data under the run's stored `revenue_basis`, and lifts the frozen gate the finalized run imposed: the event's posture becomes `RESTRICTED` when the event's `status` is `SETTLING`, and `OPEN` otherwise. The run's `version` advances. The cycle `PREPARED → FINALIZED → PREPARED` may repeat as often as the books require.

Separately from any run, an `EventOrganizer` or `FinanceOfficer` may pull a live per-channel snapshot of an event that reports `tickets_cents`, `auction_cents`, `paddle_cents`, both pledge readings side by side as `pledge_booked_cents` and `pledge_cash_cents`, `sponsorship_cents`, `gross_collected_cents` and `match_awarded_cents`, using the same channel filters described above. This read stores nothing and changes nothing.

### 3.10. Pledges Over the Following Year

A pledge is recorded by a `FinanceOfficer` or an `EventOrganizer` with `event_id`, `bidder_id`, a `total_amount_cents` of at least 1, an `installment_count` of at least 1 naming how many payments were promised, and a `first_due_utc` instant anchoring the schedule. It opens in `PROMISED` with `received_amount_cents` at 0, and pledges may be listed filtered by `event_id`, `bidder_id` and `status`.

Installments are recorded by a `FinanceOfficer` supplying an `amount_cents`, which is added to the pledge's `received_amount_cents` and advances the pledge's `version`. The resulting state depends on whether the pledge is now whole: if `received_amount_cents` plus the new `amount_cents` remains strictly below `total_amount_cents`, a `PROMISED` pledge moves to `PARTIALLY_FULFILLED` and a `PARTIALLY_FULFILLED` pledge stays in `PARTIALLY_FULFILLED` — the self-loop that lets a donor pay in as many pieces as they like. If instead the sum reaches or exceeds `total_amount_cents`, the pledge moves to the terminal `FULFILLED`, whether it was previously in `PROMISED` or in `PARTIALLY_FULFILLED`.

A pledge that goes unpaid eventually lapses. A `FinanceOfficer` may mark a pledge in `PROMISED` or `PARTIALLY_FULFILLED` as `LAPSED`, but only once the grace window has run out: the clock must be strictly later than the pledge's `first_due_utc` plus 30 days, and an early attempt is refused with `ERR_INVALID_STATE`. Lapsing advances the pledge's `version`. The same 30-day grace governs the automatic sweep at event close described in §3.1, which lapses only the pledges still in `PROMISED`. Both `FULFILLED` and `LAPSED` are terminal: recording an installment against, or lapsing, a pledge already in either state is refused with `ERR_PLEDGE_TERMINAL`.

## 4. Endpoint Definitions

Resource creation returns HTTP 201 with the newly created resource in `data`. Every other successful call — reads, list reads, state transitions, and computed reads — returns HTTP 200. Errors follow the envelope and status codes of §5. The table below is a routing summary only: request payloads, response contents and side effects are specified in the narratives of §2 and §3, and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock. The clock's startup default is exactly 2026-07-01T00:00:00Z; before any call to this endpoint the server reads that instant and never falls back to real wall-clock time. | EventOrganizer, AuctionManager, FinanceOfficer |
| POST | `/api/events` | Create a gala event in DRAFT. | EventOrganizer |
| GET | `/api/events/{id}` | Read one gala event including its computed posture and rollups. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/events` | List gala events. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/events/{id}/publish` | DRAFT -> PUBLISHED. | EventOrganizer |
| POST | `/api/events/{id}/unpublish` | PUBLISHED -> DRAFT; releases every HELD table hold of the event. | EventOrganizer |
| POST | `/api/events/{id}/go-live` | PUBLISHED -> LIVE; auto-opens every DRAFT lot whose window contains the clock. | EventOrganizer |
| POST | `/api/events/{id}/start-settlement` | LIVE -> SETTLING; posture becomes RESTRICTED. | EventOrganizer |
| POST | `/api/events/{id}/close` | SETTLING -> CLOSED; lapses overdue PROMISED pledges; posture becomes FROZEN. | EventOrganizer |
| GET | `/api/events/{id}/revenue-summary` | Computed read: per-channel revenue snapshot of the event under both pledge variants. | EventOrganizer, FinanceOfficer |
| POST | `/api/events/{id}/tables` | Add a table to the event. | EventOrganizer |
| GET | `/api/tables/{id}` | Read one table. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/tables` | List tables, optionally filtered by event. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/table-holds` | Place a closed-interval hold on a table for a guest. | EventOrganizer, Bidder |
| GET | `/api/table-holds/{id}` | Read one hold. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/table-holds` | List holds, optionally filtered by table or bidder. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/table-holds/{id}/release` | HELD -> RELEASED. | EventOrganizer, Bidder |
| POST | `/api/bidders` | Register a guest / bidder for the event. | EventOrganizer |
| GET | `/api/bidders/{id}` | Read one bidder including outstanding_balance_cents. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/bidders` | List bidders, optionally filtered by event. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/bidders/{id}/payment-method` | Attach or detach a stored payment method. | EventOrganizer, Bidder |
| POST | `/api/sponsors` | Record a sponsorship commitment in PENDING. | EventOrganizer |
| GET | `/api/sponsors/{id}` | Read one sponsor. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/sponsors` | List sponsors, optionally filtered by event. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/sponsors/{id}/confirm` | Record sponsorship cash; PENDING -> CONFIRMED when the commitment is fully funded. | FinanceOfficer |
| POST | `/api/sponsors/{id}/withdraw` | PENDING -> WITHDRAWN; rejects the sponsor's non-placed ads. | EventOrganizer |
| POST | `/api/program-ads` | Submit a program ad for review. | Sponsor, EventOrganizer |
| GET | `/api/program-ads/{id}` | Read one program ad. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/program-ads` | List program ads, optionally filtered by sponsor or event. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/program-ads/{id}/review` | Advance the review cycle: decision one of BEGIN_REVIEW, REQUEST_CHANGES, APPROVE, REJECT. | EventOrganizer |
| POST | `/api/program-ads/{id}/resubmit` | CHANGES_REQUESTED -> SUBMITTED with fresh artwork; increments revision_count. | Sponsor |
| POST | `/api/program-ads/{id}/place` | APPROVED -> PLACED on a program page. | EventOrganizer |
| POST | `/api/ticket-orders` | Buy a whole table or individual seats; prices the order via calculations.ticket_order_total. | EventOrganizer, Bidder |
| GET | `/api/ticket-orders/{id}` | Read one ticket order. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/ticket-orders` | List ticket orders with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/ticket-orders/{id}/assign-seats` | Seating dimension only: UNSEATED -> SEATED at the order's table. | EventOrganizer |
| POST | `/api/ticket-orders/{id}/cancel` | Cancel an order: payment_status -> REFUNDED and seating_status -> RELEASED. | EventOrganizer |
| POST | `/api/auction-items` | Create a silent or live lot in DRAFT. | AuctionManager |
| GET | `/api/auction-items/{id}` | Read one lot including both status dimensions and current_leading_amount_cents. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/auction-items` | List lots with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/auction-items/{id}/open` | DRAFT -> OPEN; enforces the half-open live-channel window conflict check. | AuctionManager |
| POST | `/api/auction-items/{id}/close` | OPEN -> AWARDED when an ACTIVE bid exists, otherwise OPEN -> PASSED. | AuctionManager |
| GET | `/api/auction-items/{id}/valuation` | Computed read of either valuation variant of the lot. | AuctionManager, FinanceOfficer, EventOrganizer |
| POST | `/api/auction-items/{id}/bids` | Place a mobile bid, optionally with a proxy ceiling. | Bidder, AuctionManager |
| GET | `/api/bids/{id}` | Read one bid. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/bids` | List bids with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/bids/{id}/retract` | ACTIVE -> RETRACTED on an OPEN lot. | AuctionManager |
| POST | `/api/paddle-raises` | Record an appeal gift from the stage and allocate challenge-match dollars. | AuctionManager, EventOrganizer |
| GET | `/api/paddle-raises/{id}` | Read one paddle-raise gift. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/paddle-raises` | List paddle-raise gifts with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/pledges` | Record a multi-installment pledge in PROMISED. | FinanceOfficer, EventOrganizer |
| GET | `/api/pledges/{id}` | Read one pledge. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/pledges` | List pledges with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/pledges/{id}/installments` | Record received cash against the pledge; advances the pledge state machine. | FinanceOfficer |
| POST | `/api/pledges/{id}/lapse` | Mark an overdue pledge LAPSED. | FinanceOfficer |
| POST | `/api/invoices` | Open a checkout invoice for a guest. | FinanceOfficer, EventOrganizer |
| GET | `/api/invoices/{id}` | Read one invoice with its lines and totals. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/invoices` | List invoices with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/invoices/{id}/finalize` | OPEN -> PENDING_PAYMENT; sweeps the guest's UNBILLED ticket orders and UNSETTLED paddle raises onto the invoice. | FinanceOfficer |
| POST | `/api/invoices/{id}/void` | Void an unpaid invoice and detach its lines. | FinanceOfficer |
| POST | `/api/payments` | Capture a payment against a payable invoice. | FinanceOfficer, Bidder |
| GET | `/api/payments/{id}` | Read one payment. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/payments` | List payments with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/payments/{id}/void` | CAPTURED -> VOIDED; reverses the capture cascade. Segregation of duties: the voiding user must differ from captured_by_user_id. | FinanceOfficer |
| POST | `/api/receipts` | Issue the donor tax receipt for a fully PAID invoice. | FinanceOfficer |
| GET | `/api/receipts/{id}` | Read one receipt. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| GET | `/api/receipts` | List receipts with filters. | EventOrganizer, AuctionManager, FinanceOfficer, Bidder, Sponsor |
| POST | `/api/events/{id}/reconciliation-runs` | Prepare a reconciliation run for the event under a chosen revenue basis; supersedes any existing PREPARED run. Requires the caller's last-observed GalaEvent.version. | FinanceOfficer |
| GET | `/api/reconciliation-runs/{id}` | Read one reconciliation run. | EventOrganizer, FinanceOfficer |
| GET | `/api/events/{id}/reconciliation-runs` | List the event's reconciliation runs. | EventOrganizer, FinanceOfficer |
| POST | `/api/reconciliation-runs/{id}/finalize` | PREPARED -> FINALIZED; freezes the event. The finalizing user must differ from prepared_by_user_id. | FinanceOfficer |
| POST | `/api/reconciliation-runs/{id}/reopen` | FINALIZED -> PREPARED; recomputes the run and un-freezes the event. | FinanceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_TABLE_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_TICKET_ORDER_NOT_FOUND` | 404 |
| `ERR_BIDDER_NOT_FOUND` | 404 |
| `ERR_SPONSOR_NOT_FOUND` | 404 |
| `ERR_AD_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_PADDLE_RAISE_NOT_FOUND` | 404 |
| `ERR_PLEDGE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_EVENT_FROZEN` | 409 |
| `ERR_EVENT_RESTRICTED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_NOT_OPEN` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_RUN_ALREADY_FINALIZED` | 409 |
| `ERR_PLEDGE_TERMINAL` | 409 |
| `ERR_RECEIPT_ALREADY_ISSUED` | 409 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SPONSOR_NOT_CONFIRMED` | 409 |
| `ERR_OPEN_INVOICES_REMAIN` | 409 |
| `ERR_NO_FINALIZED_RUN` | 409 |
| `ERR_OPEN_LOTS_REMAIN` | 409 |
| `ERR_TICKET_ORDERS_EXIST` | 409 |
| `ERR_LOT_WINDOW_CLOSED` | 409 |
| `ERR_LOT_WINDOW_CONFLICT` | 409 |
| `ERR_TABLE_HOLD_CONFLICT` | 409 |
| `ERR_BID_TOO_LOW` | 422 |
| `ERR_AD_REVISION_LIMIT` | 409 |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_PADDLE_NUMBER` | 409 |
| `ERR_NO_PAYMENT_METHOD` | 402 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_MATERIAL_VARIANCE` | 409 |
| `ERR_SPONSOR_UNDERFUNDED` | 422 |
