# Spin Studio API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an indoor-cycling (spin) studio operator in the style of a boutique fitness brand. The platform manages the full operating surface of one or more physical studios: the seat map of bikes inside each room, the class sessions taught on those bikes, the riders who reserve a specific bike, the class-packs and memberships that pay for those rides, and the retail counter that sells water bottles, grip socks, and rented cycling shoes.

The central tension the system resolves is *quota allocation under time pressure*. A finite number of bikes exist in a room; a session snapshots that count as its capacity; riders compete for individual seats and, once a class is full, queue on a waitlist that promotes automatically when a seat frees up. Layered on top of that are the money flows — class credits that can be held, consumed, or refunded; flat fees for late cancellations and no-shows; a strike system that suspends repeat offenders; and a refundable wallet that absorbs waived fees and pays for retail. Because two riders can each believe a particular bike is free, several write paths are guarded by optimistic concurrency so that a booker acting on a stale view of a session is turned away rather than allowed to race for a seat that may already be taken.

The remainder of this document defines the global contract every endpoint shares (Section 2), the domain workflows and their interlocking rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the explicitly open operations must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes four roles, spelled exactly as follows: `StudioManager`, `Member`, `Instructor`, and `Anonymous`. A request that omits either header, or supplies a malformed one, on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`.

The two open operations that do not require authentication headers are member self-registration and the test-only logical-clock and injection helpers. Member registration is performed under the `Anonymous` role, which may do nothing else; an `Anonymous` caller's only capability is to register as a member.

Two roles are tied to persisted identities. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare that resource's member foreign key to `X-User-ID`. A member may therefore act only on their own reservations, their own credit packs, their own waitlist entries, and their own retail and penalty records. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks compare the instructor foreign key on the relevant session to `X-User-ID`, so an instructor may run roster operations (check-in, shoe return) only on sessions they themselves teach. A violation of either ownership rule is rejected with `ERR_OWNERSHIP_VIOLATION`.

The other two roles are opaque operator identities. When `X-User-Role` is `StudioManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, unverified identifier used only to satisfy the open registration path and is not matched against any stored entity.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Requests that violate these bounds are rejected as malformed input.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of items matching the query before pagination and `has_more` indicates whether additional items remain beyond the current page.

### 2.4. Common Resource Properties and Logical Clock

