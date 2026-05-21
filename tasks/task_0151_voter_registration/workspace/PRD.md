# Voter Registration & Election Management API — Product Requirements Document

## 1. Introduction

Democratic elections succeed or fail on the precision of the administrative apparatus that runs them. Between the day a registrar opens enrolment and the moment a board of canvassers certifies a winner, hundreds of moving parts have to agree: who is eligible, where they cast, what survives a signature check, whether a downed voting machine forced provisional ballots, and whether the margin is tight enough to compel a recount. The Voter Registration & Election Management API is the system of record for those moving parts. It owns the election timetable, the voter roll, party affiliation history, absentee ballot lifecycles, in-person ballot casting, voting machine availability, ballot-curing adjudication, and recount accounting.

The API is built for an environment in which clerks, reviewers, polling-place officers, and the voters themselves all participate in different parts of the workflow under strict role separation. Several rules — eligibility, double-vote prevention, segregation of duties on curing cases, deadline enforcement, recount thresholds — must hold even when two operators act simultaneously, and even when the wall clock moves across a published deadline mid-transaction. This document specifies the contract every implementation must satisfy: the resource model, the state machines, the validation order, the calculations that drive tallies and recount triggers, and the error surface returned when any of these is violated.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply to every endpoint. Concrete business workflows are spelled out in §3.

### 2.1. User and Role-Based Access Control

Every request to the API must include two HTTP headers: `X-User-ID`, an opaque or entity-backed identifier for the acting principal, and `X-User-Role`, the role under which the principal is acting. A request that omits either header, or whose headers cannot be parsed, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not authorised for the targeted endpoint is rejected with `ERR_FORBIDDEN`.

The system recognises six roles: `ElectionBoard`, `RegistrarClerk`, `ReviewerClerk`, `PrecinctOfficer`, `Voter`, and `TestDriver`.

`ElectionBoard`, `RegistrarClerk`, `ReviewerClerk`, `PrecinctOfficer`, and `TestDriver` are all operator roles whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records such operator identifiers where state-machine side effects call for them — for example, the `RegistrarClerk` who activates a voter has their `X-User-ID` snapshotted onto the voter's `registered_by_user_id` field — but the server never resolves these opaque identifiers against a stored `id`. When `X-User-Role` is `Voter`, `X-User-ID` is the `id` of the acting `Voter`; ownership checks on any resource that references a `Voter` compare that resource's `voter_id` foreign key to `X-User-ID`, and a `Voter` can only act on their own row.

