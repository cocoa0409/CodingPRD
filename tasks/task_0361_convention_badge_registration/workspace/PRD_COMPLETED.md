# Convention Badge Registration API — Product Requirements Document

## 1. Introduction

Running a large fan convention is, at its heart, an exercise in allocating a finite number of badges to a much larger pool of eager attendees while keeping money, RFID hardware, panel seats, and exhibitor floor space all consistent with one another. This API is the system of record for that allocation. It governs the full arc of a registration: configuring a convention and its ticket tiers, opening paid registration, running a lottery when demand outstrips supply, issuing and physically picking up RFID badges, reserving seats for panels and sessions, leasing exhibitor booths, and ultimately handling the transfers, cancellations, and refunds that any real event accumulates.

The defining tension the system resolves is scarcity under contention. Badge capacity is hard-capped both per ticket tier and across the convention as a whole, panel seats are limited, and a single physical booth cannot host two exhibitors whose setup windows overlap. Because many of these resources are competed for simultaneously, the API treats capacity as something that is reserved, committed, and released through carefully ordered state transitions — and it protects those transitions with optimistic concurrency so that a client acting on a stale view of remaining capacity is told to refresh rather than allowed to oversell. Around that core, a workflow spine threads each participant from intent to settlement: register, pay, receive a badge, reserve sessions, pick up and print on-site, and — when plans change — transfer or refund with the correct penalty applied.

