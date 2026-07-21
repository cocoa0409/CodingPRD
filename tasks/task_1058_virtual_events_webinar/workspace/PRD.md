# Virtual-Events & Webinar Platform API — Product Requirements Document

## 1. Introduction

Running a virtual conference is, operationally, four businesses stacked on top of each other. There is a ticketing business that must price seats correctly at the moment of purchase and then re-price them honestly once the truth is known. There is a broadcast business that must schedule rooms, secure speakers, push pixels, and turn live streams into on-demand assets. There is a sponsorship business that sells virtual booths, captures leads, and scores them. And there is a billing business that has to reconcile all of it into invoices that two different finance operators must independently touch before money moves.

This document specifies the REST API that unifies those four businesses behind a single domain model. The platform is mounted under `/api`, and every resource in it hangs, directly or transitively, off an **Event**. Organizers assemble an event's programme — ticket types, tracks, sessions, speakers, sponsors — while the event sits in draft. Publishing opens the doors to registration. Starting the event lights up the booths and permits check-in. Ending it resolves every attendee's attendance from observed watch minutes. Settlement closes the books, and — critically — it re-derives ticket prices from facts the platform actually observed rather than from claims made at registration time.

Two things make this domain unusually demanding, and the specification below returns to both repeatedly. First, **time is geometry, and there are three incompatible geometries in play**: sessions occupy half-open slots on a track, accepted speaking engagements occupy buffered windows on a speaker's personal calendar, and networking meetings occupy closed intervals on an attendee's calendar. A boundary that is legal in one geometry is illegal in another. Second, **a registration advances along two independent axes at once** — what the attendee has paid, and whether the attendee showed up — and neither axis gates the other. Implementers who collapse these into a single status field will fail in ways that are hard to see and expensive to unwind.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors and Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is absent, or if `X-User-Role` is not one of the six role names enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check runs before anything else the platform does — before the URL is resolved, before the body is parsed, before any state is inspected.

The six roles are `PlatformAdmin`, `Organizer`, `FinanceAdmin`, `Attendee`, `SpeakerUser`, and `SponsorUser`. Once the caller is authenticated, the platform checks whether the acting role is among those authorised for the specific endpoint being called; if it is not, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Section 4 records the authorised role set for each endpoint.

Three roles are **entity-backed**, meaning `X-User-ID` is the identifier of a real persisted row and ownership is decided by comparing that identifier against a foreign key on the target resource:

- When `X-User-Role` is `Attendee`, `X-User-ID` is the `id` of the acting `Registration`; ownership checks on any resource that references a `Registration` compare the resource's registration foreign-key field to `X-User-ID`.
- When `X-User-Role` is `SpeakerUser`, `X-User-ID` is the `id` of the acting `Speaker`; ownership checks on a session-speaker junction row compare that row's `speaker_id` to `X-User-ID`.
- When `X-User-Role` is `SponsorUser`, `X-User-ID` is the `id` of the acting `Sponsor`; ownership checks on a booth compare the booth's `sponsor_id` to `X-User-ID`.

The other three roles are **opaque**, meaning `X-User-ID` is an operator identifier that is not the primary key of any persisted entity:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The platform admin controls the logical clock and the media-processing pipeline, and the server does not compare this identifier to any entity's `id`.
- When `X-User-Role` is `Organizer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, but the server does record it: the identifier of whoever creates an event is stored as that event's `organizer_user_id`, and every subsequent organizer action on that event's graph compares the acting `X-User-ID` to the stored `organizer_user_id`.
- When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `issued_by_user_id` when a settlement is issued and as `paid_by_user_id` when a settlement is marked paid, and it compares those two recorded values to each other — never to an entity's `id`.

An entity-backed role acting on a resource it does not own, or an `Organizer` acting on an event whose `organizer_user_id` differs from the acting `X-User-ID`, is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership test applies to every mutating endpoint acted on by `Organizer`, `Attendee`, `SpeakerUser` or `SponsorUser`.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest accepted value is 100. A `limit` outside that inclusive range is a validation failure and yields `ERR_VALIDATION` (HTTP 400). When `offset` is omitted it defaults to 0, counting from the first matching row.

List results are ordered by `created_at` ascending, oldest first, unless a specific endpoint's narrative states otherwise. The `meta` block of a list response carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` indicating whether any matching rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and Versioning

Every persisted resource on this platform carries four common properties. The `id` is a server-minted UUID string with no type prefix — an event's identifier and a lead's identifier are indistinguishable by shape, and clients must never parse meaning out of them. The `created_at` timestamp records the instant the row was first written and is never modified afterwards. The `updated_at` timestamp records the instant of the most recent mutation to the row, and `version` is an integer that starts at 1 when the row is created and increases by one on every mutation of that row. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional-second digits. All fourteen entity types on this platform — events, ticket types, registrations, tracks, sessions, speakers, session-speaker junction rows, broadcasts, recordings, sponsors, booths, leads, match requests and settlements — carry the full set of four.

The `version` field on an `Event` deserves particular attention because it is the platform's concurrency token, and a great many operations touch it even when they appear to be about something else entirely. Creating a ticket type under an event, creating a registration, taking payment on a registration, refunding one, withdrawing one, ending a broadcast, cancelling the event, publishing it, starting it, ending it, patching its mutable attributes, creating an EVENT settlement, and issuing an EVENT settlement all increment the owning event's `version` by one. Operations elsewhere in the graph that the event's counters do not track — creating a track, creating a session, scheduling a session, inviting a speaker, submitting a booth — do not.

### 2.5. The Logical Clock

Time on this platform is not wall-clock time. The server maintains a **logical clock** whose value is read by every deadline, expiry, early-bird and duration computation described in this document. Before any client sets it, the logical clock reads exactly `2026-07-01T00:00:00Z`; it never falls back to the host machine's real time, and it never advances on its own. A platform operator moves it by supplying a `to_iso8601` instant, and the response echoes the new value as `current_utc`. Every computation performed after that call uses the new instant.

This matters because early-bird eligibility, match-request expiry, broadcast duration and settlement arithmetic are all clock-sensitive, and the platform must be deterministic under test. When this document says "the current logical clock", it means the value described here and nothing else.

### 2.6. Path Resolution, Foreign Keys and Nested Reads

URLs on this platform are hierarchical, and path segments are resolved strictly left to right. A request against a ticket type nested under an event resolves the event first; if no event bears that identifier the request fails with `ERR_EVENT_NOT_FOUND` (HTTP 404) and the ticket type is never looked up. Only once every ancestor segment has resolved does the platform look up the leaf. Each entity type has its own not-found code: `ERR_EVENT_NOT_FOUND`, `ERR_TICKET_TYPE_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_TRACK_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SPEAKER_NOT_FOUND`, `ERR_SESSION_SPEAKER_NOT_FOUND`, `ERR_BROADCAST_NOT_FOUND`, `ERR_RECORDING_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`, `ERR_MATCH_REQUEST_NOT_FOUND` and `ERR_SETTLEMENT_NOT_FOUND`, each carrying HTTP 404. The path variables that drive this resolution are `event_id`, `ticket_type_id`, `registration_id`, `track_id`, `session_id`, `speaker_id`, `session_speaker_id`, `broadcast_id`, `recording_id`, `sponsor_id`, `booth_id`, `lead_id`, `match_request_id` and `settlement_id`.

Identifiers supplied in a request **body** are resolved the same way, but in the order the fields are listed for that operation. Registration creation, session creation, speaker invitation, broadcast creation, booth creation, lead capture and match-request creation all carry foreign keys in their payloads, and each resolves them in declared order, emitting the corresponding not-found code for the first one that misses.

Some collections are reachable by two routes: nested beneath their parent, and as a flat filtered collection. Ticket types, tracks, speakers and sponsors are all readable either under their owning event or from a top-level collection filtered by `event_id`. The two routes return the same rows in the same order.

### 2.7. Rule Precedence

Many operations on this platform are guarded by several checks at once, and when more than one would fail the caller must receive a **predictable** error rather than whichever check the implementation happened to reach first. Checks are therefore evaluated in a fixed order, and the first failure is returned:

1. Authentication — headers present and role recognised (`ERR_UNAUTHENTICATED`).
2. Endpoint authorisation — the acting role appears in the endpoint's role list (`ERR_UNAUTHORIZED`).
3. Path-segment existence, left to right (the not-found codes above).
4. Body foreign-key existence, in field order (the not-found codes above).
5. Resource ownership for entity-backed and organizer-owned resources (`ERR_NOT_RESOURCE_OWNER`).
6. Body shape — required fields present, types correct, enum values inside their declared sets, integers respecting their minimums, and `limit` within 1 to 100 (`ERR_VALIDATION`).
7. Interval well-formedness — an event's `ends_at` must be strictly after its `starts_at`, a session's `ends_at` strictly after its `starts_at`, and a match request's `window_end` strictly after its `window_start`; otherwise `ERR_TIME_RANGE_INVALID` (HTTP 422). This applies to event creation, session creation and match-request creation.
8. Duplicate-registration detection (`ERR_DUPLICATE_REGISTRATION`).
9. The stale-version check on EVENT settlement creation (`ERR_STALE_EVENT_VERSION`).
10. Declared-transition check (`ERR_INVALID_STATE`), then terminal-state check (`ERR_ALREADY_TERMINAL`), on every state-transition endpoint.
11. The registration window gate (`ERR_EVENT_NOT_OPEN`).
12. Safety rules — segregation of duties, marketing consent, and on-demand gating.
13. Referential consistency rules — cross-event mismatch, unsigned contract, self-match, duplicate lead.
14. Temporal geometry rules — track slot conflict, speaker buffer conflict, meeting window conflict, and match-request expiry.
15. Settlement uniqueness (`ERR_SETTLEMENT_EXISTS`).
16. Fiscal rules — ticket sold out, event capacity exceeded, and payment amount mismatch.

Two consequences of this ordering are worth stating outright because they are easy to get backwards. A registration attempt against an event still in `DRAFT` whose chosen ticket type is *already* at quota fails with `ERR_EVENT_NOT_OPEN`, not `ERR_TICKET_SOLD_OUT` — the registration-window gate sits above the fiscal rules. And a lead capture that both lacks marketing consent *and* names a registration belonging to a different event fails with `ERR_CONSENT_REQUIRED`, not `ERR_REGISTRATION_EVENT_MISMATCH` — the safety rule sits above the referential rule.

### 2.8. Money, Scores and Rounding

Every monetary quantity on this platform is an integer number of cents. There are no floating-point amounts in any stored field or any response body. Where a percentage or a fractional unit rate enters a computation, the result is converted back to whole cents by **rounding half up** — that is, to the nearest integer cent, with exact halves rounded away from zero.

The number of times rounding occurs, and precisely where in a formula it occurs, is part of the contract and not an implementation detail. Each calculation described in Section 3 states its rounding points explicitly, and summing unrounded intermediate values before a single final rounding will produce different answers than the specification requires. Lead scores follow the same discipline: the weighted sum is rounded half up exactly once, before any cap is applied. The only non-integer quantity anywhere in the API is the average watch minutes reported by the analytics snapshot, which is carried to two decimal places, rounded half up.

### 2.9. Optimistic Concurrency on the Event Aggregate

Creating an EVENT settlement is the one write on this platform that is guarded by optimistic concurrency control, and it is guarded because that write is destructive: a new EVENT settlement supersedes any prior `DRAFT` EVENT settlement on the same event by voiding it. A client that has not seen the event's latest state must not be permitted to throw away a draft it never observed.

The create-EVENT-settlement request therefore requires `expected_event_version` as a mandatory, non-optional field carrying the client's last observed `version` of the target `Event`. If that value does not equal the event's current `version`, the request is rejected with `ERR_STALE_EVENT_VERSION` and HTTP 412, and nothing is written — no settlement row, no re-derived registration amounts, no supersede. The client must re-read the event and retry with the fresh value. No other endpoint on this platform takes a version field, and none other performs a stale-version check.

### 2.10. Three Interval Geometries

The platform reasons about overlapping time windows in three places, and the three use deliberately different inclusivity rules. Confusing them is the single most common source of subtle failure in this domain.

**Track slots are half-open.** A session, once scheduled, occupies the interval that begins at its `starts_at` (inclusive) and runs up to but not including its `ends_at`. Two sessions on the same track conflict when the new session's `starts_at` is strictly earlier than the other session's `ends_at` **and** the other session's `starts_at` is strictly earlier than the new session's `ends_at`. Zero-gap adjacency — a session starting at the exact instant another one ends — is therefore permitted.

**Speaker calendars are buffered.** An accepted speaking engagement blocks not only its own session window but a transition margin of ten minutes on each side, because a human speaker cannot appear in two rooms back to back. A new engagement conflicts with an existing accepted one when the new session's `starts_at` is strictly earlier than the other session's `ends_at` extended forward by ten minutes **and** the other session's `starts_at` is strictly earlier than the new session's `ends_at` extended forward by ten minutes. Because both comparisons are strict, a gap of exactly ten minutes between two sessions is accepted.

**Meeting windows are closed.** A networking meeting occupies the interval from its `window_start` through its `window_end`, both endpoints included. Two accepted meetings for the same participant conflict when the new meeting's `window_start` is at or before the other's `window_end` **and** the other's `window_start` is at or before the new meeting's `window_end`. Because the interval is closed, meetings that merely touch at an endpoint — one ending exactly when the other begins — **do** conflict. Each registration may hold at most one accepted meeting at any given instant.

### 2.11. Conservation Invariants and Cascades

Two quantities on this platform are conserved, and the platform's correctness is judged against them.

**Seat inventory.** A ticket type's `sold_count` is always equal to the number of registrations on that ticket type whose `attendance_status` is neither `WAITLISTED` nor `WITHDRAWN`, and an event's `registered_count` is the same count taken across all of the event's ticket types. Creating a seat-holding registration is the forward action; withdrawing it is the compensating action; after a create followed by a withdraw, both counters return to exactly the values they held before.

**Collected money.** An event's `gross_collected_cents` is always equal to the sum of `amount_paid_cents` across the event's registrations whose `payment_status` is `PAID`. Taking payment is the forward action and issuing a refund is the compensating action; after a payment followed by a refund, `gross_collected_cents` returns to exactly its pre-payment value and the registration's `amount_paid_cents` is zero, leaving no drift.

Beyond these invariants, two multi-link cascades run through the entity graph. Cancelling an event drives sessions, then their broadcasts, then those broadcasts' recordings. Refunding a registration drives money and seat release, then ticket availability, then waitlist promotion. Both chains are described in full where their originating operations are specified, and both run to completion within the single request that triggers them — this platform has no deferred or eventually-consistent propagation.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Event

An `Organizer` opens the workflow by creating an event, supplying its public `name`, an IANA `timezone` label, the window bounded by `starts_at` and `ends_at`, the instant `early_bird_ends_at` at which promotional pricing stops applying, and a `capacity` of at least one. The `timezone` is a display hint only — every timestamp the platform stores and returns is UTC. The new event lands in `DRAFT`, its `organizer_user_id` is stamped with the acting `X-User-ID`, and its `version` begins at 1. Its counters all begin at zero: `registered_count`, `gross_collected_cents`, `streamed_minutes_total`, `published_recording_count` and `settlement_adjustment_cents`.

While the event remains in `DRAFT` or `PUBLISHED`, the organizer may amend its `name`, its `capacity`, or its `early_bird_ends_at`; any such amendment advances the event's `version`. Reading a single event returns the `version` a client needs for the settlement concurrency check along with every computed counter, and that read is open to all six roles. Listing events is restricted to `Organizer`, `PlatformAdmin` and `FinanceAdmin`, and supports filtering by `state` and by `organizer_user_id`.

The event's lifecycle runs `DRAFT → PUBLISHED → LIVE → ENDED → SETTLED`, with `CANCELLED` reachable from the first three. `SETTLED` and `CANCELLED` are both terminal. Publishing is permitted only from `DRAFT`, only by the owning organizer, and only when the event already has at least one ticket type defined — an event with no tickets has nothing to sell, and the attempt is refused with `ERR_INVALID_STATE`. Publishing is what opens the registration gate described in Section 3.3, and it bumps the event's `version`.

