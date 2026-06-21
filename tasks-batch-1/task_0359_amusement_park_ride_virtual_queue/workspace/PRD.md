# Amusement Park Ride Virtual Queue API — Product Requirements Document

## 1. Introduction

A modern theme park no longer manages its midways with physical standby lines alone. Guests reserve ride times from a phone, claim premium line-skip privileges that surge with demand, link into travelling parties, and expect a fair allocation of scarce ride capacity across a single operating day. This API is the back-end of record for that experience. It governs park admission against a turnstile cap, the supply of virtual-queue slots a ride can honour during a given return window, the paid Lightning Lane tiers that let guests bypass standby, and the cascading consequences when a ride breaks down mid-day.

The system has three constituencies whose actions must remain mutually consistent at every moment. Park operations staff configure the park and its inventory, admit and release guests at the gate, and advance the logical day. Ride attendants raise and lower the operational posture of individual rides and scan guests into queues. Guest-facing applications book and manage reservations, assemble parties, and purchase line-skips on behalf of a single guest. Because capacity is finite and demand is bursty, every debit and credit of a slot, every admission, and every redistribution after a breakdown must reconcile synchronously inside the request that triggered it — there is no eventual-consistency window in which two guests can both believe they hold the last seat.

This document specifies the complete contract: the resource model, the state machines that drive reservations and rides through their lifecycles, the dual-variant pricing and capacity calculations, the priority-ordered validation pipeline, and the role-based access rules that bind each actor to the resources it may touch.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which it acts. If either header is missing, or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `ParkAdmin`, `RideOperator`, and `GuestApp`. When a recognized role attempts an operation that its permissions do not cover, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` is interpreted, which in turn determines what each may touch:

- When `X-User-Role` is `ParkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. A `ParkAdmin` is park operations staff: it configures parks, rides, return windows, entitlement plans, and day tickets, and it runs admissions, exits, the logical clock, and window advancement.
- When `X-User-Role` is `RideOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `RideOperator` is a ride attendant who controls a ride's operational posture and scans guests into queues and premium lines.
- When `X-User-Role` is `GuestApp`, `X-User-ID` is the `id` of the acting `Guest`; ownership checks on any resource that references a `Guest` compare the resource's `guest_id` (or, for a party, the `leader_guest_id` of the party) to `X-User-ID`. A `GuestApp` principal therefore acts only as one specific guest, booking and managing its own reservations, parties, and purchases.

Ownership is enforced as its own check, distinct from role membership: a `GuestApp` request that targets a reservation, party, or purchase belonging to another guest — that is, whose `X-User-ID` is neither the owning `guest_id` nor the `leader_guest_id` of the target party — is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, so the earliest-created resource appears first.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether further pages exist beyond the current window.

### 2.4. Common Resource Properties

Every primary resource in the system — `Park`, `Ride`, `ReturnWindow`, `Guest`, `Party`, `PartyMembership`, `EntitlementPlan`, `GuestDayTicket`, `Reservation`, and `LightningLanePurchase` — carries a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.7. All ten resource types in this system carry the full set — `id`, `created_at`, `updated_at`, and `version` — because every one of them is mutable over its lifetime.

When a derived counter or computed field on a resource changes — for example, a `Park`'s `admitted_count` and `day_phase`, a `Ride`'s `booked_slot_count` and `posted_wait_minutes`, or a `ReturnWindow`'s `reserved_count` and `window_status` — that change is itself a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Temporal Windowing

The park runs on a logical clock rather than wall-clock time. Each `Park` carries a `current_utc` instant that the system treats as "now" for every time comparison in the domain — chiefly the open/elapsed status of return windows and whether a reservation may be redeemed. A `ParkAdmin` advances this clock through a test-driving capability that supplies the `park_id` of the park to adjust and a `to_iso8601` instant, which becomes the park's new `current_utc`; until it is set, no window comparison should be assumed to have elapsed. The single most important rule here is that return-window math always reads `current_utc`, never the host's wall clock.

A `ReturnWindow` describes a half-open interval. Its `window_start_utc` is the inclusive start and its `window_end_utc` is the exclusive end, so the window covers instants from `window_start_utc` up to but not including `window_end_utc`. A window has elapsed precisely when the park's `current_utc` is at or after `window_end_utc`; it is still future when `current_utc` is strictly before `window_end_utc`. These same boundary semantics govern redeemability: a reservation is redeemable only while `current_utc` is at or after `window_start_utc` and strictly before `window_end_utc`.

### 2.6. Hierarchical Consistency and Cascading Effects

The park is an aggregate whose posture gates the children beneath it. A `Ride`'s `operational_status` acts as a gate over its return windows and the reservations bound to them; a `ReturnWindow`'s `window_status` gates whether new virtual-queue slots may be claimed; and a `Park`'s `day_phase` gates whether ordinary guests may book at all. Whenever an operation changes a parent's posture, the system reconciles every dependent child synchronously within the same request — there is no deferred sweep. The detailed cascades (ride breakdown suspending windows and redistributing booked reservations, window expiry forfeiting reservations, ride closure expiring windows and forfeiting reservations, party disband clearing memberships) are specified in §3, but the governing principle is that no child is left in a state inconsistent with its parent once the triggering request returns.

Each such reconciliation independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`. When a counter is debited or credited on a parent (for instance, a `ReturnWindow`'s `reserved_count` or a `Ride`'s `booked_slot_count`), that parent is mutated in the same way.