This document specifies the entities, their lifecycles, the calculations that price and settle them, the validation rules that guard every transition, and the precise REST contract the implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the two self-registration endpoints must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. When either header is missing, or when `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The two exceptions are attendee self-registration and exhibitor self-registration, which may be performed by an unauthenticated caller.

The system recognizes five roles, spelled exactly as follows: `ConventionAdmin`, `RegistrationAgent`, `Attendee`, `Exhibitor`, and `Anonymous`. A `ConventionAdmin` is the operator who configures conventions, ticket types, sessions, and booths, runs the lottery, bans attendees, closes registration, and drives the test clock. A `RegistrationAgent` is on-site staff who pick up, print, and void badges, process refunds, and act on behalf of attendees and exhibitors at the registration desk. An `Attendee` is a registered person who buys orders, holds and transfers badges, reserves sessions, and enters the lottery. An `Exhibitor` is a vendor who books and manages booths. `Anonymous` is an unauthenticated caller who may only self-register as an attendee or an exhibitor. When a request carries a valid role that is nonetheless not permitted for the requested operation, the response is `ERR_FORBIDDEN`.

Two of these roles are entity-backed and two are opaque. When `X-User-Role` is `Attendee`, `X-User-ID` is the `id` of the acting `Attendee`; ownership checks on any resource that references an attendee compare that resource's attendee foreign key (for orders, the `purchaser_attendee_id`; for badges, the `holder_attendee_id`; for reservations, the badge's holder; for waitlist entries, the `attendee_id`) to `X-User-ID`, and an attendee acting on a resource it does not own is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting `Exhibitor`; ownership checks on any booth booking compare the booking's `exhibitor_id` to `X-User-ID`. When `X-User-Role` is `ConventionAdmin`, `RegistrationAgent`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication but does not compare it to any entity's `id`, and these roles are not subject to ownership restrictions.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter skips a number of leading items and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every entity in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All entities in this system also carry an `updated_at` timestamp, likewise ISO 8601 UTC with three fractional digits and refreshed on every mutation, and an integer `version` that begins at its initial value and increments by exactly one on each mutation of that resource. The `version` field is the basis for optimistic concurrency control described in §2.7.

Computed and derived fields are first-class state: when a mutation recomputes a derived count or charge on a resource — for example a convention's `badges_issued_count`, a ticket type's `tier_issued_count`, a session's `seats_taken`, or an exhibitor's `estimated_booth_cents` and `actual_booth_cents` — that recomputation is itself a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Cascades and Hierarchical Consistency

Several operations in this system mutate more than one entity in a single atomic request, and every such cascade completes fully or not at all within that request; the system maintains immediate consistency with no deferred reconciliation. When a parent operation frees capacity, the system propagates that change downward and, where a freed seat or freed badge slot makes a waiting party eligible, it promotes that party automatically without requiring a separate client request. Each entity touched in a cascade independently has its `updated_at` refreshed and its `version` incremented. The specific cascades — order payment issuing badges and possibly flipping the convention to `SOLD_OUT`, order refund voiding badges and rippling through reservations and waitlists, badge void freeing session seats, and reservation cancellation promoting the top waitlisted reservation — are described in detail throughout §3, and the derived counters they touch are always recomputed from the authoritative source rows rather than incrementally adjusted, so they never drift.

### 2.6. Monetary Values, Counts, and Precision

All monetary amounts in this system are stored and returned as integer numbers of cents. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. The order pricing calculation pins a specific rounding order: each line is rounded to whole cents individually before the lines are summed, and the processing fee is then rounded once on its own; this per-line-then-sum order is canonical and must not be replaced by a sum-then-round approach. Refund amounts are likewise rounded half up to whole cents. Booth daily rates are expressed directly in whole cents, so booth charge aggregation requires no rounding. Capacity counters, seat counts, badge counts, priority scores, and lottery allocations are all integers.

### 2.7. Optimistic Concurrency Control

Two capacity-consuming creates are guarded by optimistic concurrency control against the version of the parent resource whose scarce capacity they consume.

Paying an order issues badges that consume convention badge capacity and may flip the convention's posture to `SOLD_OUT`, which advances the convention's `version`. A pay request must therefore carry `expected_convention_version` as a required field, holding the client's last observed `version` of the parent `Convention`. If that value does not match the convention's current `version` — because some other writer advanced it since the client last read it — the pay is rejected with `ERR_STALE_CONVENTION_VERSION` and HTTP status 412, on the grounds that the client's view of remaining capacity and posture is stale; a second pay carrying a version that an earlier successful pay already superseded is rejected the same way.

Creating a session reservation consumes a seat and advances the parent session's `version`. A reservation create must carry `expected_session_version` as a required field, holding the client's last observed `version` of the parent `Session`. If that value does not match the session's current `version`, the create is rejected with `ERR_STALE_SESSION_VERSION` and HTTP status 412 — the client's view of available seats is stale and the seat it expected to claim as `CONFIRMED` may already be gone, so the request is refused rather than silently routed to the waitlist.

No other endpoint takes a version field for OCC purposes. (Several administrative endpoints — convention close, run-lottery, and attendee ban — accept an `expected_convention_version` or `expected_attendee_version` as an input field; these are administrative guards described with their workflows in §3, and a mismatch on the ban endpoint is reported as `ERR_STALE_ATTENDEE_VERSION` at HTTP 412.)

### 2.8. Nested Resource Retrieval and Existence Ordering

Many paths embed one or more resource identifiers, and several create endpoints nest a child under a parent in the path (for example, creating a ticket type, session, or booth under a convention). For any such request, identifiers are resolved strictly left to right: the path identifiers are checked first, in order, and then any foreign-key identifiers carried in the request body. The first identifier that does not resolve to an existing row causes immediate rejection with `ERR_NOT_FOUND`, before any business rule is evaluated. This ordering guarantees that an operation aimed at a child under a non-existent parent fails on the parent, not the child.

### 2.9. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication is checked first: a missing or unknown `X-User-Role`/`X-User-ID` yields `ERR_UNAUTHENTICATED`. Authorization is checked next — whether the role is permitted for the operation, yielding `ERR_FORBIDDEN`. Existence is checked third, resolving every path and body identifier left to right and yielding `ERR_NOT_FOUND`. The entity-backed ownership sub-check (whether the acting attendee or exhibitor owns the target) is applied after existence resolution, since the target row must first be resolved before its owning foreign key can be compared, and an ownership failure surfaces as `ERR_FORBIDDEN`. Fourth, the acting attendee or exhibitor must not be `BANNED`, else `ERR_ATTENDEE_BANNED`. Fifth, the target resource must currently be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`. After these foundational checks come the business-specific rules in the order presented below: the on-site window check, the refund window check, session time-conflict, VIP requirement, booth time-conflict, transfer limit, duplicate waitlist, posture gating, per-tier capacity, convention capacity, the confirmed-only session-full check, then optimistic concurrency, and finally request well-formedness. The intent is that a more fundamental failure (you are not who you claim, the thing does not exist, the state is wrong) always surfaces ahead of a more specific business failure.

## 3. Business Logic & Workflows

### 3.1. Configuring a Convention

A `ConventionAdmin` brings an event into existence by creating a **Convention**, supplying its display `name`, the first-day reference instant `event_start_utc` and the closing instant `event_end_utc` (both ISO 8601 UTC, with `event_end_utc` required to be strictly later than `event_start_utc`), a `total_badge_capacity` that is the hard cap of one or more on the number of non-voided badges that may ever exist across all orders for the convention, and a `lottery_open_utc` instant marking when the lottery opens. A new convention starts with its `badges_issued_count` at 0 and its `posture` at `OPEN`. The `posture` field is the master gate over capacity-consuming operations and takes one of three values: `OPEN` allows paid registration, `SOLD_OUT` blocks new badge issuance but still admits lottery (waitlist) entries, and `CLOSED` blocks both registration and waitlist. An admin may explicitly drive a convention to `CLOSED`; that close operation carries `expected_convention_version` matching the convention's current `version`, sets `posture` to `CLOSED`, and increments the convention's `version` by one.