Starting the event moves it `PUBLISHED → LIVE` and carries a side effect into the sponsorship graph: every booth of this event sitting in `APPROVED` is promoted to `LIVE` in the same operation. The event's `version` advances. Ending the event moves it `LIVE → ENDED`, but only when no broadcast belonging to any of this event's sessions is still in `PREVIEW` or `LIVE`; a stream still on air blocks the close with `ERR_INVALID_STATE`. Ending is also the moment attendance is resolved for the whole audience, as Section 3.3 describes, and it too advances `version`.

Cancellation is available from `DRAFT`, `PUBLISHED` or `LIVE`, is restricted to the owning organizer, and accepts a `reason` for the audit record. From `DRAFT` the effect is modest: every session of the event in `DRAFT`, `SCHEDULED` or `LIVE` becomes `CANCELLED`. From `PUBLISHED` or `LIVE` the same first link fires and then propagates two links further. Every broadcast belonging to one of those newly cancelled sessions and sitting in `SCHEDULED`, `PREVIEW` or `LIVE` becomes `ABORTED`. Then, because those broadcasts aborted, every recording they produced that sits in `PENDING`, `PROCESSING`, `READY` or `PUBLISHED` becomes `RETRACTED`, and for each such recording that had been `PUBLISHED`, the event's `published_recording_count` is decremented by one. Registrations that have already been paid keep their `payment_status` of `PAID` — cancelling an event does not automatically refund anyone, and refunds must be issued explicitly. Cancellation advances the event's `version`.

### 3.2. Ticket Types and Seat Availability

Under each event the organizer defines one or more ticket types, each with a `name`, a `tier` drawn from `GENERAL`, `VIP`, `SPONSOR` and `SPEAKER`, a `price_cents` list price of zero or more, a `quota` of at least one seat, and a `gating_level` of `LIVE_ONLY`, `ON_DEMAND` or `BOTH` describing which consumption channels a holder unlocks. A new ticket type starts with `sold_count` at zero and `availability_status` at `AVAILABLE`, and creating one advances the owning event's `version`.

Availability is derived, never set by hand. After every mutation of a ticket type's `sold_count` — registration creation, withdrawal, the refund cascade, and waitlist promotion all qualify — the platform recomputes the number of seats still free as the `quota` less the `sold_count`. When that figure is zero or less, `availability_status` becomes `SOLD_OUT`; otherwise it is `AVAILABLE`. The boundary is exact: the seat that takes `sold_count` up to `quota` succeeds and flips the type to `SOLD_OUT`, and the next seat request is the one that is refused.

Ticket types are readable individually, listed beneath their owning event, or listed from the flat collection with filters on `event_id`, `tier` and `availability_status`. All of those reads are available to `Organizer`, `PlatformAdmin`, `Attendee` and `FinanceAdmin`.

### 3.3. Registration: Two Independent Axes

A registration is created by an `Organizer` on behalf of an attendee, naming the `event_id` and `ticket_type_id`, the `attendee_email`, and optionally a `group_code` shared with co-registering colleagues, a claimed `group_size` of at least one (defaulting to 1), and a `waitlist_if_full` flag. The registration is refused unless the event is in `PUBLISHED`; in `DRAFT`, `LIVE`, `ENDED`, `SETTLED` and `CANCELLED` the door is shut and the attempt yields `ERR_EVENT_NOT_OPEN`. The `attendee_email` must be unique among registrations of the same event whose `attendance_status` is not `WITHDRAWN`; a collision is `ERR_DUPLICATE_REGISTRATION`.

Two capacity gates then apply. If the chosen ticket type's `sold_count` has reached its `quota`, the request is refused with `ERR_TICKET_SOLD_OUT`; if the event's `registered_count` has reached its `capacity`, it is refused with `ERR_EVENT_CAPACITY_EXCEEDED`. Both refusals are conditional on `waitlist_if_full` being anything other than true. When `waitlist_if_full` **is** true, neither gate rejects: instead the row is created with `attendance_status` of `WAITLISTED` and `amount_due_cents` of zero, it does not consume a seat, and it does not advance `sold_count` or `registered_count`. A seat-holding registration, by contrast, increments both counters, triggers the availability recomputation, and has its `amount_due_cents` written by the provisional pricing pass. Registration creation advances the owning event's `version` either way.

Every registration advances along **two independent axes**. The `payment_status` axis runs `UNPAID → PAID → REFUNDED` and begins at `UNPAID`. The `attendance_status` axis runs `WAITLISTED → REGISTERED → CHECKED_IN → ATTENDED` or `CHECKED_IN → NO_SHOW`, with `WITHDRAWN` reachable from `WAITLISTED`, `REGISTERED` or `CHECKED_IN`, and begins at `REGISTERED` for seat-holding rows. The axes do not gate each other: an attendee may be checked in while still `UNPAID`, and taking payment leaves `attendance_status` untouched. `WITHDRAWN`, `ATTENDED` and `NO_SHOW` are the terminal outcomes.

Check-in moves a registration `REGISTERED → CHECKED_IN` and is permitted only while the owning event is `LIVE`. Once checked in, a registration accumulates live viewing time: an organizer reports watch time against a specific session by supplying the `registration_id` and the `watched_minutes` observed, and that figure is **added to** the registration's running `watched_minutes` total rather than replacing it.

When the organizer ends the event, every outstanding registration is resolved in one sweep. A registration still in `REGISTERED` — someone who bought a seat and never appeared — becomes `NO_SHOW`. A registration in `CHECKED_IN` whose accumulated `watched_minutes` is at least fifteen becomes `ATTENDED`; one whose `watched_minutes` is below fifteen becomes `NO_SHOW`. Fifteen minutes of viewing is the platform's definition of genuine attendance, and it is the line the analytics snapshot and the ended-event sweep both draw.

Withdrawal is available to the owning `Attendee` acting on their own registration, and to the `Organizer`, from `WAITLISTED`, `REGISTERED` or `CHECKED_IN`. When the prior `attendance_status` was anything other than `WAITLISTED`, the withdrawal releases the seat: the ticket type's `sold_count` and the event's `registered_count` each drop by one and `availability_status` is recomputed. A withdrawal out of `WAITLISTED` releases nothing, because a waitlisted row never held a seat. In both cases, every match request of that registration still sitting in `PENDING` becomes `CANCELLED`. Withdrawal advances the event's `version`.

Registrations are readable individually by `Organizer`, `PlatformAdmin`, `FinanceAdmin` and the owning `Attendee`, and listable by the first three with filters on `event_id`, `ticket_type_id`, `group_code`, `payment_status` and `attendance_status`.

### 3.4. Pricing a Seat — Twice

Every seat on this platform is priced twice with the same seven-step formula, run once provisionally at registration and once definitively at settlement. What differs between the two runs is not the arithmetic but the two inputs the arithmetic consumes: the clock against which early-bird eligibility is judged, and the group size that qualifies for the group discount.

The seven steps run in order. **First**, the list price starts as the ticket type's `price_cents`, and when the ticket type's `tier` is `VIP` a surcharge of 5,000 cents — fifty dollars — is added to it. **Second**, an early-bird component of twenty percent applies when the pricing clock falls strictly before the event's `early_bird_ends_at`, and is zero otherwise; a purchase made at the exact cut-off instant is too late. **Third**, a group component of ten percent applies when the effective group size is at least five, and is zero otherwise. **Fourth**, the two components are added together and the sum is capped at twenty-five percent, so a purchase qualifying for both discounts receives twenty-five percent rather than thirty. **Fifth**, the list price is multiplied by one minus that capped discount fraction and the product is rounded half up to a whole cent — this is the first of the formula's two roundings. **Sixth**, a processing fee is taken as three percent of that discounted amount, rounded half up to a whole cent, and then clamped so that it is never below 100 cents and never above 2,500 cents — this is the second and last rounding. **Seventh**, the amount owed is the discounted amount plus the clamped processing fee. The sum itself is never rounded again.