A dedicated segregation-of-duties rule applies to curing adjudication: the `ReviewerClerk` who acts on a `CuringCase` (resolving it, or requesting a revision) must present an `X-User-ID` different from the `Voter.registered_by_user_id` snapshot captured when that voter transitioned from `PENDING` to `ACTIVE`. A violation is rejected with `ERR_FORBIDDEN_SOD`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, list endpoints sort their results by `created_at` in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Election`, `Precinct`, `Voter`, `AbsenteeBallot`, `CuringCase`, `BallotCast`, `VotingMachine`, and `RecountRequest` — carries four system-managed fields:

- `id` (string): a server-minted UUID. The identifier has no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation that changes the resource.
- `version` (integer): a counter initialised to 1 on creation and incremented by 1 on every server-side mutation of the row, including mutations driven by cascade side effects from another entity.

Two entities are immutable-event-style and carry only `id` and `created_at` — they do not expose `updated_at` and they do not expose `version`. These are `PartyRegistration` (an append-only audit log of party changes) and `ClockState` (the server-controlled wall-clock row).

When a system-driven cascade mutates a row — for instance, when suspending a voter forces a still-`REQUESTED` absentee ballot to `REJECTED` — the cascaded row's `updated_at` is refreshed and its `version` is incremented exactly as it would be on a direct client mutation.

### 2.5. The Server Clock

Time in this system is not the host wall clock — it is a single server-controlled instant exposed through `ClockState`, whose `now` field can only be moved forward through an administrative clock-advance capability. The clock-advance request supplies a single `to_instant` field carrying the target ISO 8601 instant the clock should jump to. Every deadline check (registration, absentee request, ballot return, cure, certification), every scheduled state rollover (entering early voting, ending early voting, transitioning to election day), and every system-driven curing-case expiry consults this `now` rather than the host clock. Reading the clock is open to every authenticated role; advancing it is reserved for `TestDriver`. Advancing the clock past a threshold immediately runs the relevant sweeps — Election day-rollovers in the `DRAFT`, `OPEN_REGISTRATION`, `EARLY_VOTING`, or `ELECTION_DAY` window, and `CuringCase` expiry that transitions any `OPEN_PENDING_VOTER` or `UNDER_REVIEW` case to `EXPIRED` and cascades the linked `AbsenteeBallot` from `RETURNED` to `REJECTED`.

### 2.6. Hierarchical Consistency and Cascades

Several mutations in this system are inherently multi-row: changing the state of one entity can force dependent entities into compatible states, and the API must commit those secondary changes atomically with the primary one. Each cascaded mutation independently refreshes its target row's `updated_at` and increments that row's `version`. Two cascade families are particularly load-bearing.

Suspending a voter (the `ACTIVE` → `SUSPENDED` transition on a `Voter`) is a depth-3 cascade. The voter row mutates first (link 1). Every `AbsenteeBallot` owned by that voter whose `status` is `REQUESTED`, `ISSUED`, or `RETURNED` is then driven to `REJECTED` with the reason "voter suspended" (link 2). For each such ballot that had a `linked_curing_case_id`, the linked `CuringCase` — provided it is in `OPEN_PENDING_VOTER` or `UNDER_REVIEW` — is in turn driven to `RESOLVED_REJECT` (link 3). The curing-case transition at link 3 is caused by the ballot transition at link 2, not directly by the voter transition; it is a true transitive cascade and the curing case's `updated_at` and `version` reflect that.

Resolving a curing case in either direction also cascades. A `ReviewerClerk`-driven transition to `RESOLVED_ACCEPT` cascades up: the linked `AbsenteeBallot` moves from `RETURNED` to `CURED`, and a new `BallotCast` with `method=ABSENTEE` is created using the `voter_choice` the voter supplied at submit time. A transition to `RESOLVED_REJECT` does not cascade the ballot automatically; instead, it merely makes the ballot eligible for a subsequent operator-driven move to `REJECTED`.

When a `CuringCase` is system-expired because `now` has crossed `Election.cure_deadline`, the linked `AbsenteeBallot` cascades from `RETURNED` to `REJECTED`, and no `BallotCast` is created.

### 2.7. Nested Resource Retrieval and Path Validation

When an endpoint path contains multiple resource identifiers — for example, `/elections/{electionId}/precincts/{precinctId}` — the system validates each identifier in left-to-right order. The first missing identifier produces `ERR_NOT_FOUND` immediately, before any deeper identifier is checked or any business rule is evaluated. A request for a precinct under a non-existent election therefore reports the election as missing rather than the precinct.

### 2.8. Optimistic Concurrency Control

Any mutating endpoint that targets a specific row by its `id` accepts an optional `version` field in the request body. If `version` is supplied and does not match the row's current `version`, the request is rejected with `ERR_VERSION_MISMATCH`. If `version` is omitted, the server processes the mutation without an OCC check. The mechanism applies uniformly to `PATCH` endpoints, to every state-transition endpoint, to the absentee ballot return endpoint, the party-registration endpoint, the curing-case submit and request-revision endpoints, and the recount state endpoint.

### 2.9. Validation Priority

When more than one validation could reject a single request, the rules are evaluated in a strict global order so that the returned `error_id` is deterministic. The order is: (1) authentication of `X-User-ID` and `X-User-Role` headers, surfacing `ERR_UNAUTHENTICATED`; (2) role authorisation per the RBAC matrix, surfacing `ERR_FORBIDDEN`; (3) path-parameter existence checks (the left-to-right rule of §2.7), surfacing `ERR_NOT_FOUND`; (4) segregation-of-duties check on curing-case mutations, surfacing `ERR_FORBIDDEN_SOD`; (5) state-machine from-state legality, surfacing `ERR_INVALID_STATE`; (6) deadline-window checks, surfacing `ERR_DEADLINE_PASSED`; (7) the no-double-vote check, surfacing `ERR_DOUBLE_VOTE`; (8) the machine-failure-forces-provisional check, surfacing `ERR_MACHINE_FAILURE`; (9) eligibility checks at activation, surfacing `ERR_NOT_CITIZEN`, `ERR_UNDER_AGE`, or `ERR_RESIDENCY_INSUFFICIENT`; (10) precinct assignment, surfacing `ERR_NO_PRECINCT_MATCH`; (11) the party-lock check and the certify-requires-recount check, surfacing `ERR_PARTY_LOCKED` or `ERR_RECOUNT_REQUIRED` respectively; (12) the petition-count threshold for manual recounts, surfacing `ERR_RECOUNT_PETITION_INSUFFICIENT`; (13) the OCC check, surfacing `ERR_VERSION_MISMATCH`.

Two consequences are worth stating explicitly. An unauthenticated caller who also has a stale `version` always sees `ERR_UNAUTHENTICATED`, never `ERR_VERSION_MISMATCH`. A `PrecinctOfficer` attempting to cast on a `READY` machine for a voter who has already cast absentee sees `ERR_INVALID_STATE` only if the from-state is wrong; otherwise the request fails at the double-vote check with `ERR_DOUBLE_VOTE` before the machine-failure check even runs.

### 2.10. Numeric Precision

Percentages and ratios produced by the tally pipeline — `precinct_margin`, `election_margin_pct`, and `RecountRequest.trigger_margin_pct` — are rounded to six decimal places using round-half-up. Voter age is computed as the integer floor of `(Election.election_date - Voter.date_of_birth)` measured in days and then divided by 365.25; residency duration is computed as the integer day difference between `Election.election_date` and `Voter.residency_since`. Both are integer-valued. The recount auto-trigger threshold uses inclusive-on-the-low-side comparison: a provisional `election_margin_pct` exactly equal to `Election.recount_threshold_pct` triggers an automatic recount. Conversely, the cure-deadline check uses strictly-greater comparison: a submit-cure attempt where `now` is strictly later than `Election.cure_deadline` is rejected; equality is still on time.

### 2.11. Concurrency Guarantees

The API guarantees the following serialisation outcomes when two operations race on the same logical resource:

- Two attempts by the same voter to cast a ballot — for instance, an absentee acceptance racing a walk-in cast — serialise on the uniqueness of `(voter_id, election_id)` over `BallotCast` rows whose `status` is not `INVALIDATED`. The first writer wins; the loser receives `ERR_DOUBLE_VOTE` with HTTP `409`.
- Two `RegistrarClerk` calls that would issue an absentee ballot for the same `(voter_id, election_id)` serialise on the uniqueness of an `AbsenteeBallot` for that pair whose `status` is in `REQUESTED`, `ISSUED`, `RETURNED`, `ACCEPTED`, or `CURED`. The first writer wins; the loser receives `ERR_ABSENTEE_ALREADY_ISSUED` with HTTP `409`.
- A `Voter` party change running concurrently with an `ElectionBoard` transition of the election from `OPEN_REGISTRATION` to `EARLY_VOTING` is serialised on the `Election.state` read at the start of the party-change transaction. Exactly one wins: if the election rolls first, the party change is rejected with `ERR_PARTY_LOCKED`; otherwise, the party change commits and the election transition proceeds. HTTP `409` in either case.
- Two `ReviewerClerk` attempts to resolve the same `CuringCase` in opposite directions (one to `RESOLVED_ACCEPT`, the other to `RESOLVED_REJECT`) serialise on `CuringCase.status`. Exactly one transition succeeds; the loser sees `ERR_INVALID_STATE` (HTTP `409`) because the case is no longer in `UNDER_REVIEW`.
- A `PrecinctOfficer` marking a `VotingMachine` `DOWN` concurrently with a `PrecinctOfficer` casting on that machine serialises on `VotingMachine.status`. If the cast commits first, the cast succeeds and the machine still moves to `DOWN`; if the down-transition commits first, the cast is rejected with `ERR_MACHINE_FAILURE` (HTTP `409`).
- Two parallel attempts to approve the same `RecountRequest` serialise on `RecountRequest.version` (OCC); at most one approval succeeds and the loser sees `ERR_VERSION_MISMATCH` (HTTP `409`).

### 2.12. State Enumerations

The exact state strings used by every state machine in this system are:

- `Election`: `DRAFT`, `OPEN_REGISTRATION`, `EARLY_VOTING`, `ELECTION_DAY`, `TALLY`, `RECOUNT`, `CERTIFIED`.
- `Voter`: `PENDING`, `ACTIVE`, `SUSPENDED`, `PURGED`.
- `AbsenteeBallot`: `REQUESTED`, `ISSUED`, `RETURNED`, `ACCEPTED`, `REJECTED`, `CURED`.
- `CuringCase`: `OPEN_PENDING_VOTER`, `UNDER_REVIEW`, `RESOLVED_ACCEPT`, `RESOLVED_REJECT`, `EXPIRED`.
- `BallotCast`: `CAST`, `TALLIED`, `CHALLENGED`, `INVALIDATED`.
- `VotingMachine`: `READY`, `IN_USE`, `DOWN`, `DECOMMISSIONED`.
- `RecountRequest`: `REQUESTED`, `APPROVED`, `IN_PROGRESS`, `RESOLVED_NO_CHANGE`, `RESOLVED_OVERTURN`, `DENIED`.

Other enumerated values are: `reason_code` for an absentee request — `MILITARY`, `OVERSEAS`, `DISABILITY`, `ABSENT`, `NO_REASON` (with `NO_REASON` as the default if the requester does not supply one); `signature_match` reported on a ballot return — `MATCH`, `MISMATCH`, `MISSING`; `defect_code` on a curing case — `SIGNATURE_MISMATCH`, `SIGNATURE_MISSING`; `method` on a cast — `EARLY_IN_PERSON`, `ELECTION_DAY_MACHINE`, `ELECTION_DAY_PROVISIONAL`, `ABSENTEE`; `challenge_reason` on a cast — `DOUBLE_VOTE`, `MACHINE_FAILURE`, `RECOUNT_DISCREPANCY` (default null); `failure_reason` on a voting machine — `POWER`, `JAM`, `TAMPER`, `OTHER`; `party_affiliation` and `previous_party`/`new_party` on party rows — `DEMOCRATIC`, `REPUBLICAN`, `INDEPENDENT`, `UNAFFILIATED` (with `UNAFFILIATED` as the default at voter creation); `requested_by_role` on a recount — `ElectionBoard` or `system`; and `actor_role` on a `PartyRegistration` row — `VoterSelf` or `RegistrarClerk`.

## 3. Business Logic & Workflows

### 3.1. Setting Up an Election

An `ElectionBoard` operator initiates the lifecycle by creating an election. The creation payload supplies a human-readable `name`; the wall-clock anchors `election_date` (the election day, given as the UTC midnight of the date in question), `registration_deadline` (the instant after which voters cannot newly register and party changes are frozen), `absentee_request_deadline` (the last instant an absentee request is accepted), `early_voting_starts_at` (the inclusive start of the early voting window), `early_voting_ends_at` (the exclusive end of that window, which must be earlier than `election_date`), `ballot_return_deadline` (the last instant a returned absentee ballot is timely — the postmark rule does not apply, the server clock at the moment of receive governs), `cure_deadline` (the last instant a curing case can transition to `RESOLVED_ACCEPT`), and `certification_deadline` (the last instant the election can be certified). The optional `recount_threshold_pct` specifies the margin-of-victory percentage at or below which an automatic recount is required; when not supplied, it defaults to 0.005, that is, half of one percent.

A new election is in `DRAFT`. Before opening registration, the board must provision at least one precinct: an attempt to transition the election from `DRAFT` to `OPEN_REGISTRATION` while no precinct exists for that election is rejected with `ERR_NO_PRECINCTS`. The same transition also enforces that `registration_deadline` is still in the future relative to the server clock; if the deadline has already passed, the transition is rejected with `ERR_DEADLINE_PASSED`.

A precinct is created under its parent election. Each precinct carries a `code` that must be unique within the parent `election_id`, a `street_pattern` (a regex or CIDR-style pattern that drives residency-based voter assignment), and a `capacity_machines` integer counting the voting machines provisioned for election day. A precinct response also exposes the computed `provisional_ballot_count` — the count of `BallotCast` rows for this precinct whose `method` is `ELECTION_DAY_PROVISIONAL` and whose `status` is in `CAST`, `TALLIED`, or `CHALLENGED` — and the computed `machine_failure_active` boolean, which is true if and only if at least one `VotingMachine` at the precinct currently has `status=DOWN`.

A voting machine is provisioned at a specific precinct under a specific election. Each machine carries a `serial_no` that must be globally unique across the entire system. A newly provisioned machine starts in `READY`.

### 3.2. The Election Lifecycle and System-Driven Rollovers

An election traverses `DRAFT → OPEN_REGISTRATION → EARLY_VOTING → ELECTION_DAY → TALLY → (CERTIFIED or RECOUNT) → CERTIFIED`. The first transition (opening registration) is initiated by the `ElectionBoard` and is gated on having at least one precinct and on the registration deadline not yet having passed, as described above.

The rollover from `OPEN_REGISTRATION` to `EARLY_VOTING` is system-driven: when the server clock reaches or surpasses `early_voting_starts_at` and the clock-advance capability runs the relevant sweep, the election advances automatically. The sweep simultaneously re-evaluates every voter still in `PENDING`; any `PENDING` voter who now fails any eligibility criterion is auto-transitioned to `SUSPENDED` as a cascade-down side effect of the rollover. The cure-grace exception described in §3.6 also fires at this moment for affected `ACTIVE` voters.

The rollover from `EARLY_VOTING` to `ELECTION_DAY` is likewise system-driven once the clock reaches or surpasses `early_voting_ends_at`; this transition itself has no further side effects.

The rollover from `ELECTION_DAY` to `TALLY` is initiated by the `ElectionBoard`. It is gated on two conditions: the server clock must have reached or surpassed `ballot_return_deadline` (an attempt before that point is rejected with `ERR_TALLY_TOO_EARLY`), and no curing case may be in `OPEN_PENDING_VOTER` or `UNDER_REVIEW` (otherwise the transition is rejected with `ERR_CURING_IN_PROGRESS`). When the transition succeeds, three side effects execute in order: the provisional precinct totals are computed for every precinct, the provisional election-wide margin is computed, and — if the resulting margin meets or falls below `Election.recount_threshold_pct` — a `RecountRequest` is created automatically with `requested_by_role=system` and `trigger_margin_pct` snapshotted to the provisional margin.

From `TALLY` the election can move two ways. Going on to `CERTIFIED` requires that the provisional margin is strictly greater than the recount threshold (otherwise the transition is rejected with `ERR_RECOUNT_REQUIRED`), that no curing case is still open in `OPEN_PENDING_VOTER` or `UNDER_REVIEW`, and that the server clock has not surpassed `certification_deadline`. The side effect of this transition is to set `Election.certified_winner_voter_choice` to the `voter_choice` with the highest reconciled total across all precincts.

The alternative is `TALLY → RECOUNT`, initiated by the `ElectionBoard` filing a manual recount petition or accepting a system-triggered recount. The transition requires that either an auto-trigger `RecountRequest` already exists for this election or that the supplied `petition_count` is at least 100 (otherwise rejected with `ERR_RECOUNT_PETITION_INSUFFICIENT`), and it requires the server clock to be no later than `certification_deadline` (otherwise `ERR_DEADLINE_PASSED`). The transition cascades two effects: the underlying `RecountRequest` advances `REQUESTED → APPROVED → IN_PROGRESS`, and every `BallotCast` currently in `TALLIED` is set to `CHALLENGED` with `challenge_reason=RECOUNT_DISCREPANCY` (cascade-down).

From `RECOUNT` the election can move to `CERTIFIED` once every `RecountRequest` row for this election has reached one of `RESOLVED_NO_CHANGE`, `RESOLVED_OVERTURN`, or `DENIED`, and `now` is still no later than `certification_deadline`. The certification side effect sets `Election.certified_winner_voter_choice` to the `voter_choice` with the highest reconciled total drawn from the most recent resolved recount.

The `Election` row also exposes `total_registered_active`, a computed integer equal to the count of `Voter` rows whose `status` is `ACTIVE` and whose `precinct_id` lies under this election.

### 3.3. Voter Onboarding and Activation

Voter registration is a two-step affair. Either a `Voter` self-registers or a `RegistrarClerk` registers them; in either case the creation payload supplies `full_name`, `date_of_birth`, `residency_address`, `residency_since`, `is_citizen`, and the `election_id` the voter is registering for. The server creates a row in `PENDING` with `party_affiliation=UNAFFILIATED`, runs the precinct-assignment routine, and persists a `precinct_id` if a match was found. If no precinct's `street_pattern` matches the supplied address, the creation still succeeds but the voter's `precinct_id` remains null; the voter cannot later be activated.

The precinct-assignment routine considers exactly the `Precinct` rows whose `election_id` equals the voter's election. Each precinct is filtered by whether its `street_pattern` matches the voter's `residency_address`. Among the matches, the routine ranks by the length of `street_pattern` in descending order; ties are broken by `Precinct.code` in ascending lexicographic order. The first precinct under that ranking is assigned. If the match set is empty, the voter's `precinct_id` stays null and the routine reports `ERR_NO_PRECINCT_MATCH` to any caller that is performing an activation.

A `Voter` or `RegistrarClerk` may patch the voter's mutable fields — `full_name`, `residency_address`, `residency_since` — under OCC. A patch that changes `residency_address` triggers a re-run of the precinct-assignment routine and may change the voter's `precinct_id`; the patch refreshes the voter's `updated_at` and increments `version`.

A `RegistrarClerk` activates a voter by transitioning `PENDING → ACTIVE`. Activation enforces five preconditions, evaluated in this order after the higher-priority global checks of §2.9 have already cleared: the voter must attest citizenship (`is_citizen=true`, otherwise `ERR_NOT_CITIZEN`); the voter must be at least 18 years of age on `Election.election_date`, where age in whole years is computed as the floor of the day-count between birth date and election date divided by 365.25 (otherwise `ERR_UNDER_AGE`); the residency duration (the day-count between `residency_since` and `Election.election_date`) must be at least 30 days (otherwise `ERR_RESIDENCY_INSUFFICIENT`); the server clock must be no later than `registration_deadline` (otherwise `ERR_DEADLINE_PASSED`); and the voter's `precinct_id` must be non-null (otherwise `ERR_NO_PRECINCT_MATCH`). Activation is also where two snapshots are taken: `total_registered_active` on the parent election is incremented by one (cascade-up), `party_locked_at` on the voter is set to the election's `registration_deadline`, and `registered_by_user_id` is set to the activating clerk's `X-User-ID`. The last snapshot is what the segregation-of-duties check later compares against on curing-case mutations.

A voter who has been activated can later be suspended. The `RegistrarClerk` initiates an `ACTIVE → SUSPENDED` transition explicitly; the system may also drive the same transition during the `OPEN_REGISTRATION → EARLY_VOTING` rollover when an eligibility criterion newly fails. In either case the transition is blocked if the voter already has a `BallotCast` in `CAST` or `TALLIED` for this election; the rejection code is `ERR_VOTER_HAS_BALLOT`. Successful suspension decrements `total_registered_active` by one and triggers the depth-3 cascade described in §2.6.

The reverse transition `SUSPENDED → ACTIVE` is driven by the `RegistrarClerk`; it requires that the server clock is still no later than `registration_deadline` and that every eligibility check now passes again. The successful re-activation increments `total_registered_active` by one.

After the election has been certified, a `RegistrarClerk` may purge a voter — either `ACTIVE → PURGED` or `SUSPENDED → PURGED`. Both transitions are gated on `Election.state == CERTIFIED` (otherwise `ERR_INVALID_STATE`). The voter row is retained for audit; no further mutation is allowed.

### 3.4. Party Affiliation and the Lock

A voter's party affiliation is mutated only through a dedicated party-change endpoint. The mutation requires a `new_party` value and accepts the optional OCC `version`. Acting roles are either the `Voter` themselves or a `RegistrarClerk` who is performing the change on their behalf. The change is rejected with `ERR_PARTY_LOCKED` if the server clock is at or beyond the voter's snapshotted `party_locked_at`.

A successful change updates `Voter.party_affiliation`, refreshes `Voter.updated_at`, and writes a new `PartyRegistration` row recording the `voter_id`, the `previous_party` (the voter's value before the change), the `new_party` (the value being set), and the `actor_role` (`VoterSelf` or `RegistrarClerk` depending on the calling principal). `PartyRegistration` is append-only and immutable; the rows are themselves not patchable and expose only `id` and `created_at` as system-managed properties. The history is exposed through a paginated list endpoint scoped to the voter.

### 3.5. Absentee Ballots and Curing

A `Voter` (or a `RegistrarClerk` acting on their behalf) requests an absentee ballot by supplying the `election_id` and optionally a `reason_code`. The server creates an `AbsenteeBallot` row in `REQUESTED` with `requested_at` set to the server clock; if no reason is supplied, `reason_code` defaults to `NO_REASON`.

A `RegistrarClerk` issues the ballot by transitioning `REQUESTED → ISSUED`. The transition has two cross-entity preconditions: the parent `Voter.status` must be `ACTIVE` (otherwise `ERR_VOTER_NOT_ACTIVE`) and the server clock must be no later than `absentee_request_deadline` (otherwise `ERR_DEADLINE_PASSED`). The successful transition writes `issued_at = now`.

The `RegistrarClerk` records the ballot's return via the dedicated return endpoint, supplying `signature_match` (`MATCH`, `MISMATCH`, or `MISSING`) and the `voter_choice` the ballot bears. The transition `ISSUED → RETURNED` is gated by the ballot-return deadline: if the server clock is later than `ballot_return_deadline`, the request is rejected with `ERR_RETURN_LATE`. The successful transition writes `returned_at = now` and then branches. If `signature_match` is `MATCH`, the ballot auto-transitions to `ACCEPTED`, `decided_at` is set, and a new `BallotCast` is created with `method=ABSENTEE`, the supplied `voter_choice`, and the `absentee_ballot_id` of this row. If `signature_match` is `MISMATCH` or `MISSING`, a `CuringCase` is opened with `defect_code` equal to `SIGNATURE_MISMATCH` or `SIGNATURE_MISSING` respectively, and the ballot's `linked_curing_case_id` is populated with the new case's `id`. Note that an `ACCEPTED` cascade is the path through which a successful absentee return is counted; the explicit operator-driven `RETURNED → REJECTED` transition is permitted only when the linked curing case is in `RESOLVED_REJECT` or `EXPIRED`, or when no curing case was opened in the first place (because `linked_curing_case_id` is null).

A curing case starts in `OPEN_PENDING_VOTER`. Only the owning `Voter` — whose `id` must match the `voter_id` on the case (otherwise `ERR_FORBIDDEN`) — may submit a cure, supplying `voter_submission_text` and the intended `voter_choice`. The submission moves the case to `UNDER_REVIEW` and stores the submission text; the `voter_choice` is held until a later `RESOLVED_ACCEPT` to populate the eventual `BallotCast`. The submit endpoint enforces the cure deadline with a strict comparison: if the server clock is strictly later than `Election.cure_deadline`, the submission is rejected with `ERR_DEADLINE_PASSED`. Equality is still on time.

A `ReviewerClerk` adjudicates the case from `UNDER_REVIEW`. Three outcomes are possible: requesting a revision moves the case back to `OPEN_PENDING_VOTER` and increments `round_count` by one; this is gated on `round_count < max_rounds` (default 3, otherwise `ERR_MAX_ROUNDS_REACHED`), on `now` not having surpassed `Election.cure_deadline`, and on the segregation-of-duties check that `X-User-ID` of the caller is not equal to the voter's `Voter.registered_by_user_id` (otherwise `ERR_FORBIDDEN_SOD`). Resolving the case as `RESOLVED_ACCEPT` is gated on the cure deadline and on the same segregation-of-duties check; its side effects are the cascade-up of the linked `AbsenteeBallot` from `RETURNED` to `CURED` and the creation of a new `BallotCast` with `method=ABSENTEE` carrying the voter's submitted `voter_choice`. Resolving the case as `RESOLVED_REJECT` is gated on the same segregation-of-duties check; the linked ballot stays in `RETURNED` and becomes eligible for a subsequent operator-driven `REJECTED` transition.

A curing case can also reach `RESOLVED_REJECT` system-driven, when the voter is suspended and the link-3 cascade described in §2.6 fires from either `OPEN_PENDING_VOTER` or `UNDER_REVIEW`. A curing case can reach `EXPIRED` system-driven from either `OPEN_PENDING_VOTER` or `UNDER_REVIEW` when the clock-advance sweep observes `now > Election.cure_deadline`; the linked absentee ballot cascades to `REJECTED` and no `BallotCast` is created.

The `CuringCase` row also exposes `absentee_ballot_id`, `voter_id`, and `election_id` so that consumers can navigate back to the relevant context without separate joins.

### 3.6. The Cure-Grace Window for Domestic Movers

Eligibility recomputation is normally strict: all four of citizenship, age, residency duration, and the deadline window must hold, and the voter's `precinct_id` must be non-null. There is one variant, the cure-grace window, that applies under a narrow circumstance: when the election has just moved into `EARLY_VOTING`, the voter was `ACTIVE` at the moment of `registration_deadline`, and the current server clock is within seven days of `registration_deadline`. In that variant the residency-duration requirement is waived to accommodate voters who have moved within the jurisdiction, while citizenship and the age threshold continue to hold. The same input row evaluated in the strict variant before the rollover and in the cure-grace variant after it can yield different outcomes; this is intentional. The strict variant continues to govern any `PENDING → ACTIVE` activation during `OPEN_REGISTRATION`.

### 3.7. Voting Machines and the Provisional Fallback

A precinct's voting machines start in `READY` and are escorted through their lifecycle by `PrecinctOfficer` operators. A machine moves from `READY` to `IN_USE` automatically the first time a ballot is cast on it with `method=ELECTION_DAY_MACHINE` and a matching `machine_id`; this transition is system-driven and gated on `Election.state == ELECTION_DAY`.

A machine in `IN_USE` can be marked `DOWN` by a `PrecinctOfficer` reporting a `failure_reason` (`POWER`, `JAM`, `TAMPER`, or `OTHER`). The transition is rejected with `ERR_BAD_REQUEST` if no reason is supplied, and with `ERR_INVALID_STATE` if the election is not in `ELECTION_DAY`. Successful transition sets `down_since` to the server clock, sets the parent precinct's computed `machine_failure_active` to true, and from that moment on any cast attempt at this precinct with `method=ELECTION_DAY_MACHINE` is rejected with `ERR_MACHINE_FAILURE`. Officers must instead present `method=ELECTION_DAY_PROVISIONAL`. The voting-machine row also exposes a computed `backup_emergency_ballots_issued` counter — the number of `BallotCast` rows at this machine's precinct with `method=ELECTION_DAY_PROVISIONAL` whose `cast_at` is at or later than this machine's `down_since`.

A machine can be brought back from `DOWN` to `READY` by a `PrecinctOfficer`. The transition has no further preconditions; its side effect is to flip the parent precinct's `machine_failure_active` back to false provided no other machine at the same precinct is still `DOWN`. Once the election is `CERTIFIED`, the `ElectionBoard` may transition a `READY` machine to the terminal `DECOMMISSIONED` state.

### 3.8. Casting a Ballot In-Person

A `PrecinctOfficer` records an in-person ballot via a payload carrying `voter_id`, `precinct_id`, `method`, an optional `machine_id` (required when `method=ELECTION_DAY_MACHINE`, null otherwise), and `voter_choice`. The server creates a `BallotCast` in `CAST` with `cast_at` set to the server clock. Several rules act on this endpoint, evaluated in the global priority order of §2.9 once authentication, authorisation, and existence checks have cleared.

The double-vote rule (priority 7) is the dominant business-safety guard: at most one non-`INVALIDATED` `BallotCast` may exist per `(voter_id, election_id)` pair. A second creation that would violate this is rejected with `ERR_DOUBLE_VOTE`. The first-writer-wins semantics described in §2.11 govern races; the rare data-import edge case in which two casts already exist is handled by the system invalidating the later row with `challenge_reason=DOUBLE_VOTE` while preserving the first.

The machine-failure rule (priority 8) follows: if `Precinct.machine_failure_active` is true and the supplied `method` is `ELECTION_DAY_MACHINE`, the request is rejected with `ERR_MACHINE_FAILURE` and the officer must re-submit with `method=ELECTION_DAY_PROVISIONAL`. The provisional method is also the correct choice when the voter's `Voter.status` is still `PENDING`.

A successful cast on `method=ELECTION_DAY_MACHINE` triggers the machine's automatic `READY → IN_USE` transition described in §3.7, the first time it happens for that machine. `absentee_ballot_id` on a `BallotCast` row is populated only when `method=ABSENTEE`, in which case the row mirrors the absentee row that produced it via the acceptance or cure path. `challenge_reason` is null unless a subsequent system action sets it.

### 3.9. Tally, Recount, and Reconciliation

When the election rolls into `TALLY`, the provisional precinct totals run. For each precinct and each candidate or option `voter_choice` `c`, the provisional total is the count of `BallotCast` rows at that precinct whose `voter_choice` is `c`, whose `status` is in `CAST`, `TALLIED`, or `CHALLENGED`, whose `method` is in `EARLY_IN_PERSON`, `ELECTION_DAY_MACHINE`, or `ABSENTEE` — `ELECTION_DAY_PROVISIONAL` is explicitly excluded under the provisional variant, on the principle that provisional ballots have not yet been adjudicated — and whose `challenge_reason` is not `DOUBLE_VOTE`. The precinct's margin is then computed as the difference between the largest provisional total and the second-largest, divided by the sum across all `voter_choice` values, with the ratio rounded half-up to six decimal places.

The election-wide provisional margin follows from those per-precinct totals using a pinned rounding order. First, each per-choice total is summed across precincts as integer counts (each precinct's per-choice count is already integer, so this addition is exact and incurs no rounding). The summed totals are sorted in descending order. The election-wide margin is then the difference between the top total and the second total, divided once by the sum across all totals, with the resulting ratio rounded half-up to six decimal places. This order — sum integer counts first, then divide once — is mandatory; the alternative of computing per-precinct ratios and summing them across precincts is forbidden.

If the resulting provisional election-wide margin is at or below `Election.recount_threshold_pct`, the system creates a `RecountRequest` automatically with `requested_by_role=system` and `trigger_margin_pct` snapshotted to the provisional margin. The boundary is inclusive on the low side: a margin exactly equal to the threshold triggers a recount.

A manual recount is filed by an `ElectionBoard` operator submitting `petition_count` against the election; the recount-petition rule rejects the filing with `ERR_RECOUNT_PETITION_INSUFFICIENT` when `petition_count` is below 100 and `requested_by_role=ElectionBoard`. A successful filing creates a `RecountRequest` in `REQUESTED`; the request also exposes `trigger_margin_pct` and `reconciled_totals_json` once those fields are populated.

A `RecountRequest` traverses `REQUESTED → APPROVED → IN_PROGRESS → (RESOLVED_NO_CHANGE | RESOLVED_OVERTURN)` under board control, or `REQUESTED → DENIED`. Approval requires that, if the request was filed manually, `petition_count` is at least 100 (otherwise `ERR_RECOUNT_PETITION_INSUFFICIENT`) and the election is in `TALLY` or `RECOUNT` (otherwise `ERR_INVALID_STATE`). A denial is permitted only for manually-filed requests; system-triggered requests cannot be denied (otherwise `ERR_RECOUNT_REQUIRED`). Advancing approval to `IN_PROGRESS` has the side effect of cascading the election from `TALLY` to `RECOUNT` (cascade-up) and setting every `TALLIED` `BallotCast` to `CHALLENGED`.

In `IN_PROGRESS`, the reconciled totals are computed under the reconciled variant — identical to the provisional formula in all respects except that `ELECTION_DAY_PROVISIONAL` ballots are included. Each per-precinct per-choice count remains an integer and is again summed across precincts before the division, with the resulting ratio rounded half-up to six decimal places. The board resolves the recount as `RESOLVED_NO_CHANGE` when the reconciled winner agrees with the provisional winner, and as `RESOLVED_OVERTURN` when they differ; an attempt to resolve as `RESOLVED_OVERTURN` while the two winners agree is rejected with `ERR_RECOUNT_NO_OVERTURN`. Both resolution side effects snapshot `reconciled_totals_json` and cascade-down by moving every `CHALLENGED` `BallotCast` back to `TALLIED` with `challenge_reason` cleared to null; on a `RESOLVED_OVERTURN`, the eventual certification will draw `certified_winner_voter_choice` from the reconciled totals rather than the provisional ones.

A `BallotCast` that has already been certified into `TALLIED` may also be manually invalidated by the `ElectionBoard` post-hoc — for example, when a double-vote is discovered after the tally has begun. The endpoint accepts `to_state` and an optional `challenge_reason`, is permitted only while the election is in `TALLY` or `RECOUNT`, and triggers a recomputation of `precinct_margin` for the affected precinct.

The election's tally endpoint accepts an optional `variant` query parameter (`provisional` or `reconciled`) so a consumer can request either tally view independently of where the election currently sits in its own state machine.

## 4. Endpoint Definitions

Operations that create new resources — an election, a precinct, a voter, an absentee request, a voting machine, a recount filing, or a party-registration row — return `201 Created`. Operations that modify an existing row, including state transitions and cascades initiated through dedicated endpoints, return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/advance` | Advance the server clock to a specified instant; triggers day-rollover and curing-expiry sweeps | TestDriver |
| GET | `/_clock` | Read the current server clock | TestDriver, ElectionBoard, RegistrarClerk, ReviewerClerk, PrecinctOfficer, Voter |
| POST | `/elections` | Create an election in DRAFT | ElectionBoard |
| GET | `/elections/{electionId}` | Get a single election (includes computed `total_registered_active` and `certified_winner_voter_choice`) | ElectionBoard, RegistrarClerk, ReviewerClerk, PrecinctOfficer, Voter |
| GET | `/elections` | List elections, paginated; filterable by `state` | ElectionBoard, RegistrarClerk, ReviewerClerk, PrecinctOfficer, Voter |
| POST | `/elections/{electionId}/state` | Transition election state per the election state machine | ElectionBoard |
| GET | `/elections/{electionId}/tally` | Return provisional or reconciled tallies; controlled by `variant` query parameter | ElectionBoard, RegistrarClerk |
| POST | `/elections/{electionId}/precincts` | Create a precinct under an election | ElectionBoard |
| GET | `/elections/{electionId}/precincts/{precinctId}` | Get a precinct (includes computed `provisional_ballot_count` and `machine_failure_active`) | ElectionBoard, RegistrarClerk, PrecinctOfficer |
| GET | `/elections/{electionId}/precincts` | List precincts under an election, paginated | ElectionBoard, RegistrarClerk, PrecinctOfficer |
| POST | `/voters` | Create a voter; runs precinct assignment and sets `status=PENDING` | RegistrarClerk, Voter |
| GET | `/voters/{voterId}` | Get a voter | RegistrarClerk, ReviewerClerk, Voter, ElectionBoard |
| PATCH | `/voters/{voterId}` | Update mutable voter fields; re-runs precinct assignment when `residency_address` changes | RegistrarClerk, Voter |
| POST | `/voters/{voterId}/state` | Transition voter state per the voter state machine; cascades to absentee ballots and curing cases on suspension | RegistrarClerk |
| POST | `/voters/{voterId}/party-registration` | Change party affiliation; creates an immutable PartyRegistration row | Voter, RegistrarClerk |
| GET | `/voters/{voterId}/party-registration` | List the voter's party-registration history, paginated | Voter, RegistrarClerk, ElectionBoard |
| POST | `/voters/{voterId}/absentee-ballots` | Request an absentee ballot | Voter, RegistrarClerk |
| GET | `/absentee-ballots/{ballotId}` | Get an absentee ballot | Voter, RegistrarClerk, ReviewerClerk, ElectionBoard |
| POST | `/absentee-ballots/{ballotId}/state` | Operator-driven absentee transition (ISSUED, REJECTED) | RegistrarClerk |
| POST | `/absentee-ballots/{ballotId}/return` | Record return with `signature_match` and `voter_choice`; cascades to ACCEPTED or opens a CuringCase | RegistrarClerk |
| GET | `/curing-cases/{caseId}` | Get a curing case | Voter, ReviewerClerk, ElectionBoard |
| POST | `/curing-cases/{caseId}/submit` | Voter submits affirmation text and intended `voter_choice`; OPEN_PENDING_VOTER → UNDER_REVIEW | Voter |
| POST | `/curing-cases/{caseId}/request-revision` | Reviewer sends a case back to the voter; UNDER_REVIEW → OPEN_PENDING_VOTER with round_count + 1 | ReviewerClerk |
| POST | `/curing-cases/{caseId}/state` | Reviewer resolves a case (RESOLVED_ACCEPT or RESOLVED_REJECT); cascades to absentee ballot | ReviewerClerk |
| POST | `/ballots` | Cast an in-person ballot (early voting or election day); enforces double-vote, machine-failure, and eligibility | PrecinctOfficer |
| GET | `/ballots/{ballotId}` | Get a ballot cast | ElectionBoard, PrecinctOfficer |
| POST | `/ballots/{ballotId}/state` | ElectionBoard manually invalidates a TALLIED ballot post-hoc | ElectionBoard |
| POST | `/elections/{electionId}/precincts/{precinctId}/voting-machines` | Provision a voting machine at a precinct | ElectionBoard |
| GET | `/voting-machines/{machineId}` | Get a voting machine | ElectionBoard, PrecinctOfficer |
| POST | `/voting-machines/{machineId}/state` | Transition voting machine status; `failure_reason` required on DOWN | PrecinctOfficer, ElectionBoard |
| POST | `/elections/{electionId}/recounts` | File a manual recount petition | ElectionBoard |
| GET | `/elections/{electionId}/recounts` | List recount requests under this election (including system-triggered) | ElectionBoard |
| POST | `/recounts/{recountId}/state` | Transition recount state per the recount state machine | ElectionBoard |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_FORBIDDEN_SOD` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_MISMATCH` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_DOUBLE_VOTE` | 409 |
| `ERR_PARTY_LOCKED` | 409 |
| `ERR_ABSENTEE_ALREADY_ISSUED` | 409 |
| `ERR_VOTER_NOT_ACTIVE` | 409 |
| `ERR_RETURN_LATE` | 409 |
| `ERR_MAX_ROUNDS_REACHED` | 409 |
| `ERR_CURING_IN_PROGRESS` | 409 |
| `ERR_MACHINE_FAILURE` | 409 |
| `ERR_VOTER_HAS_BALLOT` | 409 |
| `ERR_TALLY_TOO_EARLY` | 409 |
| `ERR_RECOUNT_REQUIRED` | 409 |
| `ERR_RECOUNT_NO_OVERTURN` | 409 |
| `ERR_NO_PRECINCTS` | 409 |
| `ERR_NOT_CITIZEN` | 422 |
| `ERR_UNDER_AGE` | 422 |
| `ERR_RESIDENCY_INSUFFICIENT` | 422 |
| `ERR_NO_PRECINCT_MATCH` | 422 |
| `ERR_RECOUNT_PETITION_INSUFFICIENT` | 422 |