### 2.7. Optimistic Concurrency Control

Two write operations in this system are guarded by optimistic concurrency control because they compete for capacity that a concurrent writer may have already changed. In each case the client must echo, as a required input field, the `version` of the parent resource it last observed; if that value no longer matches the parent's current `version`, the write is refused so the client cannot act on a stale view.

Creating a reservation is guarded against the target `ReturnWindow`. The create request must carry `expected_return_window_id_version`, set to the window's `version` as the client last read it. If the window's `version` has advanced since then — because another writer claimed a slot and bumped it — the new reservation's view of `reserved_count` against `slot_capacity` is no longer current, so the create is rejected with `ERR_STALE_VERSION` (HTTP 412) before it can oversell the window.

Submitting a party-booking is guarded against the target `Party`. The request must carry `expected_party_version`, set to the party's `version` as the client last read it. Membership link and unlink operations, as well as a prior party-booking, all advance `Party.version`; if it has moved since the client's last read, the booking would fan out reservations over a member set the client no longer knows accurately, so it is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field; only these two creates carry the OCC contract.

### 2.8. Capacity, Occupancy, and the Day Phase

Park admission is bounded by `gate_capacity`, the maximum number of guests that may be simultaneously admitted. The live count of admitted guests is `admitted_count`, recomputed on every admission and exit. From the ratio of these two the system derives `day_phase`, which takes one of `OPEN`, `PEAK`, or `FULL`. The phase is `OPEN` while occupancy — `admitted_count` divided by `gate_capacity` — is strictly below `peak_threshold_pct`; it is `PEAK` once occupancy reaches `peak_threshold_pct` or higher while remaining strictly below full (`admitted_count` strictly less than `gate_capacity`); and it is `FULL` once `admitted_count` reaches `gate_capacity` or more. The `peak_threshold_pct` is an occupancy fraction strictly greater than 0 and at most 1, defaulting to 0.85 when not supplied. The phase is recomputed on every admission change, in either direction, so releasing guests can relax the park from `FULL` back toward `PEAK` and then `OPEN`.

The day phase is more than a label: during `PEAK`, the virtual queue is reserved for premium guests, a gate detailed in §3. During `FULL`, the gate is shut to further admissions.

### 2.9. Precision and Rounding

Two figures in this system are computed and must be produced exactly. Lightning Lane prices are money in whole cents: a surged price is first computed as a floating value, the single-pass cap is applied if applicable, and only then is the result rounded to a whole number of cents using the round-half-up convention (a fractional cent of exactly one-half rounds up). The cap-then-round order is fixed and must not be reversed. Slot capacities and posted wait times are whole integers: slot capacity is produced by truncating downward (floor) and posted wait time by rounding upward (ceiling), as detailed in §3. Posted wait time is never negative.

### 2.10. Resource Existence and Nested Path Validation

Before any business rule runs, the system confirms that every resource named in the request — whether in the URL path or the body — exists. References are checked left to right in the order they appear in the path, and the first missing identifier short-circuits the request with `ERR_NOT_FOUND`. For an endpoint such as a ride's return-window collection, the parent ride's existence is confirmed before the window beneath it. The full set of entities subject to this existence check comprises `Park`, `Ride`, `Guest`, `Party`, `ReturnWindow`, `EntitlementPlan`, `Reservation`, `LightningLanePurchase`, and day tickets. Separately, when a referenced `Guest`, `Ride`, or `ReturnWindow` belongs to a different `Park` than the operation's park scope, the request is rejected with `ERR_GUEST_PARK_MISMATCH`. Malformed input — a missing required field, a value of the wrong shape, or an enum outside its permitted set — is rejected with `ERR_VALIDATION`.

