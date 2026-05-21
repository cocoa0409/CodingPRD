# Airline Crew Scheduling API — Product Requirements Document

## 1. Introduction

Running a commercial airline's daily flying program is in equal parts an exercise in safety regulation, labor relations, and pure logistics. Federal Aviation Administration duty-time rules cap how much a pilot or flight attendant may fly inside rolling windows; collective-bargaining agreements with each union local impose seniority-driven bidding, minimum-credit floors, and consent rules around trades; and the day-of-operations reality of sick calls, no-shows, and last-minute cancellations means the schedule that was published two weeks ago is almost never the schedule that flies. The Airline Crew Scheduling API is the system of record that holds these three forces together, behind a single domain mounted under `/crew-scheduling`.

This document describes the API that crew schedulers, line pilots, cabin crew, and union representatives all touch — sometimes against one another — to keep aircraft staffed with legally rested, correctly ranked, and properly credited crew. The system mediates pairing construction, opens and awards seniority-driven bid windows, runs the reserve pool when something breaks, supports up to three rounds of trade counter-proposals between crew members of equivalent rank, and finalizes pay credit when a pairing closes. A test-driving logical clock is exposed so that time-gated transitions — pairings advancing through their lifecycle, reserve windows expiring, trade requests aging out at the 24-hour mark — are deterministic and inspectable.

A guiding tension runs through the whole specification. Safety rules are absolute: a single duty-period overrun, a missed rest interval, or a cumulative-block-cap breach must block an assignment before it is written. Yet seniority must still be honored, deadhead minutes still credited, and a sick call at T-minus-eight-hours must still find a covered slot. The contracts below are written so that no single workflow can resolve this tension by silently dropping a constraint.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either is missing or empty, the request is rejected with `ERR_AUTH_REQUIRED`. If `X-User-Role` is present but is not one of the four supported values — `CrewScheduler`, `Pilot`, `FlightAttendant`, or `UnionSteward` — the request is rejected with `ERR_AUTH_INVALID_ROLE`. When a role is recognized but is not permitted to invoke the requested endpoint per the RBAC matrix described in §4, the request is rejected with `ERR_FORBIDDEN`.

The four roles fall into two identity classes. When `X-User-Role` is `Pilot` or `FlightAttendant`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks on any resource that references a `CrewMember` (a `Bid`, a `SickCall`, an `Assignment`, a `TradeRequest`) compare the resource's foreign-key field — `crew_member_id`, `initiator_id`, or `counterparty_id` — to `X-User-ID`. A `Pilot` may only bid, withdraw, sick-out, propose, counter, accept, reject, or cancel on resources where the relevant foreign key equals their own `X-User-ID`; the same is true for `FlightAttendant`. When `X-User-Role` is `CrewScheduler` or `UnionSteward`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as part of an audit trail) but does not compare it to any entity's `id`. The `UnionSteward` role additionally identifies its acting union local through an `X-Union-Local-Id` header, used when blessing a cross-local trade.

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

All list endpoints accept `limit` and `offset` query parameters. The default `limit` is 10, the minimum is 1, and the maximum is 100; any value outside that range is rejected with `ERR_VALIDATION_FAILED`. The default `offset` is 0 and must be non-negative. List endpoints sort results by `created_at` ascending unless explicitly stated otherwise, so that a fresh `offset`-based scan revisits already-paginated entries in a stable order. The pagination block in `meta` for a list response includes `limit`, `offset`, `total_count` (the total number of rows matching the filter, irrespective of pagination), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a plain UUID — no domain prefix, no embedded entity-type marker, no other decoration. The server also records a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits at the instant the row is first written, and that value is never modified again.

Top-level aggregate entities — `CrewMember`, `Pairing`, `Bid`, `Assignment`, `ReservePool`, `TradeRequest` — additionally carry an `updated_at` timestamp (same ISO 8601 UTC, three fractional digits, refreshed on every mutation including computed-field recomputation) and a monotonically increasing integer `version` that starts at 1 and is incremented by exactly 1 on every successful mutation. The child entities `DutyPeriod`, `FlightLeg`, and `SickCall` carry only `id` and `created_at`; they have no `updated_at` field and no `version` field, and clients must not assume either is present in their JSON payloads.

### 2.5. Optimistic Concurrency Control

Any `PATCH` or `PUT` endpoint that mutates one of the entities with a `version` field accepts an optional `version` field in the request body. When omitted, the server applies the mutation without checking. When supplied, the server compares it to the persisted entity's current `version`: a match permits the mutation and increments `version` by one as the change is committed; a mismatch causes the request to be rejected with `ERR_VERSION_CONFLICT` and no state change. Two simultaneous counter-proposals on the same `TradeRequest` from the same actor are likewise serialized by the OCC mechanism on `TradeRequest.version`: the second writer observes the bumped version and receives `ERR_VERSION_CONFLICT`.