Every entity in this system is a top-level resource that carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` advances on every mutation. The `version` field is an integer that begins at the resource's creation and increments by one on every mutation. All entities in this system carry the full set — `id`, `created_at`, `updated_at`, and `version`.

The system runs on a **logical clock**, not wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until a clock-setting request arrives the clock holds at that default and never falls back to real time. An operator may advance the clock by supplying a target instant in the `to_iso8601` field; the server then reports the new value as `now_utc`. Every time-dependent rule in this document — expiry of packs, cancellation windows, check-in windows, strike windows, the "now" recorded on bookings and charges — is evaluated against this logical clock.

### 2.5. Nested Resource Retrieval and Scope Matching

Several endpoint paths nest identifiers — for example a bike lives under a room which lives under a studio, and a reservation lives under a session which lives under a studio. The system validates path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Beyond mere existence, the system enforces *scope matching*: a room must belong to the studio named earlier in the path, a bike must belong to the room, a session's room must belong to the session's studio, and a bike chosen for a reservation must belong to the session's room. A scope mismatch anywhere in the chain is also surfaced as `ERR_NOT_FOUND`, because from the caller's perspective the nested resource does not exist within the stated parent.

### 2.6. Precision, Money, and Counting Rules

All monetary amounts are stored and returned as integer cents. Wherever a calculation produces a fractional cent — the per-credit value of a class-pack, a percentage discount on a retail order, a time-prorated membership refund — the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one-half rounds away from zero, upward). Stated as "two decimal places at the cents level," the cents themselves are always integers in API payloads.

Credit counts are integers. Capacity, booked counts, waitlist counts, strike counts, and completed-ride counts are all whole numbers. Boundary comparisons in this document are exact: where a rule says a count must "reach" or be "at or above" a threshold, the threshold value itself triggers the rule (the comparison is inclusive), and this distinction is load-bearing for capacity, strikes, and pack exhaustion.

### 2.7. Derived Fields and Reconciliation

Many fields are computed rather than supplied by the client, and the system keeps them reconciled with the underlying rows on every read and every relevant mutation. A room's `bike_count` is the number of its bikes whose status is not `RETIRED`. A session's `booked_count` is the number of its reservations whose attendance is `BOOKED`, and its `waitlist_count` is the number of its waitlist entries in `WAITING`. A member's `completed_ride_count` is the number of their reservations whose attendance is `ATTENDED`. A credit pack's `remaining_credits` and a member's `active_strike_count` and `wallet_credit_cents` are likewise derived, by the rules given in Section 3. Whenever a derived field on a resource changes as a side effect of an operation, that change is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.8. Hierarchical Consistency and Cascades

A single operation in this domain frequently mutates more than one resource, and each such cascade is part of the contract rather than an incidental detail. Cancelling a session reverses its bookings and closes its waitlist; completing a session converts no-shows into fee-bearing penalties and may suspend a member; a member's cancellation can promote the next person off the waitlist, which in turn creates a brand-new reservation and debits a credit. Each affected resource undergoes its own mutation with the attendant `updated_at` refresh and `version` increment. The precise step-by-step cascades are described in Section 3 alongside the workflows that trigger them; the governing principle here is that the system completes the entire cascade as one consistent unit, leaving no resource in a state that contradicts its siblings.

### 2.9. Strike Accumulation and Account Suspension

The studio penalizes unreliable riders through a rolling strike window. A penalty charge marked as counting toward strikes contributes to a member's `active_strike_count` for a fixed trailing window of 30 days measured backward from the current logical-clock instant. Concretely, the active strike count is the number of penalty charges belonging to the member that count as a strike, have not been waived, and whose charge time falls on or after the start of that 30-day window and on or before the current clock instant. Charges older than 30 days drop out of the count automatically as the clock advances, and waiving a charge removes it from the count immediately.

When a newly created strike-bearing charge causes the active strike count to reach three or more, the member's account transitions from `ACTIVE` to `SUSPENDED`. The threshold is inclusive — three strikes is enough. A suspended member is barred from creating new reservations and from joining waitlists; such attempts are rejected with `ERR_MEMBER_SUSPENDED`. Suspension is only lifted by an explicit manager reinstatement; the underlying strikes are not erased by reinstatement, and a strike count that later drifts below the threshold (because charges aged out or were waived) does not auto-reinstate the member.

### 2.10. Optimistic Concurrency Control

Two write paths require the client to prove it is acting on a current view of a shared parent, and both reject stale writes with HTTP 412 rather than letting them proceed.

Booking a bike on a session is one such path. A booking request must carry `expected_session_version`, holding the `version` of the target `ClassSession` that the client last observed. If a prior booking, a cancellation, or an automatic waitlist promotion has advanced the session's `version` since the client read it, the client's picture of which seats remain free is stale, so the booking is rejected with `ERR_STALE_SESSION_VERSION`. The check compares `expected_session_version` against the session's current `version` and fails on any mismatch.

Refunding a credit pack is the other. A refund request must carry `expected_pack_version`, holding the `version` of the target `CreditPack` that the client last observed. Because a credit debit, a credit restore, or an expiry transition changes the pack's remaining-credit count and therefore its prorated refund base, a refund issued against a stale pack view is rejected with `ERR_STALE_PACK_VERSION` rather than refunding against an outdated count; the check compares `expected_pack_version` against the pack's current `version` and fails on any mismatch. No other endpoint accepts a version field, and endpoints not named here perform no concurrency check.

## 3. Business Logic & Workflows

### 3.1. Provisioning Studios, Rooms, and the Seat Map

A `StudioManager` provisions the physical estate. A studio is created with a display `name`, a `city`, and an optional IANA `timezone` that defaults to `UTC` and is purely informational because all session times are stored in UTC. The studio also holds the operator-tunable penalty policy: `late_cancel_window_minutes`, the number of minutes before a session's start inside which a cancellation counts as late, defaulting to 720 (twelve hours); `late_cancel_fee_cents`, the flat fee for a late cancellation, defaulting to 2000; and `no_show_fee_cents`, the flat fee for a no-show, defaulting to 3000. A studio's `status` is system-managed and is always `ACTIVE` in this version (there is no studio-close flow).

Within a studio the manager creates rooms. A room carries a `name` and belongs to its studio. Its `status` is system-managed and always `OPEN`. Its `bike_count` is derived as the number of non-retired bikes it contains and starts at zero. Into a room the manager places bikes, each forming a cell of the seat map. A bike is created with a `position_row` and a `position_col`, both one-based integers of at least one, and a human-readable `label` such as "A3". A bike's `status` is `ACTIVE` on creation and may later become `RETIRED`. Adding or retiring a bike recomputes the parent room's `bike_count`.

Retiring a bike sets its status to `RETIRED` and removes it from future capacity snapshots. Retirement does not shrink the capacity of sessions that already exist — capacity is fixed at scheduling time, as described next — but a retired bike can never again be chosen for a new reservation.

### 3.2. Instructors and Scheduling Sessions

Instructors are registered by a manager with a unique `email` and a `full_name`; an instructor's `status` is system-managed and always `ACTIVE`. A class session is scheduled by a manager inside a studio and references a `room_id`, an `instructor_id`, a `start_utc`, and an `end_utc`, where the end must be strictly later than the start (a non-positive interval is rejected as malformed input). The referenced room must belong to the studio. An optional `waitlist_capacity` caps how many entries may wait for the session and defaults to 10.

At the moment of scheduling, the session's `capacity` is snapshotted: it is set to the count of bikes in the chosen room whose status is `ACTIVE` at that instant, and it must be at least one. This snapshot is permanent for the session even if bikes are later retired. The session also records its `studio_id`, starts in `SCHEDULED` status, and initializes `booked_count` and `waitlist_count` to zero.

Before a session is accepted, the system guards against double-booking shared resources. Neither the chosen instructor nor the chosen room may already be committed to another `SCHEDULED` session whose time interval overlaps the new one; an overlap on either the instructor or the room is rejected with `ERR_SCHEDULE_CONFLICT`. A session's `status` may be `SCHEDULED`, `CANCELLED`, or `COMPLETED`, with the latter two terminal.

When a manager cancels a `SCHEDULED` session, the cancellation is permitted only while the session is still `SCHEDULED` and the current clock instant is strictly before the session's `start_utc`; an attempt against a session not in `SCHEDULED` is rejected as an invalid state transition with `ERR_INVALID_STATE`. The cancel triggers a cascade. First, every reservation still in `BOOKED` moves to `EARLY_CANCELLED` attendance with `CREDIT_REFUNDED` billing. Second, as a consequence of each such refund, any class-pack that had been charged has its `consumed_credits` decremented by one, and a pack that was sitting in `EXHAUSTED` returns to `ACTIVE`. Third, every waitlist entry still in `WAITING` is moved to `CANCELLED` — a studio-initiated cancel performs no promotions. No penalty charge is ever created by a studio cancel; the studio never penalizes a member for its own cancellation.

Completing a session is the mirror-image terminal transition, available only while the session is still `SCHEDULED` and only once the current clock instant is at or after the session's `end_utc`; a completion attempt against a session not in `SCHEDULED` is rejected as an invalid state transition with `ERR_INVALID_STATE`. The completion cascade is described in Section 3.4 because it is where no-shows and penalties originate.

### 3.3. Riders, Packs, Coverage, and the First Ride

A member self-registers (anonymously) with a unique `email`, a `full_name`, and a `home_studio_id`. On registration the member's `account_status` is `ACTIVE`, and the computed `completed_ride_count`, `active_strike_count`, and `wallet_credit_cents` all start at zero. A member's account may later be `SUSPENDED` and reinstated as described in Section 2.9.

Riders pay for classes through credit packs, purchasable either by the member themselves or by a manager. A pack references its `member_id` and has a `kind` of either `CLASS_PACK` or `MEMBERSHIP`, a `price_cents` paid, and an `expires_at` instant after which it can no longer be charged. A `CLASS_PACK` is bought with a `purchased_credits` count (at least zero), tracks `consumed_credits` (starting at zero), and reports `remaining_credits` as its purchased credits minus its consumed credits, never below zero. A `MEMBERSHIP` ignores `purchased_credits`, grants unlimited rides within its window, and always reports `remaining_credits` as the sentinel value of `-1`. Every pack records its `activated_at` (the logical-clock instant it became active) and begins in `ACTIVE` status.

A pack's `scope` governs where it may be spent and defaults to `HOME_ONLY`. A `HOME_ONLY` pack covers only sessions at the member's home studio. A `MULTI_STUDIO` pack covers sessions at any studio whose id appears in its `grant_studio_ids` array — a list of plain studio id references (resolved against the studio collection, not enforced as foreign keys), which is empty for a home-only pack. A pack's `status` may be `ACTIVE`, `EXHAUSTED`, `EXPIRED`, or `REFUNDED`, the last being terminal.

Pack lifecycle is partly cyclic. A `CLASS_PACK` whose `consumed_credits` reach its `purchased_credits` — that is, whose remaining credits fall to zero after a booking debit — transitions from `ACTIVE` to `EXHAUSTED` and can no longer be selected to cover a new booking. An `EXHAUSTED` pack returns to `ACTIVE` the moment a refund, early cancellation, or session cancellation restores a credit so that its remaining credits rise above zero, provided the current clock is still before the pack's `expires_at`; this `ACTIVE`-to-`EXHAUSTED`-to-`ACTIVE` movement is the conserved-credit cycle. Independently, once the clock reaches or passes a pack's `expires_at`, the pack becomes `EXPIRED` — observed lazily on the next read of the pack or the next attempt to charge it — and its remaining credits are forfeited; an `EXHAUSTED` pack likewise becomes `EXPIRED` at that instant. An expired pack is never charged and never silently returns to `ACTIVE`.

The **first ride** is comped. The very first time a member rides, the booking consumes no credit and incurs no fee. A booking qualifies for the first-ride comp only when the member's `completed_ride_count` is zero, the member has no prior reservation in any attendance state other than `EARLY_CANCELLED` (so a genuine first ride, not a re-attempt after a real attendance), and the first-ride comp has not already been consumed. When the comp applies, the reservation's `first_ride_discount_applied` is set true and its `credit_pack_id` is left null because no pack was debited.

### 3.4. Booking a Bike, Charge Resolution, and Attendance

Booking is the heart of the system, performed by a member who names the `member_id`, the chosen `bike_id`, the `expected_session_version`, and optionally a `shoe_size`. The system evaluates a strict ladder of checks before a reservation is created, and the relative ordering of these checks is significant because an earlier failure masks a later one. Authentication is checked first, then role permission, then the existence and scope of every path resource, then the acting member's ownership of the booking, then the validity of the session's state for booking. Next the system enforces the session-version concurrency check of Section 2.10, rejecting a stale booking with `ERR_STALE_SESSION_VERSION`. Only then does it confirm the member's account is `ACTIVE` rather than `SUSPENDED`, rejecting a suspended booker with `ERR_MEMBER_SUSPENDED`.

After those gates, the business constraints on the seat itself are evaluated. The chosen bike must be `ACTIVE`, must belong to the session's room, and must not already be held by another `BOOKED` reservation on this session; any of these failures yields `ERR_BIKE_UNAVAILABLE`. The member must not already hold a `BOOKED` reservation on the same session — one bike per member per class — and a second attempt yields `ERR_DUPLICATE_RESERVATION`. The system must be able to fund the ride: unless the first-ride comp applies, a chargeable pack must exist, and if none does the booking is rejected with `ERR_NO_CHARGEABLE_PACK`. Finally, capacity is checked: a booking is rejected with `ERR_SESSION_FULL` when the session's `booked_count` is at or above its `capacity`, in which case the rider must join the waitlist instead. Malformed request bodies — bad enum members, non-positive integers, an end that is not after a start — are rejected as `ERR_VALIDATION`.

**Charge resolution** decides how the single class credit for a booking is covered, and its evaluation order is fixed. First, if the member is first-ride eligible (per Section 3.3), the comp is applied: `first_ride_discount_applied` becomes true, `credit_pack_id` stays null, no credit is debited and no fee is taken, and resolution is complete. Otherwise the system assembles the candidate set of the member's packs that are all of: belonging to the booking member, in `ACTIVE` status, not yet expired (the clock is before `expires_at`), and able to pay — meaning the pack is a `MEMBERSHIP`, or it is a `CLASS_PACK` with at least one remaining credit. Each candidate must also cover the session's studio by scope: a `HOME_ONLY` pack covers the booking only when the session's `studio_id` equals the member's `home_studio_id` (its grant list is ignored), whereas a `MULTI_STUDIO` pack covers the booking only when the session's `studio_id` appears in the pack's `grant_studio_ids` (the home studio is ignored). If the candidate set is empty, the booking fails with `ERR_NO_CHARGEABLE_PACK`. Otherwise exactly one pack is selected by ranking the candidates: `CLASS_PACK` packs are preferred over `MEMBERSHIP` packs so that finite credits are spent before unlimited ones; among equals, the pack with the earliest `expires_at` is chosen so the soonest-to-expire is used first; and any remaining tie is broken by the earlier `created_at`. The chosen pack's id is recorded as the reservation's `credit_pack_id`; if it is a `CLASS_PACK` its `consumed_credits` is incremented by one (and if that brings remaining credits to zero the pack transitions to `EXHAUSTED`), while a `MEMBERSHIP` changes no credit counter.

A new reservation is born with `attendance_status` of `BOOKED` and `billing_status` of `CREDIT_HELD`, records its `session_id`, `member_id`, `bike_id`, and `booked_at` (the clock instant of booking), and on success the session's `version` is incremented and its `booked_count` recomputed. Attendance and billing are two **independent dimensions** living on the same reservation row and advancing through different triggers. Attendance may be `BOOKED`, `ATTENDED`, `LATE_CANCELLED`, `EARLY_CANCELLED`, or `NO_SHOW`, with all but `BOOKED` terminal. Billing may be `CREDIT_HELD`, `CREDIT_CONSUMED`, `CREDIT_REFUNDED`, or `FEE_CHARGED`, with all but `CREDIT_HELD` terminal. `CREDIT_HELD` means a credit is reserved but still reversible; each of the four terminal attendance outcomes drives billing to exactly one terminal value.

An instructor checks a rider in, moving attendance from `BOOKED` to `ATTENDED`. Check-in is permitted only while the reservation is still `BOOKED`, the session is still `SCHEDULED`, and the current clock instant falls within the check-in window — at or after the session's `start_utc` minus the configured check-in lead time, and at or before the session's `end_utc`. A check-in attempted outside that window is rejected with `ERR_WINDOW_CLOSED`, and an attempt against a reservation not in `BOOKED` is rejected as an invalid state transition with `ERR_INVALID_STATE`. A successful check-in advances billing from `CREDIT_HELD` to `CREDIT_CONSUMED` — for a `CLASS_PACK` booking the held credit is now permanently consumed with no reversal path — and recomputes the member's `completed_ride_count` upward by one.

When a session is **completed**, every reservation still in `BOOKED` is swept to `NO_SHOW` attendance with `FEE_CHARGED` billing (the held credit is not returned). For each such new no-show the system creates a penalty charge of kind `NO_SHOW` with `amount_cents` snapshotted from the studio's `no_show_fee_cents` and `counts_as_strike` true; creating that charge recomputes the member's `active_strike_count`, and if it reaches the suspend threshold the member is moved to `SUSPENDED`. Any no-show reservation whose `shoe_status` was `RESERVED` has that shoe `FORFEITED`. Every waitlist entry still `WAITING` is moved to `EXPIRED_OFF`. These three cascade steps — attendance/billing flip, penalty creation, possible suspension — are causally chained and all part of the single completion operation.

### 3.5. Cancellation: Early Versus Late

A member may cancel their own booking, and whether the cancellation is *early* or *late* is decided by comparing the current clock instant against the studio's late-cancel window measured back from the session start. The boundary instant is the session's `start_utc` minus the studio's `late_cancel_window_minutes`. A cancellation at or before that boundary is **early**; a cancellation strictly after the boundary but still strictly before `start_utc` is **late**. Cancellation is permitted only while the reservation is `BOOKED` and the session is `SCHEDULED`; a cancellation attempted at or after the session's start is rejected with `ERR_WINDOW_CLOSED`.

An **early** cancellation moves attendance to `EARLY_CANCELLED` and billing to `CREDIT_REFUNDED`. If a `CLASS_PACK` was charged, its `consumed_credits` is decremented by one and an `EXHAUSTED` pack thereby returns to `ACTIVE` (the conserved-credit invariant). No penalty is created. Because a seat has been freed, the system then promotes the earliest waiting entry on the session, as described in Section 3.6. The session's `version` is incremented.

A **late** cancellation moves attendance to `LATE_CANCELLED` and billing to `FEE_CHARGED`; crucially the held credit is *not* refunded. The system creates a penalty charge of kind `LATE_CANCEL` with `amount_cents` snapshotted from the studio's `late_cancel_fee_cents` and `counts_as_strike` true; that charge recomputes the member's `active_strike_count`, and a breach of the suspend threshold moves the member to `SUSPENDED`. If the reservation's `shoe_status` was `RESERVED`, the shoe is `FORFEITED` and its `shoe_fee_cents` is retained, not refunded. A late cancellation still frees the bike, so the earliest waiting entry is promoted just as with an early cancel. The session's `version` is incremented.

### 3.6. The Waitlist and Automatic Promotion

When a session is full, a member may join its waitlist by naming the `member_id` and the `credit_pack_id` that should pre-authorize the eventual booking. A waitlist join is rejected with `ERR_WAITLIST_FULL` when the count of entries in `WAITING` is already at the session's `waitlist_capacity`, and — like booking — it is rejected for a `SUSPENDED` member with `ERR_MEMBER_SUSPENDED`. Joining is meaningful only for a full session; a join attempted on a session that still has free capacity is rejected with `ERR_SESSION_NOT_FULL`, since the member should simply book. A new entry starts in `WAITING`, records its `enqueued_at` (the clock instant of joining, which is the FIFO promotion key), leaves `promoted_reservation_id` null, and the session's `waitlist_count` is recomputed. A waitlist entry's `status` may be `WAITING`, `PROMOTED`, `EXPIRED_OFF`, or `CANCELLED`, the latter three terminal. A member may leave the waitlist while `WAITING`, which moves the entry to `CANCELLED` and recomputes the session's `waitlist_count`; no charge is taken.

When an early or late cancellation frees a seat, the system attempts to **promote** off the waitlist. The candidate is the earliest `WAITING` entry by `enqueued_at` ascending, breaking ties by `created_at` ascending. Promotion proceeds only if the session now has free capacity (its booked count is below capacity after the freeing cancel) and the entry's pre-authorized pack is chargeable — that is, the pack referenced by the entry's `credit_pack_id` is `ACTIVE`, not expired, and either a `MEMBERSHIP` or a `CLASS_PACK` with remaining credit — or the member is first-ride eligible. On promotion the system creates a fresh reservation for that member in `BOOKED` attendance and `CREDIT_HELD` billing on an auto-assigned free `ACTIVE` bike, selecting the bike with the lowest `position_row`, then the lowest `position_col`, then the earliest `created_at`. It debits one credit from the entry's pre-authorized pack (or applies first-ride comp or membership coverage), sets the entry's `promoted_reservation_id` to the new reservation, and moves the entry's status to `PROMOTED`. The duplicate-reservation guard still holds during promotion, so a member already holding a booked seat on the session is not double-promoted. A waitlist entry that is still `WAITING` when its session is completed is moved to `EXPIRED_OFF` with no charge, and one caught by a session cancellation is moved to `CANCELLED`.

### 3.7. Shoe Rentals

A shoe rental rides alongside a reservation as its own small lifecycle. If the member supplies a `shoe_size` at booking (for example 8.5), the reservation's `shoe_status` starts at `RESERVED` and its `shoe_fee_cents` is snapshotted from the shoe-rental fee of 500 cents; if no `shoe_size` is given the `shoe_status` is `NONE` and `shoe_fee_cents` is zero. The shoe lifecycle is settled independently of attendance. An instructor returns a rented shoe, moving `shoe_status` from `RESERVED` to `RETURNED`; a return is allowed only when the shoe is `RESERVED` and the owning reservation's attendance is `ATTENDED`, and a return against a reservation that is not attended is rejected with `ERR_PARENT_RESERVATION_NOT_ATTENDED`. A shoe that was `RESERVED` is `FORFEITED` automatically when its reservation becomes a no-show or a late cancellation, and in that case the `shoe_fee_cents` is retained rather than refunded. The terminal shoe states are `RETURNED` and `FORFEITED`.

### 3.8. Penalties, Waivers, the Wallet, and Reinstatement

Every late cancellation and every no-show produces a **penalty charge** against the offending member. Each charge records its `member_id`, the `reservation_id` that triggered it, a `kind` of either `LATE_CANCEL` or `NO_SHOW`, the `amount_cents` snapshotted from the studio's corresponding fee field at charge time, a `counts_as_strike` flag (true by default), a `waived` flag (false until a manager waives it), and a `charged_at` instant from the logical clock. The strike-window arithmetic of Section 2.9 reads these rows.

A manager may **waive** a penalty charge. Waiving sets the charge's `waived` to true, credits the member's `wallet_credit_cents` by the charge's `amount_cents`, and recomputes the member's `active_strike_count` so the waived charge no longer counts. Waiving does not by itself reinstate a suspended member: if the member was suspended and the waiver drops the count below the threshold, the member nonetheless stays `SUSPENDED` until an explicit reinstatement. Reinstatement is a separate manager action that moves a `SUSPENDED` member back to `ACTIVE`; it lifts the suspension as a manager override without erasing the underlying strikes.

The member **wallet** (`wallet_credit_cents`) is a refundable monetary balance in cents. It is credited by waived penalty fees and by pack refunds, and debited by retail purchases that draw from it. It starts at zero on registration.

### 3.9. Pack Refunds

A manager may refund a credit pack to the member's wallet. A refund is permitted while the pack is `ACTIVE`, `EXHAUSTED`, or `EXPIRED`, provided no reservation currently in `BOOKED` attendance is still charged to the pack (all holds must be resolved first); a refund of a pack already `REFUNDED`, or one with unresolved holds, is rejected as an invalid state transition with `ERR_INVALID_STATE`. The refund request must carry `expected_pack_version`, and a mismatch with the pack's current `version` is rejected with `ERR_STALE_PACK_VERSION` as described in Section 2.10. A successful refund credits the computed amount to the member's `wallet_credit_cents`, moves the pack to `REFUNDED` (terminal), and increments the pack's `version`.

The **refund amount** depends on the pack kind, and the two kinds deliberately use different algorithms that can yield different cents for otherwise comparable packs. For a `CLASS_PACK` the refund is *unused-value* based and ignores elapsed time: the per-credit value is the pack's `price_cents` divided by its `purchased_credits`, rounded half-up to whole cents, and the refund is that per-credit value multiplied by the pack's remaining credits, where remaining credits are recomputed at refund time as purchased minus consumed. For a `MEMBERSHIP` the refund is *time-prorated* and ignores any credit count: the total days are the number of days between the pack's `activated_at` and its `expires_at` (counting the start day and excluding the end day); the used days are the number of days between `activated_at` and the current clock instant, clamped to lie between zero and the total days; the unused days are the total days minus the used days; and the refund is the pack's `price_cents` multiplied by unused days divided by total days, rounded half-up to whole cents. Regardless of kind, if the pack is `EXPIRED` at refund time the refund amount is zero.

### 3.10. The Retail Counter

A manager stocks the studio's retail counter with products, each carrying a `sku` unique within its studio, a `name`, a `unit_price_cents`, and a `stock_qty` of at least zero. A product's `status` is `AVAILABLE` on creation and may be moved to `DISCONTINUED` by a manager, after which future orders against it are rejected with `ERR_PRODUCT_DISCONTINUED`.

A member places a retail order naming the `member_id`, the `studio_id`, the `product_id`, the `quantity` (at least one), and an optional `pay_from_wallet` flag (default false). The product must belong to the named studio. The order is refused if the product is `DISCONTINUED`, and refused with `ERR_INSUFFICIENT_STOCK` if the requested quantity exceeds the product's `stock_qty`. On success the order records a `subtotal_cents` (the pre-discount value), a `wallet_applied_cents`, a `card_charged_cents`, and a `status` of `PLACED` (the only value in this version), and the product's `stock_qty` is reduced by the ordered quantity.

The **order total** is computed in fixed steps. The `subtotal_cents` is the quantity multiplied by the product's `unit_price_cents`. A volume discount is then chosen by quantity and applied once to the whole subtotal (not per unit): a quantity of fewer than 3 units earns no discount; a quantity of at least 3 but fewer than 6 units earns a 5 percent discount; a quantity of 6 or more units earns a 10 percent discount. The discounted total is the subtotal minus the discount, where the discount is the subtotal multiplied by the chosen percentage and rounded half-up to whole cents. Payment is then split: if `pay_from_wallet` is true, the `wallet_applied_cents` is the smaller of the member's `wallet_credit_cents` and the discounted total, and the `card_charged_cents` is the discounted total minus that wallet portion; if `pay_from_wallet` is false, `wallet_applied_cents` is zero and the whole discounted total is charged to card. When the wallet is drawn upon, the member's `wallet_credit_cents` is reduced by `wallet_applied_cents`. Note that `subtotal_cents` is stored as the pre-discount figure, while the actual amount collected is the sum of the wallet and card portions.

### 3.11. Reading Resources and the Logical Clock

All resources are individually retrievable and listable, and computed fields reflect the clock at read time. Reading a member recomputes the `active_strike_count` against the current clock so that aged-out strikes are not counted. Reading a credit pack lazily transitions it to `EXPIRED` if the clock has reached or passed its `expires_at`. List endpoints accept optional filters that narrow results by foreign key — sessions by `studio_id`, `room_id`, or `instructor_id`; members by `home_studio_id`; credit packs by `member_id`; reservations by `session_id`, `member_id`, `bike_id`, or `credit_pack_id`; waitlist entries by `session_id`, `member_id`, `credit_pack_id`, or `promoted_reservation_id`; products by `studio_id`; retail orders by `member_id`, `studio_id`, or `product_id`; and penalty charges by `member_id` or `reservation_id` — each alongside the standard `limit` and `offset`. The manager-only logical-clock capability accepts a target instant in `to_iso8601` and returns the new `now_utc`; advancing it lazily expires packs whose `expires_at` has been reached on their next read.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including state transitions, cancellations, completions, refunds, waivers, and the logical-clock setter — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studios` | Create a studio | StudioManager |
| GET | `/studios/{studio_id}` | Get a studio | StudioManager, Member, Instructor |
| GET | `/studios` | List studios | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/rooms` | Create a room in a studio | StudioManager |
| GET | `/rooms/{room_id}` | Get a room | StudioManager, Member, Instructor |
| GET | `/studios/{id}/rooms` | List rooms in a studio | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/rooms/{room_id}/bikes` | Add a bike to a room's seat map | StudioManager |
| GET | `/rooms/{id}/bikes` | List bikes in a room | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/rooms/{room_id}/bikes/{bike_id}/retire` | Retire a bike | StudioManager |
| POST | `/instructors` | Register an instructor | StudioManager |
| POST | `/studios/{studio_id}/sessions` | Schedule a class session | StudioManager |
| GET | `/sessions/{session_id}` | Get a session | StudioManager, Member, Instructor |
| GET | `/sessions` | List sessions | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/sessions/{session_id}/cancel` | Studio cancels a session | StudioManager |
| POST | `/studios/{studio_id}/sessions/{session_id}/complete` | Mark a session completed | StudioManager |
| POST | `/members/register` | Register a member | Anonymous |
| GET | `/members/{member_id}` | Get a member | StudioManager, Member |
| GET | `/members` | List members | StudioManager |
| POST | `/members/{member_id}/reinstate` | Lift a member suspension | StudioManager |
| POST | `/credit-packs` | Purchase a class-pack or membership | StudioManager, Member |
| GET | `/credit-packs/{pack_id}` | Get a credit pack | StudioManager, Member |
| GET | `/credit-packs` | List credit packs | StudioManager, Member |
| POST | `/credit-packs/{pack_id}/refund` | Refund a pack to member wallet | StudioManager |
| POST | `/studios/{studio_id}/sessions/{session_id}/reservations` | Book a specific bike on a session | Member |
| GET | `/reservations/{reservation_id}` | Get a reservation | StudioManager, Member, Instructor |
| GET | `/reservations` | List reservations | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/sessions/{session_id}/reservations/{reservation_id}/cancel` | Member cancels a booking | Member |
| POST | `/studios/{studio_id}/sessions/{session_id}/reservations/{reservation_id}/check-in` | Instructor checks a member in | Instructor |
| POST | `/reservations/{reservation_id}/return-shoe` | Return a rented shoe | Instructor |
| POST | `/studios/{studio_id}/sessions/{session_id}/waitlist` | Join the waitlist for a full session | Member |
| GET | `/waitlist-entries/{entry_id}` | Get a waitlist entry | StudioManager, Member, Instructor |
| GET | `/waitlist-entries` | List waitlist entries | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/sessions/{session_id}/waitlist/{entry_id}/leave` | Member leaves the waitlist | Member |
| POST | `/studios/{studio_id}/products` | Create a retail product | StudioManager |
| GET | `/products/{product_id}` | Get a product | StudioManager, Member, Instructor |
| GET | `/products` | List products | StudioManager, Member, Instructor |
| POST | `/studios/{studio_id}/products/{product_id}/discontinue` | Discontinue a product | StudioManager |
| POST | `/retail-orders` | Place a retail order | Member |
| GET | `/retail-orders/{order_id}` | Get a retail order | StudioManager, Member |
| GET | `/retail-orders` | List retail orders | StudioManager, Member |
| GET | `/penalty-charges/{charge_id}` | Get a penalty charge | StudioManager, Member |
| GET | `/penalty-charges` | List penalty charges | StudioManager, Member |
| POST | `/penalty-charges/{charge_id}/waive` | Waive a penalty charge | StudioManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_PACK_VERSION` | 412 |
| `ERR_MEMBER_SUSPENDED` | 403 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_BIKE_UNAVAILABLE` | 409 |
| `ERR_DUPLICATE_RESERVATION` | 409 |
| `ERR_NO_CHARGEABLE_PACK` | 402 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_WAITLIST_FULL` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_WINDOW_CLOSED` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_SESSION_NOT_FULL` | 409 |
| `ERR_PARENT_RESERVATION_NOT_ATTENDED` | 409 |