Under a convention, the admin defines one or more **Ticket Types**. Each ticket type belongs to a convention through its `convention_id` and declares a `tier` — one of `GENERAL`, `THREE_DAY`, `VIP`, or `EXHIBITOR` — together with a `base_price_cents` (the per-badge price in cents before any group discount, zero or greater), a `tier_capacity` (the maximum number of non-voided badges issuable against this type, one or greater), and an optional `is_day_pass` flag that defaults to false and marks single-day passes without affecting pricing. A ticket type tracks `tier_issued_count`, the running number of non-voided badges issued against it, which starts at 0.

The admin also lays out the **Sessions** (panels) of the convention and the **Booths** of the show floor; those are described in §3.5 and §3.7 respectively. A `ConventionAdmin` additionally controls the logical clock through an admin-only test-driving capability that pins the server's current UTC clock to a supplied `to_iso8601` instant for all subsequent time-dependent reads.

### 3.2. Attendees, Exhibitors, and Banning

A person joins the system through attendee self-registration, providing a `email` (unique across all attendees, compared case-insensitively, and used as login identity), a `full_name` printed on the badge, and an optional `loyalty_tier` that defaults to `NONE` and is otherwise one of `SILVER`, `GOLD`, or `PLATINUM`. A new attendee starts `ACTIVE`. If the supplied email already belongs to another attendee under a case-insensitive comparison, the registration is rejected with `ERR_DUPLICATE_EMAIL`.

A vendor joins through exhibitor self-registration, supplying the `convention_id` it intends to exhibit at, a `company_name`, and a `contact_email` that is unique across all exhibitors under a case-insensitive comparison; a duplicate contact email is likewise rejected with `ERR_DUPLICATE_EMAIL`. A new exhibitor begins with both its `estimated_booth_cents` and `actual_booth_cents` at 0.

An attendee carries a `status` of either `ACTIVE` or `BANNED`. A `ConventionAdmin` may ban an attendee; the ban request carries `expected_attendee_version` matching the attendee's current `version`, sets `status` to `BANNED`, and increments the attendee's `version` by one. A mismatch on that version is reported as `ERR_STALE_ATTENDEE_VERSION`. Once an attendee (or, analogously, an exhibitor) is `BANNED`, every create or transition operation they attempt is blocked with `ERR_ATTENDEE_BANNED`.

### 3.3. Ordering and Pricing

An `Attendee` (or a `RegistrationAgent` acting on their behalf) opens a purchase by creating an **Order** against a `convention_id` with a `purchaser_attendee_id` and a set of `line_items`. The order is born in `DRAFT` with all of its pricing fields at 0. Each entry in `line_items` becomes a **Ticket Line Item** referencing its `order_id` and a `ticket_type_id`, with a `quantity` of one or more badges of that tier; a line also carries the computed `line_base_cents` and `line_discounted_cents`, both starting at 0 until the order is priced. An order created with zero line items is rejected with `ERR_EMPTY_ORDER`, as is a submit attempt on an order that has no line items.

Submitting a `DRAFT` order prices it and advances it to `PENDING_PAYMENT`. Submission is permitted only when the order has at least one line item and the convention's `posture` is `OPEN`; when the posture is not `OPEN` (i.e. `SOLD_OUT` or `CLOSED`) the submit is rejected with `ERR_POSTURE_BLOCKED`, and capacity is not yet checked at submit time. Pricing proceeds as follows. First, the total badge quantity is the sum of `quantity` across all of the order's line items. That total determines the order-level group discount percentage on a tiered breakpoint schedule: the discount is 15.0% when the total quantity is at least 50, otherwise 12.5% when it is at least 25, otherwise 10.0% when it is at least 10, otherwise 5.0% when it is at least 5 (the group minimum), and otherwise 0%. For each line, `line_base_cents` is the line's ticket type `base_price_cents` multiplied by the line's `quantity`, and `line_discounted_cents` is `line_base_cents` multiplied by one minus the group discount percentage, rounded half up to a whole cent on that line individually. The order's `ticket_subtotal_cents` is then the sum of every line's already-rounded `line_discounted_cents`. The non-refundable `processing_fee_cents` is the smaller of two values: the subtotal multiplied by the fee rate of 3% and rounded half up to a whole cent, or the fee cap of 5000 cents. The order's `total_cents` is `ticket_subtotal_cents` plus `processing_fee_cents`. Finally, the order's `is_group` flag is set true exactly when the total badge quantity is at least the group minimum of five. Submitting increments the order's `version` by one.

