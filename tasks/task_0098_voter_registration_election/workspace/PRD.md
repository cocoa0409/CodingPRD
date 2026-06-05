# Voter Registration & Election Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Voter Registration & Election Management API, a system that administers the full arc of an election: from opening registration and adjudicating voter eligibility, through precinct assignment, absentee balloting, signature curing, early voting, and polling-place machine operations, to the closing of polls and the certification of results. The system is built for an environment where correctness is paramount and where every consequential action must be attributable, ordered, and reversible only under tightly controlled conditions.

Two governing concerns shape the design. The first is **compliance and auditability**: eligibility gates (citizenship, age, residency), deadline windows, and separation-of-duties controls must be enforced uniformly, and the consequences of each action must cascade predictably across the registrations, ballots, precincts, machines, and recounts that link to one another. The second is **allocation under capacity**: voters are assigned to precincts that have finite room, and a failed voting machine must be covered — if possible — by an idle backup chosen deterministically. Because election operations are inherently concurrent, the system relies on a simulated clock for all deadline arithmetic and on optimistic concurrency control to reject writes founded on a stale view of a registration or a machine.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `ElectionAdmin`, `ElectionOfficial`, `Voter`, `PollWorker`, and `Canvasser`.

Four of these roles carry an opaque identity. When `X-User-Role` is `ElectionAdmin`, `ElectionOfficial`, `PollWorker`, or `Canvasser`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id`. It does, however, record it where a workflow demands attribution: the `Canvasser` who records a precinct tally is written to that precinct's `tally_recorded_by_user_id`, the `ElectionOfficial` who last approves or rejects a registration is written to that registration's `reviewed_by_user_id`, and the `ElectionOfficial` who adjudicates a cure is written to that cure case's `adjudicated_by_user_id`. These recorded identifiers later drive the separation-of-duties checks described in §3.

The fifth role, `Voter`, is entity-backed by a registration. When `X-User-Role` is `Voter`, `X-User-ID` is the `id` of a `VoterRegistration` the voter owns; any ownership check on a resource that references a registration compares that resource's registration foreign key to `X-User-ID`. A `Voter` may self-submit a registration, request an absentee ballot against their own registration, submit a cure response on their own ballot's cure case, and read their own registration, ballots, and cure cases.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must lie between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all lists are sorted by `created_at` in ascending order — oldest first.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Simulated Clock

Most resources in the system are full audit-bearing entities and expose a common set of system-managed fields. Each carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking creation, an `updated_at` timestamp in the same format marking the last modification, and a `version` integer that begins at its initial value and increments by one on every mutation. Elections, precincts, voter registrations, absentee ballots, cure cases, voting machines, and recount cases all carry this full set.

Two entities are deliberately lightweight and immutable after creation: a `MachineFailure` record and an `EarlyVoteCheckIn` record carry only an `id` and a `created_at`. Neither has an `updated_at` field and neither has a `version` field, because once written they are never modified. The `ClockState` is likewise a singleton holding only `current_utc`.

All deadline and window comparisons in the system are made against a **simulated clock** rather than wall-clock time. The clock exposes a single field, `current_utc`, and an `ElectionAdmin` may set it to any instant for test-driving purposes; this capability supplies a `current_utc` value and overwrites the stored clock. Every temporal precondition described in §3 — registration deadlines, absentee request deadlines, cure deadlines, and early-voting windows — is evaluated against this `current_utc`.

### 2.5. Mutation, Cascade, and Hierarchical Consistency

Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` increments by one. This holds for recomputations of derived fields as much as for direct state changes: when a precinct's `assigned_count` and `capacity_posture` are recomputed, or an election's `total_registered` or `total_ballots_accepted` is recomputed, the affected entity's `version` advances.

Several operations mutate more than one entity. The system applies all such secondary effects atomically with the primary action, and each affected entity independently advances its own `version`. The most consequential cascades — the cure sweep at poll close, the depth-three rejection chain when a cure fails, the precinct ledger adjustments on approval and withdrawal, and the recount write-back to a precinct's reported count — are described in full within the relevant workflow in §3. The governing rule is that no derived field is ever left inconsistent with the rows it summarizes once an operation completes.

### 2.6. Left-to-Right Existence Validation

