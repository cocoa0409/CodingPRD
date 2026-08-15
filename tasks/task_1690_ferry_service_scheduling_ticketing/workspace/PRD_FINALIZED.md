# Ferry Service Scheduling & Ticketing API — Product Requirements Document

## 1. Introduction

Operating a scheduled vehicle-and-passenger ferry service is an exercise in dividing finite, perishable inventory under rules that nobody may bend on the day of departure. A vessel's vehicle deck is measured in linear feet and its certificate fixes a maximum passenger count; both must be apportioned between travelers who reserved ahead and the standby lane that forms at the terminal, and that apportionment has to survive weather cancellations, fare revisions, crew shortfalls, and the queue-jumping pressures of a holiday weekend. This document specifies the Ferry Service Scheduling & Ticketing API, the system of record for that operation: route and vessel registration, seasonal fare schedules with an approval chain, sailing scheduling, reservation and standby management, terminal boarding, and Coast Guard manning compliance.

The API serves four operator constituencies with sharply different concerns. A central scheduling authority owns the network definition — routes, vessels, fare schedules, the sailing lifecycle, customer registration, and the logical clock used for testing. Terminal staff run the dock: they open boarding, check travelers in, board them, work the standby lane, and sail the vessel. A crew planning office staffs every departure to regulatory minimums. And travelers themselves create, confirm, modify, cancel, and rebook their own reservations and queue entries. Every one of these actors reads from the same computed capacity counters, so a deck foot held by a reservation at quote time is the same deck foot the standby sweep cannot hand out at boarding.

