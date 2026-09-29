# Traveling Carnival Route Ops API — Product Requirements Document

## 1. Introduction

A traveling amusement company lives or dies by the calendar. Units leave the winter quarters in the spring and spend the season hauling between county fairs, church festivals and community events, and every lot on that itinerary carries its own paperwork: a contract with the fair authority setting the revenue split and the guarantee, a stack of state permits, an inspection regime that varies from jurisdiction to jurisdiction, a crew roster mixing permanent hands with seasonal and H-2B visa labor, and a ticket-and-wristband reconciliation that has to survive a rained-out Saturday. Today that coordination happens on clipboards and in spreadsheets carried in the lead truck, and the cost of a missed lead-time filing or a double-booked Ferris wheel is measured in dark days.

The Traveling Carnival Route Ops API replaces those clipboards with a single system of record for the season. It models the haul chain as an explicit, order-bearing structure so that travel time and mandated driver rest are validated *before* a route is locked; it models the fair deal as a negotiation with a finite round budget and a hard separation between the person who sends terms and the person who countersigns them; it charges every ride against a lot's usable square footage and service amperage so that no midway is laid out on paper that cannot be laid out on grass; and it treats money as the last thing to close, running a provisional settlement while the gates are open and a materially different final settlement once the closures have been adjudicated and the sponsors have been made whole.

This document is the complete specification for that API. Sections 2 and 3 define the behavior; Section 4 lists the HTTP surface; Section 5 catalogues the error identifiers. Where the two differ in emphasis, the narrative in Sections 2 and 3 governs: it is where the business rules, thresholds and cascade orders live.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting rules that hold for every operation in the system.

### 2.1. Operating Roles and Caller Identity

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header, or that presents an `X-User-Role` value which is not one of the ten role names below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but is not listed as an authorized role for the endpoint being called is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The ten recognized roles are:

- `PlatformAdmin` — back-office operator who seeds reference data (jurisdictions, lots, rides, workers) and drives the logical clock.
- `RouteManager` — plans the season, adds stops, sequences and commits the route, drives the lot lifecycle and logs weather closures.
- `ContractNegotiator` — drafts, sends and counters fair contracts, disputes settlements and records sponsor responses; may never countersign a deal they sent.
- `GeneralManager` — countersigns deals, commits routes, adjudicates weather, proposes make-goods and finalizes money.
- `LotBoss` — runs the lot: reserves, commits and releases rides, books and cancels crew, drives setup, gates and teardown.
- `SafetyOfficer` — schedules ride inspections against allocations, and never records their outcome.
- `ComplianceClerk` — prepares and files jurisdiction permits.
- `JurisdictionOfficer` — the external authority: decides permits and records inspection results.
- `TicketingAuditor` — records ticket and wristband batches, builds and reconciles provisional settlements.
- `CrewChief` — a working crew leader who may read only their own assignment roster.

Nine of these roles are **opaque identities**. When `X-User-Role` is `PlatformAdmin`, `RouteManager`, `ContractNegotiator`, `GeneralManager`, `LotBoss`, `SafetyOfficer`, `ComplianceClerk`, `JurisdictionOfficer` or `TicketingAuditor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier — it stores the sending negotiator's value as `last_sent_by_user_id` on a contract, and compares a countersigner's value against that stored string — but it never compares an opaque `X-User-ID` to any entity's `id`.

`CrewChief` is the one **entity-backed identity**. When `X-User-Role` is `CrewChief`, `X-User-ID` is the `id` of the acting `Worker` row; ownership checks on a crew-roster read compare the worker identifier in the path to `X-User-ID`. A `CrewChief` reading the assignment roster of a worker whose `id` differs from their own `X-User-ID` is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

Two role separations are structural rather than merely conventional, and both are enforced by the system rather than by process. The negotiator who sends a set of terms may not be the general manager who executes them — a violation answers `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The safety officer who schedules an inspection may not record its outcome, and the auditor who builds a provisional settlement may not finalize it; those two separations are enforced simply by the role lists on the endpoints involved.

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

List endpoints accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` skips that many rows before the page begins and defaults to 0.

Unless a specific endpoint states otherwise, list responses are ordered by `created_at` ascending — oldest row first. This is what makes the settlement history of a contract read newest-last, and it is also the order in which cascaded child transitions are processed where processing order is significant.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filter before pagination and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every resource the API creates is addressed by an `id`: a server-minted UUID string carrying no type prefix. Alongside it, fourteen of the fifteen resource kinds — jurisdictions, lots, rides, workers, routes, route stops, contracts, ride allocations, permit applications, inspection orders, crew assignments, settlements, weather closures and make-good arrangements — carry three further system-managed fields:

- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row, including mutations that only touch computed aggregates.
- `version` (integer): a counter that increments by exactly one on every mutation of the row. Recomputing a derived aggregate — a lot's footprint total, a route's guarantee total — is a mutation and therefore bumps `version` and refreshes `updated_at` on the row that owns the aggregate.

The single exception is the ticket-sale record. A sales batch is an immutable financial fact: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, and no operation in the system mutates one after it is written.

All instants the system reads or writes — permit validity edges, shift boundaries, closure windows, decision stamps — are ISO 8601 UTC. Wherever the specification says "the logical clock", it means the server's own notion of now, which is **not** wall-clock time. Before any caller sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. An administrative test-driving capability, reserved to `PlatformAdmin`, moves the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc` value. Setting the clock changes no stored row; it does, however, change the answer to every clock-sensitive question asked afterwards, including a worker's derived visa posture, which is re-evaluated when the worker is read.

### 2.5. Stale-Version Protection on Lot and Deal Writes

Two write operations in the system are protected by optimistic concurrency against a *parent* resource's `version`, and only those two.

Reserving a ride onto a lot requires the field `expected_route_stop_version` in the request body. This field is not optional: the caller must supply the `version` of the route stop as they last observed it. If that value does not equal the route stop's current `version`, the reservation is rejected with `ERR_STALE_ROUTE_STOP_VERSION` (HTTP 412). The reason is capacity arithmetic: the caller's view of the lot's remaining footprint and amperage came from a read of the stop, and if the stop's `version` has advanced since then, that view is stale — a reservation the caller believes fits may in fact overrun the lot. The server refuses to admit the write on a stale footprint budget rather than accept it and discover the overrun later.

Creating a provisional settlement for a contract requires the field `expected_contract_version` in the request body, again non-optional, carrying the `version` of the contract as the caller last observed it. A mismatch with the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). Settlement creation legitimately supersedes any prior provisional or disputed row, so it cannot be refused on state grounds; the stale-version check is precisely what prevents an auditor from superseding a settlement computed from deal terms they never saw, after a counter round or a termination has changed the deal underneath them.

No other endpoint accepts a version field of any kind. Endpoints not named above never take one, and supplying one has no effect on their outcome.

### 2.6. Money, Hours and Rounding Discipline

All money in the system is expressed in whole **cents** as integers. There are no fractional cents anywhere in a stored row or a response body. Wherever a monetary quantity is derived from a percentage or a multiplier, the result is rounded to a whole number of cents using the **round-half-up** convention (a value ending in exactly one half rounds away from zero), and the rounding happens at the step where the specification says it happens — not later.

Where a calculation sums many rounded amounts, the rounding order is pinned and matters. Labor cost is rounded to whole cents **per assignment** and only then summed to the lot total; the alternative of summing unrounded hour-cost products across the lot and rounding once at the end is not used and yields a different total. Amusement tax is rounded to whole cents **per sales channel** and only then summed; summing the channels' gross first and rounding the tax once is not used.

Hour quantities — shift lengths, travel hours, closure hours — are carried to **two decimal places**, round-half-up. Amperage is carried to **one decimal place**, round-half-up. Percentages carry two decimal places. Square footage is always a whole number, and the specification names the direction of each truncation explicitly: a ride's charged footprint rounds **up** to the next whole square foot, a lot's usable area rounds **down**, and a lot's circulation reserve rounds **up**.

Whole-day quantities — permit lead time, elapsed operating days, a worker's consecutive-day run — are counted in UTC calendar days with no rounding at all.

### 2.7. The Order in Which a Request Is Refused

A single request can violate many rules at once, and callers must be able to rely on *which* violation is reported. The system evaluates checks in a fixed global order and returns the first failure it encounters; a check later in the order is never allowed to mask an earlier one. The order, from first-evaluated to last, is:

1. **Authentication** — headers present and the role recognized (`ERR_UNAUTHENTICATED`). Applies to every endpoint.
2. **Endpoint authorization** — the acting role appears on the endpoint's authorized-role list (`ERR_ROLE_NOT_PERMITTED`). Applies to every endpoint.
3. **Crew-chief self-scope** — a `CrewChief` reading a worker's assignment roster must be that worker (`ERR_ROLE_NOT_PERMITTED`). Applies to the worker-scoped crew-assignment list only.
4. **Path existence, left to right** — every resource named by an identifier in the URL must exist, validated in the order the identifiers appear. The 404 raised names the *first* identifier that fails to resolve, using this mapping: a route yields `ERR_ROUTE_NOT_FOUND`, a route stop `ERR_ROUTE_STOP_NOT_FOUND`, a contract `ERR_CONTRACT_NOT_FOUND`, a ride allocation `ERR_ALLOCATION_NOT_FOUND`, a permit application `ERR_PERMIT_NOT_FOUND`, an inspection order `ERR_INSPECTION_NOT_FOUND`, a crew assignment `ERR_ASSIGNMENT_NOT_FOUND`, a settlement `ERR_SETTLEMENT_NOT_FOUND`, a weather closure `ERR_CLOSURE_NOT_FOUND`, a make-good arrangement `ERR_MAKEGOOD_NOT_FOUND`, and a worker `ERR_WORKER_NOT_FOUND`.
5. **Body reference existence** — every foreign reference carried in a request body must resolve to an existing row: `jurisdiction_id`, `venue_id`, `route_id`, `previous_stop_id`, `route_stop_id`, `ride_id`, `worker_id`, `contract_id`, `ride_allocation_id` and `weather_closure_id`. Any unresolved reference yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).
6. **Body shape and range** — required fields present, enum values inside their declared sets, numeric ranges honored, and every declared intra-body rule satisfied. All failures at this stage answer `ERR_INVALID_REQUEST` (HTTP 400). Applies to every creating or acting operation.
7. **Jurisdiction uniqueness** — `ERR_DUPLICATE_JURISDICTION_STATE` when a jurisdiction is registered with a `state_code` that already exists.
8. **One live deal per lot** — `ERR_DUPLICATE_ACTIVE_CONTRACT` when a contract is drafted for a stop that already carries one in `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED`.
9. **Lot stale-version check** — `ERR_STALE_ROUTE_STOP_VERSION` on ride reservation.
10. **Deal stale-version check** — `ERR_STALE_CONTRACT_VERSION` on settlement creation.
11. **Money already closed** — `ERR_SETTLEMENT_ALREADY_FINAL` when a new settlement is created for a contract that already has a `FINAL` settlement, or when a make-good response accepts an arrangement on such a contract. This check deliberately runs **ahead** of the route-stop state gate below: the stop is `CLOSED` precisely *because* the settlement went `FINAL`, so reporting the derived stop state would hide the real cause.
12. **Route state** — `ERR_ROUTE_STATE_INVALID` when the route is not in the state the operation requires: `DRAFT` to sequence, `SEQUENCED` to commit, `DRAFT` or `SEQUENCED` to add a stop, `SEQUENCED` or `COMMITTED` to send a contract, `COMMITTED` to execute one.
13. **Route-stop state** — `ERR_STOP_STATE_INVALID`. The stop must be `PLANNED`, `CONFIRMED` or `SETUP` to reserve a ride; `CONFIRMED` to begin setup; `SETUP` to open gates; `OPEN` to tear down; `PLANNED`, `CONFIRMED`, `SETUP` or `OPEN` to be cancelled; `OPEN` or `TEARDOWN` to record a ticket sale, to log a closure, to adjudicate a closure or to create a settlement; `TEARDOWN` to finalize a settlement; `PLANNED`, `CONFIRMED` or `SETUP` to submit a permit; `PLANNED` to execute a contract; and anything other than `CLOSED` to release an allocation or cancel a crew shift.
14. **Contract state** — `ERR_CONTRACT_STATE_INVALID`: `DRAFT` or `COUNTERED` to send, `SENT` to counter and to execute, `EXECUTED` to create a settlement.
15. **Allocation state** — `ERR_ALLOCATION_STATE_INVALID`: `RESERVED` to commit; `RESERVED`, `COMMITTED` or `INSPECTION_HELD` to release and to schedule an inspection.
16. **Other child-resource state** — a permit must be `DRAFT` to submit and `SUBMITTED` to decide (`ERR_PERMIT_STATE_INVALID`); an inspection order must be `SCHEDULED` to record a result (`ERR_INSPECTION_STATE_INVALID`); a crew assignment must be `SCHEDULED` to cancel (`ERR_ASSIGNMENT_STATE_INVALID`); a weather closure must be `LOGGED` to adjudicate (`ERR_CLOSURE_STATE_INVALID`); a make-good arrangement must be `PROPOSED` to respond to (`ERR_MAKEGOOD_STATE_INVALID`).
17. **Settlement state** — `ERR_SETTLEMENT_STATE_INVALID`: a settlement must be `PROVISIONAL` to be disputed or finalized and `DISPUTED` to be reconciled, and when a newly created settlement supersedes an existing row that row must be `PROVISIONAL` or `DISPUTED`. The already-final case never surfaces here; it was caught at step 11 as `ERR_SETTLEMENT_ALREADY_FINAL`.
18. **Inspectability** — `ERR_ALLOCATION_NOT_INSPECTABLE` when a result is recorded against an inspection order whose allocation is neither `COMMITTED` nor `INSPECTION_HELD`.
19. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` on contract execution.
20. **Ride serviceability** — `ERR_RIDE_OUT_OF_SERVICE` when the ride being reserved or committed is `OUT_OF_SERVICE`.
21. **Operator certification** — `ERR_WORKER_NOT_CERTIFIED` on crew assignment.
22. **Visa validity** — `ERR_WORKER_VISA_LAPSED` on crew assignment.
23. **Consecutive-day ceiling** — `ERR_CONSECUTIVE_DAYS_EXCEEDED` on crew assignment.
24. **Inspection posture at the gates** — `ERR_INSPECTION_NOT_PASSED` when gates are opened while the lot's posture is `INSPECTION_HOLD`. Because this sits ahead of the clock, ride-minimum, permit and crew checks below, an unresolved inspection is the error a caller sees even when the lot is also short of permits or crew.
25. **Ride double-booking** — `ERR_RIDE_DOUBLE_BOOKED` on ride reservation.
26. **Crew shift overlap** — `ERR_CREW_SHIFT_OVERLAP` on crew assignment.
27. **Permit lead time** — `ERR_PERMIT_LEAD_TIME_VIOLATION` on permit submission.
28. **Inspection slot capacity** — `ERR_INSPECTION_SLOTS_FULL` on manual inspection scheduling.
29. **Travel window** — `ERR_INSUFFICIENT_TRAVEL_WINDOW` on route sequencing.
30. **Shift inside the lot's window** — `ERR_SHIFT_OUTSIDE_STOP_WINDOW` on crew assignment.
31. **Sale inside the operating window** — `ERR_SALE_OUTSIDE_OPERATING_WINDOW` on ticket-sale recording.
32. **Closure inside the operating window** — `ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW` on closure logging.
33. **Clock gates** — the logical clock must have reached the instant the gate requires: load-in for setup start (`ERR_LOAD_IN_NOT_OPEN`), the open date for gate opening (`ERR_GATES_BEFORE_OPEN_DATE`), the close date for teardown (`ERR_TEARDOWN_BEFORE_CLOSE_DATE`).
34. **Route has stops** — `ERR_ROUTE_HAS_NO_STOPS` on sequencing.
35. **Haul chain is well formed** — `ERR_STOP_CHAIN_INVALID` on sequencing.
36. **Every stop is contracted** — `ERR_STOP_NOT_CONTRACTED` on route commit.
37. **Exclusivity** — `ERR_EXCLUSIVITY_CONFLICT` on contract execution.
38. **Negotiation budget** — `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` on contract send.
39. **Rides on the lot at setup** — `ERR_NO_COMMITTED_RIDES` on setup start.
40. **Ride minimum at the gates** — `ERR_RIDE_MINIMUM_NOT_MET` on gate opening.
41. **Lot footprint budget** — `ERR_LOT_CAPACITY_EXCEEDED` on ride reservation.
42. **Lot power budget** — `ERR_LOT_POWER_EXCEEDED` on ride reservation.
43. **Housing pads** — `ERR_HOUSING_PADS_EXHAUSTED` on crew assignment.
44. **Make-good cap** — `ERR_MAKEGOOD_CAP_EXCEEDED` on make-good proposal.
45. **Gating permits** — `ERR_PERMIT_NOT_APPROVED`, or `ERR_PERMIT_EXPIRED` where the gating permit exists but has lapsed, on setup start and on gate opening.
46. **Crew coverage** — `ERR_CREW_COVERAGE_INSUFFICIENT` when gates are opened while the lot's posture is `LABOR_HOLD`.
47. **Closures adjudicated** — `ERR_CLOSURE_NOT_ADJUDICATED` on settlement finalization.
48. **Make-goods resolved** — `ERR_MAKEGOOD_PENDING` on settlement finalization.
49. **A provisional settlement exists** — `ERR_NO_PROVISIONAL_SETTLEMENT` on make-good proposal.
50. **Closure belongs to the deal's lot** — `ERR_MAKEGOOD_STOP_MISMATCH` on make-good proposal.
51. **Refund eligibility** — `ERR_REFUND_NOT_ELIGIBLE` on make-good proposal.

Section 3 states the substance of each of these checks in the workflow that raises it. This list fixes only their relative order.

### 2.8. Cascade Discipline Across the Route Hierarchy

Many operations in this system mutate more than one row. A contract execution confirms a lot, which commits the lot's reserved rides, which flips each ride's inventory posture and may create an inspection order, which in turn re-derives the lot's compliance posture. The specification calls each of those steps a **cascade hop**, and every hop is part of the same request: there is no deferred or eventual reconciliation, and a caller who reads any touched row immediately afterwards sees its post-cascade state. Each row a cascade touches has its own `version` incremented and its own `updated_at` refreshed.

Where a cascade fans out over a set of sibling children, the processing order is `created_at` ascending. This is not cosmetic. When a lot's reserved allocations are committed en bloc, each commit may consume one of the jurisdiction's finite inspection slots for a calendar day, so the order in which the allocations are processed determines which of them gets a slot and which is held.

Two of the entities in the system hold **derived state**: a route's `status` and a route stop's `compliance_posture` are both functions of their children, and both are re-derived by the server rather than set by a caller. A route advances from `COMMITTED` to `IN_PROGRESS` when the first of its stops opens its gates, and from `IN_PROGRESS` to `CLOSED` when every one of its stops has become terminal — no client request names those transitions. Likewise a lot's posture is recomputed at the end of every mutation that touches its permits, inspections, allocations or crew.

Reversals are as carefully specified as advances. When a booked shift is cancelled, the worker's scheduled hours and the lot's provisional labor cost are each reduced by exactly the amount that shift contributed, restoring both running totals to their pre-assignment values. When an allocation is released, the lot's footprint and amperage totals are reduced by exactly that allocation's charged amounts. When an executed deal is terminated because its lot went dark, the route's guarantee total is reduced by exactly that deal's guarantee — but a deal that was voided before execution never contributed to the total in the first place and therefore leaves it untouched.

### 2.9. Nested Reads and Path Resolution

Several read endpoints address a child collection through its parent: the permits filed for a lot, the crew booked on a lot, the sales batches booked to a lot, the closures logged against a lot, the inspections ordered against an allocation, the settlements of a contract, the make-goods of a contract or of a closure, and a worker's own assignment roster. In every such case the parent identifier in the path is resolved first, and a request naming a parent that does not exist fails with that parent's own 404 identifier before the system looks for any child. A caller asking for the crew of a non-existent lot receives `ERR_ROUTE_STOP_NOT_FOUND`, not an empty list.

Child collection reads accept the same `limit` and `offset` parameters as top-level lists, plus whichever narrowing filters the endpoint declares — `permit_type` and `status` on a lot's permits, `crew_role` and `status` on a lot's crew, `channel` on a lot's sales, `status` on a lot's closures, on an allocation's inspections, on a contract's settlements and on a worker's roster, and `status` together with `kind` on a contract's make-goods. Top-level list reads accept their own filters: `jurisdiction_id` and `state_code` on lots, `route_id`, `venue_id`, `previous_stop_id` and `status` on stops, `route_stop_id` and `status` on contracts, and `ride_id`, `route_stop_id` and `status` on allocations.

### 2.10. The Conserved Ledgers of a Lot

Four running totals in this system behave as ledgers: they are never edited directly, they are always the sum of a precisely defined set of contributing rows, and every operation that adds or removes a contributor adjusts them by exactly that contributor's amount.

The **footprint ledger** of a lot, `allocated_sqft_used`, is the sum of `footprint_charged_sqft` over the lot's allocations whose status is `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power ledger**, `power_amps_used`, is the sum of `power_charged_amps` over that same status set, rounded to one decimal place. Allocations that have reached `RELEASED` or `STRUCK` contribute to neither, so striking a lot at teardown or pulling a broken ride mid-run gives its footprint and amperage back to the lot.