The **provisional** run happens when a seat-holding registration is created and again when a waitlisted registration is promoted. Its pricing clock is the current logical clock at the moment of the call, and its effective group size is simply the `group_size` the registrant claimed in the request, defaulting to one. The claim is taken on trust and checked against nothing. The result is written to `amount_due_cents`.

The **final** run happens during EVENT settlement creation, for every registration of the event whose `payment_status` is `PAID`. Its pricing clock is the registration's own `created_at`, so early-bird eligibility is judged by when the attendee actually registered rather than by when finance got round to invoicing. Its effective group size is the **observed** number of registrations on the same event that share the same non-null `group_code` and whose `payment_status` is `PAID`; when the registration's `group_code` is null the observed size is one. The result is written to `final_amount_due_cents`, which is null until settlement runs. A registrant who claimed a group of five or more but whose colleagues never materialised — or never paid — therefore ends up with a `final_amount_due_cents` strictly greater than the `amount_due_cents` they were originally charged, and that difference is exactly what the settlement adjustment captures.

### 3.5. Collecting and Returning Money

Payment is recorded by the `Organizer` against a registration whose `payment_status` is `UNPAID`, whose `attendance_status` is neither `WITHDRAWN` nor `WAITLISTED`, and whose `amount_cents` submitted in the request equals the registration's `amount_due_cents` exactly. A figure that differs in either direction is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` — the platform never accepts partial or over-payment. On success, `payment_status` becomes `PAID`, `amount_paid_cents` is set to the submitted `amount_cents`, the event's `gross_collected_cents` grows by the same figure, and the event's `version` advances.

Refunding is the compensating action, available only from `payment_status` of `PAID` and accepting a `reason`. It sets `payment_status` to `REFUNDED` and then runs a three-link chain that reaches well beyond the row being refunded.

The **first link** unwinds the money and the seat together: the event's `gross_collected_cents` is reduced by the registration's `amount_paid_cents`, then `amount_paid_cents` is set to zero, and the registration's `attendance_status` transitions to `WITHDRAWN`, which in turn decrements the ticket type's `sold_count` by one and the event's `registered_count` by one.

The **second link** follows from that seat release: because `sold_count` has now fallen below `quota`, the availability recomputation flips the ticket type's `availability_status` from `SOLD_OUT` back to `AVAILABLE`.

The **third link** follows from the availability flip: the waitlisted registration on that same ticket type with the earliest `created_at` is promoted from `WAITLISTED` to `REGISTERED`, its `amount_due_cents` is written by the provisional pricing run evaluated at the current logical clock, and the ticket type's `sold_count` and the event's `registered_count` are each incremented back by one. Refunding, like paying, advances the event's `version`.

### 3.6. The Programme: Tracks, Sessions and Speakers

Tracks are the scheduling resource that sessions compete for — think of a track as a virtual room with a single door. An organizer creates one under an event with just a `name`, and it begins with `scheduled_session_count` at zero. Tracks are readable individually, beneath their event, or from a flat collection filtered by `event_id`, in all cases by `Organizer` and `PlatformAdmin` only.

Sessions are created against an `event_id` and a `track_id` with a `title`, a `starts_at` and `ends_at` pair, a `session_type` of `LIVE`, `SIMULIVE` or `ON_DEMAND`, and a `capacity` of at least one concurrent live viewer. A newly created session sits in `DRAFT` and occupies **no** track slot — it is a proposal, not a booking. Its `accepted_speaker_count` starts at zero.

Scheduling is what claims the slot. It moves the session `DRAFT → SCHEDULED`, requires the owning event to be in `DRAFT` or `PUBLISHED`, and enforces the half-open track geometry from Section 2.10 against every other session on the same `track_id` sitting in `SCHEDULED`, `LIVE` or `COMPLETED`. A conflict is refused with `ERR_TRACK_SLOT_CONFLICT`; a success increments the track's `scheduled_session_count`. Sessions are listable with filters on `event_id`, `track_id` and `state` and readable individually, by `Organizer`, `PlatformAdmin`, `Attendee` and `SpeakerUser`.

Speaker profiles are created under an event with a `full_name` and an `email` that is unique within that event, and each begins with `accepted_session_count` at zero and `engagement_status` at `UNASSIGNED`. A speaker's `engagement_status` is purely derived: it reads `ENGAGED` whenever `accepted_session_count` is one or more, and `UNASSIGNED` otherwise. Speakers are readable individually, beneath their event, or from a flat collection filtered by `event_id` and `engagement_status`, by `Organizer`, `PlatformAdmin` and `SpeakerUser`.

The junction between a session and a speaker is a first-class row carrying `session_id`, `speaker_id`, a `speaking_role` of `HOST`, `PANELIST` or `MODERATOR`, its own `state`, and an `invite_round` counter. An organizer creates one by inviting a speaker; the row lands in `INVITED` with `invite_round` at 1. The invitation lifecycle is deliberately **cyclic**: `INVITED → ACCEPTED → WITHDRAWN → INVITED` may repeat without bound, and `invite_round` records how many times the row has entered `INVITED`. `DECLINED` and `RELEASED` are terminal.

Only the invited `SpeakerUser` — the caller whose `X-User-ID` equals the row's `speaker_id` — may accept, decline or withdraw. Accepting moves the row `INVITED → ACCEPTED`, requires the owning session to be in `DRAFT` or `SCHEDULED`, and enforces the buffered speaker geometry of Section 2.10 against every other session for which this speaker already holds an `ACCEPTED` row; a clash is `ERR_SPEAKER_BUFFER_CONFLICT`. On success the speaker's `accepted_session_count` rises by one, and because that count is now at least one the speaker's `engagement_status` becomes `ENGAGED`; the session's `accepted_speaker_count` also rises by one. Declining moves the row `INVITED → DECLINED` and changes no counter at all.

Withdrawing moves the row `ACCEPTED → WITHDRAWN` and is refused once the session has reached `COMPLETED`. It reverses the acceptance exactly: the speaker's `accepted_session_count` falls by one, and because that count has fallen to zero the speaker's `engagement_status` returns to `UNASSIGNED`; the session's `accepted_speaker_count` falls by one. The organizer may then re-invite, moving the row `WITHDRAWN → INVITED` while the session is in `DRAFT` or `SCHEDULED`, which increments `invite_round` and changes nothing else. Junction rows are listable with filters on `session_id`, `speaker_id` and `state`.

Cancelling a session — whether requested directly with a `reason` or driven by the event-cancellation cascade — is permitted from `DRAFT`, `SCHEDULED` or `LIVE`. If the prior state was `SCHEDULED` or `LIVE`, the track's `scheduled_session_count` drops by one, releasing the slot. Every junction row of that session in `INVITED` or `ACCEPTED` moves to `RELEASED`; for rows that were `ACCEPTED`, the speaker's `accepted_session_count` falls by one with `engagement_status` recomputed, and the session's `accepted_speaker_count` falls by one, while rows that were merely `INVITED` change no counters. Every broadcast of that session in `SCHEDULED`, `PREVIEW` or `LIVE` moves to `ABORTED`.

### 3.7. Streaming: Broadcasts and the Recording Cycle

A broadcast is the streaming apparatus attached to a session. The organizer creates one against a `session_id` with an `ingest_region` of `US_EAST`, `US_WEST`, `EU_WEST` or `AP_SOUTH`, and it lands in `SCHEDULED` with `started_at`, `ended_at` both null and `streamed_minutes` at zero. Broadcasts run `SCHEDULED → PREVIEW → LIVE → ENDED`, with `ABORTED` reachable from the first three; `ENDED` and `ABORTED` are terminal. Broadcasts are readable individually and listable with filters on `session_id` and `state`, by `Organizer` and `PlatformAdmin`.

Entering preview moves the broadcast `SCHEDULED → PREVIEW` and requires the owning session to be `SCHEDULED`; it reserves the ingest slot and nothing more. Going live is the heavyweight step. It moves the broadcast `PREVIEW → LIVE` and demands three things at once: the owning session must still be `SCHEDULED`, the owning **event** must be `LIVE`, and the session must have at least one accepted speaker — that is, its `accepted_speaker_count` must be one or more. A failure on any of those three is `ERR_INVALID_STATE`. On success the broadcast's `started_at` is stamped with the current logical clock, the session transitions `SCHEDULED → LIVE`, and a recording row is created in `PENDING` with its `broadcast_id`, `session_id` and `event_id` all populated from the producing broadcast and its ancestors.

