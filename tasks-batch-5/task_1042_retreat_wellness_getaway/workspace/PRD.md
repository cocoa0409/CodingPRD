# Retreat Wellness Getaway API — Product Requirements Document

## 1. Introduction

The Retreat Wellness Getaway API is the reservation and operations backbone for a boutique wellness-travel business. Operators publish a catalog of multi-day getaways — silent retreats, yoga intensives, detox weeks — each anchored to a venue, a check-in and departure window, a total guest capacity, and a per-person base price. Around that catalog sit the moving parts of a real retreat: lodging rooms of varying comfort tiers, facilitator-led activity sessions, airport shuttles, catalog add-ons, and the money trail of deposits, balances, and refunds.

Guests self-register, browse published retreats, reserve a room for a party of one or more, sign a health waiver, and settle their bill in two stages. The system must hold several invariants at once: seats and beds may never be oversold, a getaway automatically fills and re-opens as bookings come and go, facilitators cannot be double-booked, and every cancellation must return exactly the right refund according to how far out it lands. This document specifies the complete contract — resource shapes, lifecycle rules, calculations, validations, and the REST surface — that any conforming implementation must satisfy. Because timing drives refunds, deadlines, and check-in eligibility, the server maintains a controllable logical clock rather than reading the wall clock directly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Domain workflows in Section 3 assume everything here.

### 2.1. User and Role-Based Access Control