### 2.6. Nested Resource Retrieval

Path-referenced resources are validated left to right. For an endpoint such as the one that appends a flight leg to a duty period under a draft pairing, the parent duty period is checked first; if its `id` does not resolve, `ERR_RESOURCE_NOT_FOUND` is returned and no further checks run. Foreign keys carried in the request body — `crew_member_id`, `pairing_id`, `assignment_id`, `counterparty_assignment_id`, `initiator_assignment_id`, and so on — are validated after path checks succeed, and an unresolved one yields `ERR_REFERENCE_NOT_FOUND`. This body-level reference check applies specifically to bid creation, reserve-pool placement, trade-request creation, sick-call creation, and the admin-override assignment endpoint.

### 2.7. Time, Units, and Precision

All durations the system reasons about — duty minutes, block minutes, crew-rest intervals, cumulative caps — are integer minutes. No rounding is needed for durations. Pay credit, although derived from a fractional deadhead multiplier, is also expressed as integer minutes; the rounding rule is `floor` applied after aggregation, never before (see §3.6). All timestamps in inputs and outputs are ISO 8601 UTC with three fractional digits. The logical clock starts at server boot and is advanced exclusively through the test-driving capability described in §3.7; no transition that depends on `now` may fire except in response to that advance.

### 2.8. Validation Priority

When a single request would fail multiple checks, the system evaluates them in a fixed order so that the most fundamental failure is the one reported. The order is: authentication header presence (`ERR_AUTH_REQUIRED`), then role-value validity (`ERR_AUTH_INVALID_ROLE`), then endpoint-level role permission (`ERR_FORBIDDEN`), then path-resource existence (`ERR_RESOURCE_NOT_FOUND`), then body foreign-key resolution (`ERR_REFERENCE_NOT_FOUND`), then assignment-state preconditions (`ERR_INVALID_ASSIGNMENT_STATE`), then pairing-state preconditions (`ERR_PAIRING_INVALID_STATE`), then trade-state preconditions (`ERR_INVALID_TRADE_STATE`), then FAA crew-rest interval (`ERR_FAA_CREW_REST_VIOLATION`), then the broader FAA duty/block caps (`ERR_FAA_DUTY_VIOLATION`), then trade-rule legality (`ERR_TRADE_RULE_VIOLATION`), then reserve-window temporal bounds (`ERR_RESERVE_OUTSIDE_WINDOW`), then bid-cutoff temporal bounds (`ERR_BID_TOO_LATE`), then pairing internal overlap (`ERR_PAIRING_INTERNAL_OVERLAP`), then flight-leg internal consistency (`ERR_FLIGHT_LEG_INVALID`), then duplicate bid preference (`ERR_DUPLICATE_BID_PREFERENCE`), then crew-availability (`ERR_CREW_NOT_AVAILABLE`), then field-level type and format validity (`ERR_VALIDATION_FAILED`), and finally OCC `version` mismatch (`ERR_VERSION_CONFLICT`).

The practical effect is that, for example, on an attempt by a `Pilot` to call out a reserve to themselves on a pairing they cannot cover, the rejection is `ERR_FORBIDDEN` (a `Pilot` is never permitted to invoke a reserve callout) rather than a downstream FAA error — the role check runs first so that data-shape errors never mask permission errors.

### 2.9. Hierarchical Consistency and Cascade Semantics

Pairings own their `DutyPeriod` rows, which in turn own their `FlightLeg` rows; mutations at a lower level walk back up. Adding a duty period to a draft pairing recomputes `Pairing.total_duty_minutes`, `Pairing.start_at`, and `Pairing.end_at`. Adding a flight leg to a duty period recomputes `DutyPeriod.block_minutes` and `Pairing.total_block_minutes`. Each of these recomputations refreshes `updated_at` and increments `version` on the affected top-level aggregate `Pairing`. Cascades on terminal-state transitions of a pairing (cancel, close) are described under the relevant business workflow in §3 — they ripple into `Bid`, `Assignment`, and `CrewMember` cumulative counters in lockstep.

### 2.10. Cumulative Counters and the Conservation Invariant

Two cumulative counters on each `CrewMember` — `cumulative_block_minutes_30d` (a rolling 30-day block-minutes total) and `cumulative_duty_minutes_7d` (a rolling 7-day duty-minutes total) — drive the FAA caps. They are incremented when an assignment binds and decremented when an assignment is released or its parent pairing is cancelled; the decrement happens only when the affected dates still fall within the rolling window from `now`. Across a successful trade execution, the SUM of `cumulative_block_minutes_30d` across the two crew members is identical before and after, because each minute moves from one ledger to the other with no net loss or gain. This conservation invariant is the safety net that lets a scheduler audit a day's trades without comparing every assignment individually.