Ending the stream moves the broadcast `LIVE → ENDED`. Its `ended_at` is stamped with the current logical clock, and its `streamed_minutes` is computed as the elapsed time from `started_at` to `ended_at` expressed in whole minutes, discarding any remainder — a stream lasting fifty-nine seconds bills zero minutes. That figure is added to the owning event's `streamed_minutes_total`, the session transitions `LIVE → COMPLETED`, the broadcast's recording moves `PENDING → PROCESSING`, and the event's `version` advances. A broadcast that never reaches `ENDED` keeps `streamed_minutes` at zero.

Aborting a broadcast, with a `reason`, is available from `SCHEDULED`, `PREVIEW` or `LIVE`, and also arrives as a cascade from session cancellation. Every recording of that broadcast in `PENDING`, `PROCESSING`, `READY` or `PUBLISHED` moves to `RETRACTED`, and for each one that had been `PUBLISHED`, the event's `published_recording_count` drops by one.

Recordings themselves are never created by a client — they appear only as a consequence of a broadcast going live. Their lifecycle is `PENDING → PROCESSING → READY → PUBLISHED`, and it is **cyclic**: a `PUBLISHED` recording may be retracted and a `RETRACTED` one reprocessed, running `PUBLISHED → RETRACTED → PROCESSING → READY → PUBLISHED` as many times as needed. `DELETED` is the only terminal state.

A `PlatformAdmin` completes media processing, moving the recording `PROCESSING → READY` and supplying the encoded `duration_seconds`, which is written onto the row. The organizer then publishes it, moving it `READY → PUBLISHED`, but only when `duration_seconds` is greater than zero — a zero-length asset cannot be published. Publication takes a `gating_level` of either `ON_DEMAND` or `BOTH`, writes it onto the recording as the minimum ticket entitlement required to view the asset, and increments the event's `published_recording_count`. Retraction, taking a `reason`, moves the recording `PUBLISHED → RETRACTED`, decrements `published_recording_count`, and closes the asset to further viewing. A platform admin may reprocess a `RETRACTED` recording back to `PROCESSING`, which resets its `duration_seconds` to zero and starts the encode cycle over. Deletion is a soft operation available from `RETRACTED` or `READY`: the row moves to `DELETED` and thereafter is excluded from list results and answers individual reads with `ERR_RECORDING_NOT_FOUND`, unless a list request explicitly asks for the `DELETED` state. Recordings are listable with filters on `event_id`, `session_id`, `broadcast_id` and `state`.

On-demand consumption is gated. An `Attendee` registers a view by naming their `registration_id`, and two conditions must hold: the ticket type behind that registration must carry a `gating_level` of `ON_DEMAND` or `BOTH` — a `LIVE_ONLY` ticket buys no replay rights — and the registration's `payment_status` must be `PAID`. Either failure yields `ERR_GATING_NOT_PERMITTED` (HTTP 403). The named registration must also belong to the same event as the recording; a cross-event reference is `ERR_REGISTRATION_EVENT_MISMATCH` (HTTP 422). A permitted view increments the recording's `view_count` by one.

### 3.8. Sponsorship: Booths, Leads and Lead Scoring

Sponsors are registered against an event by the organizer with a company `name`, a `package_tier` of `BRONZE`, `SILVER` or `GOLD`, and a `contact_email`. A new sponsor's `contract_status` is `UNSIGNED`. Marking the contract signed — an organizer action recording who `signed_by` — flips `contract_status` to `SIGNED`, and that flip is the gate on booth approval. Sponsors are readable individually, beneath their event, or from a flat collection filtered by `event_id`, `package_tier` and `contract_status`.

A `SponsorUser` creates their own virtual booth by naming their `sponsor_id` and supplying a `headline` and a `lead_quota` of zero or more, which is the number of captured leads included in the sponsorship package. The booth's `event_id` is copied from the sponsor rather than supplied, and the row starts in `DRAFT` with `revision_round` at zero, `captured_lead_count` at zero and `stream_minutes_total` at zero.

Booth review is a **branching workflow with a revision loop**. The sponsor submits the booth from `DRAFT` or from `CHANGES_REQUESTED`, and either way the submission increments `revision_round` — so a booth that was drafted, submitted, sent back and resubmitted carries `revision_round` of 2. From `SUBMITTED` the organizer forks: approval moves the booth `SUBMITTED → APPROVED` and requires the owning sponsor's `contract_status` to be `SIGNED`, refusing otherwise with `ERR_CONTRACT_NOT_SIGNED`; requesting changes, with a `reason`, moves it `SUBMITTED → CHANGES_REQUESTED` and — unlike submission — leaves `revision_round` untouched, since the counter tracks submissions rather than review rounds. An `APPROVED` booth is promoted to `LIVE` automatically when the event starts. From `APPROVED` or `LIVE` the organizer may suspend the booth with a `reason`, moving it to the terminal `SUSPENDED` state, after which no further lead capture is accepted. Booths are readable individually and listable with filters on `sponsor_id`, `event_id` and `state`.

Sponsors also report their booth video consumption: a sponsor user posts the `minutes` consumed, and that figure is added to the booth's running `stream_minutes_total`, which is billed on the sponsorship invoice.

Lead capture is an `Attendee` action against a booth, naming the `registration_id` and a `marketing_consent` flag. Consent is mandatory — a capture attempted with `marketing_consent` false is refused with `ERR_CONSENT_REQUIRED` (HTTP 422), and that refusal takes precedence over the cross-event check. The named registration must belong to the same event as the booth, or the capture fails with `ERR_REGISTRATION_EVENT_MISMATCH`. No two leads may share the same `booth_id` and `registration_id` pair; a repeat capture is `ERR_DUPLICATE_LEAD` (HTTP 409). A successful capture creates the lead with its `event_id` denormalised from the booth, `booth_visits` at 1, `doc_downloads` at 0, increments the booth's `captured_lead_count`, and scores the lead immediately.

**Lead scoring** runs in two variants over the same weighted sum. The booth-weighted variant takes three points for each of the lead's `booth_visits` plus five points for each of its `doc_downloads`. The engagement-weighted variant adds to that same sum half a point for each minute of the linked registration's `watched_minutes` and twelve points for each of its `accepted_meeting_count`. In both variants the weighted sum is rounded half up to a whole number exactly once, then capped at 100, and the result is written to `score`. A lead's `is_hot` flag is then set to true when `score` is at least 60 and false otherwise, and `score_variant` records which variant last wrote the score — `BOOTH_WEIGHTED` or `ENGAGEMENT_WEIGHTED`.

The booth-weighted variant runs at lead capture and after every booth interaction. A `SponsorUser` logs an interaction by supplying an `interaction_type`: a `VISIT` increments the lead's `booth_visits` and a `DOWNLOAD` increments its `doc_downloads`, and the lead is then re-scored with the booth-weighted variant, refreshing `score` and `is_hot`.

The engagement-weighted variant runs only when the organizer triggers an event-wide rescore, which walks every lead of the event, applies the engagement-weighted formula, sets each lead's `score_variant` to `ENGAGEMENT_WEIGHTED`, and returns a `rescored_count` of leads touched together with a `hot_lead_count` of those whose `is_hot` ended up true. Because the engagement variant only ever adds non-negative terms to the booth-weighted sum, the identical lead row scores strictly higher after a rescore, or equal when the attendee has zero watched minutes and zero accepted meetings. A lead whose registration has been withdrawn contributes zero watched minutes and zero accepted meetings to the engagement variant regardless of what those counters held before withdrawal. Leads are readable individually and listable with filters on `booth_id`, `registration_id` and `event_id`.

### 3.9. Networking and Matchmaking

Attendees propose meetings with one another. A match request names the `event_id`, the `requester_registration_id`, the `target_registration_id`, and the proposed `window_start` and `window_end` bounding the meeting; `window_end` must be strictly later than `window_start`. A registration may not propose a meeting with itself — identical requester and target identifiers are refused with `ERR_SELF_MATCH_NOT_ALLOWED` (HTTP 422) — and both registrations must belong to the named event, or the proposal fails with `ERR_REGISTRATION_EVENT_MISMATCH`.

