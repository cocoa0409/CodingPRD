# Polling-Place Management API — Product Requirements Document

## 1. Introduction

Running an election day is an exercise in orchestrating people, equipment, paper, and time under rules that cannot be bent. This document specifies the Polling-Place & Poll-Worker Management API, a system whose job is to keep every precinct honest and operational from the moment blank ballots leave a central warehouse to the moment a precinct's results are reconciled against its electronic pollbook. The API is mounted at the root path and coordinates the recruitment and certification of poll workers, their assignment and scheduling into staffed shifts, the physical chain-of-custody of sealed supply kits, the live operational posture of each polling location, the adjudication of provisional ballots, the support-hotline incident queue, and the final results-return reconciliation.

The central design tension the system resolves is that election-day operations are gated by *posture*: a polling place may only accept voters when its equipment is working, its supplies are present and untampered, and it is adequately staffed — and that guarantee must survive events that arrive out of order, such as an equipment failure reported mid-day or a seal found broken on a delivered kit. Every consequential action therefore either advances a state machine or is blocked by one, and many actions cascade: closing voting closes places, closing a place checks out its workers, and checking a worker out accrues their pay. The requirements below define these workflows precisely so that an implementation can be verified against a fixed contract.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Read operations (GET) require authentication just as writes do. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `ElectionAdmin`, `PrecinctCaptain`, `PollWorker`, `CustodyOfficer`, and `SupportAgent`.

- An `ElectionAdmin` runs the election as a whole: creating elections, polling places, equipment, and poll workers; deploying equipment; opening and closing the voting window; and certifying training. When `X-User-Role` is `ElectionAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit context but never compares it to any entity's `id`.
- A `PrecinctCaptain` runs a single place: opening, suspending, resuming, closing, and reconciling it, managing its assignments and shifts, and adjudicating its provisional ballots. When `X-User-Role` is `PrecinctCaptain`, `X-User-ID` is the `id` of the acting `PollWorker`; ownership checks on any resource that references a `PollWorker` compare that resource's poll-worker foreign key to `X-User-ID`.
- A `PollWorker` is a regular worker who checks into and out of their own shifts and casts provisional ballots. When `X-User-Role` is `PollWorker`, `X-User-ID` is likewise the `id` of the acting `PollWorker`, and the same ownership comparison applies.
- A `CustodyOfficer` owns the chain of custody: preparing supply kits and recording every custody transition. When `X-User-Role` is `CustodyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records the acting role in the `actor_role` field of each custody event it appends, but does not compare `X-User-ID` to any entity's `id`.
- A `SupportAgent` runs the support hotline: opening, acknowledging, escalating, and resolving incidents. When `X-User-Role` is `SupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

The specific operations each role may invoke are summarized by the authorized-role column of the endpoint table in Section 4; the two authentication checks above are always evaluated before any other validation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100, and a non-integer `limit` falls back to the default of 10. The `offset` parameter is the number of items to skip and defaults to 0; a negative or non-integer `offset` is treated as 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties

Most resources share a common set of system-managed fields. Elections, polling places, equipment units, poll workers, assignments, shifts, supply kits, provisional ballots, and incidents each carry:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It is the anchor for optimistic concurrency control (Section 2.8).

Custody events are the one exception. A custody event is an immutable audit record: once appended it is never modified, so it carries only `id` and `created_at`. It has no `updated_at` and no `version`.

Whenever a derived or system field on a resource changes — for example when a place's `slots_filled` shifts because an assignment activated, or when a poll worker's `accrued_payroll_cents` grows on check-out — that change is a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Readiness Posture and Cascading State Propagation

The operational heartbeat of the system is the polling place's `readiness_posture`, a derived operational posture that gates all child operations at the place. It is one of `SETUP`, `OPEN`, `SUSPENDED`, `CLOSED`, or `RECONCILED`, starting at `SETUP`. A place cycles between `OPEN` and `SUSPENDED` as conditions degrade and recover during the day, ends the day at `CLOSED`, and finishes at `RECONCILED` once its results are returned.

State transitions frequently cascade across resources, and every arm of a cascade must land. Three cascade chains matter:

- **Voting close → place close → shift check-out → payroll.** When an election closes its voting window, every child polling place still in posture `OPEN` is transitioned `OPEN → CLOSED`. Each such place-close in turn auto-checks-out every one of its shifts in status `CHECKED_IN` (`CHECKED_IN → CHECKED_OUT`, stamping `check_out_time` from the logical clock), and each auto-check-out computes pay and accrues it to the worker exactly as a manual check-out would.
- **Incident escalate → equipment out of service → place suspend.** Escalating an equipment-related incident takes the referenced equipment unit `OPERATIONAL → OUT_OF_SERVICE`; if that unit's owning place is `OPEN`, the loss of its operational guarantee forces the place `OPEN → SUSPENDED`.
- **Seal break → place suspend.** Recording a broken seal on a kit that is stationed at an `OPEN` place forces that place `OPEN → SUSPENDED`.

Every one of these automatic transitions is a genuine mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`, exactly as an explicit client request would. The system performs these transitions on its own initiative, without requiring the client to call the affected resource directly.