### 2.11. Concurrency Serialization

Several workflows are subject to first-writer-wins serialization beyond the OCC mechanism:

- Two `CrewScheduler` operators racing the bid-window awarding sweep on the same window serialize on the `Pairing.status` transition from `BIDDING_OPEN` to `AWARDED`; whichever sweep commits first wins, and the loser receives `ERR_BID_WINDOW_ALREADY_AWARDED`.
- Two reserve callouts targeting the same vacated rank slot on the same pairing serialize on the insertion of an `Assignment` row keyed by `(pairing_id, assigned_rank_slot)`; the second writer receives `ERR_SLOT_ALREADY_COVERED`.
- A trade approval and a sick call on the same `Assignment` serialize on the `Assignment.status` field; whichever transitions the assignment first wins, and the loser receives `ERR_INVALID_ASSIGNMENT_STATE`.
- Two `Pilot` bids racing the bid-window-close instant serialize on `Pairing.status`; bids whose write commits before the `BIDDING_OPEN → AWARDED` transition succeed, and any that arrive after receive `ERR_BID_WINDOW_CLOSED`.

## 3. Business Logic & Workflows

### 3.1. Crew Members and Pairing Construction

A `CrewMember` is registered by a `CrewScheduler` with an `employee_no` matching the pattern `^E\d{6}$` (the letter E followed by exactly six digits, unique across the workforce), a `rank` drawn from `CAPTAIN`, `FIRST_OFFICER`, `PURSER`, or `FLIGHT_ATTENDANT`, a three-letter IATA `base_airport` code, a strictly positive `union_seniority_number` (lower numbers indicate greater seniority and the number must be unique within rank), and a `union_local_id` identifying the local the member belongs to. The `status` field is computed and starts at `ACTIVE`; the three cumulative counters `cumulative_duty_minutes_7d`, `cumulative_block_minutes_30d`, and `last_duty_end_at` are all maintained by the system. A non-`ACTIVE` crew member — one in `ON_SICK_CALL`, `ON_LEAVE`, or `INACTIVE` — fails the crew-availability check and any attempt to bind them to an assignment yields `ERR_CREW_NOT_AVAILABLE`.

Pairing construction is a multi-step drafting process by the `CrewScheduler`. Creating a pairing supplies the human-readable `pairing_code` (which must be unique), the `base_airport` from which the pairing departs and returns, and a `required_rank_composition` object specifying headcount per rank (for example, one captain, one first officer, and three flight attendants). The pairing is born in `DRAFT`. Inside the draft, the scheduler appends `DutyPeriod` rows in `sequence_no` order — sequence numbers are 1-based and must be unique within the pairing — supplying for each a UTC `report_at` and `release_at`, from which the system computes the duty period's `duty_minutes`. Within each duty period the scheduler appends `FlightLeg` rows by `leg_sequence_no` (1-based, unique within the duty period); each leg's `duty_period_id` foreign key is implied by the path, and each leg carries a `flight_number`, IATA `dep_airport` and `arr_airport`, UTC `dep_at` and `arr_at`, and an optional `leg_type` defaulting to `REVENUE` and otherwise set to `DEADHEAD`; the system computes the leg's `block_minutes`. A flight leg with `dep_at` greater than or equal to `arr_at` is rejected with `ERR_FLIGHT_LEG_INVALID`, and so is one whose `dep_at` is earlier than the prior leg's `arr_at` in the same duty period (sequential legs may touch but must not overlap; no buffer is required inside a duty period).

Publishing a draft pairing moves it to `PUBLISHED` and is rejected if the pairing has no duty periods or contains a duty period with no flight legs. Publication recomputes `Pairing.total_block_minutes` (the sum of `block_minutes` over `REVENUE` legs only — deadheads are excluded from the block total even though they will earn fractional credit later), `Pairing.total_duty_minutes` (the sum of `duty_minutes` across all duty periods), and refreshes `Pairing.start_at` and `Pairing.end_at` as the minimum `report_at` and maximum `release_at` across the pairing. The publish step additionally verifies that no two duty periods overlap and that the rest gap between consecutive duty periods (the difference between the earlier period's `release_at` and the later period's `report_at`) is at least the crew-rest minimum interval of ten hours; any violation yields `ERR_PAIRING_INTERNAL_OVERLAP`, and the same check applies whenever a duty period is appended to a draft.

### 3.2. Opening Bidding and the Bid Lifecycle

