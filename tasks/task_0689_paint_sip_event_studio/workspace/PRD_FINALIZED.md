# Paint & Sip Event Studio API — Product Requirements Document

## 1. Introduction

The Paint & Sip Event Studio API powers the back-office and floor operations of a "Painting with a Twist"-style social-art business. Each location runs a calendar of guided painting classes held in physical studio rooms, mixing scheduled public classes with privately booked parties, charity fundraisers, and corporate team events. The platform's central challenge is the management of a finite seat pool against a clock: seats are reserved, committed, and released in real time as customers book online, walk in on the day, or cancel ahead of an event, and the same seat must never be sold twice even when several bookers reach for the last chair at once.

Beyond seat accounting, the system coordinates the many moving parts that surround an event. Instructors (artists) are assigned to events and must not be double-booked across overlapping time windows; canvas-and-supply kits are stocked in batches and consumed at check-in; bring-your-own-beverage events impose age and waiver gates before anyone may be seated; and money flows through tiered group pricing, a cancellation-credit ladder, a gift-card and studio-credit payment waterfall, and a fundraiser donation pledge that is provisional until the event closes. This document specifies every entity, lifecycle, calculation, and guard rule that an implementation must honor so that managers, customers, front-desk staff, and platform operators all see one consistent, immediately-reconciled view of the studio's operations.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint in the API. All resources are served beneath the `/studio-ops` prefix, except for the test-driving clock control endpoint described later.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `StudioManager`, `Customer`, `FrontDesk`, and `PlatformAdmin`. When an authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles relate to persisted identity in different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any reservation compare the reservation's `customer_id` to `X-User-ID`. A `Customer` may act only on reservations they own — paying, confirming, or cancelling another customer's reservation, or booking with a `customer_id` other than their own, is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; a `StudioManager` operates studios, artists, events, assignments, kit batches, and gift cards, and may also act on any reservation on behalf of the studio. When `X-User-Role` is `FrontDesk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the front desk registers and cancels walk-ins and checks in attendees on the day of the event. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator controls the logical clock and may perform any operation as an operator override (a superset of all other roles). The server may record an opaque operator identifier where a workflow naturally captures it, but it never compares such an identifier to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields. Every such resource exposes an `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix. It also exposes a `created_at` field, an ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) recording when the resource was first created.

Resources that may change after creation additionally carry an `updated_at` field and a `version` field. The `updated_at` field is an ISO 8601 UTC timestamp (three fractional digits) refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins the optimistic-concurrency mechanism described below. The Studio, Artist, Customer, StudioEvent, ArtistAssignment, CanvasKitBatch, Reservation, WalkIn, GiftCard, and Payment resources all carry `id`, `created_at`, `updated_at`, and `version`.

The Attendee resource is the sole exception: it carries only `id` and `created_at`. Attendee records have no `updated_at` and no `version` field — neither is present in an Attendee's representation.

### 2.5. Nested Resource Retrieval and Reference Resolution

Several endpoints address a resource by an identifier embedded in the URL path. When such a path identifier does not correspond to an existing resource, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Where a path carries more than one identifier, the identifiers are validated left to right, and the first one that fails to resolve produces the `ERR_NOT_FOUND` rejection before any later segment is considered.

References supplied inside a request body are validated separately. When a body names a foreign entity — a `studio_id`, `event_id`, `customer_id`, `artist_id`, `reservation_id`, or any of the supplied gift-card identifiers — and that entity does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422). This body-reference check applies to event creation, reservation creation, assignment creation, kit-batch creation, attendee creation, walk-in registration, and reservation payment. List endpoints accept optional filter parameters that resolve resources in reverse (for example, listing reservations by `event_id` or `customer_id`); these filters narrow the returned collection rather than addressing a single resource.

### 2.6. Validation Order and Error Precedence

When several conditions could each reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication is checked first: a missing or unknown header pair yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the operation, or a `Customer` acting on a reservation they do not own, yields `ERR_FORBIDDEN`. Existence of the path resource is checked third, yielding `ERR_NOT_FOUND`. Request-body well-formedness is checked fourth — required fields present, enum values valid, integers positive where required, and pagination parameters within bounds — yielding `ERR_VALIDATION` (HTTP 400) on failure.

