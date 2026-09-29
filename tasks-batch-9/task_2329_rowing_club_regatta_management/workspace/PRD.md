# Rowing Club Regatta Management API — Product Requirements Document

## 1. Introduction

A community rowing club runs on three things that rarely talk to each other: a membership ledger, a boathouse full of expensive carbon hulls, and a race calendar. Today the club reconciles all three by hand. A coach declares an eight for Saturday's regatta without knowing that one of the seat-holders went into dues arrears on Thursday; the equipment manager schedules a repair bay window that a colleague already reserved; a safety officer signs a crew onto the water in twelve-degree river temperatures without a second launch on the schedule. Every one of those mistakes is recoverable, but only if someone notices, and the club has no system that notices.

This document specifies the Rowing Club & Regatta Management API — a single service, mounted under `/boathouse`, that owns membership standing and dues, the equipment fleet and its damage-and-repair pipeline, water-safety clearance for every outing, regatta entry and lineup declaration, race-day lane assignment and heat progression, jury handling of protests, and trailer logistics for away regattas. The service is deliberately opinionated: it refuses operations rather than warning about them, and it propagates consequences automatically. When an invoice tips into delinquency, the member's boathouse access closes, their declared racing seats are marked blocked, the affected entries fall back out of submission, and the race lanes those entries were holding are voided — all inside the one operator call that flagged the invoice.

Two engineering properties shape the whole specification. First, **time is explicit**: the service runs on a logical clock that tests drive directly, and every deadline, certification expiry, damage-decay period and protest window is evaluated against that clock rather than against wall time. Second, **arithmetic is pinned**: dues, entry fees, refunds, coxswain deadweight and hull condition indices each specify not only their inputs but the exact order in which rounding is applied, because the club's auditors reconcile cents and the fleet committee reconciles index points.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity they are acting in. If either header is absent, or if `X-User-Role` is not one of the seven declared roles, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If the headers are well formed but the declared role is not authorised for the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The seven roles are `ClubAdmin`, `Member`, `Coach`, `SafetyOfficer`, `EquipmentManager`, `RaceOfficial`, and `JuryChair`.

- `ClubAdmin` is the club office. It enrols members, bills and voids dues, runs the delinquency checkpoint, owns the regatta calendar, and drives the logical clock. When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, but it never compares it to any entity's `id`, and no ownership check is performed against it.
- `Member`, `Coach`, `SafetyOfficer`, `EquipmentManager`, `RaceOfficial` and `JuryChair` are all entity-backed roles. When `X-User-Role` is any of these six, `X-User-ID` is the `id` of the acting `Member` record, and it must resolve to an existing `Member`; if it does not, the request is rejected with `ERR_UNAUTHORIZED`. Ownership and conflict-of-interest checks on any resource that references a `Member` compare that resource's member-valued field to `X-User-ID` directly — for example, a damage report's `reported_by_member_id`, a session's `coach_member_id`, a seat's `member_id`, or a protest's `filed_by_member_id`.

Role responsibilities, in brief: a `Member` pays their own dues, files damage reports, lodges protests and withdraws protests they filed. A `Coach` books water sessions, opens entries, declares lineups, submits entries and scratches them. A `SafetyOfficer` posts river-condition readings and owns the clearance, launch and return gate. An `EquipmentManager` owns the fleet, the damage-report pipeline and trailer racking. A `RaceOfficial` records coxswain weigh-ins, confirms entries, schedules and seeds heats, posts results and officializes them. A `JuryChair` opens review rounds and rules on protests. Section 4 fixes the exact role list authorised for each operation.

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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` is the number of items to skip and defaults to 0. Both are echoed in the `meta` object of the envelope alongside `total_count` (the number of items matching the filter before pagination is applied) and `has_more` (whether any matching item remains beyond the current page).

Unless a listing explicitly states another order, every list endpoint returns its resources sorted by `created_at` ascending.

Beyond `limit` and `offset`, list endpoints accept optional equality filters drawn from the fields of the resource they return, which double as the reverse-reachability path for foreign keys. The roster accepts `tier` and `membership_status`. A member's invoice list and every other lifecycle-bearing listing accept `status`. The fleet roster accepts `status` and `boat_class`. Damage reports may be filtered by `shell_id`, `reported_by_member_id`, `status` and `severity`. The reading log accepts `posture`. Water sessions may be filtered by `shell_id`, `coach_member_id`, `coxswain_member_id`, `primary_launch_driver_member_id`, `secondary_launch_driver_member_id`, `athlete_member_ids`, `reading_id` and `status`. Regattas accept `status` and `venue_kind`. Entries accept `regatta_id`, `shell_id`, `trailer_load_id`, `event_code` and `status`. Lineup seats accept `regatta_entry_id`, `member_id`, `seat_role`, `weigh_in_status` and `eligibility_status`. Heats accept `regatta_id`, `advances_to_heat_id`, `event_code`, `round_kind` and `status`. Race lanes accept `heat_id`, `regatta_entry_id`, `lane_status` and `advanced`. Protests accept `heat_id`, `filed_by_member_id`, `against_race_lane_id` and `status`. Trailer loads accept `regatta_id`, `driver_member_id` and `status`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`: a UUID string with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.

All resources except river-condition readings additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource, including mutations the server performs on its own initiative when a cascade reaches the resource. Recomputation of a derived field counts as a mutation: when a payment changes a member's `dues_balance_cents`, or when a damage report changes a hull's `condition_index_conservative`, that member row and that hull row each have `updated_at` refreshed and `version` incremented.

`WaterConditionReading` is the one exception. A reading is an immutable observation of the river at an instant, so it carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and no operation ever amends one.

### 2.5. The Logical Clock, Windows and Temporal Comparisons

The service does not read wall-clock time. It keeps a logical clock that a `ClubAdmin` moves by supplying a `to_iso8601` instant to the clock-setting capability. Before that capability is ever called, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to real time. Every deadline test, certification-expiry test, damage-decay computation, window-membership test and stamped instant in this specification is evaluated against the logical clock as it reads at the moment the request is processed.

Windows in this domain are not uniform, and the differences are load-bearing:

- A water session's window `[planned_start_at, planned_end_at)` is **half-open**: the start instant belongs to the window, the end instant does not. Two sessions that merely touch endpoints do not overlap.
- A repair window `[repair_window_start_at, repair_window_end_at]` is **closed** at both ends. Two repair windows that share exactly one endpoint instant *do* conflict.
- A regatta's weigh-in window `[weigh_in_opens_at, weigh_in_closes_at)` is half-open: a weigh-in recorded exactly at the opening instant is inside the window, one recorded exactly at the closing instant is outside it.
- A heat's protest window ends at `protest_window_closes_at`: filing is permitted strictly before that instant, and officialization is permitted at or after it.

All datetimes in request payloads must parse as ISO 8601 UTC; anything that does not is a payload-shape failure reported as `ERR_INVALID_REQUEST`.

### 2.6. Rounding Discipline: Cents, Kilograms and Index Points

Money is carried in whole cents as integers, and every monetary rounding in the system is **round half up**. What differs between calculations is *where* the rounding is applied, and the club has pinned each case deliberately:

- **Dues assessment rounds per component, then sums.** Each of the three prorated components is rounded to whole cents on its own, and only then are the rounded components added. The rejected alternative — summing three unrounded components and rounding once at the end — differs by a cent whenever the fractional parts carry. For a `RECREATIONAL` member with four billable months and a locker, the pinned order yields 27584 cents; sum-then-round would yield 27583.
- **Scratch refunds also round per component, then sum**, matching dues assessment.
- **The regatta entry fee rounds exactly once**, at the point where the late-fee percentage is multiplied by the pre-late-fee subtotal. No other step in that fee involves a fraction.
- **The hull condition index rounds the other way round**: each report's contribution is carried at full precision, the contributions are summed unrounded, and the *sum* is rounded once, half up, to a whole index point before being deducted.
- **Protest deposits require no rounding at all**; they are flat whole-cent amounts.

Weights are carried at one decimal place. A coxswain's recorded weight and the derived deadweight are each rounded half up to one decimal place. Temperatures and wind speeds on a river-condition reading are likewise carried at one decimal place and compared exactly, with no tolerance band. Seed times and finish times are carried and compared at one decimal place. Lane numbers, rack units, launch counts, review rounds and index points are integers.

### 2.7. Optimistic Concurrency on Entries and Trailer Loads

Two write operations in this system legitimately overwrite work that a previous writer performed, so both are guarded by optimistic concurrency control on the parent resource's `version`.

The first is **lineup declaration**. Declaring a lineup for a regatta entry supersedes any previously declared seats wholesale, so a client holding a stale view of the entry would otherwise silently replace a declaration it never saw. Every lineup declaration must therefore carry `expected_regatta_entry_version` as a required, non-optional field of the request body, holding the `version` of the `RegattaEntry` the client last observed. If that value does not equal the entry's current `version`, the declaration is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412) and nothing is written. A successful declaration increments the entry's `version` by one, which is what invalidates every other client's stale snapshot.

The second is **trailer rack allocation**. Claiming rack units on an open trailer load is repeatable for different entries, so a client whose capacity view predates another writer's assignment would otherwise commit an allocation computed against free units that no longer exist. Both the rack-assignment and the rack-release operations must therefore carry `expected_trailer_load_version`, holding the `version` of the `TrailerLoad` the client last observed. A value that does not equal the load's current `version` is rejected with `ERR_STALE_TRAILER_VERSION` (HTTP 412). Each successful assignment or release increments the load's `version` by one.

No other endpoint accepts a version field, and no other endpoint performs a version check. Endpoints that are not listed here process their mutation without any concurrency guard.

### 2.8. Reference Resolution and Nested Path Validation

Identifiers in a request path are resolved left to right, and the first identifier that does not resolve ends the request with that entity's own 404 error rather than a generic one. The entity-specific codes are `ERR_MEMBER_NOT_FOUND`, `ERR_DUES_INVOICE_NOT_FOUND`, `ERR_SHELL_NOT_FOUND`, `ERR_DAMAGE_REPORT_NOT_FOUND`, `ERR_READING_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_REGATTA_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and `ERR_TRAILER_NOT_FOUND`.

Once every path identifier resolves, the same treatment is applied to foreign keys supplied in the request body: each is resolved to an existing row, and a miss returns that entity's own 404 code. A protest filing that names a `heat_id` which does not exist fails with `ERR_HEAT_NOT_FOUND`; one that names a valid heat but a non-existent `against_race_lane_id` fails with `ERR_LANE_NOT_FOUND`; one whose `filed_by_member_id` does not resolve fails with `ERR_MEMBER_NOT_FOUND`.