A new request lands in `PENDING`, and its `expires_at` is derived as the `window_start` less one hour. That derivation is what gives participants a guaranteed hour of notice: a request that has not been answered by sixty minutes before the meeting was due to start is no longer answerable. The lifecycle is `PENDING` branching to `ACCEPTED`, `DECLINED`, `EXPIRED` or `CANCELLED`, with the last three plus `ACCEPTED` all being end-states in practice and `DECLINED`, `EXPIRED` and `CANCELLED` declared terminal.

Only the target may answer, meaning the acting `X-User-ID` must equal the request's `target_registration_id`. Acceptance moves the request `PENDING → ACCEPTED` and requires two further things. The current logical clock must be strictly before `expires_at`; at or past that instant the attempt is refused with `ERR_MATCH_REQUEST_EXPIRED` (HTTP 409). And neither the requester's nor the target's calendar may already hold an accepted meeting whose closed window intersects this one under the geometry of Section 2.10 — each participant may hold at most one accepted meeting at any instant, so an intersection is refused with `ERR_MEETING_WINDOW_CONFLICT` (HTTP 409). On success, both the requester's and the target's `accepted_meeting_count` rise by one. Declining moves the request `PENDING → DECLINED` and changes no counter.

Requests that nobody answered are cleared by an organizer-triggered sweep over a single event, which moves every `PENDING` request of that event whose `expires_at` is at or before the current logical clock to `EXPIRED` and returns the `expired_count` of rows it touched. Requests are also cancelled indirectly: when either participant's registration is withdrawn, every `PENDING` request involving that registration becomes `CANCELLED`. Match requests are readable individually and listable with filters on `event_id`, `requester_registration_id`, `target_registration_id` and `state`, by `Attendee`, `Organizer` and `PlatformAdmin`.

### 3.10. Event Analytics

The analytics snapshot is a computed read, available to `Organizer` and `PlatformAdmin`, that persists nothing. Its attendee population is the set of registrations of the event whose `attendance_status` is `CHECKED_IN` or `ATTENDED`; registrations in `NO_SHOW`, `WITHDRAWN`, `WAITLISTED` or `REGISTERED` are excluded entirely, and only rows created at or before the current logical clock participate.

From that population the snapshot reports `unique_attendees` as the count of rows, and `total_watch_minutes` as the sum of their `watched_minutes`. It reports `avg_watch_minutes` as the total watch minutes divided by the number of unique attendees, carried to two decimal places and rounded half up; when the population is empty the average is reported as 0.00 rather than attempting a division. It reports `on_demand_views` as the sum of `view_count` across the event's recordings currently in `PUBLISHED` — retracted and deleted assets contribute nothing. Finally it echoes the event's own `registered_count` and `gross_collected_cents`. Every figure except the average is an integer, and because the computation is made of pure sums and counts the result does not depend on the order in which rows are visited.

### 3.11. Settlement and Billing

Two kinds of invoice close the books, distinguished by a settlement's `subject_type`. Both share a lifecycle of `DRAFT → ISSUED → PAID`, with `VOID` reachable from `DRAFT` or `ISSUED`; `PAID` and `VOID` are terminal. Both carry `line_items` — an ordered list of objects each bearing a `label`, a `units` figure, a `unit_cents` rate and a `line_total_cents` — plus `subtotal_cents`, `tax_cents`, `platform_fee_cents`, `total_cents` and `organizer_payout_cents`. Every settlement records the `event_id` it covers; a settlement whose `subject_type` is `SPONSOR` additionally records the `sponsor_id` it bills, while a settlement whose `subject_type` is `EVENT` leaves `sponsor_id` null. All settlement creation, issuance, payment and voiding is restricted to `FinanceAdmin`; reads are shared with `PlatformAdmin` and `Organizer`, and settlements are listable with filters on `event_id`, `sponsor_id`, `subject_type` and `state`.

**The sponsorship invoice** has `subject_type` of `SPONSOR` and is drawn against a single sponsor, billing the one booth whose `sponsor_id` matches. It has exactly three lines, in this order. The `PACKAGE` line always bills one unit at the package rate for the sponsor's `package_tier`: 250,000 cents for `BRONZE`, 500,000 cents for `SILVER`, and 900,000 cents for `GOLD`. The `LEAD_OVERAGE` line bills the excess of the booth's `captured_lead_count` over its `lead_quota` — or zero units when the booth stayed within quota, never a negative figure — at 137.5 cents per lead. The `BOOTH_STREAM` line bills the booth's `stream_minutes_total` at 4.25 cents per minute. When the sponsor has no booth at all, the package line still bills its single unit and the other two lines bill zero units. A booth in `SUSPENDED` is still billed in full.

The rounding order on that invoice is pinned and is not interchangeable with any equivalent-looking alternative. **Each line's `line_total_cents` is computed as its units multiplied by its unit rate and rounded half up to a whole cent first**, and only then are the three rounded line totals added to give `subtotal_cents`. Summing the unrounded line values and rounding once at the end produces a different subtotal and is wrong. Tax is then taken as 8.25 percent of that already-rounded `subtotal_cents`, rounded half up exactly once, and written to `tax_cents`; `total_cents` is `subtotal_cents` plus `tax_cents`. Sponsorship invoices carry `platform_fee_cents` of zero and `organizer_payout_cents` of zero.

**The organizer invoice** has `subject_type` of `EVENT`, is created against an event under the concurrency guard of Section 2.9, and is refused with `ERR_SETTLEMENT_EXISTS` (HTTP 409) when an EVENT settlement for the same event already sits in `ISSUED` or `PAID`. A prior EVENT settlement still in `DRAFT` is not an obstacle: it is superseded, moving to `VOID` as the new one is created. Creation advances the event's `version`.

Its seven steps run strictly in order, and the order matters because the computation *looks* circular without being so — the volume discount that reduces the platform fee is keyed on the subtotal of tickets and streaming, never on the invoice total that the fee itself feeds into. Do not iterate to a fixed point.

**Step one** re-derives every registration of the event whose `payment_status` is `PAID` using the final pricing variant of Section 3.4, writing each row's `final_amount_due_cents`. **Step two** sums those `final_amount_due_cents` values across the same PAID population to give the gross ticket revenue. **Step three** sums, over that same population, each registration's `final_amount_due_cents` less its `amount_paid_cents`, and writes the result to the event's `settlement_adjustment_cents` — this is the aggregate correction between what attendees were charged and what they actually owed. **Step four** values the streaming consumption as the event's `streamed_minutes_total` multiplied by 4 cents per minute, and sets `subtotal_cents` to the gross ticket revenue plus that streaming charge. **Step five** picks the volume discount from the subtotal: a `subtotal_cents` of at least 250,000 earns fifteen percent, otherwise a `subtotal_cents` of at least 100,000 earns ten percent, and anything below that earns none — both thresholds are inclusive. **Step six** takes the raw platform fee as eight percent of `subtotal_cents` rounded half up, multiplies it by one minus the volume discount fraction and rounds half up again, then applies a floor so that `platform_fee_cents` is never less than 500 cents. Those two are the only roundings in the whole computation. **Step seven** sets `total_cents` to `platform_fee_cents` plus the streaming charge, and `organizer_payout_cents` to the gross ticket revenue less `total_cents` — a figure that may legitimately be negative. The invoice's `line_items` are, in order, a `PLATFORM_FEE` line of one unit at the platform fee rate, and a `STREAMING` line of `streamed_minutes_total` units at 4 cents each. `tax_cents` on an organizer invoice is zero.

Only PAID registrations participate; `UNPAID`, `REFUNDED` and `WAITLISTED` rows contribute nothing. When no registration of the event has been paid, gross ticket revenue and `settlement_adjustment_cents` are both zero, the 500-cent floor still applies, and so `total_cents` equals 500 cents against zero revenue and `organizer_payout_cents` comes out negative.