After those four universal gates, body-referenced foreign keys are resolved (`ERR_REFERENCE_NOT_FOUND`), then uniqueness constraints are enforced (`ERR_DUPLICATE_RESOURCE`), then the target's state is checked for transition validity (`ERR_INVALID_STATE`), and then operation-specific business rules apply. The detailed business rules and their precise trigger conditions are described in their natural workflow homes throughout §2.7 onward and §3; the ordering stated here governs which error surfaces first when more than one applies. Where a more specific business rule shares an endpoint with these gates, that rule's relative position is called out in the workflow narrative where it lives.

### 2.7. Uniqueness Constraints

Two values must be unique across the system. A `Customer` registers with an `email`, and email comparison is case-insensitive: registering an email that collides with an existing customer's email (ignoring letter case) is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A `GiftCard` is issued with a `code`, which must not collide with the code of any existing gift card; a collision is likewise rejected with `ERR_DUPLICATE_RESOURCE`. These checks apply to customer creation and gift-card creation respectively.

### 2.8. The Seat Ledger and Capacity Discipline

Every `StudioEvent` maintains a live seat ledger that is recomputed immediately whenever a reservation or walk-in is created, cancelled, or marked a no-show, and whenever the event closes. The ledger derives three values. `seats_reserved` is the sum of `seats` over all of the event's reservations whose status is `HELD`, `CONFIRMED`, or `CHECKED_IN`. `walk_in_seats` is the sum of `party_size` over all of the event's walk-ins whose status is `REGISTERED` or `CHECKED_IN`. `seats_available` is the event's `seats_capacity` minus `seats_reserved` minus `walk_in_seats`, floored at zero so that it never reports a negative number.

A booking may never oversell the room. When a reservation is created, its requested `seats` must not exceed the event's current `seats_available`; when a walk-in is registered, its `party_size` must not exceed the current `seats_available`. A request that would exceed available seats is rejected with `ERR_INSUFFICIENT_SEATS` (HTTP 409). Because a `FULL` event has zero seats available, it still rejects further seat-consuming bookings on this rule.

### 2.9. Optimistic Concurrency on Seat Grabs

Creating a reservation is the one write that is guarded by optimistic concurrency control against its parent event. A reservation-create request must carry `expected_event_version`, a non-optional field carrying the client's last observed `version` of the target `StudioEvent`. If `expected_event_version` does not equal the event's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). This captures the case where another booking has already consumed seats and advanced the event toward `FULL` since the client last read it: the booker's view of remaining seats is stale, and the reservation must be re-evaluated against fresh capacity rather than overwriting a state the client never observed. No other endpoint accepts or requires a version field; only reservation creation participates in this check.

### 2.10. Monetary Precision, Seat Precision, and Rounding

All monetary amounts in the system are whole integer cents — prices, kit fees, totals, credits, donations, gift-card balances, and payments are never fractional. Wherever a percentage is applied to a cent amount (group discounts, cancellation credit, fundraiser donations), the result is taken by integer floor division: multiply first, then divide by 100 discarding any remainder (rounding toward zero). Seat counts and party sizes are whole integers, and `seats_available` is floored at zero as described in §2.8. The payment waterfall performs exact integer allocation with no rounding at all. No floating-point arithmetic is used for any of these computations.

### 2.11. Immediate Consistency, Cascades, and Versioning of Mutations

The system is immediately consistent: every derived field is recomputed within the same operation that changes its inputs, with no deferred reconciliation. When a mutation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one. Several operations cascade across multiple aggregates — cancelling an event, for example, touches its reservations, their payments, the affected customers' credit wallets, the event's artist assignments, and its walk-ins. Each such cascade is described in full in the workflow narratives of §3, including which entities change, in what order, and how the event's own `version` advances. The event lifecycle also includes two automatic, system-driven transitions between `OPEN` and `FULL` that are not requested explicitly by any client but are applied by the server as seat occupancy crosses zero; these are detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Studios, Artists, Customers, and Gift Cards: the Standing Catalogue

Before any event can run, the studio's standing catalogue must exist. A `StudioManager` (or `PlatformAdmin`) creates a **Studio** — a physical room — by supplying its display `name`, its physical seat capacity `room_capacity_seats` (which must be at least 1), and optionally its `timezone`, an IANA label used for display only since all stored timestamps are UTC; when omitted the timezone defaults to `America/Chicago`. A new studio begins life in `ACTIVE` status. A studio may be retired, transitioning from `ACTIVE` to `CLOSED`; a `CLOSED` studio can no longer host newly scheduled events.