### 2.11. Validation Priority Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order, and the first failure is the one reported. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, role authorization (`ERR_UNAUTHORIZED`); third, existence of all referenced resources, left to right (`ERR_NOT_FOUND`); fourth, resource ownership for `GuestApp` actions (`ERR_NOT_RESOURCE_OWNER`); fifth, that the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); sixth, the optimistic-concurrency version match on the two guarded creates (`ERR_STALE_VERSION`); seventh, the height requirement (`ERR_HEIGHT_REQUIREMENT_NOT_MET`); eighth, the accessibility check (`ERR_ACCESSIBILITY_BLOCKED`); ninth, the temporal window check (`ERR_WINDOW_NOT_REDEEMABLE`); tenth, the peak day-phase gate (`ERR_PEAK_GATE_BLOCKED`); eleventh, the per-guest virtual-queue ceiling (`ERR_VQ_LIMIT_REACHED`); twelfth, the per-guest Lightning Lane hold ceiling (`ERR_HOLD_LIMIT_REACHED`); thirteenth, the window-capacity (exhaustion) check (`ERR_WINDOW_EXHAUSTED`); and fourteenth, the park admission-capacity check (`ERR_PARK_AT_CAPACITY`). A request must clear an earlier check before a later one is even evaluated, so a guest who is both too short and trying to book an exhausted window sees the height failure, not the exhaustion failure.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Park and Its Inventory

A `ParkAdmin` brings a park into being by supplying a `name`, a `gate_capacity` of at least 1, the `operating_date` the park is selling and serving (in `YYYY-MM-DD` form), and optionally a `peak_threshold_pct`. A freshly created park starts with `admitted_count` at 0 and `day_phase` at `OPEN`; its logical clock `current_utc` is unset until an admin sets it. Reading a park returns its live `admitted_count` and derived `day_phase`.

Under a park, the same admin defines rides. A `Ride` is created with a `name` and an `hourly_throughput` of at least 1, which is the number of guests the ride can cycle through per operating hour at full operation and the basis for both its virtual-queue slot supply and its posted wait estimate. A ride optionally declares a `min_height_cm` (the minimum guest height in centimeters required to board, where 0 means no requirement and which must be at least 0), a `wheelchair_transfer_required` flag (true when a guest must transfer out of a wheelchair to ride), and a `single_rider_enabled` flag (true when the ride offers a single-rider line); each of these three defaults to its safe value — 0, false, and false respectively. A ride is born `OPEN` with `booked_slot_count` at 0 and its `posted_wait_minutes` computed. Each ride records the `park_id` of the park it belongs to.

Return windows are the unit of virtual-queue capacity. A `ParkAdmin` opens a `ReturnWindow` on a ride by supplying its `window_start_utc` and `window_end_utc`; the window records the `ride_id` it allocates for. Its `slot_capacity` is computed at creation, not supplied: take the window's length in whole minutes — the difference between `window_end_utc` and `window_start_utc`, truncated to whole minutes — multiply the ride's `hourly_throughput` by that length divided by 60, multiply again by the virtual-queue supply fraction of 0.40 (the share of total throughput carved out for the virtual queue, the remainder being implicitly standby and single-rider), and floor the result to a whole number of slots. A window so short that this raw figure is below 1 floors to a `slot_capacity` of 0; such a window is still created but accepts no virtual-queue bookings from the outset, behaving as exhausted-equivalent while remaining distinct from an expired window. A new window opens with `reserved_count` at 0 and `window_status` at `OPEN`.

### 3.2. Guests, Tickets, and Crossing the Gate

A guest profile is created under a park by either a `ParkAdmin` or a `GuestApp`, supplying the guest's `full_name`, `height_cm` (in centimeters, which must be at least 30), and optionally a `uses_wheelchair` flag (true when the guest uses a wheelchair and cannot transfer, defaulting to false). Each guest records the `park_id` of its park and starts with `party_id` null, signifying no party membership. A guest's `party_id` is never set directly; it is managed entirely by the party-link and party-unlink flows in §3.5.