The **labor ledger** of a lot, `labor_cost_provisional_cents`, is the sum of `cost_cents` over the lot's crew assignments whose status is `SCHEDULED` or `COMPLETED`; its per-worker twin, `scheduled_hours_total`, is the sum of `shift_hours` over that worker's assignments in the same two statuses, rounded to two decimal places. Completing a shift therefore changes neither total — `COMPLETED` remains inside the contributing set — while releasing one removes its contribution from both.

The **guarantee ledger** of a route, `total_guaranteed_cents`, is the sum of `guarantee_cents` over the contracts covering that route's stops whose status is `EXECUTED`. Executing a deal adds its guarantee; terminating an executed deal subtracts it; voiding an unexecuted one changes nothing.

### 2.11. Half-Open Intervals and UTC Day Buckets

Time intervals in this system are **half-open** unless stated otherwise: a crew shift covers `[shift_start, shift_end)`, a weather closure covers `[closed_from, closed_to)`, and a daily operating window covers its start instant up to but excluding its end instant. Two shifts that share an endpoint — one ending exactly when the next begins — therefore do not overlap and are both admitted. Two closure intervals separated by a gap of exactly zero are adjacent and merge into one.

Calendar-day buckets are likewise half-open: the UTC day `D` spans `[D 00:00:00Z, D+1 00:00:00Z)`. Inspection slot capacity is counted per such bucket, and a worker's consecutive-day run is counted over such buckets.

A ride's occupation interval, by contrast, is treated as **closed** on both ends — `[occupation_start, occupation_end]` — because a unit is physically on a lot for the whole load-in-to-teardown span including both edges, and two lots that share an edge instant cannot both hold the same unit.

Where a boundary comparison admits exact equality, this document says so explicitly. Lot footprint and amperage gates admit exact equality: a reservation that brings a lot exactly to its limit is accepted. The permit lead-time gate admits exact equality: filing exactly the required number of whole days ahead is accepted.

## 3. Business Logic & Workflows

### 3.1. Laying Out the Season: Jurisdictions, Lots and the Haul Chain

Reference data comes first, and only a `PlatformAdmin` may write it. A **jurisdiction** is a state whose rules govern every lot inside it. It is registered with a two-letter `state_code` — matching exactly two uppercase letters, and unique across all jurisdictions, a second registration of the same code being refused with `ERR_DUPLICATE_JURISDICTION_STATE` — a human-readable `name`, a `permit_lead_days` count of whole days (zero or more) that must separate a permit filing from the lot's opening, an `amusement_tax_pct` between 0 and 25 inclusive carrying at most two decimals, and a `permit_fee_cents` base filing fee of zero or more. Four further attributes may be omitted and then take defaults: `requires_state_ride_inspection` defaults to false and, when true, obliges every committed allocation of a state-inspectable ride to hold a passed state inspection before the gates may open; `inspection_slot_capacity_per_day` defaults to 2 and must be at least 1, capping how many inspection orders the state will accept in any one UTC day; `max_consecutive_work_days` defaults to 6 and must be at least 1, capping how many consecutive calendar days a single worker may be scheduled inside that state; and `housing_permit_required` defaults to false, declaring that an approved `HOUSING` permit must be in hand before any worker who needs on-lot housing may be booked at a lot in that state.

A **lot** — the fairground or midway itself — is registered against a `jurisdiction_id` with a `name`, a `city`, a `lot_area_sqft` gross area greater than zero, a `power_amps_available` service amperage greater than zero, an `expected_attendance` projection of zero or more supplied by the fair authority for the full run, and a `lot_surface` of `PAVED`, `GRAVEL` or `GRASS`, the ground condition that feeds the setup-hours multiplier a lot boss uses when planning erection crews. Optionally it declares `housing_pads_available`, the number of on-lot bunkhouse pads, defaulting to 0 and never negative.

A **route** is the season itinerary. A `RouteManager` (or a `PlatformAdmin`) opens one with a `name`, a `season_year` between 2020 and 2100 inclusive, and a `home_base_state` recording where the units winter — informational only. A new route begins in `DRAFT` with all of its computed aggregates at zero: `stop_count`, `total_haul_miles`, `total_travel_hours`, `total_guaranteed_cents` and `closed_stop_count`. Reading a route exposes all five.

Only a `RouteManager` may add a **stop** to a route. A stop names its `route_id` and its `venue_id` and pins down four instants: `load_in_start`, the moment crews may first enter the lot; `open_date`, the moment gates open to the public; `close_date`, the final operating hour; and `teardown_deadline`, the moment the lot must be clear. Two further inputs are optional. `previous_stop_id` names the stop the units haul from and is null for the first stop of the route; when supplied it must belong to the same `route_id` and must not close a cycle, and a violation of either condition is an `ERR_INVALID_REQUEST`. `haul_miles_from_previous` gives the road miles from that previous lot to this one, defaults to 0 and is never negative — it is 0 for the first stop. Stops may be added only while the route is `DRAFT` or `SEQUENCED`.

Creating a stop computes two durations immediately. `operating_days` is the span from `open_date` to `close_date` in 24-hour units, rounded **up** to the next whole day, with a floor of one day. `scheduled_operating_hours` is that day count multiplied by the standard eight-hour operating day, which makes it the denominator of every weather abatement later in the run. The new stop enters `PLANNED` with `sequence_index` and `travel_hours_from_previous` at 0, every capacity, labor and closure aggregate at 0, and a `compliance_posture` of `PERMIT_HOLD` — no lot is clear before its event permit exists. The route's `stop_count` (its non-`DARK` stops) and `total_haul_miles` are re-derived. And because the stop set has changed, a route that was `SEQUENCED` reverts `SEQUENCED → DRAFT`: `sequence_index` and `travel_hours_from_previous` are reset to 0 on every non-`DARK` stop of the route and the route's `total_travel_hours` is reset to 0. Sequencing is invalidated by any change to the stop set, and the route must be re-sequenced before it can be committed.

**Sequencing** is where the haul chain is validated and travel time is computed, a `RouteManager`-only operation that moves the route `DRAFT → SEQUENCED`. Order is structural, never derived from identifiers. The chain begins at the single non-`DARK` stop whose `previous_stop_id` is null and is extended by repeatedly finding the non-`DARK` stop whose `previous_stop_id` is the last stop found. Three structural conditions must hold, and each failure answers `ERR_STOP_CHAIN_INVALID`: exactly one non-`DARK` stop has a null `previous_stop_id`; no non-`DARK` stop is named as the predecessor of two or more non-`DARK` stops; and the chain so built covers every non-`DARK` stop of the route, which rules out both unreachable stops and cycles. Separately, a route with no non-`DARK` stop at all cannot be sequenced and answers `ERR_ROUTE_HAS_NO_STOPS`.

Walking the validated chain from its head, the system assigns `sequence_index` — 0 for the head, then one more for each link walked forward — and computes travel time for each stop. Raw driving hours are the stop's `haul_miles_from_previous` divided by an average haul speed of 45 miles per hour. Federal rest rules oblige a ten-hour break after each full eleven-hour driving shift, so the number of rest blocks is the raw driving hours divided by eleven, rounded **down** to a whole number; note that this floor is taken on the unrounded ratio. The stop's `travel_hours_from_previous` is then the raw driving hours plus ten hours for each rest block, rounded half-up to two decimals. For every stop after the head, the itinerary must actually leave room for that haul: the gap from the previous stop's `teardown_deadline` to this stop's `load_in_start`, measured in hours, must be at least this stop's `travel_hours_from_previous` plus a six-hour load-out buffer. A gap smaller than that required total is refused with `ERR_INSUFFICIENT_TRAVEL_WINDOW`.

Sequencing then re-derives the route's aggregates: `stop_count` is re-counted over the non-`DARK` stops, `total_haul_miles` is the plain sum of `haul_miles_from_previous` across the chain, and `total_travel_hours` is the sum of the per-stop travel hours, rounded half-up to two decimals. Stops that have gone `DARK` are excluded from the chain and from all three figures.

**Committing** a route (`SEQUENCED → COMMITTED`), open to a `RouteManager` or a `GeneralManager`, is the point of no return for the itinerary. It requires that every non-`DARK` stop of the route already carries a contract in `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED`; a stop with no such deal blocks the commit with `ERR_STOP_NOT_CONTRACTED`. The commit itself changes nothing but the route's status and `version`.

### 3.2. Negotiating and Countersigning the Fair Deal

A **contract** is the deal for one lot, drafted by a `ContractNegotiator` against a `route_stop_id`. The counterparty is identified by `counterparty_name`, the fair authority or community event committee, and `revenue_split_pct_operator` sets the operator's base share of taxable ticket net as a percentage between 20 and 70 inclusive with at most two decimals. Five further terms are optional at draft time: `sponsor_name`, the presenting sponsor entitled to make-good arrangements, null when the deal has no sponsor; `guarantee_cents`, the floor owed to the operator, defaulting to 0 and never negative; `ride_minimum_count`, the number of rides the operator promises to open, defaulting to 0 and never negative; `exclusivity`, one of `NONE`, `RIDES`, `FOOD` or `FULL`, defaulting to `NONE`; and `settlement_basis`, either `GREATER_OF` or `SPLIT_ONLY`, defaulting to `GREATER_OF`. A fresh deal sits in `DRAFT` with `negotiation_round` at 0, `last_sent_by_user_id` null and `executed_at` null. A lot may carry only one live deal: drafting a second contract for a stop that already has one in `DRAFT`, `SENT`, `COUNTERED` or `EXECUTED` is refused with `ERR_DUPLICATE_ACTIVE_CONTRACT`.