Once a pairing is `PUBLISHED`, the scheduler may open bidding on it by associating it with a `bid_window_id`, transitioning the pairing from `PUBLISHED` to `BIDDING_OPEN`. The transition is rejected unless `Pairing.start_at` is at least 24 hours in the future; the API responds with `ERR_PAIRING_INVALID_STATE` if the pairing is not `PUBLISHED` (for example, the scheduler tried to open bidding on a `DRAFT` or already-`AWARDED` pairing).

A `Pilot` or `FlightAttendant` submits a `Bid` against a `BIDDING_OPEN` pairing by sending the target `pairing_id`, a `preference_rank` indicating the bidder's ordering within their own bid set for this window (1 being most preferred), and the `bid_window_id`. The bid is born `SUBMITTED`. `preference_rank` must be strictly positive and unique within the pair `(crew_member_id, bid_window_id)`; a duplicate is rejected with `ERR_DUPLICATE_BID_PREFERENCE`. A bid against a pairing that is no longer `BIDDING_OPEN` is rejected with `ERR_BID_WINDOW_CLOSED` if the pairing has just left that state through an awarding sweep, or with `ERR_PAIRING_INVALID_STATE` otherwise. Submitting a bid less than 24 hours before `Pairing.start_at` is rejected with `ERR_BID_TOO_LATE` (the inclusive 24-hour cutoff is enforced strictly: a `start_at` minus 24 hours that exactly equals `now` is still permitted; anything later is rejected).

A bidder may withdraw their own `SUBMITTED` bid while the pairing remains `BIDDING_OPEN`, taking the bid from `SUBMITTED` to `WITHDRAWN`. Withdrawal by anyone other than the bid's owner is rejected by the ownership rule embedded in `X-User-ID` enforcement; withdrawal after the pairing has left `BIDDING_OPEN` is likewise rejected.

### 3.3. The Awarding Sweep

When the bid window closes, a `CrewScheduler` runs the awarding sweep across every `BIDDING_OPEN` pairing whose `bid_window_id` matches the closing window. The sweep transitions each such pairing from `BIDDING_OPEN` to `AWARDED`; a second sweep on the same window finds no `BIDDING_OPEN` pairings and is rejected at the window level with `ERR_BID_WINDOW_ALREADY_AWARDED`.

Pairings in the sweep are processed in a pinned chronological order: first by ascending `Pairing.start_at`, with ascending `Pairing.created_at` as the secondary tie-break. The order matters because awarding an earlier pairing to a candidate increments that candidate's cumulative counters, which can disqualify them on a later pairing within the same sweep. For each pairing in turn, and for each rank slot the pairing requires, candidates are drawn from the `SUBMITTED` bids on that pairing whose owning `CrewMember.rank` equals the slot and whose owning `CrewMember.status` is `ACTIVE`.

Two awarding policies exist. The default `seniority_first` variant ranks candidates by `union_seniority_number` ascending alone, then applies the FAA duty/rest check; a senior bidder who fails the FAA check yields to the next senior bidder in seniority order, who is then checked. The `load_balanced` variant — selected when the pairing's `required_rank_composition` object carries the flag `mode: 'LOAD_BALANCED'` — instead ranks candidates first by `cumulative_block_minutes_30d` ascending (least-used first), with `union_seniority_number` ascending as the tie-break, before applying the same FAA check. Identical bids can produce different awards under the two variants: a high-seniority bidder with high recent block hours loses to a junior, less-used bidder under `load_balanced` but wins under `seniority_first`. Since `union_seniority_number` is unique within rank, there is never a tie at the seniority key. When no candidate for a slot passes the FAA check, the slot is left uncovered and the pairing still moves to `AWARDED` with whatever slots were filled; the unfilled slot is recoverable later through a reserve callout or an admin override.

The successful candidate's `Bid` transitions from `SUBMITTED` to `AWARDED`, and a new `Assignment` row with `source = BID_AWARD` is created, snapshotting `Pairing.total_block_minutes` into the assignment's `scheduled_block_minutes` field. The crew member's `cumulative_block_minutes_30d` is incremented by `Pairing.total_block_minutes` (specifically, only the portion of `total_block_minutes` that falls within the rolling 30-day window measured from `Pairing.start_at`). All other `SUBMITTED` bids on that pairing's awarded slot transition to `NOT_AWARDED`; bids that lost on FAA grounds are also `NOT_AWARDED`.

### 3.4. Reserve Pool, Sick Calls, and No-Shows

A reserve crew member is placed on reserve by a `CrewScheduler` who supplies the `crew_member_id`, a `reserve_date` aligned to UTC midnight, and the `standby_start_at` / `standby_end_at` bounding the standby window. The combination `(crew_member_id, reserve_date)` must be unique. The reserve row begins in `AVAILABLE` and may end in `CALLED_OUT`, `RELEASED` (when the scheduler manually releases the standby), or `EXPIRED` (when the logical clock advances past `standby_end_at`).