### 2.6. The Logical Clock

The system keeps a logical clock rather than reading wall-clock time. At startup the clock reads `2026-03-01T00:00:00Z`, and it never falls back to real time. An `ElectionAdmin` may advance or set the clock by supplying a target instant `to_iso8601` (the clock may be moved forward or backward with no monotonicity check); the response reports the new value as `current_utc`. Every timestamp the system stamps itself — a shift's `check_in_time`, a shift's `check_out_time`, and equally every resource's `created_at` and `updated_at`, every custody event's `created_at`, and each response's `api_request_timestamp` — is read from this logical clock at the instant of the operation, never from wall-clock time.

### 2.7. Payroll Precision and Rounding

All money in the system is expressed in whole integer cents. Hours are computed to four decimal places using the round-half-up rule: an hour count is the elapsed seconds divided by 3600, rounded half-up to four decimals. When pay is computed, the regular-pay component and the overtime-pay component are each rounded half-up to whole cents *independently*, and only then summed; there is no separate rounding of the sum. When a place's total payroll is aggregated across its shifts, each shift's already-rounded gross pay is summed as an integer with no further rounding — the per-shift rounding is authoritative, and summing raw unrounded amounts and rounding once at the end is explicitly forbidden. Reconciliation counts are plain integers and are never rounded.

### 2.8. Optimistic Concurrency Control

The results-return reconciliation is the one write in the system guarded by optimistic concurrency control, because it is deliberately re-runnable: a corrected results-return is allowed to supersede a prior one, so the system cannot rely on a one-way posture change to prevent a client from overwriting a submission it never saw. A reconcile request against a polling place must carry `expected_polling_place_version`, a non-optional field holding the `version` of that place the client last observed. If `expected_polling_place_version` does not equal the place's current `version` — meaning another writer advanced the place since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because reconcile is re-runnable, a stale submission is caught on this version check rather than on any posture precondition. No other endpoint takes a version field or performs an OCC check.

### 2.9. Nested Resource Retrieval and Referential Validation

References are validated left-to-right. For any request, the system checks that every resource named in the path and every resource named by a foreign key in the body exists, in order, before applying business rules. The first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404). A request that names a shift under a nonexistent assignment, or an adjudication of a provisional ballot that does not exist, fails on the missing resource before any state or business check runs.

### 2.10. Conserved-Quantity Invariants

Two quantities in the system are strictly conserved and must always balance.

**Ballot stock.** An election is created with an `initial_ballot_stock` of blank ballots held centrally. Its `unallocated_ballot_stock` starts equal to `initial_ballot_stock` and tracks the ballots not yet committed to any kit. Committing a kit's `ballot_count` to it (issuing the kit) decrements `unallocated_ballot_stock` by that count; voiding that issuance restores it by the same count. The sum of unallocated stock and all committed kit ballots is therefore conserved against `initial_ballot_stock`.

**Staffing slots.** A polling place is created with a `staffing_capacity`, and its `slots_open` starts equal to `staffing_capacity`. Its `slots_filled` counts the assignments at the place in status `ACTIVE`. The invariant `slots_filled` + `slots_open` == `staffing_capacity` holds at all times: activating an assignment increments `slots_filled` and decrements `slots_open` by one; withdrawing an active assignment does the reverse.