Every request other than guest self-registration must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request that is missing either header, or that names a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized caller who attempts an operation their role is not permitted to perform — or an ownership-scoped caller acting on a resource they do not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Anonymous`, `Guest`, `Operator`, and `Facilitator`.

- When `X-User-Role` is `Anonymous`, the caller is unauthenticated and may only self-register as a guest. This is the sole operation that does not require prior authentication; the identifier such a caller presents is not tied to any persisted entity.
- When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`. Ownership checks compare the `guest_id` of any booking (and, transitively, the payments, waivers, transport segments, and add-on attachments reached through that booking) against `X-User-ID`; a guest may only create and act upon resources that resolve to their own guest record.
- When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`; an operator has full reach across the catalog, schedule, rooms, facilitators, shuttles, add-ons, check-in, waiver review, and the test clock.
- When `X-User-Role` is `Facilitator`, `X-User-ID` is the `id` of the acting `Facilitator`; a facilitator may read their own facilitator profile (including payout) and read activity slots, but performs no write operations.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; when omitted it defaults to 10, and callers may request a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource is assigned an `id`, a server-minted UUID that carries no type prefix, and a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits — fixed at creation. Resources that can change after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and a `version` integer that begins at 1 and increments by one on each mutation.

Three resources are immutable ledger-style records and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: a `Payment` (a single money-movement record), an `AddOn` (a catalog entry), and a `BookingAddOn` (the junction that attaches an add-on to a booking). All other resources — retreats, rooms, guests, facilitators, bookings, waivers, activity slots, shuttles, and transport segments — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`. Whenever the server automatically recomputes a derived value on a resource (for example, refreshing a retreat's occupancy counters or its schedule-readiness flag), that recomputation is itself a mutation: it refreshes `updated_at` and increments `version`.

### 2.5. Reference Resolution and Nested Retrieval

Many requests carry references to other resources, either as path identifiers or as foreign keys inside the request body. The server validates every referenced identifier for existence before applying business rules, and it does so left to right in the order the identifiers appear — path identifiers first, then body references in declaration order. The first identifier that does not resolve determines the error. Each entity type has its own not-found error: a missing retreat yields `ERR_RETREAT_NOT_FOUND`, a missing room `ERR_ROOM_NOT_FOUND`, a missing guest `ERR_GUEST_NOT_FOUND`, a missing facilitator `ERR_FACILITATOR_NOT_FOUND`, a missing booking `ERR_BOOKING_NOT_FOUND`, a missing waiver `ERR_WAIVER_NOT_FOUND`, a missing shuttle `ERR_SHUTTLE_NOT_FOUND`, a missing add-on `ERR_ADDON_NOT_FOUND`, a missing activity slot `ERR_ACTIVITY_SLOT_NOT_FOUND`, a missing transport segment `ERR_TRANSPORT_SEGMENT_NOT_FOUND`, and a missing booking-addon link `ERR_BOOKING_ADDON_NOT_FOUND`. All of these carry HTTP 404. Reverse-reachability list endpoints (for example, listing the rooms or shuttles of a retreat, the payments or waiver of a booking, or the transport segments of a booking) resolve the parent identifier the same way before returning the child collection.

### 2.6. Monetary Precision and Rounding

All money is represented as an integer number of cents. Wherever a calculation multiplies a cent amount by a rate or percentage, the result is rounded to a whole cent using the round-half-up rule (a fractional cent of exactly one half rounds away from zero, upward). This applies to discounts, taxes, deposits, and refunds alike.

One rounding rule is order-sensitive and must be followed exactly: booking tax is computed by rounding the tax on each pre-discount line item individually and then summing those rounded per-line amounts. Rounding the summed base and then taxing it can differ by a cent, so the per-line-then-sum order is mandatory. Facilitator payouts are computed as exact integer products and require no rounding.

### 2.7. Optimistic Concurrency on Retreat Capacity

Creating a booking is guarded by optimistic concurrency control against the target retreat. A create-booking request must include `expected_retreat_version`, carrying the `version` of the retreat the client last observed. Because publishing a retreat, cancelling it, and every prior booking all advance the retreat's `version` and change how many seats remain, a client whose `expected_retreat_version` no longer equals the retreat's current `version` is working from a stale view of capacity. When the two values differ, the booking create is rejected with `ERR_STALE_RETREAT_VERSION` (HTTP 412), and the client must re-read the retreat and retry with the current version. This is the only endpoint that takes a version field in its body; no other operation requires one.

### 2.8. Occupancy and Seat Allocation Invariants

The system tracks live occupancy through three derived counters that must always reflect committed reservations. A retreat's `reserved_count` is the sum of `party_size` across every booking on that retreat whose status is `PENDING_DEPOSIT`, `DEPOSIT_PAID`, `CONFIRMED`, or `CHECKED_IN`. A lodging room's `reserved_beds` is the sum of `party_size` across bookings on that room in those same four statuses. A shuttle's `reserved_seats` is the sum of `seat_count` across its transport segments whose status is `BOOKED`. These counters rise when a reservation is committed and fall when it is released; the specific increments and decrements are described with the workflows in Section 3. No operation may drive a counter above the capacity it is measured against.

### 2.9. Validation Ordering and Error Precedence

When several checks could fail on the same request, they are evaluated in a fixed priority order so the returned error is deterministic. Authentication comes first: absent or unrecognized credentials yield `ERR_UNAUTHENTICATED` (401). Authorization is second: a permitted role acting outside its rights, or an owner acting on another's resource, yields `ERR_UNAUTHORIZED` (403). Third is existence of every referenced resource, yielding the appropriate 404 as described in §2.5. Fourth is body well-formedness — required fields present, enum values legal, integer amounts non-negative, and any end instant strictly after its start instant — with `ERR_VALIDATION` (400) on failure. Fifth is state eligibility: the target must be in a state from which the requested transition is allowed, including cross-entity state preconditions such as a retreat being `PUBLISHED` before a booking may be created or a facilitator being `ACTIVE` before a slot may be scheduled; violations yield `ERR_INVALID_STATE` (409). Sixth is the optimistic-concurrency check on booking creation, yielding `ERR_STALE_RETREAT_VERSION` (412). Seventh is waiver clearance, yielding `ERR_WAIVER_NOT_CLEARED` (422) where it applies. Eighth are temporal-window checks. Ninth are capacity and resource-kind checks. Tenth is payment-amount matching, yielding `ERR_PAYMENT_AMOUNT_MISMATCH` (422). Where a later category defines more than one concrete error, the specific error is chosen by the condition that fails, but the category's position in this ladder is what determines which family of check is reached first.

## 3. Business Logic & Workflows

### 3.1. The Retreat Catalog and Its Capacity Cycle

Because refunds, check-in eligibility, and completion all hinge on time, an operator drives the system's clock explicitly: an operator-only test capability advances or rewinds the logical current UTC to a supplied `to_iso8601` instant, and until it is set the clock rests at its startup default. All deadline and window math reads this logical clock.

An `Operator` seeds the catalog by creating a retreat, which begins life in `DRAFT`. Creation captures the marketing `name`, the catalog `theme` (such as a yoga, silent, or detox theme), the venue `location`, the check-in instant `start_date`, the departure instant `end_date`, the total `capacity` of guests the getaway can hold, and the per-person `base_price_cents`. The departure instant must be strictly later than the check-in instant, capacity must be at least 1, and the base price may not be negative. A freshly created retreat reports `status` of `DRAFT`, a `reserved_count` of 0, and a `schedule_ready` flag of false.

Before guests can book, the operator publishes the retreat, moving it from `DRAFT` to `PUBLISHED`. Publication is permitted only when the retreat holds at least one lodging room; an attempt to publish a retreat with no lodging room, or a retreat not currently in `DRAFT`, is rejected with `ERR_INVALID_STATE`. Publishing increments the retreat's `version`.

Once published, a retreat oscillates between `PUBLISHED` and `FULL` as demand ebbs and flows. When a booking pushes `reserved_count` up to exactly `capacity`, the server transitions the retreat from `PUBLISHED` to `FULL` at the end of that booking. Later, when a cancellation releases seats so that `reserved_count` falls back below `capacity`, the server transitions the retreat from `FULL` back to `PUBLISHED`. This cycle is automatic and repeats for the life of the retreat.

Two terminal outcomes close a retreat. An operator may cancel a `PUBLISHED` or `FULL` retreat, driving it to `CANCELLED`. Cancellation cascades: every booking on the retreat still in `PENDING_DEPOSIT`, `DEPOSIT_PAID`, `CONFIRMED`, or `CHECKED_IN` is cancelled with its `cancelled_by` set to `OPERATOR` (which forces a full refund, per §3.7), each such booking's `BOOKED` transport segments are cancelled and their shuttle seats released, and every `SCHEDULED` activity slot on the retreat is cancelled; the retreat's `version` is incremented. Alternatively, once the logical clock has reached or passed the retreat's `end_date`, an operator may complete a `PUBLISHED` or `FULL` retreat, driving it to `COMPLETED`; attempting completion before `end_date`, or on a retreat in the wrong state, is rejected with `ERR_INVALID_STATE`. Completion stamps each facilitator's final payout (§3.5), transitions every `SCHEDULED` activity slot to `COMPLETED`, transitions every `CHECKED_IN` booking to `COMPLETED`, and increments the retreat's `version`.

A retreat also exposes `schedule_ready`, a boolean that is true exactly when at least one activity slot on the retreat is in `SCHEDULED`. The server recomputes this flag whenever slots are scheduled, cancelled, or completed, as described in §3.5.

### 3.2. Rooms, Booking Creation, and the Charge Calculation

An operator furnishes a retreat with rooms. Each room names its parent retreat through `retreat_id`, a `kind` that is either `LODGING` or `COMMON`, a comfort `tier` of `PRIVATE`, `STANDARD`, or `SHARED_DORM` (defaulting to `STANDARD` and ignored for common rooms), a `tier_delta_cents` price adjustment (defaulting to 0), a `bed_count` capacity (defaulting to 0 and never negative), and a human `label`. Lodging rooms hold beds for guests; common rooms are activity venues and use a `bed_count` of 0. Each room reports `reserved_beds`, starting at 0.

A `Guest` creates a booking against a retreat. The request identifies the retreat through `retreat_id`, the owning guest through `guest_id` (which must equal the caller's `X-User-ID`), and the chosen room through `room_id`, and states the `party_size` — the number of guests traveling together, at least 1 — which consumes that many beds and that many retreat seats. The booking may also carry `has_special_diet` (see §3.3) and a list of `addon_ids` naming catalog add-ons to attach at creation, and it must carry `expected_retreat_version` for the concurrency check of §2.7. Several preconditions gate the create: the retreat must be `PUBLISHED` (otherwise `ERR_INVALID_STATE`); the chosen room must be of kind `LODGING` (otherwise `ERR_ROOM_KIND_MISMATCH`, HTTP 422); the room's `reserved_beds` plus the new `party_size` must not exceed the room's `bed_count` (otherwise `ERR_ROOM_FULL`, HTTP 409); and the retreat's `reserved_count` plus the new `party_size` must not exceed the retreat's `capacity` (otherwise `ERR_RETREAT_FULL`, HTTP 409). A successful create places the booking in `PENDING_DEPOSIT`, adds `party_size` to both the room's `reserved_beds` and the retreat's `reserved_count`, and — if that brings `reserved_count` to exactly `capacity` — flips the retreat to `FULL`. The create also increments the retreat's `version`.

At creation the server computes and stamps the full charge breakdown on the booking. The `subtotal_cents` is the per-person base price multiplied by the party size, plus the chosen room's `tier_delta_cents`, plus the sum of the snapshotted prices of every attached add-on. From the party size the server selects a tiered group discount, recorded as `group_discount_pct`: parties of four or more receive a fifteen percent discount, parties of two or three receive an eight percent discount, and a solo party receives no discount. The `discount_cents` is the subtotal multiplied by that discount rate, rounded half up to a whole cent. The special-diet surcharge is covered in §3.3. The pre-tax `total_cents` is the subtotal minus the discount plus the special-diet surcharge.

Tax and the payment split follow. The server forms the pre-discount line items — the base line (per-person base price times party size), the room's `tier_delta_cents`, and each attached add-on's snapshotted price — taxes each line at eight and one-half percent, rounds each line's tax half up to a whole cent, and sums those rounded amounts to produce `tax_cents`. The `grand_total_cents` is the pre-tax total plus that tax; this is the amount the guest ultimately owes. The `deposit_cents` is thirty percent of the grand total, rounded half up, and the `balance_due_cents` is the grand total minus the deposit. The booking also tracks `amount_paid_cents` (the running sum of deposit and balance payments, which refunds never reduce), `refund_cents` (any refund issued on cancellation), and `cancelled_by` (who cancelled, or unset while active).

### 3.3. Dietary Surcharge, Deposits, and Balance Settlement

When a guest flags `has_special_diet` as true on a booking, the server adds a one-time special-diet surcharge of 5000 cents to the charge, recorded as `special_diet_surcharge_cents`; when the flag is false the surcharge field is 0. The surcharge is added exactly once regardless of party size and feeds the pre-tax total described in §3.2. Guest profiles themselves also carry free-text `dietary_notes` and `health_notes` captured at registration (§3.4), which document requirements without changing the charge.

Payment proceeds in two stages, each a state transition on the booking. First the guest pays the deposit, moving the booking from `PENDING_DEPOSIT` to `DEPOSIT_PAID`. The deposit payment carries an `amount_cents` that must equal the booking's `deposit_cents` exactly; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful deposit records a `Payment` of type `DEPOSIT` for the deposit amount and adds that amount to `amount_paid_cents`. Second, the guest pays the balance, moving the booking from `DEPOSIT_PAID` to `CONFIRMED`. Paying the balance requires that a waiver for the booking exists and has reached `CLEARED` status (otherwise `ERR_WAIVER_NOT_CLEARED`, HTTP 422), and the balance payment's `amount_cents` must equal the booking's `balance_due_cents` exactly (otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`). A successful balance payment records a `Payment` of type `BALANCE` for the balance amount and adds it to `amount_paid_cents`.

Each `Payment` record captures the `booking_id` it belongs to, its `type` (`DEPOSIT` and `BALANCE` are inbound, `REFUND` is outbound), the positive `amount_cents` of the money movement, and an optional human `note`. The payments of a booking are retrievable as a list.

After the balance is settled, an `Operator` checks the guest in, moving the booking from `CONFIRMED` to `CHECKED_IN`. Check-in is doubly gated: the booking's waiver must be `CLEARED` (otherwise `ERR_WAIVER_NOT_CLEARED`), and the logical clock must have reached or passed the retreat's `start_date` — an earlier attempt is rejected with `ERR_CHECKIN_TOO_EARLY` (HTTP 409). Check-in refreshes the booking's `updated_at`. A `CHECKED_IN` booking is later carried to `COMPLETED` when the operator completes the retreat (§3.1).

### 3.4. Guests, Waivers, and Safety Clearance

A prospective guest self-registers without authentication, supplying a unique `email` and a `full_name`, and optionally a `phone`, `dietary_notes`, and `health_notes` (each defaulting to an empty string). The resulting guest profile is the identity a booking's `guest_id` must reference.

Every booking must clear a health waiver before its guest can settle the balance or check in. A guest creates a waiver for a booking by supplying the `booking_id` and the `health_disclosures` text; the waiver starts in `PENDING`. Only one waiver may exist per booking — a second attempt is rejected with `ERR_WAIVER_ALREADY_EXISTS` (HTTP 409). The guest then signs the waiver, supplying a `signature_name` which the server stamps onto the record as it moves the waiver from `PENDING` to `SIGNED`; the sign increments the waiver's `version`. An `Operator` then reviews the signed waiver, supplying a `decision` of either `CLEAR` or `REJECT`, which the server records in `review_decision` as it moves the waiver from `SIGNED` to either `CLEARED` or `REJECTED`; the review increments the waiver's `version`. A waiver's overall `status` therefore walks `PENDING` to `SIGNED` and then to either `CLEARED` or `REJECTED`, with the latter two being terminal. Only a `CLEARED` waiver satisfies the balance-payment and check-in gates. The waiver of a booking (zero or one) is retrievable as a list.

### 3.5. Facilitators, Activity Scheduling, and Payouts

An operator registers a facilitator with a `full_name`, an `email`, and a practice `specialty`. A facilitator starts in `ACTIVE` and reports a `payout_cents` of 0 until a retreat completes.

Operators build the activity schedule by creating slots. A slot names its `retreat_id`, the leading `facilitator_id`, the hosting `room_id`, a session `title`, and a half-open time interval defined by `start_datetime` and `end_datetime`, where the end must be strictly after the start. Scheduling enforces four conditions. The facilitator must be `ACTIVE` (a withdrawn facilitator cannot be scheduled; violation is `ERR_INVALID_STATE`). The room must be of kind `COMMON` (otherwise `ERR_ROOM_KIND_MISMATCH`, HTTP 422). The new interval must not overlap any other `SCHEDULED` slot led by the same facilitator; because intervals are half-open, a slot that begins exactly when another ends is allowed, but any true overlap is rejected with `ERR_FACILITATOR_DOUBLE_BOOKED` (HTTP 409). And within the same room, the new slot must not fall within thirty minutes of another `SCHEDULED` slot — a setup buffer applied on both sides of each existing slot — with a violation rejected as `ERR_SPACE_UNAVAILABLE` (HTTP 409). A successful create places the slot in `SCHEDULED` and sets the retreat's `schedule_ready` to true. An operator may cancel a `SCHEDULED` slot, moving it to `CANCELLED`, after which the server recomputes the retreat's `schedule_ready`. When a retreat completes, its `SCHEDULED` slots move to `COMPLETED`, and `schedule_ready` is recomputed accordingly.

Withdrawing a facilitator moves them from `ACTIVE` to `WITHDRAWN` and cascades: every `SCHEDULED` slot led by that facilitator is cancelled, the `schedule_ready` flag of each affected retreat is recomputed, and the facilitator's `version` is incremented.

Facilitator pay is computed two ways for two different moments. The provisional figure, available while scheduling is underway, pays a flat 40000 cents for each session the facilitator leads: the count of that facilitator's slots on the retreat whose status is `SCHEDULED` or `COMPLETED`, multiplied by 40000 cents, ignoring how many guests actually attend. The final figure, stamped into `payout_cents` when the retreat transitions to `COMPLETED`, instead pays 3000 cents per confirmed attendee: the sum of `party_size` across the retreat's bookings whose status is `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`, multiplied by 3000 cents, ignoring the slot count. Only the final per-attendee figure is persisted on the facilitator at completion; both figures are exact integer amounts.

### 3.6. Airport Transport

An operator provisions airport shuttles for a retreat. A shuttle names its `retreat_id`, a `direction` of either `ARRIVAL` (airport to venue) or `DEPARTURE` (venue to airport), a `depart_datetime`, and a `seat_capacity` of at least one seat. It reports `reserved_seats`, starting at 0. The shuttles of a retreat are retrievable as a list.

A guest reserves shuttle seats for a booking's party by creating a transport segment that names the `booking_id` and the `shuttle_id`. The booking must be in `DEPOSIT_PAID`, `CONFIRMED`, or `CHECKED_IN` (otherwise `ERR_INVALID_STATE`), and the shuttle's `reserved_seats` plus the booking's `party_size` must not exceed the shuttle's `seat_capacity` (otherwise `ERR_SHUTTLE_FULL`, HTTP 409). On creation the segment copies the booking's `party_size` into its own `seat_count`, adds that seat count to the shuttle's `reserved_seats`, and enters `BOOKED`. When the owning booking is cancelled, each of its `BOOKED` segments is cancelled and its `seat_count` is subtracted back from the shuttle's `reserved_seats`. When the retreat completes, `BOOKED` segments move to `COMPLETED`.

### 3.7. Cancellation and Tiered Refunds

A guest may cancel their own booking from `PENDING_DEPOSIT`, `DEPOSIT_PAID`, or `CONFIRMED`, and the same cancellation logic runs when a retreat cancellation cascades over its bookings (§3.1). Cancelling always releases capacity and transport: the booking's `party_size` is subtracted from the room's `reserved_beds` and from the retreat's `reserved_count`, and if the retreat was `FULL` and now sits below `capacity`, it returns to `PUBLISHED`; every `BOOKED` transport segment of the booking is cancelled, freeing its seats on the shuttle.

The refund is set by `cancelled_by`, which distinguishes the two ways a booking reaches `CANCELLED`. When the guest cancels their own booking, `cancelled_by` is `GUEST` and the refund percentage is chosen from a lead-time ladder. The lead time is the number of whole days between the current logical time and the retreat's `start_date`, taken as the floor of the gap divided into 86400-second days. A guest cancelling sixty or more days ahead receives a full refund; thirty or more but fewer than sixty days ahead receives half; fourteen or more but fewer than thirty days ahead receives a quarter; and fewer than fourteen days ahead receives nothing. When instead the cancellation is driven by an operator cancelling the whole retreat, `cancelled_by` is `OPERATOR` and the refund is forced to the full amount regardless of lead time. In both cases the refund amount is the booking's `amount_paid_cents` multiplied by the selected percentage, rounded half up to a whole cent, and stored in `refund_cents`. If that refund is greater than zero, the server records a `Payment` of type `REFUND` for the refund amount. Note that refunds never reduce `amount_paid_cents`, which continues to reflect the gross deposit and balance actually paid.

### 3.8. Catalog Add-Ons

Operators maintain a catalog of add-ons — spa treatments, excursions, meals, and gear. Each add-on carries a `name`, a `category` of `SPA`, `EXCURSION`, `MEAL`, or `GEAR`, and a `price_cents` that may not be negative.

A guest attaches an add-on to their booking by supplying the `booking_id` and the `addon_id`; the booking must still be in `PENDING_DEPOSIT` (otherwise `ERR_INVALID_STATE`). At attach time the server snapshots the add-on's current `price_cents` into the link's `price_cents_snapshot`, so later edits to the catalog price never disturb an existing booking. Because the snapshotted price feeds the subtotal, tax, deposit, and balance, attaching an add-on triggers a full recomputation of the booking's charge breakdown exactly as at booking creation. Add-ons named through the `addon_ids` list at booking creation are attached and snapshotted the same way. The add-on links of a booking are retrievable as a list.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return HTTP 201 Created. Operations that modify an existing resource — including state transitions, payments, and the test-clock control — return HTTP 200 OK. All list and fetch operations return HTTP 200 OK.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the logical current UTC (test clock; startup default 2026-07-01T00:00:00Z) | Operator |
| POST | `/v1/retreats` | Create a retreat in DRAFT | Operator |
| GET | `/v1/retreats/{id}` | Fetch one retreat | Operator, Guest |
| GET | `/v1/retreats` | List retreats | Operator, Guest |
| POST | `/v1/retreats/{id}/publish` | Publish a DRAFT retreat | Operator |
| POST | `/v1/retreats/{id}/cancel` | Cancel a retreat (cascades bookings, transport, slots) | Operator |
| POST | `/v1/retreats/{id}/complete` | Complete a retreat past end_date (stamps payouts) | Operator |
| GET | `/v1/retreats/{id}/rooms` | List a retreat's rooms | Operator, Guest |
| GET | `/v1/retreats/{id}/shuttles` | List a retreat's shuttles | Operator, Guest |
| POST | `/v1/rooms` | Create a room under a retreat | Operator |
| POST | `/v1/guests` | Self-register a guest | Anonymous |
| GET | `/v1/guests/{id}` | Fetch a guest profile | Guest, Operator |
| POST | `/v1/facilitators` | Create a facilitator | Operator |
| GET | `/v1/facilitators/{id}` | Fetch a facilitator (with payout) | Operator, Facilitator |
| POST | `/v1/facilitators/{id}/withdraw` | Withdraw a facilitator (cascades slot cancellations) | Operator |
| POST | `/v1/bookings` | Create a booking against a PUBLISHED retreat (OCC on retreat version) | Guest |
| GET | `/v1/bookings/{id}` | Fetch one booking with computed charges | Guest, Operator |
| GET | `/v1/bookings` | List bookings by retreat, guest, or room | Guest, Operator |
| POST | `/v1/bookings/{id}/pay-deposit` | Pay the deposit | Guest |
| POST | `/v1/bookings/{id}/pay-balance` | Pay the balance (requires cleared waiver) | Guest |
| POST | `/v1/bookings/{id}/cancel` | Guest cancels own booking (tiered refund) | Guest |
| POST | `/v1/bookings/{id}/check-in` | Check in a confirmed booking on/after start_date | Operator |
| GET | `/v1/bookings/{id}/payments` | List a booking's payment/refund events | Guest, Operator |
| GET | `/v1/bookings/{id}/waiver` | List a booking's waiver (0 or 1) | Guest, Operator |
| POST | `/v1/waivers` | Create a PENDING waiver for a booking | Guest |
| POST | `/v1/waivers/{id}/sign` | Sign a waiver (PENDING to SIGNED) | Guest |
| POST | `/v1/waivers/{id}/review` | Review a waiver (SIGNED to CLEARED or REJECTED) | Operator |
| POST | `/v1/activity-slots` | Schedule a facilitator-led slot in a COMMON room | Operator |
| GET | `/v1/activity-slots/{id}` | Fetch one activity slot | Operator, Guest, Facilitator |
| GET | `/v1/activity-slots` | List activity slots by retreat, facilitator, or room | Operator, Guest, Facilitator |
| POST | `/v1/activity-slots/{id}/cancel` | Cancel a scheduled slot | Operator |
| POST | `/v1/shuttles` | Create an airport shuttle | Operator |
| POST | `/v1/transport-segments` | Reserve shuttle seats for a booking | Guest |
| GET | `/v1/transport-segments/{id}` | Fetch one transport segment | Guest, Operator |
| GET | `/v1/transport-segments` | List transport segments by booking or shuttle | Guest, Operator |
| POST | `/v1/addons` | Create a catalog add-on | Operator |
| GET | `/v1/addons/{id}` | Fetch one add-on | Operator, Guest |
| POST | `/v1/booking-addons` | Attach an add-on to a PENDING_DEPOSIT booking | Guest |
| GET | `/v1/booking-addons/{id}` | Fetch one booking-addon link | Guest, Operator |
| GET | `/v1/booking-addons` | List booking-addon links by booking or addon | Guest, Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_RETREAT_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_GUEST_NOT_FOUND` | 404 |
| `ERR_FACILITATOR_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_WAIVER_NOT_FOUND` | 404 |
| `ERR_SHUTTLE_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_ACTIVITY_SLOT_NOT_FOUND` | 404 |
| `ERR_TRANSPORT_SEGMENT_NOT_FOUND` | 404 |
| `ERR_BOOKING_ADDON_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_RETREAT_VERSION` | 412 |
| `ERR_WAIVER_NOT_CLEARED` | 422 |
| `ERR_CHECKIN_TOO_EARLY` | 409 |
| `ERR_FACILITATOR_DOUBLE_BOOKED` | 409 |
| `ERR_SPACE_UNAVAILABLE` | 409 |
| `ERR_ROOM_FULL` | 409 |
| `ERR_RETREAT_FULL` | 409 |
| `ERR_SHUTTLE_FULL` | 409 |
| `ERR_ROOM_KIND_MISMATCH` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_WAIVER_ALREADY_EXISTS` | 409 |
