# Ride-Sharing Surge Pricing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a ride-sharing dynamic surge pricing platform. The platform models a city as a grid of geographic cells, called **Zones**, and continuously re-prices rides as the balance between open ride requests and idle drivers shifts within each cell. When demand outpaces supply, a surge multiplier lifts fares above a zone's base fare; when supply recovers, prices fall back toward baseline. A Heat Map view lets operators and participants see at a glance which zones are cool and which are blazing.

The system serves three kinds of actors. Riders request trips, cancel matched trips, and open disputes over completed fares. Drivers move between online and offline states, join airport pickup queues, and start and complete the trips assigned to them. A Dispatcher — the platform operator — onboards participants, publishes surge snapshots, runs the dispatch matching tick, expires stale requests, and adjudicates disputes. Around this core the platform layers several incentive and fairness mechanisms: a driver **Quest** bonus that rewards completing a target number of trips inside a time window, a first-in-first-out airport queue that overrides nearest-driver matching at airports, a rush-hour surcharge, a multiplier cap, and a dispute-driven refund path that returns money to a rider's prepaid wallet.

Because surge pricing turns on volatile, derived counters — how many requests are open, how many drivers are free — the system treats consistency as a first-class concern. Trip lifecycle events ripple through zone counters, driver positions, and quest progress in carefully ordered cascades, and surge snapshots are published under optimistic concurrency control so that a price computed against stale conditions can never silently overwrite a fresher one.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which the request is made. The system recognizes exactly three roles: `Rider`, `Driver`, and `Dispatcher`. If `X-User-Role` is missing or is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The roles differ in how `X-User-ID` ties to persisted data. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The Dispatcher is a platform operator that creates zones, riders, drivers, and quests, publishes surge snapshots, runs the dispatch tick, expires trips and quests, and resolves disputes. When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`; ownership checks on any resource that references a `Rider` compare the resource's rider foreign key to `X-User-ID`. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on any resource that references a `Driver` compare the resource's driver foreign key to `X-User-ID`.

Ownership is enforced for operations that an entity-backed actor performs on resources they own. Specifically, when a `Rider` starts, completes, or cancels actions that the rider must own, or a `Driver` acts on their own trips and queue entries, the acting user's `X-User-ID` must equal the relevant owner foreign key — a rider's `id` must equal the disputed or cancelled trip's `rider_id`, and a driver's `id` must equal the trip's `driver_id` when starting or completing a trip, or the queue entry's `driver_id` when withdrawing from a queue. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, rather than rejected. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` query value that is not a valid integer is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint explicitly states a different ordering, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Two list endpoints deviate from this default and say so in their workflow descriptions: the surge-snapshot list for a zone is returned newest first by `created_at` descending, and a zone's airport queue listing returns `WAITING` entries ordered by their FIFO `position` ascending (with `created_at` ascending as a tie-break), followed by any non-`WAITING` entries ordered by `created_at` ascending.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. Every `Zone`, `Driver`, `Rider`, `Trip`, `AirportQueueEntry`, `Quest`, and `Dispute` includes:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp recording the most recent modification; refreshed on every mutation.
- `version` — an integer that starts at its initial value and increments by one on each modification. It underpins optimistic concurrency control where applicable.

The `SurgeSnapshot` resource is an exception. A surge snapshot is an immutable event-log row: once published it is never modified. It therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

### 2.5. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one resource at once, and these cascades are part of the contract. Whenever a mutation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this applies equally to changes in derived counters and to lifecycle state changes. For example, publishing a surge snapshot increments the target `Zone`'s `version`, and crediting a rider's wallet increments that `Rider`'s `version`.

The most consistency-sensitive derived fields are a zone's two counters. `open_demand_count` tracks the number of trips whose pickup zone is this zone and whose status is `REQUESTED`. `available_supply_count` tracks the number of drivers whose current zone is this zone and whose status is `AVAILABLE`. Trip and driver lifecycle events keep these counters in step in real time, as described in §3. Counters are never allowed to go negative: any decrement that would push a counter below zero leaves it at zero (a floor of zero).

### 2.6. Nested Resource Retrieval and Existence Checks