## 3. Business Logic & Workflows

### 3.1. The Election and Its Voting Window

Everything hangs off an **Election**, created by an `ElectionAdmin` with a `name` (for example, "2026 General Election"), a `jurisdiction` identifier, an `election_date` in ISO 8601, and an `initial_ballot_stock` of at least zero. On creation the election's `status` begins at `PLANNING` and its `unallocated_ballot_stock` is initialized to equal `initial_ballot_stock`.

The voting window is a two-step lifecycle. Opening voting advances the election `PLANNING → VOTING_OPEN`; it is permitted only while the election is in `PLANNING`. Closing voting advances it `VOTING_OPEN → VOTING_CLOSED` and is permitted only while the election is in `VOTING_OPEN`; `VOTING_CLOSED` is terminal. Closing voting is the head of the day-end cascade described in Section 2.5: every child polling place still in posture `OPEN` is closed, which in turn checks out its checked-in shifts and accrues their pay. Both voting transitions increment the election's `version` by one. Attempting either transition from the wrong status is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Standing Up and Operating a Polling Place

A polling place is created by an `ElectionAdmin` under an election, identified by its `election_id`, with a `name`, a street `address`, a `min_workers_required` quorum of at least one, a `staffing_capacity` of at least one, and a `station_capacity` of at least one (the number of check-in stations, which bounds how many shift windows may overlap at the place). Three accessibility attributes are captured: `wheelchair_accessible` and `accessible_parking` are booleans that each default to false, and `ada_voting_stations` is a count of ADA-compliant ballot-marking stations of at least zero, defaulting to zero. On creation `slots_open` is initialized to `staffing_capacity`, `slots_filled` and `provisional_cast_count` and `provisional_accepted_count` and `spoiled_count` begin at zero, `reconciliation_status` begins at `UNRECONCILED`, and the machine-return fields `scanner_tally`, `epollbook_checkins`, and `reconciliation_discrepancy` are null until reconciliation.

**Opening.** Bringing a place from `SETUP` to `OPEN` is the most heavily gated action in the system, run by the `PrecinctCaptain`. It requires, in this evaluation order after the standard existence check: that the place currently be in a posture from which opening is defined, i.e. `SETUP` (otherwise `ERR_INVALID_STATE`, 409); that the place's election be in `VOTING_OPEN` (otherwise `ERR_VOTING_NOT_OPEN`, 409); that no supply kit for the place be in custody state `COMPROMISED` (otherwise `ERR_KIT_COMPROMISED`, 409); that no equipment unit assigned to the place be `OUT_OF_SERVICE` and that at least one supply kit for the place be in custody state `AT_PLACE` (otherwise `ERR_EQUIPMENT_NOT_OPERATIONAL`, 409); and finally that `slots_filled` be greater than or equal to `min_workers_required` (otherwise `ERR_UNDERSTAFFED`, 422). When all pass, `readiness_posture` is set to `OPEN` and the place's `version` increments.

**Suspending, resuming, closing.** A `PrecinctCaptain` may suspend an open place, taking it `OPEN → SUSPENDED`, optionally supplying a `reason`; suspend is defined only from `OPEN`. This same `OPEN → SUSPENDED` edge is also the tail of the two automatic cascades in Section 2.5 (equipment going out of service, and a seal break at the place). Resuming takes a place `SUSPENDED → OPEN` and re-checks the same physical guarantees, evaluated in this order: first that no kit for the place may be `COMPROMISED` (otherwise `ERR_KIT_COMPROMISED`), then that no equipment unit at the place may be `OUT_OF_SERVICE` (otherwise `ERR_EQUIPMENT_NOT_OPERATIONAL`); unlike opening, resuming does not require any kit to be `AT_PLACE`. Closing a place takes it to `CLOSED` from either `OPEN` or `SUSPENDED`. When closing from `OPEN`, the close carries out the middle link of the day-end cascade: every shift at the place in status `CHECKED_IN` is auto-transitioned `CHECKED_IN → CHECKED_OUT`, its `check_out_time` stamped from the logical clock and its pay computed and accrued. Each of suspend, resume, and close increments the place's `version`; an attempt from a posture where the transition is undefined yields `ERR_INVALID_STATE`.