Negotiation is a genuine loop with a finite budget. Sending a deal moves it `DRAFT → SENT`, or `COUNTERED → SENT` when terms have been revised, and is available to a `ContractNegotiator` while the route is `SEQUENCED` or `COMMITTED` — any other route state answers `ERR_ROUTE_STATE_INVALID`. Sending also stamps `last_sent_by_user_id` with the caller's `X-User-ID`, which is what makes the later countersignature check possible. Recording the counterparty's response moves the deal `SENT → COUNTERED`, increments `negotiation_round` by one, and overwrites `revenue_split_pct_operator`, `guarantee_cents` and `ride_minimum_count` with whatever values the counter supplies. Each of those three is optional on a counter.

The budget is two rounds, and both halves of the loop respect it: a deal may be sent, or re-sent, only while its `negotiation_round` is strictly less than 2, and a counter may likewise be recorded only while that same figure is strictly less than 2. A deal that has already been countered twice dead-ends at `COUNTERED`, and a further send attempt answers `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. This matters because the negotiation loop itself never voids a deal — exhausting the budget leaves the row sitting in `COUNTERED` indefinitely, and the only paths out of the negotiation states are execution or the lot going dark.

**Executing** a deal — `SENT → EXECUTED` — is reserved to a `GeneralManager` and is the single most consequential operation in the system. Four conditions guard it beyond the deal being `SENT`. First, segregation of duties: the executing manager's `X-User-ID` must differ from the deal's stored `last_sent_by_user_id`, and an attempt by the same user to countersign what they sent is refused with `ERR_SEGREGATION_OF_DUTIES`. Second, the route must be `COMMITTED`, else `ERR_ROUTE_STATE_INVALID`. Third, the stop must still be `PLANNED`, else `ERR_STOP_STATE_INVALID`. Fourth, exclusivity: if either this deal or another already-`EXECUTED` deal on the *same lot* grants `RIDES` or `FULL` exclusivity, and the two stops' operating windows from `open_date` to `close_date` overlap, the execution is refused with `ERR_EXCLUSIVITY_CONFLICT`. A `FOOD` or `NONE` provision on both sides does not conflict.

Execution stamps `executed_at` from the logical clock, adds the deal's `guarantee_cents` to the route's `total_guaranteed_cents`, and then cascades. The first hop advances the lot `PLANNED → CONFIRMED`. The second hop commits every one of that lot's allocations sitting in `RESERVED`, processed oldest-first by `created_at`, because each commit may consume a scarce inspection slot. The third hop, caused by the second, sets each newly committed allocation's ride to `ASSIGNED` and — where the ride requires a state inspection and the lot's jurisdiction demands one — creates a single inspection order with `authority` of `STATE`, `status` of `SCHEDULED` and `attempt_number` of 1, on a date chosen by the slot ladder described in §3.5; where that ladder finds no day with free capacity, the allocation is instead moved `COMMITTED → INSPECTION_HELD` and no inspection row is written. The fourth hop, caused by the third, re-derives the lot's `compliance_posture`. Every row touched along the way has its own `version` incremented.

### 3.3. Filling the Lot: Ride Inventory and the Footprint Budget

The **ride inventory** is registered by a `PlatformAdmin`. Each ride carries a `name`; a `ride_class` of `MAJOR`, `FLAT` or `KIDDIE`, which drives its spacing multiplier, its startup power surge and its operator-certification requirement; a `footprint_sqft` bare footprint greater than zero; a `power_amps` steady-state draw greater than zero; a `crew_size_setup` of at least one worker needed to erect it; a `setup_hours` base erection time greater than zero, quoted for a paved lot; and an `axle_count` of at least one trailer axle, which drives the transport-permit surcharge. Optionally it declares `requires_state_inspection`, which defaults to **true**. A ride begins `AVAILABLE`; its `status` becomes `ASSIGNED` while a non-terminal allocation holds it and `OUT_OF_SERVICE` after a failed inspection recording at least three defects.

A `LotBoss` puts a ride on a lot by reserving an **allocation**, naming a `ride_id`, a `route_stop_id` and the mandatory `expected_route_stop_version` described in §2.5. The lot must be `PLANNED`, `CONFIRMED` or `SETUP`, and the ride must not be `OUT_OF_SERVICE` — a broken unit cannot be booked, and the attempt answers `ERR_RIDE_OUT_OF_SERVICE`. The new allocation enters `RESERVED` with `released_at` null, and its occupation interval is fixed at creation: `occupation_start` is copied from the lot's `load_in_start` and `occupation_end` from its `teardown_deadline`.

Reservation is also where the lot's physical budget is charged. A ride's **charged footprint**, `footprint_charged_sqft`, is its bare `footprint_sqft` multiplied by a spacing multiplier that depends on class — 1.35 for `MAJOR`, 1.20 for `FLAT` and 1.10 for `KIDDIE` — and rounded **up** to a whole square foot. Its **charged amperage**, `power_charged_amps`, is its `power_amps` inflated by a startup surge of 25 percent for `MAJOR`, 15 percent for `FLAT` and none at all for `KIDDIE`, rounded half-up to one decimal place.

Those charges are measured against two budgets derived from the lot. Not all of a fairground can hold rides: the usable area is 80 percent of `lot_area_sqft`, rounded **down** to a whole square foot, less a circulation reserve of half a square foot per projected attendee — that is, `expected_attendance` multiplied by 0.5 and rounded **up** to a whole square foot. If the lot's existing `allocated_sqft_used` plus the candidate's charged footprint exceeds that usable area, the reservation is refused with `ERR_LOT_CAPACITY_EXCEEDED`; a total exactly equal to the usable area is admitted. The amperage budget is 90 percent of `power_amps_available`, rounded half-up to one decimal place, and if the lot's existing `power_amps_used` plus the candidate's charged amperage exceeds it the reservation is refused with `ERR_LOT_POWER_EXCEEDED`, again with exact equality admitted. When the reservation is accepted, both lot ledgers are re-derived over the contributing status set and the lot's `version` is incremented.

A single unit cannot be in two towns at once, and it cannot teleport between them. A reservation is refused with `ERR_RIDE_DOUBLE_BOOKED` when the same ride already holds another allocation in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING` whose occupation interval either overlaps the candidate's interval, or is separated from it by less than the required haul gap. That required gap is the `travel_hours_from_previous` of whichever of the two stops sits later in its haul chain — the one with the greater `sequence_index` — plus a four-hour transport buffer.

Committing an allocation explicitly (`RESERVED → COMMITTED`) is a `LotBoss` action available while the lot is `CONFIRMED` or `SETUP`; it produces exactly the same effects as the cascaded commit described in §3.2, setting the ride to `ASSIGNED`, running the slot ladder to create a `STATE` inspection order where the ride and jurisdiction both demand one, holding the allocation as `INSPECTION_HELD` where the ladder finds no free day, and re-deriving the lot's posture. It, too, refuses an `OUT_OF_SERVICE` ride with `ERR_RIDE_OUT_OF_SERVICE`.

**Releasing** an allocation is the divergent branch, and it is available to a `LotBoss` or a `RouteManager` from `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING` so long as the lot is not `CLOSED`. Release stamps `released_at` from the logical clock and reduces the lot's `allocated_sqft_used` by this allocation's `footprint_charged_sqft` and its `power_amps_used` by this allocation's `power_charged_amps`. The ride returns to `AVAILABLE` unless it is `OUT_OF_SERVICE` or still holds another allocation in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. Unlike commit, release creates no inspection order, and it leaves any existing `SCHEDULED` inspection order on the allocation untouched — the posture calculation simply ignores inspections belonging to terminal allocations. The lot's posture is then re-derived.

Releasing an `OPERATING` allocation is the mid-run pull-off: a ride that breaks down is hauled off the midway. It carries all of the effects above and additionally re-derives the lot's `operating_ride_count`, so the pulled unit stops counting as operated. This is the only path by which the final settlement can count *fewer* rides than the provisional one already counted.

### 3.4. Permits and the Jurisdiction Paper Trail

A `ComplianceClerk` prepares each **permit application** against a `route_stop_id` with a `permit_type`, a `valid_from` instant and a `valid_until` instant that must be strictly later than `valid_from`. Four permit types exist and they do very different work: an `EVENT` permit gates the opening of the gates, a `TRANSPORT` permit gates the start of setup, an `ELECTRICAL` permit is informational only, and a `HOUSING` permit is what a jurisdiction that sets `housing_permit_required` demands before workers needing on-lot housing may be booked. A transport filing also declares `axles_declared`, the total trailer axles on the move, defaulting to 0 and never negative; other permit types carry 0.

The filing fee, `fee_cents`, is computed at creation and never renegotiated: it is the jurisdiction's `permit_fee_cents` base fee plus, for a `TRANSPORT` permit only, a surcharge of 1,500 cents (fifteen dollars) for each declared axle. For every other permit type the axle component is zero. A new permit sits in `DRAFT` with `submitted_at`, `decided_at` and `denial_reason` all null.

**Submitting** a permit (`DRAFT → SUBMITTED`) is also a `ComplianceClerk` action, admitted while the lot is `PLANNED`, `CONFIRMED` or `SETUP`, and it is where the lead-time rule bites. The number of whole days from the logical clock to the lot's `open_date` — the elapsed seconds divided by one day and rounded **down** to a whole number — must be at least the jurisdiction's `permit_lead_days`; filing exactly that many whole days ahead is admitted, and filing any later is refused with `ERR_PERMIT_LEAD_TIME_VIOLATION`. Submission stamps `submitted_at` from the logical clock.

Only a `JurisdictionOfficer` decides. The decision call carries a `decision` of either `APPROVE` or `DENY` and, on a denial, a `denial_reason`; a denial submitted without a reason is refused with `ERR_INVALID_REQUEST`. Approval moves the permit `SUBMITTED → APPROVED` and stamps `decided_at`; denial moves it `SUBMITTED → DENIED`, stamps `decided_at` and stores the supplied `denial_reason` on the row. Both outcomes re-derive the lot's `compliance_posture` — a denied `EVENT` permit is what drives a lot into `PERMIT_HOLD`.