A `Pilot`, `FlightAttendant`, or `CrewScheduler` may report a sick call by supplying the affected `crew_member_id`, an optional `assignment_id` identifying the pairing slot being vacated, an `effective_from` UTC start of the sick-out period, and an `expected_return_at` UTC expected return-to-duty timestamp. The server stamps `reported_at` itself. When `assignment_id` is supplied and that assignment is still `SCHEDULED`, the assignment is released to `RELEASED`. The crew member's `status` transitions from `ACTIVE` to `ON_SICK_CALL`. The system then runs the reserve-selection algorithm against the vacated rank slot; if a covering candidate is found, a new `Assignment` row with `source = RESERVE_CALLOUT` is created linking the reserve to the vacated slot, the reserve row moves from `AVAILABLE` to `CALLED_OUT`, the sick call's `covered_by_assignment_id` is set to the new assignment's `id`, and the covering crew member's `cumulative_block_minutes_30d` is incremented by `Pairing.total_block_minutes`. If no covering candidate exists, the sick call is still recorded (HTTP 201) but `covered_by_assignment_id` remains null, the pairing keeps its uncovered slot, and the response body's `error_id` is `ERR_NO_RESERVE_AVAILABLE` to signal the manual-intervention need.

The reserve-selection algorithm filters and ranks the pool. A reserve row is eligible if its `state` is `AVAILABLE`, `now` lies within the half-open standby window — at or after `standby_start_at` and strictly before `standby_end_at` — the owning crew member's `rank` matches the vacated `assigned_rank_slot`, the crew member's `base_airport` equals the pairing's `base_airport`, and the FAA duty/rest check would pass for that candidate against the target pairing. Among eligible candidates, the primary key is `cumulative_block_minutes_30d` ascending (least-used first); the first tie-break is `union_seniority_number` ascending (more senior wins); the second tie-break is `CrewMember.created_at` ascending (longer-tenured row wins). If the eligible set is empty, the result is `ERR_NO_RESERVE_AVAILABLE` and `covered_by_assignment_id` remains null.

A manual reserve callout — used when a scheduler picks a specific reserve themselves rather than letting the auto-selection run — takes the target `pairing_id`, the `assigned_rank_slot` to fill, and an optional `sick_call_id` if the callout is in response to a recorded sick call. The same eligibility and FAA checks apply: a callout outside the half-open standby window is rejected with `ERR_RESERVE_OUTSIDE_WINDOW`, an FAA failure with `ERR_FAA_CREW_REST_VIOLATION` or `ERR_FAA_DUTY_VIOLATION` as appropriate, and a non-`ACTIVE` candidate with `ERR_CREW_NOT_AVAILABLE`. A successful callout transitions the reserve from `AVAILABLE` to `CALLED_OUT`, creates the `Assignment` with `source = RESERVE_CALLOUT`, updates the sick call's `covered_by_assignment_id` if `sick_call_id` was supplied, and increments the covering member's `cumulative_block_minutes_30d`. Two callouts racing for the same `(pairing_id, assigned_rank_slot)` are serialized so that the second receives `ERR_SLOT_ALREADY_COVERED`.

A no-show is the day-of analogue: when the logical clock has reached `Pairing.start_at` and a scheduled crew member has not checked in, the `CrewScheduler` marks the assignment as no-show, transitioning the assignment from `SCHEDULED` to `NO_SHOW`. The crew member's `status` remains `ACTIVE`, pay credit is not granted for the no-show assignment, and the reserve-selection algorithm runs to recover the slot.

### 3.5. The FAA Duty-Rest Check

Before any assignment binds — a bid award, a reserve callout, a trade execution, or an admin override — the FAA duty-rest check evaluates the candidate against the target pairing. Four inequalities must all hold; the first to fail is the one reported. First, the gap from the candidate's `last_duty_end_at` to the candidate pairing's earliest `report_at` must be at least 600 minutes (the ten-hour crew-rest minimum); a shorter gap yields `ERR_FAA_CREW_REST_VIOLATION`. Second, the candidate's `cumulative_duty_minutes_7d` plus the candidate pairing's `total_duty_minutes` must be at most 3600 minutes (the rolling 60-hour, seven-day duty cap). Third, the candidate's `cumulative_block_minutes_30d` plus the pairing's `total_block_minutes` must be at most 6000 minutes (the rolling 100-hour, thirty-day block cap). Fourth, every `DutyPeriod` belonging to the candidate pairing must have a `duty_minutes` of at most 840 minutes (the 14-hour single-duty-period cap). Any of the last three failures yields `ERR_FAA_DUTY_VIOLATION`. All four boundary inequalities are inclusive — a gap of exactly 600 minutes, a cumulative duty total reaching exactly 3600 minutes, a cumulative block total reaching exactly 6000 minutes, and a duty period of exactly 840 minutes are all permitted. All comparisons are in integer minutes with no rounding.