### 3.3. Equipment Inventory and Deployment

An **EquipmentUnit** is created in the warehouse by an `ElectionAdmin` with an `equipment_type` — one of `SCANNER`, `BMD`, `EPOLLBOOK`, or `PRINTER` — and a manufacturer `serial_number`. Its `status` begins at `IN_WAREHOUSE` and its `polling_place_id` is null. Deploying a unit takes it `IN_WAREHOUSE → OPERATIONAL`: the caller supplies the target `polling_place_id`, which must reference an existing place; the unit's `polling_place_id` is set and its `version` increments. Deploy is defined only from `IN_WAREHOUSE`.

A unit reaches `OUT_OF_SERVICE`, a terminal status, only through the equipment cascade: when an equipment-related incident is escalated, the referenced unit is driven `OPERATIONAL → OUT_OF_SERVICE`, and if its owning place is `OPEN` that place is forced `OPEN → SUSPENDED` because its operational guarantee is now broken. This is why opening and resuming a place both require that no equipment unit at the place be out of service.

### 3.4. Recruiting, Certifying, and Assigning Poll Workers

A **PollWorker** is recruited by an `ElectionAdmin` with a `full_name`, an `email`, and an optional `phone` (which defaults to null). Their `training_status` begins at `PENDING`, their `accrued_payroll_cents` at zero, and their `stipend_paid` flag at false. Completing training moves `training_status` `PENDING → CERTIFIED` and increments the worker's `version`; it is defined only from `PENDING`, and an attempt to complete training for a worker not in `PENDING` is rejected with `ERR_INVALID_STATE` (409). Certification is a hard prerequisite for real work: a worker must be `CERTIFIED` before an assignment naming them can be activated and before they can be checked into a shift.

An **Assignment** proposes placing a worker at a place. It is created (by a `PrecinctCaptain` or `ElectionAdmin`) with a `poll_worker_id`, a `polling_place_id`, and an optional `is_lead` boolean (defaulting to false) marking the worker as the precinct lead for differential pay. Its `status` begins at `PROPOSED`. Activating an assignment takes it `PROPOSED → ACTIVE` and consumes a staffing slot; it requires that the assignment be `PROPOSED`, that the named worker's `training_status` be `CERTIFIED` (otherwise `ERR_WORKER_NOT_CERTIFIED`, 422), and that the place have at least one open slot, i.e. `slots_open` greater than or equal to one (otherwise `ERR_NO_OPEN_SLOTS`, 422). On success the place's `slots_filled` increases by one and `slots_open` decreases by one, and the assignment's `version` increments.

Withdrawing an assignment moves it to `WITHDRAWN`, a terminal status, from either `PROPOSED` or `ACTIVE`. Withdrawing an `ACTIVE` assignment releases its slot — `slots_filled` decreases by one and `slots_open` increases by one — whereas withdrawing a `PROPOSED` assignment releases no slot, because none was ever filled. Either way the assignment's `version` increments. A transition attempted from a status where it is undefined is rejected with `ERR_INVALID_STATE`.

### 3.5. Scheduling Shifts, Check-In, Check-Out, and Pay

A **Shift** is scheduled against an assignment by a `PrecinctCaptain` or `ElectionAdmin`, who supply the `assignment_id`, a `scheduled_start`, and a `scheduled_end`; creation validates only that the named assignment exists and does not require it to be `ACTIVE` (that requirement is enforced later, at check-in). The `scheduled_end` must be strictly after `scheduled_start`; otherwise the request is rejected with `ERR_INVALID_REQUEST` (422). On creation the shift copies `poll_worker_id`, `polling_place_id`, and `is_lead` from its parent assignment, and its `status` begins at `SCHEDULED` with `check_in_time` and `check_out_time` null. The system computes `scheduled_hours` as the planned window length — the seconds between `scheduled_start` and `scheduled_end` divided by 3600, rounded half-up to four decimals — and from it computes the provisional gross pay `scheduled_pay_cents` (the scheduled-projection pay variant described below). This projected pay is fixed at creation and is independent of what actually gets worked.