Several endpoints address a resource through a path that names a parent first, such as a zone's surge-snapshot collection or a zone's airport queue. The system validates the existence of every referenced resource — whether named in the path or the body — in left-to-right order, covering `Zone`, `Driver`, `Rider`, `Trip`, `Quest`, `Dispute`, and `AirportQueueEntry`. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`, before any deeper validation runs.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary amounts are stored and exchanged as integer cents; there is no sub-cent rounding because cents are the smallest unit. Surge multipliers and demand-to-supply ratios are real numbers carried to exactly two decimal places, rounded half up. Wherever a fare or payout calculation multiplies cents by a multiplier and must yield a whole-cent result, the product is rounded half up to the nearest whole cent. The specific points at which rounding occurs are pinned in each calculation's narrative in §3 and must be followed exactly, because the order of rounding relative to additive steps changes the result.

### 2.8. Surge Pricing and the Heat Map

Surge pricing is governed entirely by published surge snapshots. Each `Zone` exposes a `current_multiplier`, a two-decimal number that equals the multiplier of the latest published snapshot for that zone, and a `heat_level`, an enumerated Heat Map bucket derived from that multiplier. Until a zone's first snapshot is published, its `current_multiplier` is 1.00 and its `heat_level` is `COOL`. The `heat_level` enumeration has exactly four values — `COOL`, `WARM`, `HOT`, and `BLAZING` — and the bands that map a multiplier to a bucket are specified in §3.

A multiplier is never allowed to run away without bound: the system enforces a hard multiplier cap, and a snapshot records whether its raw multiplier had to be clamped down to that cap. Rush hour adds a fixed surcharge step to the banded multiplier before the cap is applied. The exact thresholds, the rush-hour step, and the cap are described in the surge calculation in §3.

### 2.9. Optimistic Concurrency Control on Surge Publishing

Publishing a surge snapshot for a zone is the one operation guarded by optimistic concurrency control. A publish request must carry `expected_zone_version` as a required field, holding the client's last observed `version` of the target `Zone`. Publishing recomputes and overwrites the zone's `current_multiplier` and `heat_level`, a deliberate supersede of the prior snapshot; this is legitimate only when the snapshot prices the conditions the dispatcher actually observed. If `expected_zone_version` does not equal the zone's current `version` — because some intervening event, such as a trip lifecycle change that bumped the zone's demand or supply counters, has advanced the zone since the dispatcher last read it — the publish is rejected with `ERR_STALE_ZONE_VERSION` and HTTP status 412, since the snapshot would otherwise price stale conditions. No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.10. Validation Ordering

When several validations could apply to a single request, they are evaluated in a fixed priority order, and the first failing check determines the rejection. Authentication comes first: a missing or unknown `X-User-Role` yields `ERR_UNAUTHENTICATED`. Next the role's permission for the endpoint is checked, yielding `ERR_FORBIDDEN_ROLE` if the role is not authorized. On `POST` endpoints, however, the presence and type of the required request-body fields are validated before any body-referenced resource is looked up: a body that is missing a required field, carries a value of the wrong type, or carries an out-of-range enum or numeric value is rejected with `ERR_INVALID_REQUEST` ahead of the existence check for resources named only in the body (the resolve-dispute `decision` field follows this same body-before-state rule). Path-parameter resources are still resolved as part of existence. Then existence of every referenced resource is verified left-to-right, yielding `ERR_NOT_FOUND`. After existence, for entity-backed actors operating on resources they must own, ownership is checked, yielding `ERR_NOT_RESOURCE_OWNER`. Then, for transition endpoints, the target resource's current state is checked against the state machine, yielding `ERR_INVALID_STATE` when the requested transition is not defined from that state. Domain-specific business constraints — duplicate grid codes, airport-zone checks, queue eligibility, dispute preconditions, wallet sufficiency, window overlaps, the surge OCC check, and request-body field validation — follow, as described alongside the workflows in §3. As a general guardrail across every create and publish endpoint, a request whose body is missing a required field, carries an out-of-range enum, or violates a declared numeric constraint (such as a base fare below the minimum, a quest target below one, or a negative observed count) is rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Building the City: Zones and Onboarding

The Dispatcher lays out the city as a set of geo-grid cells. Creating a `Zone` supplies a human-readable `name` such as "Downtown-A1", a `grid_code` such as "A1", an optional `is_airport` flag, and a `base_fare_cents` amount. The `grid_code` is a geo-grid cell code conventionally written as an uppercase letter followed by a digit; the server validates only that it is a non-empty string and does not enforce that letter-then-digit shape, but the code must be unique across all zones, and an attempt to create a zone whose `grid_code` duplicates an existing one is rejected with `ERR_DUPLICATE_GRID_CODE`. The `base_fare_cents` is the fare charged before any surge multiplier and must be a required integer of at least 100 cents (a missing, non-integer, or below-100 value is rejected with `ERR_INVALID_REQUEST`). The `is_airport` flag defaults to false; airport zones use FIFO queue dispatch instead of nearest-driver matching. On creation, a zone's `open_demand_count` and `available_supply_count` both start at 0, its `current_multiplier` starts at 1.00, and its `heat_level` starts at `COOL`.

A `Rider` is onboarded by the Dispatcher with a `name`, a `home_zone_id` naming the rider's default pickup zone, and an optional starting `wallet_balance_cents`. The wallet balance is a prepaid balance in cents that defaults to 0 and may never be negative. The Dispatcher can later top up a rider's wallet through an operator funding capability that takes a required integer `amount_cents` value of at least 0 (a missing, non-integer, or negative `amount_cents` is rejected with `ERR_INVALID_REQUEST`); crediting the wallet increases `wallet_balance_cents` by that amount and increments the rider's `version`.

A `Driver` is onboarded by the Dispatcher with a `name` and a `home_zone_id`, the zone in which the driver registered. The driver's `current_zone_id` — the cell the driver currently occupies — is initialized to the `home_zone_id` at onboarding. A driver also carries a `status` that starts at `OFFLINE` and an `active_trip_id` that names the trip currently being serviced and is null when the driver is not on a trip.

### 3.2. Driver Availability and Supply

A driver controls their own availability. Going online moves the driver from `OFFLINE` to `AVAILABLE` and is permitted only when the driver has no `active_trip_id`; a go-online attempt from any status other than `OFFLINE`, or while the driver still holds an `active_trip_id`, is rejected with `ERR_INVALID_STATE`. The effect is to add the driver to their current zone's supply: the `available_supply_count` of the driver's current zone is incremented by 1, because only `AVAILABLE` drivers count toward zone supply.

Going offline moves the driver from `AVAILABLE` back to `OFFLINE`; a go-offline attempt from any status other than `AVAILABLE` is rejected with `ERR_INVALID_STATE`. This decrements the driver's current-zone `available_supply_count` by 1, floored at 0. Going offline also tears down any airport commitment: if the driver holds a `WAITING` airport queue entry, that entry transitions to `WITHDRAWN`, and the remaining `WAITING` entries in that airport zone re-sequence their `position` ordered by `joined_at` ascending with `created_at` ascending as a tie-break. (Only the driver's first matching `WAITING` entry is withdrawn, though a driver holds at most one such entry at a time.)

Drivers also move between zones as a consequence of completing trips, and the system uses the `AVAILABLE` driver count per zone as the live supply signal that feeds surge pricing. A driver may be listed and filtered by `home_zone_id`, `current_zone_id`, `active_trip_id`, and `status`.

### 3.3. Requesting a Trip and Freezing the Quote

A `Rider` requests a trip by naming themselves through `rider_id`, a `pickup_zone_id`, and a `dropoff_zone_id`. The system verifies these references in left-to-right order — `rider_id`, then `pickup_zone_id`, then `dropoff_zone_id`, with `ERR_NOT_FOUND` for the first that does not resolve — and then enforces ownership: the acting `Rider`'s `X-User-ID` must equal the supplied `rider_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. At request time the system freezes the price the rider is quoted: the trip's `quoted_multiplier` is set to the pickup zone's `current_multiplier` as it stands at that moment, and the trip's `quoted_base_fare_cents` is set to the pickup zone's `base_fare_cents` at that moment. These frozen values, not the live zone surge, drive the eventual fare. Requesting a trip also increments the pickup zone's `open_demand_count` by 1, and the new trip starts in `REQUESTED` status.