Permits lapse in two ways. An `APPROVED` permit whose `valid_until` has fallen behind the logical clock is moved `APPROVED → EXPIRED`, and this sweep is evaluated at the start of setup and at the opening of the gates, before the permit checks those operations run — so a permit that lapsed while the lot sat idle is recognized as expired rather than silently satisfying the gate. Both an `APPROVED` and a `SUBMITTED` permit are moved to `EXPIRED` when the lot goes `DARK`. Each of these transitions re-derives the lot's posture and increments the permit's `version`.

### 3.5. Ride Inspections and the Slot Ladder

Jurisdictions that set `requires_state_ride_inspection` will not let a state-inspectable ride open to the public without a passed state inspection, and they accept only a fixed number of inspections per day. That scarcity is managed by the **slot ladder**, which is what the system uses whenever it creates an inspection order for itself during a commit.

The ladder considers the UTC calendar days from the day of the lot's `load_in_start` through the day of its `open_date`, inclusive. For each such day it counts how many inspection orders in the *same jurisdiction* already fall in that day's half-open UTC bucket, counting rows in `SCHEDULED`, `PASSED` and `FAILED` alike — a consumed slot is consumed whatever the outcome. A day is a candidate when that count is strictly below the jurisdiction's `inspection_slot_capacity_per_day`. The ladder picks the **earliest** candidate day, and because calendar days are distinct the ranking never ties; the chosen day at 14:00:00Z becomes the inspection's `scheduled_date`. When the candidate set is empty, no synthetic row is invented: the allocation is moved `COMMITTED → INSPECTION_HELD` instead, and the lot's posture reflects the hold.

A `SafetyOfficer` may also schedule an inspection by hand, naming a `ride_allocation_id`, an `authority` of either `STATE` or `THIRD_PARTY`, and a `scheduled_date`. Only a `STATE` inspection satisfies a jurisdiction's state-inspection demand; a `THIRD_PARTY` inspection never does. The allocation must be `RESERVED`, `COMMITTED` or `INSPECTION_HELD`. The same capacity rule applies to manual scheduling: if the scheduled date's UTC day bucket already holds as many inspection orders in `SCHEDULED`, `PASSED` or `FAILED` in that jurisdiction as its `inspection_slot_capacity_per_day` allows, the request is refused with `ERR_INSPECTION_SLOTS_FULL`. The new order enters `SCHEDULED` with `defect_count` 0 and `result_recorded_at` null, and its `attempt_number` is computed as one more than the number of inspection orders already `FAILED` on the same allocation — so a re-inspection is a *new* row rather than a reopened one. Creating an order re-derives the lot's posture.

Recording a result is a `JurisdictionOfficer`'s exclusive act, and it forks. The call carries a `result` of either `PASS` or `FAIL`, plus a `defect_count` where relevant. Either way the allocation must be `COMMITTED` or `INSPECTION_HELD` at the moment the result lands, and an allocation in any other status answers `ERR_ALLOCATION_NOT_INSPECTABLE`.

On the **pass** branch — `SCHEDULED → PASSED` — the order's `defect_count` is set to 0 and `result_recorded_at` is stamped from the logical clock. If the allocation was `INSPECTION_HELD` and its ride is not `OUT_OF_SERVICE`, the allocation returns `INSPECTION_HELD → COMMITTED`, closing the hold loop; if the ride is `OUT_OF_SERVICE` the allocation stays `INSPECTION_HELD` even on a pass. The lot's posture is then re-derived, which may clear an `INSPECTION_HOLD`.

On the **fail** branch — `SCHEDULED → FAILED` — the request must carry a `defect_count` of at least 1, and a failure recorded without one is refused with `ERR_INVALID_REQUEST`. The supplied count is stored and `result_recorded_at` is stamped. The allocation is moved `COMMITTED → INSPECTION_HELD`. If the failure recorded three or more defects, the ride itself is set `OUT_OF_SERVICE`, which both blocks any further reservation of that unit and prevents a later passing inspection from releasing the hold. The lot's `compliance_posture` is set directly to `INSPECTION_HOLD`. The allocation's and the order's `version` are each incremented.

### 3.6. Crewing the Midway: Workers, Shifts and Duty Exposure

A **worker** is registered by a `PlatformAdmin` with a `full_name`, an `employment_type` of `PERMANENT`, `SEASONAL_DOMESTIC` or `H2B_VISA`, and an `hourly_rate_cents` straight-time rate greater than zero. `visa_expires_on` records the instant an H-2B authorization lapses; it is required exactly when `employment_type` is `H2B_VISA` and must be null otherwise, a mismatch either way being refused with `ERR_INVALID_REQUEST`. Two optional attributes shape scheduling: `certified_ride_classes`, a subset of `MAJOR`, `FLAT` and `KIDDIE` the worker is qualified to operate, defaulting to an empty list; and `housing_required`, defaulting to false, which when true means each concurrent assignment consumes one of the lot's bunkhouse pads. A new worker's `scheduled_hours_total` and `worked_days_count` are 0.

A worker's `compliance_status` is derived, never supplied, and it is re-evaluated against the logical clock whenever the worker is read — including immediately after registration. A worker whose `employment_type` is not `H2B_VISA` is always `CLEAR`. An H-2B worker whose `visa_expires_on` already lies before the clock is `VISA_LAPSED`. An H-2B worker whose `visa_expires_on` is within thirty days of the clock is `VISA_EXPIRING`. Any other H-2B worker is `CLEAR`.

A `LotBoss` books a **crew assignment** naming a `route_stop_id`, a `worker_id`, a `crew_role` of `SETUP`, `RIDE_OPERATOR`, `TEARDOWN` or `TICKETING`, and a `shift_start` and `shift_end` where the end must be strictly later than the start. The booking enters `SCHEDULED`, and five business checks guard it, evaluated in the global order of §2.7.

Certification comes first. A `RIDE_OPERATOR` shift requires that the worker's `certified_ride_classes` include the `ride_class` of at least one ride allocated to that lot in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`; a worker certified for nothing on the lot is refused with `ERR_WORKER_NOT_CERTIFIED`. `SETUP`, `TEARDOWN` and `TICKETING` shifts carry no certification requirement.

The visa gate comes next: for an `H2B_VISA` worker, the shift's `shift_end` may not fall later than `visa_expires_on`, and a shift running past the authorization is refused with `ERR_WORKER_VISA_LAPSED`.

Then the consecutive-day ceiling. An assignment is deemed to cover every UTC calendar date from the date of its `shift_start` through the date one second before its `shift_end`, inclusive. For the purpose of this gate, the system takes the union of the dates covered by all of that worker's assignments whose lot lies in the *same jurisdiction* and whose status is `SCHEDULED` or `COMPLETED`, with the candidate assignment included in the union, and finds the longest run of consecutive UTC dates in that union. If the longest run exceeds the jurisdiction's `max_consecutive_work_days`, the booking is refused with `ERR_CONSECUTIVE_DAYS_EXCEEDED`. Note that this scheduled basis counts booked-but-unworked shifts: a shift on the books consumes a consecutive day whether or not it is ever worked.

Overlap comes next: the worker may hold no other `SCHEDULED` assignment whose half-open interval intersects the candidate's, and a collision answers `ERR_CREW_SHIFT_OVERLAP`. Back-to-back shifts sharing an endpoint do not intersect and are admitted.

Then the shift-window rule, which differs by role. `SETUP` and `TEARDOWN` shifts may fall anywhere inside the lot's load-in-to-teardown span, from `load_in_start` to `teardown_deadline`. `RIDE_OPERATOR` and `TICKETING` shifts must lie inside the public operating window, from `open_date` to `close_date`. A shift outside the window its role permits is refused with `ERR_SHIFT_OUTSIDE_STOP_WINDOW`.

Last comes housing. `housing_pad_assigned` on the assignment is set to true exactly when the worker's `housing_required` is true, and such an assignment occupies a lot pad for the whole load-in-to-teardown window. If the count of the lot's `SCHEDULED` assignments carrying `housing_pad_assigned`, including the candidate, would exceed the lot's `housing_pads_available`, the booking is refused with `ERR_HOUSING_PADS_EXHAUSTED`.

Once admitted, the assignment's cost is computed and rounded per assignment before it enters any total. `shift_hours` is the elapsed time from `shift_start` to `shift_end` expressed in hours and rounded half-up to two decimals. Of those hours, the straight-time portion is whichever is smaller: the shift hours themselves, or the ten-hour overtime threshold; the overtime portion is the excess of the shift hours over ten hours, or zero when there is none. The base amount is the straight-time hours multiplied by the worker's `hourly_rate_cents` plus the overtime hours multiplied by that same rate at time-and-a-half, the whole sum rounded half-up to whole cents. A rigging premium of 10 percent of that base amount, rounded half-up to whole cents, is added for `SETUP` and `TEARDOWN` shifts only, and is zero for `RIDE_OPERATOR` and `TICKETING`. A housing stipend of 3,500 cents (thirty-five dollars) per shift is added when the worker's `housing_required` is true, and is zero otherwise. The assignment's `cost_cents` is the sum of those three components. The lot's `labor_cost_provisional_cents` and the worker's `scheduled_hours_total` are then re-derived over the contributing statuses as described in §2.10, and the lot's posture is re-derived.

Cancelling a booked shift (`SCHEDULED → RELEASED`) is a `LotBoss` action available while the lot is not `CLOSED`. It reverses exactly what the booking added: the worker's `scheduled_hours_total` falls by that assignment's `shift_hours` and the lot's `labor_cost_provisional_cents` falls by its `cost_cents`, restoring both ledgers to their pre-assignment values. The housing pad is freed where `housing_pad_assigned` was true. The lot's posture is re-derived, which may newly raise a `LABOR_HOLD`, and the assignment's `version` is incremented.

Shifts are completed by the system, not by a caller: when a lot closes, every one of its `SCHEDULED` assignments moves `SCHEDULED → COMPLETED`. Completion recomputes `worked_days_count` for the assignment's worker, and it deliberately leaves `scheduled_hours_total` unchanged, since `COMPLETED` remains inside the scheduled-hours contributing set. `worked_days_count` uses the **worked** basis rather than the scheduled one: it is the number of distinct UTC calendar dates covered by that worker's `COMPLETED` assignments across every jurisdiction. Because the worked basis counts only completed rows, the same worker with the same history yields a shorter run than the scheduled basis whenever a booked shift was released or its lot went `DARK`.