Two scheduling constraints guard creation. First, the new shift's half-open window `[scheduled_start, scheduled_end)` must not overlap any other shift of the same worker; two shifts that merely touch at a shared boundary do not overlap and are allowed. A violation is `ERR_WORKER_SHIFT_OVERLAP` (409). Second, the number of existing shifts at the place whose windows overlap the new shift's window must be strictly less than the place's `station_capacity`; if admitting the new shift would meet or exceed capacity, it is rejected with `ERR_PLACE_CAPACITY_EXCEEDED` (409).

**Check-in.** A `PrecinctCaptain` or the `PollWorker` themselves checks a worker into a shift, advancing it `SCHEDULED → CHECKED_IN`. Check-in requires that the shift be `SCHEDULED`, that the worker's `training_status` be `CERTIFIED` (otherwise `ERR_WORKER_NOT_CERTIFIED`, 422), that the parent assignment be `ACTIVE`, and that the owning place's `readiness_posture` be `OPEN` — the latter two being conditions on the surrounding state, rejected as `ERR_INVALID_STATE` when unmet. Check-in also re-applies the per-worker overlap guard: no other shift of the same worker in status `CHECKED_IN` or `SCHEDULED` may have a window overlapping `[scheduled_start, scheduled_end)`, again with `ERR_WORKER_SHIFT_OVERLAP` on violation. On success `check_in_time` is stamped from the logical clock, the status becomes `CHECKED_IN`, and `version` increments.

**Check-out and pay.** A check-out advances a shift `CHECKED_IN → CHECKED_OUT`; it may be triggered explicitly by a `PrecinctCaptain` or the `PollWorker`, or automatically by the place-close cascade. On check-out the system stamps `check_out_time` from the logical clock, computes `actual_hours` as the seconds between `check_in_time` and `check_out_time` divided by 3600 rounded half-up to four decimals, and computes the final gross pay `gross_pay_cents` from `actual_hours` (the actual-final pay variant). It then performs the payroll cascade: `gross_pay_cents` is added to the worker's `accrued_payroll_cents`, and if the worker's `stipend_paid` flag is still false, a one-time training stipend of 5000 cents is additionally added to `accrued_payroll_cents` and `stipend_paid` is set to true. The owning place's `total_payroll_cents` is then recomputed, and the shift's `version` increments.

**The pay formula.** Gross pay for a shift is tiered on an eight-hour daily threshold. The applicable hourly rate is 2450 cents when the shift's `is_lead` is true and 1825 cents otherwise. Given a number of hours H, the regular hours are the lesser of H and 8.0, and the overtime hours are H minus 8.0 when that difference is positive and zero otherwise — so overtime accrues only when H is strictly greater than 8.0. Regular pay is the regular hours multiplied by the rate, rounded half-up to whole cents. Overtime pay is the overtime hours multiplied by the rate multiplied by an overtime multiplier of 1.5, rounded half-up to whole cents independently. Gross pay is the sum of those two rounded components. This formula has two variants that differ only in which H they use:

- **Scheduled-projection variant.** H is `scheduled_hours`, derived from the planned window `scheduled_start`/`scheduled_end`. This yields `scheduled_pay_cents`, computed at shift creation as a provisional estimate; it diverges from the final gross whenever worked time differs from planned time.
- **Actual-final variant.** H is `actual_hours`, derived from the `check_in_time`/`check_out_time` clock stamps. This is the authoritative pay, written to `gross_pay_cents` on check-out and rolled into payroll.

The one-time training stipend is never part of `gross_pay_cents`; it is added to the worker's `accrued_payroll_cents` exactly once, on that worker's first check-out.

**Place payroll aggregation.** A place's `total_payroll_cents` is the sum, over only those shifts of the place in status `CHECKED_OUT`, of each shift's `gross_pay_cents`. Shifts in `SCHEDULED` or `CHECKED_IN` are excluded. Because each shift's gross was already rounded per the pay formula, the aggregation is a plain integer summation with no second rounding.