When a request references resources — whether through an identifier in the URL path or through a foreign-key field in the body — the system validates their existence in left-to-right order: path identifiers first, then body references in the order they appear. The first reference that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`, before any state, eligibility, or capacity logic runs. A request that names a non-existent election, precinct, registration, ballot, cure case, machine, or recount therefore fails at the existence stage regardless of any later condition it might also violate.

### 2.7. Numeric Precision and Rounding

All percentage and vote calculations follow fixed precision rules. Turnout percentages are reported to exactly two decimal places using the round-half-up convention. Vote counts and the discrepancy comparisons used in recount certification are whole integers. Ages are computed as whole completed years. Where a turnout denominator is zero, the reported percentage is exactly `0.00` rather than an error or an undefined value.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent entity, and each carries a mandatory version field.

A request to create an absentee ballot must include `expected_registration_version`, carrying the `version` of the target `VoterRegistration` as the client last observed it. If that value does not match the registration's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against a writer whose view predates, for example, a withdrawal that released the registration's precinct headroom and now forbids further ballot requests. A successful create advances the registration's `version` by one, so a second create founded on the same stale view will itself be rejected.

A request to report a machine failure must include `expected_machine_version`, carrying the `version` of the target `VotingMachine` as the client last observed it. If that value does not match the machine's current `version`, the report is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against a writer whose view predates an earlier failure report that already drove the machine out of `OPERATIONAL` and triggered backup activation.

No other endpoint takes a version field; operations not named here perform no OCC check.

### 2.9. Order of Validation

When several conditions could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then the existence of every referenced resource (`ERR_NOT_FOUND`), then whether the target resource is in a legal state for the requested transition (`ERR_INVALID_STATE`). Only after these does the system evaluate separation-of-duties (`ERR_SEGREGATION_OF_DUTIES`), then the general time-window checks (`ERR_WINDOW_CLOSED`), then the cure-specific deadline check (`ERR_CURE_DEADLINE_PASSED`).

Business-constraint checks follow in this order: citizenship (`ERR_NOT_CITIZEN`), then age (`ERR_UNDERAGE`), then residency match (`ERR_NO_PRECINCT_MATCH`), then whether a referenced registration is active (`ERR_REGISTRATION_NOT_ACTIVE`), then the accept-time cure guard (`ERR_BALLOT_NOT_CURED`), then registration uniqueness (`ERR_DUPLICATE_REGISTRATION`), then the double-vote guard (`ERR_ALREADY_VOTED`), then the withdraw guard (`ERR_BALLOT_BLOCKS_WITHDRAW`), then the recount precondition (`ERR_PRECINCT_NOT_TALLIED`), then the machine-retire guard (`ERR_BACKUP_IN_USE`), and then precinct capacity (`ERR_PRECINCT_FULL`). The OCC stale-version check (`ERR_STALE_VERSION`) is evaluated next, and finally generic body-shape validation (`ERR_INVALID_REQUEST`) — required fields present, enum values in range, and numeric constraints such as `max_registrations` being at least 1 and `street_high` being at least `street_low`. The practical consequence is that, for registration approval, residency is always checked before capacity: a voter with no covering precinct receives `ERR_NO_PRECINCT_MATCH`, never `ERR_PRECINCT_FULL`.

## 3. Business Logic & Workflows

### 3.1. Configuring an Election and Its Precincts

An `ElectionAdmin` opens the process by creating an **Election**, supplying its `name`, the `election_date` at which polls close, the `registration_deadline` after which no registration may be approved, the `absentee_request_deadline` after which absentee requests are refused, the `cure_deadline` at or after which a flagged ballot can no longer be cured, and the early-voting window bounded by `early_voting_start` (inclusive) and `early_voting_end` (exclusive). A new election begins with its `status` field set to `SCHEDULED`. It also carries computed reporting fields — `total_registered`, `total_ballots_accepted`, `turnout_pct`, and `projected_turnout_pct` — described in §3.8. The lifecycle `status` field is the standard name for the single-dimension state of an election, a voter registration, a cure case, a voting machine, and a recount case alike, and list endpoints that accept a `status` filter narrow their results to resources whose `status` equals the supplied value.

The election advances through its lifecycle by admin-driven transitions, each supplying a `target_status`. Opening registration moves it `SCHEDULED → REGISTRATION_OPEN`. Opening voting moves it `REGISTRATION_OPEN → VOTING_OPEN`, but only once the simulated clock has reached or passed `early_voting_start`; an attempt before that instant is refused with `ERR_VOTING_NOT_OPEN`. Closing the polls moves it `VOTING_OPEN → POLLS_CLOSED`, permitted only once the clock has reached or passed `election_date`; an attempt before that instant is likewise refused with `ERR_VOTING_NOT_OPEN`. The final transition `POLLS_CLOSED → CERTIFIED` is the terminal state and is gated by two conditions beyond being in `POLLS_CLOSED`: every precinct of the election must have a tally status of `TALLIED` (otherwise `ERR_PRECINCTS_NOT_TALLIED`), and no recount case of the election may still be in any of `REQUESTED`, `MACHINE_DONE`, `HAND_DONE`, or `BOTH_DONE` (otherwise `ERR_RECOUNT_IN_PROGRESS`). Any of these transitions attempted from the wrong current status is refused with `ERR_INVALID_STATE`. Each successful transition increments the election's `version`.

The close-polls transition additionally runs the **cure sweep**, detailed in §3.5. An `ElectionAdmin` defines the geography of an election by creating **Precincts** under it. A precinct is created with its parent `election_id`, a `code` unique within that election (so the pair of election and `code` may not repeat), a 5-digit `county_fips` used for residency matching, the inclusive residential street-number range `street_low` through `street_high` it covers, and a `max_registrations` hard cap. The cap must be at least 1, and `street_high` must be at least `street_low`; violating either yields `ERR_INVALID_REQUEST`. Each precinct exposes a computed `assigned_count` (the number of active registrations assigned to it) and a computed `capacity_posture`, which reads `OPEN` while `assigned_count` is below `max_registrations` and `FULL` once `assigned_count` reaches or exceeds it. A precinct also tracks a `tally_status` that begins at `PENDING`, a `reported_vote_count` that stays null until the tally is recorded, and a `tally_recorded_by_user_id` that stays null until then.

### 3.2. Registering and Approving Voters

A registration enters the system when an `ElectionOfficial` or a self-submitting `Voter` creates a **VoterRegistration**. The submission supplies the `election_id` it belongs to, the registrant's `first_name`, `last_name`, and `national_id`, the self-attested citizenship flag `is_citizen`, the `date_of_birth`, the residential `county_fips` and `street_number`, and optionally a `party`. The `party` is one of `DEMOCRAT`, `REPUBLICAN`, `INDEPENDENT`, `GREEN`, `LIBERTARIAN`, or `UNAFFILIATED`, defaulting to `UNAFFILIATED` when omitted. A new registration starts in `PENDING` status with a null `precinct_id`, a null `early_voted_at`, and a null `reviewed_by_user_id`. At creation the system rejects a duplicate: if any other registration for the same election shares the same `national_id` and sits in `PENDING`, `NEEDS_REVIEW`, or `ACTIVE`, the create fails with `ERR_DUPLICATE_REGISTRATION` (a previously `REJECTED` or `WITHDRAWN` registration does not block a fresh one).

Approval is the pivotal step, performed by an `ElectionOfficial`, and it drives `PENDING → ACTIVE`. Approval is admissible only while the registration is `PENDING`, the election is in `REGISTRATION_OPEN`, and the simulated clock is strictly before the election's `registration_deadline`; a clock at or past that deadline yields `ERR_WINDOW_CLOSED`. The eligibility gate then runs in order. Citizenship is checked first: the `is_citizen` flag must be true, or the request is rejected with `ERR_NOT_CITIZEN`. Age is checked next, using the **completed-years rule** described in §3.9, and must be at least the voting age, or the request is rejected with `ERR_UNDERAGE`. Residency follows: at least one precinct of the election must cover the voter (see the precinct selector in §3.9), failing which the request is rejected with `ERR_NO_PRECINCT_MATCH`. Only after a covering precinct is found does capacity apply: the selected precinct must be `OPEN`, failing which the request is rejected with `ERR_PRECINCT_FULL`.

On a successful approval, the system runs the precinct selector and writes the chosen precinct's identity into the registration's `precinct_id`, sets `reviewed_by_user_id` to the acting `X-User-ID`, increments that precinct's `assigned_count` by one and recomputes its `capacity_posture`, recomputes the election's `total_registered`, and increments the registration's `version`. Note the recorded reviewer identity becomes a separation-of-duties key later applied to that voter's ballot curing.

Registrations that are not yet approvable move through the non-approval transitions, each supplying a `target_status`. An official may send a `PENDING` registration to `NEEDS_REVIEW` and may send a `NEEDS_REVIEW` registration back to `PENDING`; on that return-to-pending resubmit, any corrected `county_fips`, `street_number`, or `is_citizen` value present in the payload is applied to the record. A registration in either `PENDING` or `NEEDS_REVIEW` may be sent to `REJECTED`, which also records the acting `X-User-ID` as `reviewed_by_user_id`. Each such transition is admissible only from its stated source status (otherwise `ERR_INVALID_STATE`) and increments the registration's `version`.

Withdrawal applies only to an `ACTIVE` registration and moves it `ACTIVE → WITHDRAWN`, but it is blocked when the voter holds an absentee ballot in flight — that is, when any absentee ballot for the registration has a request status of `ISSUED`, `RETURNED`, or `ACCEPTED` — in which case the request is refused with `ERR_BALLOT_BLOCKS_WITHDRAW`. A permitted withdrawal is a compensating action: it decrements the assigned precinct's `assigned_count` by one and recomputes that precinct's `capacity_posture`, recomputes the election's `total_registered`, and increments the registration's `version`.

### 3.3. Absentee Ballots

A voter who is registered and active may obtain an **AbsenteeBallot**, requested by an `ElectionOfficial` or by the owning `Voter`. The request supplies the `registration_id` it is for, the `mailing_address` the ballot is sent to, and the `expected_registration_version` for the optimistic-concurrency check described in §2.8. The referenced registration must be `ACTIVE`, or the request is refused with `ERR_REGISTRATION_NOT_ACTIVE`, and the simulated clock must be before the election's `absentee_request_deadline`, or it is refused with `ERR_WINDOW_CLOSED`. On creation the ballot copies its `election_id` and `precinct_id` from the registration, begins with a request status of `REQUESTED` and a cure status of `NONE`, and carries a null `returned_at`. The act of creating the ballot advances the parent registration's `version` by one, which is what makes a subsequent stale-version request fail.

Each absentee ballot evolves along two independent dimensions on the same record: a **request dimension** (`request_status`, the logistics of issuing, returning, and accepting) and a **cure dimension** (`cure_status`, the signature-adjudication track driven by a cure case). The request dimension is driven by an `ElectionOfficial` supplying a `target_request_status`. Issuing moves the request `REQUESTED → ISSUED`, permitted only while the linked registration is `ACTIVE`. Returning moves it `ISSUED → RETURNED`, permitted only while the clock is before the election's `election_date`, and it stamps `returned_at` with the current clock instant. Accepting moves it `RETURNED → ACCEPTED`, but only when the cure status is either `NONE` or `CURED`; a ballot whose cure status is `FLAGGED`, `CURE_PENDING`, or `CURE_FAILED` is blocked from acceptance with `ERR_BALLOT_NOT_CURED`. Acceptance recomputes the election's `total_ballots_accepted`. Every one of these request transitions is admissible only from its stated source status (otherwise `ERR_INVALID_STATE`) and increments the ballot's `version`.

The cure dimension begins when an `ElectionOfficial` flags a returned ballot. Flagging requires the request status to be `RETURNED` and the cure status to be `NONE`; it supplies a `reason` (one of `SIGNATURE_MISMATCH`, `MISSING_SIGNATURE`, or `MISSING_WITNESS`), moves the cure status `NONE → FLAGGED`, opens a cure case for the ballot, and increments the ballot's `version`. The remaining cure-status movements are not invoked directly; they are driven as cross-aggregate side effects of the cure case described in §3.4. When a cure case first receives a voter response, the ballot's cure status advances `FLAGGED → CURE_PENDING`. When a cure case is approved, the ballot's cure status advances `CURE_PENDING → CURED`. When a cure case is denied or expires, the ballot's cure status advances `CURE_PENDING → CURE_FAILED`, and — this is the consequential cascade — that failure itself sets the ballot's request status to `REJECTED`. Each such system-driven cure-status change increments the ballot's `version`.

### 3.4. Curing a Flagged Ballot

Flagging a ballot opens a **CureCase** in `OPEN` status. The case records the `ballot_id` under cure, copies the `election_id` from that ballot (which is what binds it to the governing `cure_deadline`), carries the flag `reason` forwarded from the flagging step, holds a null `voter_response_text` until the voter responds, and holds a null `adjudicated_by_user_id` until it is decided.

The case progresses by a `decision` supplied on each transition. The voter (or an `ElectionOfficial` acting for them) submits a response with the `decision` value `SUBMIT_RESPONSE`, which is admissible only while the case is `OPEN` and the clock is before the election's `cure_deadline`. This submission writes the supplied `voter_response_text`, moves the case `OPEN → RESPONSE_SUBMITTED`, and as its cross-aggregate effect advances the linked ballot's cure status `FLAGGED → CURE_PENDING`. A submission at or after the cure deadline is refused with `ERR_CURE_DEADLINE_PASSED`.

Adjudication is performed by an `ElectionOfficial` on a case in `RESPONSE_SUBMITTED`. Approving with the `decision` value `APPROVE` is admissible only while the clock is before the `cure_deadline` (otherwise `ERR_CURE_DEADLINE_PASSED`) and only when the acting `X-User-ID` differs from the `reviewed_by_user_id` recorded on the ballot's underlying registration — the official who reviewed the registration may not adjudicate that voter's cure, and a self-adjudication is refused with `ERR_SEGREGATION_OF_DUTIES`. Approval records the acting `X-User-ID` as `adjudicated_by_user_id`, moves the case `RESPONSE_SUBMITTED → APPROVED`, and advances the linked ballot's cure status `CURE_PENDING → CURED`. Denying with the `decision` value `DENY` is subject to the same separation-of-duties check (and the same `ERR_SEGREGATION_OF_DUTIES` on violation), records `adjudicated_by_user_id`, moves the case `RESPONSE_SUBMITTED → DENIED`, and triggers the depth-three cascade: the linked ballot's cure status advances `CURE_PENDING → CURE_FAILED`, which itself sets that ballot's request status to `REJECTED`. Each cure-case decision increments the cure case's `version`.

A cure case may also reach the terminal `EXPIRED` state, but only through the system-driven sweep described next, never by a client request.

### 3.5. Closing the Polls and the Cure Sweep

The close-polls transition (`VOTING_OPEN → POLLS_CLOSED`) carries a system-driven cure sweep as its side effect. The sweep examines every cure case of the election that is still in `OPEN` or `RESPONSE_SUBMITTED` and whose governing window has lapsed — that is, where the simulated clock has reached or passed the election's `cure_deadline`. Each such case is moved to `EXPIRED`. Expiry is not silent: an expired case advances its linked ballot's cure status to `CURE_FAILED`, which in turn sets that ballot's request status to `REJECTED` — the same depth-three cascade a denial produces. Every cure case touched by the sweep increments its own `version`, every affected ballot increments its `version`, and the election itself increments its `version` on the transition. The cure window is governed by a strict comparison: while the clock is before the `cure_deadline` the window is open, and exactly at the `cure_deadline` it is already closed.

### 3.6. Polling-Place Machines and Failure Backup

An `ElectionAdmin` registers a **VotingMachine** at a precinct, supplying the `precinct_id`, a `serial` unique within that precinct (the pair of precinct and `serial` may not repeat), an optional `role` of `PRIMARY` or `BACKUP` defaulting to `PRIMARY`, and a `capacity` (voters processed per hour, at least 1). A machine begins `OPERATIONAL` with a null `backup_for_machine_id`. `PRIMARY` machines serve voters; `BACKUP` machines sit idle until activated to cover a failure.

When a machine breaks down, a `PollWorker` reports it, supplying the failed `machine_id` and the `expected_machine_version` for the optimistic-concurrency check in §2.8. A failure may only be reported against a machine that is currently `OPERATIONAL` and whose role is `PRIMARY`. Reporting the failure records a **MachineFailure** row carrying the `machine_id`, the server-clock `reported_at` instant, a `backup_machine_id`, and a `resolution`. It moves the primary machine `OPERATIONAL → FAILED` and runs the backup selector (see §3.9) over the idle backups in that precinct. If a backup is chosen, the selector sets that backup's `backup_for_machine_id` to the failed machine's identity, records the chosen machine in the failure's `backup_machine_id`, and sets the failure's `resolution` to `BACKUP_ACTIVATED`. If no backup is available, the failure is still recorded with a null `backup_machine_id` and a `resolution` of `NO_BACKUP_AVAILABLE` — the absence of a backup is an outcome, not an error. The failed machine's `version` increments.

A failed machine is handled through the machine lifecycle transitions, each driven by a `target_status`. A `PollWorker` repairs a failed machine back to service, moving it `FAILED → OPERATIONAL`; as a compensating action, if some backup is currently covering this machine (its `backup_for_machine_id` points at this machine), that backup's `backup_for_machine_id` is cleared, releasing it to idle. Alternatively a `PollWorker` may move a failed machine `FAILED → REPLACED`. A machine in any of `OPERATIONAL`, `FAILED`, or `REPLACED` may be retired to the terminal `RETIRED` state by either a `PollWorker` or an `ElectionAdmin`, but retirement is blocked while the machine is still serving as the active backup of a machine that remains `FAILED`; such an attempt is refused with `ERR_BACKUP_IN_USE`. Each machine lifecycle transition is admissible only from a legal source status (otherwise `ERR_INVALID_STATE`) and increments the machine's `version`.

### 3.7. Early Voting

During the early-voting window, a `PollWorker` records an in-person **EarlyVoteCheckIn** for a registered voter, supplying the voter's `registration_id`. The check-in is admissible only while the referenced registration is `ACTIVE` (otherwise `ERR_REGISTRATION_NOT_ACTIVE`) and only while the simulated clock falls within the window — at or after `early_voting_start` and strictly before `early_voting_end` — failing which it is refused with `ERR_WINDOW_CLOSED`. The system also enforces a double-vote guard: the voter must have no prior early-vote instant recorded and no absentee ballot whose request status is `ISSUED`, `RETURNED`, or `ACCEPTED`; otherwise the check-in is refused with `ERR_ALREADY_VOTED`. A successful check-in copies the `precinct_id` from the registration, stamps the check-in's `checked_in_at` with the current clock instant, and stamps the registration's `early_voted_at` with the same instant.

### 3.8. Tallies, Recounts, and Turnout Reporting

A `Canvasser` records a precinct's in-person results, supplying the `reported_vote_count`. Recording the tally moves the precinct's tally status `PENDING → TALLIED`, writes the supplied count into `reported_vote_count`, records the acting `X-User-ID` into `tally_recorded_by_user_id` (the separation key for any later recount), and increments the precinct's `version`.

A recount runs against a single tallied precinct. An `ElectionAdmin` opens a **RecountCase** by supplying the `election_id` and the `precinct_id`; the precinct must already be `TALLIED`, or the open is refused with `ERR_PRECINCT_NOT_TALLIED`. Opening the case snapshots the precinct's current `reported_vote_count` into the recount's `original_count`, sets `machine_recount` and `hand_recount` to null, sets `certified_count` to null, and starts the case in `REQUESTED`. A recount proceeds by a **fork-join over two tally passes**, each submitted by a `Canvasser` who supplies the `pass` (`MACHINE` or `HAND`) and the `count`. Every pass submission requires that the acting `X-User-ID` differ from the precinct's `tally_recorded_by_user_id` — a canvasser may not recount a precinct whose original tally they recorded — and a violation is refused with `ERR_SEGREGATION_OF_DUTIES`.

The two passes are symmetric and independent. From `REQUESTED`, a machine pass writes `machine_recount` and moves the case to `MACHINE_DONE`, while a hand pass writes `hand_recount` and moves it to `HAND_DONE`. From `MACHINE_DONE`, a hand pass writes `hand_recount` and joins to `BOTH_DONE`; from `HAND_DONE`, a machine pass writes `machine_recount` and joins to `BOTH_DONE`. A pass that does not match a legal source status is refused with `ERR_INVALID_STATE`, and every pass increments the recount's `version`. Once both passes are in, an `ElectionAdmin` resolves the case on one of two divergent branches via a `target_status`. Certifying moves it `BOTH_DONE → CERTIFIED`, runs the recount-certification calculation in §3.9 to set `certified_count`, and writes that certified count back into the precinct's `reported_vote_count` — the recount's verdict supersedes the original tally. Dismissing may be applied from any of `REQUESTED`, `MACHINE_DONE`, `HAND_DONE`, or `BOTH_DONE`, moving the case to the terminal `DISMISSED` and leaving the precinct's count at its `original_count` unchanged. Each resolution increments the recount's `version`.

An election surfaces four computed reporting fields, recomputed whenever a ballot transition or an early-vote check-in changes the underlying data. The denominator throughout is `total_registered`, the count of the election's registrations whose status is `ACTIVE`. The numerator combines two sources: the in-person early voters (the distinct registrations of the election that have a non-null `early_voted_at`) and a count of absentee ballots. The **final** turnout, reported as `turnout_pct`, counts only absentee ballots whose request status is `ACCEPTED`. The **projected** turnout, reported as `projected_turnout_pct`, counts absentee ballots whose request status is `RETURNED` or `ACCEPTED` — that is, ballots physically in hand even if not yet adjudicated — so for identical data the projected figure is at least as large as the final figure whenever any ballot is returned but not yet accepted. Each percentage is the relevant cast count divided by `total_registered`, multiplied by 100, rounded half-up to two decimal places. The separately reported `total_ballots_accepted` is the count of the election's absentee ballots whose request status is `ACCEPTED`. When `total_registered` is zero, both `turnout_pct` and `projected_turnout_pct` are reported as `0.00` and no division is attempted.

### 3.9. Deterministic Selectors and Calculations

**Age eligibility.** A voter's age is the count of full birthdays falling on or before the election's `election_date`, computed by calendar arithmetic rather than by dividing elapsed days. Take the difference between the election year and the birth year, and subtract one if the election's month-and-day falls before the birthday's month-and-day. The resulting whole-year age must be at least the voting age of 18 for the voter to be eligible. The as-of instant for this calculation is always the election's `election_date`, not the simulated clock. A voter whose eighteenth birthday falls exactly on the election date is eligible (their month and day equal the election's, so no year is subtracted); a voter whose birthday is one day later computes to 17 and is not.

**Precinct selection.** When a registration is approved, the selector considers the precincts of the registration's election that match on `county_fips`, that cover the voter's `street_number` within their inclusive `street_low`-through-`street_high` range, and that are currently `OPEN`. Among these candidates it ranks by `assigned_count` ascending — filling the emptiest precinct first — breaking ties by `max_registrations` descending (the precinct with the most headroom), and breaking remaining ties by `created_at` ascending (the oldest precinct). The first candidate after this ordering is selected. If no precinct of the election matches the county-and-street filter at all, approval fails with `ERR_NO_PRECINCT_MATCH`; if precincts match the filter but every one of them is `FULL`, approval fails with `ERR_PRECINCT_FULL`.

**Backup selection.** When a primary machine fails, the selector considers the voting machines in the failed machine's precinct whose role is `BACKUP`, whose status is `OPERATIONAL`, and whose `backup_for_machine_id` is null (idle). It ranks them by `capacity` descending — activating the highest-throughput backup first — breaking ties by `created_at` ascending (the oldest backup). The first candidate after this ordering is activated. If there are no idle operational backups, the outcome is `NO_BACKUP_AVAILABLE` and no error is raised; the failure row is recorded regardless.

**Recount certification.** When a recount is certified, the system compares its two passes. Compute the absolute difference between `machine_recount` and `hand_recount`. If that difference is at most the discrepancy tolerance of 5 votes, the hand count governs and `certified_count` is set to `hand_recount`. If the difference exceeds 5 votes, the system takes the conservative lower of the two and sets `certified_count` to the smaller of `machine_recount` and `hand_recount`. A difference of exactly 5 is within tolerance, so the hand count governs at the boundary.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and recorded actions — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/elections` | Create an election | ElectionAdmin |
| GET | `/elections/{id}` | Fetch one election (with computed turnout fields) | ElectionAdmin, ElectionOfficial, Canvasser, PollWorker |
| GET | `/elections` | List elections | ElectionAdmin, ElectionOfficial, Canvasser, PollWorker |
| POST | `/elections/{id}/transition` | Drive the election lifecycle; close-polls runs the cure sweep | ElectionAdmin |
| POST | `/precincts` | Create a precinct under an election | ElectionAdmin |
| GET | `/precincts/{id}` | Fetch one precinct | ElectionAdmin, ElectionOfficial, Canvasser, PollWorker |
| GET | `/precincts` | List precincts | ElectionAdmin, ElectionOfficial, Canvasser, PollWorker |
| POST | `/precincts/{id}/tally` | Record the precinct's in-person tally | Canvasser |
| POST | `/registrations` | Submit a voter registration | ElectionOfficial, Voter |
| GET | `/registrations/{id}` | Fetch one registration | ElectionAdmin, ElectionOfficial, Voter |
| GET | `/registrations` | List registrations | ElectionAdmin, ElectionOfficial |
| POST | `/registrations/{id}/approve` | Eligibility + capacity gate; assigns a precinct | ElectionOfficial |
| POST | `/registrations/{id}/transition` | Non-approval registration transitions | ElectionOfficial |
| POST | `/absentee-ballots` | Request an absentee ballot (OCC on the registration) | ElectionOfficial, Voter |
| GET | `/absentee-ballots/{id}` | Fetch one absentee ballot | ElectionAdmin, ElectionOfficial, Voter |
| GET | `/absentee-ballots` | List absentee ballots | ElectionAdmin, ElectionOfficial |
| POST | `/absentee-ballots/{id}/transition` | Request-dimension transitions (issue/return/accept) | ElectionOfficial |
| POST | `/absentee-ballots/{id}/flag-cure` | Flag a returned ballot and open a cure case | ElectionOfficial |
| GET | `/cure-cases/{id}` | Fetch one cure case | ElectionAdmin, ElectionOfficial, Voter |
| GET | `/cure-cases` | List cure cases | ElectionAdmin, ElectionOfficial |
| POST | `/cure-cases/{id}/transition` | Cure decisions (submit response / approve / deny) | Voter, ElectionOfficial |
| POST | `/voting-machines` | Register a voting machine at a precinct | ElectionAdmin |
| GET | `/voting-machines/{id}` | Fetch one voting machine | ElectionAdmin, PollWorker |
| GET | `/voting-machines` | List voting machines | ElectionAdmin, PollWorker |
| POST | `/voting-machines/{id}/transition` | Machine lifecycle (repair / replace / retire) | PollWorker, ElectionAdmin |
| POST | `/machine-failures` | Report a primary machine failure (OCC on the machine) | PollWorker |
| GET | `/machine-failures/{id}` | Fetch one machine failure | ElectionAdmin, PollWorker |
| GET | `/machine-failures` | List machine failures | ElectionAdmin, PollWorker |
| POST | `/early-vote-checkins` | Record an in-person early vote | PollWorker |
| GET | `/early-vote-checkins/{id}` | Fetch one early-vote check-in | ElectionAdmin, Canvasser, PollWorker |
| GET | `/early-vote-checkins` | List early-vote check-ins | ElectionAdmin, Canvasser, PollWorker |
| POST | `/recount-cases` | Open a recount on a tallied precinct | ElectionAdmin |
| GET | `/recount-cases/{id}` | Fetch one recount case | ElectionAdmin, Canvasser |
| GET | `/recount-cases` | List recount cases | ElectionAdmin, Canvasser |
| POST | `/recount-cases/{id}/submit-pass` | Record a recount pass (machine or hand) | Canvasser |
| POST | `/recount-cases/{id}/transition` | Recount join branch (certify / dismiss) | ElectionAdmin |
| POST | `/_clock/set` | Test-driving: set the simulated server clock | ElectionAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_CLOSED` | 422 |
| `ERR_CURE_DEADLINE_PASSED` | 422 |
| `ERR_NOT_CITIZEN` | 422 |
| `ERR_UNDERAGE` | 422 |
| `ERR_NO_PRECINCT_MATCH` | 422 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_PRECINCT_FULL` | 409 |
| `ERR_ALREADY_VOTED` | 409 |
| `ERR_REGISTRATION_NOT_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_BALLOT_NOT_CURED` | 409 |
| `ERR_BALLOT_BLOCKS_WITHDRAW` | 409 |
| `ERR_PRECINCT_NOT_TALLIED` | 409 |
| `ERR_PRECINCTS_NOT_TALLIED` | 409 |
| `ERR_RECOUNT_IN_PROGRESS` | 409 |
| `ERR_VOTING_NOT_OPEN` | 422 |
| `ERR_BACKUP_IN_USE` | 409 |
| `ERR_STALE_VERSION` | 412 |