A `CrewChief` may read their own roster and their own worker row, and nothing else.

### 3.7. Readiness, Opening the Gates, and Going Dark

A lot's `compliance_posture` is the single derived answer to "may this midway open?", and it is recomputed at the end of every mutation that touches the lot's permits, inspections, allocations or crew. It takes one of four values — `CLEAR`, `PERMIT_HOLD`, `INSPECTION_HOLD` or `LABOR_HOLD` — and it is determined by a **first-match-wins** ladder evaluated in exactly this precedence order.

The first test is the event permit. Unless the lot holds a permit whose `permit_type` is `EVENT`, whose `status` is `APPROVED`, whose `valid_from` is at or before the lot's `open_date` and whose `valid_until` is at or after its `close_date`, the posture is `PERMIT_HOLD`. The blocking error that posture would raise is `ERR_PERMIT_NOT_APPROVED`, except where such a permit exists but has gone `EXPIRED`, in which case it is `ERR_PERMIT_EXPIRED`.

The second test is inspections. If any of the lot's allocations in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING` either is itself `INSPECTION_HELD`, or belongs to a ride whose `requires_state_inspection` is true at a lot whose jurisdiction sets `requires_state_ride_inspection` and has no inspection order of its own with `authority` `STATE`, `status` `PASSED` and a `scheduled_date` at or before the lot's `open_date`, then the posture is `INSPECTION_HOLD` and its blocking error is `ERR_INSPECTION_NOT_PASSED`.

The third test is labor, and it is a three-way disjunction: the posture is `LABOR_HOLD` if the count of the lot's `SCHEDULED` `RIDE_OPERATOR` assignments is fewer than one per allocation of the lot in `COMMITTED` or `OPERATING`; **or** any of the lot's `SCHEDULED` assignments belongs to a worker whose `compliance_status` is `VISA_LAPSED`; **or** the count of the lot's `SCHEDULED` assignments carrying `housing_pad_assigned` exceeds the lot's `housing_pads_available`. Its blocking error is `ERR_CREW_COVERAGE_INSUFFICIENT`.

If none of the three matches, the posture is `CLEAR` and there is no blocking error.

The readiness read exposes this reasoning directly, returning the lot's `route_stop_id`, its `compliance_posture`, the `blocking_error_id` that posture would raise (null when the posture is `CLEAR`), and four narrower signals: `event_permit_ok`, true when the event-permit test above is satisfied; `inspections_ok`, true when no allocation trips the inspection test; `crew_coverage_ok`, true when none of the three labor conditions holds; `committed_ride_count`, the number of the lot's allocations currently in `COMMITTED`; and `ride_minimum_required`, the `ride_minimum_count` of the lot's executed deal.

**Beginning setup** — `CONFIRMED → SETUP` — is available to a `RouteManager` or a `LotBoss`. Before its own checks run, the system sweeps the lot's `APPROVED` permits and expires any whose `valid_until` has fallen behind the logical clock, so that a lapsed transport permit cannot satisfy the gate that follows. Three conditions then apply. The logical clock must have reached the lot's `load_in_start`, else `ERR_LOAD_IN_NOT_OPEN`. The lot must hold at least one allocation in `COMMITTED` or `INSPECTION_HELD`, else `ERR_NO_COMMITTED_RIDES` — there is no point opening a gate to an empty lot. And the lot must hold a `TRANSPORT` permit in `APPROVED` whose `valid_from` is at or before `load_in_start` and whose `valid_until` is at or after `teardown_deadline`, else `ERR_PERMIT_NOT_APPROVED`. Setup re-derives the posture and increments the lot's `version`.

**Opening the gates** — `SETUP → OPEN` — is likewise a `RouteManager` or `LotBoss` action, and it is the most heavily guarded transition on the lot. The checks run in the global order of §2.7, which means an unresolved inspection is reported before a missing permit or a thin crew: first the lot must be `SETUP`; then the posture must not be `INSPECTION_HOLD`, else `ERR_INSPECTION_NOT_PASSED`; then the logical clock must have reached `open_date`, else `ERR_GATES_BEFORE_OPEN_DATE`; then the count of the lot's allocations in `COMMITTED` must be at least the `ride_minimum_count` of the lot's `EXECUTED` deal, else `ERR_RIDE_MINIMUM_NOT_MET`; then the `EVENT` permit must be in hand and unexpired, else `ERR_PERMIT_NOT_APPROVED` or `ERR_PERMIT_EXPIRED`; and finally the posture must not be `LABOR_HOLD`, else `ERR_CREW_COVERAGE_INSUFFICIENT`. Stated the other way round, the posture must come out `CLEAR` on recomputation, and each hold reports its own blocking error.

Opening the gates moves every one of the lot's `COMMITTED` allocations to `OPERATING` and re-derives the lot's `operating_ride_count`. It also reaches across to the route: a route sitting in `COMMITTED` advances `COMMITTED → IN_PROGRESS` the moment its first lot opens. The lot's `version` is incremented.

**Tearing down** — `OPEN → TEARDOWN` — requires only that the logical clock has reached the lot's `close_date`, a premature attempt answering `ERR_TEARDOWN_BEFORE_CLOSE_DATE`. Teardown moves every `OPERATING` allocation to `STRUCK`, and each struck allocation returns its ride to `AVAILABLE` unless that ride is `OUT_OF_SERVICE`. Because `operating_ride_count` counts allocations in `OPERATING` **and** `STRUCK`, teardown freezes that count rather than zeroing it — which is precisely what the final settlement needs.

**Going dark** is the escape hatch, open to a `RouteManager` or a `GeneralManager` while the lot is `PLANNED`, `CONFIRMED`, `SETUP` or `OPEN`, and refused with `ERR_SETTLEMENT_ALREADY_FINAL` once the lot's deal has a `FINAL` settlement. The side-effect set is identical from all four originating states and is conditional on each child's own current state. The first hop branches on the deal: a contract in `EXECUTED` is moved to `TERMINATED`, while one in `DRAFT`, `SENT` or `COUNTERED` is moved to `VOID`. The second hop follows from the first: the `TERMINATED` branch decreases the route's `total_guaranteed_cents` by that deal's `guarantee_cents`, whereas the `VOID` branch leaves the route total untouched because an unexecuted guarantee was never added to it, and leaves `negotiation_round` and every negotiated term exactly as they stood. Beyond the deal, every allocation of the lot in `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING` is moved to `RELEASED`, each release returning its ride to `AVAILABLE` unless that ride is `OUT_OF_SERVICE` or still holds another non-terminal allocation; every `SCHEDULED` crew assignment is moved to `RELEASED`, decreasing the worker's `scheduled_hours_total` and the lot's `labor_cost_provisional_cents`; every permit in `SUBMITTED` or `APPROVED` is moved to `EXPIRED`; a route sitting in `SEQUENCED` reverts to `DRAFT`; and the route's `stop_count` and `closed_stop_count` are re-derived. The lot's `version` is incremented.

The two terminal lot states, `CLOSED` and `DARK`, are both counted by the route's `closed_stop_count`. When that count reaches the route's `stop_count` and the route holds at least one stop, a route in `IN_PROGRESS` advances `IN_PROGRESS → CLOSED`. Reaching `CLOSED` is the end of the route's lifecycle.

### 3.8. Tickets, Weather, and the Money at the End of the Run

Revenue is booked as **ticket sales** batches by a `TicketingAuditor` while the lot is `OPEN` or `TEARDOWN`. Each batch names a `channel` of `WRISTBAND`, `SINGLE`, `PRESALE` or `COMP`; a `units` count greater than zero; a `unit_price_cents` price per unit that must be exactly 0 when the channel is `COMP` and strictly greater than 0 for every other channel, a violation either way answering `ERR_INVALID_REQUEST`; and a `business_date`, the UTC operating date the batch is booked to, which must fall inside the lot's window from `open_date` to `close_date`, a batch outside it being refused with `ERR_SALE_OUTSIDE_OPERATING_WINDOW`. The batch's `gross_cents` is its `units` multiplied by its `unit_price_cents`. Comp admissions are attendance, not revenue: they contribute zero gross and are excluded from every channel bucket in the settlement arithmetic.

A **weather closure** is logged against an `OPEN` or `TEARDOWN` lot by a `RouteManager` or a `LotBoss`, naming a `cause` of `WIND`, `RAIN`, `LIGHTNING` or `HEAT`, plus `closed_from` and a `closed_to` strictly later than it. The closure must actually intersect at least one of the lot's daily operating windows, else it is refused with `ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW`. Logging computes `closure_hours_raw`, the elapsed hours from `closed_from` to `closed_to` rounded half-up to two decimals, before any clipping or merging, and the row enters `LOGGED` with `abated_hours` at 0.

Only a `GeneralManager` may **adjudicate** a closure (`LOGGED → ADJUDICATED`), and only while the lot is `OPEN` or `TEARDOWN`. Adjudication is what turns wall-clock downtime into abatable hours. The lot's daily operating windows are constructed as one window per operating day: for each day index from zero through one less than `operating_days`, the window runs from `open_date` advanced by that many 24-hour periods, for eight hours. Each closure is **clipped** to the intersection of its own half-open interval with the union of those windows — downtime at three in the morning abates nothing.

The clipped intervals of all of the lot's `ADJUDICATED` closures, including the row being adjudicated by the current call, are then merged. The closures are processed chronologically, ordered by `closed_from` ascending, then `closed_to` ascending, then `created_at` ascending; their clipped intervals are sorted by start then end and joined whenever the next interval's start is at or before the current interval's end, so that a gap of exactly zero merges. The merged total is the sum of the merged intervals' lengths in hours, rounded half-up to two decimals. That total becomes the lot's `closure_hours_adjudicated` only if it is at least two hours; a merged total below two hours abates nothing at all and the lot's figure is 0. Rows in `LOGGED` contribute nothing to any of this.