### 3.6. Supply Kits and the Chain of Custody

A **SupplyKit** is prepared by a `CustodyOfficer` for an election, named by its `election_id`, with a `ballot_count` of at least one blank ballots sealed inside and a tamper-evident `seal_number`. Its `custody_state` begins at `PREPARED`, its `polling_place_id` is null until it is received at a place, and its `returned_ballot_count` is null until reconciled. Every custody change is recorded by appending an immutable **CustodyEvent**, which captures the `supply_kit_id`, the `event_type`, the `from_state` and `to_state` of the kit around the transition, the `actor_role` that performed it, and an optional free-text `note`. The valid custody transitions, each driven by the corresponding `event_type`, are:

- **ISSUE** (`PREPARED → ISSUED`): permitted only from `PREPARED`, and only if the election's `unallocated_ballot_stock` is greater than or equal to the kit's `ballot_count` (otherwise `ERR_INSUFFICIENT_BALLOT_STOCK`, 422). On issue, the election's `unallocated_ballot_stock` is decreased by `ballot_count`.
- **VOID_ISSUE** (`ISSUED → PREPARED`): the compensating reversal of an issue; the election's `unallocated_ballot_stock` is increased back by `ballot_count`.
- **DISPATCH** (`ISSUED → IN_TRANSIT`): send an issued kit toward its place.
- **RECEIVE** (`IN_TRANSIT → AT_PLACE`): the request must include a `polling_place_id` naming an existing place, which is stored on the kit; a receive without a `polling_place_id` is rejected as an invalid custody transition.
- **RETURN** (`AT_PLACE → RETURN_PENDING`): begin the return of a kit from its place.
- **RECONCILE** (`RETURN_PENDING → RECONCILED`): the request may supply a `returned_ballot_count`, which is stored on the kit (and stored as null when omitted); when present it must be a non-negative integer, otherwise the request is rejected with `ERR_INVALID_REQUEST` (422). `RECONCILED` is a terminal custody state.
- **SEAL_BREAK** (to `COMPROMISED`): permitted from any of `ISSUED`, `IN_TRANSIT`, or `AT_PLACE`. The kit's `custody_state` is set to `COMPROMISED`, and if the kit is stationed at a place (`polling_place_id` set) whose posture is `OPEN`, that place is forced `OPEN → SUSPENDED`.

Any `event_type` that is not defined from the kit's current `custody_state`, and any `RECEIVE` missing its `polling_place_id`, is rejected with `ERR_INVALID_CUSTODY_TRANSITION` (422). Every accepted custody event advances the kit's state, appends the audit record, and increments the kit's `version`. A compromised kit is precisely what blocks a place from opening or resuming, per the safety checks in Section 3.2.

### 3.7. Provisional Ballots and Adjudication

A **ProvisionalBallot** is cast at an open place by a `PrecinctCaptain` or `PollWorker`, supplying the `polling_place_id`, the `voter_name`, and the `reason` the ballot is provisional (for example, no identification or not in the pollbook). Casting requires the place's posture to be `OPEN`; casting at a place that is not open is rejected with `ERR_VOTING_NOT_OPEN` (409). A newly cast ballot's `status` begins at `CAST`, and the place's `provisional_cast_count` is incremented.

Adjudication, performed by a `PrecinctCaptain`, branches from `CAST`. Supplying a `decision` of ACCEPT advances the ballot `CAST → ACCEPTED` and increments the owning place's `provisional_accepted_count` by one. Supplying a `decision` of REJECT advances it `CAST → REJECTED` and, unlike acceptance, does not touch `provisional_accepted_count`. Both outcomes are terminal and increment the ballot's `version`. A `decision` that is neither valid value is rejected with `ERR_INVALID_REQUEST` (422), and an attempt to adjudicate a ballot that is not in `CAST` is rejected with `ERR_INVALID_STATE`.

### 3.8. Incidents and the Support Hotline

