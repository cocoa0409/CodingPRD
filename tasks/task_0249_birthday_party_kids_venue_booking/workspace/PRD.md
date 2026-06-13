# Kids Venue Booking API — Product Requirements Document

## 1. Introduction

Children's party venues juggle a deceptively intricate scheduling problem: a single afternoon may host several parties in different rooms, each with its own theme package, cast of entertainers, cake order, and a roster of guardians who keep changing their head counts up to the last minute. This API exists to make that orchestration safe and predictable. It governs the full life of a booking — from the moment a guardian or coordinator requests a quote, through holding a room slot, collecting deposits and signed liability waivers, assigning hosts and entertainers, weathering an outdoor cancellation, all the way to settling the final bill once the party is over.

The system treats time as a first-class resource. Rooms have hard capacity caps and turnover buffers that must be respected so cleaning crews are never rushed; outdoor rooms at weather-dependent venues can be placed on hold and rescheduled when storms threaten; and staff members cannot be in two places at once. Layered on top of this temporal model is a financial ledger that distinguishes the *estimate* a customer sees when quoting from the *settlement* figure computed once the event has actually run, and that handles deposits, balances, and tiered cancellation refunds. The remainder of this document specifies the global contracts every endpoint honors (Section 2) and the domain workflows where the real business logic lives (Section 3), followed by the endpoint and error reference tables (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `VenueManager`, `Coordinator`, `Guardian`, and `FinanceClerk`. A request that omits either header, or whose `X-User-Role` is not one of these four known roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The four roles divide responsibility cleanly. A `VenueManager` owns configuration — venues, rooms, party packages, and staff members — and the configuration-lifecycle actions that close a room, retire a package, or deactivate a staff member. A `Coordinator` drives the booking lifecycle (holding, releasing, confirming, weather-holding, rescheduling, completing), manages staffing, add-ons, roster events, and waivers, and may take payments on a guardian's behalf. A `Guardian` is the customer acting on their own booking. A `FinanceClerk` handles money: recording payments and voiding charges. All four roles may call every read (GET) endpoint.

The identity semantics differ by role. When `X-User-Role` is `Guardian`, the identity is entity-backed against the `Booking` aggregate: `X-User-ID` is the identifier of the acting guardian and is stored as `guardian_user_id` on any booking that guardian creates. For every booking-scoped write a `Guardian` attempts, the server compares the booking's `guardian_user_id` to `X-User-ID`; a guardian may act only on their own bookings, and a mismatch is treated as a permission failure (`ERR_INSUFFICIENT_PERMISSIONS`). When `X-User-Role` is `VenueManager`, `Coordinator`, or `FinanceClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts and may log it but does not compare it against any entity's `id`. Note that guardians have no weather-hold or reschedule capability — those operations belong to the `Coordinator` alone.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint says otherwise, all list endpoints sort their results by the resource's creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a uniform set of server-managed fields. The `id` is a server-minted UUID with no type prefix, used purely for identity. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp, similarly formatted, refreshed on every mutation of the resource. The `version` field is an integer that starts at its initial value and increments by one on every mutation; it underpins the optimistic-concurrency mechanism described in Section 2.6.

Two entities are deliberately lighter. A `GuestParty` roster event and the `SystemClock` singleton carry only `id` and `created_at` — they have neither `updated_at` nor `version`, because a roster event is an immutable historical record once written and the clock is a test-driving fixture. Every other entity — `Venue`, `Room`, `PartyPackage`, `StaffMember`, `Booking`, `AddOn`, `Waiver`, `StaffAssignment`, and `Payment` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When a write mutates a derived field on a booking — for instance recomputing `quote_total_cents`, `balance_due_cents`, or `payment_status` — that counts as a mutation of the booking: its `updated_at` is refreshed and its `version` increments. Each booking lifecycle transition described in Section 3 likewise increments `Booking.version` by one.

### 2.5. Hierarchical Consistency and Cascades

The booking is the hub of a small tree: add-ons, waivers, staff assignments, payments, and roster events all hang off a parent booking, while rooms, packages, venues, and staff members are flat configuration peers the booking references. Several operations on the parent ripple into the children, and these cascades are part of the contract, not incidental behavior.

When a booking is cancelled, the system resolves every dependent record in one pass: all `ACTIVE` add-ons move to `REMOVED`, all `ASSIGNED` staff assignments move to `RELEASED`, and all waivers still in `DRAFT` or `SIGNED` move to `VOIDED`. When a booking is completed, every `ASSIGNED` staff assignment is moved to `RELEASED` so the staff windows free up. Conversely, child-side changes recompute parent-side derived fields: signing or revoking a waiver adjusts the parent's `waivers_signed`; adding or removing an add-on re-prices the parent; recording a roster event shifts the parent's head count. Each such reconciliation is a mutation of the booking, refreshing `updated_at` and incrementing `version`.

### 2.6. Optimistic Concurrency on Reschedule

Rescheduling a weather-held booking is guarded by optimistic concurrency control. A reschedule request must carry `expected_booking_version`, the booking `version` the client last observed. The server compares it against the booking's current `version`; if another writer has advanced the version since the client read it — for example a second coordinator who already moved the event to a new window and bumped the version — the client's view is stale and the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412), so the request cannot silently overwrite a slot it never observed. This is the only endpoint that accepts a version field; no other write takes one, and every other mutation proceeds without a version check.

