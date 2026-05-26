# Airline Crew Scheduling API — Product Requirements Document

## 1. Introduction

Commercial airline operations live or die by the precision with which crews are paired to flights. Federal regulators cap how many minutes a pilot or flight attendant may fly and how many duty minutes they may accumulate inside any rolling seven-day window; union agreements layer on minimum rest intervals between assignments and define how trips are bid, awarded, traded, and recovered when crew unexpectedly fall sick. This Product Requirements Document specifies the API that the airline's Operations Control Center, Scheduling Planners, and individual crew members will use to plan, bid, confirm, and execute a flying schedule under those constraints.

The system is organized around the **Pairing** — a single duty period composed of one or more sequential **FlightLegs** that originate and terminate at a base airport. Around each Pairing, the API coordinates the bidding flow that allocates seats to crew, the assignment lifecycle that tracks each crew member's commitment from `SCHEDULED` through `CONFIRMED` and on to `ACTIVE`/`COMPLETED`, the sick-call and reserve-callup chain that recovers an assignment when a crew member can no longer fly, and the trip-trade workflow by which two crew members swap pairings subject to operational approval. Throughout, the FAA's rolling 7-day duty/flight caps and the union's 10-hour minimum-rest rule are enforced as preflight checks rather than after-the-fact audits — the system refuses to confirm or recover any assignment that would project a violation.