The crew-rest interval (`ERR_FAA_CREW_REST_VIOLATION`) and the broader duty/block caps (`ERR_FAA_DUTY_VIOLATION`) guard four operations: the bid-award sweep, the manual reserve callout, the trade approval, and the admin-override assignment creation. In all four, the rejection codes are the ones above.

### 3.6. Time-Gated Lifecycle and Pay Credit

The pairing lifecycle past `AWARDED` is driven by the logical clock. When `now` reaches or exceeds `Pairing.start_at` and all required rank slots have a `SCHEDULED` assignment, the pairing transitions from `AWARDED` to `IN_PROGRESS` and every `SCHEDULED` assignment on it transitions to `IN_PROGRESS`. When `now` reaches or exceeds `Pairing.end_at`, the pairing transitions from `IN_PROGRESS` to `CLOSED`, every `IN_PROGRESS` assignment on it transitions to `COMPLETED`, and for each completed assignment the system computes `actual_block_minutes` (the sum of `block_minutes` over the assignment's `REVENUE` flight legs that actually flew — that is, legs whose owning duty period's `release_at` is at or before `Pairing.end_at` and whose assignment was `IN_PROGRESS` at that release time, excluding legs cancelled because of an intra-pairing sick call) and then runs the pay-credit calculation. The system also refreshes `CrewMember.last_duty_end_at` to the greater of its prior value and the closing pairing's `end_at`.

Pay credit is computed in five steps. First, revenue minutes are summed: take the `block_minutes` of every `REVENUE` flight leg belonging to the crew member through this assignment and add them. Second, deadhead minutes are summed in the same way over `DEADHEAD` legs. Third, the deadhead credit is derived by multiplying the integer deadhead-minute total by the deadhead pay ratio of one half and then taking the floor of the product — aggregate first, then floor, never floor each leg individually. Fourth, the raw credit is the sum of the revenue minutes and the deadhead credit. Fifth, `pay_credit_minutes` is the greater of the raw credit and the minimum-pay-credit floor of 240 minutes (four hours). The aggregate-then-floor ordering is load-bearing: two deadhead legs of 35 minutes each at the half ratio yield an aggregate of 35 minutes (the floor of 70 times one half), not 34 minutes (which would be the floor of 35 times one half added to itself). Pay credit is integer minutes with the floor applied only after aggregation; the minimum-credit floor of 240 minutes applies only to the final `actual` variant.

A forward-looking estimate is also available before a pairing closes. The scheduled variant of the pay-credit calculation treats every flight leg currently scheduled in the pairing as if it had flown, summing the revenue and deadhead block minutes as above and applying the same aggregate-then-floor deadhead arithmetic — but it does not apply the 240-minute minimum-pay-credit floor. As legs drop because of intra-pairing sick calls, the actual variant may differ from the scheduled variant. The estimate endpoint returns an object containing `scheduled_pay_credit_minutes`.

### 3.7. Cancellation, Release, and the Test-Driving Clock

A `CrewScheduler` may cancel a pairing while it is in `DRAFT`, `PUBLISHED`, `BIDDING_OPEN`, or `AWARDED`. Cancelling from `BIDDING_OPEN` transitions all `SUBMITTED` bids on the pairing to `NOT_AWARDED`, and if any bids were already `AWARDED`, they too become `NOT_AWARDED` and their `Assignment` rows are moved to `RELEASED`. Cancelling from `AWARDED` releases every `AWARDED` assignment on the pairing: the assignment transitions to `RELEASED`, the crew member's `cumulative_block_minutes_30d` is debited by `Assignment.scheduled_block_minutes` if `Pairing.start_at` falls within the rolling 30-day window from `now`, and the crew member's `cumulative_duty_minutes_7d` is debited by `Pairing.total_duty_minutes` if `Pairing.end_at` falls within the rolling 7-day window from `now`. Both debits are compensating adjustments that preserve the conservation invariant on the cumulative counters.

An individual assignment may be released by a `CrewScheduler` while it is `SCHEDULED` (for instance, in response to a sick call without an auto-cover, or as the manual half of a trade unwind). The release moves the assignment from `SCHEDULED` to `RELEASED`, applies the same window-aware debits to the affected crew member's two cumulative counters, and — if the release was caused by a sick call — opens a reserve callout via the reserve-selection algorithm.

The test-driving capability exposed under the system endpoints lets an operator advance the logical clock to a supplied `target_at` instant; the response carries the new `now`. Time-gated transitions are then run in a pinned order: pairings move `AWARDED → IN_PROGRESS` first, then `IN_PROGRESS → CLOSED` (which triggers the actual variant of pay credit on every completing assignment), then `ReservePool` rows move `AVAILABLE → EXPIRED` if `now` is past their `standby_end_at`, and finally trade requests that are still `PROPOSED` or `COUNTER_PROPOSED` after 24 hours since their `created_at` move to `EXPIRED`. A companion clock-read capability returns the current `now` without advancing it.