Issuing a settlement moves it `DRAFT → ISSUED` and stamps `issued_by_user_id` with the acting `X-User-ID`. When the settlement's `subject_type` is `EVENT`, issuance is also what closes the event: the owning event transitions `ENDED → SETTLED` and its `version` advances. Payment moves the settlement `ISSUED → PAID`, stamps `paid_by_user_id` with the acting `X-User-ID`, and enforces two conditions. The submitted `paid_amount_cents` must equal `total_cents` exactly, failing otherwise with `ERR_PAYMENT_AMOUNT_MISMATCH`. And **segregation of duties** applies: the finance operator marking the settlement paid must not be the same operator recorded in `issued_by_user_id`, or the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Voiding, with a `reason`, is available from `DRAFT` or `ISSUED` and renders the settlement no longer billable.

## 4. Endpoint Definitions

The table below is the complete HTTP surface of the platform. Endpoints that bring a new resource into existence answer with **201 Created**; endpoints that modify, transition or read an existing resource answer with **200 OK**; the soft-delete of a recording answers with **204 No Content** and an empty body. Request and response payloads are deliberately not repeated here — the fields each operation consumes, and the side effects each one produces, are specified in the narrative of Sections 2 and 3, and readers must reconstruct the full contract from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock. Before any call to this endpoint the logical clock reads exactly 2026-07-01T00:00:00Z; it never falls back to real ... | `PlatformAdmin` |
| POST | `/api/events` | Create an event in DRAFT. | `Organizer` |
| GET | `/api/events` | List events with pagination. | `Organizer`, `PlatformAdmin`, `FinanceAdmin` |
| GET | `/api/events/{event_id}` | Read one event, including version for OCC and all computed counters. | `Organizer`, `PlatformAdmin`, `FinanceAdmin`, `Attendee`, `SponsorUser`, `SpeakerUser` |
| PATCH | `/api/events/{event_id}` | Update mutable event attributes while the event is DRAFT or PUBLISHED. | `Organizer` |
| POST | `/api/events/{event_id}/publish` | DRAFT -> PUBLISHED; opens registration. | `Organizer` |
| POST | `/api/events/{event_id}/start` | PUBLISHED -> LIVE; promotes APPROVED booths to LIVE. | `Organizer` |
| POST | `/api/events/{event_id}/end` | LIVE -> ENDED; resolves attendance for every registration. | `Organizer` |
| POST | `/api/events/{event_id}/cancel` | Cancel the event and run the three-link CASCADE-A chain (sessions -> broadcasts -> recordings). | `Organizer` |
| GET | `/api/events/{event_id}/analytics` | Computed read returning the event_analytics_snapshot. | `Organizer`, `PlatformAdmin` |
| POST | `/api/events/{event_id}/ticket-types` | Create a ticket type under an event. | `Organizer` |
| GET | `/api/events/{event_id}/ticket-types` | Reverse-reachability list of ticket types for an event. | `Organizer`, `PlatformAdmin`, `Attendee`, `FinanceAdmin` |
| GET | `/api/ticket-types` | Filtered list of ticket types (reverse-reachability from event_id). | `Organizer`, `PlatformAdmin`, `Attendee`, `FinanceAdmin` |
| GET | `/api/ticket-types/{ticket_type_id}` | Read one ticket type including sold_count and availability_status. | `Organizer`, `PlatformAdmin`, `Attendee`, `FinanceAdmin` |
| POST | `/api/registrations` | Register an attendee. Prices with registration_amount_due variant provisional. When the ticket type is SOLD_OUT or the event is at capacity and wai... | `Organizer` |
| GET | `/api/registrations` | Filtered list of registrations. | `Organizer`, `PlatformAdmin`, `FinanceAdmin` |
| GET | `/api/registrations/{registration_id}` | Read one registration with both state axes and all money fields. | `Organizer`, `PlatformAdmin`, `FinanceAdmin`, `Attendee` |
| POST | `/api/registrations/{registration_id}/pay` | Collect payment; payment_status UNPAID -> PAID. | `Organizer` |
| POST | `/api/registrations/{registration_id}/refund` | Refund a paid registration and run the three-link CASCADE-B chain (money + seat release -> availability flip -> waitlist promotion). | `Organizer` |
| POST | `/api/registrations/{registration_id}/check-in` | attendance_status REGISTERED -> CHECKED_IN while the event is LIVE. | `Organizer` |
| POST | `/api/registrations/{registration_id}/withdraw` | Withdraw a registration; compensating action for the seat-inventory invariant. | `Organizer`, `Attendee` |
| POST | `/api/events/{event_id}/tracks` | Create a track (the scheduling resource sessions occupy). | `Organizer` |
| GET | `/api/events/{event_id}/tracks` | Reverse-reachability list of tracks for an event. | `Organizer`, `PlatformAdmin` |
| GET | `/api/tracks` | Filtered list of tracks (reverse-reachability from event_id). | `Organizer`, `PlatformAdmin` |
| GET | `/api/tracks/{track_id}` | Read one track. | `Organizer`, `PlatformAdmin` |
| POST | `/api/sessions` | Create a session in DRAFT (no track slot is occupied yet). | `Organizer` |
| GET | `/api/sessions` | Filtered list of sessions. | `Organizer`, `PlatformAdmin`, `Attendee`, `SpeakerUser` |
| GET | `/api/sessions/{session_id}` | Read one session. | `Organizer`, `PlatformAdmin`, `Attendee`, `SpeakerUser` |
| POST | `/api/sessions/{session_id}/schedule` | DRAFT -> SCHEDULED; claims the half-open [starts_at, ends_at) slot on the track. | `Organizer` |
| POST | `/api/sessions/{session_id}/cancel` | Cancel a session; releases the track slot, RELEASEs its session-speakers and ABORTs its broadcasts. | `Organizer` |
| POST | `/api/sessions/{session_id}/attendance` | Record live watch minutes for a checked-in registration on this session. | `Organizer` |
| POST | `/api/events/{event_id}/speakers` | Create a speaker profile scoped to an event. | `Organizer` |
| GET | `/api/events/{event_id}/speakers` | Reverse-reachability list of speakers for an event. | `Organizer`, `PlatformAdmin`, `SpeakerUser` |
| GET | `/api/speakers` | Filtered list of speakers (reverse-reachability from event_id). | `Organizer`, `PlatformAdmin`, `SpeakerUser` |
| GET | `/api/speakers/{speaker_id}` | Read one speaker including accepted_session_count and engagement_status. | `Organizer`, `PlatformAdmin`, `SpeakerUser` |
| POST | `/api/session-speakers` | Invite a speaker to a session; creates the junction row in INVITED with invite_round 1. | `Organizer` |
| GET | `/api/session-speakers` | Filtered list of session-speaker junction rows. | `Organizer`, `PlatformAdmin`, `SpeakerUser` |
| GET | `/api/session-speakers/{session_speaker_id}` | Read one junction row. | `Organizer`, `PlatformAdmin`, `SpeakerUser` |
| POST | `/api/session-speakers/{session_speaker_id}/accept` | INVITED -> ACCEPTED; enforces the 10-minute buffered speaker-calendar geometry. | `SpeakerUser` |
| POST | `/api/session-speakers/{session_speaker_id}/decline` | INVITED -> DECLINED (terminal). | `SpeakerUser` |
| POST | `/api/session-speakers/{session_speaker_id}/withdraw` | ACCEPTED -> WITHDRAWN; releases the speaker's calendar window. | `SpeakerUser` |
| POST | `/api/session-speakers/{session_speaker_id}/reinvite` | WITHDRAWN -> INVITED; closes the invite cycle and bumps invite_round. | `Organizer` |
| POST | `/api/broadcasts` | Create a broadcast for a session in SCHEDULED state. | `Organizer` |
| GET | `/api/broadcasts` | Filtered list of broadcasts. | `Organizer`, `PlatformAdmin` |
| GET | `/api/broadcasts/{broadcast_id}` | Read one broadcast. | `Organizer`, `PlatformAdmin` |
| POST | `/api/broadcasts/{broadcast_id}/preview` | SCHEDULED -> PREVIEW. | `Organizer` |
| POST | `/api/broadcasts/{broadcast_id}/go-live` | PREVIEW -> LIVE; requires the owning Event to be LIVE and the session to have at least one ACCEPTED speaker. | `Organizer` |
| POST | `/api/broadcasts/{broadcast_id}/end` | LIVE -> ENDED; computes streamed_minutes and advances the recording to PROCESSING. | `Organizer` |
| POST | `/api/broadcasts/{broadcast_id}/abort` | Abort a broadcast; retracts its recordings. | `Organizer` |
| GET | `/api/recordings` | Filtered list of recordings; DELETED rows are excluded unless state=DELETED is requested. | `Organizer`, `PlatformAdmin`, `Attendee` |
| GET | `/api/recordings/{recording_id}` | Read one recording. | `Organizer`, `PlatformAdmin`, `Attendee` |
| POST | `/api/recordings/{recording_id}/complete` | PROCESSING -> READY with the encoded duration. | `PlatformAdmin` |
| POST | `/api/recordings/{recording_id}/publish` | READY -> PUBLISHED with a gating level. | `Organizer` |
| POST | `/api/recordings/{recording_id}/retract` | PUBLISHED -> RETRACTED. | `Organizer` |
| POST | `/api/recordings/{recording_id}/reprocess` | RETRACTED -> PROCESSING (closes the recording cycle). | `PlatformAdmin` |
| POST | `/api/recordings/{recording_id}/views` | Record an on-demand view; enforces the ticket gating level and PAID status of the acting registration. | `Attendee` |
| DELETE | `/api/recordings/{recording_id}` | Delete a RETRACTED or READY recording (soft, state -> DELETED). | `Organizer` |
| POST | `/api/events/{event_id}/sponsors` | Register a sponsor against an event. | `Organizer` |
| GET | `/api/events/{event_id}/sponsors` | Reverse-reachability list of sponsors for an event. | `Organizer`, `PlatformAdmin`, `FinanceAdmin` |
| GET | `/api/sponsors` | Filtered list of sponsors (reverse-reachability from event_id). | `Organizer`, `PlatformAdmin`, `FinanceAdmin`, `SponsorUser` |
| GET | `/api/sponsors/{sponsor_id}` | Read one sponsor. | `Organizer`, `PlatformAdmin`, `FinanceAdmin`, `SponsorUser` |
| POST | `/api/sponsors/{sponsor_id}/sign-contract` | Mark the sponsorship contract SIGNED, unlocking booth approval. | `Organizer` |
| POST | `/api/booths` | Create a virtual booth in DRAFT for a sponsor. | `SponsorUser` |
| GET | `/api/booths` | Filtered list of booths. | `Organizer`, `PlatformAdmin`, `SponsorUser`, `Attendee`, `FinanceAdmin` |
| GET | `/api/booths/{booth_id}` | Read one booth including captured_lead_count and stream_minutes_total. | `Organizer`, `PlatformAdmin`, `SponsorUser`, `Attendee`, `FinanceAdmin` |
| POST | `/api/booths/{booth_id}/submit` | DRAFT or CHANGES_REQUESTED -> SUBMITTED; bumps revision_round. | `SponsorUser` |
| POST | `/api/booths/{booth_id}/approve` | SUBMITTED -> APPROVED; requires the sponsor's contract_status == SIGNED. | `Organizer` |
| POST | `/api/booths/{booth_id}/request-changes` | SUBMITTED -> CHANGES_REQUESTED (the other fork of the branch). | `Organizer` |
| POST | `/api/booths/{booth_id}/suspend` | APPROVED or LIVE -> SUSPENDED (terminal). | `Organizer` |
| POST | `/api/booths/{booth_id}/stream-usage` | Report booth video minutes consumed; billed on the sponsor settlement at BOOTH_STREAM_UNIT_CENTS. | `SponsorUser` |
| POST | `/api/booths/{booth_id}/leads` | Capture a lead at a booth; requires marketing consent and an attendee registered to the booth's event. | `Attendee` |
| GET | `/api/leads` | Filtered list of leads. | `Organizer`, `PlatformAdmin`, `SponsorUser`, `FinanceAdmin` |
| GET | `/api/leads/{lead_id}` | Read one lead including score and score_variant. | `Organizer`, `PlatformAdmin`, `SponsorUser`, `FinanceAdmin` |
| POST | `/api/leads/{lead_id}/interactions` | Log a booth interaction against a lead and re-score with the booth_weighted variant. | `SponsorUser` |
| POST | `/api/events/{event_id}/leads/rescore` | Re-score every lead of the event with the engagement_weighted lead_score variant. | `Organizer` |
| POST | `/api/match-requests` | Propose a networking meeting between two registrations of the same event. | `Attendee` |
| GET | `/api/match-requests` | Filtered list of match requests. | `Attendee`, `Organizer`, `PlatformAdmin` |
| GET | `/api/match-requests/{match_request_id}` | Read one match request. | `Attendee`, `Organizer`, `PlatformAdmin` |
| POST | `/api/match-requests/{match_request_id}/accept` | PENDING -> ACCEPTED; enforces the closed-interval meeting geometry on both registrations. | `Attendee` |
| POST | `/api/match-requests/{match_request_id}/decline` | PENDING -> DECLINED. | `Attendee` |
| POST | `/api/events/{event_id}/matchmaking/sweep` | Expire every PENDING match request of the event whose expires_at is at or before the current logical clock. | `Organizer` |
| POST | `/api/events/{event_id}/settlements` | Create the EVENT settlement (organizer platform-fee invoice). OCC-guarded on Event.version; supersedes any existing DRAFT EVENT settlement by voidi... | `FinanceAdmin` |
| POST | `/api/sponsors/{sponsor_id}/settlements` | Create the SPONSOR settlement (sponsorship invoice) using per-line rounding. | `FinanceAdmin` |
| GET | `/api/settlements` | Filtered list of settlements. | `FinanceAdmin`, `PlatformAdmin`, `Organizer` |
| GET | `/api/settlements/{settlement_id}` | Read one settlement with line_items and totals. | `FinanceAdmin`, `PlatformAdmin`, `Organizer` |
| POST | `/api/settlements/{settlement_id}/issue` | DRAFT -> ISSUED; stamps issued_by_user_id and, for EVENT settlements, moves the event ENDED -> SETTLED. | `FinanceAdmin` |
| POST | `/api/settlements/{settlement_id}/pay` | ISSUED -> PAID; the payer must differ from the issuer (segregation of duties). | `FinanceAdmin` |
| POST | `/api/settlements/{settlement_id}/void` | DRAFT or ISSUED -> VOID. | `FinanceAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_TICKET_TYPE_NOT_FOUND` | 404 |
| `ERR_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_TRACK_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_SPEAKER_NOT_FOUND` | 404 |
| `ERR_SESSION_SPEAKER_NOT_FOUND` | 404 |
| `ERR_BROADCAST_NOT_FOUND` | 404 |
| `ERR_RECORDING_NOT_FOUND` | 404 |
| `ERR_SPONSOR_NOT_FOUND` | 404 |
| `ERR_BOOTH_NOT_FOUND` | 404 |
| `ERR_LEAD_NOT_FOUND` | 404 |
| `ERR_MATCH_REQUEST_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_TIME_RANGE_INVALID` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_STALE_EVENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_EVENT_NOT_OPEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CONSENT_REQUIRED` | 422 |
| `ERR_GATING_NOT_PERMITTED` | 403 |
| `ERR_REGISTRATION_EVENT_MISMATCH` | 422 |
| `ERR_CONTRACT_NOT_SIGNED` | 409 |
| `ERR_SELF_MATCH_NOT_ALLOWED` | 422 |
| `ERR_DUPLICATE_LEAD` | 409 |
| `ERR_TRACK_SLOT_CONFLICT` | 409 |
| `ERR_SPEAKER_BUFFER_CONFLICT` | 409 |
| `ERR_MEETING_WINDOW_CONFLICT` | 409 |
| `ERR_MATCH_REQUEST_EXPIRED` | 409 |
| `ERR_SETTLEMENT_EXISTS` | 409 |
| `ERR_TICKET_SOLD_OUT` | 409 |
| `ERR_EVENT_CAPACITY_EXCEEDED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