To enter, a guest needs a day ticket. A `ParkAdmin` issues a `GuestDayTicket` for a guest by supplying the `guest_id` and the `ticket_date` (the operating date the ticket admits for); each ticket records the `park_id` admitting it and is born `ISSUED`. Admission is the act of scanning that ticket through the turnstile, performed by a `ParkAdmin` who supplies the `ticket_id` of the ticket to admit. Admission may proceed only when the ticket is `ISSUED`, its `ticket_date` equals the park's `operating_date`, and the park is not full (`admitted_count` strictly less than `gate_capacity`); if the park is already at or above its gate capacity, admission is rejected with `ERR_PARK_AT_CAPACITY`. A successful admission moves the ticket from `ISSUED` to `ADMITTED`, increases the park's `admitted_count` by one, recomputes the park's `day_phase` from the new occupancy, and advances `Park.version`. The complementary exit, also performed by a `ParkAdmin` by supplying the `ticket_id`, may proceed only when the ticket is `ADMITTED`; it moves the ticket from `ADMITTED` to `EXITED`, decreases `admitted_count` by one, recomputes `day_phase` (which may relax the park from `FULL` toward `PEAK` and then `OPEN`), and advances `Park.version`. The `EXITED` state is terminal for a ticket, and `admission_status` thus walks `ISSUED → ADMITTED → EXITED`.

### 3.3. Booking and Holding a Virtual-Queue Reservation

The heart of the guest experience is the virtual-queue reservation. A `GuestApp` creates a `Reservation` by supplying the `ride_id`, the `guest_id` it acts for, the `return_window_id` whose slot it wants, a `queue_type`, and the `expected_return_window_id_version` described in §2.7. The `queue_type` is either `VIRTUAL_QUEUE`, which claims a free return-window slot, or `SINGLE_RIDER`, a loose-fill standby for individual seats that does not consume any window's `slot_capacity`. An optional `party_id` is set on the reservation only when it was created as part of a linked party-booking; otherwise it is null. Every reservation begins `HELD`, with its capacity provisionally debited, and records a `redistributed_from_window_id` that is null unless and until a ride-down redistribution moves it.

Several gates guard a virtual-queue create, and they fire in the priority order of §2.11. The guest must clear the height requirement: the guest's `height_cm` must be at least the ride's `min_height_cm`, or the request is rejected with `ERR_HEIGHT_REQUIREMENT_NOT_MET`. The guest must clear the accessibility check: it is forbidden for a guest whose `uses_wheelchair` is true to book a ride whose `wheelchair_transfer_required` is true — that combination, and only that combination, is rejected with `ERR_ACCESSIBILITY_BLOCKED`. The chosen window must not already have elapsed: its `window_end_utc` must be strictly after the park's `current_utc`, or the booking is rejected with `ERR_WINDOW_NOT_REDEEMABLE`. The peak gate must pass: when the park's `day_phase` is `PEAK`, a new virtual-queue reservation is allowed only if the acting guest holds an `ACTIVE` Lightning Lane purchase of the `MULTI_PASS` tier in this park; absent that, the booking is rejected with `ERR_PEAK_GATE_BLOCKED`. The guest must be under the virtual-queue ceiling: counting that guest's `VIRTUAL_QUEUE` reservations in `HELD` or `BOOKED` status, the count must be strictly below the park-wide limit of 2 active virtual-queue reservations per guest before another is added; at or above the limit the request is rejected with `ERR_VQ_LIMIT_REACHED`. Finally, for a `VIRTUAL_QUEUE` booking, the window must have room: its `reserved_count` must be strictly below its `slot_capacity`, or the request is rejected with `ERR_WINDOW_EXHAUSTED`.

When a `VIRTUAL_QUEUE` reservation is created and passes every gate, the system increments the target window's `reserved_count` by one and the ride's `booked_slot_count` by one, advances `ReturnWindow.version`, and recomputes the ride's `posted_wait_minutes`. If that debit brings the window's `reserved_count` to its `slot_capacity` or above, the window bubbles up from `OPEN` to `EXHAUSTED`. A `SINGLE_RIDER` reservation consumes no slot and so leaves `reserved_count` and the window status untouched.

A held reservation is made firm by confirmation, performed by the owning `GuestApp`. Confirmation is allowed only when the reservation is `HELD`, the parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the owning window is `OPEN`; otherwise it is rejected with `ERR_INVALID_STATE`. A successful confirm moves the reservation `HELD → BOOKED` and recomputes the ride's `posted_wait_minutes`. A guest may also abandon a still-held reservation: cancelling, again by the owning `GuestApp`, is allowed only while the reservation is `HELD`, and moves it `HELD → FORFEITED`. Cancellation of a `VIRTUAL_QUEUE` reservation credits the slot back — decrementing the window's `reserved_count` and the ride's `booked_slot_count` each by one — and if the window had been `EXHAUSTED` and now sits below capacity while not yet expired, it bubbles back from `EXHAUSTED` to `OPEN`; the ride's `posted_wait_minutes` is recomputed. The `reservation_status` field thus ranges over `HELD`, `BOOKED`, `REDEEMED`, `FORFEITED`, and `REDISTRIBUTED`.