Because crew rosters change minute to minute on the day of operations, the API is built for immediate consistency: every state change emits its cascading side effects atomically, every parent–child reconciliation bumps `updated_at` and `version`, and optimistic-concurrency tokens guard the two operations — pairing awards and trade executes — where two operators could otherwise act on stale planner views.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers identifying the caller: `X-User-ID` to identify the acting principal and `X-User-Role` to declare their operational capacity. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED`. If the supplied role is not listed in the authorized roles for the target endpoint, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles, all of which appear with the exact spelling shown here:

- `SchedulingPlanner` — long-range planning, pairing construction, bidding lifecycle, and seat awards.
- `OperationsController` — day-of-operations control: sick-call acknowledgement, pairing completion, trade approval and execution.
- `CrewMember` — individual flight crew acting on their own bids, assignments, sick calls, reserve offers, and trip-trade proposals.

`SchedulingPlanner` and `OperationsController` are peer operator roles: when `X-User-Role` is `SchedulingPlanner` or `OperationsController`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `CrewMember`, by contrast, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on any resource that references a `CrewMember` compare the resource's foreign-key field to `X-User-ID`. Specifically, a `CrewMember` submitting a bid must use their own crew identity in `crew_member_id`; confirming an assignment requires that the assignment's `crew_member_id` equals the caller's `X-User-ID`; reporting a sick call requires that the underlying assignment's `crew_member_id` matches; accepting or declining a reserve callup requires that the callup's `selected_reserve_id` matches; proposing a trip trade requires that the initiator assignment's `crew_member_id` matches; countersigning or rejecting a trade requires that the trade's `counterparty_id` matches; and withdrawing a trade requires that the trade's `initiator_id` matches. Any ownership violation surfaces as `ERR_FORBIDDEN`.

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

For endpoints that return lists of resources, pagination is controlled by two query parameters. The `limit` parameter caps the number of items returned and defaults to 10; the minimum permitted value is 1 and the maximum is 100. The `offset` parameter specifies how many leading items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated responses include the following fields inside the response envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in this API — `CrewMember`, `Pairing`, `FlightLeg`, `Bid`, `Assignment`, `SickCall`, `ReserveCallup`, and `TripTrade` — carries a uniform set of system-managed properties:

- **`id`** (string): a server-minted UUID; it does **not** carry a type prefix and is the sole identifier used in URL paths and as the value of any foreign-key field that references this resource.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional-second digits, set once at the moment the resource is created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional-second digits, refreshed on every mutation to the resource — including system-driven mutations such as the cascade refresh of a `CrewMember`'s rolling totals when one of their assignments completes.
- **`version`** (integer): a monotonically increasing counter that starts at 1 on creation and increments by exactly one on every mutation. The counter underpins optimistic-concurrency checks (§2.10).

All eight primary entities carry the full quartet (`id`, `created_at`, `updated_at`, `version`). No entity in this domain is immutable-after-create; every entity participates in lifecycle state changes that bump `updated_at` and `version`.

### 2.5. Nested Resource Retrieval

Several endpoints expose sub-resources under a parent path — most importantly the FlightLeg collection mounted under a Pairing. For any request whose path contains multiple identifiers (for example, `/pairings/{id}/flight-legs`), the server resolves each path segment from left to right. The first identifier that does not match an existing entity causes the request to be rejected immediately with `ERR_NOT_FOUND` (HTTP 404), without evaluating any later segments or any body-level validation. Foreign-key fields in request bodies (`pairing_id`, `crew_member_id`, `assignment_id`, `sick_call_id`, `initiator_assignment_id`, `counterparty_assignment_id`) follow the same rule: a body that references a non-existent parent is rejected with `ERR_NOT_FOUND` before any business logic runs.

### 2.6. Logical Clock and Time-Driven Auto-Transitions

The system maintains a single logical wall-clock value, `current_utc`, that drives every time-dependent transition: bidding windows close when the clock crosses `bidding_close_utc`, pairings transition from `AWARDED` to `IN_PROGRESS` when the clock crosses `scheduled_start_utc`, and rolling 7-day duty totals are recomputed whenever the window slides. For testing and deterministic replay, an administrative test-driving capability accepts a target instant in the body field `to_iso8601` and advances `current_utc` to that value. Setting the clock not only updates the stored time but synchronously fires every transition that the new clock makes due: for each Pairing in `BID_OPEN` whose `current_utc >= bidding_close_utc`, the Pairing cascades to `BID_CLOSED`; for each Pairing in `AWARDED` whose `current_utc >= scheduled_start_utc` and whose every child Assignment is `CONFIRMED`, the Pairing cascades to `IN_PROGRESS` and each child Assignment moves from `CONFIRMED` to `ACTIVE` with `actual_duty_start_utc` set to `current_utc` and the owning `CrewMember.status` set to `ON_DUTY`. Each `CrewMember` whose assignments have completed within the new trailing-seven-day window has their `total_flight_minutes_7d` and `total_duty_minutes_7d` re-evaluated by the rolling-duty calculation described in §2.7.

### 2.7. FAA Duty and Flight Caps

Federal Aviation Administration rules constrain the rolling seven-day duty and flight totals for every crew member. The system enforces these caps preemptively rather than retroactively: any action that would project a violation is refused.

The **rolling 7-day window** for a given `CrewMember` spans from 168 hours before `current_utc` up to and including `current_utc`. Two persisted totals are maintained on each crew member: `total_flight_minutes_7d` is the sum of `flight_minutes_credited` over the crew member's `Assignment` rows that are in state `COMPLETED` and whose `actual_duty_end_utc` falls at or after the window start and at or before `current_utc`; `total_duty_minutes_7d` is the analogous sum of `duty_minutes_credited` over the same set of completed assignments. The eligible assignments are taken in order of `actual_duty_end_utc` ascending, with ties broken by `created_at` ascending. Both totals are integer minutes; partial minutes are floored. These persisted totals are refreshed whenever an assignment transitions to `COMPLETED` and whenever the logical clock advances.

When a crew member is about to take on a new commitment — confirming an assignment, accepting a reserve callup, or being approved as the new owner under a trip trade — the system runs a **preview form** of the rolling calculation: it adds the candidate Pairing's `total_duty_minutes` and `total_flight_minutes` to the persisted seven-day totals as if the assignment had already completed, without writing the preview back to the `CrewMember`. A violation is declared if the previewed duty total exceeds 3,600 minutes (60 hours of duty in any rolling seven-day window) or if the previewed flight total exceeds 1,800 minutes (30 hours of flight in any rolling seven-day window). The comparison uses strict greater-than at the cap: a value exactly equal to the cap passes, and exceeding the cap by one minute fails. A duty-cap violation surfaces as `ERR_FAA_DUTY_CAP_EXCEEDED` (HTTP 422); a flight-cap violation surfaces as `ERR_FAA_FLIGHT_CAP_EXCEEDED` (HTTP 422). The preview is evaluated on three operations: assignment confirmation, reserve-callup acceptance, and trip-trade approval. For trip-trade approval, the preview must clear for **both** crew members under their post-swap seat assignments.

### 2.8. Crew Rest Minimum Interval

Independent of FAA cap arithmetic, every crew member must observe a minimum off-duty period of 600 minutes (10 hours) between the moment they last came off duty and the start of any new assignment. Concretely, for a candidate Pairing, the system computes the difference in minutes between the candidate's `scheduled_start_utc` and the crew member's `last_off_duty_utc`. If `last_off_duty_utc` is null — meaning the crew member has never completed any assignment — the rest interval is treated as effectively unbounded and the check passes. Otherwise, the difference must be at least 600 minutes (the threshold uses inclusive comparison: an interval of exactly 600 minutes passes; an interval one minute shorter fails). A violation surfaces as `ERR_CREW_REST_VIOLATION` (HTTP 422). Like the FAA caps, this check is evaluated on assignment confirmation, reserve-callup acceptance, and trip-trade approval.

### 2.9. Validation Priority Order

When more than one of the rules below could apply to a request, validations run in a fixed priority order so the same input always produces the same error. The order, from first-evaluated to last, is:

1. Authentication: both `X-User-ID` and `X-User-Role` headers must be present and non-empty (else `ERR_UNAUTHENTICATED`).
2. Authorization: the supplied `X-User-Role` must appear in the endpoint's authorized roles list (else `ERR_FORBIDDEN`).
3. Path-segment existence: every `{id}` in the URL must resolve to an existing entity, left to right (else `ERR_NOT_FOUND`).
4. Foreign-key existence: every foreign-key identifier in the request body must resolve to an existing parent (else `ERR_NOT_FOUND`).
5. State eligibility: the target resource must currently be in a state from which the requested transition is defined (else `ERR_INVALID_STATE`).
6. Cross-entity state: for assignment confirmation, reserve-callup acceptance, trip-trade approval, and trip-trade execution, the dependent entity (parent Pairing, related SickCall, related Assignment) must itself be in a compatible state (else `ERR_CROSS_ENTITY_STATE`).
7. FAA duty cap, then 8. FAA flight cap, then 9. crew-rest interval (the three business-safety checks of §2.7–§2.8, evaluated in this order so that a duty-cap breach surfaces before a flight-cap breach, and both surface before a rest-interval breach).
10. Bid / trade rank-vs-seat compatibility — `ERR_RANK_SEAT_MISMATCH` (see §3.2 for the rank↔seat mapping).
11. Pairing time-window sanity — `ERR_INVALID_TIME_WINDOW` (see §3.1).
12. Trip-trade pairing-overlap — `ERR_PAIRING_OVERLAP` (see §3.6).
13. Bid uniqueness — `ERR_DUPLICATE_BID` (see §3.2).
14. FlightLeg overlap within a Pairing — `ERR_LEG_OVERLAP` (see §3.1).
15. Optimistic-concurrency mismatch — `ERR_STALE_VERSION` (see §2.10).
16. Reserve-callup exhaustion — `ERR_NO_RESERVE_AVAILABLE` (see §3.4).
17. Generic schema conformance: required fields present, types/enums/formats valid, no unknown fields — else `ERR_INVALID_REQUEST` (HTTP 400).

Two consequences are worth noting. First, authentication and authorization always precede any not-found check, so a missing-header caller is told they are unauthenticated even if the path id is wrong. Second, the three FAA / rest checks run after state validation but before the structural checks (rank-seat, time-window, overlap), so an in-state but cap-breaching confirm surfaces as a safety error rather than a request-shape error.

### 2.10. Optimistic Concurrency Control

Two endpoints in this API require the caller to declare which version of the parent entity they have observed. Both endpoints sit at points in the workflow where one operator's view can become stale relative to another operator's actions, and both reject the write outright when staleness is detected — they do not retry, merge, or fall through.

The first is the pairing-award action, which transitions a Pairing from `BID_CLOSED` to `AWARDED`. The request body must include a non-optional field `expected_pairing_version` carrying the integer `version` of the target Pairing as the planner last read it. If that value does not equal the Pairing's current `version`, the award is rejected with `ERR_STALE_VERSION` and HTTP status 412. The most common cause is that the bidding window auto-closed and bumped `version` between the planner's read and write; the planner's view of which bids are still `SUBMITTED` may therefore be out of date.

The second is the trip-trade execute action, which transitions a TripTrade from `APPROVED` to `EXECUTED`. The request body must include a non-optional field `expected_trip_trade_version` carrying the integer `version` of the target TripTrade. If that value does not equal the TripTrade's current `version`, the execute is rejected with `ERR_STALE_VERSION` and HTTP status 412. The typical cause is that an interleaved withdraw, reject, or earlier execute path advanced the trade's version after the operator's last read, so the operator may be acting on a trade record they have not in fact observed.

No other endpoint accepts a version-expectation field. Endpoints not listed in either rule perform their mutations without an OCC check.

### 2.11. Cascading Side Effects and Version Propagation

Many transitions in this domain are not isolated mutations — they update one entity and, in the same atomic step, propagate updates across related entities. Every entity that is touched by such a cascade has its `updated_at` refreshed to `current_utc` and its `version` incremented by one, regardless of whether the change originated from a direct client request or from a parent's cascade. Two motifs recur throughout §3 and must be respected:

- **Pairing-driven cascades.** When a Pairing transitions to `IN_PROGRESS` (driven by the clock), every child Assignment in `CONFIRMED` cascades to `ACTIVE` with `actual_duty_start_utc` set to `current_utc`, and each owning `CrewMember.status` is set to `ON_DUTY`. When a Pairing transitions to `COMPLETED`, every `ACTIVE` Assignment cascades to `COMPLETED` with `actual_duty_end_utc` set to `current_utc`; the Assignment's `flight_minutes_credited` is locked to the parent Pairing's `total_flight_minutes` and `duty_minutes_credited` is locked to the parent's `total_duty_minutes`; the owning `CrewMember.status` flips to `ON_REST` and their `last_off_duty_utc` is set to `current_utc`; and the rolling 7-day totals on that crew member are recomputed. Cancelling a Pairing from `BID_OPEN` cascades every `SUBMITTED` Bid on that Pairing to `WITHDRAWN`.
- **Sick-call → reserve-callup → assignment recovery.** Acknowledging a SickCall creates an `OFFERED` ReserveCallup and flips the sick-calling crew member's `status` to `SICK`. Accepting that callup cascades the original Assignment from `CONFIRMED` to `RECOVERED`, creates a replacement Assignment in `CONFIRMED` with `source` set to `RESERVE_CALLUP`, populates the callup's `replacement_assignment_id` with the new assignment's id, and cascades the SickCall from `ACKNOWLEDGED` to `CLOSED`.

In both motifs, every entity that changes — parents, children, and the crew members whose status is updated — has its own `updated_at` and `version` advanced. Derived fields like `total_flight_minutes_7d`, `total_duty_minutes_7d`, `scheduled_block_minutes`, and `actual_block_minutes` are likewise treated as mutations: writing to them refreshes the resource's audit fields.

### 2.12. Integer-Minute Precision and Boundary Inclusivity

Every duration in this API — pairing duty windows, flight totals, rolling seven-day caps, the crew-rest interval, leg flight minutes — is expressed in **integer minutes**. Where a computation involves a sub-minute remainder (for example, computing `flight_minutes` on a FlightLeg from `scheduled_arrival_utc - scheduled_departure_utc`), the remainder is floored to the nearest whole minute. When averaging across multiple Assignments to set `actual_block_minutes` on a Pairing, integer division is used (floor of the sum divided by the count).

Boundary semantics for the major threshold comparisons are explicit and uniform:

- FAA duty and flight caps use strict greater-than at the cap. A projected total of exactly 3,600 duty minutes or exactly 1,800 flight minutes passes; one minute beyond either cap fails.
- The crew-rest minimum uses inclusive comparison at the threshold. A rest interval of exactly 600 minutes passes; an interval of 599 minutes fails.
- FlightLeg overlap within a Pairing uses **closed** intervals on `[scheduled_departure_utc, scheduled_arrival_utc]`: two legs that touch at a single instant are in conflict.
- Trip-trade pairing-overlap uses **half-open** intervals: two duty windows where one ends exactly when the other begins (end_A equals start_B) are permitted as back-to-back, while end_A strictly greater than start_B is a conflict.

## 3. Business Logic & Workflows

### 3.1. Pairing Construction and the Bidding Lifecycle

A Pairing is the central scheduling unit. A `SchedulingPlanner` creates a Pairing in `DRAFT` by supplying a unique `pairing_code` that conforms to the pattern of a literal `P-`, four digits, a hyphen, and three more digits; the home base for the duty period as `origin_base`, expressed as a three-letter uppercase IATA code; the scheduled duty window's start and end instants in `scheduled_start_utc` and `scheduled_end_utc` as ISO 8601 UTC timestamps; the seat-count requirements `required_captains`, `required_first_officers`, and `required_cabin_crew`; and the planned `bidding_close_utc` at which the bidding window will close on its own. The captain count must be at least 1 and at most 2; the first-officer count must be at least 1 and at most 2; the cabin-crew count must be at least 0 and at most 8 (where the cabin-crew bucket counts both `PURSER` and `FLIGHT_ATTENDANT` together). The Pairing's lifecycle `state` enumerates `DRAFT`, `BID_OPEN`, `BID_CLOSED`, `AWARDED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal.