### 3.8. Trade Requests, Counter-Proposals, and Approval

A trade request is initiated by a `Pilot` or `FlightAttendant` who supplies their own assignment as `initiator_assignment_id`, the counterparty's assignment as `counterparty_assignment_id`, and the counterparty's crew member id as `counterparty_id`; the system records `initiator_id` from `X-User-ID`. The trade is born in `PROPOSED` with `revision_count` of zero.

The counterparty may accept (`PROPOSED → ACCEPTED`), reject (`PROPOSED → REJECTED`), or counter-propose. A counter-proposal accepts `new_initiator_assignment_id` and `new_counterparty_assignment_id` and is allowed only while `revision_count` is strictly less than 3 and the current state is `PROPOSED` or `COUNTER_PROPOSED`; the action swaps the two assignment ids in the trade, swaps the `initiator_id` and `counterparty_id` roles (the prior counterparty becomes the new proposer), and increments `revision_count` by one. Starting from `PROPOSED` it lands in `COUNTER_PROPOSED`; from `COUNTER_PROPOSED` it lands back in `PROPOSED` — the cycle is allowed up to three total rounds, after which any further counter is rejected with `ERR_INVALID_TRADE_STATE`. An initiator may cancel their own `PROPOSED` trade (taking the state to `CANCELLED`). After 24 hours of no movement from the trade's `created_at`, a clock advance moves a `PROPOSED` or `COUNTER_PROPOSED` trade to `EXPIRED`.

When the trade is `ACCEPTED`, the `CrewScheduler` approves it, which runs the legality check, transitions the trade `ACCEPTED → APPROVED → EXECUTED` within the same request, and atomically swaps `Assignment.crew_member_id` between the two assignments referenced by `initiator_assignment_id` and `counterparty_assignment_id`. After the swap, both crew members' `cumulative_block_minutes_30d` and `cumulative_duty_minutes_7d` are recomputed; the conservation invariant guarantees their sum across the two members is unchanged. Approval is rejected with `ERR_INVALID_ASSIGNMENT_STATE` if either assignment is no longer `SCHEDULED` at approval time — for instance, if a sick call beat the approval to the assignment, the trade approver receives that error and the sick call wins. If the approval itself wins the race, a concurrent sick call observes the swapped assignment and proceeds against the new occupant.