### 2.7. Nested Resource Retrieval and Existence Ordering

Many paths address a child within a booking, such as a waiver, add-on, staff assignment, or payment under a booking. The system validates the identifiers in these paths strictly left to right. The booking identifier (`bookingId`) is checked first; only if the booking exists does the server then look up the child identifier (`waiverId`, `addOnId`, `assignmentId`, or `paymentId`). The first identifier that fails to resolve determines the error: a missing booking yields `ERR_BOOKING_NOT_FOUND` before the child is ever consulted, and a present booking with a missing child yields the child-specific not-found error (`ERR_WAIVER_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, or `ERR_PAYMENT_NOT_FOUND`). Configuration lookups behave the same way — a missing venue, room, package, or staff member surfaces `ERR_VENUE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, or `ERR_STAFF_NOT_FOUND` respectively, whether the identifier arrived in the path or as a body foreign key. Each child record records the booking it belongs to through a `booking_id` reference, which is what lets a booking's add-ons, roster events, waivers, staff assignments, and payments be listed back under that booking.

### 2.8. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so the returned error is deterministic. The order is: (1) authentication of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role authorization (`ERR_INSUFFICIENT_PERMISSIONS`); (3) existence of path-referenced resources, left to right; (4) referential resolution of body foreign keys such as `room_id`, `package_id`, and `staff_member_id`, including the venue-agreement check on booking creation; (5) field-level request shape and bounds (`ERR_INVALID_REQUEST`); (6) the target entity being in a state that admits the requested transition; (7) cross-entity configuration preconditions such as a room being open, a package listed, and a staff member available with the matching skill; (8) waiver completeness for confirmation; (9) staffing completeness for confirmation; (10) room and staff window overlap checks; (11) room capacity; (12) reschedule and weather timing; (13) fiscal gates for deposit, balance, and refund magnitude; and finally (14) the optimistic-concurrency version check on reschedule. Earlier checks mask later ones: a request that fails authentication never reaches a state check, and a request to confirm a booking whose room state is irrelevant will still surface a missing-host failure only after the booking's own state has been found acceptable. Within step 13 the relevant error is `ERR_DEPOSIT_NOT_MET`, `ERR_BALANCE_OUTSTANDING`, or `ERR_REFUND_EXCEEDS_PAID`, each returned with HTTP 402.

### 2.9. Monetary Precision and Time

All monetary amounts are integer cents; there are no fractional cents and no rounding is needed where every input is already an integer. Where a fraction enters — most notably when computing a deposit as a percentage of a quote — the result is taken to the next whole cent by rounding upward (ceiling), never truncated downward. Times are ISO 8601 UTC. The room and staff overlap geometry described in Section 3 is computed at second resolution.

### 2.10. The Logical Clock

Time-sensitive rules — whether an event has started, whether it has ended, and how many hours remain before it begins — are evaluated against the server's logical clock rather than wall-clock time. The clock is a singleton `SystemClock` whose `current_utc` field holds the server's notion of "now." An administrative capability lets an operator set `current_utc` to a supplied instant — passed as `to_iso8601` — for test-driving, and another reads the current clock value. Reschedule-lead checks, weather-hold eligibility timing, and completion timing all read `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Configuring Venues, Rooms, Packages, and Staff

Before any party can be booked, a `VenueManager` lays down the configuration layer. A **Venue** is created with a `name` and optionally a `timezone` (an IANA zone used to interpret event-local times, defaulting to `UTC`), a `weather_dependent` flag (defaulting to false, marking whether outdoor bookings here may be weather-held), and a `reschedule_lead_hours` value (defaulting to 48, the lead time a guardian self-reschedule would require). A venue begins life — and remains — in `ACTIVE`; there is no suspension in this version.

A **Room** belongs to a venue via `venue_id` and is described by a `name`, a `room_kind` of either `INDOOR` or `OUTDOOR` (defaulting to `INDOOR`; only `OUTDOOR` rooms are weather-eligible), a `max_capacity` that hard-caps committed head count and must be at least 1, and a `buffer_minutes` turnover window applied after each booking's event window on that room (defaulting to 30). A room starts `OPEN` and a manager may later close it, moving it to `CLOSED`; a closed room rejects new holds with `ERR_ROOM_CLOSED`.

A **PartyPackage** is offered by a venue (`venue_id`) under a `theme` label, priced with a `base_price_cents` (at least 0) that covers a count of `included_children` (at least 1) for a `base_duration_minutes` window (defaulting to 120), with each child beyond the included count costing `per_extra_child_cents` (at least 0). The package also fixes a `deposit_pct`, the fraction of the quote required as a deposit, which defaults to 0.25 and must be greater than 0 and at most 1. A package starts `LISTED`; a manager may retire it to `RETIRED`, after which it rejects new quotes with `ERR_PACKAGE_RETIRED`.

A **StaffMember** belongs to a venue (`venue_id`), has a `full_name`, and carries a `skills` array of capability tags drawn from `HOST`, `ENTERTAINER`, and `COOK` (empty by default). A staff member starts `AVAILABLE`; a manager may deactivate them to `INACTIVE`, and an inactive staff member cannot be assigned (`ERR_STAFF_INACTIVE`). All configuration list endpoints accept an optional `status` filter, and rooms, packages, and staff lists additionally accept a `venue_id` filter so callers can scope to one venue.

### 3.2. Opening a Booking and Quoting It

A booking is opened by a `Coordinator` or a `Guardian`, who supplies a `room_id`, a `package_id`, an `event_start_utc`, a `children_count` (at least 1), and optionally an `adults_count` (defaulting to 0). The server resolves both foreign keys; the room and the package must belong to the same venue, and if `room.venue_id` does not equal `package.venue_id` the create is rejected with `ERR_VENUE_MISMATCH` (HTTP 422). The booking's `venue_id` is then resolved from that agreement. The new booking lands in `QUOTE_DRAFT`. At creation the server sets `effective_duration_minutes` to the package's `base_duration_minutes`, computes `event_end_utc` from the start plus that duration, sets `waivers_required` equal to `children_count`, initializes `payment_status` to `UNPAID`, sets `reschedule_count` to 0, and derives `weather_eligible`. A booking is weather-eligible exactly when its room's `room_kind` is `OUTDOOR` and its venue's `weather_dependent` flag is true. The `headcount_committed` field is reconciled as the sum of `children_count` and `adults_count`.

The **quote estimate** is computed immediately and stored as `quote_total_cents`. It prices the booking forward from its currently active line items. First the system finds how many children exceed the package's included allotment — the overage is the children count minus `included_children`, but never below zero. The package charge is `base_price_cents` plus that overage multiplied by `per_extra_child_cents`. To this is added the add-on charge: the sum, over every add-on still in `ACTIVE` status, of its `unit_price_cents` multiplied by its `quantity`. The quote total is the package charge plus the add-on charge; every input is integer cents so no rounding occurs. This estimate variant is recomputed on every line-item or head-count mutation while the booking is in `QUOTE_DRAFT`, `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`, always against the live `children_count` and the currently active add-ons.

Whenever the quote is recomputed the booking's `balance_due_cents` is reconciled as well: it is the applicable total minus `amount_paid_cents`, where the applicable total is `final_total_cents` once the booking is `COMPLETED` and `quote_total_cents` otherwise.

A coordinator or guardian may revise head count on a `QUOTE_DRAFT` or `HELD` booking, supplying a new `children_count` and/or `adults_count`. The revision re-derives `headcount_committed` and `waivers_required`, re-prices `quote_total_cents`, re-derives `deposit_due_cents` and `balance_due_cents`, and re-checks capacity: the sum of children and adults may not exceed the room's `max_capacity`, or the request is rejected with `ERR_ROOM_CAPACITY_EXCEEDED`.

### 3.3. Add-Ons: Cake, Characters, and Extra Time

Add-ons enrich a booking and are added only while the booking is in `QUOTE_DRAFT` or `HELD`; attempting to add or remove an add-on in any other state is rejected with `ERR_ADDON_LOCKED`, because add-ons are immutable once the booking is `CONFIRMED`. Each **AddOn** carries a `kind` of `CAKE`, `CHARACTER`, or `EXTRA_TIME`, a `unit_price_cents` (at least 0), a `quantity` (defaulting to 1, at least 1), and for extra-time add-ons an `extra_minutes` value (defaulting to 0) giving the minutes added per unit. From the kind the server derives `requires_skill`: a `CHARACTER` add-on requires `ENTERTAINER`, a `CAKE` add-on requires `COOK`, and an `EXTRA_TIME` add-on requires no skill, recorded as `NONE`. An add-on starts `ACTIVE` and may be removed to `REMOVED`, at which point it drops out of both pricing and duration.

Adding or removing an add-on re-prices the booking — recomputing `quote_total_cents`, then `deposit_due_cents`, then `balance_due_cents`. Extra-time add-ons additionally affect the schedule. The booking's `effective_duration_minutes` is the package's `base_duration_minutes` plus, summed over every active extra-time add-on, that add-on's `extra_minutes` multiplied by its `quantity`. Whenever an extra-time add-on is added or removed, the server recomputes `effective_duration_minutes` and `event_end_utc` and then re-checks the room window for overlap. When an extra-time add-on is removed, the event window can only shrink, and if the shrunken window still fits the room schedule the removal is accepted.

### 3.4. Guest Roster and Head-Count History

Head-count changes during planning are recorded as **GuestParty** roster events, each a small immutable record carrying a signed `children_delta` (defaulting to 0), a signed `adults_delta` (defaulting to 0), and a free-text `reason` (defaulting to `ADJUSTMENT`). A coordinator or guardian records one; the server applies the deltas to the booking's `children_count` and `adults_count`, then reconciles `headcount_committed`, `waivers_required`, `quote_total_cents`, `deposit_due_cents`, and `balance_due_cents`, and re-checks that the new committed head count does not exceed the room's `max_capacity` (`ERR_ROOM_CAPACITY_EXCEEDED`). These roster events are the historical spine the settlement calculation later replays, and because they have no `version` they are never mutated after creation.

### 3.5. Waivers

One signed liability waiver is required per child before a booking may be confirmed: `waivers_required` always equals `children_count`. A **Waiver** is created in `DRAFT` for a named child (`child_name`), optionally capturing a `guardian_signature` at creation. A guardian (or a coordinator acting for them) signs a draft waiver by supplying a non-empty `guardian_signature`; signing moves the waiver from `DRAFT` to `SIGNED` and increments the parent booking's `waivers_signed`. Signing is permitted only while the parent booking is in `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`; attempting to sign against a booking in any other state is rejected with `ERR_BOOKING_NOT_SIGNABLE`, and an empty signature is rejected with `ERR_INVALID_REQUEST`.

A signed waiver may be revoked back to `DRAFT`, which decrements the parent's `waivers_signed`. Revocation is blocked once the booking is `CONFIRMED`: a confirmed booking's signed waivers are locked, and an attempted revoke is rejected with `ERR_WAIVER_LOCKED`. When a booking is cancelled, every waiver still in `DRAFT` or `SIGNED` is voided to `VOIDED` by the system and the parent's `waivers_signed` is recomputed accordingly. The `waivers_signed` field always reflects the count of waivers in `SIGNED` status on the booking.

### 3.6. Staffing and Window Conflicts

A `Coordinator` assigns a **StaffMember** to a booking by supplying a `staff_member_id` and a `role_on_event` of `HOST`, `ENTERTAINER`, or `COOK`. The staff member must be `AVAILABLE` — an inactive one is rejected with `ERR_STAFF_INACTIVE` — and the requested `role_on_event` must appear in that member's `skills`, or the assignment is rejected with `ERR_SKILL_MISMATCH`. A new assignment starts `ASSIGNED`.

Staff cannot be double-booked, and staff windows are stricter than room windows. A staff member's occupancy for a booking is the closed interval from `event_start_utc` to `event_end_utc` plus the room's buffer, where `event_end_utc` is `event_start_utc` plus `effective_duration_minutes`. Because the interval is closed and inclusive of the buffer, two bookings whose windows merely touch end-to-end — where one window's end-plus-buffer equals the next window's start — do conflict for staff, since a person cannot teleport between back-to-back parties. Two staff occupancies conflict when the first starts at or before the second's buffered end and the second starts at or before the first's buffered end. The candidate set for this check is every other `ASSIGNED` assignment for the same staff member across any room whose parent booking is in `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`. A conflict is rejected with `ERR_STAFF_WINDOW_CONFLICT`.

An assignment may be released back to `RELEASED`, which frees that staff member's window for the booking's interval. Releasing is constrained for confirmed bookings: if the booking is `CONFIRMED` and the assignment is the sole `HOST`, the release is rejected with `ERR_HOST_REQUIRED`, because a confirmed booking must always retain exactly one host. Releasing is permitted when the booking is not `CONFIRMED`, or when the assignment being released is not the only host. The system also releases assignments automatically: when a booking is completed or cancelled, all its `ASSIGNED` assignments move to `RELEASED`.

### 3.7. Holding the Slot

Moving a booking from `QUOTE_DRAFT` to `HELD` reserves the room window so subsequent overlap checks can see it. The `Coordinator` initiating the hold must clear several preconditions. The room must be `OPEN`, or the hold is rejected with `ERR_ROOM_CLOSED`. The package must be `LISTED`, or the hold is rejected with `ERR_PACKAGE_RETIRED`. The committed head count — children plus adults — must not exceed the room's `max_capacity`, or the hold is rejected with `ERR_ROOM_CAPACITY_EXCEEDED`. Finally, the requested window must not collide with another active booking on the same room.

Room window geometry uses half-open intervals. A booking occupies, on its room, the half-open interval beginning at `event_start_utc` and ending at `event_end_utc` plus the room's `buffer_minutes` — that is, the event window followed by the cleanup buffer, with the buffered end itself excluded. Two such occupancies conflict when the first starts strictly before the second's buffered end and the second starts strictly before the first's buffered end. Because the intervals are half-open, exact adjacency — one booking's buffered end equal to the next's start — is not a conflict, so a room can host back-to-back parties as long as the cleanup buffer fits between them. The candidate set is every other booking on the same room whose status is `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`; bookings in `QUOTE_DRAFT`, `COMPLETED`, or `CANCELLED` are excluded. A conflict is rejected with `ERR_ROOM_WINDOW_CONFLICT`. On a successful hold the server recomputes `quote_total_cents`, sets `deposit_due_cents` to the quote times the package's `deposit_pct` rounded up to whole cents, reconciles `balance_due_cents` as `quote_total_cents` minus `amount_paid_cents`, and reserves the room window.

A held booking may be released back to `QUOTE_DRAFT`, which frees the reserved room window. Release is allowed only while the booking's `payment_status` is `UNPAID`; if any payment has been taken the release is rejected with `ERR_HOLD_HAS_PAYMENTS`.

The deposit derives from the quote through a pinned evaluation order that avoids any apparent circularity. First `quote_total_cents` is computed from the line items alone; then `deposit_due_cents` is set to `quote_total_cents` multiplied by the package's `deposit_pct`, taken up to the next whole cent by ceiling; then `balance_due_cents` is computed as `quote_total_cents` minus `amount_paid_cents`. The balance depends on the quote and the amount paid, not on the deposit, so once this order is fixed there is no real cycle. While the booking is `HELD`, the deposit is recomputed whenever the quote changes; on confirmation it is pinned and no longer recomputed.

### 3.8. Confirming a Booking

Confirmation moves a booking from `HELD` to `CONFIRMED` (and likewise from `RESCHEDULED` back to `CONFIRMED` after a weather reschedule). A `Coordinator` performs it, and three classes of completeness must hold. Waiver completeness comes first: the count of `SIGNED` waivers (`waivers_signed`) must be at least `waivers_required`, or the confirmation is rejected with `ERR_WAIVERS_INCOMPLETE`. The deposit gate must be met: `amount_paid_cents` must be at least `deposit_due_cents`, or confirmation is rejected with `ERR_DEPOSIT_NOT_MET` (HTTP 402). Staffing completeness must hold: exactly one `ASSIGNED` staff assignment with `role_on_event` of `HOST` must exist, or confirmation is rejected with `ERR_HOST_NOT_ASSIGNED`; and for every active add-on whose `requires_skill` is not `NONE`, an `ASSIGNED` assignment with the matching `role_on_event` must exist — a character add-on needs an entertainer and a cake add-on needs a cook — or confirmation is rejected with `ERR_ADDON_STAFF_MISSING`.

When confirmation succeeds from `HELD`, the server pins `deposit_due_cents` so it is no longer recomputed and recomputes `payment_status`. When confirmation succeeds from `RESCHEDULED`, the server recomputes `payment_status` (the deposit was already pinned on the original confirmation). Note that the host-required and add-on-staffing checks are part of the `HELD → CONFIRMED` path; the `RESCHEDULED → CONFIRMED` path re-checks waiver completeness and the deposit gate.

### 3.9. Weather Holds and Rescheduling

Outdoor parties at weather-dependent venues can be paused when storms threaten. A `Coordinator` may move a `CONFIRMED` booking to `WEATHER_HOLD` only if the booking is `weather_eligible` — otherwise the request is rejected with `ERR_NOT_WEATHER_ELIGIBLE` — and only if the event has not yet started, meaning the clock's `current_utc` is strictly before `event_start_utc`; an attempt at or after the start is rejected with `ERR_EVENT_ALREADY_STARTED`. While on weather hold the room window stays reserved so the slot remains protected.

From `WEATHER_HOLD`, the coordinator reschedules to a new start, transitioning the booking to `RESCHEDULED`. The request supplies a new `event_start_utc` and the `expected_booking_version` for the optimistic-concurrency check. The new window — from the new start through the new start plus `effective_duration_minutes` plus the room's `buffer_minutes` — must not overlap any other booking on the room in `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`, or the reschedule is rejected with `ERR_ROOM_WINDOW_CONFLICT`. The supplied `expected_booking_version` must match the booking's current `version`, or the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the server releases the old reserved room window and reserves the new one, sets `event_start_utc` to the new start, recomputes `event_end_utc`, and increments `reschedule_count` by one. The booking then awaits confirmation again to return to `CONFIRMED`.

A separate timing rule governs guardian-initiated changes more broadly: a guardian self-reschedule is permitted only when the time from now to the event is at least the venue's `reschedule_lead_hours` — that is, `event_start_utc` minus the clock's `current_utc` is at least that many hours — and a request inside that lead window is rejected with `ERR_RESCHEDULE_TOO_LATE`.

### 3.10. Completion and the Settlement Bill

Once an event has run, a `Coordinator` completes it, moving the booking from `CONFIRMED` to `COMPLETED`. Two preconditions guard the transition. The event must have ended: the clock's `current_utc` must be at or after `event_end_utc`, or completion is rejected with `ERR_EVENT_NOT_ENDED`. The balance must be clear: after recomputing the bill against the settlement total, `balance_due_cents` must be at most zero, or completion is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 402).

Completion is where the **settlement** figure is computed and stored as `final_total_cents`. Where the quote estimate prices against the net-current children count, the settlement prices against the *peak* children count realized over the booking's history — these diverge whenever head count was raised and later lowered, because the estimate sees only the net while the settlement charges the peak. The settlement replays the roster. First the children count at creation is reconstructed as the current `children_count` minus the sum of every roster event's `children_delta`. Then, walking the booking's `GuestParty` events in ascending `created_at` order (each event's `created_at` is unique), a running children total starts at that reconstructed creation count and each event's `children_delta` is added to it in turn; the peak children figure is the maximum the running total ever reaches. The overage is that peak minus `included_children`, never below zero. The package charge is `base_price_cents` plus the overage multiplied by `per_extra_child_cents`. The add-on charge is, as before, the sum over every active add-on of `unit_price_cents` times `quantity`. The settlement total is the package charge plus the add-on charge, in integer cents.

On completion the server recomputes `final_total_cents`, reconciles `balance_due_cents` as `final_total_cents` minus `amount_paid_cents`, recomputes `payment_status`, releases the room window, and releases every `ASSIGNED` staff assignment to `RELEASED`. `COMPLETED` is terminal.

### 3.11. Payments, Balances, and Payment Status

Money moves through **Payment** records, an append-only ledger on the booking. A `FinanceClerk` or `Coordinator` records one with a `direction` of `CHARGE` (the guardian paying in) or `REFUND` (the venue paying out), a positive `amount_cents` (at least 1), and a `purpose` of `DEPOSIT`, `BALANCE`, or `CANCELLATION_REFUND` (defaulting to `BALANCE`). A payment starts `SETTLED`. A manual refund may not exceed what has been paid: a `REFUND` whose `amount_cents` is greater than the current `amount_paid_cents` is rejected with `ERR_REFUND_EXCEEDS_PAID` (HTTP 402).

The booking's `amount_paid_cents` is reconciled as the sum of `amount_cents` over all `SETTLED` charges minus the sum of `amount_cents` over all `SETTLED` refunds. After this, `balance_due_cents` is reconciled as the applicable total — `final_total_cents` when the booking is `COMPLETED`, otherwise `quote_total_cents` — minus `amount_paid_cents`. The recompute runs on every payment recorded or voided and on the booking's confirm, complete, and cancel transitions.

The `payment_status` is then derived against a target equal to `final_total_cents` when the booking is `COMPLETED` and `quote_total_cents` otherwise, evaluated in this order. If `amount_paid_cents` is at most zero and a `SETTLED` refund with purpose `CANCELLATION_REFUND` exists on the booking, the status is `REFUNDED`. Otherwise, if `amount_paid_cents` is at most zero, the status is `UNPAID`. Otherwise, if `amount_paid_cents` is at least the target, the status is `PAID_IN_FULL`. Otherwise, if `amount_paid_cents` is at least `deposit_due_cents`, the status is `DEPOSIT_PAID`. Otherwise — a partial payment that has not reached the deposit — the status is `UNPAID`, so that a sub-deposit payment still reads as unpaid for gating purposes. The boundary is inclusive at each threshold: meeting the target exactly reads as `PAID_IN_FULL`, and meeting the deposit exactly reads as `DEPOSIT_PAID`.

A `FinanceClerk` may void a payment, moving it from `SETTLED` to `VOIDED`, after which it no longer counts toward `amount_paid_cents`. Voiding is constrained: it is not allowed once the booking is `COMPLETED` (`ERR_BOOKING_SETTLED`), and only inbound charges may be voided — a `REFUND`-direction payment is immutable and a void attempt against it is rejected with `ERR_REFUND_IMMUTABLE`. Voiding a charge recomputes `amount_paid_cents`, then `balance_due_cents`, then `payment_status`. Payment lists may be filtered by `direction` and by `status`.

### 3.12. Cancellation and Tiered Refunds

A `Coordinator` or a `Guardian` may cancel a booking from any non-terminal state — `QUOTE_DRAFT`, `HELD`, `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED` — moving it to `CANCELLED`. Cancellation is permitted when the clock's `current_utc` is before `event_start_utc`, or when the booking is still in `QUOTE_DRAFT` or `HELD`; otherwise — a started event in a confirmed-class state — it is rejected with `ERR_EVENT_ALREADY_STARTED`. Cancellation releases any reserved room window and runs the cascade described in Section 2.5: active add-ons become `REMOVED`, assigned staff become `RELEASED`, and draft or signed waivers become `VOIDED`.

If the booking has any money paid (`amount_paid_cents` greater than zero), cancellation synthesizes one refund — a `Payment` with `direction` `REFUND`, `purpose` `CANCELLATION_REFUND`, `status` `SETTLED`, and an `amount_cents` computed by the tiered refund rule below. That synthesized refund then flows through the reconciliation chain: `amount_paid_cents` is recomputed, then `balance_due_cents`, then `payment_status` — which lands on `REFUNDED` once the net paid returns to zero.

The **tiered cancellation refund** depends on how long before the event the cancellation lands and on the booking's stage. Let the hours to the event be `event_start_utc` minus the clock's `current_utc` expressed in hours (this can be negative if the event has passed). If the booking was still pre-confirmation — in `QUOTE_DRAFT` or `HELD` — the deposit is not yet binding and the full paid amount is refunded. Otherwise, if the hours to the event are at least 72 — the free-cancellation window — the full paid amount is refunded. Otherwise, if the hours to the event are at least 0 but less than 72 (inside the forfeiture window but before the event), the deposit is forfeited: the refund is the amount paid minus `deposit_due_cents`, but never below zero. Otherwise — the event has already started or passed — there is no refund. The 72-hour threshold is the free-cancellation cutoff; at or beyond it a confirmed booking still gets everything back, and inside it the venue keeps the deposit.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and configuration-lifecycle actions — return `200 OK`. All endpoints honor the response envelope, authentication, and validation ordering described in Section 2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue | VenueManager |
| GET | `/venues` | List venues (paginated) | VenueManager, Coordinator, FinanceClerk, Guardian |
| GET | `/venues/{id}` | Get a venue | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/rooms` | Create a room under a venue | VenueManager |
| GET | `/rooms` | List rooms, optionally filtered by venue | VenueManager, Coordinator, FinanceClerk, Guardian |
| GET | `/rooms/{id}` | Get a room | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/rooms/{id}/close` | Close a room | VenueManager |
| POST | `/packages` | Create a party package under a venue | VenueManager |
| GET | `/packages` | List packages, optionally filtered by venue | VenueManager, Coordinator, FinanceClerk, Guardian |
| GET | `/packages/{id}` | Get a package | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/packages/{id}/retire` | Retire a package | VenueManager |
| POST | `/staff-members` | Create a staff member under a venue | VenueManager |
| GET | `/staff-members` | List staff members, optionally filtered by venue | VenueManager, Coordinator, FinanceClerk, Guardian |
| GET | `/staff-members/{id}` | Get a staff member | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/staff-members/{id}/deactivate` | Deactivate a staff member | VenueManager |
| POST | `/bookings` | Create a booking in QUOTE_DRAFT | Coordinator, Guardian |
| GET | `/bookings` | List bookings with filters (paginated) | VenueManager, Coordinator, FinanceClerk, Guardian |
| GET | `/bookings/{id}` | Get a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| PATCH | `/bookings/{id}` | Update head count on a QUOTE_DRAFT/HELD booking | Coordinator, Guardian |
| POST | `/bookings/{id}/hold` | Move QUOTE_DRAFT to HELD; reserve room window | Coordinator |
| POST | `/bookings/{id}/release-hold` | Move HELD to QUOTE_DRAFT; release room window | Coordinator |
| POST | `/bookings/{id}/confirm` | Move HELD/RESCHEDULED to CONFIRMED | Coordinator |
| POST | `/bookings/{id}/weather-hold` | Move CONFIRMED to WEATHER_HOLD | Coordinator |
| PATCH | `/bookings/{id}/reschedule` | Move WEATHER_HOLD to RESCHEDULED (OCC-guarded) | Coordinator |
| POST | `/bookings/{id}/complete` | Move CONFIRMED to COMPLETED; settle final bill | Coordinator |
| POST | `/bookings/{id}/cancel` | Cancel a non-terminal booking; cascade and refund | Coordinator, Guardian |
| POST | `/bookings/{id}/add-ons` | Add an add-on to a QUOTE_DRAFT/HELD booking | Coordinator, Guardian |
| GET | `/bookings/{id}/add-ons` | List add-ons for a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| DELETE | `/bookings/{id}/add-ons/{addOnId}` | Remove an add-on (QUOTE_DRAFT/HELD only) | Coordinator, Guardian |
| POST | `/bookings/{id}/guest-parties` | Record a head-count roster event | Coordinator, Guardian |
| GET | `/bookings/{id}/guest-parties` | List roster events for a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/bookings/{id}/waivers` | Create a DRAFT waiver for a child | Coordinator, Guardian |
| GET | `/bookings/{id}/waivers` | List waivers for a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/bookings/{id}/waivers/{waiverId}/sign` | Sign a DRAFT waiver | Guardian, Coordinator |
| POST | `/bookings/{id}/waivers/{waiverId}/revoke` | Revoke a SIGNED waiver back to DRAFT | Guardian, Coordinator |
| POST | `/bookings/{id}/staff-assignments` | Assign a staff member to a booking | Coordinator |
| GET | `/bookings/{id}/staff-assignments` | List staff assignments for a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/bookings/{id}/staff-assignments/{assignmentId}/release` | Release a staff assignment | Coordinator |
| GET | `/staff-members/{id}/staff-assignments` | List assignments for a staff member | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/bookings/{id}/payments` | Record a payment (charge or refund) | FinanceClerk, Coordinator |
| GET | `/bookings/{id}/payments` | List payments for a booking | VenueManager, Coordinator, FinanceClerk, Guardian |
| POST | `/bookings/{id}/payments/{paymentId}/void` | Void a SETTLED charge payment | FinanceClerk |
| POST | `/_clock/set_current_utc` | Set the server logical clock | VenueManager, Coordinator |
| GET | `/_clock` | Read the server logical clock | VenueManager, Coordinator, FinanceClerk, Guardian |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_ADDON_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_VENUE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BOOKING_NOT_SIGNABLE` | 409 Conflict |
| `ERR_WAIVER_LOCKED` | 409 Conflict |
| `ERR_ADDON_LOCKED` | 409 Conflict |
| `ERR_BOOKING_SETTLED` | 409 Conflict |
| `ERR_REFUND_IMMUTABLE` | 409 Conflict |
| `ERR_HOLD_HAS_PAYMENTS` | 409 Conflict |
| `ERR_HOST_REQUIRED` | 409 Conflict |
| `ERR_ROOM_CLOSED` | 409 Conflict |
| `ERR_PACKAGE_RETIRED` | 409 Conflict |
| `ERR_STAFF_INACTIVE` | 409 Conflict |
| `ERR_SKILL_MISMATCH` | 409 Conflict |
| `ERR_WAIVERS_INCOMPLETE` | 409 Conflict |
| `ERR_HOST_NOT_ASSIGNED` | 409 Conflict |
| `ERR_ADDON_STAFF_MISSING` | 409 Conflict |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_STAFF_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EVENT_ALREADY_STARTED` | 409 Conflict |
| `ERR_EVENT_NOT_ENDED` | 409 Conflict |
| `ERR_NOT_WEATHER_ELIGIBLE` | 409 Conflict |
| `ERR_RESCHEDULE_TOO_LATE` | 409 Conflict |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_MET` | 402 Payment Required |
| `ERR_BALANCE_OUTSTANDING` | 402 Payment Required |
| `ERR_REFUND_EXCEEDS_PAID` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