Time-window sanity is enforced at creation and at open-bidding time: `bidding_close_utc` must be strictly less than `scheduled_start_utc`, and `scheduled_end_utc` must be strictly greater than `scheduled_start_utc`; any other arrangement is rejected with `ERR_INVALID_TIME_WINDOW`. On creation, the pairing-duty-window calculation initializes the Pairing's two derived totals: `total_duty_minutes` is set to the difference in whole minutes between `scheduled_end_utc` and `scheduled_start_utc`, plus a 60-minute report buffer and a 30-minute debrief buffer — that is, the difference in minutes plus a fixed 90 minutes of pre- and post-flight time. `total_flight_minutes` is initially zero because no FlightLeg exists; as legs are added it becomes the sum of each leg's `flight_minutes` over legs whose `leg_type` is `REVENUE`. Deadhead legs are deliberately excluded from `total_flight_minutes` but are included in `total_duty_minutes` indirectly, because the outer scheduled window subsumes them.

Each FlightLeg is added under a Pairing while the Pairing is in `DRAFT`. A leg carries the parent pointer `pairing_id`, a 1-based `leg_sequence` unique within that parent, a `departure_airport` and `arrival_airport` (each a three-letter uppercase IATA code), the scheduled `scheduled_departure_utc` and `scheduled_arrival_utc` (with arrival strictly greater than departure — else `ERR_INVALID_TIME_WINDOW`), and a `leg_type` of either `REVENUE` or `DEADHEAD`. The server computes `flight_minutes` as the floor of `(scheduled_arrival_utc - scheduled_departure_utc)` in seconds divided by 60. Two distinct legs of the same Pairing must not have overlapping `[scheduled_departure_utc, scheduled_arrival_utc]` windows under closed-interval semantics — even legs that merely touch at a single instant are in conflict — and an overlap is rejected with `ERR_LEG_OVERLAP`. Adding a leg recomputes the parent Pairing's `total_flight_minutes` and `total_duty_minutes` and bumps the parent's `version`.