An **Incident** is opened via the support hotline by a `SupportAgent` or `PrecinctCaptain`, naming the affected `polling_place_id`, a `category` — one of `EQUIPMENT`, `STAFFING`, `SECURITY`, `ACCESSIBILITY`, or `OTHER` — a free-text `description`, and, only for equipment-related tickets, an `equipment_unit_id` (which defaults to null). A new incident starts with `severity` `LOW` and `status` `OPEN`, and its `resolution` is null.

A `SupportAgent` drives the incident lifecycle. Acknowledging takes it `OPEN → ACKNOWLEDGED`. Escalating takes it to `ESCALATED` from either `OPEN` or `ACKNOWLEDGED`, sets `severity` to `CRITICAL`, and — when the incident's `category` is `EQUIPMENT` and an `equipment_unit_id` is set — drives that equipment unit `OPERATIONAL → OUT_OF_SERVICE`, which in turn suspends the unit's owning place if it was open (the cascade of Section 2.5). Resolving takes the incident to `RESOLVED`, a terminal status, from either `ACKNOWLEDGED` or `ESCALATED`, and records the supplied `resolution`. Every incident transition increments the incident's `version`, and a transition attempted from a status where it is undefined is rejected with `ERR_INVALID_STATE`.

### 3.9. Results-Return Reconciliation

Closing out a place ends with reconciliation, run by the `PrecinctCaptain`. Reconcile is defined only when the place is `CLOSED` or already `RECONCILED` — the latter allowing a corrected results-return to legitimately supersede a prior one — and it is guarded by the optimistic concurrency check of Section 2.8: the request must carry `expected_polling_place_version` matching the place's current `version`, or it is rejected with `ERR_STALE_VERSION` (412). The request supplies `scanner_tally` (the machine-scanned ballot count), `epollbook_checkins` (the number of e-pollbook voter check-ins), an optional `spoiled_count`, an optional `explanation`, and the `expected_polling_place_version`. Any negative count is rejected with `ERR_INVALID_REQUEST` (422). On success the place's `scanner_tally`, `epollbook_checkins`, and `spoiled_count` are stored, the reconciliation figures are recomputed, `readiness_posture` becomes `RECONCILED`, and the place's `version` increments.