A trip carries several fields that remain at their defaults until later lifecycle stages. The `driver_id` is null while the trip is `REQUESTED` and is set when the trip is matched. The `final_fare_cents` and `driver_payout_cents` are both 0 until the trip is completed. The `refunded_cents` field starts at 0 and is increased only when a dispute against the trip is upheld. Trips may be listed and filtered by `rider_id`, `driver_id`, `pickup_zone_id`, `dropoff_zone_id`, and `status`.

### 3.4. Dispatch Matching

The Dispatcher drives matching by running a dispatch tick, a test-driving capability that processes open requests and matches each to a driver. The tick may be scoped to a single pickup zone by supplying an optional `zone_id`; when omitted, it considers all zones. A supplied `zone_id` that does not resolve to an existing zone is rejected with `ERR_NOT_FOUND`. Within a run, requested trips are processed in `created_at` ascending order. The tick reports a result containing `matched_trip_ids`, the list of trip identifiers it matched, and `matched_count`, the number matched.

For each matchable `REQUESTED` trip, the tick selects a candidate driver and advances the trip from `REQUESTED` to `MATCHED`. Candidate selection depends on whether the pickup zone is an airport. For a non-airport pickup zone, the candidate set is the drivers whose `status` is `AVAILABLE` and whose `current_zone_id` equals the trip's `pickup_zone_id`, ranked by `created_at` ascending so that the earliest-registered driver is chosen first. For an airport pickup zone, the candidate set is the drivers holding a `WAITING` airport queue entry in that zone, ranked strictly first-in-first-out by the queue entry's `joined_at` ascending, with `created_at` ascending as a tie-break. In either case, if the candidate set is empty the trip simply stays `REQUESTED` — the tick skips it with no error.