Each closure's own `abated_hours` is attributed by **chronological first claim**, so overlapping closures never double-count. Walking the closures in that same chronological order, a row's `abated_hours` is the length in hours of its clipped interval minus whatever earlier rows have already claimed, rounded half-up to two decimals; the row's clipped interval is then added to the claimed set. A closure entirely covered by an earlier one therefore abates zero hours even though its `closure_hours_raw` is positive.

A **settlement** reconciles one deal, and it is built by a `TicketingAuditor` naming a `contract_id` and the mandatory `expected_contract_version`. The deal must be `EXECUTED` and the lot must be `OPEN` or `TEARDOWN`. Creating a settlement moves any prior settlement of the same deal in `PROVISIONAL` or `DISPUTED` to `SUPERSEDED`, writes a new row whose `variant` and `status` are both `PROVISIONAL` with `dispute_reason` and `finalized_at` null, and increments the contract's `version` by one.

The settlement calculation runs in eight numbered steps and **the order is pinned**, because the dependency graph looks circular: the volume-tier bonus depends on the post-tax net, which depends on the tax; the penalty cap depends on the operator's split, which depends on the tier bonus; and the guarantee floor is compared against the already-penalised split. Every figure below is defined only by this order.

1. **Channel gross.** For each of `WRISTBAND`, `SINGLE` and `PRESALE` separately, sum `units` multiplied by `unit_price_cents` over the lot's sales batches in that channel. These are exact integers with no rounding. The settlement's `gross_cents` is the sum of those three channel figures. `COMP` batches enter none of them.
2. **Tax, rounded per channel then summed.** For each of the same three channels, multiply that channel's gross by the jurisdiction's `amusement_tax_pct` divided by 100 and round half-up to whole cents. The settlement's `tax_cents` is the sum of the three rounded channel taxes. Summing the channels first and rounding once is not used and gives a different answer.
3. **Taxable net.** `taxable_net_cents` is `gross_cents` less `tax_cents`.
4. **Volume tier on the post-tax net.** The tier bonus is measured against the taxable net, with inclusive lower bounds: a net of at least 5,000,000 cents earns a bonus of 5.0 percentage points; otherwise a net of at least 2,000,000 cents earns 2.5 percentage points; otherwise the bonus is 0. `effective_operator_pct` is the deal's `revenue_split_pct_operator` plus that bonus, capped at 72.5 — whichever is smaller.
5. **Split share.** `split_share_cents` is `taxable_net_cents` multiplied by `effective_operator_pct` divided by 100, rounded half-up to whole cents.
6. **Ride-minimum penalty, capped against that split.** Count the lot's allocations whose status falls in the counting set for the variant in force (defined below). The ride shortfall is the deal's `ride_minimum_count` less that count, or zero if the count meets or exceeds the minimum. The raw penalty is the shortfall multiplied by 25,000 cents (two hundred and fifty dollars) per missing ride. The cap is 10 percent of `split_share_cents`, rounded half-up to whole cents. `shortfall_penalty_cents` is whichever of the raw penalty and the cap is smaller.
7. **The guarantee floor, which differs by variant.** See below.
8. **Amount due.** The base due is `split_share_cents` less `shortfall_penalty_cents`. Where the deal's `settlement_basis` is `GREATER_OF`, the due figure is whichever is larger of that base due and `guarantee_effective_cents`; where it is `SPLIT_ONLY`, the due figure is the base due with no guarantee floor at all. `settlement_due_cents` is then that due figure less `makegood_deduction_cents`, or zero if the subtraction would go negative — whichever is larger.

The two **variants** differ in three places, and identical ticket data therefore yields a different `settlement_due_cents` depending on which is in force. The `PROVISIONAL` variant is used when a settlement is created and again when a disputed one is reconciled, while the run is still open or being struck. It counts rides forward-looking: allocations in `COMMITTED`, `INSPECTION_HELD` and `OPERATING` all count toward the ride minimum in step 6. In step 7 it pro-rates the guarantee by elapsed operating days: the elapsed day count is the whole days from the lot's `open_date` to the earlier of the logical clock and the lot's `close_date`, rounded down, plus one, taken as at least one day, and then capped at the lot's `operating_days`; `guarantee_effective_cents` is the deal's `guarantee_cents` multiplied by that elapsed count divided by `operating_days`, rounded half-up to whole cents. And `makegood_deduction_cents` is always 0 under this variant — the provisional numbers ignore every make-good.

The `FINAL` variant is used only at finalization, once the lot is being struck and every closure has been adjudicated. It counts only rides that actually operated: allocations in `OPERATING` and `STRUCK` count in step 6, which is why a mid-run pull-off can lower the final ride count below what the provisional already counted. In step 7 it abates the guarantee by adjudicated closure hours instead of pro-rating by elapsed days: the abatement ratio is the lot's `closure_hours_adjudicated` divided by its `scheduled_operating_hours`, capped at 1; `guarantee_effective_cents` is the deal's `guarantee_cents` multiplied by one minus that ratio, rounded half-up to whole cents. And `makegood_deduction_cents` is the sum of `amount_cents` over the deal's make-good arrangements whose `kind` is `CASH_REFUND` and whose `status` is `ACCEPTED`.

Settlements can be contested. A `ContractNegotiator` disputes a `PROVISIONAL` settlement (`PROVISIONAL → DISPUTED`), supplying a `dispute_reason` that is stored on the row. A `TicketingAuditor` then reconciles it (`DISPUTED → PROVISIONAL`), re-running the provisional variant over the sales rows as they now stand, overwriting every computed amount on the same row and clearing `dispute_reason` back to null. That loop may run as often as the parties need; the row's identity never changes.

**Make-good arrangements** are how a sponsor is compensated for weather. A `GeneralManager` proposes one naming a `weather_closure_id`, a `contract_id` and a `kind` of `CASH_REFUND`, `SPONSOR_CREDIT` or `BONUS_DAY`. Four conditions guard the proposal. The deal must have exactly one settlement in `PROVISIONAL`, else `ERR_NO_PROVISIONAL_SETTLEMENT`. The referenced closure must be `ADJUDICATED` and must belong to the same lot as the deal, else `ERR_MAKEGOOD_STOP_MISMATCH`. Refund eligibility depends on the weather: a `CASH_REFUND` is admitted only where the closure's `cause` is `WIND` or `LIGHTNING`, since only those are refund-eligible causes; a `RAIN` or `HEAT` closure may be compensated with `SPONSOR_CREDIT` or `BONUS_DAY` only, and a cash refund against one is refused with `ERR_REFUND_NOT_ELIGIBLE`. And the cumulative cap must hold, as follows.

The arrangement's `amount_cents` is computed at proposal time. The abatement ratio for the named closure is its own `abated_hours` divided by the lot's `scheduled_operating_hours`, capped at 1. The base amount is that ratio applied to the deal's `PROVISIONAL` settlement's `split_share_cents`, rounded half-up to whole cents. The raw amount is that base multiplied by the multiplier for the chosen kind — 1.00 for `CASH_REFUND`, 1.25 for `SPONSOR_CREDIT`, and 0.00 for `BONUS_DAY`, which is in-kind and therefore always carries a zero amount — again rounded half-up to whole cents. The cap is 30 percent of the deal's `guarantee_cents`, rounded half-up to whole cents. Summing the `amount_cents` already committed by the deal's arrangements in `PROPOSED` or `ACCEPTED`, if that running total plus the smaller of the raw amount and the cap would exceed the cap, the proposal is refused with `ERR_MAKEGOOD_CAP_EXCEEDED`. Otherwise `amount_cents` is the smaller of the raw amount and the cap, and the arrangement enters `PROPOSED` with `responded_at` null.

The sponsor's answer is recorded by a `ContractNegotiator` and carries a `response` of either `ACCEPT` or `DECLINE`. Accepting (`PROPOSED → ACCEPTED`) is admitted only while no settlement of the deal is `FINAL`, else `ERR_SETTLEMENT_ALREADY_FINAL`; it stamps `responded_at` from the logical clock, and the amount will enter the final settlement's `makegood_deduction_cents` at finalization when the `kind` is `CASH_REFUND`. Declining (`PROPOSED → DECLINED`) also stamps `responded_at`, and the amount never enters any settlement.

**Finalizing** is the last act of the run, reserved to a `GeneralManager` and moving the settlement `PROVISIONAL → FINAL`. Four conditions apply: the settlement must be `PROVISIONAL`, else `ERR_SETTLEMENT_STATE_INVALID`; the lot must be `TEARDOWN`, else `ERR_STOP_STATE_INVALID`; every weather closure of the lot must be `ADJUDICATED`, a lingering `LOGGED` closure answering `ERR_CLOSURE_NOT_ADJUDICATED`; and every make-good arrangement of the deal must be `ACCEPTED` or `DECLINED`, a lingering `PROPOSED` one answering `ERR_MAKEGOOD_PENDING`. Finalization re-runs the calculation under the `FINAL` variant, overwrites every computed amount on the row, sets `variant` to `FINAL` and stamps `finalized_at` from the logical clock.

It then cascades. The lot advances `TEARDOWN → CLOSED`. That closure moves every `SCHEDULED` crew assignment of the lot to `COMPLETED`, and each completion recomputes its worker's `worked_days_count` on the worked basis. The route's `closed_stop_count` is re-derived, and a route in `IN_PROGRESS` whose closed count has caught up with its `stop_count` advances to `CLOSED`. Every row along that chain has its `version` incremented and its `updated_at` refreshed. Once a settlement is `FINAL`, the money for that lot is closed: no further settlement may be created for the deal, no make-good may be accepted against it, and the lot itself can no longer be sent dark.

## 4. Endpoint Definitions