The bidding flow runs as follows. A planner opens bidding on a `DRAFT` Pairing, transitioning `state` to `BID_OPEN`; this is admissible only if the Pairing has at least one `REVENUE` FlightLeg, `bidding_close_utc` is strictly less than `scheduled_start_utc`, and the entire duty window lies in the future (`scheduled_start_utc` is strictly greater than `current_utc`). Once bidding is open, eligible crew submit Bids (§3.2). Bidding closes by one of two paths: the planner may manually close it, advancing `state` from `BID_OPEN` to `BID_CLOSED`; or the logical clock crossing `bidding_close_utc` auto-closes it, which is what makes §2.10's OCC guard on the award action meaningful. Either way, no further bids are accepted once the Pairing is in `BID_CLOSED`.

The award step is restricted to a `SchedulingPlanner`, transitions a Pairing from `BID_CLOSED` to `AWARDED`, and is the first place where OCC enters the picture: the request body must carry `expected_pairing_version` matching the Pairing's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The award is permitted only if the pool of `SUBMITTED` Bids covers all required seats by rank (captain, first officer, and cabin crew). When it does, for each required seat the system selects the most-senior `SUBMITTED` Bid by `seniority_number` ascending (lower number is more senior), with ties broken by `created_at` ascending; that Bid transitions from `SUBMITTED` to `AWARDED`, and a new Assignment is created in `state` `SCHEDULED` with `source` set to `BID_AWARD`, carrying the awarded crew member's `crew_member_id` and the seat in `seat`. Every other `SUBMITTED` Bid on the same Pairing is moved to `UNSUCCESSFUL`. At the same moment the Pairing's `scheduled_block_minutes` is computed and locked: it equals the difference in whole minutes between `scheduled_end_utc` and `scheduled_start_utc`, minus the 60-minute report buffer and minus the 30-minute debrief buffer (i.e., the planned duty window less the 90 minutes of buffer time). Finally `state` flips to `AWARDED` and `version` increments.