The order also exposes an `amount_paid_cents`, which is the amount captured at payment and equals `total_cents` once the order is `PAID`; a `refund_amount_cents`, the final settled refund written when the order moves to `REFUNDED`; and a `provisional_refund_cents`, a forward-looking refund estimate described in §3.4. All three default to 0.

### 3.4. Payment, Badge Issuance, and Refunds

Paying a `PENDING_PAYMENT` order is the pivotal capacity-consuming step and advances the order to `PAID`. Several conditions must all hold at pay time. The convention's `posture` must be `OPEN`, otherwise the pay is blocked with `ERR_POSTURE_BLOCKED`. For every line, the line's ticket type `tier_issued_count` plus the quantities being paid for that tier must not exceed that ticket type's `tier_capacity`, otherwise `ERR_TIER_SOLD_OUT`. Across the whole order, the convention's `badges_issued_count` plus the sum of all line quantities must not exceed the convention's `total_badge_capacity`, otherwise `ERR_CAPACITY_EXCEEDED`. The request must carry `expected_convention_version` equal to the convention's current `version`, otherwise `ERR_STALE_CONVENTION_VERSION` (HTTP 412) as described in §2.7. Separately, when the convention's `posture` is `SOLD_OUT`, an attendee may only create a paid order if they hold a `WON` waitlist entry for that convention; an attempt to register under `SOLD_OUT` posture without a `WON` `WaitlistEntry` is rejected with `ERR_LOTTERY_NOT_WON`.