Operations that mint a brand-new resource — registering reference data, opening a route, adding a stop, drafting a deal, reserving a ride, filing a permit, scheduling an inspection, booking a shift, recording a sales batch, building a settlement, logging a closure or proposing a make-good — answer `201 Created`. Every operation that modifies an existing resource, drives a state transition, or reads data answers `200 OK`. Request bodies, response bodies and side effects are not repeated here; they are specified in Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jurisdictions` | Register a state jurisdiction with its permit, inspection, tax and labor rules | PlatformAdmin |
| GET | `/jurisdictions/{id}` | Read a jurisdiction | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ComplianceClerk |
| POST | `/venues` | Register a lot inside a jurisdiction | PlatformAdmin |
| GET | `/venues/{id}` | Read a lot | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss |
| GET | `/venues` | List lots, filterable by jurisdiction | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss |
| POST | `/rides` | Register a ride in the inventory | PlatformAdmin |
| GET | `/rides/{id}` | Read a ride, including its inventory status | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, SafetyOfficer |
| POST | `/workers` | Register a worker (permanent, seasonal or H-2B visa program) | PlatformAdmin |
| GET | `/workers/{id}` | Read a worker, including scheduled hours, worked days and visa compliance | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, CrewChief |
| POST | `/routes` | Create a season route in DRAFT | RouteManager, PlatformAdmin |
| GET | `/routes/{id}` | Read a route with its computed stop, haul, travel and guarantee aggregates | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| POST | `/route-stops` | Add a stop to a route; `previous_stop_id` links it into the haul chain | RouteManager |
| GET | `/route-stops/{id}` | Read a stop with its computed capacity, labor, closure and posture fields | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, ComplianceClerk |
| GET | `/route-stops` | List stops, filterable by route, venue, chain predecessor and status | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, ComplianceClerk |
| POST | `/routes/{id}/sequence` | Validate the haul chain and compute travel times; DRAFT to SEQUENCED | RouteManager |
| POST | `/routes/{id}/commit` | Lock the route for execution; SEQUENCED to COMMITTED | RouteManager, GeneralManager |
| POST | `/route-stops/{id}/begin-setup` | Move the lot into setup once load-in opens and the transport permit is approved; CONFIRMED to SETUP | RouteManager, LotBoss |
| POST | `/route-stops/{id}/open-gates` | Open the midway to the public; SETUP to OPEN, committed allocations start operating | RouteManager, LotBoss |
| POST | `/route-stops/{id}/teardown` | Strike the lot after the final operating hour; OPEN to TEARDOWN | RouteManager, LotBoss |
| POST | `/route-stops/{id}/cancel` | Go dark on a lot; cascades to the contract, allocations, crew and permits | RouteManager, GeneralManager |
| GET | `/route-stops/{id}/readiness` | Computed readiness read: the stop's posture, the blocking error id it would raise, and the ride-minimum comparison | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, ComplianceClerk |
| POST | `/contracts` | Draft a fair or community event contract for a stop | ContractNegotiator |
| GET | `/contracts/{id}` | Read a contract with its negotiation round and terms | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| GET | `/contracts` | List contracts, filterable by stop and status | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| POST | `/contracts/{id}/send` | Send the deal to the counterparty; DRAFT or COUNTERED to SENT, stamping the sender | ContractNegotiator |
| POST | `/contracts/{id}/counter` | Record the counterparty's counter; SENT to COUNTERED with new terms, admitted only while the round budget is unspent | ContractNegotiator |
| POST | `/contracts/{id}/execute` | Countersign the deal; SENT to EXECUTED, confirms the stop and cascades to allocations and inspections | GeneralManager |
| POST | `/ride-allocations` | Reserve a ride onto a lot; charges footprint and amperage against the lot budget under optimistic concurrency on the stop | LotBoss |
| GET | `/ride-allocations/{id}` | Read an allocation | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, SafetyOfficer |
| GET | `/ride-allocations` | List allocations, filterable by ride, stop and status | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, SafetyOfficer |
| POST | `/ride-allocations/{id}/commit` | Commit a reserved allocation on a confirmed lot; RESERVED to COMMITTED | LotBoss |
| POST | `/ride-allocations/{id}/release` | Release an allocation and return its footprint, amperage and ride to the pool; also the mid-run pull-off path for an operating ride | LotBoss, RouteManager |
| POST | `/permit-applications` | Draft a jurisdiction permit for a stop; the fee is computed from the jurisdiction and declared axles | ComplianceClerk |
| GET | `/route-stops/{id}/permit-applications` | List the permits filed for a stop | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ComplianceClerk, JurisdictionOfficer |
| POST | `/permit-applications/{id}/submit` | File the permit with the jurisdiction; DRAFT to SUBMITTED, subject to the lead-time rule | ComplianceClerk |
| POST | `/permit-applications/{id}/decision` | Record the jurisdiction's decision; SUBMITTED to APPROVED or DENIED | JurisdictionOfficer |
| POST | `/inspection-orders` | Schedule a ride inspection against an allocation; consumes one jurisdiction slot on the scheduled UTC day | SafetyOfficer |
| GET | `/ride-allocations/{id}/inspections` | List the inspections ordered against an allocation | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, SafetyOfficer, JurisdictionOfficer |
| POST | `/inspection-orders/{id}/result` | Record the inspecting authority's result; SCHEDULED to PASSED or FAILED with divergent cascades | JurisdictionOfficer |
| POST | `/crew-assignments` | Assign a worker to a shift on a lot; computes labor cost and enforces certification, visa, overlap, consecutive-day and housing rules | LotBoss |
| GET | `/route-stops/{id}/crew-assignments` | List the crew booked on a lot | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss |
| GET | `/workers/{id}/crew-assignments` | List a worker's assignments; a CrewChief may read only their own | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss, CrewChief |
| POST | `/crew-assignments/{id}/cancel` | Cancel a booked shift and reverse its labor ledgers; SCHEDULED to RELEASED | LotBoss |
| POST | `/route-stops/{id}/ticket-sales` | Record a wristband, single-ride, presale or comp batch for a lot | TicketingAuditor |
| GET | `/route-stops/{id}/ticket-sales` | List the sales batches booked to a lot | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor |
| POST | `/settlements` | Build a provisional settlement for a contract under optimistic concurrency on the deal; supersedes any prior provisional or disputed row | TicketingAuditor |
| GET | `/settlements/{id}` | Read a settlement with every computed amount | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| GET | `/contracts/{id}/settlements` | List the settlement rows of a contract, newest last | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| POST | `/settlements/{id}/dispute` | Counterparty disputes the provisional numbers; PROVISIONAL to DISPUTED | ContractNegotiator |
| POST | `/settlements/{id}/reconcile` | Re-run the provisional calculation over the current sales rows; DISPUTED to PROVISIONAL | TicketingAuditor |
| POST | `/settlements/{id}/finalize` | Finalize the lot's money; PROVISIONAL to FINAL with the final variant, then closes the stop | GeneralManager |
| POST | `/route-stops/{id}/weather-closures` | Log a weather closure window against an operating lot | RouteManager, LotBoss |
| GET | `/route-stops/{id}/weather-closures` | List the closures logged against a lot | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss |
| GET | `/weather-closures/{id}` | Read a closure with its raw and abated hours | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, LotBoss |
| POST | `/weather-closures/{id}/adjudicate` | Adjudicate a closure; clips and merges it into the lot's abated hours | GeneralManager |
| POST | `/make-goods` | Propose a sponsor make-good against an adjudicated closure | GeneralManager |
| GET | `/contracts/{id}/make-goods` | List the make-goods proposed under a contract | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| GET | `/weather-closures/{id}/make-goods` | List the make-goods attached to a closure | PlatformAdmin, RouteManager, GeneralManager, TicketingAuditor, ContractNegotiator |
| POST | `/make-goods/{id}/respond` | Record the sponsor's response; PROPOSED to ACCEPTED or DECLINED | ContractNegotiator |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to the supplied `to_iso8601` instant and return `current_utc` | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSURE_NOT_FOUND` | 404 Not Found |
| `ERR_MAKEGOOD_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_JURISDICTION_STATE` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CONTRACT` | 409 Conflict |
| `ERR_STALE_ROUTE_STOP_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_ROUTE_STATE_INVALID` | 409 Conflict |
| `ERR_STOP_STATE_INVALID` | 409 Conflict |
| `ERR_CONTRACT_STATE_INVALID` | 409 Conflict |
| `ERR_ALLOCATION_STATE_INVALID` | 409 Conflict |
| `ERR_PERMIT_STATE_INVALID` | 409 Conflict |
| `ERR_INSPECTION_STATE_INVALID` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE_INVALID` | 409 Conflict |
| `ERR_CLOSURE_STATE_INVALID` | 409 Conflict |
| `ERR_MAKEGOOD_STATE_INVALID` | 409 Conflict |
| `ERR_SETTLEMENT_STATE_INVALID` | 409 Conflict |
| `ERR_SETTLEMENT_ALREADY_FINAL` | 409 Conflict |
| `ERR_ALLOCATION_NOT_INSPECTABLE` | 409 Conflict |
| `ERR_RIDE_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_WORKER_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_WORKER_VISA_LAPSED` | 422 Unprocessable Entity |
| `ERR_CONSECUTIVE_DAYS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_RIDE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREW_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_PERMIT_LEAD_TIME_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INSPECTION_SLOTS_FULL` | 409 Conflict |
| `ERR_INSUFFICIENT_TRAVEL_WINDOW` | 422 Unprocessable Entity |
| `ERR_SHIFT_OUTSIDE_STOP_WINDOW` | 422 Unprocessable Entity |
| `ERR_SALE_OUTSIDE_OPERATING_WINDOW` | 422 Unprocessable Entity |
| `ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW` | 422 Unprocessable Entity |
| `ERR_LOAD_IN_NOT_OPEN` | 409 Conflict |
| `ERR_GATES_BEFORE_OPEN_DATE` | 409 Conflict |
| `ERR_TEARDOWN_BEFORE_CLOSE_DATE` | 409 Conflict |
| `ERR_ROUTE_HAS_NO_STOPS` | 422 Unprocessable Entity |
| `ERR_STOP_CHAIN_INVALID` | 422 Unprocessable Entity |
| `ERR_STOP_NOT_CONTRACTED` | 409 Conflict |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_NO_COMMITTED_RIDES` | 409 Conflict |
| `ERR_RIDE_MINIMUM_NOT_MET` | 409 Conflict |
| `ERR_LOT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOT_POWER_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_HOUSING_PADS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_MAKEGOOD_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_PERMIT_EXPIRED` | 409 Conflict |
| `ERR_CREW_COVERAGE_INSUFFICIENT` | 409 Conflict |
| `ERR_CLOSURE_NOT_ADJUDICATED` | 409 Conflict |
| `ERR_MAKEGOOD_PENDING` | 409 Conflict |
| `ERR_NO_PROVISIONAL_SETTLEMENT` | 409 Conflict |
| `ERR_MAKEGOOD_STOP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFUND_NOT_ELIGIBLE` | 422 Unprocessable Entity |