A Pairing can be cancelled by a `SchedulingPlanner` while it is in `DRAFT` or `BID_OPEN`. Cancellation from `DRAFT` simply sets `state` to `CANCELLED`. Cancellation from `BID_OPEN` additionally cascades every Bid on that Pairing with `state` `SUBMITTED` to `WITHDRAWN`. In both cases the Pairing's `version` increments. No cancellation path exists out of `BID_CLOSED`, `AWARDED`, `IN_PROGRESS`, or any terminal state; an attempt is rejected with `ERR_INVALID_STATE`.

After an awarded Pairing's `scheduled_start_utc` is reached, the logical clock drives the next transitions automatically (§2.6). When the clock advances to or past `scheduled_start_utc` and every child Assignment for that Pairing is in `CONFIRMED`, the Pairing cascades from `AWARDED` to `IN_PROGRESS`, each child Assignment cascades from `CONFIRMED` to `ACTIVE` with `actual_duty_start_utc` set to `current_utc`, and each owning `CrewMember.status` is set to `ON_DUTY`. The pairing is finally completed by an `OperationsController` once `current_utc` is at or past `scheduled_end_utc`: the Pairing's `state` flips to `COMPLETED`, each `ACTIVE` Assignment cascades to `COMPLETED` with `actual_duty_end_utc` set to `current_utc`, the Assignment's `flight_minutes_credited` and `duty_minutes_credited` are locked from the parent Pairing's `total_flight_minutes` and `total_duty_minutes`, the owning `CrewMember.status` becomes `ON_REST`, `last_off_duty_utc` is set to `current_utc`, and the rolling seven-day totals on that crew member are recomputed. In the same atomic step the Pairing's `actual_block_minutes` is locked: it is the floor of the sum, over each `COMPLETED` Assignment on this Pairing, of the difference in minutes between that Assignment's `actual_duty_end_utc` and `actual_duty_start_utc`, divided by the count of such Assignments. The scheduled-block snapshot is set at `AWARDED` and locked thereafter; the actual-block snapshot is set at `COMPLETED` and locked thereafter — neither is recomputed later.

### 3.2. Crew Members, Bidding, and Rank–Seat Compatibility