When a pay succeeds, the system sets `amount_paid_cents` to `total_cents` and then runs cascade A: it issues one **Badge** per badge unit on the order, each created with `status` `ISSUED`, `rfid_status` `UNASSIGNED`, and `holder_attendee_id` set to the purchaser; it recomputes the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` from the authoritative badge set (counting badges whose `status` is one of `ISSUED`, `PICKED_UP`, or `PRINTED`); and, if the convention's `badges_issued_count` has reached its `total_badge_capacity`, it flips `posture` to `SOLD_OUT`. The pay increments the convention's `version` by one.

A `DRAFT` or `PENDING_PAYMENT` order may instead be cancelled by its attendee, moving the order to the terminal `CANCELLED` state; cancelling sets `refund_amount_cents` to 0 (nothing was captured) and increments the order's `version` by one. There is no badge cascade because no badges were ever issued.

Refunds apply only to a `PAID` order and are performed by a `RegistrationAgent` or `ConventionAdmin`, moving the order to the terminal `REFUNDED` state. A refund is permitted only while the current clock is strictly before the convention's `event_end_utc`; at or after that instant refunds are closed and the attempt is rejected with `ERR_REFUND_WINDOW_CLOSED`. The refund amount uses a forward-looking penalty schedule keyed to how far ahead of the event the refund is executed. Let the number of whole days before the event be the difference between the convention's `event_start_utc` and the current clock, divided by the number of seconds in a day (86,400) and rounded down to a whole number. The penalty percentage is then 0% when more than 30 days remain, 25% when at least 8 days (but not more than 30) remain, 50% when at least 1 day (but fewer than 8) remains, and 100% on the day of the event or any time on or after the start (that is, when zero or fewer days remain). The final `refund_amount_cents` is the order's `ticket_subtotal_cents` multiplied by one minus the penalty percentage, rounded half up to a whole cent; the `processing_fee_cents` is never refunded. This is the FINAL variant of the refund calculation, computed from the penalty tier implied by the clock at execution time.

The same penalty schedule also drives a PROVISIONAL estimate. An attendee, agent, or admin may request a refund quote on an order at any time; that read computes the provisional refund from the penalty tier implied by the current clock and writes it to the order's `provisional_refund_cents`, recomputing it on every quote read; because writing that field is itself a mutation of the order, the quote read refreshes the order's `updated_at` and increments its `version` by one. Because it is forward-looking, the provisional quote becomes stale as the clock advances toward the event and crosses a penalty boundary, so if refund approval is delayed across such a boundary the FINAL `refund_amount_cents` will be strictly less than an earlier provisional quote for the same order. The PROVISIONAL value lives in `provisional_refund_cents` and is distinct from the settled `refund_amount_cents`.

Executing a refund runs cascade B atomically: every non-`VOID` badge of the order is voided (`status` `VOID`, `rfid_status` `DEACTIVATED`); for each voided badge, that badge's `CONFIRMED` and `WAITLISTED` session reservations are cancelled; for each `CONFIRMED` seat thereby freed, the highest-`waitlist_score` `WAITLISTED` reservation on that same session is promoted to `CONFIRMED` and the session's `seats_taken` is recomputed; the convention's `badges_issued_count` and each affected ticket type's `tier_issued_count` are recomputed downward from the surviving badge set; and if the convention was `SOLD_OUT` and its `badges_issued_count` is now below `total_badge_capacity`, its `posture` returns to `OPEN`. The refund increments the convention's `version` by one.

### 3.5. Badge Lifecycle: Pickup, Print, Transfer, and Void

A **Badge** carries two parallel state dimensions on the same row, each advancing on its own axis. The first is `status`, taking one of `ISSUED`, `PICKED_UP`, `PRINTED`, or `VOID`. The second is `rfid_status`, the RFID-activation dimension, taking one of `UNASSIGNED`, `ENCODED`, or `DEACTIVATED`. A badge also holds an `rfid_uid` — the hardware UID, null until RFID is encoded — and a `transfer_count` recording how many completed holder transfers it has undergone, starting at 0. Every badge references the `order_id` that paid for it, the `ticket_type_id` whose tier it grants, and its `holder_attendee_id`.

On-site pickup is a `RegistrationAgent` operation that advances a badge from `ISSUED` to `PICKED_UP`. It is permitted only when the badge is currently `ISSUED` and the on-site window is open, meaning the current clock is at or after the instant 48 hours before the convention's `event_start_utc`; the boundary instant itself counts as open. An attempt before that window opens is rejected with `ERR_PICKUP_WINDOW_CLOSED`. A successful pickup sets `rfid_status` to `ENCODED`, assigns the badge an `rfid_uid`, and increments the badge's `version` by one — the RFID dimension advancing independently of the `status` dimension.

Printing advances a badge from `PICKED_UP` to `PRINTED` and is also a `RegistrationAgent` operation. It requires the badge to be `PICKED_UP` and its `rfid_status` to be `ENCODED` — a print attempted on a badge that is not `PICKED_UP`, or whose `rfid_status` is not `ENCODED`, is rejected with `ERR_INVALID_STATE` — and it is likewise gated by the same on-site window, so a print attempted before the window opens is rejected with `ERR_PICKUP_WINDOW_CLOSED`. Printing increments the badge's `version` by one. Taken together, the two dimensions advance as `ISSUED → PICKED_UP → PRINTED` on the `status` axis and `UNASSIGNED → ENCODED → DEACTIVATED` on the `rfid_status` axis.

A badge may be transferred to a new holder by its current holder (an `Attendee`) or by a `RegistrationAgent`. A transfer carries a `new_holder_attendee_id`, updates the badge's `holder_attendee_id` to it, and increments `transfer_count` by one without changing the badge's `status`. Transfers are allowed only while the badge's `status` is `ISSUED` and its `transfer_count` is below the maximum of two completed transfers; a transfer attempted when the badge is not `ISSUED` or whose `transfer_count` already stands at that limit of two is rejected with `ERR_TRANSFER_LIMIT`.

Voiding a badge moves it to the terminal `VOID` state and may be performed by a `RegistrationAgent` or `ConventionAdmin`, or be triggered by the system as part of an order refund. A void is defined from any of `ISSUED`, `PICKED_UP`, or `PRINTED`. Voiding sets `rfid_status` to `DEACTIVATED`, cancels that badge's `CONFIRMED` and `WAITLISTED` session reservations — which in turn promotes the top waitlisted reservation on each freed session — recomputes (decrements) the convention's `badges_issued_count` and the relevant ticket type's `tier_issued_count` from the surviving badge set, and increments the badge's `version` by one.

### 3.6. Sessions and Seat Reservations

A **Session** is created under a convention by a `ConventionAdmin` with a `title`, a `start_utc` and an `end_utc` (the latter strictly after the former), a `seat_capacity` of one or more confirmed reservations, and an optional `requires_vip` flag that defaults to false. A session belongs to its convention through `convention_id` and tracks `seats_taken`, the count of its `CONFIRMED` reservations, starting at 0. Session intervals are treated as half-open: a session occupies the range from its `start_utc` up to but not including its `end_utc`.

A **Session Reservation** binds a badge to a session. An `Attendee` (for their own badge) or a `RegistrationAgent` creates one against a `session_id` and a `badge_id`, supplying `expected_session_version` for the optimistic-concurrency check of §2.7 and an optional `confirmed_only` flag. A reservation's `status` is `CONFIRMED`, `WAITLISTED`, or `CANCELLED`, and it carries a `waitlist_score` used to order waitlisted rows for promotion (0 for confirmed rows). Whether a new reservation lands as `CONFIRMED` or `WAITLISTED` is decided at create time: if the session's `seats_taken` is below its `seat_capacity` the reservation is `CONFIRMED` (and `seats_taken` is incremented), otherwise it is `WAITLISTED`. Creating a `CONFIRMED` reservation increments the session's `version` by one.

Two business constraints guard a reservation create. First, the badge must not already hold another `CONFIRMED` reservation whose half-open interval overlaps this session's half-open interval; two sessions that merely abut (one ending exactly when the other starts) do not overlap and are allowed, but a genuine overlap is rejected with `ERR_SESSION_TIME_CONFLICT`. Second, if the target session's `requires_vip` is true, the badge's ticket tier must be `VIP`, otherwise the reservation is rejected with `ERR_VIP_REQUIRED`. A full session is not normally an error: when `seats_taken` already equals `seat_capacity` the reservation is simply created `WAITLISTED`. Only when the caller passes `confirmed_only` as true and no seat is free does the create fail outright with `ERR_SESSION_FULL`.

The `waitlist_score` placed on a waitlisted reservation is computed by the priority-scoring rule (the same rule that scores lottery entries, see §3.8). For a session reservation the score is the holder attendee's loyalty points plus an early-bird bonus plus a group-size factor, with the group size defaulting to one for reservations.

Cancelling a reservation is performed by its owning attendee or the system. Cancelling a `CONFIRMED` reservation moves it to `CANCELLED`, decrements the session's `seats_taken` by one, then promotes the highest-`waitlist_score` `WAITLISTED` reservation on the same session to `CONFIRMED` — breaking ties by earliest `created_at` — and recomputes the session's `seats_taken`; this is cascade C. Cancelling a `WAITLISTED` reservation simply moves it to `CANCELLED`. Either cancellation increments the reservation's `version` by one. A system promotion of a waitlisted reservation to `CONFIRMED` may occur only while the session's `seats_taken` is below its `seat_capacity`; the promotion increments `seats_taken` by one, resets the promoted row's `waitlist_score` to 0, and increments that reservation's `version` by one.

### 3.7. Exhibitors, Booths, and Booth Bookings

The show floor is laid out as **Booths**, each created under a convention by a `ConventionAdmin`. A booth belongs to its convention through `convention_id`, carries a `booth_code` that must be unique within the convention (a duplicate code is rejected with `ERR_DUPLICATE_BOOTH_CODE`), a `zone` of `STANDARD`, `PREMIUM`, or `ENDCAP` that sets its daily rate, and a `setup_buffer_hours` integer (defaulting to 12, zero or greater) that pads each booking interval symmetrically for overlap detection.

An `Exhibitor` (or a `ConventionAdmin`) reserves floor time by creating a **Booth Booking** against a `booth_id` and an `exhibitor_id`, with an occupancy window from `occupy_start_utc` to `occupy_end_utc` (the end strictly after the start) and a `requested_days` count of one or more. The booking is born `RESERVED`, with `occupied_days` at 0. A booking's `status` is `RESERVED`, `CHECKED_IN`, or `RELEASED`. Before a booking is accepted, the system checks for floor conflicts: the requested window, expanded by the booth's `setup_buffer_hours` on each side (from `occupy_start_utc` minus the buffer to `occupy_end_utc` plus the buffer), must not overlap the similarly buffer-expanded window of any other `RESERVED` or `CHECKED_IN` booking on the same booth; these are treated as closed intervals, so any shared instant counts as overlap, and a conflict is rejected with `ERR_BOOTH_TIME_CONFLICT`.

Booth charges are kept on the exhibitor in two distinct figures. The forward-looking `estimated_booth_cents` is the sum, over every booking of that exhibitor whose `status` is `RESERVED` or `CHECKED_IN`, of the booking's booth zone daily rate multiplied by the booking's `requested_days`. The chronological `actual_booth_cents` is the sum, over only those bookings whose `status` is `CHECKED_IN`, of the booth zone daily rate multiplied by the booking's `occupied_days`. The zone daily rates are 50,000 cents for `STANDARD`, 120,000 cents for `PREMIUM`, and 200,000 cents for `ENDCAP`. Creating a booking recomputes the exhibitor's `estimated_booth_cents`. Because `estimated_booth_cents` bills the full `requested_days` of every still-active booking while `actual_booth_cents` bills only the `occupied_days` of checked-in bookings, an exhibitor with reserved-but-not-yet-checked-in bookings will have an actual charge below its estimate.

Checking in a `RESERVED` booking is performed by the booking's exhibitor or a `RegistrationAgent` and advances it to `CHECKED_IN`. Check-in is gated by the same on-site window as badge pickup — the current clock must be at or after 48 hours before the convention's `event_start_utc`, else `ERR_PICKUP_WINDOW_CLOSED`. Check-in sets `occupied_days` equal to `requested_days`, recomputes the exhibitor's `actual_booth_cents`, and increments the booking's `version` by one.

Releasing a booking moves it to the terminal `RELEASED` state and may be done from either `RESERVED` or `CHECKED_IN` by the booking's exhibitor or a `RegistrationAgent`. Releasing recomputes the exhibitor's `estimated_booth_cents` with this booking excluded and frees the booth interval so a later booking no longer overlaps it; when the booking had already been checked in, the exhibitor's `actual_booth_cents` retains the `occupied_days` already billed. Either release increments the booking's `version` by one.

### 3.8. The Lottery: Waitlist Entries and Allocation

When demand exceeds supply, attendees compete through a convention lottery. An `Attendee` (or a `RegistrationAgent` on their behalf) enters by creating a **Waitlist Entry** against a convention, supplying the `attendee_id`, a `requested_quantity` of one or more badges, and a declared `group_size` of one or more. Entering is gated by posture: a waitlist entry requires the convention's `posture` to be `OPEN` or `SOLD_OUT`, and is blocked with `ERR_POSTURE_BLOCKED` when the convention is `CLOSED`. At most one `ENTERED` waitlist entry may exist for any given convention-and-attendee pair; a second such entry is rejected with `ERR_DUPLICATE_WAITLIST`. A new entry begins in the `ENTERED` state, which is one of `ENTERED`, `WON`, or `LOST`.

Each entry's `priority_score` is computed and pinned at creation as the sum of three components. The first is loyalty points drawn from the entering attendee's `loyalty_tier`: 0 for `NONE`, 100 for `SILVER`, 200 for `GOLD`, and 300 for `PLATINUM`. The second is an early-bird bonus of 50 points, granted only when the entry's `created_at` is at or after the convention's `lottery_open_utc` and at the same time no later than 24 hours after that instant; outside that window the bonus is 0. The third is a group-size factor equal to the entry's `group_size` multiplied by 5 points per head, capped at 60 points. (This same scoring rule sets the `waitlist_score` of a waitlisted session reservation, where the group size is taken as one.)

A `ConventionAdmin` runs the allocation in a single deterministic batch. The run carries `expected_convention_version` matching the convention's current `version`. The allocation first computes the convention's remaining capacity as its `total_badge_capacity` minus its `badges_issued_count`. It then gathers every `ENTERED` waitlist entry for the convention and sorts them by `priority_score` from highest to lowest, breaking ties by earliest `created_at` (never by id). Walking that sorted order, each entry is granted on an all-or-nothing basis: if the entry's `requested_quantity` is no greater than the remaining capacity, the entry transitions to `WON` and its `requested_quantity` is subtracted from the remaining capacity; otherwise the entry transitions to `LOST` and the walk continues to later, smaller entries, which may still win. Winning grants the attendee eligibility to create a paid order under `SOLD_OUT` posture but does not itself issue any badges. Each entry's transition to `WON` or `LOST` increments its `version` by one, and running the lottery increments the convention's `version` by one.

### 3.9. Request Well-Formedness

Across all create and update operations, a request body must be well-formed: required fields present, enum-valued fields carrying only legal values, numeric fields within their stated ranges, and any end instant strictly after its corresponding start instant. A malformed body — a missing required field, an illegal enum value, an out-of-range number, or an end at or before its start — is rejected with `ERR_INVALID_REQUEST`. This is the lowest-priority check, evaluated only after the structural and business validations above have passed.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that read a resource or modify an existing one — including all state transitions, the clock control, and lottery run — return `200 OK`. Authentication and authorization are governed by §2.1; the "Authorized Role(s)" column lists the roles permitted to invoke each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/conventions` | Create a convention | ConventionAdmin |
| GET | `/conventions/{id}` | Read a convention | ConventionAdmin, RegistrationAgent, Attendee, Exhibitor |
| GET | `/conventions` | List conventions | ConventionAdmin, RegistrationAgent, Attendee, Exhibitor |
| POST | `/conventions/{id}/close` | Set convention posture to CLOSED | ConventionAdmin |
| POST | `/conventions/{id}/run-lottery` | Run the deterministic lottery allocation | ConventionAdmin |
| POST | `/conventions/{id}/ticket-types` | Create a ticket type under a convention | ConventionAdmin |
| GET | `/conventions/{id}/ticket-types` | List a convention's ticket types | ConventionAdmin, RegistrationAgent, Attendee, Exhibitor |
| GET | `/ticket-types/{id}` | Read a ticket type | ConventionAdmin, RegistrationAgent, Attendee, Exhibitor |
| POST | `/attendees` | Self-register an attendee | Anonymous, ConventionAdmin, RegistrationAgent |
| GET | `/attendees/{id}` | Read an attendee | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/attendees/{id}/ban` | Ban an attendee | ConventionAdmin |
| POST | `/orders` | Create a DRAFT order with line items | Attendee, RegistrationAgent |
| GET | `/orders/{id}` | Read an order | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/orders` | List orders (filter by purchaser_attendee_id or convention_id) | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/orders/{id}/line-items` | List an order's line items | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/ticket-line-items` | List line items (filter by order_id or ticket_type_id) | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/ticket-line-items/{id}` | Read a ticket line item | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/orders/{id}/submit` | Submit and price a DRAFT order | Attendee, RegistrationAgent |
| POST | `/orders/{id}/pay` | Pay an order, issuing badges | Attendee, RegistrationAgent |
| GET | `/orders/{id}/refund-quote` | Compute the provisional refund estimate | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT or PENDING_PAYMENT order | Attendee, RegistrationAgent |
| POST | `/orders/{id}/refund` | Refund a PAID order, voiding badges | RegistrationAgent, ConventionAdmin |
| GET | `/badges/{id}` | Read a badge | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/badges` | List badges (filter by order_id, ticket_type_id, or holder_attendee_id) | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/badges/{id}/pickup` | On-site pickup; encode RFID | RegistrationAgent |
| POST | `/badges/{id}/print` | Print a picked-up badge | RegistrationAgent |
| POST | `/badges/{id}/transfer` | Transfer a badge to a new holder | Attendee, RegistrationAgent |
| POST | `/badges/{id}/void` | Void a badge | RegistrationAgent, ConventionAdmin |
| POST | `/conventions/{id}/sessions` | Create a session under a convention | ConventionAdmin |
| GET | `/conventions/{id}/sessions` | List a convention's sessions | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/sessions/{id}` | Read a session | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/session-reservations` | Reserve a session seat for a badge | Attendee, RegistrationAgent |
| GET | `/session-reservations/{id}` | Read a reservation | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/session-reservations` | List reservations (filter by session_id or badge_id) | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/session-reservations/{id}/cancel` | Cancel a reservation; promote waitlist | Attendee, RegistrationAgent |
| POST | `/conventions/{id}/waitlist` | Enter the convention lottery | Attendee, RegistrationAgent |
| GET | `/conventions/{id}/waitlist` | List a convention's waitlist entries | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/waitlist-entries` | List waitlist entries (filter by attendee_id or convention_id) | ConventionAdmin, RegistrationAgent, Attendee |
| GET | `/waitlist-entries/{id}` | Read a waitlist entry | ConventionAdmin, RegistrationAgent, Attendee |
| POST | `/exhibitors` | Self-register an exhibitor | Anonymous, ConventionAdmin |
| GET | `/exhibitors/{id}` | Read an exhibitor | ConventionAdmin, RegistrationAgent, Exhibitor |
| GET | `/exhibitors` | List exhibitors (filter by convention_id) | ConventionAdmin, RegistrationAgent, Exhibitor |
| POST | `/conventions/{id}/booths` | Create a booth on the convention floor | ConventionAdmin |
| GET | `/conventions/{id}/booths` | List a convention's booths | ConventionAdmin, RegistrationAgent, Exhibitor |
| GET | `/booths/{id}` | Read a booth | ConventionAdmin, RegistrationAgent, Exhibitor |
| POST | `/booth-bookings` | Book a booth over an occupancy interval | Exhibitor, ConventionAdmin |
| GET | `/booth-bookings/{id}` | Read a booth booking | ConventionAdmin, RegistrationAgent, Exhibitor |
| GET | `/booth-bookings` | List booth bookings (filter by booth_id or exhibitor_id) | ConventionAdmin, RegistrationAgent, Exhibitor |
| POST | `/booth-bookings/{id}/check-in` | Check in a reserved booking | Exhibitor, RegistrationAgent |
| POST | `/booth-bookings/{id}/release` | Release a booking, freeing the interval | Exhibitor, RegistrationAgent |
| POST | `/_clock/set` | Test-driving: set the server's current UTC clock | ConventionAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ATTENDEE_BANNED` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PICKUP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_REFUND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SESSION_TIME_CONFLICT` | 409 Conflict |
| `ERR_VIP_REQUIRED` | 409 Conflict |
| `ERR_BOOTH_TIME_CONFLICT` | 409 Conflict |
| `ERR_TRANSFER_LIMIT` | 409 Conflict |
| `ERR_DUPLICATE_WAITLIST` | 409 Conflict |
| `ERR_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_TIER_SOLD_OUT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_STALE_CONVENTION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SESSION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ATTENDEE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_BOOTH_CODE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_LOTTERY_NOT_WON` | 409 Conflict |