Legality has four parts. Both assignments must independently pass the FAA duty-rest check against the swap (the initiator's crew member checked against the counterparty's pairing, and the counterparty's crew member checked against the initiator's pairing); a failure yields `ERR_FAA_CREW_REST_VIOLATION` or `ERR_FAA_DUTY_VIOLATION`. Both crew members must hold the same `rank`. The `assigned_rank_slot` after the swap must match the new occupant's `rank` for both assignments. If the two crew members belong to the same `union_local_id`, no further blessing is needed; if they belong to different locals, both legs require that a `UnionSteward` from each affected local has previously called the cross-local-blessing capability against the trade. A `CrewScheduler` is barred from blessing — this is the segregation of duties — and any of the three union-rule failures (rank mismatch, slot mismatch, missing cross-local blessing) is reported as `ERR_TRADE_RULE_VIOLATION`. The compensating invariant under the union-legality check is named explicitly: the sum `sum_block_30d_both = m1.block_30d + m2.block_30d` across the two crew members is identical before and after the trade.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that mutate an existing resource respond with HTTP 200 carrying the updated representation. Deletion-style operations that produce no body respond with HTTP 204. Validation failures and state-precondition failures use the status codes given in the error catalogue; all responses (success or error) wrap their payload in the standard envelope from §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /crew-members | Register a new crew member. | CrewScheduler |
| GET | /crew-members/{id} | Get crew member with computed cumulative counters. | CrewScheduler, Pilot, FlightAttendant, UnionSteward |
| GET | /crew-members | List crew members; supports filter by rank/base_airport/status. | CrewScheduler |
| POST | /pairings | Create a Pairing in DRAFT state. | CrewScheduler |
| POST | /pairings/{id}/duty-periods | Append a DutyPeriod to a DRAFT pairing. | CrewScheduler |
| POST | /duty-periods/{id}/flight-legs | Append a FlightLeg to a DutyPeriod of a DRAFT pairing. | CrewScheduler |
| POST | /pairings/{id}/publish | Move pairing DRAFT -> PUBLISHED. | CrewScheduler |
| POST | /pairings/{id}/open-bidding | Move PUBLISHED -> BIDDING_OPEN. | CrewScheduler |
| POST | /pairings/{id}/cancel | Cancel pairing in DRAFT/PUBLISHED/BIDDING_OPEN/AWARDED states; releases assignments. | CrewScheduler |
| GET | /pairings/{id} | Retrieve a pairing with computed totals. | CrewScheduler, Pilot, FlightAttendant, UnionSteward |
| GET | /pairings | List pairings; filter by status/base_airport. | CrewScheduler, Pilot, FlightAttendant, UnionSteward |
| POST | /bids | Pilot/FA submits a bid on a BIDDING_OPEN pairing. | Pilot, FlightAttendant |
| DELETE | /bids/{id} | Withdraw a SUBMITTED bid (only by its owner). | Pilot, FlightAttendant |
| POST | /bid-windows/{id}/award | Run awarding sweep across all BIDDING_OPEN pairings in the window. | CrewScheduler |
| POST | /reserve-pool | Place a crew member on reserve for a specific date and standby window. | CrewScheduler |
| POST | /reserve-pool/{id}/call-out | Manually call out a specific reserve crew member to cover a pairing slot. | CrewScheduler |
| POST | /reserve-pool/{id}/release | Release a reserve crew member (manual). | CrewScheduler |
| GET | /reserve-pool | List reserve pool entries; filter by reserve_date / state. | CrewScheduler |
| POST | /sick-calls | Crew member reports sick; system auto-runs reserve selection to cover assignment. | Pilot, FlightAttendant, CrewScheduler |
| GET | /sick-calls/{id} | Read a sick call record. | CrewScheduler, Pilot, FlightAttendant |
| POST | /assignments | Admin override — directly create an Assignment without going through bid or reserve. | CrewScheduler |
| POST | /assignments/{id}/release | Release a SCHEDULED Assignment (admin action). | CrewScheduler |
| POST | /assignments/{id}/mark-no-show | Mark a crew member no-show at start of duty. | CrewScheduler |
| GET | /assignments/{id} | Read an assignment. | CrewScheduler, Pilot, FlightAttendant |
| GET | /assignments/{id}/pay-credit-estimate | Forward-looking pay-credit estimate (scheduled variant). | CrewScheduler, Pilot, FlightAttendant |
| GET | /assignments | List assignments; filter by crew_member_id / pairing_id / status. | CrewScheduler, Pilot, FlightAttendant |
| POST | /trade-requests | Initiator proposes a trade between two Assignments. | Pilot, FlightAttendant |
| POST | /trade-requests/{id}/counter | Counterparty proposes alternative assignment ids (cyclic, up to 3 revisions). | Pilot, FlightAttendant |
| POST | /trade-requests/{id}/accept | Counterparty accepts the current proposal. | Pilot, FlightAttendant |
| POST | /trade-requests/{id}/reject | Counterparty rejects. | Pilot, FlightAttendant |
| POST | /trade-requests/{id}/union-bless | UnionSteward blesses a cross-local trade. | UnionSteward |
| POST | /trade-requests/{id}/approve | Scheduler approves an ACCEPTED trade; executes swap atomically. | CrewScheduler |
| DELETE | /trade-requests/{id} | Initiator cancels a PROPOSED trade request. | Pilot, FlightAttendant |
| GET | /trade-requests/{id} | Read a trade request. | Pilot, FlightAttendant, CrewScheduler, UnionSteward |
| POST | /_clock/advance | Advance the server clock to a specific UTC instant; drives time-gated transitions. | CrewScheduler |
| POST | /_clock/now | Read current server clock. | CrewScheduler, Pilot, FlightAttendant, UnionSteward |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_REQUIRED | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_VALIDATION_FAILED | 400 |
| ERR_INVALID_ASSIGNMENT_STATE | 409 |
| ERR_PAIRING_INVALID_STATE | 409 |
| ERR_INVALID_TRADE_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_BID_WINDOW_CLOSED | 409 |
| ERR_BID_WINDOW_ALREADY_AWARDED | 409 |
| ERR_DUPLICATE_BID_PREFERENCE | 409 |
| ERR_SLOT_ALREADY_COVERED | 409 |
| ERR_FAA_CREW_REST_VIOLATION | 422 |
| ERR_FAA_DUTY_VIOLATION | 422 |
| ERR_TRADE_RULE_VIOLATION | 422 |
| ERR_RESERVE_OUTSIDE_WINDOW | 422 |
| ERR_NO_RESERVE_AVAILABLE | 422 |
| ERR_BID_TOO_LATE | 422 |
| ERR_PAIRING_INTERNAL_OVERLAP | 422 |
| ERR_FLIGHT_LEG_INVALID | 422 |
| ERR_CREW_NOT_AVAILABLE | 422 |