When a match lands, the effects cascade. The trip's `driver_id` is set to the selected driver. The selected driver transitions from `AVAILABLE` to `ON_TRIP`; as part of that transition the driver's `active_trip_id` is set to the matched trip and the driver's current-zone `available_supply_count` is decremented by 1, floored at 0. The pickup zone's `open_demand_count` is decremented by 1, floored at 0. For an airport pickup, the dispatched driver's `WAITING` airport queue entry transitions to `DISPATCHED`, and the remaining `WAITING` entries in that airport zone re-sequence their `position` by `joined_at` ascending with `created_at` ascending as a tie-break.

### 3.5. The Trip Lifecycle: Start, Complete, Cancel, Expire

Once matched, the assigned driver starts the trip, advancing it from `MATCHED` to `ENROUTE`. Starting is permitted only when the trip is `MATCHED` and the acting driver's `id` equals the trip's `driver_id`; otherwise the ownership check rejects with `ERR_NOT_RESOURCE_OWNER`, and a start attempted from any state other than `MATCHED` is rejected with `ERR_INVALID_STATE`.

The assigned driver completes the trip, advancing it from `ENROUTE` to `COMPLETED`. Completion is permitted only when the trip is `ENROUTE` and the acting driver's `id` equals the trip's `driver_id`. Completion is the system's settlement point and triggers a tightly ordered cascade. First, the trip's `final_fare_cents` is computed (see §3.7) and its `driver_payout_cents` is computed (see §3.8). The fare must be affordable: the rider's `wallet_balance_cents` must be at least the computed `final_fare_cents`, and if it is not, completion is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402). When the fare is affordable, the rider's `wallet_balance_cents` is decremented by the `final_fare_cents`. The assigned driver then transitions from `ON_TRIP` back to `AVAILABLE`: the driver's `active_trip_id` is cleared, the driver relocates to the completed trip's `dropoff_zone_id` (so the driver's `current_zone_id` becomes the dropoff zone), and that new current zone's `available_supply_count` is incremented by 1. Finally, if the driver has an `ACTIVE` quest, that quest's `completed_trips` is incremented by 1, and if the increment brings `completed_trips` to at least the quest's `target_trips`, the quest is earned, as described in §3.9.

A `Rider` may cancel their own matched trip, moving it from `MATCHED` to `CANCELLED`. Cancellation is permitted only when the trip is `MATCHED` and the acting rider's `id` equals the trip's `rider_id`. Cancelling releases the assigned driver: the driver transitions from `ON_TRIP` back to `AVAILABLE`, the driver's `active_trip_id` is cleared to null, the driver stays in their current pickup-side zone (their `current_zone_id` is unchanged), and that zone's `available_supply_count` is incremented by 1. No fare is charged on cancellation and the trip's `final_fare_cents` stays 0.

The Dispatcher may expire an unmatched request, moving a trip from `REQUESTED` to `EXPIRED`. Expiry is permitted only when the trip is `REQUESTED`, and its sole effect is to decrement the pickup zone's `open_demand_count` by 1, floored at 0. A trip that has reached `COMPLETED`, `CANCELLED`, or `EXPIRED` is terminal.

### 3.6. Publishing Surge Snapshots

The Dispatcher prices a zone by publishing a `SurgeSnapshot`. The publish body carries `observed_demand` and `observed_supply` — the dispatcher's captured readings of the zone's `open_demand_count` and `available_supply_count`, each of which must be at least 0 — an optional `is_rush_hour` flag, an `effective_from` and `effective_to` pair bounding the pricing window, and the `expected_zone_version` required for the concurrency check described in §2.9. The `effective_from` is the inclusive UTC start of the window and `effective_to` is the exclusive UTC end, which must be strictly later than `effective_from`; an `effective_to` that is at or before `effective_from` is rejected with `ERR_INVALID_REQUEST`, and this check (like the other body-field checks) runs before the window-overlap and OCC checks. A snapshot also records, as computed fields, the `zone_id` it prices, the derived `ratio`, the final `multiplier`, and a `capped` flag.

The pricing window must not collide with an existing window for the same zone. The system treats each snapshot window as the half-open interval from `effective_from` (inclusive) to `effective_to` (exclusive). A new snapshot is rejected with `ERR_SNAPSHOT_WINDOW_OVERLAP` if its interval overlaps any existing snapshot's interval for the same `zone_id` — that is, if the new window's `effective_from` is earlier than the existing window's `effective_to` and the existing window's `effective_from` is earlier than the new window's `effective_to`. Because the interval is half-open, two windows that merely touch at a boundary, where the new window's `effective_from` equals an existing window's `effective_to`, do not overlap and are allowed.

The surge multiplier is derived in a fixed four-step procedure that must be followed exactly. First, compute an effective supply equal to the larger of `observed_supply` and 1, then compute the demand-to-supply ratio as `observed_demand` divided by that effective supply, rounded half up to two decimal places; the supply is floored at 1 to avoid division by zero, and the ratio is rounded to two decimals before any banding. Second, band this rounded ratio into a raw multiplier using lower-inclusive thresholds: a ratio below 1.00 gives a raw multiplier of 1.00; a ratio of at least 1.00 but below 2.00 gives 1.50; a ratio of at least 2.00 but below 3.00 gives 2.00; and a ratio of at least 3.00 gives 2.50. Third, if `is_rush_hour` is true, add a rush-hour step of 0.50 to the banded raw multiplier — the step is added to the banded value, never to the ratio. Fourth, clamp the result to the multiplier cap of 2.50: the final `multiplier` is the smaller of the raw value and 2.50, and `capped` is true exactly when the raw value before clamping exceeded 2.50. As a worked illustration of the rush-hour path, a band that was already 2.50 plus the 0.50 step would reach 3.00 but is clamped back down to the 2.50 cap, with `capped` set to true.

On a successful publish, the computed `multiplier` is written to the zone's `current_multiplier`, the zone's `heat_level` is re-derived from that newly written multiplier, and the zone's `version` is incremented by 1. The Heat Map buckets are assigned from the just-published multiplier using lower-inclusive, upper-exclusive bands: a multiplier below 1.25 is `COOL`; a multiplier of at least 1.25 but below 1.75 is `WARM`; a multiplier of at least 1.75 but below 2.50 is `HOT`; and a multiplier of at least 2.50 is `BLAZING`. The snapshot list for a zone is returned newest first, and any participant role may read it.

### 3.7. Computing the Final Fare

A trip's `final_fare_cents` is settled at completion using the values frozen at request time, not the zone's live surge. The surged amount is the trip's `quoted_base_fare_cents` multiplied by its `quoted_multiplier`, rounded half up to a whole number of cents. A flat booking fee of 150 cents is then added to that surged amount as an exact integer, and the sum is the `final_fare_cents`. The order is pinned: multiply the base by the surge and round to cents first, then add the flat booking fee. The alternative of adding the fee before multiplying is explicitly not used.

### 3.8. Paying the Driver

A trip's `driver_payout_cents` is also settled at completion and is computed from the same frozen values. Take the same surged amount — the `quoted_base_fare_cents` multiplied by the `quoted_multiplier`, rounded half up to whole cents — and multiply it by the driver share of 0.80, rounding the result half up to whole cents. The payout share applies to the surged fare only and excludes the 150-cent booking fee, which is the platform's and is never shared with the driver; folding the booking fee into the payable base is the incorrect reading and is not used. Any quest bonus the driver earns is tracked separately on the quest and is never folded into `driver_payout_cents`.

### 3.9. Driver Quests

The Dispatcher creates a driver `Quest` bonus naming the `driver_id`, a `target_trips` count of completed trips required to earn the bonus, a flat `bonus_cents` payout, and a `window_start` and `window_end` bounding the eligibility window. The `target_trips` must be at least 1 and the `bonus_cents` must be at least 0; a `target_trips` below 1 or a `bonus_cents` below 0 is rejected with `ERR_INVALID_REQUEST`. The window is a closed interval whose `window_end` must be at or after `window_start`; a `window_end` earlier than `window_start` is rejected with `ERR_INVALID_REQUEST`, checked before the window-overlap check. A quest tracks `completed_trips`, which starts at 0, a `status` that starts at `ACTIVE`, and a `paid_out_cents` that starts at 0.

Quest windows for the same driver may not collide, and unlike surge windows, quest windows may not even touch. The window is treated as the closed interval from `window_start` to `window_end` inclusive. A new quest is rejected with `ERR_QUEST_WINDOW_OVERLAP` if its interval overlaps or merely touches the interval of any existing `ACTIVE` or `EARNED` quest for the same `driver_id` — that is, if the new window's `window_start` is at or before the existing window's `window_end` and the existing window's `window_start` is at or before the new window's `window_end`. Boundary contact, where the new window's `window_start` equals an existing window's `window_end`, does conflict here.

As described in §3.5, completing a trip credits the driver's `ACTIVE` quest by incrementing `completed_trips` by 1. When that increment brings `completed_trips` to at least `target_trips`, the quest transitions from `ACTIVE` to `EARNED` and its `paid_out_cents` is set to `bonus_cents`. The Dispatcher may instead expire a quest still in `ACTIVE`, moving it to `EXPIRED`; an expired quest's `paid_out_cents` stays 0. Both `EARNED` and `EXPIRED` are terminal. Quests may be listed and filtered by `driver_id` and `status`.

### 3.10. Airport Queues

Airports replace nearest-driver matching with a fair first-in-first-out queue. A `Driver` joins by naming the airport `zone_id` and their own `driver_id`. The target zone must be an airport zone — its `is_airport` flag must be true — or the join is rejected with `ERR_NOT_AIRPORT_ZONE`. A driver may hold at most one `WAITING` queue entry across all airport zones at a time; a second concurrent join is rejected with `ERR_ALREADY_QUEUED`. The joining driver must currently be `AVAILABLE`, or the join is rejected with `ERR_DRIVER_NOT_AVAILABLE`. These three business checks run in exactly that order — airport-zone first, then the at-most-one-`WAITING` duplicate check, then the availability check — so a driver who already holds a `WAITING` entry is rejected with `ERR_ALREADY_QUEUED` ahead of the availability check. On a successful join the entry's `joined_at` is stamped, its `status` is set to `WAITING`, and its `position` is computed as its 1-based FIFO rank among the `WAITING` entries in the same airport zone, ordered by `joined_at` ascending and then `created_at` ascending.

A driver may withdraw their own `WAITING` entry, moving it from `WAITING` to `WITHDRAWN`; this is permitted only when the entry is `WAITING` and the acting driver's `id` equals the entry's `driver_id`. Whether an entry leaves the queue by withdrawal or by being `DISPATCHED` during matching, the remaining `WAITING` entries in the same airport zone re-sequence their `position` by `joined_at` ascending with `created_at` ascending as a tie-break. As noted in §3.2, a driver going offline also withdraws their `WAITING` entry and triggers the same re-sequencing. Queue entries may be listed and filtered by `zone_id`, `driver_id`, and `status`.

### 3.11. Disputes and Refunds

After a trip completes, the `Rider` who took it may open a `Dispute`. The dispute body names the `trip_id`, a `reason` that is one of `OVERCHARGED`, `DRIVER_NO_SHOW`, or `ROUTE_ERROR`, and a `requested_refund_cents` claiming how much should be returned. The request body is validated first: a `reason` that is missing or outside the three allowed values, and a `requested_refund_cents` that is missing or not an integer, are each rejected with `ERR_INVALID_REQUEST` — these body checks run before the `trip_id` existence lookup. The system then verifies the referenced `trip_id` exists (`ERR_NOT_FOUND`), enforces ownership so that the acting `Rider`'s `X-User-ID` must equal the disputed trip's `rider_id` (`ERR_NOT_RESOURCE_OWNER`), and then applies the business checks. A dispute may only be opened against a trip whose status is `COMPLETED`; an attempt against any other trip status is rejected with `ERR_TRIP_NOT_COMPLETED`. The `requested_refund_cents` must be at least 1, or the request is rejected with `ERR_INVALID_REFUND_AMOUNT`; this minimum-amount check runs after the `COMPLETED` check. On creation the dispute's `rider_id` is copied from the disputed trip's `rider_id`, its `status` starts at `OPEN`, and its `refund_cents` stays 0 until upheld. Disputes may be listed and filtered by `trip_id` and `rider_id`.

The Dispatcher resolves an open dispute by supplying a `decision`, which must be exactly `UPHELD` or `REJECTED`; a missing or out-of-range `decision` is rejected with `ERR_INVALID_REQUEST`, and this body validation is checked before the dispute's state, so an invalid `decision` on an already-resolved dispute still yields `ERR_INVALID_REQUEST` rather than `ERR_INVALID_STATE`. When the decision upholds the dispute, it moves from `OPEN` to `UPHELD`; this requires the dispute to be `OPEN` (otherwise `ERR_INVALID_STATE`) and the disputed trip to be `COMPLETED` (otherwise `ERR_INVALID_STATE`). The refund is computed as the lesser of the requested amount and what the rider has actually paid net of prior refunds: the net paid is the trip's `final_fare_cents` minus the trip's current `refunded_cents`, where `refunded_cents` is the sum of prior upheld refunds on the same trip applied in `created_at` ascending order; the refund is the smaller of `requested_refund_cents` and that net paid. If the net paid is zero or negative — for instance because a prior dispute already refunded the entire fare — the refund is 0. The computed refund is recorded as the dispute's `refund_cents`, added to the rider's `wallet_balance_cents`, and added to the disputed trip's `refunded_cents`. A second upheld dispute on a trip whose fare has already been fully refunded therefore yields 0, never a second full refund.

When the decision rejects the dispute, it moves from `OPEN` to `REJECTED`; this requires only that the dispute be `OPEN`. A rejected dispute's `refund_cents` stays 0 and no wallet change occurs. Both `UPHELD` and `REJECTED` are terminal.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify an existing resource, including state transitions and the dispatch tick, return `200 OK`. The request and response bodies for each endpoint are described in the workflow narratives of §3; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/zones` | Create a geo-grid Zone | Dispatcher |
| GET | `/zones/{id}` | Fetch a Zone with live counters and current surge | Dispatcher, Rider, Driver |
| GET | `/zones` | List Zones (Heat Map feed); filter by `is_airport`, `heat_level` | Dispatcher, Rider, Driver |
| POST | `/zones/{id}/surge-snapshots` | Publish a SurgeSnapshot; recompute surge under OCC | Dispatcher |
| GET | `/zones/{id}/surge-snapshots` | List a Zone's SurgeSnapshots, newest first | Dispatcher, Rider, Driver |
| GET | `/zones/{id}/trips` | List Trips with this pickup Zone; filter by `status` | Dispatcher |
| GET | `/zones/{id}/drivers` | List Drivers with this home Zone | Dispatcher |
| GET | `/zones/{id}/airport-queue` | List a Zone's airport queue, WAITING by position; filter by `status` | Dispatcher, Driver |
| POST | `/riders` | Onboard a Rider | Dispatcher |
| GET | `/riders/{id}` | Fetch a Rider | Dispatcher, Rider |
| GET | `/riders` | List Riders; filter by `home_zone_id` | Dispatcher |
| POST | `/riders/{id}/wallet/credit` | Top up a Rider's wallet | Dispatcher |
| POST | `/drivers` | Onboard a Driver | Dispatcher |
| GET | `/drivers/{id}` | Fetch a Driver | Dispatcher, Driver |
| GET | `/drivers` | List Drivers; filter by `home_zone_id`, `current_zone_id`, `active_trip_id`, `status` | Dispatcher |
| POST | `/drivers/{id}/go-online` | Driver goes AVAILABLE in their current Zone | Driver |
| POST | `/drivers/{id}/go-offline` | Driver goes OFFLINE; withdraws any queue entry | Driver |
| POST | `/trips` | Rider requests a trip; freezes quoted surge | Rider |
| GET | `/trips/{id}` | Fetch a Trip | Dispatcher, Rider, Driver |
| GET | `/trips` | List Trips; filter by `rider_id`, `driver_id`, `pickup_zone_id`, `dropoff_zone_id`, `status` | Dispatcher, Rider, Driver |
| POST | `/trips/{id}/start` | Assigned driver starts the matched trip | Driver |
| POST | `/trips/{id}/complete` | Assigned driver completes the trip | Driver |
| POST | `/trips/{id}/cancel` | Rider cancels a matched trip | Rider |
| POST | `/trips/{id}/expire` | Dispatcher expires an unmatched request | Dispatcher |
| POST | `/_dispatch/tick` | Run a dispatch epoch; match REQUESTED trips | Dispatcher |
| POST | `/airport-queue` | Driver joins an airport Zone FIFO queue | Driver |
| GET | `/airport-queue/{id}` | Fetch an AirportQueueEntry | Dispatcher, Driver |
| GET | `/airport-queue` | List queue entries; filter by `zone_id`, `driver_id`, `status` | Dispatcher, Driver |
| POST | `/airport-queue/{id}/withdraw` | Driver withdraws from the airport queue | Driver |
| POST | `/quests` | Dispatcher creates a driver Quest bonus | Dispatcher |
| GET | `/quests/{id}` | Fetch a Quest | Dispatcher, Driver |
| GET | `/quests` | List Quests; filter by `driver_id`, `status` | Dispatcher, Driver |
| POST | `/quests/{id}/expire` | Dispatcher expires an ACTIVE Quest | Dispatcher |
| POST | `/disputes` | Rider opens a Dispute against a COMPLETED trip | Rider |
| GET | `/disputes/{id}` | Fetch a Dispute | Dispatcher, Rider |
| GET | `/disputes` | List Disputes; filter by `trip_id`, `rider_id`, `status` | Dispatcher, Rider |
| POST | `/disputes/{id}/resolve` | Dispatcher resolves a Dispute (uphold or reject) | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_GRID_CODE` | 409 |
| `ERR_NOT_AIRPORT_ZONE` | 422 |
| `ERR_ALREADY_QUEUED` | 409 |
| `ERR_DRIVER_NOT_AVAILABLE` | 422 |
| `ERR_TRIP_NOT_COMPLETED` | 422 |
| `ERR_INVALID_REFUND_AMOUNT` | 422 |
| `ERR_INSUFFICIENT_WALLET` | 402 |
| `ERR_STALE_ZONE_VERSION` | 412 |
| `ERR_SNAPSHOT_WINDOW_OVERLAP` | 409 |
| `ERR_QUEST_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