Two design commitments shape everything that follows. First, consistency is immediate: when a sailing is cancelled, the booking cancellations, refund credits, standby expirations, and crew releases that follow are applied as one visible cascade, not reconciled later. Second, money is pinned early and re-pinned only at defined moments: a reservation carries the fare quoted when it was created, settles that fare at confirmation, and re-quotes only when the fare schedule it pinned has since been retired. The remainder of this document defines the global contracts (§2), the business workflows (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four roles: `SchedulerAdmin`, `TerminalAgent`, `Customer`, and `CrewPlanner`. A request that arrives without both headers, or whose `X-User-Role` value does not name one of these four roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer — a booking's `customer_id`, a standby entry's `customer_id` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `SchedulerAdmin`, `TerminalAgent`, or `CrewPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

The division of authority is peer-style rather than hierarchical: `SchedulerAdmin` owns network configuration (routes, vessels, fare schedules, sailing open/close/cancel, customer registration, and the logical clock); `TerminalAgent` owns the dock (begin-boarding, depart, complete, check-in, board); `CrewPlanner` owns the crew roster and assignments; and `Customer` owns its own bookings and standby entries. Read endpoints are broadly shared across all four roles, subject to the per-endpoint authorization table in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets how many items to skip before the returned window and defaults to 0.

Unless an endpoint documents otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order — oldest first.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count` (the full count of matching resources, not just the returned page), and `has_more` (whether additional items exist beyond the current window).

### 2.4. The Logical Clock

Time inside the system is governed by a server-maintained logical clock, not by the host machine's wall clock. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z` as a fixed server default; it never falls back to wall-clock time. A `SchedulerAdmin` advances the clock through a test-driving capability that sets the current UTC instant from a supplied `to_iso8601` value and returns the resulting `current_utc`.

The logical clock drives fare-schedule seasonality. Advancing the clock evaluates every `APPROVED` fare schedule whose effective window now covers the current instant and promotes it to `EFFECTIVE`, retiring whichever schedule previously held that route-and-season slot; schedules whose window has passed retire as well. The same evaluation also runs lazily whenever a fare schedule is read or consulted, so time-driven transitions are visible even between explicit clock sets. The full lifecycle is described in §3.2.

### 2.5. Common Resource Properties

Every primary resource in the API — routes, vessels, fare schedules, sailings, customers, bookings, standby queue entries, crew members, and crew assignments — carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 and increments by 1 on every mutation of the resource, including system-driven mutations such as state-machine transitions and computed-counter recomputation.

All entities in this system carry the full common set; there are no reduced-field resources. Timestamp fields describing business events rather than record bookkeeping — a sailing's `departure_time` and `arrival_time`, a fare window's `effective_from` and `effective_to`, a crew shift's `shift_start` and `shift_end`, a standby entry's `queued_at` — are likewise ISO 8601 UTC instants. Every timestamp the server itself generates — `created_at`, `updated_at`, `api_request_timestamp`, the logical clock's returned `current_utc`, and the server-stamped business timestamps such as `arrival_time` and `queued_at` — is rendered in one canonical form: ISO 8601 UTC with exactly three fractional digits and a `Z` suffix (for example, `2026-09-01T10:35:00.000Z`). Timestamps supplied by the client in a request — `departure_time`, `effective_from`, `effective_to`, `shift_start`, and `shift_end` — are stored and returned exactly as supplied, without re-rendering or normalization.

### 2.6. Monetary Values and Precision

All monetary amounts in the system are integer counts of cents — fare components, surcharges, quoted and settled fares, and refund credits alike. No fractional cents exist anywhere in the API, and responses render these fields as integers.

Exactly one calculation in the system performs rounding: the peak-season vehicle multiplier described in §3.5. When it applies, the fully computed vehicle component is multiplied and then rounded half-up to whole cents before being combined with the other components. Every other monetary operation is exact integer arithmetic, and the half-up rule is the only rounding mode the system recognizes.

### 2.7. Deck Space, Pools, and Capacity Doctrine

A vessel's vehicle deck is a single linear-feet budget, `vehicle_deck_linear_feet`, and its certificate fixes `passenger_capacity`. Each sailing divides the deck into two pools at the moment booking opens: a **reservation pool** (`reserved_deck_allotment_feet`) that reservations draw against from quote time onward, and a **standby pool** (the remainder) that the standby lane competes for at boarding. The split is computed once and frozen for the sailing's life; it never rebalances afterward.

Two invariants hold for the life of every sailing. First, the reservation pool plus the standby pool always equals the vessel's full deck footage — the pools are a partition, never an overlap. Second, reservations hold deck space from the moment they are quoted: the sailing's `reserved_vehicle_feet` counter sums vehicle lengths across bookings in `RESERVED`, `CONFIRMED`, `MODIFIED`, `CHECKED_IN`, and `BOARDED` status, so an unconfirmed reservation genuinely excludes that footage from everyone else. Passenger counts behave the same way through `booked_passengers`, which sums `passenger_count` over those same booking statuses and additionally includes passengers from standby entries that have already cleared. `standby_cleared_feet` tracks cleared standby vehicle footage separately so the standby sweep can measure its own consumption.

A sailing also exposes `manning_ok`, a computed boolean that is true exactly when the manning compliance rule of §2.8 currently passes, and `arrival_time`, computed at scheduling as the departure instant plus the route's crossing time. Operators who want to see how a different reservation-to-standby ratio would divide the same deck can consult a read-only what-if projection capability, described in §3.4, which recomputes the split under a caller-supplied ratio without touching the pinned allotment.

### 2.8. Manning and Safety Governance

No sailing opens for booking and no sailing begins boarding unless its assigned crew satisfies the Coast Guard manning table for the vessel's `crew_class`, counted over that sailing's crew assignments currently in `ASSIGNED` status, joined to each member's `credential_class`:

- `SMALL` vessels require at least 1 `CAPTAIN` and at least 1 `DECK`.
- `MEDIUM` vessels require at least 1 `CAPTAIN`, at least 2 `DECK`, and at least 1 `ENGINE`.
- `LARGE` vessels require at least 1 `CAPTAIN`, at least 3 `DECK`, and at least 2 `ENGINE`.

A passenger-load escalator applies on top of the class minimums: when a sailing's `booked_passengers` is strictly greater than 500, the required `DECK` count rises by one. Exactly 500 passengers does not trigger the extra deckhand — the threshold is exclusive.

Manning compliance is re-evaluated on every crew assignment creation or release, and it is a hard precondition at two lifecycle gates: opening a sailing for booking and beginning boarding. An attempt to pass either gate, or to release a crew assignment whose removal would break the table for a sailing still relying on it, is rejected with `ERR_MANNING_SHORTFALL` (HTTP 409).

### 2.9. Optimistic Concurrency Control

One write operation in the API is guarded by optimistic concurrency control: creating a fare schedule draft under a route. The request must carry `expected_route_version`, the client's last-observed `version` of the owning route. If the route's current `version` has advanced past that value — because another writer created a fare schedule against the same route in the interim, an action which itself increments the route's `version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a scheduler from drafting a season's fares on top of a route state they have not observed. No other endpoint accepts a version field; every other write proceeds without an OCC check.

### 2.10. Nested Resource Retrieval

Requests that address nested resources validate path identifiers left to right. A fare-schedule create under a route first resolves the `route_id` path parameter; a booking create first resolves the `sailing_id` in the path; a crew-assignment create likewise resolves its sailing before touching the crew member named in the payload. The first identifier that does not correspond to an existing resource terminates the request with `ERR_NOT_FOUND` (HTTP 404), and no later segment is consulted.

### 2.11. Validation Ordering

When a request fails several rules at once, the error it receives is deterministic. Every endpoint evaluates its checks in this fixed priority order:

1. Authentication headers present and role recognized — otherwise `ERR_UNAUTHENTICATED`.
2. Role authorized for this endpoint — otherwise `ERR_FORBIDDEN`.
3. Path identifiers exist, left to right — otherwise `ERR_NOT_FOUND`.
4. Target resource in a legal state for the requested transition — otherwise `ERR_INVALID_STATE`.
5. Sailing posture permits the requested ticketing activity — otherwise `ERR_SAILING_NOT_BOOKABLE`.
6. Fare-schedule window well-formed and non-overlapping — otherwise `ERR_SCHEDULE_WINDOW_CONFLICT`.
7. Customer acting on its own resources — otherwise `ERR_NOT_RESOURCE_OWNER`.
8. Manning minimums satisfied — otherwise `ERR_MANNING_SHORTFALL`.
9. Vessel schedule free of buffered overlap — otherwise `ERR_VESSEL_SCHEDULE_CONFLICT`.
10. Crew rest and shift-overlap rules satisfied — otherwise `ERR_CREW_REST_CONFLICT`.
11. Party specification well-formed — otherwise `ERR_INVALID_PARTY_SPEC`.
12. Standby vehicle length within the staging limit — otherwise `ERR_VEHICLE_LENGTH_EXCEEDS`.
13. An `EFFECTIVE` fare schedule covers the sailing — otherwise `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`.
14. Reservation pool and passenger capacity sufficient — otherwise `ERR_CAPACITY_EXCEEDED`.
15. `expected_route_version` matches the route's current version — otherwise `ERR_STALE_VERSION`.
16. Uniqueness constraints — otherwise `ERR_DUPLICATE`.

The ordering matters operationally: an unauthenticated request always fails as 401 even when its path is nonsense; a state-machine violation surfaces as `ERR_INVALID_STATE` before the sailing-posture check can produce `ERR_SAILING_NOT_BOOKABLE`; and a fare-schedule create whose window conflicts surfaces as `ERR_SCHEDULE_WINDOW_CONFLICT` before its stale-version check would surface as `ERR_STALE_VERSION`.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Routes and Vessels

Everything begins with a `SchedulerAdmin` defining the network. A **Route** is created with a short unique `route_code` (for example, `SEA-BI`), an `origin_terminal`, a `destination_terminal`, a `crossing_minutes` value giving the scheduled crossing time (a positive integer), and a `turnaround_minutes` value giving the minimum buffer between a vessel's arrival and its next departure on any route (zero or greater). A newly created route starts with `status` set to `ACTIVE`, which is the only route status in this version of the system. Route codes are unique: reusing an existing `route_code` is rejected with `ERR_DUPLICATE`.

Vessels are registered alongside routes. A **Vessel** record carries a unique `vessel_name`, the deck budget `vehicle_deck_linear_feet` (a positive integer), the certificated `passenger_capacity` (a positive integer), and a `crew_class` of `SMALL`, `MEDIUM`, or `LARGE` that drives the manning table of §2.8. New vessels enter service immediately with `status` set to `IN_SERVICE`; duplicate vessel names are rejected with `ERR_DUPLICATE`. A vessel can later be taken out of service, moving its `status` to `OUT_OF_SERVICE` — and when that happens, every still-`SCHEDULED` sailing using that vessel is cancelled with `cancel_reason` set to `MECHANICAL`, firing the full cancellation cascade of §3.8.

The `turnaround_minutes` buffer is enforced at sailing-scheduling time: no two non-`CANCELLED` sailings may assign the same vessel to voyages whose occupied windows intersect. A vessel is occupied from its `departure_time` until its `arrival_time` plus the route's turnaround buffer, treated as a half-open interval; a new sailing whose own occupied window touches that interval is rejected with `ERR_VESSEL_SCHEDULE_CONFLICT`.

### 3.2. Fare Governance: Drafting, Submission, and the Seasonal Hand-Off

Fares are versioned, seasonal, and approved through a formal chain. A `SchedulerAdmin` drafts a **FareSchedule** under a specific route by supplying the `season` it governs (`PEAK` or `OFF_PEAK`), the effective window as `effective_from` (inclusive) and `effective_to` (exclusive), and the full component price list: `passenger_standard_cents`, `passenger_resident_cents`, and `passenger_commuter_cents` for the three traveler classes; `vehicle_standard_base_cents` for vehicles under 22 feet (driver included); `vehicle_oversize_base_cents` for vehicles 22 feet and over (driver included); and `vehicle_overlength_per_foot_cents`, the per-foot surcharge applied to each foot at or beyond 22. A draft also carries a `fuel_surcharge_cents` value, although — as described below — submission overwrites it. The create is the system's one OCC-guarded write: it must carry `expected_route_version` matching the route's current `version` or it fails with `ERR_STALE_VERSION`, and a successful create increments the route's `version` by 1, which is precisely what makes a second, concurrent drafter's version stale. A new draft starts in `DRAFT`.

Submission moves the draft `DRAFT → SUBMITTED` and does real work. The caller supplies `fuel_price_index_cents`, and the system re-pins the surcharge from it: an index below 300 cents yields a `fuel_surcharge_cents` of 0; an index of at least 300 but below 500 yields 100; an index of 500 or more yields 250. An index of exactly 300 therefore produces 100, and exactly 500 produces 250. The submission is also where window integrity is enforced: `effective_from` must be strictly earlier than `effective_to`, and no other fare schedule for the same route and season may hold `SUBMITTED`, `APPROVED`, or `EFFECTIVE` status with an overlapping effective window. Violations of either clause are rejected with `ERR_SCHEDULE_WINDOW_CONFLICT`. The owning route must be `ACTIVE` at submission.

From `SUBMITTED`, three outcomes are possible, all performed by `SchedulerAdmin` and each incrementing the schedule's `version`. Approval moves the schedule `SUBMITTED → APPROVED`. Rejection moves it `SUBMITTED → REJECTED`, which is terminal. Returning for revision moves it `SUBMITTED → DRAFT` — the revision loop — after which the schedule may be edited and resubmitted through the same path.

The final transitions belong to the logical clock. When the current instant reaches an `APPROVED` schedule's `effective_from` while remaining before its `effective_to`, the schedule becomes `EFFECTIVE` — evaluated both when the clock is set and lazily whenever a fare schedule is read or consulted. That promotion retires any previously `EFFECTIVE` schedule for the same route and season (`EFFECTIVE → RETIRED`), and a schedule whose window has passed also retires. Retirement has a direct consequence for travelers: every booking that pinned the retired schedule via its `fare_schedule_id` and still sits in `RESERVED`, `CONFIRMED`, or `MODIFIED` is flagged for requote, meaning its `final_fare_cents` will be recomputed against the newly effective schedule at its next confirmation. `RETIRED` and `REJECTED` are the terminal states of the fare lifecycle.

### 3.3. Scheduling Sailings and Crewing Them

With a route, a vessel, and an effective fare schedule in place, a `SchedulerAdmin` schedules a **Sailing** by supplying the `vessel_id`, the `departure_time`, and the `season` (`PEAK` or `OFF_PEAK`) that selects which fare schedule governs. The server stamps `arrival_time` as the departure instant plus the route's `crossing_minutes`, sets `status` to `SCHEDULED`, and enforces the vessel-overlap rule of §3.1. A sailing's computed counters — `reserved_vehicle_feet`, `standby_cleared_feet`, `booked_passengers`, `reserved_deck_allotment_feet`, and `manning_ok` — are visible on every read.

Crewing proceeds in parallel under the `CrewPlanner`. Crew members are registered with a `full_name` and a `credential_class` of `DECK`, `ENGINE`, or `CAPTAIN`, entering the roster in `AVAILABLE` status. Assigning a member to a sailing creates a **CrewAssignment** carrying the `crew_member_id` and a half-open shift interval from `shift_start` to `shift_end` (the end must be strictly later than the start); the assignment starts in `ASSIGNED` status, the member moves `AVAILABLE → ASSIGNED`, and the sailing's `manning_ok` is recomputed. Two crew-protection rules guard assignment creation, both failing with `ERR_CREW_REST_CONFLICT`: no two `ASSIGNED` assignments for the same member may have overlapping half-open shift intervals, and any two such assignments must leave at least 480 minutes of rest between them. Releasing an assignment (`ASSIGNED → RELEASED`) is permitted only while the sailing has not departed — a sailing in `DEPARTED` status refuses releases with `ERR_INVALID_STATE` — and each release recomputes `manning_ok`; a member with no remaining `ASSIGNED` assignments returns to `AVAILABLE`. The `CrewPlanner` can also move a member `AVAILABLE → OFF_DUTY` and back `OFF_DUTY → AVAILABLE` as roster availability changes. Manually releasing an assignment whose removal breaks the manning table for a sailing that still requires it is rejected with `ERR_MANNING_SHORTFALL`.

### 3.4. Opening the Sailing: Pinning the Deck Split

A sailing in `SCHEDULED` becomes bookable when a `SchedulerAdmin` opens it, moving `SCHEDULED → OPEN_FOR_BOOKING`. Four preconditions gate the transition, and a failure on the manning or state legs surfaces as the corresponding error from §2.11: the route must be `ACTIVE`, the vessel must be `IN_SERVICE`, an `EFFECTIVE` fare schedule must exist for the sailing's route and season covering its `departure_time`, and `manning_ok` must be true.

Opening is the moment the deck split of §2.7 is computed and pinned. Let the vessel's deck be D feet and let the season's reservation ratio be seven-tenths of the deck for `PEAK` sailings or six-tenths for `OFF_PEAK` sailings. The raw reservation figure is that product rounded down to a whole foot. The pinned `reserved_deck_allotment_feet` is then the raw figure clamped on both sides: it never exceeds the deck minus a 40-foot standby floor, and it never falls below a 20-foot reservation floor — so even a tiny vessel keeps at least 20 reservable feet, and even a dominant reservation market leaves at least 40 feet for the standby lane. The standby pool is whatever remains, and the two pools always sum to D. For example, a 200-foot vessel sailing in `PEAK` season pins 140 feet for reservations (seven-tenths of 200, already whole) and 60 feet for standby; in `OFF_PEAK` it would pin 120 and 80.

Operators sometimes want to see a different split before deciding policy — for instance, how a 0.75 ratio would divide the same deck. A read-only what-if projection capability accepts a `ratio` and returns the `reserved_deck_allotment_feet` and `standby_pool_feet` that ratio would produce for the same vessel, applying the same floors and rounding. This projection never mutates the sailing: the pinned allotment is frozen at open time for the sailing's entire life.

Later, a `SchedulerAdmin` closes booking, moving `OPEN_FOR_BOOKING → BOOKING_CLOSED`. From that instant no new bookings and no new standby entries are accepted — attempts to create either against a sailing that is not `OPEN_FOR_BOOKING` are rejected with `ERR_SAILING_NOT_BOOKABLE`.

### 3.5. Reservations: Quoting, Confirming, Modifying, and the Traveler's Own Lifecycle

Travelers are registered by a `SchedulerAdmin` as **Customer** records with a `full_name`, a unique `email` (duplicates rejected with `ERR_DUPLICATE`), and a `fare_class` of `STANDARD`, `RESIDENT`, or `COMMUTER` fixed at registration. A new customer's `refund_credit_cents` — the ledger of operator-cancellation credit — starts at 0 and may never go negative.

A `Customer` creates a **Booking** against an `OPEN_FOR_BOOKING` sailing by supplying their `customer_id` (which must equal their `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`), a `passenger_count` covering travelers excluding any vehicle driver, a `has_vehicle` flag, and — exactly when `has_vehicle` is true — a `vehicle_length_feet` in whole feet. Party specifications are validated: a vehicle's length must be at least 1 and at most 80 feet when a vehicle is present, and malformed combinations (length missing when required, length supplied out of range) are rejected with `ERR_INVALID_PARTY_SPEC`. Capacity is enforced at quote time against the pinned pools: the requested vehicle feet must fit within the reservation pool after accounting for `reserved_vehicle_feet` already held, and the requested passengers must fit within `passenger_capacity` after `booked_passengers`; shortfalls are rejected with `ERR_CAPACITY_EXCEEDED`. Because reservations hold deck space from quote time, a successful create immediately joins the `RESERVED` population counted by both counters.

Every booking pins two things at creation: the `fare_schedule_id` of the schedule currently `EFFECTIVE` for the sailing's route and season (its absence fails with `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`), and a `quoted_fare_cents` computed from that schedule. The quote is assembled from up to three components, in this order. The passenger component multiplies `passenger_count` by the per-crossing rate matching the customer's `fare_class`: `passenger_standard_cents` for `STANDARD`, `passenger_resident_cents` for `RESIDENT`, or `passenger_commuter_cents` for `COMMUTER`. The vehicle component is zero when the booking brings no vehicle; otherwise it is the schedule's standard vehicle base when the vehicle is under 22 feet, or — at 22 feet and above — the oversize base plus the per-foot overlength surcharge for every foot beyond 21 (so a 22-foot vehicle pays the oversize base plus exactly one surcharge foot, while a 21-foot vehicle stays in the standard band). The fuel surcharge applies once per fare component present: the schedule's `fuel_surcharge_cents` is added once if `passenger_count` is at least 1, and once more if a vehicle is present. The quoted fare is the sum of the three components, all integer cents with no rounding.

One seasonal variant modifies the vehicle component only. On a `PEAK` sailing, the fully computed vehicle component — base plus any overlength surcharge — is multiplied by 1.25 and rounded half-up to whole cents before the passenger and surcharge components are added. Rounding each per-foot surcharge first and then summing is forbidden, because it yields different cents; the multiplier applies to the complete vehicle figure exactly once. `OFF_PEAK` sailings use the base formula with no multiplier.

Confirmation settles the fare. A customer confirming their own booking — from `RESERVED → CONFIRMED`, and identically from `MODIFIED → CONFIRMED` to close the modify loop — requires the sailing to be in `OPEN_FOR_BOOKING` or `BOOKING_CLOSED` and re-checks capacity. If the pinned schedule is still `EFFECTIVE`, `final_fare_cents` settles equal to `quoted_fare_cents`; if the pinned schedule has since been `RETIRED`, the fare is re-quoted against the schedule currently `EFFECTIVE` for the sailing's route and season before settling, honoring the requote flag raised at retirement (§3.2). Should no `EFFECTIVE` schedule cover that route and season at confirmation time, the confirm is rejected with `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`, exactly as at creation. Confirmation recomputes the sailing's counters and increments the booking's `version`.

Modification loops through `MODIFIED`. A customer may modify a `CONFIRMED` booking while the sailing is `OPEN_FOR_BOOKING`, changing `passenger_count`, `has_vehicle`, or `vehicle_length_feet`; the booking moves to `MODIFIED`, its fields are replaced by the modification payload, and `quoted_fare_cents` is recomputed against the pinned schedule. Growth is capacity-checked: if the modification adds a vehicle or lengthens it, the requested feet must fit the reservation pool's remaining space, else `ERR_CAPACITY_EXCEEDED`. The booking then confirms back through the ordinary confirmation path, closing `MODIFIED → CONFIRMED`.

Customer-initiated cancellation distinguishes settled from unsettled fares. Cancelling a `RESERVED` booking settles nothing and refunds nothing — the reservation simply releases its held space and the sailing's aggregates are recomputed. Cancelling a `CONFIRMED` booking is permitted only while the sailing is `OPEN_FOR_BOOKING`; it credits the customer's `refund_credit_cents` by the booking's `final_fare_cents` and recomputes the sailing's `reserved_vehicle_feet` and `booked_passengers`.

### 3.6. The Standby Lane

Travelers without reservations queue in the standby lane. A `Customer` joins by creating a **StandbyQueueEntry** against an `OPEN_FOR_BOOKING` sailing with their `customer_id` (ownership-checked as with bookings), a `has_vehicle` flag with `vehicle_length_feet` required exactly when a vehicle is queued, a `passenger_count` of at least 1 for the party, and a `priority_class` of `MEDICAL`, `COMMUTER`, or `STANDARD`. The server stamps `queued_at` at join time — the queue's ordering key — and the entry starts `WAITING`. Two standby-specific constraints apply beyond the shared party rules: a customer may hold at most one `WAITING` entry per sailing (a second join is `ERR_DUPLICATE`), and standby vehicles longer than 60 feet cannot be staged in the lane at all, rejected with `ERR_VEHICLE_LENGTH_EXCEEDS` even though a reserved booking may legally carry up to 80 feet.

A waiting customer may leave the lane at any time, moving their own entry `WAITING → EXPIRED`; the entry's `customer_id` must match the acting `X-User-ID` (else `ERR_NOT_RESOURCE_OWNER`), and only a `WAITING` entry may be left this way — attempting to leave from any other status is rejected with `ERR_INVALID_STATE`. Entries are also expired or refused by system events described in §3.7 and §3.8.

### 3.7. Boarding, Departure, and Arrival

The dock belongs to the `TerminalAgent`. Once booking is closed, beginning boarding moves the sailing `BOOKING_CLOSED → BOARDING`; the gate requires `manning_ok` to still hold, failing with `ERR_MANNING_SHORTFALL` otherwise. Beginning boarding fires the standby clearance sweep as a single pass over the lane.

The sweep considers entries still `WAITING`, ranked first by priority band — `MEDICAL` highest, then `COMMUTER`, then `STANDARD` — and within a band by `queued_at`, earliest first; because `queued_at` is server-stamped unique, no deeper tie-break exists. Each entry is measured against what remains: its needed deck feet (its `vehicle_length_feet` if it has a vehicle, else 0) against the standby pool minus footage already cleared in this sweep, and its `passenger_count` against the vessel's `passenger_capacity` minus the running booked-passenger count. An entry clears when both fit — an entry needing exactly the remaining footage clears, since the test is "no more than," not "strictly less" — moving `WAITING → CALLED → CLEARED` and debiting the running counters, with `standby_cleared_feet` and `booked_passengers` recomputed on the sailing. An entry that does not fit stays `WAITING` and the sweep moves on: skip-over is allowed, so a small later vehicle, or a walk-on party needing zero feet, can still clear behind an oversize one. When no footage remains, only walk-on entries can clear, subject to passenger capacity.

During boarding, checked-in travelers are processed individually. A `TerminalAgent` checks in a `CONFIRMED` booking (`CONFIRMED → CHECKED_IN`) once the sailing has closed booking — check-in is legal in `BOOKING_CLOSED` or `BOARDING` — and boards it (`CHECKED_IN → BOARDED`) once the sailing is `BOARDING`. Requests made against a sailing in the wrong posture fail with `ERR_SAILING_NOT_BOOKABLE`; a booking in the wrong status fails with `ERR_INVALID_STATE`.

Departure is the point of no return. The `TerminalAgent` departs a `BOARDING` sailing (`BOARDING → DEPARTED`), and two sweeps fire: every booking still `CONFIRMED` or `MODIFIED` — reserved, settled, but never checked in — becomes `NO_SHOW` with its fare forfeited (no refund credit is issued), and its vehicle feet and passenger counts are released as the counters are recomputed; and every standby entry still `WAITING` or `CALLED` but not `CLEARED` becomes `NO_BOARD`.

Completion closes the voyage. A `TerminalAgent` completes a `DEPARTED` sailing (`DEPARTED → COMPLETED`): all `BOARDED` bookings become `COMPLETED`, all crew assignments still `ASSIGNED` are released, and each crew member left with no remaining `ASSIGNED` assignments anywhere returns to `AVAILABLE`.

### 3.8. Cancellation, Refunds, and Rebooking

A `SchedulerAdmin` may cancel a sailing from any pre-departure posture — `SCHEDULED`, `OPEN_FOR_BOOKING`, `BOOKING_CLOSED`, or `BOARDING` — supplying a `cancel_reason` of `WEATHER`, `TIDES`, `MECHANICAL`, `CREW_SHORTAGE`, or `OTHER`. Cancellation is a three-hop cascade applied immediately. First, every booking in `RESERVED`, `CONFIRMED`, `MODIFIED`, or `CHECKED_IN` moves to `CANCELLED`, and for each booking that had settled a fare, the customer's `refund_credit_cents` increases by that booking's `final_fare_cents` (bookings cancelled from `RESERVED` had settled nothing and generate no credit). Second, every standby entry in `WAITING` or `CALLED` moves to `EXPIRED`. Third, every crew assignment still `ASSIGNED` is released, and each crew member with no remaining assignments returns to `AVAILABLE`. One nuance applies when cancellation strikes mid-boarding: standby entries already `CLEARED` remain `CLEARED` — their travelers are ashore-side and counted — but they are never charged. The sailing itself lands in `CANCELLED` with the reason recorded.

Refunded customers hold their credit on `refund_credit_cents` until they rebook. A customer whose booking was cancelled by the operator — that is, whose sailing itself sits in `CANCELLED` — may rebook onto a different sailing by naming a `target_sailing_id`. The target must be `OPEN_FOR_BOOKING` with sufficient reservation-pool capacity for the same party and vehicle, failing with `ERR_CAPACITY_EXCEEDED` or `ERR_SAILING_NOT_BOOKABLE` as appropriate. A successful rebook creates a fresh booking on the target sailing directly in `CONFIRMED` status with the same `passenger_count` and vehicle specifications as the original; the new booking's `final_fare_cents` carries over from the cancelled booking exactly — no additional charge if the new sailing is dearer, no refund of the difference if cheaper. The customer's credit is consumed: `refund_credit_cents` decreases by the carried fare. The old booking then moves `CANCELLED → REBOOKED`, its `rebooked_to_booking_id` pointing at the successor. Rebooking a booking that the customer cancelled voluntarily is not permitted — the operator-cancellation precondition fails, and the request is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/ferry` prefix. Operations that create a new resource — a route, vessel, fare-schedule draft, sailing, customer, booking, standby entry, crew member, or crew assignment — return `201 Created`. Operations that act on an existing resource, including all state-transition actions and reads, return `200 OK`. Request and response shapes follow the envelope of §2.2, and the authoritative account of each operation's preconditions and effects is the workflow narrative of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ferry/_clock/set_current_utc` | Set the logical clock; evaluates time-driven fare-schedule transitions | SchedulerAdmin |
| POST | `/ferry/routes` | Create a route | SchedulerAdmin |
| GET | `/ferry/routes/{id}` | Get a route | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/routes` | List routes | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/routes/{id}/fare-schedules` | List fare schedules for a route | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/routes/{id}/sailings` | List sailings for a route | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| POST | `/ferry/vessels` | Register a vessel | SchedulerAdmin |
| GET | `/ferry/vessels/{id}` | Get a vessel | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/vessels` | List vessels | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| POST | `/ferry/vessels/{id}/set-out-of-service` | Take a vessel out of service; cancels its SCHEDULED sailings | SchedulerAdmin |
| POST | `/ferry/routes/{route_id}/fare-schedules` | Create a fare schedule draft (OCC-guarded on the route's version) | SchedulerAdmin |
| GET | `/ferry/fare-schedules/{id}` | Get a fare schedule | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| POST | `/ferry/fare-schedules/{id}/submit` | Submit a draft; re-pins the fuel surcharge from the price index | SchedulerAdmin |
| POST | `/ferry/fare-schedules/{id}/approve` | Approve a submitted schedule | SchedulerAdmin |
| POST | `/ferry/fare-schedules/{id}/return-for-revision` | Return a submitted schedule to draft for revision | SchedulerAdmin |
| POST | `/ferry/fare-schedules/{id}/reject` | Reject a submitted schedule (terminal) | SchedulerAdmin |
| POST | `/ferry/routes/{route_id}/sailings` | Schedule a sailing | SchedulerAdmin |
| GET | `/ferry/sailings/{id}` | Get a sailing with computed counters | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/sailings` | List sailings across routes, optionally filtered by vessel | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/sailings/{id}/bookings` | List bookings on a sailing | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/sailings/{id}/standby-queue` | List standby queue entries for a sailing | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/sailings/{id}/crew-assignments` | List crew assignments for a sailing | SchedulerAdmin, TerminalAgent, CrewPlanner |
| GET | `/ferry/sailings/{id}/deck-projection` | What-if deck split under a caller-supplied ratio | SchedulerAdmin, TerminalAgent |
| POST | `/ferry/sailings/{id}/open-booking` | Open a sailing for reservations; pins the deck allotment | SchedulerAdmin |
| POST | `/ferry/sailings/{id}/close-booking` | Close reservations for a sailing | SchedulerAdmin |
| POST | `/ferry/sailings/{id}/begin-boarding` | Begin boarding; runs the standby clearance sweep | TerminalAgent |
| POST | `/ferry/sailings/{id}/depart` | Depart; no-show and no-board sweeps | TerminalAgent |
| POST | `/ferry/sailings/{id}/complete` | Complete the sailing after arrival; releases crew | TerminalAgent |
| POST | `/ferry/sailings/{id}/cancel` | Cancel a sailing with reason; full cascade | SchedulerAdmin |
| POST | `/ferry/customers` | Register a customer | SchedulerAdmin |
| GET | `/ferry/customers/{id}` | Get a customer | SchedulerAdmin, TerminalAgent, CrewPlanner, Customer |
| GET | `/ferry/customers/{id}/bookings` | List a customer's bookings | SchedulerAdmin, TerminalAgent, Customer |
| GET | `/ferry/customers/{id}/standby-queue` | List a customer's standby queue entries | SchedulerAdmin, TerminalAgent, Customer |
| POST | `/ferry/sailings/{sailing_id}/bookings` | Create a booking on an open sailing | Customer |
| GET | `/ferry/bookings/{id}` | Get a booking | SchedulerAdmin, TerminalAgent, Customer |
| GET | `/ferry/bookings` | List bookings across sailings, with filters | SchedulerAdmin, TerminalAgent, Customer |
| POST | `/ferry/bookings/{id}/confirm` | Confirm a reserved or modified booking; settles the fare | Customer |
| POST | `/ferry/bookings/{id}/modify` | Modify a confirmed booking's party or vehicle spec | Customer |
| POST | `/ferry/bookings/{id}/cancel` | Customer cancels own booking | Customer |
| POST | `/ferry/bookings/{id}/rebook` | Rebook an operator-cancelled booking onto another open sailing | Customer |
| POST | `/ferry/bookings/{id}/check-in` | Check in a confirmed booking at the terminal | TerminalAgent |
| POST | `/ferry/bookings/{id}/board` | Board a checked-in booking | TerminalAgent |
| POST | `/ferry/sailings/{sailing_id}/standby-queue` | Join the standby lane for a sailing | Customer |
| GET | `/ferry/standby-queue/{id}` | Get a standby queue entry | SchedulerAdmin, TerminalAgent, Customer |
| POST | `/ferry/standby-queue/{id}/leave` | Leave the standby lane | Customer |
| POST | `/ferry/crew-members` | Register a crew member | CrewPlanner |
| GET | `/ferry/crew-members/{id}` | Get a crew member | SchedulerAdmin, TerminalAgent, CrewPlanner |
| GET | `/ferry/crew-members/{id}/crew-assignments` | List assignments for a crew member | SchedulerAdmin, CrewPlanner |
| POST | `/ferry/crew-members/{id}/set-off-duty` | Mark a crew member off duty | CrewPlanner |
| POST | `/ferry/crew-members/{id}/set-available` | Return a crew member to available | CrewPlanner |
| POST | `/ferry/sailings/{sailing_id}/crew-assignments` | Assign a crew member to a sailing | CrewPlanner |
| POST | `/ferry/crew-assignments/{id}/release` | Release a crew assignment | CrewPlanner |
| GET | `/ferry/crew-assignments/{id}` | Get a crew assignment | SchedulerAdmin, CrewPlanner |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows they guard; this table is the authoritative list of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SAILING_NOT_BOOKABLE` | 409 |
| `ERR_SCHEDULE_WINDOW_CONFLICT` | 409 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_MANNING_SHORTFALL` | 409 |
| `ERR_VESSEL_SCHEDULE_CONFLICT` | 409 |
| `ERR_CREW_REST_CONFLICT` | 409 |
| `ERR_INVALID_PARTY_SPEC` | 400 |
| `ERR_VEHICLE_LENGTH_EXCEEDS` | 422 |
| `ERR_FARE_SCHEDULE_NOT_EFFECTIVE` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