### 2.9. The Rejection Ladder: Validation Precedence

When several checks would fail for the same request, exactly one error is returned, and which one is fully determined: the checks form a single global ladder and the first failing rung wins. Implementations must evaluate in this order.

1. Header presence and role recognition — `ERR_MISSING_AUTH_HEADERS`. Applies to every endpoint.
2. Role authorisation for the called operation, and resolution of an entity-backed role's `X-User-ID` to a `Member` — `ERR_UNAUTHORIZED`. Applies to every endpoint.
3. Path identifier existence, left to right, with the entity-specific 404 code from §2.8. Applies to every endpoint that has a path parameter.
4. Body foreign-key existence, with the entity-specific 404 code. Applies to every creating or acting endpoint that carries foreign keys.
5. Payload shape: required fields present, enum values inside their declared sets, integers inside their declared ranges, datetimes parsing as ISO 8601 UTC — `ERR_INVALID_REQUEST` (HTTP 422). Applies to every write endpoint.
6. `ERR_STALE_ENTRY_VERSION` on lineup declaration.
7. `ERR_STALE_TRAILER_VERSION` on rack assignment and on rack release.
8. Terminal-state guard — `ERR_ALREADY_TERMINAL`. Applies to every state-changing write **except** dues payment and dues true-up, which are carved out so that the more specific money-domain rule at rung 55 reports `ERR_INVOICE_NOT_PAYABLE` instead. Voiding an invoice is *not* carved out and remains under this rung.
9. `ERR_SHELL_NOT_AVAILABLE` on safety clearance.
10. `ERR_SESSION_NOT_CLEARED` on launching a crew.
11. `ERR_SESSION_NOT_LAUNCHED` on logging a crew back in.
12. `ERR_REPORT_NOT_TRIAGED` on repair scheduling.
13. `ERR_REPORT_NOT_SCHEDULED` on repair verification.
14. `ERR_REGATTA_ENTRIES_CLOSED` on opening a draft entry and on submitting an entry.
15. `ERR_ENTRY_NOT_DECLARED` on submitting an entry.
16. `ERR_ENTRY_NOT_SUBMITTED` on host confirmation of an entry.
17. `ERR_HEAT_NOT_ASSIGNED` on posting heat results.
18. `ERR_HEAT_NOT_PROVISIONAL` on officializing a heat, on filing a protest, and on a jury ruling.
19. `ERR_PROTEST_NOT_UNDER_REVIEW` on a jury ruling.
20. `ERR_TRAILER_SEALED` on rack assignment and on rack release.
21. Membership standing of every member the request references — `ERR_MEMBER_NOT_ACTIVE`. Applies to booking a water session, declaring a lineup, filing a protest, and driving a trailer load through its transitions.
22. Declared-transition legality and the transition's own preconditions — `ERR_INVALID_STATUS_TRANSITION`. Applies to the member status-transition, regatta status-transition and trailer-load transition endpoints, and is the catch-all for the temporal and relational preconditions on those three machines that carry no dedicated code of their own: closing entries before `entry_deadline_at`, moving to racing before `race_date_at`, departing before `depart_at`, returning before `return_at`, sealing an empty load, or withdrawing a member who still holds an active lineup seat.
23. `ERR_SELF_TRIAGE_FORBIDDEN` on damage-report triage and on repair verification.
24. `ERR_SELF_CLEARANCE_FORBIDDEN` on safety clearance.
25. `ERR_SELF_WEIGH_IN_FORBIDDEN` on recording a weigh-in.
26. `ERR_JURY_CONFLICT_OF_INTEREST` on opening a jury review round.
27. `ERR_WATER_CLOSED` on safety clearance.
28. `ERR_SWIM_TEST_MISSING` on safety clearance and on lineup declaration.
29. `ERR_COXSWAIN_CERT_EXPIRED` on safety clearance and on lineup declaration.
30. `ERR_COACH_CERT_EXPIRED` on safety clearance.
31. `ERR_LAUNCH_CERT_EXPIRED` on safety clearance.
32. `ERR_LAUNCH_COVERAGE_INSUFFICIENT` on safety clearance.
33. `ERR_SHELL_CONDITION_TOO_LOW` on submitting an entry.
34. `ERR_TIER_NOT_PERMITTED_FOR_HULL` on lineup declaration and on booking a water session.
35. `ERR_SHELL_WINDOW_CONFLICT` on booking a water session.
36. `ERR_LAUNCH_DRIVER_OVERBOOKED` on safety clearance.
37. `ERR_REPAIR_BAY_CONFLICT` on repair scheduling.
38. `ERR_WEIGH_IN_WINDOW_CLOSED` on recording a weigh-in.
39. `ERR_PROTEST_WINDOW_CLOSED` on filing a protest.
40. `ERR_PROTEST_WINDOW_OPEN` on officializing a heat.
41. `ERR_SEAT_COUNT_MISMATCH` (HTTP 422) on lineup declaration.
42. `ERR_DUPLICATE_SEAT_MEMBER` on lineup declaration.
43. `ERR_BOAT_CLASS_MISMATCH` on opening a draft entry.
44. `ERR_REGATTA_NOT_RACING` on lane assignment.
45. `ERR_NO_ELIGIBLE_ENTRIES` on lane assignment.
46. `ERR_LANE_CAPACITY_EXCEEDED` on lane assignment.
47. `ERR_TRAILER_TIER_UNAVAILABLE` on rack assignment.
48. `ERR_MAX_JURY_ROUNDS_EXCEEDED` on opening a jury review round and on a jury ruling.
49. `ERR_WEIGH_IN_NOT_PASSED` on host confirmation of an entry.
50. `ERR_ENTRY_NOT_RACKED` on host confirmation of an entry.
51. `ERR_LANE_NOT_IN_HEAT` on filing a protest.
52. `ERR_HEAT_NOT_IN_REGATTA` on scheduling a heat.
53. `ERR_TRAILER_REGATTA_MISMATCH` on rack assignment.
54. `ERR_SEAT_MEMBER_DELINQUENT` (HTTP 402) on submitting an entry.
55. `ERR_INVOICE_NOT_PAYABLE` on dues payment and on dues true-up.
56. `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422) on dues payment.
57. `ERR_INVOICE_HAS_PAYMENTS` on voiding an invoice.
58. `ERR_TRUEUP_ALREADY_APPLIED` on dues true-up.

The ladder matters most where two rungs could both fire on the same call. A safety clearance for a suspended crew against a closed river reports `ERR_MEMBER_NOT_ACTIVE` at rung 21, not `ERR_WATER_CLOSED` at rung 27. A clearance signed by the session's own coach against a closed river reports `ERR_SELF_CLEARANCE_FORBIDDEN` at rung 24, because segregation of duties is decided before river conditions. An entry submission for a delinquent crew in a low-condition hull reports `ERR_SHELL_CONDITION_TOO_LOW` at rung 33 before the fiscal check at rung 54.

### 2.10. Cascade Discipline and Server-Initiated Transitions

The service holds its invariants by transitioning resources the client did not name. A single operator call can walk several hops: the delinquency checkpoint flags invoices, the flagged invoices put their members on hold, the held members' declared seats become blocked, the entries holding those seats fall back out of submission, and the race lanes those entries occupied are voided, which in turn demotes their heats back to being merely scheduled. Condemning a structurally damaged hull walks a similar chain: the report is condemned, the hull is retired, every non-terminal entry racing that hull is scratched, those entries' pending lanes are voided, and the affected heats are demoted.

Three rules govern all such cascades. First, they are **immediate**: by the time the triggering request returns, every downstream resource already reflects its new state, and a read of any of them shows the settled result. Second, every resource a cascade touches is mutated in its own right — `updated_at` is refreshed and `version` is incremented on each of them, exactly as if a client had written to each individually. Third, cascades are **not conditional on client intent**: no request flag suppresses them, and the client cannot ask for a partial application.

Derived aggregates are recomputed as part of the same request, never lazily: a member's `dues_balance_cents`, `logged_session_count` and `boathouse_access_level`; a hull's `condition_index_conservative` and `condition_index_optimistic`; a heat's `occupied_lane_count` and `free_lane_count`; a trailer's `rack_units_used` and `rack_units_free`; and a regatta's `net_fee_cents` and `deposit_held_cents`.

### 2.11. Segregation of Duties on the Dock and in the Jury Room

The club's insurers require that nobody sign off on their own work, and four checks encode that requirement. The member who filed a damage report may neither triage it nor verify its repair; either attempt is rejected with `ERR_SELF_TRIAGE_FORBIDDEN`. The coach named on a water session may not sign that session's own safety clearance — `ERR_SELF_CLEARANCE_FORBIDDEN`. A coxswain may not record their own weigh-in, so a weigh-in whose acting `X-User-ID` equals the seat's `member_id` is rejected with `ERR_SELF_WEIGH_IN_FORBIDDEN`. And a jury chair may not open review on a protest they themselves filed, nor on a protest concerning a heat in which they were racing — `ERR_JURY_CONFLICT_OF_INTEREST`.

All four are decided by comparing `X-User-ID` against the stored member reference, which is why §2.1 insists that entity-backed roles carry the acting `Member` `id` in that header. When the acting identity passes the check, it is recorded for audit: triage stamps `triaged_by_user_id`, repair verification stamps `verified_by_user_id`, a weigh-in stamps `weighed_by_user_id`, and opening a review round stamps `jury_user_id`.

## 3. Business Logic & Workflows

### 3.1. Enrolling Members and Keeping Their Standing

Enrolment is a `ClubAdmin` act. The payload carries the member's `full_name`, their `tier` — one of `COMPETITIVE`, `RECREATIONAL` or `LEARN_TO_ROW`, which drives dues, boathouse access and hull eligibility — and their self-declared `body_weight_kg` at one decimal place, which the club treats as the expectation a weigh-in is measured against. Optionally the payload declares `club_roles`, an array drawn from `ATHLETE`, `COXSWAIN`, `COACH`, `LAUNCH_DRIVER`, `JURY` and `EQUIPMENT_MANAGER` and defaulting to the empty array; the four credential instants `swim_test_passed_on`, `coxswain_cert_expires_at`, `coach_cert_expires_at` and `safety_launch_cert_expires_at`, each defaulting to null meaning "never passed" or "uncertified"; and `launch_supervision_limit`, an integer between 1 and 4 inclusive defaulting to 2, capping how many overlapping outings the member may cover from a safety launch. A newly enrolled member begins with `membership_status` `ACTIVE`, `dues_balance_cents` 0, `logged_session_count` 0 and `boathouse_access_level` `FULL`.

Credentials change over the season, and a `ClubAdmin` may amend `swim_test_passed_on`, `coxswain_cert_expires_at`, `coach_cert_expires_at`, `safety_launch_cert_expires_at` and `launch_supervision_limit` on an existing member. Amending them recomputes `eligibility_status` on every `LineupSeat` this member occupies whose parent entry has not yet reached a terminal state — a lapsed coxswain certification therefore surfaces on the affected seats without waiting for the next regatta operation.

Three member figures are derived and never supplied by a client. `dues_balance_cents` is the sum, over the member's invoices whose `status` is `ISSUED`, `PARTIALLY_PAID` or `DELINQUENT`, of that invoice's `assessed_cents` less its `paid_cents`; invoices that are `PAID` or `VOIDED` leave the input set entirely. `logged_session_count` is the number of water sessions in status `RETURNED` whose `athlete_member_ids` array contains this member's `id`. `boathouse_access_level` follows mechanically from the other two: `FULL` when `membership_status` is `ACTIVE` and `dues_balance_cents` is exactly 0, `SUPERVISED` when `membership_status` is `ACTIVE` and `dues_balance_cents` is greater than 0, and `NONE` whenever `membership_status` is `DUES_HOLD`, `SUSPENDED` or `WITHDRAWN`.

`membership_status` begins at `ACTIVE` and moves only along declared paths; `WITHDRAWN` is terminal. `ACTIVE → DUES_HOLD` is driven by the delinquency checkpoint described in §3.2 and never by a direct request. `DUES_HOLD → ACTIVE` is driven by a payment that clears the member's arrears, also described in §3.2. The remaining paths are driven by a `ClubAdmin` supplying a `to_status` for the member:

- `ACTIVE → SUSPENDED` and `DUES_HOLD → SUSPENDED` both require that no session in status `LAUNCHED` reference this member in any member-valued field — not as `coach_member_id`, not as `coxswain_member_id`, not as `primary_launch_driver_member_id` or `secondary_launch_driver_member_id`, and not inside `athlete_member_ids`. The club will not suspend somebody who is currently on the water. Suspension then cancels every session in status `PLANNED` or `CLEARED` that references the member in any of those fields, and recomputes `boathouse_access_level` to `NONE`.
- `SUSPENDED → ACTIVE` requires `dues_balance_cents` to be exactly 0, and recomputes `boathouse_access_level` to `FULL`.
- `ACTIVE → WITHDRAWN` and `SUSPENDED → WITHDRAWN` each require that the member hold no `LineupSeat` whose parent entry is in status `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED`; a rower cannot resign out from under a live racing commitment. Withdrawal recomputes `boathouse_access_level` to `NONE`.

Any other `to_status` request — a direct move from `DUES_HOLD` to `WITHDRAWN`, say, or a move whose declared precondition does not hold — is rejected with `ERR_INVALID_STATUS_TRANSITION`.

### 3.2. Billing the Season: Assessment, Payment, True-Up and Delinquency

A dues invoice is issued by a `ClubAdmin` against a `member_id` for a `season_year`, prorated over `billable_months` (an integer from 1 to 12 inclusive) of the twelve-month season, with `locker_requested` declaring whether a boathouse locker is billed (defaulting to false), and `due_at` fixing the instant after which non-payment becomes delinquency. A fresh invoice is `ISSUED`, with `variant_basis` `PROVISIONAL`, `paid_cents` 0 and `trueup_cents` null.

**The provisional seasonal assessment.** The month ratio is `billable_months` divided by 12, held as an exact rational with no intermediate rounding. Three components are then computed, each rounded half up to whole cents *individually*. The season component is the tier season fee multiplied by the month ratio, where the tier season fee is 95000 cents for a `COMPETITIVE` member, 61500 cents for a `RECREATIONAL` member and 35500 cents for a `LEARN_TO_ROW` member. The access component is the tier access surcharge multiplied by the month ratio, where that surcharge is 23500 cents for `COMPETITIVE`, 12500 cents for `RECREATIONAL` and zero for `LEARN_TO_ROW` — learn-to-row rowers pay no boathouse access surcharge at all. The locker component is 8750 cents multiplied by the month ratio when `locker_requested` is true, and zero otherwise. `assessed_cents` is the sum of those three already-rounded components; the per-component rounding order is pinned as described in §2.6.

**Payments.** A `Member` or a `ClubAdmin` applies a payment by supplying `amount_cents`. The payment must not exceed the invoice's remaining balance — that is, `amount_cents` must be no greater than `assessed_cents` less `paid_cents` — or the request is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. The invoice must also still be payable: its `status` must be `ISSUED`, `PARTIALLY_PAID` or `DELINQUENT`, and a payment against a `PAID` or `VOIDED` invoice reports `ERR_INVOICE_NOT_PAYABLE` rather than the generic terminal-state error, per the carve-out in §2.9. Every accepted payment adds `amount_cents` to `paid_cents` and recomputes the member's `dues_balance_cents`.

Where the invoice lands depends on the running total. From `ISSUED` or from `DELINQUENT`, a payment that leaves `paid_cents` strictly above zero but still strictly below `assessed_cents` moves the invoice to `PARTIALLY_PAID` — that is, `ISSUED → PARTIALLY_PAID` or `DELINQUENT → PARTIALLY_PAID`. From `ISSUED`, `PARTIALLY_PAID` or `DELINQUENT`, a payment that brings `paid_cents` to at least `assessed_cents` moves the invoice to `PAID` — `ISSUED → PAID`, `PARTIALLY_PAID → PAID` or `DELINQUENT → PAID`. Payments from `ISSUED` and from `PARTIALLY_PAID` also recompute the member's `boathouse_access_level`. A payment that settles a `DELINQUENT` invoice and thereby brings the member's `dues_balance_cents` to exactly 0 drives that member `DUES_HOLD → ACTIVE`, recomputing `boathouse_access_level` to `FULL` and recomputing every `LineupSeat` of theirs whose `eligibility_status` was `BLOCKED_DUES` back to `ELIGIBLE`. Note that `DELINQUENT → PARTIALLY_PAID → DELINQUENT` is a permitted cycle across successive delinquency checkpoints: a part payment relieves nothing on its own.

**The end-of-season true-up.** A `ClubAdmin` may rebill a `PARTIALLY_PAID` invoice on actual usage, optionally attaching a `note`. The true-up discards the prorated components entirely and rebills as follows: the per-session component is 4500 cents multiplied by the member's `logged_session_count`; the floor component is 40 percent (a factor of 0.40) of that member's tier season fee, rounded half up to whole cents; the usage basis is whichever of those two is larger; and the new assessment is the usage basis plus a flat administration fee of 5000 cents. That result replaces `assessed_cents`, `variant_basis` becomes `TRUEUP`, and `trueup_cents` records the signed delta — the new assessment minus the assessment that stood before the true-up — so a negative `trueup_cents` is a credit. The member's `dues_balance_cents` is recomputed. Because the two variants read the same member differently, identical member data yields different assessments: a `RECREATIONAL` member with four billable months, a locker and seven returned sessions is assessed 27584 cents provisionally and 36500 cents on true-up, giving `trueup_cents` of 8916. A true-up whose result is at or below `paid_cents` settles the invoice outright: `PARTIALLY_PAID → PAID` with no payment required, which is how a credit-side true-up closes the books. A true-up against an invoice whose `variant_basis` is already `TRUEUP` is rejected with `ERR_TRUEUP_ALREADY_APPLIED`, and a true-up against a `PAID` or `VOIDED` invoice reports `ERR_INVOICE_NOT_PAYABLE`.

**Voiding.** A `ClubAdmin` may void an `ISSUED` invoice with a stated `reason`, but only while `paid_cents` is exactly 0; otherwise the request fails with `ERR_INVOICE_HAS_PAYMENTS`. `ISSUED → VOIDED` removes the invoice from the balance input set, so the member's `dues_balance_cents` and `boathouse_access_level` are both recomputed. `PAID` and `VOIDED` are the invoice's terminal states.

**The delinquency checkpoint.** A `ClubAdmin` runs the delinquency checkpoint as a single operator call, optionally narrowed to one `season_year`. Every invoice in status `ISSUED` or `PARTIALLY_PAID` whose `due_at` is strictly before the logical clock and whose `paid_cents` is still below `assessed_cents` moves to `DELINQUENT` — `ISSUED → DELINQUENT` or `PARTIALLY_PAID → DELINQUENT` — and the billed member's `dues_balance_cents` is recomputed. That is hop one of a four-hop chain. Hop two: any member for whom at least one invoice transitioned into `DELINQUENT` *inside this same run* moves `ACTIVE → DUES_HOLD`, with `boathouse_access_level` recomputed to `NONE`. Hop three: every `LineupSeat` held by such a member whose parent entry is in status `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` has its `eligibility_status` set to `BLOCKED_DUES`. Hop four: each seat that just became `BLOCKED_DUES` drives its parent entry `SUBMITTED → LINEUP_DECLARED`, and that demotion in turn voids the entry's pending race lanes and demotes their heats, exactly as described in §3.6 and §3.8. The whole chain settles inside the one call.

### 3.3. The Fleet: Hulls, Damage Reports, Repair Bays and Condemnation

An `EquipmentManager` or a `ClubAdmin` adds a hull with a `hull_name` painted on it, a `boat_class` of `1X`, `2X`, `4+` or `8+`, a `hull_weight_kg` at one decimal place, and a `home_bay` label naming the boathouse bay it is racked in. Optionally the hull declares a `tier_restriction` of `COMPETITIVE_ONLY` or `ANY`, defaulting to `ANY`, and a `last_serviced_at` instant defaulting to null for a hull never yet serviced. A new hull is `AVAILABLE`, its `slot_units` derived from `boat_class` as the trailer rack units it occupies (a single or a double occupies 1 unit, a four occupies 2, an eight occupies 3), and both condition indices — `condition_index_conservative` and `condition_index_optimistic` — initialised to 100.

A hull cycles `AVAILABLE → ASSIGNED → AVAILABLE` around every outing: clearance reserves it, and a return or a cancellation releases it, the release being permitted only when no other session in status `CLEARED` or `LAUNCHED` still references that hull. An `EquipmentManager` may retire an `AVAILABLE` hull outright with a stated `reason` (`AVAILABLE → RETIRED`), but only when no session in status `PLANNED`, `CLEARED` or `LAUNCHED` references it and no entry in status `DRAFT`, `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` races it. `RETIRED` is terminal.

**Filing damage.** A `Member`, `Coach` or `EquipmentManager` files a damage report naming the `shell_id`, the `reported_by_member_id` who observed the damage, a `severity` of `COSMETIC`, `MINOR`, `MAJOR` or `STRUCTURAL`, and a free-text `narrative`. The server stamps `reported_at` from the logical clock; that instant is the baseline from which the report's deduction decays. A new report is `REPORTED`, with `triaged_by_user_id`, `verified_by_user_id`, `assigned_repair_bay`, `repair_window_start_at` and `repair_window_end_at` all null. A report of `MAJOR` or `STRUCTURAL` severity also takes the hull out of service, moving it `AVAILABLE → DAMAGED` or `ASSIGNED → DAMAGED`; when the hull was `ASSIGNED`, every session in status `PLANNED` or `CLEARED` on that hull is cancelled as well. `COSMETIC` and `MINOR` reports leave the hull's status untouched. Either way both condition indices and the report's own `severity_points` are recomputed.

**The condition index.** For each report on a hull the server first computes the report's current deduction. The age in days is the elapsed time from `reported_at` to the logical clock, expressed in whole days by discarding any remainder of a day. The number of completed decay periods is that day count divided by 30 and rounded down to a whole number. The report's raw severity weight is 2 points for `COSMETIC`, 6 for `MINOR`, 18 for `MAJOR` and 40 for `STRUCTURAL`; from it the server subtracts 0.5 points per completed decay period, and the result is floored at zero. That decayed figure is stored as the report's `severity_points`.

Two indices are then published from two different input sets. The conservative index counts reports whose status is `REPORTED`, `TRIAGED`, `REPAIR_SCHEDULED` or `VERIFIED`, with a `VERIFIED` report contributing only a quarter of its decayed points (a residual factor of 0.25) — a repaired hull never fully recovers on the conservative reading. The optimistic index counts only reports whose status is `REPORTED`, `TRIAGED` or `REPAIR_SCHEDULED`, dropping `VERIFIED` reports from the deduction set entirely. Both exclude `CONDEMNED` and `CLOSED_NO_ACTION` reports. For each index the contributions are summed at full precision, that single sum is rounded half up to a whole index point, and the rounded sum is subtracted from a ceiling of 100, with the result floored at 0 and never exceeding 100. The two figures diverge for identical history: an 89-day-old `VERIFIED` `MAJOR` alongside a 30-day-old `REPAIR_SCHEDULED` `MINOR` gives 90 conservatively and 94 optimistically. The conservative figure is the one that gates racing; the optimistic figure is what the club publishes in its fleet roster.

**Triage, scheduling, verification.** An `EquipmentManager` triages a `REPORTED` report by supplying a `disposition`. A `disposition` of `REPAIR` moves it `REPORTED → TRIAGED` and stamps `triaged_by_user_id`. A `disposition` of `CLOSE_NO_ACTION` moves it `REPORTED → CLOSED_NO_ACTION`, also stamping `triaged_by_user_id`; because the report leaves both index input sets, both indices are recomputed, and if the hull is `DAMAGED` and no other report on it remains in status `REPORTED`, `TRIAGED` or `REPAIR_SCHEDULED`, the hull is driven `DAMAGED → AVAILABLE`.

Scheduling a repair takes an `assigned_repair_bay` label with `repair_window_start_at` and `repair_window_end_at`, moves the report `TRIAGED → REPAIR_SCHEDULED`, persists all three fields, and drives the hull `DAMAGED → IN_REPAIR`. The bay reservation is exclusive over a **closed** window: if any other report in status `REPAIR_SCHEDULED` on the same bay holds a window that intersects the requested one, the request is rejected with `ERR_REPAIR_BAY_CONFLICT`, and two windows that share exactly one endpoint instant do conflict. Repair scheduling against a report that is not `TRIAGED` fails with `ERR_REPORT_NOT_TRIAGED`.

The reschedule loop runs the other way: triaging a `REPAIR_SCHEDULED` report with a `disposition` of `REPAIR` moves it `REPAIR_SCHEDULED → TRIAGED`, permitted only while the logical clock is strictly before `repair_window_end_at`, and resets `assigned_repair_bay`, `repair_window_start_at` and `repair_window_end_at` to null, freeing the bay window; the hull follows `IN_REPAIR → DAMAGED`. So a report may travel `TRIAGED → REPAIR_SCHEDULED → TRIAGED` as often as the boatman needs, and the hull with it, `DAMAGED → IN_REPAIR → DAMAGED`.

Verification closes the happy path. An `EquipmentManager` other than the reporter verifies a `REPAIR_SCHEDULED` report, optionally with a `note`, but only once the logical clock has reached or passed `repair_window_end_at`; earlier attempts fail on that precondition, and a report in any other status fails with `ERR_REPORT_NOT_SCHEDULED`. Verification moves the report `REPAIR_SCHEDULED → VERIFIED`, stamps `verified_by_user_id`, drives the hull `IN_REPAIR → AVAILABLE`, and recomputes both indices — the report now contributes a quarter of its decayed points to the conservative index and nothing at all to the optimistic one.

**Condemnation.** A structurally damaged hull is condemned by an `EquipmentManager` with a stated `reason`, permitted only when the report's `severity` is `STRUCTURAL`. The report moves `TRIAGED → CONDEMNED` or `REPAIR_SCHEDULED → CONDEMNED`; from `REPAIR_SCHEDULED` the reserved bay window is released. The hull follows `DAMAGED → RETIRED` or `IN_REPAIR → RETIRED`. From there the cascade continues: every entry racing that hull in status `DRAFT`, `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` is scratched, every session in status `PLANNED` or `CLEARED` on that hull is cancelled, the scratched entries' pending race lanes are voided, the heats holding those lanes are demoted from `LANES_ASSIGNED` back to `SCHEDULED`, and any trailer rack units those entries held are released with the owning trailer's counters recomputed. `VERIFIED`, `CONDEMNED` and `CLOSED_NO_ACTION` are the report's terminal states.

### 3.4. Reading the River and Clearing Crews onto the Water

A `SafetyOfficer` posts a river-condition reading as an immutable observation: `observed_at`, `air_temp_c`, `water_temp_c` and `wind_speed_kt` each at one decimal place, `visibility_m` as whole metres of horizontal visibility, and the `traffic_pattern` in force, which is `STANDARD_COUNTERCLOCKWISE`, `REVERSED_CLOCKWISE` or `NARROW_CHANNEL`.

Two figures are computed from the reading and nothing else. The `cold_water_flag` is raised when the water temperature is strictly below 12.8 degrees Celsius, or when the water and air temperatures added together come to 30.0 degrees or less; the two comparisons differ deliberately — strictly below on the single water reading, at-or-below on the combined sum. The `posture` is then decided in order: it is `CLOSED` when the sustained wind is 20.0 knots or more, or the visibility is 400 metres or less. Otherwise it is `RESTRICTED` when the wind is 12.0 knots or more, or the visibility is 800 metres or less, or the `cold_water_flag` is raised, or the `traffic_pattern` is `NARROW_CHANNEL`. Failing all of those, the posture is `OPEN`.

Posting a `CLOSED` reading is itself an intervention. Every session in status `CLEARED` whose `planned_start_at` falls after the new reading's `observed_at` is reverted `CLEARED → PLANNED`, its `reading_id` reset to null and its `required_launch_count` reset to 0, and its hull released `ASSIGNED → AVAILABLE`. A crew already `LAUNCHED` is not recalled, and a cleared session already under way — one whose start has passed — keeps its clearance. This is the `PLANNED → CLEARED → PLANNED` re-clearance cycle: when the river reopens, the outing must be cleared again against a fresh reading.

**Booking an outing.** A `Coach` or a `SafetyOfficer` books a session by naming the `shell_id`, the `session_kind` — `PRACTICE`, `LEARN_TO_ROW` or `RACE_PREP` — and the water window `planned_start_at` to `planned_end_at`. The crew is optional at booking and may name a supervising `coach_member_id` (null for an unsupervised recreational outing), a steering `coxswain_member_id` (null for sculling classes), a `primary_launch_driver_member_id` and a `secondary_launch_driver_member_id` for the safety launches, and `athlete_member_ids`, an ordered roster of seated athletes from bow to stern which defaults to the empty array. Every member the booking references must have `membership_status` `ACTIVE`, or the booking fails with `ERR_MEMBER_NOT_ACTIVE`. If the hull carries `tier_restriction` `COMPETITIVE_ONLY`, every seated member must be of `tier` `COMPETITIVE`, or the booking fails with `ERR_TIER_NOT_PERMITTED_FOR_HULL`. The hull's schedule is also protected: the requested half-open window must not intersect the window of any other session on the same hull in status `PLANNED`, `CLEARED` or `LAUNCHED` once a 30-minute turnaround buffer has been appended to the earlier session's end, and a collision is rejected with `ERR_SHELL_WINDOW_CONFLICT`. A booked session is `PLANNED`, with `reading_id` and `actual_return_at` null, `required_launch_count` 0, and `assigned_launch_count` set to the count of non-null values among the two launch-driver fields — 0, 1 or 2.

**Clearance.** Only a `SafetyOfficer` clears a session, and never one they coach. Clearance names a single `reading_id`, and the reading it names is the one the decision is recorded against; on success `reading_id` is persisted on the session and `required_launch_count` is recomputed from that reading. Clearance requires the hull to be `AVAILABLE` (`ERR_SHELL_NOT_AVAILABLE`) and the named reading's `posture` to be `OPEN` or `RESTRICTED` — a `CLOSED` river yields `ERR_WATER_CLOSED`.

The crew's credentials are then checked against the logical clock. Every member in `athlete_member_ids`, plus the `coxswain_member_id` when one is named, must have a non-null `swim_test_passed_on` no more than 365 days before the logical clock; a missing or stale swim test yields `ERR_SWIM_TEST_MISSING`. A named coxswain must have a non-null `coxswain_cert_expires_at` falling strictly after the logical clock, or the clearance fails with `ERR_COXSWAIN_CERT_EXPIRED`. When `coach_member_id` is not null, that member must have a non-null `coach_cert_expires_at` strictly after the logical clock — `ERR_COACH_CERT_EXPIRED`. Every non-null launch driver must have a non-null `safety_launch_cert_expires_at` strictly after the logical clock *and* carry `LAUNCH_DRIVER` in their `club_roles`; a failure on either count is `ERR_LAUNCH_CERT_EXPIRED`.

**Launch coverage.** How many safety launches an outing needs is derived from the outing and the reading together, starting from zero and adding one launch for each of three conditions: the `session_kind` is `LEARN_TO_ROW`; the reading's `cold_water_flag` is raised; the reading's `posture` is `RESTRICTED`. The total is then capped at 2, which is the club's maximum launch commitment per outing — so a learn-to-row outing on a cold, restricted river still requires only two launches. That capped figure is `required_launch_count`; `assigned_launch_count` is the count of non-null values among `primary_launch_driver_member_id` and `secondary_launch_driver_member_id`. Clearance is refused with `ERR_LAUNCH_COVERAGE_INSUFFICIENT` when the assigned count is below the required count.

A launch driver also may not be spread too thin. For each non-null launch driver, the server counts the sessions in status `CLEARED` or `LAUNCHED` naming that driver whose half-open window strictly intersects this session's window — sessions that merely touch endpoints do not count, and no turnaround buffer applies here, unlike the hull-conflict rule. That count must be strictly less than the driver's `launch_supervision_limit`, or clearance is refused with `ERR_LAUNCH_DRIVER_OVERBOOKED`.

A successful clearance moves the session `PLANNED → CLEARED` and drives the hull `AVAILABLE → ASSIGNED`.

**On the water and back.** A `SafetyOfficer` logs a `CLEARED` crew onto the water, optionally with a `note`, permitted only while the logical clock is at or after `planned_start_at` and strictly before `planned_end_at`; a session in any other status fails with `ERR_SESSION_NOT_CLEARED`. That moves the session `CLEARED → LAUNCHED`. Logging the crew back in, again optionally with a `note`, requires status `LAUNCHED` (`ERR_SESSION_NOT_LAUNCHED`), moves the session `LAUNCHED → RETURNED`, stamps `actual_return_at` from the logical clock, releases the hull `ASSIGNED → AVAILABLE`, and recomputes `logged_session_count` for every member named in `athlete_member_ids` — which is how water time feeds back into the end-of-season true-up in §3.2. A `Coach` or `SafetyOfficer` may instead cancel a session with a stated `reason` while it is `PLANNED` or `CLEARED` — `PLANNED → CANCELLED` or `CLEARED → CANCELLED`; cancelling from `CLEARED` releases the hull `ASSIGNED → AVAILABLE`. `RETURNED` and `CANCELLED` are the session's terminal states.

### 3.5. Regattas, Draft Entries and Lineup Declaration

A `ClubAdmin` creates a regatta with its `name`, its `host_club`, and a `venue_kind` of `HOME` when it is raced on the club's own water or `AWAY` when hulls must be trailered. Four instants frame it: `race_date_at` for the first race, `entry_deadline_at` after which submissions incur the late fee, `scratch_deadline_at` after which a scratch earns no refund, and the half-open coxswain weigh-in window from `weigh_in_opens_at` to `weigh_in_closes_at`. The optional `late_entry_allowed` flag, defaulting to false, records whether the host permits reopening entries. A new regatta is `OPEN_FOR_ENTRY` with `net_fee_cents` and `deposit_held_cents` both 0.

The regatta's own lifecycle is driven by a `ClubAdmin` supplying a `to_status`. `OPEN_FOR_ENTRY → ENTRIES_CLOSED` requires the logical clock to have reached `entry_deadline_at`, and thereafter no entry may be opened or submitted. `ENTRIES_CLOSED → OPEN_FOR_ENTRY` is the late-entry reopen: it requires `late_entry_allowed` to be true and the logical clock to be strictly before `race_date_at`, and it lets late submissions in at the late fee — the `OPEN_FOR_ENTRY → ENTRIES_CLOSED → OPEN_FOR_ENTRY` cycle. `ENTRIES_CLOSED → RACING` requires the logical clock to have reached `race_date_at` and, when `venue_kind` is `AWAY`, that every trailer load for this regatta be in status `DEPARTED` or `ARRIVED`; only then may heats be seeded and raced. `RACING → COMPLETE` requires every heat of the regatta to be `RESULTS_OFFICIAL` and no protest on those heats to remain in status `FILED`, `UNDER_JURY_REVIEW` or `REMANDED`; it freezes `net_fee_cents` and `deposit_held_cents`. Cancellation is available from `OPEN_FOR_ENTRY`, from `ENTRIES_CLOSED`, and from `RACING` provided no heat has yet reached `RESULTS_OFFICIAL` — `OPEN_FOR_ENTRY → CANCELLED`, `ENTRIES_CLOSED → CANCELLED` and `RACING → CANCELLED`; in all three cases every entry in status `DRAFT`, `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` is scratched with `refund_cents` set to that entry's full `total_fee_cents` and `net_fee_cents` recomputed, and a cancellation from `RACING` additionally voids every race lane on those heats whose `lane_status` is `PENDING` or `PROVISIONAL`, decrementing each heat's `occupied_lane_count`. `COMPLETE` and `CANCELLED` are terminal. Any `to_status` outside these declared paths, or one whose precondition fails, is rejected with `ERR_INVALID_STATUS_TRANSITION`.

**Opening an entry.** A `Coach` opens a draft entry naming the `regatta_id`, the `shell_id` the crew will race, the host's `event_code` (for example `M8PLUS_OPEN`), the raced `boat_class`, and a declared `seed_time_seconds` at one decimal place which later serves as the lane-assignment sort key. The regatta must be `OPEN_FOR_ENTRY`, or the request fails with `ERR_REGATTA_ENTRIES_CLOSED`; and the declared `boat_class` must equal the `boat_class` of the named hull, or it fails with `ERR_BOAT_CLASS_MISMATCH`. A new entry is `DRAFT`, with `base_fee_cents`, `transport_levy_cents`, `late_fee_cents` and `total_fee_cents` all 0, `refund_cents` null, `submitted_at` null, and `trailer_load_id`, `rack_tier` and `rack_position` all null.

**Declaring the lineup.** The `Coach` declares the crew by supplying `expected_regatta_entry_version` — the optimistic-concurrency field from §2.7 — together with `seats`, an array in which each element names the `member_id` occupying the seat, the `seat_number` as a 1-based index from bow to stern with 0 reserved for the coxswain seat and a permitted range of 0 to 8, and the `seat_role` of `ROWER` or `COXSWAIN`. The declared seats must fill exactly the seat count implied by the entry's `boat_class`: one seat for a `1X`, two for a `2X`, five for a `4+` including the coxswain, and nine for an `8+` including the coxswain, with `seat_number` 0 carrying the single `COXSWAIN` seat in the `4+` and `8+` classes. A wrong count is `ERR_SEAT_COUNT_MISMATCH` (HTTP 422), and the same `member_id` appearing in two seats of one declaration is `ERR_DUPLICATE_SEAT_MEMBER`. Every seated member must have `membership_status` `ACTIVE`, must satisfy the swim-test rule of §3.4 (`ERR_SWIM_TEST_MISSING`), and, in the coxswain seat, must hold a `coxswain_cert_expires_at` strictly after the logical clock (`ERR_COXSWAIN_CERT_EXPIRED`); and when the hull carries `tier_restriction` `COMPETITIVE_ONLY`, every seated member must be `COMPETITIVE` (`ERR_TIER_NOT_PERMITTED_FOR_HULL`).

A first declaration moves the entry `DRAFT → LINEUP_DECLARED` and creates a `LineupSeat` row per declared seat, each carrying its `regatta_entry_id`. A further declaration on an already-declared entry is the `LINEUP_DECLARED → LINEUP_DECLARED` self-loop: the previously declared seats are superseded and replaced wholesale by the new declaration. Either way the entry's `version` is incremented by one, which is precisely what makes the next declaration from a stale client fail with `ERR_STALE_ENTRY_VERSION`.

Each seat is born with `weighed_kg`, `weighed_by_user_id` and `deadweight_kg` null, a `weigh_in_status` of `NOT_REQUIRED`, and a computed `eligibility_status`. Eligibility is `ELIGIBLE` when the seated member clears the dues, certification and safety gates; when a gate blocks, the seat records the first blocking reason in the same precedence the rejection ladder uses — the safety gate first, giving `BLOCKED_SAFETY` for a missing or stale swim test; then the certification gate, giving `BLOCKED_CERT` for a lapsed coxswain certification; then the fiscal gate, giving `BLOCKED_DUES` for a member whose `dues_balance_cents` is not zero. Eligibility is not frozen at declaration: it is recomputed whenever the member's credentials are amended, whenever the delinquency checkpoint puts the member on hold, and whenever a payment clears their arrears.

### 3.6. Weigh-Ins, Submission Fees and Scratches

**Submission.** A `Coach` submits a `LINEUP_DECLARED` entry to the host, optionally with a `note`. The regatta must still be `OPEN_FOR_ENTRY` (`ERR_REGATTA_ENTRIES_CLOSED`), the entry must be `LINEUP_DECLARED` (`ERR_ENTRY_NOT_DECLARED`), the hull's `condition_index_conservative` must be at least 60 (`ERR_SHELL_CONDITION_TOO_LOW`), and every seat on the entry must be `ELIGIBLE` — a seat sitting at `BLOCKED_DUES`, equivalently a seated member whose `dues_balance_cents` is not zero, is refused with `ERR_SEAT_MEMBER_DELINQUENT` at HTTP 402. Submission stamps `submitted_at` from the logical clock, assesses the fee, moves every `COXSWAIN` seat's `weigh_in_status` from `NOT_REQUIRED` to `PENDING`, recomputes the regatta's `net_fee_cents`, and moves the entry `LINEUP_DECLARED → SUBMITTED`.

The fee is assessed in a pinned order. Step one: `base_fee_cents` is the class entry fee — 4500 cents for a `1X`, 7500 for a `2X`, 13500 for a `4+` and 25000 for an `8+`. Step two: `transport_levy_cents` is 5000 cents per rack unit the hull occupies when the regatta's `venue_kind` is `AWAY`, using the same rack-unit table as the trailer (1 unit for a `1X` or `2X`, 2 for a `4+`, 3 for an `8+`), and is zero for a `HOME` regatta. Step three: the two are added to give the pre-late-fee subtotal. Step four: the late-fee percentage is keyed on that subtotal — 15 percent (0.15) when the subtotal is 25000 cents or more, and 10 percent (0.10) otherwise. Step five: `late_fee_cents` is that percentage of the subtotal, rounded half up to whole cents, when `submitted_at` falls strictly after the regatta's `entry_deadline_at`, and zero when the submission is on time. Step six: `total_fee_cents` is the subtotal plus the late fee. The percentage is deliberately keyed on the subtotal and never on `total_fee_cents`, which would make the definition circular. A `4+` racing away and submitted late therefore has a subtotal of 23500 cents, which is below the 25000-cent threshold, so the percentage is 10 percent, the late fee is 2350 cents and the total is 25850 cents — not the 27025 cents that the circular reading would settle on.

**Weigh-in.** A `RaceOfficial` records a coxswain's weight by supplying `weighed_kg` at one decimal place, permitted only while the logical clock lies inside the regatta's half-open weigh-in window (`ERR_WEIGH_IN_WINDOW_CLOSED`) and never by the coxswain themselves (`ERR_SELF_WEIGH_IN_FORBIDDEN`). The recorded weight and the acting `weighed_by_user_id` are stamped on the seat. For a `COXSWAIN` seat, `deadweight_kg` is the club's minimum coxswain weight of 55.0 kilograms less the recorded weight, floored at zero and rounded half up to one decimal place — the sandbag the crew must carry. A `ROWER` seat is never weighed and contributes zero deadweight.

The entry as a whole is then judged: the server sums `deadweight_kg` over the seats of the same entry whose `weigh_in_status` is already `PASSED` or `FAILED`, adds the deadweight just recorded, and compares the total against the club's ceiling of 15.0 kilograms. The comparison is strictly greater-than: a total of exactly 15.0 kilograms passes. Concretely, a coxswain weighing 40.0 kilograms carries 15.0 kilograms of deadweight and is recorded `PASSED`; one weighing 39.9 kilograms carries 15.1 and is recorded `FAILED`.

A `FAILED` weigh-in demotes the entry. The `SUBMITTED → LINEUP_DECLARED` demotion fires whenever at least one seat on the entry has `weigh_in_status` `FAILED` or an `eligibility_status` other than `ELIGIBLE` — whether that came from a failed weigh-in or from the delinquency chain of §3.2. The demotion voids every race lane held by that entry whose `lane_status` is `PENDING`, and each voided lane decrements its heat's `occupied_lane_count`, recomputes `free_lane_count`, and drives that heat `LANES_ASSIGNED → SCHEDULED` so it must be re-seeded. That is the `LINEUP_DECLARED → SUBMITTED → LINEUP_DECLARED` demotion cycle: fix the lineup, resubmit, and the fee is assessed afresh.

**Host confirmation.** A `RaceOfficial` confirms a `SUBMITTED` entry, optionally with a `note`; any other status is `ERR_ENTRY_NOT_SUBMITTED`. Confirmation requires that every `COXSWAIN` seat on the entry have `weigh_in_status` `PASSED` (`ERR_WEIGH_IN_NOT_PASSED`), that every seat be `ELIGIBLE`, and — when the regatta's `venue_kind` is `AWAY` — that the entry's `rack_tier` be non-null and its owning trailer load be in status `SEALED`, `DEPARTED` or `ARRIVED` (`ERR_ENTRY_NOT_RACKED`). `SUBMITTED → CONFIRMED` is what puts the crew into the lane-assignment candidate pool.

**Scratching.** A `Coach` or `ClubAdmin` scratches an entry with a stated `reason`, from any of `DRAFT`, `LINEUP_DECLARED`, `SUBMITTED` or `CONFIRMED` — `DRAFT → SCRATCHED`, `LINEUP_DECLARED → SCRATCHED`, `SUBMITTED → SCRATCHED` and `CONFIRMED → SCRATCHED`. From `DRAFT` or `LINEUP_DECLARED` no fee was ever assessed, so `refund_cents` is set to 0 and nothing else moves. From `SUBMITTED` or `CONFIRMED` the refund is computed and the regatta's `net_fee_cents` is recomputed; if `rack_tier` is non-null the entry's rack units are released and the owning trailer's `rack_units_used` and `rack_units_free` are recomputed. A scratch from `CONFIRMED` additionally voids every race lane of that entry whose `lane_status` is `PENDING`, and each voided lane decrements its heat's `occupied_lane_count` and drives that heat `LANES_ASSIGNED → SCHEDULED`. `RACED` and `SCRATCHED` are the entry's terminal states.

The refund percentage is chronological. When the logical clock at the scratch is at or before the regatta's `entry_deadline_at`, the percentage is 100 percent (1.00); otherwise, when it is at or before `scratch_deadline_at`, it is 55 percent (0.55); after that it is zero (0.00). The transport levy is refundable only while the hull can still be taken off the trailer: that is, when the entry's `trailer_load_id` is null, or when the owning trailer load is still in status `OPEN`. `refund_cents` is then the sum of three separately rounded components — the percentage of `base_fee_cents` rounded half up, plus the percentage of `late_fee_cents` rounded half up, plus, when the levy is refundable, the percentage of `transport_levy_cents` rounded half up; a non-refundable levy contributes zero. A regatta's `net_fee_cents` is at all times the sum, over its entries in status `SUBMITTED`, `CONFIRMED`, `RACED` or `SCRATCHED`, of `total_fee_cents` less `refund_cents` where a refund has been computed.

### 3.7. Trailering Hulls to Away Regattas

For an away regatta an `EquipmentManager` or `ClubAdmin` opens a trailer load against a `regatta_id`, naming the towing `driver_member_id` and the club `tow_vehicle_code`, with a scheduled `depart_at` and `return_at`. The rack geometry is declared as `rack_tier_count`, the number of horizontal tiers, and `rack_units_per_tier`, the units available on each tier; both default to 4 and both must be integers from 1 to 4 inclusive. The derived `rack_unit_capacity` is the tier count multiplied by the units per tier. A new load is `OPEN` with `rack_units_used` 0 and `rack_units_free` equal to the capacity.

**Claiming rack units.** An `EquipmentManager` racks an entry's hull by naming the `regatta_entry_id` alongside `expected_trailer_load_version`. The load must be `OPEN` — a sealed or departed load refuses both assignments and releases with `ERR_TRAILER_SEALED` — and the entry's `regatta_id` must match the load's `regatta_id`, or the request fails with `ERR_TRAILER_REGATTA_MISMATCH`.

Placement is a waterfall. The hull needs as many contiguous units as its class occupies: 1 for a `1X` or `2X`, 2 for a `4+`, 3 for an `8+`. Heavier hulls must ride low, so each class also has a highest permitted tier: a `1X` or `2X` may ride on any tier up to 4, a `4+` no higher than tier 2, and an `8+` only on tier 1. The server walks the tiers from tier 1 upward, stopping at whichever is lower of that class ceiling and the trailer's own `rack_tier_count`; within each tier it walks candidate starting positions from position 1 up to the last position at which a run of the required length still fits, which is the units per tier less the required units plus one. The first tier-and-start pair whose whole run of positions is free wins: `rack_tier` records the 1-based tier index, `rack_position` records the 1-based first occupied unit position within that tier, and `trailer_load_id` records the load. If no such run exists anywhere in the permitted range, the request is rejected with `ERR_TRAILER_TIER_UNAVAILABLE`.

After every assignment or release, `rack_units_used` is recomputed as the sum of the class rack units over the entries whose `trailer_load_id` is this load and whose status is `SUBMITTED`, `CONFIRMED` or `RACED` — a scratched entry releases its units and leaves the set — and `rack_units_free` is the capacity less that figure. Used plus free always equals `rack_unit_capacity`, before and after every assignment and release pair. Releasing an entry's units, again under `expected_trailer_load_version`, resets that entry's `rack_tier`, `rack_position` and `trailer_load_id` to null and recomputes both counters. Both operations increment the load's `version` by one.

**Moving the trailer.** The `EquipmentManager` drives the load through its states with a `to_status`. `OPEN → SEALED` requires the regatta to be `OPEN_FOR_ENTRY` or `ENTRIES_CLOSED` — a load may be built and sealed before entries close but never once the regatta is `RACING` — and requires `rack_units_used` to be greater than zero, since the club will not seal an empty trailer. `SEALED → OPEN` unseals the load and is permitted only while the logical clock is strictly before `depart_at`; that is the `OPEN → SEALED → OPEN` cycle, and it makes rack assignments and releases acceptable again. `SEALED → DEPARTED` requires the logical clock to have reached `depart_at` and the `driver_member_id` to have `membership_status` `ACTIVE`; from that moment the transport levy is no longer refundable on a scratch, per §3.6. `DEPARTED → ARRIVED` makes the hulls available for rigging at the away venue. `ARRIVED → RETURNED` requires the logical clock to have reached `return_at` and every entry on the load to have reached `RACED` or `SCRATCHED`; it releases every rack unit, recomputing `rack_units_used` to 0 and `rack_units_free` to the full `rack_unit_capacity`. `RETURNED` is terminal, and any transition outside these declared paths, or one whose precondition fails, is `ERR_INVALID_STATUS_TRANSITION`.

### 3.8. Race Day: Heats, Lanes, Results and Progression

A `RaceOfficial` schedules a heat against a `regatta_id` for an `event_code`, declaring the `round_kind` — `HEAT`, `SEMI` or `FINAL` — the `scheduled_start_at` first-stroke instant, the `lane_count` of buoyed lanes available as an integer from 1 to 8, and optionally `advance_count`, the number of automatic qualifiers from this heat, as an integer from 0 to 8 defaulting to 0. A heat may also be wired into the progression tree by naming `advances_to_heat_id`, the downstream round it feeds, which is null for a final. That downstream heat must belong to the same regatta and sit later in the progression — a heat may feed a semi or a final, and a semi may feed a final, but never the reverse — or the request is rejected with `ERR_HEAT_NOT_IN_REGATTA`. A new heat is `SCHEDULED` with `occupied_lane_count` 0, `free_lane_count` equal to `lane_count`, and `protest_window_closes_at` null.

**Seeding.** Lane assignment, run by a `RaceOfficial` and optionally annotated with a `note`, requires the heat's regatta to be `RACING` (`ERR_REGATTA_NOT_RACING`). The candidate pool is every entry whose `regatta_id` matches the heat's regatta, whose `event_code` matches the heat's event code, and whose status is exactly `CONFIRMED`; entries in any other status are excluded. An empty pool is rejected with `ERR_NO_ELIGIBLE_ENTRIES`. The candidates are then ranked by `seed_time_seconds` ascending, ties broken by `created_at` ascending. Lanes are drawn from the club's preference order — 3, 4, 2, 5, 1, 6, 7, 8 — filtered to those numbers that are no greater than the heat's `lane_count`, taken in that same list order, so the fastest seed gets the most sheltered middle water. If there are more candidates than available lanes, the request is rejected with `ERR_LANE_CAPACITY_EXCEEDED`. Otherwise a `RaceLane` row is created for each candidate in rank order, carrying the `heat_id`, the `regatta_entry_id`, the awarded `lane_number`, a `lane_status` of `PENDING`, `elapsed_seconds` and `place` null, and `advanced` false. `occupied_lane_count` is then the count of lanes on the heat whose `lane_status` is anything other than `VOIDED`, and `free_lane_count` is `lane_count` less that figure. The heat moves `SCHEDULED → LANES_ASSIGNED`.

Seeding is undone whenever a crew falls out. A lane moves `PENDING → VOIDED` when the entry occupying it leaves `CONFIRMED` or `SUBMITTED` — that is, when the entry has become `LINEUP_DECLARED` or `SCRATCHED` — and each such voiding decrements the heat's `occupied_lane_count`, recomputes `free_lane_count`, and drives the heat `LANES_ASSIGNED → SCHEDULED`. Demoting the heat voids every remaining lane on it that is still `PENDING` and recomputes `occupied_lane_count` to 0: the whole heat must be re-seeded rather than run a lane short. That is the `SCHEDULED → LANES_ASSIGNED → SCHEDULED` re-seed cycle.

**Results.** A `RaceOfficial` posts results for a `LANES_ASSIGNED` heat — any other status is `ERR_HEAT_NOT_ASSIGNED` — by supplying `lane_results`, which must carry an `elapsed_seconds` value at one decimal place for every lane on the heat currently in `PENDING`. Each such lane moves `PENDING → PROVISIONAL` with its `elapsed_seconds` recorded and its `place` computed, and the heat moves `LANES_ASSIGNED → RESULTS_PROVISIONAL`. A lane's `place` is its 1-based finish rank within the heat computed over the lanes whose `lane_status` is `PROVISIONAL` or `OFFICIAL`, ordered by `elapsed_seconds` ascending with ties broken by `created_at` ascending. Posting results also opens the jury's window: `protest_window_closes_at` is set to the logical clock at posting plus 30 minutes.

**Officialization.** Making a heat official requires the heat to be `RESULTS_PROVISIONAL` (`ERR_HEAT_NOT_PROVISIONAL`), the logical clock to have reached `protest_window_closes_at` (`ERR_PROTEST_WINDOW_OPEN` if it has not), and no protest on the heat to remain in status `FILED`, `UNDER_JURY_REVIEW` or `REMANDED`. Every lane still `PROVISIONAL` moves `PROVISIONAL → OFFICIAL`; a lane that the jury disqualified stays `DISQUALIFIED`. Advancement selection then runs, and every entry holding an `OFFICIAL` or `DISQUALIFIED` lane on this heat moves `CONFIRMED → RACED`. The heat moves `RESULTS_PROVISIONAL → RESULTS_OFFICIAL`, which is terminal. `OFFICIAL` and `VOIDED` are the lane's terminal states; `DISQUALIFIED` is deliberately not terminal, because a later denial can restore a disqualified lane as described in §3.9.

**Advancement.** Nothing advances when the heat's `advances_to_heat_id` is null. Otherwise the target is that downstream heat, and the source pool is every heat that feeds the same target and has itself reached `RESULTS_OFFICIAL`. Selection runs in three steps. First, the automatic qualifiers: taking the source heats in order of `scheduled_start_at` ascending with ties broken by `created_at` ascending, each source's lanes in `OFFICIAL` status are ordered by `elapsed_seconds` ascending with ties broken by `created_at` ascending, and the first `advance_count` of them for that source qualify automatically. Second, the fastest-loser fill: the number of remaining places is the target heat's `lane_count` less the total count of automatic qualifiers, and the pool of losers is every `OFFICIAL` lane across all source heats that did not qualify automatically, ordered by `elapsed_seconds` ascending with ties broken by `created_at` ascending; the first as-many-as-remaining of them fill the target, and the fill is empty when there are no remaining places. `DISQUALIFIED` and `VOIDED` lanes are excluded from both the automatic and the fastest-loser pools. Every selected lane has `advanced` set to true. Third, the target heat is seeded with the advancing crews: they are ordered by `elapsed_seconds` ascending with ties broken by `created_at` ascending, and lanes are awarded from the same preference order — 3, 4, 2, 5, 1, 6, 7, 8, filtered to the target's `lane_count` and taken in list order — exactly as at initial seeding.

### 3.9. The Jury: Protests, Deposits and Remedies

A `Member` or `Coach` lodges a protest while a heat's results are provisional, naming the `heat_id` under protest, the `filed_by_member_id` lodging it, the `against_race_lane_id` whose conduct is challenged, the rulebook `ground_code` — `INTERFERENCE`, `LANE_VIOLATION`, `EQUIPMENT` or `FALSE_START` — and a free-text `narrative` statement of the incident. The heat must be `RESULTS_PROVISIONAL` (`ERR_HEAT_NOT_PROVISIONAL`), the filer must have `membership_status` `ACTIVE`, the logical clock must be strictly before the heat's `protest_window_closes_at` (`ERR_PROTEST_WINDOW_CLOSED`), and the challenged lane must belong to that same heat, or the filing is rejected with `ERR_LANE_NOT_IN_HEAT`. The server stamps `filed_at` from the logical clock, holds a deposit of 5000 cents in `deposit_cents` with `deposit_refunded` false, sets `review_round` to 0 and `jury_user_id` to null, opens the protest at `FILED`, and recomputes the regatta's `deposit_held_cents`.

That regatta figure is the sum of `deposit_cents` over the protests attached to the regatta's heats whose `deposit_refunded` is false and whose status is not `WITHDRAWN`. Filing a protest raises it by 5000 cents; upholding or withdrawing the protest returns it to exactly its pre-filing value; denying the protest leaves the forfeited deposit in it permanently.

**Opening review.** A `JuryChair` opens a review round on a `FILED` protest, or reopens one on a `REMANDED` protest, optionally with a `note`. Conflict-of-interest screening applies: the acting chair may not be the protest's `filed_by_member_id`, and — when opening from `FILED` — may not hold a `LineupSeat` on any entry that holds a race lane on the protested heat; either bars the request with `ERR_JURY_CONFLICT_OF_INTEREST`. Reopening from `REMANDED` additionally requires `review_round` to be strictly below the ceiling of two review rounds, or the request fails with `ERR_MAX_JURY_ROUNDS_EXCEEDED`. Opening increments `review_round` by one, stamps `jury_user_id` with the acting chair, and moves the protest to `UNDER_JURY_REVIEW` — `FILED → UNDER_JURY_REVIEW` or `REMANDED → UNDER_JURY_REVIEW`.

**Ruling.** A `JuryChair` rules on an `UNDER_JURY_REVIEW` protest — any other status is `ERR_PROTEST_NOT_UNDER_REVIEW` — by supplying a `decision` with a written `rationale`, and, when upholding, a `remedy`. The heat must still be `RESULTS_PROVISIONAL`.

- A `decision` of `REMAND` sends the matter back for a further round, permitted only while `review_round` is strictly below two (`ERR_MAX_JURY_ROUNDS_EXCEEDED`). `UNDER_JURY_REVIEW → REMANDED` leaves the deposit held and the regatta's `deposit_held_cents` unchanged, and the protest may then be reopened — the `UNDER_JURY_REVIEW → REMANDED → UNDER_JURY_REVIEW` negotiation cycle, bounded at two rounds in total.
- A `decision` of `UPHELD` moves the protest `UNDER_JURY_REVIEW → UPHELD`, sets `deposit_refunded` to true and recomputes the regatta's `deposit_held_cents`, and applies the `remedy`. A `remedy` of `DISQUALIFY` drives the lane named by `against_race_lane_id` from `PROVISIONAL → DISQUALIFIED`, resets that lane's `place` to null, and recomputes `place` across the heat's remaining `PROVISIONAL` lanes. A `remedy` of `RE_ROW` drives the heat `RESULTS_PROVISIONAL → LANES_ASSIGNED`, returns every lane on that heat still in `PROVISIONAL` to `PENDING` with `elapsed_seconds` and `place` reset to null, and resets `protest_window_closes_at` to null — the `LANES_ASSIGNED → RESULTS_PROVISIONAL → LANES_ASSIGNED` protest cycle, after which results must be posted again and a fresh protest window opens.
- A `decision` of `DENIED` moves the protest `UNDER_JURY_REVIEW → DENIED` and leaves `deposit_refunded` false: the deposit is forfeited to the host and remains inside the regatta's `deposit_held_cents`. A denial on a later protest citing a lane that an earlier ruling disqualified restores that lane `DISQUALIFIED → PROVISIONAL`, provided no other protest citing the same lane stands `UPHELD`, and `place` is recomputed across the heat.

**Withdrawal.** The filer, acting as a `Member`, may withdraw their own protest while it is still `FILED`; the acting `X-User-ID` must equal `filed_by_member_id`. `FILED → WITHDRAWN` sets `deposit_refunded` to true and recomputes the regatta's `deposit_held_cents`. `UPHELD`, `DENIED` and `WITHDRAWN` are the protest's terminal states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, payments, weigh-ins, rack assignments and operator checkpoints — return `200 OK`. All read operations return `200 OK`. Every error carries the status code listed in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/boathouse/_clock/set_current_utc` | Move the server's logical clock to the supplied instant | ClubAdmin |
| POST | `/boathouse/members` | Enrol a club member in a membership tier | ClubAdmin |
| GET | `/boathouse/members/{id}` | Read one member including computed dues balance and access level | ClubAdmin, Member, Coach, SafetyOfficer, EquipmentManager, RaceOfficial, JuryChair |
| GET | `/boathouse/members` | Paginated member roster | ClubAdmin, Coach, SafetyOfficer, RaceOfficial |
| PATCH | `/boathouse/members/{id}/certifications` | Record or amend swim test, certification expiries and launch supervision limit | ClubAdmin |
| POST | `/boathouse/members/{id}/status-transitions` | Drive a member through the membership state machine | ClubAdmin |
| GET | `/boathouse/members/{id}/dues-invoices` | List a member's dues invoices | ClubAdmin, Member |
| POST | `/boathouse/dues-invoices` | Issue a prorated seasonal dues invoice | ClubAdmin |
| GET | `/boathouse/dues-invoices/{id}` | Read one dues invoice | ClubAdmin, Member |
| POST | `/boathouse/dues-invoices/{id}/payments` | Apply a payment to a dues invoice | Member, ClubAdmin |
| POST | `/boathouse/dues-invoices/{id}/true-up` | Rebill a dues invoice on actual usage | ClubAdmin |
| POST | `/boathouse/dues-invoices/{id}/void` | Void an unpaid dues invoice | ClubAdmin |
| POST | `/boathouse/ops/dues-delinquency-run` | Operator checkpoint: flag past-due invoices and cascade the delinquency chain | ClubAdmin |
| POST | `/boathouse/shells` | Add a hull to the fleet | EquipmentManager, ClubAdmin |
| GET | `/boathouse/shells/{id}` | Read one hull including both condition-index variants | ClubAdmin, Member, Coach, SafetyOfficer, EquipmentManager, RaceOfficial |
| GET | `/boathouse/shells` | Paginated fleet roster | ClubAdmin, Coach, SafetyOfficer, EquipmentManager |
| POST | `/boathouse/shells/{id}/retire` | Retire an available hull permanently | EquipmentManager |
| POST | `/boathouse/damage-reports` | File a damage report against a hull | Member, Coach, EquipmentManager |
| GET | `/boathouse/damage-reports/{id}` | Read one damage report | ClubAdmin, Member, Coach, EquipmentManager |
| GET | `/boathouse/damage-reports` | Filtered damage-report list | ClubAdmin, Member, Coach, EquipmentManager |
| POST | `/boathouse/damage-reports/{id}/triage` | Triage a report to repair or close it with no action; also the reschedule path | EquipmentManager |
| POST | `/boathouse/damage-reports/{id}/schedule-repair` | Reserve a repair bay and closed repair window | EquipmentManager |
| POST | `/boathouse/damage-reports/{id}/verify-repair` | Verify a completed repair after the reserved window has elapsed | EquipmentManager |
| POST | `/boathouse/damage-reports/{id}/condemn` | Condemn a structurally damaged hull, starting the condemnation cascade | EquipmentManager |
| POST | `/boathouse/water-condition-readings` | Post an immutable river-condition observation | SafetyOfficer |
| GET | `/boathouse/water-condition-readings/{id}` | Read one condition reading | ClubAdmin, Coach, SafetyOfficer |
| GET | `/boathouse/water-condition-readings` | Paginated reading log | ClubAdmin, Coach, SafetyOfficer |
| POST | `/boathouse/water-sessions` | Book a hull and crew onto a water window | Coach, SafetyOfficer |
| GET | `/boathouse/water-sessions/{id}` | Read one water session | ClubAdmin, Coach, SafetyOfficer, Member |
| GET | `/boathouse/water-sessions` | Filtered session list | ClubAdmin, Coach, SafetyOfficer, Member |
| POST | `/boathouse/water-sessions/{id}/clear` | Safety-clear a planned session against a specific condition reading | SafetyOfficer |
| POST | `/boathouse/water-sessions/{id}/launch` | Log a cleared crew onto the water | SafetyOfficer |
| POST | `/boathouse/water-sessions/{id}/return` | Log a crew back in, releasing the hull and crediting session counts | SafetyOfficer |
| POST | `/boathouse/water-sessions/{id}/cancel` | Cancel a planned or cleared session | Coach, SafetyOfficer |
| POST | `/boathouse/regattas` | Create a regatta with its entry, scratch and weigh-in windows | ClubAdmin |
| GET | `/boathouse/regattas/{id}` | Read one regatta including the fee and deposit ledgers | ClubAdmin, Coach, RaceOfficial, JuryChair, EquipmentManager, Member |
| GET | `/boathouse/regattas` | Paginated regatta calendar | ClubAdmin, Coach, RaceOfficial, Member |
| POST | `/boathouse/regattas/{id}/status-transitions` | Drive a regatta through its lifecycle, including the late-entry reopen | ClubAdmin |
| POST | `/boathouse/regatta-entries` | Open a draft entry for a boat class in a regatta event | Coach |
| GET | `/boathouse/regatta-entries/{id}` | Read one entry including its fee breakdown and rack position | ClubAdmin, Coach, RaceOfficial, EquipmentManager, JuryChair |
| GET | `/boathouse/regatta-entries` | Filtered entry list | ClubAdmin, Coach, RaceOfficial, EquipmentManager |
| POST | `/boathouse/regatta-entries/{id}/lineup` | Declare or wholesale redeclare the crew lineup under optimistic concurrency | Coach |
| POST | `/boathouse/regatta-entries/{id}/submit` | Submit a declared entry to the host, assessing the entry fee | Coach |
| POST | `/boathouse/regatta-entries/{id}/confirm` | Host confirmation after weigh-ins and, for away regattas, racking | RaceOfficial |
| POST | `/boathouse/regatta-entries/{id}/scratch` | Scratch an entry, computing the refund and releasing rack units and lanes | Coach, ClubAdmin |
| GET | `/boathouse/lineup-seats/{id}` | Read one lineup seat including weigh-in and eligibility state | ClubAdmin, Coach, RaceOfficial, Member |
| GET | `/boathouse/lineup-seats` | Filtered seat list | ClubAdmin, Coach, RaceOfficial, Member |
| POST | `/boathouse/lineup-seats/{id}/weigh-in` | Record a coxswain weigh-in inside the regatta's weigh-in window | RaceOfficial |
| POST | `/boathouse/heats` | Schedule a heat, optionally wiring it into a downstream round | RaceOfficial |
| GET | `/boathouse/heats/{id}` | Read one heat including lane occupancy and the protest window | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| GET | `/boathouse/heats` | Filtered heat list | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| POST | `/boathouse/heats/{id}/assign-lanes` | Seed the heat from confirmed entries and award lanes by preference order | RaceOfficial |
| POST | `/boathouse/heats/{id}/results` | Post provisional finish times for every pending lane and open the protest window | RaceOfficial |
| POST | `/boathouse/heats/{id}/officialize` | Make results official once the protest window has closed, running advancement | RaceOfficial |
| GET | `/boathouse/race-lanes/{id}` | Read one race lane | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| GET | `/boathouse/race-lanes` | Filtered lane list | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| POST | `/boathouse/protests` | Lodge a protest against a lane inside the heat's protest window | Member, Coach |
| GET | `/boathouse/protests/{id}` | Read one protest including review round and deposit state | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| GET | `/boathouse/protests` | Filtered protest list | ClubAdmin, Coach, RaceOfficial, JuryChair, Member |
| POST | `/boathouse/protests/{id}/open-review` | Open or reopen a jury review round, subject to conflict-of-interest screening | JuryChair |
| POST | `/boathouse/protests/{id}/rule` | Rule on a protest: uphold with a remedy, deny, or remand for another round | JuryChair |
| POST | `/boathouse/protests/{id}/withdraw` | Filer withdraws their own protest before review opens | Member |
| POST | `/boathouse/trailer-loads` | Open a trailer load for an away regatta | EquipmentManager, ClubAdmin |
| GET | `/boathouse/trailer-loads/{id}` | Read one trailer load including rack occupancy | ClubAdmin, Coach, EquipmentManager, RaceOfficial |
| GET | `/boathouse/trailer-loads` | Filtered trailer list | ClubAdmin, Coach, EquipmentManager, RaceOfficial |
| POST | `/boathouse/trailer-loads/{id}/rack-assignments` | Claim a contiguous run of rack units under optimistic concurrency | EquipmentManager |
| POST | `/boathouse/trailer-loads/{id}/rack-releases` | Release an entry's rack units under optimistic concurrency | EquipmentManager |
| POST | `/boathouse/trailer-loads/{id}/transitions` | Drive a trailer load through sealing, unsealing, departure, arrival and return | EquipmentManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_DUES_INVOICE_NOT_FOUND` | 404 |
| `ERR_SHELL_NOT_FOUND` | 404 |
| `ERR_DAMAGE_REPORT_NOT_FOUND` | 404 |
| `ERR_READING_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_REGATTA_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_SEAT_NOT_FOUND` | 404 |
| `ERR_HEAT_NOT_FOUND` | 404 |
| `ERR_LANE_NOT_FOUND` | 404 |
| `ERR_PROTEST_NOT_FOUND` | 404 |
| `ERR_TRAILER_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_ENTRY_VERSION` | 412 |
| `ERR_STALE_TRAILER_VERSION` | 412 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_SHELL_NOT_AVAILABLE` | 409 |
| `ERR_SESSION_NOT_CLEARED` | 409 |
| `ERR_SESSION_NOT_LAUNCHED` | 409 |
| `ERR_REPORT_NOT_TRIAGED` | 409 |
| `ERR_REPORT_NOT_SCHEDULED` | 409 |
| `ERR_REGATTA_ENTRIES_CLOSED` | 409 |
| `ERR_ENTRY_NOT_DECLARED` | 409 |
| `ERR_ENTRY_NOT_SUBMITTED` | 409 |
| `ERR_HEAT_NOT_ASSIGNED` | 409 |
| `ERR_HEAT_NOT_PROVISIONAL` | 409 |
| `ERR_PROTEST_NOT_UNDER_REVIEW` | 409 |
| `ERR_TRAILER_SEALED` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATUS_TRANSITION` | 409 |
| `ERR_SELF_TRIAGE_FORBIDDEN` | 403 |
| `ERR_SELF_CLEARANCE_FORBIDDEN` | 403 |
| `ERR_SELF_WEIGH_IN_FORBIDDEN` | 403 |
| `ERR_JURY_CONFLICT_OF_INTEREST` | 403 |
| `ERR_WATER_CLOSED` | 409 |
| `ERR_SWIM_TEST_MISSING` | 409 |
| `ERR_COXSWAIN_CERT_EXPIRED` | 409 |
| `ERR_COACH_CERT_EXPIRED` | 409 |
| `ERR_LAUNCH_CERT_EXPIRED` | 409 |
| `ERR_LAUNCH_COVERAGE_INSUFFICIENT` | 409 |
| `ERR_SHELL_CONDITION_TOO_LOW` | 409 |
| `ERR_TIER_NOT_PERMITTED_FOR_HULL` | 409 |
| `ERR_SHELL_WINDOW_CONFLICT` | 409 |
| `ERR_LAUNCH_DRIVER_OVERBOOKED` | 409 |
| `ERR_REPAIR_BAY_CONFLICT` | 409 |
| `ERR_WEIGH_IN_WINDOW_CLOSED` | 409 |
| `ERR_PROTEST_WINDOW_CLOSED` | 409 |
| `ERR_PROTEST_WINDOW_OPEN` | 409 |
| `ERR_SEAT_COUNT_MISMATCH` | 422 |
| `ERR_DUPLICATE_SEAT_MEMBER` | 409 |
| `ERR_BOAT_CLASS_MISMATCH` | 409 |
| `ERR_NO_ELIGIBLE_ENTRIES` | 409 |
| `ERR_REGATTA_NOT_RACING` | 409 |
| `ERR_LANE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TRAILER_TIER_UNAVAILABLE` | 409 |
| `ERR_MAX_JURY_ROUNDS_EXCEEDED` | 409 |
| `ERR_WEIGH_IN_NOT_PASSED` | 409 |
| `ERR_ENTRY_NOT_RACKED` | 409 |
| `ERR_LANE_NOT_IN_HEAT` | 409 |
| `ERR_HEAT_NOT_IN_REGATTA` | 409 |
| `ERR_TRAILER_REGATTA_MISMATCH` | 409 |
| `ERR_SEAT_MEMBER_DELINQUENT` | 402 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 |
| `ERR_TRUEUP_ALREADY_APPLIED` | 409 |