### 3.4. Redeeming and the Window Lifecycle

Redemption is the moment a guest is scanned in, and it belongs to the `RideOperator`. A booked reservation may be redeemed only when it is `BOOKED`, its parent ride is `OPEN`, and — for a `VIRTUAL_QUEUE` reservation — the park's `current_utc` falls within the window: at or after `window_start_utc` and strictly before `window_end_utc`. A redemption attempted outside that interval is rejected with `ERR_WINDOW_NOT_REDEEMABLE`; an attempt against a reservation not in `BOOKED` status, or a ride not `OPEN`, is rejected with `ERR_INVALID_STATE`. Also at redemption the height requirement is re-checked, so a guest whose `height_cm` is below the ride's `min_height_cm` is turned away with `ERR_HEIGHT_REQUIREMENT_NOT_MET`. A successful redemption moves the reservation `BOOKED → REDEEMED`; for a `VIRTUAL_QUEUE` reservation it decrements the owning window's `reserved_count` by one and the ride's `booked_slot_count` by one, and if that window had been `EXHAUSTED` and now sits below `slot_capacity` while not expired, it bubbles from `EXHAUSTED` to `OPEN`. The ride's `posted_wait_minutes` is recomputed. `REDEEMED` is terminal for a reservation, as is `FORFEITED`.

The window itself moves through `OPEN`, `EXHAUSTED`, `EXPIRED`, and `SUSPENDED`. It opens `OPEN`. It tips to `EXHAUSTED` the instant a held reservation drives `reserved_count` to `slot_capacity` or above, and it bubbles back to `OPEN` whenever a forfeit, cancellation, redemption, or redistribution frees a slot so that `reserved_count` falls below `slot_capacity`, provided the park's `current_utc` is still before `window_end_utc`. It becomes `SUSPENDED` when its parent ride goes down. It becomes `EXPIRED` once the logical clock has passed it.

Window expiry is driven explicitly. A `ParkAdmin` advances the day's windows, which expires every window whose end has elapsed: for each window in `OPEN` or `EXHAUSTED` status whose `window_end_utc` is at or before the park's `current_utc`, the window moves to `EXPIRED`. Expiring a window cascades to its reservations: each reservation on that window still in `HELD` or `BOOKED` is forfeited — moved to `FORFEITED` — and for `VIRTUAL_QUEUE` reservations the freed slot is credited back by decrementing the window's `reserved_count` and the ride's `booked_slot_count` each by one. The advance returns the count of expired windows and the list of forfeited reservation identifiers. A `SUSPENDED` window also expires, rather than reopening, if it is touched (by a restore or an advance) while its `window_end_utc` is already at or before `current_utc`.

### 3.5. Parties and Group Booking

Guests travel together, and a party lets one guest book for the group. A `GuestApp` creates a `Party` under a park by supplying the `leader_guest_id` — the guest who founds the party and may book on its behalf — and the party records its `park_id`. On creation the party is `FORMING`, its leader is auto-linked as a `PartyMembership` in `LINKED` status, its `member_count` is 1, and the leader guest's `party_id` is set to point at the new party. The `party_status` ranges over `FORMING`, `LOCKED`, and `DISBANDED`.