Artists are the instructors. A manager registers an **Artist** with a `full_name` and an `hourly_rate_cents` (an informational echo of the instructor's pay rate per hour in cents, which must be at least 0). An artist starts `ACTIVE` and may be deactivated to `INACTIVE`; an `INACTIVE` artist can no longer receive new assignments.

Customers may self-register, or a manager may register them. A **Customer** is created with a unique `email`, a `full_name`, and a `birthdate` (a date of birth stored at midnight UTC, kept for information only). On creation the customer's studio-credit wallet is initialized: both `credit_balance_cents` and `credit_redeemed_cents` start at 0. The wallet's `credit_balance_cents` is the spendable balance — increased by cancellation credits and operator grants, decreased when credit is spent on a reservation — and it may never go negative. The `credit_redeemed_cents` field is the lifetime amount of studio credit the customer has spent on reservations; the sum of `credit_balance_cents` and `credit_redeemed_cents` is conserved against the total credit ever granted to that customer. An operator may adjust a customer's wallet directly through a credit-adjustment, supplying an `amount_cents` (positive to grant, negative to debit) and a `reason`. A positive grant raises both the spendable balance and the conserved credit total. A debit that would drive `credit_balance_cents` below 0 is rejected with `ERR_CREDIT_INSUFFICIENT` (HTTP 422).

A **GiftCard** is issued by a manager with a unique `code` and an `issued_value_cents` face value (at least 1 cent), which is immutable. At issuance the card's spendable `balance_cents` equals `issued_value_cents` and its `redeemed_cents` is 0, and its status is `ACTIVE`. As the card is drawn upon, `balance_cents` decreases and `redeemed_cents` increases, and the identity that `balance_cents` plus `redeemed_cents` equals `issued_value_cents` is always conserved. The moment a redemption brings `balance_cents` to exactly 0, the card automatically transitions to `DEPLETED` and is no longer tappable.

### 3.2. Building an Event: Configuration, Staffing, and the Calendar

A `StudioManager` creates a **StudioEvent** in `DRAFT` status by naming the hosting room via `studio_id`, a `title`, and an `event_type` — one of `PUBLIC_CLASS`, `PRIVATE_PARTY`, `FUNDRAISER`, or `CORPORATE`, fixed at creation. The event's time window is given by `start_utc` (inclusive) and `end_utc` (exclusive), and the window must be valid: `end_utc` must fall strictly after `start_utc`. The event declares `seats_capacity`, its total bookable seats (at least 1), which must not exceed the hosting studio's `room_capacity_seats`. It sets `price_cents_per_seat` (the list price per seat, at least 0) and may set `kit_fee_cents`, the per-seat canvas/supply-kit fee charged when a reservation opts into kits (at least 0, defaulting to 0).

Two further options shape the event. The `byob_allowed` flag (default false) marks an event as bring-your-own-beverage; when true, every attendee must clear an age and waiver gate before check-in. The `min_age` field (default 0, at least 0) is the minimum attendee age in whole years; a caller configuring a BYOB event is expected to pass 21. Finally, `fundraiser_donation_pct` is the whole-percent of seat revenue pledged to the beneficiary: it is required to be between 1 and 100 inclusive when the `event_type` is `FUNDRAISER`, and it must be 0 for every other event type (it defaults to 0). At creation the system validates the event configuration as a unit: if `seats_capacity` exceeds the host studio's `room_capacity_seats`, or `end_utc` is not strictly after `start_utc`, or the fundraiser-percent rule is violated for the chosen `event_type`, the create is rejected with `ERR_INVALID_EVENT_CONFIG` (HTTP 422).

An event must not collide with another event in the same room. At creation, and again when the event is scheduled, the system rejects the event if any other non-`CANCELLED` `StudioEvent` in the same studio occupies an overlapping time window. Windows are half-open: two events overlap when one starts strictly before the other ends and ends strictly after the other starts, so back-to-back events where one's `end_utc` exactly equals the next's `start_utc` are adjacent and allowed, not a conflict. A conflict is rejected with `ERR_STUDIO_TIME_CONFLICT` (HTTP 409).

Staffing is recorded through the **ArtistAssignment** junction, which links an event to an instructor and carries the many-to-many relationship between artists and events. A manager creates an assignment by supplying the `event_id` and the `artist_id`; the assignment begins `ASSIGNED`. Two guards apply. The artist must be `ACTIVE`; assigning an `INACTIVE` artist is rejected with `ERR_ARTIST_INACTIVE` (HTTP 422). The artist must also be free: an artist may not hold another `ASSIGNED` assignment on an event whose time window, widened by a 30-minute travel buffer on each side, overlaps this event's window. Concretely, the buffer extends the comparison window to begin 30 minutes before the event's `start_utc` and end 30 minutes after its `end_utc`; a clear gap of exactly 30 minutes between two events is permitted, but anything closer is a double-booking and is rejected with `ERR_ARTIST_DOUBLE_BOOKED` (HTTP 409). An assignment may later be released, transitioning from `ASSIGNED` to `RELEASED`.

Canvas and supply inventory is stocked through a **CanvasKitBatch**. A manager stocks a batch for an event by supplying the `event_id`, a `sku` label, and a `prepared_count` (at least 0). The batch's `consumed_count` starts at 0 and rises as kits are consumed at check-in; it never exceeds `prepared_count`.

The event calendar is browsable. The list-events endpoint supports filtering by `studio_id`, `status`, `event_type`, and by a time window via `from_utc` and `to_utc`, in addition to the standard `limit` and `offset`. Listing assignments supports filtering by `event_id`, `artist_id`, and `status`; listing kit batches supports filtering by `event_id`.

### 3.3. Opening an Event for Booking

An event progresses through a branching lifecycle whose `status` runs across `DRAFT`, `SCHEDULED`, `OPEN`, `FULL`, `CLOSED`, and `CANCELLED`, beginning at `DRAFT` with `CLOSED` and `CANCELLED` as terminal states. A manager schedules a `DRAFT` event, advancing it `DRAFT → SCHEDULED`. Scheduling has three preconditions: at least one `ArtistAssignment` in status `ASSIGNED` must reference the event, the hosting studio must be `ACTIVE`, and there must be no room-time conflict with another non-`CANCELLED` event in the same studio (the same `ERR_STUDIO_TIME_CONFLICT` guard as at creation). A successful schedule increments the event's `version` by one. An attempt to schedule an event that is not in `DRAFT`, or any other transition attempted from an incompatible state, is rejected with `ERR_INVALID_STATE` (HTTP 409).

From `SCHEDULED`, a manager opens the event for booking, advancing it `SCHEDULED → OPEN`; bookings are only accepted once the event is `OPEN` (or `FULL`). Opening increments the event's `version` by one. From this point the event's occupancy may flip automatically between `OPEN` and `FULL`: whenever a seat-consuming mutation drives `seats_available` to exactly 0, the system transitions the event `OPEN → FULL`; whenever a seat-releasing mutation brings `seats_available` back above 0, the system transitions it `FULL → OPEN`. These two transitions are performed by the system itself as a consequence of seat changes, not by any direct client request.

### 3.4. Reserving Seats: Pricing and the Group Discount

A reservation is how a customer claims seats. A `Customer` (acting for themselves) or a manager creates a **Reservation** by supplying the `event_id`, the `customer_id`, a `booking_mode`, the number of `seats` requested (at least 1), the required `expected_event_version` for the concurrency check, and optionally `include_supply_kit` (default false). A new reservation begins with booking status `HELD` and payment status `UNPAID`. The parent event must be in `OPEN` or `FULL` status for a reservation to be created; otherwise the create is rejected with `ERR_INVALID_STATE`.

The `booking_mode` must match the event type. `PUBLIC` seat booking is allowed only on `PUBLIC_CLASS` and `FUNDRAISER` events, and `PRIVATE` whole-party booking is allowed only on `PRIVATE_PARTY` and `CORPORATE` events; any other pairing is rejected with `ERR_BOOKING_MODE_MISMATCH` (HTTP 422). Capacity (§2.8) and the optimistic-concurrency check on `expected_event_version` (§2.9) also apply to every reservation create.

Pricing is computed at creation and recorded on the reservation. The `base_cents` is the requested `seats` multiplied by the event's `price_cents_per_seat`. A tiered group discount is then selected from the seat count and stored as `group_discount_pct`: a reservation of 8 or more seats earns 15 percent; a reservation of 4 to 7 seats inclusive earns 10 percent; a reservation of 3 or fewer seats earns 0 percent. The rounding order is pinned to discount-then-add. First the discount is applied to the whole-cent base by integer floor division — the discounted base is `base_cents` minus the quantity (`base_cents` multiplied by `group_discount_pct`, then divided by 100 discarding any remainder). Then the kit charge is computed: `kit_charge_cents` is the requested `seats` multiplied by the event's `kit_fee_cents` when `include_supply_kit` is true, and 0 otherwise. The reservation's `total_cents` is the discounted base plus `kit_charge_cents`. The kit charge is never discounted.

Creating a reservation has further effects on the parent event. The seat ledger is recomputed, and if the new reservation drives `seats_available` to 0 the event flips `OPEN → FULL`. For a `FUNDRAISER` event the provisional pledged donation is recomputed (see §3.8). The event's `version` is incremented by one as part of the create — which is exactly why a concurrent booker's `expected_event_version` may now be stale.

### 3.5. Paying a Reservation: the Gift-Card and Credit Waterfall

A held or confirmed reservation is paid through a payment waterfall. A `Customer` (for their own reservation) or a manager pays a reservation, optionally supplying `gift_card_ids` (the cards to tap) and `use_studio_credit` (whether to draw on the customer's wallet). Payment is permitted only while the reservation's booking status is `HELD` or `CONFIRMED`; otherwise it is rejected with `ERR_INVALID_STATE`. Every gift card supplied to the waterfall must be `ACTIVE`; if any supplied card is `DEPLETED` (zero balance) when the waterfall reaches it, the payment is rejected with `ERR_GIFT_CARD_DEPLETED` (HTTP 422).

The waterfall covers the reservation's `total_cents` by drawing from sources in a pinned bucket order, recording one **Payment** row per source actually tapped. First come the supplied gift cards, processed in ascending order of each card's `created_at`: for each card the amount drawn is the smaller of the card's `balance_cents` and the still-uncovered remainder, and when that draw is positive a `Payment` is recorded with `method` of `GIFT_CARD` and the card's identity in `gift_card_id`, the card's `balance_cents` decreases by the draw while its `redeemed_cents` increases by the same amount, and if the card's `balance_cents` reaches 0 it becomes `DEPLETED`. Second, if `use_studio_credit` was requested and the customer's `credit_balance_cents` is positive, the amount drawn is the smaller of that balance and the remaining uncovered amount; when positive, a `Payment` with `method` of `STUDIO_CREDIT` is recorded, the customer's `credit_balance_cents` decreases by the draw and their `credit_redeemed_cents` increases by the same amount. Third, any remainder still uncovered after gift cards and credit is charged to card: a single `Payment` with `method` of `CARD` is recorded for the whole remainder. Because the card source always absorbs whatever is left, a well-formed payment always reaches full coverage. Each created Payment is `SETTLED` and carries an `amount_cents` equal to the amount drawn from that source.

After the waterfall runs, the reservation's `amount_paid_cents` — the sum of `amount_cents` over its `SETTLED` payments — is recomputed and its `payment_status` becomes `PAID`. The booking status and the payment status are two independent dimensions of the same reservation: payment does not by itself change the booking status, which remains `HELD` or `CONFIRMED` as it was.

### 3.6. Confirming, Rostering, and Checking In

Payment and booking status evolve as parallel axes. Once a reservation's `payment_status` is `PAID`, a `Customer` or manager may confirm it, advancing the booking status `HELD → CONFIRMED`; confirmation requires both that `payment_status` is `PAID` and that the parent event is in `OPEN` or `FULL` status, and an attempt that violates either is rejected with `ERR_INVALID_STATE`. Should a confirmed reservation lose its paid standing — when its payment status drops back to `UNPAID` before check-in — the system reverts it `CONFIRMED → HELD` automatically, leaving the seats reserved. This payment-side drop itself occurs when all of a reservation's payments have been reversed while the reservation is still `HELD`, at which point the `payment_status` returns to `UNPAID`; if the reservation had been confirmed, that drop drives the `CONFIRMED → HELD` revert.

Before a reservation can be checked in, its attendee roster must be built. An **Attendee** is added to a reservation by supplying the owning `reservation_id`, the attendee's `full_name`, their `age_years` (whole years at event time, at least 0), and optionally `waiver_signed` (default false) indicating whether the liability/BYOB waiver has been signed. Attendees may be listed by `reservation_id`.

A `FrontDesk` operator (or manager) checks in a confirmed reservation on the day, advancing the booking status `CONFIRMED → CHECKED_IN`. Check-in is gated by three conditions. The parent event must be in `OPEN` or `FULL` status. The number of `Attendee` rows on the reservation must exactly equal the reservation's `seats`; a roster with too few or too many attendees is rejected with `ERR_ATTENDEE_ROSTER_INCOMPLETE` (HTTP 422). And if the event is `byob_allowed`, every attendee must have `waiver_signed` true and an `age_years` of at least the event's `min_age`; any attendee failing either part is rejected with `ERR_WAIVER_OR_AGE_FAIL` (HTTP 422). On a successful check-in, if the reservation opted into kits via `include_supply_kit`, the event's `CanvasKitBatch` has its `consumed_count` increased by the reservation's `seats`, capped so that `consumed_count` never exceeds `prepared_count`.

### 3.7. Walk-Ins on the Day

The front desk also handles parties who arrive without a reservation. A `FrontDesk` operator (or manager) registers a **WalkIn** against an event by supplying the `event_id`, a `party_name`, the `party_size` (at least 1), and optionally `include_supply_kit` (default false). A walk-in begins `REGISTERED` and consumes seats immediately: the event's seat ledger is recomputed and, if the registration drives `seats_available` to 0, the event flips `OPEN → FULL`. Registering a walk-in is a seat-consuming event mutation, so the event's `version` is incremented by one as part of the registration. As with reservations, the parent event must be in `OPEN` or `FULL` to register a walk-in, and the `party_size` must not exceed the current `seats_available` (else `ERR_INSUFFICIENT_SEATS`). A walk-in may be cancelled, transitioning to `CANCELLED`, which releases its seats; the ledger is recomputed, the event flips `FULL → OPEN` if seats free up, and the event's `version` is incremented by one. A walk-in's lifecycle status is one of `REGISTERED`, `CHECKED_IN`, or `CANCELLED`.

### 3.8. Fundraisers: Pledged Versus Settled Donations

A `FUNDRAISER` event carries two donation figures, both expressed in cents and both 0 for non-fundraiser events. The provisional `pledged_donation_cents` is forward-looking and is recomputed on every reservation create and cancel for fundraiser events. It is the event's `fundraiser_donation_pct` applied once to the aggregated base: first sum the `total_cents` of every reservation on the event whose status is `HELD` or `CONFIRMED`, then multiply that sum by `fundraiser_donation_pct` and divide by 100 by floor division. The order is pinned — aggregate the base across the qualifying reservations first, then apply the percentage exactly once and floor the single result.

The final `settled_donation_cents` is computed once, at the moment the event closes, over actual attendance: sum the `total_cents` of every reservation on the event whose status is `CHECKED_IN`, then multiply by `fundraiser_donation_pct` and divide by 100 by floor division, again summing the base first and applying the percentage once. No-shows and cancellations are excluded from the settled figure. Before close the settled figure remains 0; after close the pledged figure is no longer recomputed.

### 3.9. Cancelling a Reservation: the Credit Ladder

A `Customer` (for their own reservation) or a manager may cancel a reservation that is in `HELD` or `CONFIRMED` status, provided the parent event is neither `CLOSED` nor `CANCELLED`; a cancel attempt against a closed or cancelled event is rejected with `ERR_INVALID_STATE`. Cancellation runs the credit ladder. First the system records `cancelled_at_hours_before`: the whole number of hours between the cancellation moment (the current logical clock) and the event's `start_utc`, computed as the difference in seconds divided by 3600 and floored, which may be negative if the event has already started. The credit percentage is then chosen from that hour count: a cancellation at 48 or more hours before start earns 100 percent; a cancellation from 24 hours up to but not including 48 hours before start earns 50 percent; a cancellation fewer than 24 hours before start earns 0 percent. The granted credit `credit_granted_cents` is the reservation's `total_cents` multiplied by that percentage and divided by 100 by floor division.

The cancellation then cascades. If the reservation's `payment_status` is `PAID`, its `SETTLED` `CARD` payments are reversed (each such `Payment` moves to `REVERSED`) and the reservation's `payment_status` becomes `REFUNDED`. The customer's `credit_balance_cents` is increased by `credit_granted_cents`. The reservation's booking status moves to `CANCELLED`, its seats are released, the parent event's seat ledger is recomputed, the event flips `FULL → OPEN` if seats free up, and the event's `version` is incremented by one.

Customers can preview the outcome before committing. A what-if cancellation quote evaluates the ladder against the current clock without mutating anything, returning the `hours_before`, the chosen `credit_pct`, and the resulting `credit_granted_cents`. Because the quote reflects only the clock at the instant it is requested, the credit actually realized at a later real cancellation may be lower if the clock has by then advanced into a lower tier.

### 3.10. Closing an Event and the No-Show Sweep

Once an event has started, a manager closes it, advancing it `OPEN → CLOSED` or `FULL → CLOSED`. Closing requires that the logical clock has reached or passed the event's `start_utc`; closing before the event has started is rejected with `ERR_EVENT_NOT_STARTED` (HTTP 409). Closing cascades across the event's bookings. Every reservation still in `HELD` or `CONFIRMED` is swept to `NO_SHOW` — its seats are released, no credit is granted, and it is excluded from the settled donation. Every walk-in still in `REGISTERED` is advanced to `CHECKED_IN`. For a `FUNDRAISER` event, `settled_donation_cents` is computed over the `CHECKED_IN` reservations as described in §3.8. Closing increments the event's `version` by one. A reservation reaching `NO_SHOW` is terminal, as is one reaching `CANCELLED`.

### 3.11. Cancelling an Event: the Full-Credit Cascade

A manager may cancel an event from any non-terminal state — `DRAFT`, `SCHEDULED`, `OPEN`, or `FULL` — provided it is neither `CLOSED` nor `CANCELLED` already; otherwise the cancel is rejected with `ERR_INVALID_STATE`. An event cancellation is studio-initiated and therefore generous, overriding the ordinary credit ladder. The event moves to `CANCELLED`, and the cascade proceeds in hops. In the first hop, each reservation in `HELD`, `CONFIRMED`, or `CHECKED_IN` is cancelled to `CANCELLED` with full credit — the credit ladder is bypassed and the percentage is forced to 100 regardless of how many hours remain before start, so each such reservation's `credit_granted_cents` equals its full `total_cents` (studio-fault full credit). In the second hop, each such reservation whose `payment_status` is `PAID` has its `SETTLED` `CARD` payments reversed to `REVERSED` and its `payment_status` set to `REFUNDED`. In the third hop, each affected customer's `credit_balance_cents` is increased by the cancelled reservation's `total_cents`. In addition, each `ArtistAssignment` in `ASSIGNED` is released to `RELEASED`, and each `WalkIn` in `REGISTERED` or `CHECKED_IN` is cancelled to `CANCELLED`. The event's `version` is incremented by one as part of the cancellation.

### 3.12. The Logical Clock

All time-gated rules — the cancellation ladder's hour bucketing, the cancellation quote, the event-not-started guard at close — are evaluated against a server-controlled logical clock rather than wall-clock time. A `PlatformAdmin` may drive this clock to an absolute UTC instant by supplying the target instant as `to_iso8601`; the response echoes the new `now_utc`. The server's startup default is `2026-04-01T00:00:00Z`, and before any clock-setting call the clock reads exactly that default and never falls back to real-world wall-clock time. Subsequent time-gated rules evaluate against whatever instant the clock currently holds.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions, payments, and clock control — return a `200 OK` status code. All listed `/studio-ops` endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1; the authorized roles for each endpoint are given below, and `PlatformAdmin` may perform any operation as an operator override.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | PlatformAdmin |
| POST | `/studio-ops/studios` | Create a studio (room) | StudioManager, PlatformAdmin |
| GET | `/studio-ops/studios/{id}` | Get a studio | StudioManager, FrontDesk, Customer, PlatformAdmin |
| GET | `/studio-ops/studios` | List studios (paginated) | StudioManager, FrontDesk, Customer, PlatformAdmin |
| POST | `/studio-ops/studios/{id}/close` | Retire a studio room (ACTIVE → CLOSED) | StudioManager, PlatformAdmin |
| POST | `/studio-ops/artists` | Create an artist (instructor) | StudioManager, PlatformAdmin |
| GET | `/studio-ops/artists/{id}` | Get an artist | StudioManager, FrontDesk, PlatformAdmin |
| POST | `/studio-ops/artists/{id}/deactivate` | Mark an artist INACTIVE | StudioManager, PlatformAdmin |
| POST | `/studio-ops/customers` | Register a customer | Customer, StudioManager, PlatformAdmin |
| GET | `/studio-ops/customers/{id}` | Get a customer (with credit wallet) | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/customers/{id}/credit-adjustments` | Grant or debit studio credit | StudioManager, PlatformAdmin |
| POST | `/studio-ops/gift-cards` | Issue a gift card | StudioManager, PlatformAdmin |
| GET | `/studio-ops/gift-cards/{id}` | Get a gift card | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/events` | Create a studio event in DRAFT | StudioManager, PlatformAdmin |
| GET | `/studio-ops/events/{id}` | Get a studio event (with seat ledger and donation fields) | StudioManager, FrontDesk, Customer, PlatformAdmin |
| GET | `/studio-ops/events` | List events (calendar) | StudioManager, FrontDesk, Customer, PlatformAdmin |
| POST | `/studio-ops/events/{id}/schedule` | Schedule a DRAFT event (requires a staffed artist) | StudioManager, PlatformAdmin |
| POST | `/studio-ops/events/{id}/open` | Open a SCHEDULED event for booking | StudioManager, PlatformAdmin |
| POST | `/studio-ops/events/{id}/close` | Close an event after it has started | StudioManager, PlatformAdmin |
| POST | `/studio-ops/events/{id}/cancel` | Cancel an event (studio-initiated full-credit cascade) | StudioManager, PlatformAdmin |
| POST | `/studio-ops/assignments` | Assign an artist to an event | StudioManager, PlatformAdmin |
| GET | `/studio-ops/assignments/{id}` | Get an assignment | StudioManager, FrontDesk, PlatformAdmin |
| GET | `/studio-ops/assignments` | List assignments | StudioManager, FrontDesk, PlatformAdmin |
| POST | `/studio-ops/assignments/{id}/release` | Release an artist assignment | StudioManager, PlatformAdmin |
| POST | `/studio-ops/kit-batches` | Stock a canvas/supply kit batch for an event | StudioManager, PlatformAdmin |
| GET | `/studio-ops/kit-batches/{id}` | Get a kit batch | StudioManager, FrontDesk, PlatformAdmin |
| GET | `/studio-ops/kit-batches` | List kit batches | StudioManager, FrontDesk, PlatformAdmin |
| POST | `/studio-ops/reservations` | Create a seat reservation (HELD) | Customer, StudioManager, PlatformAdmin |
| GET | `/studio-ops/reservations/{id}` | Get a reservation | Customer, FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/reservations` | List reservations | FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/reservations/{id}/cancellation-quote` | What-if provisional cancellation credit at the current clock | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/reservations/{id}/pay` | Pay a reservation via gift-card/credit/card waterfall | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/reservations/{id}/confirm` | Confirm a paid HELD reservation | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/reservations/{id}/check-in` | Check in a confirmed reservation (BYOB age/waiver gate) | FrontDesk, StudioManager, PlatformAdmin |
| POST | `/studio-ops/reservations/{id}/cancel` | Cancel a reservation (credit ladder) | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/attendees` | Add an attendee to a reservation | Customer, FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/attendees/{id}` | Get an attendee | Customer, FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/attendees` | List attendees | Customer, FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/payments/{id}` | Get a payment | Customer, StudioManager, PlatformAdmin |
| GET | `/studio-ops/payments` | List payments | Customer, StudioManager, PlatformAdmin |
| POST | `/studio-ops/walk-ins` | Register a walk-in party (consumes seats immediately) | FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/walk-ins/{id}` | Get a walk-in | FrontDesk, StudioManager, PlatformAdmin |
| GET | `/studio-ops/walk-ins` | List walk-ins | FrontDesk, StudioManager, PlatformAdmin |
| POST | `/studio-ops/walk-ins/{id}/cancel` | Cancel a walk-in (releases seats) | FrontDesk, StudioManager, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ARTIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STUDIO_TIME_CONFLICT` | 409 Conflict |
| `ERR_WAIVER_OR_AGE_FAIL` | 422 Unprocessable Entity |
| `ERR_ATTENDEE_ROSTER_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_SEATS` | 409 Conflict |
| `ERR_STALE_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_EVENT_CONFIG` | 422 Unprocessable Entity |
| `ERR_GIFT_CARD_DEPLETED` | 422 Unprocessable Entity |
| `ERR_ARTIST_INACTIVE` | 422 Unprocessable Entity |
| `ERR_EVENT_NOT_STARTED` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_CREDIT_INSUFFICIENT` | 422 Unprocessable Entity |