Reconciliation compares two tallies of the same place. The machine-only view counts only machine-scanned ballots, so its total is exactly `scanner_tally`. The reconciled inclusive view adds the place's live count of accepted provisional ballots, `provisional_accepted_count` (which are hand-counted separately), to `scanner_tally`; it therefore differs from the machine-only view by exactly `provisional_accepted_count`. It is this inclusive total that is compared against the electronic pollbook. Concretely, `reconciliation_discrepancy` is the sum of `scanner_tally` and `provisional_accepted_count`, minus `epollbook_checkins`. The `reconciliation_status` is `BALANCED` when `reconciliation_discrepancy` is exactly zero, and `MISMATCH` otherwise.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, custody-event appends, and clock control — return `200 OK`. (The custody-event endpoint creates a new custody record and returns `201 Created`.) All list and fetch reads return `200 OK`. "All roles" below denotes every authenticated role: `ElectionAdmin`, `PrecinctCaptain`, `PollWorker`, `CustodyOfficer`, and `SupportAgent`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | ElectionAdmin |
| POST | `/elections` | Create an election | ElectionAdmin |
| GET | `/elections/{id}` | Fetch an election | All roles |
| POST | `/elections/{id}/open-voting` | Open the election-day voting window | ElectionAdmin |
| POST | `/elections/{id}/close-voting` | Close voting; cascades place close → shift check-out → payroll | ElectionAdmin |
| POST | `/polling-places` | Create a polling place under an election | ElectionAdmin |
| GET | `/polling-places/{id}` | Fetch a polling place | All roles |
| GET | `/polling-places` | List polling places; filterable by election | All roles |
| POST | `/polling-places/{id}/open` | Open the place for voting | PrecinctCaptain |
| POST | `/polling-places/{id}/suspend` | Suspend an open place | PrecinctCaptain |
| POST | `/polling-places/{id}/resume` | Resume a suspended place | PrecinctCaptain |
| POST | `/polling-places/{id}/close` | Close the place; auto checks-out active shifts | PrecinctCaptain |
| POST | `/polling-places/{id}/reconcile` | Submit results-return reconciliation (re-runnable, OCC-guarded) | PrecinctCaptain |
| POST | `/equipment` | Create an equipment unit in the warehouse | ElectionAdmin |
| GET | `/equipment/{id}` | Fetch an equipment unit | All roles |
| GET | `/equipment` | List equipment; filterable by polling place | All roles |
| POST | `/equipment/{id}/deploy` | Deploy warehouse equipment to a polling place | ElectionAdmin |
| POST | `/poll-workers` | Recruit a poll worker | ElectionAdmin |
| GET | `/poll-workers/{id}` | Fetch a poll worker with payroll accrual | All roles |
| POST | `/poll-workers/{id}/complete-training` | Mark a worker CERTIFIED after training | ElectionAdmin |
| POST | `/assignments` | Propose assigning a worker to a place | PrecinctCaptain, ElectionAdmin |
| GET | `/assignments/{id}` | Fetch an assignment | All roles |
| GET | `/assignments` | List assignments; filterable by worker and/or place | All roles |
| POST | `/assignments/{id}/activate` | Activate an assignment (fills a staffing slot) | PrecinctCaptain, ElectionAdmin |
| POST | `/assignments/{id}/withdraw` | Withdraw an assignment (releases a slot if ACTIVE) | PrecinctCaptain, ElectionAdmin |
| POST | `/shifts` | Schedule a shift for an active assignment | PrecinctCaptain, ElectionAdmin |
| GET | `/shifts/{id}` | Fetch a shift with computed hours and pay | All roles |
| GET | `/shifts` | List shifts; filterable by assignment, worker, and/or place | All roles |
| POST | `/shifts/{id}/check-in` | Check a worker into a shift (stamps clock) | PrecinctCaptain, PollWorker |
| POST | `/shifts/{id}/check-out` | Check a worker out; computes pay and accrues payroll | PrecinctCaptain, PollWorker |
| POST | `/supply-kits` | Prepare a supply kit for an election | CustodyOfficer |
| GET | `/supply-kits/{id}` | Fetch a supply kit with custody state | All roles |
| GET | `/supply-kits` | List supply kits; filterable by election and/or place | All roles |
| POST | `/supply-kits/{id}/custody-events` | Record a chain-of-custody transition; appends an immutable event | CustodyOfficer |
| GET | `/supply-kits/{id}/custody-events` | List the chain-of-custody audit log for a kit | All roles |
| POST | `/provisional-ballots` | Cast a provisional ballot at an open place | PrecinctCaptain, PollWorker |
| GET | `/provisional-ballots/{id}` | Fetch a provisional ballot | All roles |
| GET | `/provisional-ballots` | List provisional ballots; filterable by place | All roles |
| POST | `/provisional-ballots/{id}/adjudicate` | Adjudicate a provisional ballot (accept or reject) | PrecinctCaptain |
| POST | `/incidents` | Open an incident / support-hotline ticket | SupportAgent, PrecinctCaptain |
| GET | `/incidents/{id}` | Fetch an incident | All roles |
| GET | `/incidents` | List incidents; filterable by place and/or equipment | All roles |
| POST | `/incidents/{id}/acknowledge` | Acknowledge an open incident | SupportAgent |
| POST | `/incidents/{id}/escalate` | Escalate an incident to CRITICAL; equipment cascade | SupportAgent |
| POST | `/incidents/{id}/resolve` | Resolve an incident | SupportAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VOTING_NOT_OPEN` | 409 |
| `ERR_KIT_COMPROMISED` | 409 |
| `ERR_EQUIPMENT_NOT_OPERATIONAL` | 409 |
| `ERR_WORKER_NOT_CERTIFIED` | 422 |
| `ERR_WORKER_SHIFT_OVERLAP` | 409 |
| `ERR_PLACE_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVALID_CUSTODY_TRANSITION` | 422 |
| `ERR_INSUFFICIENT_BALLOT_STOCK` | 422 |
| `ERR_UNDERSTAFFED` | 422 |
| `ERR_NO_OPEN_SLOTS` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