A `CrewMember` is created by a `SchedulingPlanner` with an `employee_code` matching the pattern of exactly two uppercase letters followed by four digits, a `full_name`, a `rank` from the set `CAPTAIN`, `FIRST_OFFICER`, `PURSER`, and `FLIGHT_ATTENDANT`, a `base_airport` as a three-letter uppercase IATA code, a `seniority_number` that is at least 1 and is unique within the combination of `rank` and `base_airport` (so seniority lists are scoped per base-and-rank, with 1 being the most senior), and a `line_type` of either `LINEHOLDER` (regular bid-line crew) or `RESERVE` (on-call reserve crew). The system maintains an operational `status` defaulting to `AVAILABLE` and ranging across `AVAILABLE`, `ON_DUTY`, `ON_REST`, `SICK`, and `INACTIVE`, plus three derived crew-level totals that default to zero or null on creation: `total_flight_minutes_7d`, `total_duty_minutes_7d`, and `last_off_duty_utc` (which remains null until the crew member's first Assignment completes).

A Bid is submitted by a `CrewMember` against a Pairing in `BID_OPEN`. The body carries `pairing_id`, `crew_member_id`, and `requested_seat`, where `requested_seat` is one of `CAPTAIN`, `FIRST_OFFICER`, `PURSER`, or `FLIGHT_ATTENDANT`. The Bid's `state` is initialized to `SUBMITTED` and proceeds through one of `AWARDED`, `UNSUCCESSFUL`, or `WITHDRAWN`. Two structural rules guard bid creation. First, **rank–seat compatibility**: a `CAPTAIN` may only bid for a `CAPTAIN` seat; a `FIRST_OFFICER` may only bid for a `FIRST_OFFICER` seat; both `PURSER` and `FLIGHT_ATTENDANT` are permitted to bid for either the `PURSER` seat or the `FLIGHT_ATTENDANT` seat. Any other combination is rejected with `ERR_RANK_SEAT_MISMATCH`. The same rank–seat rule is also enforced when a TripTrade is proposed and again at trade approval time, where the seat of each crew member's post-swap Assignment must be compatible with that crew member's `rank`. Second, **bid uniqueness**: a given `crew_member_id` may have at most one non-terminal Bid (state in `SUBMITTED` or `AWARDED`) against a given `pairing_id`. A duplicate is rejected with `ERR_DUPLICATE_BID`. A crew member may withdraw their own `SUBMITTED` Bid before the Pairing reaches `BID_CLOSED`, which moves the Bid to `WITHDRAWN` and bumps its `version`.

### 3.3. Assignment Confirmation

An Assignment is the durable record of a single crew member's commitment to a single Pairing. Assignments are not created directly by clients; they are minted as side effects of three workflows: pairing awards (Assignments with `source` set to `BID_AWARD` in `state` `SCHEDULED`), reserve-callup acceptance (Assignments with `source` set to `RESERVE_CALLUP` in `state` `CONFIRMED`), and trip-trade execution (Assignments with `source` set to `TRIP_TRADE` in `state` `CONFIRMED`). Each Assignment carries `pairing_id`, `crew_member_id`, `seat`, `source`, lifecycle `state` (one of `SCHEDULED`, `CONFIRMED`, `ACTIVE`, `COMPLETED`, `RELEASED`, `RECOVERED`, `CANCELLED`, with the last four terminal), the runtime timestamps `actual_duty_start_utc` and `actual_duty_end_utc` (both null until set by the cascade transitions), and the locked-at-completion snapshots `flight_minutes_credited` and `duty_minutes_credited` (zero until COMPLETED).

The only manual action a crew member takes on an Assignment is confirmation. Confirming moves a `SCHEDULED` Assignment to `CONFIRMED` and is permitted only when three conditions are satisfied. First, the acting caller's `X-User-ID` must equal the Assignment's `crew_member_id` (else `ERR_FORBIDDEN`). Second, the parent Pairing must be in `state` `AWARDED` (else `ERR_CROSS_ENTITY_STATE`). Third, all three business-safety checks must clear in the order given in §2.9: the rolling-duty preview must not project `total_duty_minutes_7d` exceeding 3,600 minutes (else `ERR_FAA_DUTY_CAP_EXCEEDED`), the same preview must not project `total_flight_minutes_7d` exceeding 1,800 minutes (else `ERR_FAA_FLIGHT_CAP_EXCEEDED`), and the candidate Pairing's `scheduled_start_utc` minus the crew member's `last_off_duty_utc` must be at least 600 minutes (else `ERR_CREW_REST_VIOLATION`). On success the Assignment's `state` flips to `CONFIRMED` and its `version` increments.

From `CONFIRMED` an Assignment can move along several paths, all driven by other workflows: it transitions to `ACTIVE` and then `COMPLETED` under the parent Pairing's clock-driven cascades (§3.1); it transitions to `RECOVERED` when a sick-call recovery chain succeeds (§3.4); and it transitions to `RELEASED` when a trip-trade executes against it (§3.5). A `SCHEDULED` Assignment can also be released directly when a trade execute happens before the owner ever confirmed it.

### 3.4. Sick Calls and Reserve Callups

When a crew member can no longer fly an assignment they have already taken, they file a SickCall. The body carries `assignment_id` referencing one of their own Assignments and `reason_code` from the set `ILLNESS`, `INJURY`, and `FAMILY_EMERGENCY`. The server stamps `reported_utc` at creation and computes `hours_before_departure` as the integer hours from `reported_utc` to the parent Assignment's Pairing's `scheduled_start_utc` (negative when the sick call is reported past departure). The SickCall is created in `state` `REPORTED` and proceeds through `ACKNOWLEDGED` to terminal `CLOSED`.

An `OperationsController` acknowledges a `REPORTED` SickCall, which is admissible only when the referenced Assignment is in `state` `SCHEDULED` or `CONFIRMED` (an attempt to acknowledge against an out-of-state Assignment is rejected with `ERR_CROSS_ENTITY_STATE`). Acknowledgement does three things in one atomic step: the SickCall flips to `ACKNOWLEDGED`, a first ReserveCallup is minted in `state` `OFFERED` with `callup_sequence` 1 and `selected_reserve_id` chosen by the reserve-selector policy described below, and the sick-calling crew member's `status` becomes `SICK`. The acknowledgement bumps the SickCall's `version`.

The **reserve-selector policy** runs whenever a new ReserveCallup needs a target. It first filters the candidate pool to crew members whose `line_type` is `RESERVE`, whose `status` is `AVAILABLE`, whose `rank` is compatible with the seat being recovered (under the same rank–seat mapping as §3.2), whose `base_airport` matches the orphaned Pairing's `origin_base`, and whose `id` is not in the set of crew members already offered the same SickCall via earlier callup attempts. From the remaining candidates the policy ranks by `total_duty_minutes_7d` ascending — that is, the least-worked reserve first — with ties broken by `seniority_number` ascending (most-senior wins) and then by `created_at` ascending. The top candidate is selected. If no candidate survives the filter, the operation is rejected with `ERR_NO_RESERVE_AVAILABLE` (HTTP 422). The same exhaustion error is raised when the total number of callup attempts for a single SickCall would exceed five — that is, `callup_sequence` cannot grow beyond 5.

The selected reserve responds in one of two ways. If they decline, the current ReserveCallup moves from `OFFERED` to `DECLINED`, and the system immediately mints the next ReserveCallup with `callup_sequence` set to the prior sequence plus one, `state` `OFFERED`, and `selected_reserve_id` chosen by re-running the reserve-selector policy with the declining crew member excluded from the candidate pool. If they accept, the current ReserveCallup moves from `OFFERED` to `ACCEPTED` — but acceptance is gated on the same three FAA / rest checks as assignment confirmation: the rolling-duty preview against this reserve crew member must not project `total_duty_minutes_7d` exceeding 3,600 minutes, must not project `total_flight_minutes_7d` exceeding 1,800 minutes, and the reserve's `scheduled_start_utc` minus their `last_off_duty_utc` must be at least 600 minutes; violations surface as `ERR_FAA_DUTY_CAP_EXCEEDED`, `ERR_FAA_FLIGHT_CAP_EXCEEDED`, and `ERR_CREW_REST_VIOLATION` respectively. On success a chain of cascades fires atomically: the original Assignment moves from `CONFIRMED` to `RECOVERED`; a replacement Assignment is created in `state` `CONFIRMED` with `source` `RESERVE_CALLUP`, `crew_member_id` set to the reserve's id (i.e., to `selected_reserve_id`), and `seat` copied from the original Assignment; the ReserveCallup's `replacement_assignment_id` is set to the new Assignment's id; and the SickCall transitions from `ACKNOWLEDGED` to terminal `CLOSED`. Every entity touched in this cascade has its `updated_at` refreshed and its `version` incremented (§2.11).

The `offered_utc` system timestamp on the ReserveCallup records when each callup was first offered to the selected reserve.

### 3.5. Trip Trades

Trip trades let two crew members swap pairings. The flow has five user-driven transitions plus a terminal-execute, and exposes the API's second OCC guard. A trip-trade is initiated by a `CrewMember` who already owns one Assignment and offers it in exchange for another crew member's Assignment. The proposal body carries `initiator_assignment_id` and `counterparty_assignment_id`; both assignments must exist and the caller's `X-User-ID` must equal the initiator assignment's `crew_member_id`. At creation, the server copies `initiator_id` from the initiator-assignment's `crew_member_id` and `counterparty_id` from the counterparty-assignment's `crew_member_id`. The TripTrade's `state` starts at `PROPOSED` and proceeds through `COUNTERSIGNED`, `APPROVED`, and finally terminal `EXECUTED`; the three terminal-rejection paths are `REJECTED`, `WITHDRAWN`, and (after approval is bypassed for whatever reason) re-entry from approved into withdrawn is not permitted.

From `PROPOSED` the counterparty (whose `X-User-ID` must match the trade's `counterparty_id`) may either countersign — moving `state` to `COUNTERSIGNED`, gated on both Assignments still being in `SCHEDULED` or `CONFIRMED` — or reject the trade outright, moving `state` to `REJECTED` and capturing the supplied `reason` into the trade's `rejection_reason` field. Also from `PROPOSED` the initiator (whose `X-User-ID` must match `initiator_id`) may withdraw, moving `state` to `WITHDRAWN`. Withdrawal is also permitted out of `COUNTERSIGNED` by the same initiator.

Once a trade is `COUNTERSIGNED`, an `OperationsController` approves it, advancing `state` to `APPROVED`. Approval runs three structural checks. The rolling-duty preview must clear for **both** crew members under their post-swap assignment owners (each must not project `total_duty_minutes_7d` exceeding 3,600 minutes and must not project `total_flight_minutes_7d` exceeding 1,800 minutes). The crew-rest interval must clear for both. Each crew member's `rank` must match the seat they would inherit under the swap (i.e., the seat of the assignment they would now own); a mismatch is rejected with `ERR_RANK_SEAT_MISMATCH`. The approval also runs the trade-overlap check described in §3.6.

Finally an `OperationsController` executes the approved trade. Execution is the second OCC site: the request body must include `expected_trip_trade_version` matching the TripTrade's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412 (§2.10). Execution also re-verifies that both original Assignments are still in `SCHEDULED` or `CONFIRMED` (else `ERR_CROSS_ENTITY_STATE`). On success the swap fires atomically: the initiator's original Assignment cascades to `RELEASED`; the counterparty's original Assignment cascades to `RELEASED`; two new Assignments are created in `state` `CONFIRMED` with `source` `TRIP_TRADE`, each carrying the swapped `pairing_id` with the original seat, and `crew_member_id` set to the new owner; and the TripTrade's `state` flips to `EXECUTED`. Every entity touched advances its `version`.

### 3.6. Pairing Overlap on Trade Approval

A trade approval is rejected if executing the swap would put either crew member into two overlapping duty windows. The overlap test treats each crew member's already-`CONFIRMED` Assignments as fixed and asks whether the candidate Pairing each would inherit fits cleanly alongside them. Specifically, duty-window intervals use **half-open** semantics on `[scheduled_start_utc, scheduled_end_utc)`: two windows where one ends exactly when the other begins (the prior window's end equals the next window's start) are permitted as back-to-back, while a prior window whose end is strictly later than the next window's start is a conflict. A conflict is reported as `ERR_PAIRING_OVERLAP` (HTTP 422). This is the only place in the API where pairing-level duty windows are compared across distinct Pairings; FlightLeg overlap within a single Pairing (§3.1) uses closed intervals instead, because legs that touch at one instant cannot be staffed by the same crew.

## 4. Endpoint Definitions

Operations that create a new, distinct resource — a CrewMember, a Pairing, a FlightLeg under a Pairing, a Bid, a SickCall, or a TripTrade — return `201 Created`. Every other state-changing or read operation returns `200 OK`. Path identifiers are denoted `{id}` throughout; the system resolves them left to right as described in §2.5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/crew-members` | Create a crew member | SchedulingPlanner |
| GET | `/crew-members` | List crew members (paginated, filterable by `rank`, `base_airport`, `line_type`, `status`) | SchedulingPlanner, OperationsController |
| GET | `/crew-members/{id}` | Read a crew member | SchedulingPlanner, OperationsController, CrewMember |
| POST | `/pairings` | Create a pairing in `DRAFT` | SchedulingPlanner |
| GET | `/pairings` | List pairings (paginated, filterable by `state`, `origin_base`) | SchedulingPlanner, OperationsController, CrewMember |
| GET | `/pairings/{id}` | Read a pairing | SchedulingPlanner, OperationsController, CrewMember |
| POST | `/pairings/{id}/open-bidding` | Open bidding on a `DRAFT` pairing | SchedulingPlanner |
| POST | `/pairings/{id}/close-bidding` | Manually close bidding before the scheduled close time | SchedulingPlanner |
| POST | `/pairings/{id}/award` | Award seats by seniority and snapshot scheduled block | SchedulingPlanner |
| POST | `/pairings/{id}/complete` | Complete an in-progress pairing and cascade assignments | OperationsController |
| POST | `/pairings/{id}/cancel` | Cancel a pairing from `DRAFT` or `BID_OPEN` | SchedulingPlanner |
| POST | `/pairings/{id}/flight-legs` | Add a flight leg to a `DRAFT` pairing | SchedulingPlanner |
| GET | `/pairings/{id}/flight-legs` | List flight legs for a pairing | SchedulingPlanner, OperationsController, CrewMember |
| POST | `/bids` | Crew member submits a bid for a `BID_OPEN` pairing | CrewMember |
| GET | `/bids` | List bids (filterable by `pairing_id`, `crew_member_id`, `state`) | SchedulingPlanner, CrewMember |
| GET | `/bids/{id}` | Read a bid | SchedulingPlanner, CrewMember |
| POST | `/bids/{id}/withdraw` | Crew member withdraws their own `SUBMITTED` bid | CrewMember |
| GET | `/assignments` | List assignments (filterable by `pairing_id`, `crew_member_id`, `state`) | SchedulingPlanner, OperationsController, CrewMember |
| GET | `/assignments/{id}` | Read an assignment | SchedulingPlanner, OperationsController, CrewMember |
| POST | `/assignments/{id}/confirm` | Crew member confirms a `SCHEDULED` assignment | CrewMember |
| POST | `/sick-calls` | Crew member reports sick for one of their own assignments | CrewMember |
| GET | `/sick-calls` | List sick calls (filterable by `assignment_id`, `state`) | OperationsController, SchedulingPlanner |
| GET | `/sick-calls/{id}` | Read a sick call | OperationsController, SchedulingPlanner, CrewMember |
| POST | `/sick-calls/{id}/acknowledge` | Operations acknowledges a sick call and triggers reserve callup | OperationsController |
| GET | `/reserve-callups` | List reserve callups (filterable by `sick_call_id`, `selected_reserve_id`, `replacement_assignment_id`, `state`) | OperationsController, CrewMember |
| GET | `/reserve-callups/{id}` | Read a reserve callup | OperationsController, CrewMember |
| POST | `/reserve-callups/{id}/accept` | Reserve crew accepts an `OFFERED` callup | CrewMember |
| POST | `/reserve-callups/{id}/decline` | Reserve crew declines an `OFFERED` callup; system attempts next reserve | CrewMember |
| POST | `/trip-trades` | Initiator proposes a trip trade between two assignments | CrewMember |
| GET | `/trip-trades` | List trip trades (filterable by `initiator_id`, `counterparty_id`, `initiator_assignment_id`, `counterparty_assignment_id`, `state`) | SchedulingPlanner, OperationsController, CrewMember |
| GET | `/trip-trades/{id}` | Read a trip trade | SchedulingPlanner, OperationsController, CrewMember |
| POST | `/trip-trades/{id}/countersign` | Counterparty agrees; trade moves to `COUNTERSIGNED` | CrewMember |
| POST | `/trip-trades/{id}/reject` | Counterparty rejects a `PROPOSED` trade (optional `reason`) | CrewMember |
| POST | `/trip-trades/{id}/withdraw` | Initiator withdraws a `PROPOSED` or `COUNTERSIGNED` trade | CrewMember |
| POST | `/trip-trades/{id}/approve` | Operations approves a `COUNTERSIGNED` trade after FAA, rest, and overlap checks | OperationsController |
| POST | `/trip-trades/{id}/execute` | Execute an `APPROVED` trade with `expected_trip_trade_version` | OperationsController |
| POST | `/_clock/set_current_utc` | Set the server clock to `to_iso8601`; cascades time-driven transitions | SchedulingPlanner, OperationsController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_FAA_DUTY_CAP_EXCEEDED` | 422 |
| `ERR_FAA_FLIGHT_CAP_EXCEEDED` | 422 |
| `ERR_CREW_REST_VIOLATION` | 422 |
| `ERR_RANK_SEAT_MISMATCH` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_PAIRING_OVERLAP` | 422 |
| `ERR_LEG_OVERLAP` | 422 |
| `ERR_DUPLICATE_BID` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_RESERVE_AVAILABLE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