The leader links additional guests. Adding a member, by the leading `GuestApp`, supplies the `guest_id` to link; it creates a `PartyMembership` in `LINKED` status (recording the membership's `party_id` and `guest_id`), increases the party's `member_count` by one, sets that guest's `party_id` to the party, and advances `Party.version`. Unlinking a member, again by the leader, removes a guest from the party: the membership moves `LINKED → REMOVED`, the party's `member_count` decreases by one, the guest's `party_id` is cleared back to null, and `Party.version` advances. The leader may not be unlinked from its own party — an attempt to do so is rejected with `ERR_LEADER_REMOVAL_FORBIDDEN`. The `membership_status` of a `PartyMembership` is either `LINKED` or `REMOVED`.

A party-booking fans a single request out across the group. The leading `GuestApp` submits a party-booking by supplying the `ride_id`, the `return_window_id`, and the `expected_party_version` that guards it. The booking is allowed only when the party is `FORMING` with a `member_count` of at least 1; it moves the party `FORMING → LOCKED`, which freezes membership churn while the booking is in flight, and advances `Party.version`. For each `LINKED` member that passes the height and accessibility checks, the system creates one `HELD` `VIRTUAL_QUEUE` reservation against the chosen window, debiting the window's `reserved_count` and the ride's `booked_slot_count` per created reservation and bubbling the window to `EXHAUSTED` if it fills. Members who fail height or accessibility are skipped rather than failing the whole booking. The same per-guest gates that govern an individual booking apply here — the peak day-phase gate (`ERR_PEAK_GATE_BLOCKED`), the per-guest virtual-queue ceiling (`ERR_VQ_LIMIT_REACHED`), the window-exhaustion check (`ERR_WINDOW_EXHAUSTED`), the height requirement (`ERR_HEIGHT_REQUIREMENT_NOT_MET`), and the accessibility check (`ERR_ACCESSIBILITY_BLOCKED`) all apply to a party-booking just as to a single reservation. The booking response reports the `party_id`, the list of created reservation identifiers, and the list of skipped guest identifiers. A locked party may be released back to `FORMING` by the leader, which advances `Party.version`. A party that is still `FORMING` may be disbanded by the leader: disbanding moves the party `FORMING → DISBANDED`, sets every `LINKED` membership to `REMOVED`, and clears the `party_id` of each affected guest back to null. `DISBANDED` is terminal for a party.

### 3.6. Lightning Lane Line-Skips and Surge Pricing

Premium line-skips are sold against entitlement plans. A `ParkAdmin` creates an `EntitlementPlan` under a park by supplying its `tier`, its base `price_cents` in cents (at least 0), its `max_concurrent_holds` (the most simultaneously active line-skip holds a guest may carry under the plan, at least 1), and optionally a `surge_multiplier` (the demand multiplier applied to the base price when the target ride is loaded, at least 1.0 and defaulting to 1.0). The plan records its `park_id`. The `tier` is either `MULTI_PASS`, which lets a guest carry multiple concurrent line-skip holds across rides (and, per §3.3, satisfies the peak gate), or `SINGLE_PASS`, which grants one premium per day on a single high-demand ride.

A `GuestApp` buys a line-skip by supplying the `park_id`, the `guest_id` it acts for, the `ride_id` the skip applies to, and the `plan_id` of the plan to purchase under. The purchase is born `ACTIVE`, recording its `charged_cents`. The same boarding gates that protect reservations protect a purchase: a guest below the ride's `min_height_cm` is rejected with `ERR_HEIGHT_REQUIREMENT_NOT_MET`, and a wheelchair-using guest on a transfer-required ride is rejected with `ERR_ACCESSIBILITY_BLOCKED`. The guest must also be under the plan's hold ceiling: counting that guest's `ACTIVE` Lightning Lane purchases, the count must be strictly below the plan's `max_concurrent_holds` before another is bought; at or above the ceiling the purchase is rejected with `ERR_HOLD_LIMIT_REACHED`.

The price is computed at purchase, not supplied. First the system derives whether the target ride is loaded enough to surge. It measures the ride's load as its `booked_slot_count` divided by the greater of 1 and the total `slot_capacity` summed across the ride's `OPEN` and `EXHAUSTED` windows; the ride contributes a `PEAK` posture when that load is at or above the ride-peak-load threshold of 0.75, and an `OPEN` posture otherwise. Taking the plan's `price_cents` as the base, when the posture is `PEAK` the base is multiplied by the plan's `surge_multiplier` to give a surged figure; when the posture is `OPEN` the surged figure is simply the base with no multiplier. Then the tier cap is applied before rounding: for a `SINGLE_PASS` plan the charge is the lesser of the surged figure and the single-pass cap of 9900 cents, after which it is rounded half-up to whole cents; for a `MULTI_PASS` plan the surged figure is rounded half-up to whole cents directly. The cap is therefore taken first and the rounding second — that order is fixed. The result is stored as `charged_cents`.

A `RideOperator` scans a guest into the premium line by redeeming the purchase, allowed only while the purchase is `ACTIVE` and the parent ride is `OPEN`; redemption moves the purchase `ACTIVE → CONSUMED`. The `hold_status` of a purchase ranges over `ACTIVE`, `CONSUMED`, and `REFUNDED`, with `CONSUMED` and `REFUNDED` both terminal.

### 3.7. Ride Breakdowns, Redistribution, and Restoration

A ride does not always run. A `RideOperator` declares a ride down, allowed only when the ride is `OPEN`. Declaring down is the system's most far-reaching cascade. The ride moves `OPEN → DOWN`. Every child window currently `OPEN` or `EXHAUSTED` is suspended, moving to `SUSPENDED`. Every reservation on the ride in `BOOKED` status is redistributed: it moves `BOOKED → REDISTRIBUTED`, its `redistributed_from_window_id` is set to the window it currently occupies, and that old window's `reserved_count` and the ride's `booked_slot_count` are each decremented by one. Every Lightning Lane purchase on the ride in `ACTIVE` status is refunded as compensation: it moves `ACTIVE → REFUNDED`, and its `charged_cents` is credited back. After these effects, the ride's `booked_slot_count` is recomputed (it falls to the count of remaining held or booked reservations, which is zero once all booked reservations have been redistributed) and its `posted_wait_minutes` is recomputed.

Bringing a ride back is a `RideOperator`'s restore, allowed only when the ride is `DOWN`. The ride moves `DOWN → OPEN`. Each child window that is `SUSPENDED` and whose `window_end_utc` is still after the park's `current_utc` returns to `OPEN`; a `SUSPENDED` window whose end has already elapsed (its `window_end_utc` at or before `current_utc`) instead becomes `EXPIRED`. The ride's `posted_wait_minutes` is recomputed. Restoring does not by itself re-home the reservations that were redistributed during the down episode; those remain `REDISTRIBUTED` until the operator runs redistribution.

Redistribution re-homes a ride's stranded reservations, performed by the `RideOperator`. For each reservation on the ride in `REDISTRIBUTED` status, the system selects a replacement window on the same ride: among that ride's windows that are `OPEN`, have room (`reserved_count` strictly below `slot_capacity`), and have a `window_end_utc` still after the park's `current_utc`, it picks the one with the earliest `window_start_utc`, breaking ties by the earliest `created_at`. A reservation that finds a replacement has its `return_window_id` set to the chosen window, moves `REDISTRIBUTED → BOOKED`, and increments the replacement window's `reserved_count` and the ride's `booked_slot_count` each by one; if that increment fills the replacement window, the window bubbles to `EXHAUSTED`. A reservation for which no qualifying replacement window exists stays `REDISTRIBUTED`, and the redistribute call surfaces `ERR_NO_REPLACEMENT_WINDOW` for the unplaced reservations. The response reports the count of re-homed reservations, the list of re-homed reservation identifiers, and the list of any unplaced reservation identifiers.

Closing a ride ends its day. A `RideOperator` closes a ride that is `OPEN`; the ride moves `OPEN → CLOSED`, every child window not already `EXPIRED` is set to `EXPIRED`, and every reservation still in `HELD` or `BOOKED` is forfeited to `FORFEITED`. `CLOSED` is terminal for a ride, and `operational_status` ranges over `OPEN`, `DOWN`, and `CLOSED`.

### 3.8. Posted Wait Times and Live Counters

A ride advertises a standby estimate through `posted_wait_minutes`, recomputed whenever a reservation is confirmed, redeemed, or forfeited and whenever the ride changes operational posture. A ride that is not operating posts zero: when the ride's `operational_status` is `DOWN` or `CLOSED`, `posted_wait_minutes` is 0 regardless of its booked load, serving as a not-operating sentinel. When the ride is `OPEN`, the estimate models how long it takes to clear the standby demand: standby demand is the ride's `booked_slot_count` plus a baseline of 20 notional standby guests, and the posted wait is that demand divided by the ride's `hourly_throughput`, multiplied by 60 to convert hours to minutes, then rounded up to the next whole minute. The estimate is never negative. The `booked_slot_count` that feeds this figure is the count of the ride's `VIRTUAL_QUEUE` reservations in `HELD` or `BOOKED` status, kept current by every debit and credit described above.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or otherwise act on an existing resource — including admissions, exits, window advancement, ride posture changes, redistribution, reservation transitions, party transitions, purchase redemption, and the clock-setting capability — return `200 OK`. All endpoints are mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parks` | Create a park | ParkAdmin |
| GET | `/parks/{id}` | Read a park including computed admitted_count and day_phase | ParkAdmin, RideOperator, GuestApp |
| POST | `/parks/{id}/admissions` | Admit a guest's day ticket through the gate | ParkAdmin |
| POST | `/parks/{id}/exits` | Exit an admitted guest through the gate | ParkAdmin |
| POST | `/parks/{id}/advance-windows` | Advance/expire elapsed return windows; cascade forfeits | ParkAdmin |
| POST | `/_clock/set_current_utc` | Set the park logical clock for window comparisons | ParkAdmin |
| POST | `/parks/{id}/rides` | Create a ride under a park | ParkAdmin |
| GET | `/parks/{id}/rides` | List rides for a park | ParkAdmin, RideOperator, GuestApp |
| GET | `/rides/{id}` | Read a ride including posted_wait_minutes and operational_status | ParkAdmin, RideOperator, GuestApp |
| POST | `/rides/{id}/return-windows` | Create a return window for a ride | ParkAdmin |
| GET | `/rides/{id}/return-windows` | List return windows of a ride | ParkAdmin, RideOperator, GuestApp |
| GET | `/return-windows/{id}` | Read a return window including reserved_count and window_status | ParkAdmin, RideOperator, GuestApp |
| POST | `/rides/{id}/declare-down` | Declare the ride down; suspend windows, redistribute, refund holds | RideOperator |
| POST | `/rides/{id}/restore` | Restore a down ride; un-suspend still-valid windows | RideOperator |
| POST | `/rides/{id}/close` | Close the ride for the day | RideOperator |
| POST | `/rides/{id}/redistribute` | Re-home redistributed reservations into replacement windows | RideOperator |
| POST | `/parks/{id}/guests` | Create a guest profile under a park | ParkAdmin, GuestApp |
| GET | `/parks/{id}/guests` | List guests of a park | ParkAdmin, GuestApp |
| GET | `/guests/{id}` | Read a guest including current party_id | ParkAdmin, RideOperator, GuestApp |
| GET | `/guests` | List/filter guests across the system | ParkAdmin, GuestApp |
| POST | `/parks/{id}/day-tickets` | Issue a day ticket for a guest | ParkAdmin |
| GET | `/parks/{id}/day-tickets` | List day tickets of a park | ParkAdmin |
| GET | `/day-tickets/{id}` | Read a single day ticket including admission_status | ParkAdmin |
| GET | `/day-tickets` | List/filter day tickets across the system | ParkAdmin |
| POST | `/parks/{id}/parties` | Create a party led by a guest | GuestApp |
| GET | `/parks/{id}/parties` | List parties of a park | ParkAdmin, GuestApp |
| GET | `/parties/{id}` | Read a party including member_count and party_status | ParkAdmin, GuestApp |
| GET | `/parties` | List/filter parties across the system | ParkAdmin, GuestApp |
| POST | `/parties/{id}/members` | Link a guest into a party | GuestApp |
| GET | `/parties/{id}/members` | List memberships of a party | ParkAdmin, GuestApp |
| GET | `/party-memberships/{id}` | Read a single party membership including membership_status | ParkAdmin, GuestApp |
| GET | `/party-memberships` | List/filter party memberships across the system | ParkAdmin, GuestApp |
| DELETE | `/parties/{id}/members/{guest_id}` | Unlink a guest from a party | GuestApp |
| POST | `/parties/{id}/party-book` | Book virtual-queue reservations for eligible members | GuestApp |
| POST | `/parties/{id}/release-lock` | Release a locked party back to forming | GuestApp |
| POST | `/parties/{id}/disband` | Disband a forming party | GuestApp |
| POST | `/parks/{id}/entitlement-plans` | Create a Lightning Lane entitlement plan | ParkAdmin |
| GET | `/parks/{id}/entitlement-plans` | List entitlement plans of a park | ParkAdmin, GuestApp |
| POST | `/lightning-lane-purchases` | Buy a Lightning Lane line-skip for a guest on a ride | GuestApp |
| GET | `/lightning-lane-purchases` | List Lightning Lane purchases; filterable | ParkAdmin, RideOperator, GuestApp |
| GET | `/lightning-lane-purchases/{id}` | Read a Lightning Lane purchase including charged_cents and hold_status | ParkAdmin, RideOperator, GuestApp |
| POST | `/lightning-lane-purchases/{id}/redeem` | Scan the guest into the premium line | RideOperator |
| POST | `/reservations` | Create a virtual-queue or single-rider reservation | GuestApp |
| GET | `/reservations` | List reservations; filterable | ParkAdmin, RideOperator, GuestApp |
| GET | `/reservations/{id}` | Read a reservation including reservation_status and redistributed_from_window_id | ParkAdmin, RideOperator, GuestApp |
| POST | `/reservations/{id}/confirm` | Confirm a held reservation into booked | GuestApp |
| POST | `/reservations/{id}/redeem` | Scan a booked reservation in during its window | RideOperator |
| POST | `/reservations/{id}/cancel` | Cancel a held reservation, freeing the slot | GuestApp |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_HEIGHT_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ACCESSIBILITY_BLOCKED` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_REDEEMABLE` | 422 Unprocessable Entity |
| `ERR_PEAK_GATE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_VQ_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_HOLD_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_WINDOW_EXHAUSTED` | 409 Conflict |
| `ERR_PARK_AT_CAPACITY` | 409 Conflict |
| `ERR_NO_REPLACEMENT_WINDOW` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_LEADER_REMOVAL_FORBIDDEN` | 409 Conflict |
| `ERR_GUEST_PARK_MISMATCH` | 422 Unprocessable Entity |
