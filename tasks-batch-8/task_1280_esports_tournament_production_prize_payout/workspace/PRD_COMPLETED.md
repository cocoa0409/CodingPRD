# Esports Tournament Payout API — Product Requirements Document

## 1. Introduction

Running a large esports event is not a single workflow but several interlocking ones: a competitive pipeline (registration, roster lock, bracket seeding, match officiating, dispute adjudication), an integrity pipeline (anti-cheat investigation, strike accrual, disqualification), a broadcast pipeline (talent booking and settlement), and a finance pipeline (prize pool funding, payout computation, tax documentation, disbursement). Each pipeline has its own actors, its own clocks, and its own failure modes, yet every one of them reads and writes the same shared state — a disputed match freezes prize computation, a banned player forfeits a roster slot, a funding shortfall blocks bracket generation.

This document specifies the HTTP API for an Esports Tournament Production & Prize Payout system. The platform is operated by an organizer whose staff are split into strongly segregated duties: those who run the competition may not touch money, those who approve money may not certify the documents that justify it, and those who referee a match may not later adjudicate an integrity case arising from it. Segregation of duties is enforced in the data model, not by convention. The API also owns the canonical logical clock: the system never consults wall-clock time, and every temporal rule (registration windows, dispute windows, curfews, strike decay) is evaluated against a clock that test operators set explicitly.

The system is mounted under `/api`. All currency amounts are integer cents; all timestamps are ISO 8601 UTC.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403) per the endpoint's authorized role list in §4. A request whose role is permitted but whose identity does not own the target resource, where the resource is one for which ownership is meaningful, is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The platform recognizes nine roles, spelled exactly as follows.

- `OrganizerAdmin` — platform operator; owns configuration, funding, and master data (tournaments, players, registration shells, servers, talent, sponsor deal creation and voiding, the logical clock). When `X-User-Role` is `OrganizerAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `TournamentDirector` — runs the competitive lifecycle: advancing tournament status, reviewing registrations, generating brackets, scheduling matches, adjudicating disputes. When `X-User-Role` is `TournamentDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `confirmed_by_user_id` on a match whose dispute is ruled `UPHELD`) but does not compare it to any entity's `id`.
- `TeamManager` — manager of a single team registration. When `X-User-Role` is `TeamManager`, `X-User-ID` is the `id` of the acting `Registration`; ownership checks on any resource that references a `Registration` compare the resource's foreign-key field to `X-User-ID`. A manager submitting, appealing, or editing roster slots operates on the registration whose `id` equals `X-User-ID`; a manager filing or appealing a dispute must be filing on a registration they own.
- `Player` — a competitor. When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting `Player`; ownership checks on any resource that references a `Player` compare the resource's foreign-key field to `X-User-ID`. Concretely, submitting payout tax documents requires that the target payout record's `payee_player_id` equals `X-User-ID`.
- `Referee` — match official. When `X-User-Role` is `Referee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on matches as `assigned_referee_id`, `reported_by_user_id`, or `confirmed_by_user_id` to anchor segregation-of-duties checks, but does not compare it to any entity's `id`.
- `AntiCheatInvestigator` — integrity officer. When `X-User-Role` is `AntiCheatInvestigator`, `X-User-ID` is an opaque operator identifier recorded on cases as `opened_by_user_id` or `resolved_by_user_id`; it is SoD-barred from resolving cases on matches the same user refereed.
- `BroadcastProducer` — broadcast production owner. When `X-User-Role` is `BroadcastProducer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `PayoutOfficer` — finance operator. When `X-User-Role` is `PayoutOfficer`, `X-User-ID` is an opaque operator identifier recorded on payout records as `doc_verified_by_user_id` or `approved_by_user_id`; it is SoD-barred from approving a record whose documents the same user verified.
- `SponsorManager` — sponsor contact. When `X-User-Role` is `SponsorManager`, `X-User-ID` is an opaque operator identifier; activating a deal requires the deal's `contact_user_id` to equal `X-User-ID`, an ownership check that yields `ERR_OWNERSHIP_MISMATCH` on mismatch.

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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Responses for list endpoints carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of matching records before pagination and `has_more` indicates whether additional records exist beyond the current page.

Most list endpoints sort deterministically by `created_at` ascending, breaking ties on `id` ascending. Two exceptions exist: the match list sorts by `bracket_round` ascending then `bracket_slot` ascending, and the payout record list sorts by `placement` ascending, then the registration's `created_at` ascending, then the record's `id` ascending.

### 2.4. Common Resource Properties and Mutation Semantics

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every resource that undergoes mutation additionally carries `updated_at` (same timestamp format) and an integer `version`. The `version` starts at 1 at creation and increments by exactly 1 on every mutation, regardless of how many fields change; `updated_at` refreshes on every mutation.

Resources are validated left-to-right through the URL path before any request body is examined: a missing path segment yields `ERR_NOT_FOUND` (HTTP 404) before body shape is considered, and foreign-key references inside the body are likewise validated in body order after path resources resolve.

### 2.5. The Logical Clock

All temporal rules — the registration window, the dispute window, the schedule-in-past rule, the strike-decay window, the curfew — are evaluated against a logical clock, never against wall-clock time. At process start the clock reads exactly `2026-08-01T00:00:00Z` and never advances on its own. An `OrganizerAdmin` operator advances it via a dedicated test-driving capability that sets the logical clock to a supplied `to_iso8601` instant; the response echoes the new value as `current_utc`. Reads of the clock for rule evaluation always see the most recently set value.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control: bracket generation (initial and regeneration) and payout computation. Both require a non-optional `expected_tournament_version` field in the request body carrying the client's last observed `version` of the target tournament. If the tournament's current `version` has advanced since the client last read it — for example because another operator just funded the pool or locked the roster — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state change occurs. This forces the client to re-read before writing and prevents a superseding operation (bracket regeneration, payout recompute) from being issued against a stale view of the tournament. No other endpoint takes a version field.

### 2.7. State Machines, Versioning, and Cascading Side Effects

Every entity with a `status` field obeys a state machine with named initial and terminal states; requesting a transition from a state that does not permit it is rejected with the machine's specific invalid-status error (HTTP 409). Two controls deviate from that rule: a server-maintenance action naming the already-current target state, and a player-eligibility action whose from-state does not permit it, are rejected with `ERR_VALIDATION` (HTTP 400) — see §3.4 and §3.9. State transitions always increment `version` by 1 and refresh `updated_at`. Many transitions cascade: advancing a tournament into `REGISTRATION_LOCKED` mutates every associated registration and computes per-slot ages; resolving an integrity case as a violation may cascade into player bans, roster-slot invalidation, registration forfeits, match forfeits, and server booking recomputation. These cascades are described in §3 where the owning workflow lives, and every cascade carries the same version-increment and `updated_at`-refresh contract as a direct mutation.

### 2.8. Monetary Precision and Rounding

All currency values are integer cents. Whenever a division or percentage produces a fractional cent, the platform rounds half-up to the nearest integer cent. Two rules use higher intermediate precision: `seed_score` retains 3 decimal places, rounded half-up; the per-record gross inside the prize-pool waterfall is rounded half-up to integer cents per record before any summation, never summed as exact values and rounded once. The `prize_rounding_reconciliation` step then distributes any delta to a nominated record. Withholding is rounded half-up on the withholding amount only; the net is exact subtraction. Talent fees round half-up at three pinned steps — uplift, overtime, royalty — with the final sum assembled from already-rounded components.

### 2.9. Validation Order

When several validation rules apply to a single request, the server evaluates them in a fixed priority order and returns the first failure. Auth checks come first (missing headers, then role, then ownership). Existence checks come next, left-to-right through path then body. Body-shape validation follows. Then come per-entity state-machine from-state checks. Business-safety rules (minor curfew, minor payee, tax threshold, segregation of duties) follow the state checks. Business-constraint rules (uniqueness, roster shape, window overlaps, pause limit, participant, appeal budget, downstream bracket lock, server maintenance) come after safety. Business-temporal rules (registration window, dispute window, schedule-in-past) follow constraints. Business-fiscal rules (bracket field size, prize-pool funding, open integrity cases, payout-final) come after temporal. The OCC stale-version check is evaluated last. Two local exceptions pin tighter orders: on match scheduling the server-`ACTIVE` check is evaluated immediately after the state checks, ahead of the minor-curfew safety check (§3.4); and on payout approval the `FINAL`-mode (payout-final) gate is evaluated immediately after the disbursement state check, ahead of the safety gates (§3.8).

### 2.10. Segregation of Duties

Three SoD walls are enforced, each expressed as a same-user prohibition. A match result cannot be confirmed by the referee whose `X-User-ID` was recorded as `reported_by_user_id` on the same match. A payout record cannot be approved by the officer whose `X-User-ID` was recorded as `doc_verified_by_user_id` on the same record (the check applies only when `doc_verified_by_user_id` is non-null). An integrity case cannot be resolved by the investigator whose `X-User-ID` equals the `assigned_referee_id` of the match referenced by the case (the check applies only when `match_id` is non-null). Violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Tournament Setup and Registration Window

An `OrganizerAdmin` creates a tournament by supplying its `name`, `game_title`, `region` (one of `NA`, `EU`, `APAC`, `LATAM`), the advertised prize pool `prize_pool_target_cents`, the exact starter count `roster_size`, the maximum roster size `max_roster_size` (which must be at least `roster_size`), the registration window endpoints `registration_opens_at` and `registration_closes_at` (both inclusive — submission is allowed when the logical clock is at or after the open and at or before the close), and the minor curfew `minor_curfew_local` expressed as `HH:MM` against the UTC time-of-day of a match end. Shape violations on creation — a `prize_pool_target_cents` below 0, a `roster_size` or `max_roster_size` below 1, a `max_roster_size` below `roster_size`, or a `minor_curfew_local` not in `HH:MM` form (00:00 through 23:59) — are rejected with `ERR_VALIDATION` (HTTP 400). A new tournament lands in `DRAFT` with `funded_pool_cents` at 0, `bracket_version` at 0, and `placements_assigned` false.

From `DRAFT` the tournament may be advanced to `REGISTRATION_OPEN` or to `CANCELLED`; cancelling from `DRAFT` is unconditional. Lifecycle advances are driven by a `TournamentDirector` calling the advance capability with a `target_status` naming the desired destination state. The prize pool is topped up by the same `OrganizerAdmin` calling the funding capability with an `amount_cents` (an integer of at least 1, else `ERR_VALIDATION`), which adds the amount to `funded_pool_cents` and bumps the tournament's `version`. Funding is accepted only while the tournament is in `DRAFT`, `REGISTRATION_OPEN`, `REGISTRATION_LOCKED`, or `SEEDED`; from any other status the call is rejected with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409). Cancelling from `REGISTRATION_OPEN` flips every non-terminal registration (`DRAFT`, `SUBMITTED`, `APPEALED`, `APPROVED`) to `REJECTED` and bumps the tournament's `version`.

### 3.2. Team Registrations, Roster Construction, and the Appeal Cycle

An `OrganizerAdmin` creates a registration shell by supplying the `tournament_id`, the team's display name `team_name` (unique within the tournament), the manager contact `manager_contact_email`, three seeding inputs (`region_rank_points`, `prior_event_points`, `qualifier_wins`), and the designated prize payee `captain_player_id`. The `tournament_id` and `captain_player_id` must reference an existing tournament and player (else `ERR_NOT_FOUND`), and a `team_name` already used by another registration of the same tournament is rejected with `ERR_HANDLE_TAKEN` (HTTP 409). The returned `id` is the identity a `TeamManager` uses on all subsequent calls — `X-User-ID` equals that `id`. A new registration starts in `DRAFT` with `appeal_used` false, `seed_score` and `seed_position` null, and `placement` null.

A `TeamManager` builds a roster by adding `RosterSlot` records, each carrying the `registration_id`, the `player_id`, and a `slot_role` of `STARTER` or `SUBSTITUTE`. A slot starts in `ACTIVE` with `age_at_lock_years` and `is_minor` null until roster lock. Slots may be added only while the registration is in `DRAFT` (else `ERR_INVALID_REGISTRATION_STATUS`), and an add that would push the registration's `ACTIVE` slot count above the tournament's `max_roster_size` is rejected with `ERR_ROSTER_SIZE_VIOLATION`. Slots may be removed, which transitions them to `REMOVED`; removal likewise requires the registration to be in `DRAFT` and the slot to be `ACTIVE`, with violations rejected as `ERR_INVALID_REGISTRATION_STATUS`. The uniqueness floor applies: no two non-`REMOVED` slots may share the same `(registration_id, player_id)` pair — violations are rejected with `ERR_HANDLE_TAKEN`. A player may appear on at most one registration's `ACTIVE` roster per tournament; attempting to add a player already `ACTIVE` on another registration is rejected with `ERR_PLAYER_DOUBLE_ROSTERED`.

Submission is the gate that locks in the roster. A `TeamManager` submits a registration whose status is `DRAFT`; the tournament must be in `REGISTRATION_OPEN`, and the logical clock must lie within the registration window (at or after `registration_opens_at`, at or before `registration_closes_at`) — outside that window the request is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`. The roster shape check requires exactly `roster_size` `ACTIVE` slots with `slot_role` `STARTER` and a total `ACTIVE` count not exceeding `max_roster_size`; violations are rejected with `ERR_ROSTER_SIZE_VIOLATION`. Every `ACTIVE` slot's player must currently be `ELIGIBLE`, and the `captain_player_id` must be the `player_id` of an `ACTIVE` `STARTER` slot; violations are rejected with `ERR_PLAYER_INELIGIBLE`. The double-roster check also applies at submit time. On success the registration moves `DRAFT → SUBMITTED` and its `version` increments.

Review is performed by a `TournamentDirector` against a `SUBMITTED` or `APPEALED` registration while the tournament remains in `REGISTRATION_OPEN`. The review call takes an `action` of `APPROVE` or `REJECT` and an optional `reason`. Approval moves the registration to `APPROVED`; rejection moves it to `REJECTED`. A rejected registration may be appealed exactly once by its owning `TeamManager` while the tournament is still in `REGISTRATION_OPEN`: the appeal transitions `REJECTED → APPEALED` and flips `appeal_used` to true. A second appeal is rejected with `ERR_APPEAL_EXHAUSTED`. Review of an `APPEALED` registration may end at `APPROVED` or `REJECTED`; after a re-rejection the cycle is closed because `appeal_used` is already true.

### 3.3. Roster Lock, Bracket Seeding, and Bracket Generation

Advancing the tournament from `REGISTRATION_OPEN` to `REGISTRATION_LOCKED` requires that the logical clock has reached `registration_closes_at` — if it has not, the advance is rejected with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409). The advance cascades: every registration in `APPROVED` moves to `LOCKED`, and every registration still in `SUBMITTED` or `APPEALED` moves to `REJECTED` as unreviewed at lock. For each now-`LOCKED` registration, every `ACTIVE` `RosterSlot` has its `age_at_lock_years` and `is_minor` computed by the roster-lock-age calculation: the slot's age is the whole years between the player's `date_of_birth` and the lock instant, using calendar-year rollover so a player is exactly N years old on their Nth birthday; `is_minor` is true when `age_at_lock_years` is strictly less than 18, and an 18th birthday falling exactly on the lock day yields `is_minor` false.

Bracket generation is allowed from `REGISTRATION_LOCKED` (initial build) and from `SEEDED` (regeneration, which supersedes the prior bracket). The call requires `expected_tournament_version` matching the tournament's current `version`. The gates are: at least 2 registrations must be in `LOCKED` (else `ERR_INSUFFICIENT_FIELD`), the funded pool must be at least the advertised target — `funded_pool_cents` must be greater than or equal to `prize_pool_target_cents`, with exact equality allowed (else `ERR_PRIZE_POOL_UNDERFUNDED`) — and, on regeneration, no match of the tournament may be in `LOBBY_OPEN`, `LIVE`, `PAUSED`, `COMPLETED`, `UNDER_DISPUTE`, `CONFIRMED`, or `OVERTURNED` (a violation is rejected with `ERR_INVALID_TOURNAMENT_STATUS`, HTTP 409).

On generation the platform first computes `seed_score` for each `LOCKED` registration: half of `region_rank_points`, plus three-tenths of `prior_event_points`, plus one-fifth of `qualifier_wins` multiplied by 10, with the final score rounded half-up to 3 decimal places. `seed_position` is then assigned by a selector policy that filters to `LOCKED` registrations, ranks by `seed_score` descending, breaks ties on `qualifier_wins` descending, then on the registration's `created_at` ascending, and finally on `team_name` ascending — never on `id`.

The bracket tree is then constructed. With `n` `LOCKED` registrations sorted by `seed_position` ascending, the bracket size is the smallest power of two greater than or equal to `n`. The bracket has log2 of that size rounds; round `r` has bracket-size divided by 2^r matches, 1-indexed so round 1 is the first round. Round-1 pairing matches seed `i` against seed (bracket size plus 1 minus `i`) for `i` from 1 to half the bracket size — slot `k` pairs home seed `k` against away seed (bracket size plus 1 minus `k`). Seeds greater than `n` do not exist; a round-1 match whose away seed exceeds `n` is a walkover, created directly in `FORFEIT` status with the home seed as winner and with `completed_at` and `dispute_window_closes_at` both set to the logical clock at generation, and the winner propagates immediately to the next match's empty slot (home slot first, then away). Each match's `next_match_id` points at round `r+1` slot equal to the ceiling of `k` divided by 2; the final's `next_match_id` is null. A match created with both participants null stays `PENDING` (TBD). Every match carries a `tournament_id` set by the generator, a 1-indexed `bracket_round`, a 1-indexed `bracket_slot`, `home_registration_id` and `away_registration_id` (null while TBD), `winner_registration_id` null until a result, `server_id` and `scheduled_start_at` null until scheduled, `home_score` and `away_score` null until reported, and tactical pause counters `tactical_pauses_home` and `tactical_pauses_away` starting at 0. Generation bumps `bracket_version` by 1 and the tournament's `version` by 1, and writing the seed fields increments each `LOCKED` registration's `version` by 1; the tournament transitions to `SEEDED`. A successful generation returns HTTP 201 with the updated tournament in `data`.

Regeneration from `SEEDED` cancels every existing match of the tournament (each server's `booked_minutes` is recomputed), recomputes scores and positions, builds a new tree, bumps `bracket_version` again, and leaves the tournament in `SEEDED`.

Advancing from `SEEDED` to `IN_PROGRESS` requires every round-1 match with both participants assigned to be in `SCHEDULED`; otherwise the advance is rejected with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409).

### 3.4. Server Fleet, Match Scheduling, and the Curfew

An `OrganizerAdmin` registers a `ServerInstance` by supplying the `tournament_id`, a `label` (for example `NA-EAST-1`), and the server `region`. A new server starts `ACTIVE` with `booked_minutes` at 0. Maintenance is controlled by an `OrganizerAdmin` action of `ENTER` or `EXIT`, toggling the server between `ACTIVE` and `MAINTENANCE`; entering maintenance is blocked while the server has matches in `LOBBY_OPEN`, `LIVE`, or `PAUSED` (rejected with `ERR_SERVER_IN_MAINTENANCE`, HTTP 422), and an `ENTER` on a server already in `MAINTENANCE` or an `EXIT` on a server already `ACTIVE` is rejected with `ERR_VALIDATION` (HTTP 400).

Scheduling assigns a server, start time, duration, and referee to a `PENDING` match; the body carries `server_id`, `scheduled_start_at`, `duration_minutes` (an integer of at least 1, else `ERR_VALIDATION`), and `assigned_referee_id`, the referee identifier recorded on the match — it is taken from the request body, not from the scheduling director's headers. The tournament must be in `SEEDED` or `IN_PROGRESS`; both `home_registration_id` and `away_registration_id` must be non-null; the supplied `server_id` must reference a server that exists, belongs to the same tournament as the match (a cross-tournament server yields `ERR_VALIDATION`), and is `ACTIVE` (a `MAINTENANCE` server yields `ERR_SERVER_IN_MAINTENANCE`); and the supplied `scheduled_start_at` must be at or after the logical clock (a past instant yields `ERR_SCHEDULE_IN_PAST`). The server window overlap rule treats each booking as the half-open interval from start to (end plus 15 minutes of teardown buffer), where the end is `scheduled_start_at` plus `duration_minutes`: two such intervals on the same server must be disjoint, and adjacency where the next match starts exactly when the prior match's buffered window ends is allowed. A collision is rejected with `ERR_SERVER_WINDOW_CONFLICT`. The minor curfew rule also applies: if any `ACTIVE` roster slot of either participant has `is_minor` true, the UTC time-of-day of (`scheduled_start_at` plus `duration_minutes`) must be strictly before the tournament's `minor_curfew_local`; violation is rejected with `ERR_MINOR_CURFEW_VIOLATION`. Where several scheduling checks fail together they fire in this order: the server-`ACTIVE` check, then the minor-curfew check, then the window-overlap check, then the schedule-in-past check. On success the match moves `PENDING → SCHEDULED`, the body-supplied `assigned_referee_id` is recorded on the match, and the server's `booked_minutes` is recomputed.

`booked_minutes` on a server is the sum over matches assigned to that server whose status is in {`SCHEDULED`, `LOBBY_OPEN`, `LIVE`, `PAUSED`, `COMPLETED`, `UNDER_DISPUTE`, `CONFIRMED`, `OVERTURNED`} of (`duration_minutes` plus 15 minutes of buffer). Matches in `PENDING`, `FORFEIT`, or `CANCELLED` contribute zero.

### 3.5. Match Officiating, Results, and Disputes

A `Referee` officiates a match through a single action-driven capability. Opening the lobby (`OPEN_LOBBY`) requires both participants' registrations to be `LOCKED` (else `ERR_INVALID_MATCH_STATUS`) and the server to be `ACTIVE` (else `ERR_SERVER_IN_MAINTENANCE`); it moves the match `SCHEDULED → LOBBY_OPEN`. Starting play (`START`) moves `LOBBY_OPEN → LIVE`. Pausing (`PAUSE`) moves `LIVE → PAUSED` and takes a `pause_reason` and a `pausing_side`. If `pause_reason` is `TACTICAL`, the pausing side's tactical pause counter must be below 2 before the pause — a side that has already consumed 2 tactical pauses triggers `ERR_PAUSE_LIMIT_EXCEEDED` — and on success the corresponding counter (`tactical_pauses_home` or `tactical_pauses_away`) increments by 1. Technical pauses never count against the limit. Resuming (`RESUME`) moves `PAUSED → LIVE`. Forfeiting (`FORFEIT`) takes a `forfeiting_side` of `HOME` or `AWAY` and moves a `SCHEDULED` or `LOBBY_OPEN` match to `FORFEIT`; the winner becomes the other participant, `forfeiting_registration_id` is set to the forfeiting side, `completed_at` is set to the logical clock, and the dispute window is immediately closed (its close equals `completed_at`). The winner propagates to the next match's empty slot exactly as in the report-result flow, and the server's `booked_minutes` is recomputed because `FORFEIT` is excluded from the booked set.

Reporting a result moves `LIVE → COMPLETED`. The body carries `home_score` and `away_score`, both non-negative, and ties are not allowed — equal scores are rejected with `ERR_VALIDATION`. On success the higher-scoring side is recorded as `winner_registration_id`, the reporting referee's `X-User-ID` is recorded as `reported_by_user_id`, `completed_at` is set to the logical clock, and `dispute_window_closes_at` is set to 24 hours after `completed_at`. If `next_match_id` is non-null and the next match is `PENDING`, the winner is propagated into its first empty participant slot — home first, then away.

Confirmation is the SoD wall. A `Referee` whose `X-User-ID` differs from the recorded `reported_by_user_id` may confirm a `COMPLETED` match, moving it to `CONFIRMED` and recording the confirming referee's `X-User-ID` as `confirmed_by_user_id`. The same referee who reported the result may not confirm it — the request is rejected with `ERR_SEGREGATION_OF_DUTIES`.

A `TeamManager` files a dispute on a `COMPLETED` match by supplying the `match_id`, the filing team's `registration_id`, a `reason` (one of `RULE_VIOLATION`, `SCORE_DISCREPANCY`, `TECHNICAL_FAILURE`, `CONDUCT`), and free-form `details`. The filing registration must be a participant — either home or away — else `ERR_NOT_MATCH_PARTICIPANT`. Filing is only allowed while the logical clock is at or before the match's `dispute_window_closes_at`; after that the request is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. On acceptance the match moves `COMPLETED → UNDER_DISPUTE` and the new dispute lands in `FILED` with `appeal_used` false, `ruling` null, and `remedy` null.

Adjudication is performed by a `TournamentDirector`. `START_REVIEW` moves a `FILED` or `APPEALED` dispute to `UNDER_REVIEW`. `RULE_UPHELD` moves `UNDER_REVIEW → CLOSED_UPHELD`, records `ruling` `UPHELD`, and cascades the match from `UNDER_DISPUTE → CONFIRMED`, with the adjudicating director's `X-User-ID` recorded as the match's `confirmed_by_user_id`; if the match is no longer `UNDER_DISPUTE` (it is already `CONFIRMED` on a re-review after appeal), no match cascade occurs and `confirmed_by_user_id` is not rewritten. `RULE_OVERTURNED` takes a `remedy` of `WINNER_FLIP` or `REMATCH` and moves the dispute `UNDER_REVIEW → CLOSED_OVERTURNED`; the match-side cascades described below apply only while the match is `UNDER_DISPUTE` — if the match has already left `UNDER_DISPUTE`, only the dispute's own fields change. For `WINNER_FLIP`, the downstream next match, if any, must be in `PENDING` or `SCHEDULED`; otherwise the request is rejected with `ERR_BRACKET_LOCKED_DOWNSTREAM`. On success the match moves `UNDER_DISPUTE → OVERTURNED → CONFIRMED` in the same request, `winner_registration_id` flips to the other participant, the adjudicating director's `X-User-ID` is recorded as the match's `confirmed_by_user_id`, and if the winner had already been propagated to the next match's slot, that slot is replaced with the new winner. For `REMATCH`, the same downstream precondition applies with one tightening: if the advanced slot was already filled, the next match must still be `PENDING` — a re-queue into a started match is rejected with `ERR_BRACKET_LOCKED_DOWNSTREAM`. On success the match's `home_score`, `away_score`, `winner_registration_id`, `completed_at`, and `dispute_window_closes_at` are cleared, the advanced slot in the next match (if filled and still `PENDING`) is cleared, and the match moves `UNDER_DISPUTE → OVERTURNED → SCHEDULED` in the same request with the original `server_id` and `scheduled_start_at` retained.

A dispute closed `CLOSED_UPHELD` may be appealed once by the owning `TeamManager`, moving it to `APPEALED` and setting `appeal_used` true; the match's `CONFIRMED` status is not reopened by the appeal — the appeal reopens review only. A second appeal is rejected with `ERR_APPEAL_EXHAUSTED`. `CLOSED_OVERTURNED` is not appealable.

### 3.6. Tournament Completion and Placement Assignment

Advancing from `IN_PROGRESS` to `COMPLETED` requires every match of the tournament to be in `CONFIRMED` or `FORFEIT`; any other match state rejects the advance with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409). On success the platform assigns `placement` to every `LOCKED` registration by the placement-assignment calculation, and `placements_assigned` becomes true. Let `R` be the total number of rounds — log2 of the bracket size for the current `bracket_version`. The champion, defined as the winner of the final match, takes placement 1. A registration eliminated in a match at bracket round `r` takes placement equal to 2 raised to the power (`R` minus `r`), plus 1: the final loser (r equals `R`) places 2, semifinal losers (r equals `R` minus 1) place 3, quarterfinal losers place 5, and so on. `FORFEIT` matches count as eliminations for the forfeiting side. Registrations whose status is `FORFEITED` keep `placement` null and receive no payout record in either compute mode.

Advancing from `COMPLETED` to `PAYOUTS_FINALIZED` requires every payout record of the tournament to have `disbursement_status` in {`PAID`, `VOID`}; any other disbursement state rejects the advance with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409).

Cancelling from `SEEDED` cascades: every match in `PENDING` or `SCHEDULED` moves to `CANCELLED` and each affected server's `booked_minutes` is recomputed; every talent booking of the tournament in `TENTATIVE` or `CONFIRMED` moves to `CANCELLED`; the tournament's `version` increments.

### 3.7. Prize Pool Distribution

A `PayoutOfficer` runs prize pool distribution by calling the compute capability with a `mode` of `PROVISIONAL` or `FINAL` and an `expected_tournament_version` matching the tournament's current `version` (stale versions are rejected with `ERR_STALE_VERSION`). The tournament must be in `COMPLETED`; compute from any other tournament status is rejected with `ERR_INVALID_TOURNAMENT_STATUS` (HTTP 409).

The evaluation order is pinned across six steps. Step 1 computes the pool total: `funded_pool_cents` plus the sponsor bonus, where the sponsor bonus is the sum of `bonus_cents` over all sponsor deals of the tournament whose status is `ACTIVATED` at compute time. Step 2 selects the eligible set: registrations of the tournament whose `placement` is in {1, 2, 3} and whose status is not `FORFEITED`; placements greater than 3 pay zero. The two variants differ here. The `PROVISIONAL` variant ignores integrity cases entirely — accused players are treated as cleared — and produces records with `compute_run_mode` `PROVISIONAL` that cannot be approved (approval is rejected with `ERR_PAYOUT_NOT_FINAL`). The `FINAL` variant requires that no integrity case in `OPEN` or `INVESTIGATING` exists for any player on any eligible registration; if such a case exists the compute is rejected with `ERR_INTEGRITY_CASES_PENDING`. Step 3 sets the base percentage per placement: 50% for first place, 25% for second place, 12.5% for third place; each tied third-place team receives its own 12.5%. Step 4 applies only to the `FINAL` variant: if any placed registration was excluded because it is `FORFEITED`, its base percentage is redistributed to the remaining placed registrations in proportion to their own base percentages.

Step 5 is the waterfall with floor. Placements are processed in ascending order — first place, then second place, then third places ordered by the registration's `created_at` ascending, with a final fallback on `seed_position` ascending. Each record's exact gross is the smaller of two values: the larger of 100000 cents (the minimum placement payout) or the pool total multiplied by the record's percentage divided by 100, on one hand; and the remaining pool on the other. The remaining pool starts at the pool total and decrements by each record's exact gross. Step 5b is the residual sweep: after the last record, any positive remaining pool (unallocated percentage, as happens in a 2-team bracket where shares sum to 75%) is added to the placement-1 record's exact gross before rounding; if no placement-1 record exists, the residual goes to the record with the lowest placement number present, breaking ties by the registration's `created_at` ascending with a final fallback on `seed_position` ascending. Step 6 is the rounding reconciliation: each record's exact gross is rounded half-up to integer cents first, then the rounded values are summed; the delta — pool total minus the sum of rounded grosses, which may be negative — is added to the record with the lowest placement number (placement ascending, then the registration's `created_at` ascending, with a final fallback on `seed_position` ascending; never `id`).

Every record created carries the requesting `compute_run_mode`, the tournament's `bracket_version` at compute time, the computed `gross_amount_cents`, `withholding_cents` zero, `net_amount_cents` equal to `gross_amount_cents` (finalized at approve), `payee_is_minor` copied from the payee roster slot's `is_minor` at compute time, `doc_status` `PENDING`, and `disbursement_status` `COMPUTED`. Each record's `payee_player_id` is the owning registration's `captain_player_id` and its `placement` is copied from the registration; `doc_type`, `guardian_name`, `guardian_email`, `doc_verified_by_user_id`, `approved_by_user_id`, and `paid_at` all start null. The supersede rule voids every prior payout record of the tournament whose `disbursement_status` is `COMPUTED` before the new records persist; voided records carry `disbursement_status` `VOID`. The tournament's `version` increments by 1 on a successful compute, and the response is HTTP 201 with `data` carrying the array of newly created records in waterfall processing order.

### 3.8. Tax Documentation, Approval, and Disbursement

Each payout record tracks two parallel state dimensions. The disbursement dimension flows `COMPUTED → APPROVED → PAID` or `COMPUTED → VOID`. The documentation dimension flows `PENDING → SUBMITTED → VERIFIED` or `PENDING → SUBMITTED → REJECTED`, with `REJECTED → SUBMITTED` as a resubmission cycle. The dimensions evolve independently except where approval gates on documentation.

Document submission is performed by the payee `Player` (whose `X-User-ID` must equal the record's `payee_player_id`, an ownership check enforced with `ERR_OWNERSHIP_MISMATCH`). The body carries `doc_type` (one of `W9`, `W8BEN`, `GUARDIAN_W9`) and, when the payee is a minor, `guardian_name` and `guardian_email`. A minor payee must submit with `doc_type` `GUARDIAN_W9` and both guardian fields present; violation is rejected with `ERR_VALIDATION`. Documents cannot change after approval — the record's `disbursement_status` must be `COMPUTED` at submit time, else `ERR_INVALID_PAYOUT_STATUS`. Submission is accepted only while `doc_status` is `PENDING` or `REJECTED`; from `SUBMITTED` or `VERIFIED` it is rejected with `ERR_INVALID_PAYOUT_STATUS`. On success `doc_status` moves to `SUBMITTED` and `doc_type` is recorded (overwritten on resubmission from `REJECTED`); the guardian fields are stored only when the payee is a minor.

Verification is performed by a `PayoutOfficer` against a `SUBMITTED` record. `VERIFY` moves `doc_status` to `VERIFIED` and records the officer's `X-User-ID` as `doc_verified_by_user_id`. `REJECT` moves `doc_status` to `REJECTED`, allowing resubmission.

Approval is the gate that finalizes withholding. A `PayoutOfficer` approves a record in `COMPUTED`. The gates are evaluated in a fixed order: first the `compute_run_mode` must be `FINAL` — a `PROVISIONAL` record is rejected with `ERR_PAYOUT_NOT_FINAL`; then the minor gate, which applies independently of amount — when `payee_is_minor` is true, `doc_status` must be `VERIFIED` and `doc_type` must be `GUARDIAN_W9`, else `ERR_GUARDIAN_DOCS_REQUIRED`; then the tax threshold — when `gross_amount_cents` is at least 60000 cents (inclusive, so exactly 60000 requires it), `doc_status` must be `VERIFIED`, else `ERR_TAX_DOCS_REQUIRED`; and finally the SoD wall — when `doc_verified_by_user_id` is non-null, the approving officer's `X-User-ID` must differ from it, else `ERR_SEGREGATION_OF_DUTIES`.

On approval the withholding is computed from the record's current verified document. A verified `W9` withholds 0%. A verified `W8BEN` withholds 30%. A verified `GUARDIAN_W9` withholds 0%. A record with no verified document, which is reachable only when gross is below 60000 cents and the payee is not a minor, withholds 24%. The `withholding_cents` is the gross multiplied by the applicable rate divided by 100, rounded half-up to integer cents; `net_amount_cents` is the gross minus the withholding. The approving officer's `X-User-ID` is recorded as `approved_by_user_id`, and the record moves to `APPROVED`.

Payment moves `APPROVED → PAID`, sets `paid_at` to the logical clock, and is performed by a `PayoutOfficer` with no further preconditions.

### 3.9. Integrity Investigation, Strikes, and the DQ Cascade

An `AntiCheatInvestigator` opens an integrity case by supplying the accused `player_id`, an optional implicated `match_id`, and an `evidence_summary` digest. The new case lands in `OPEN`, with the opening investigator's `X-User-ID` recorded as `opened_by_user_id`, `resolved_by_user_id` null, `strike_issued` false, and `resolved_at` null.

`BEGIN_INVESTIGATION` moves a case `OPEN → INVESTIGATING`. `RESOLVE` is valid only from `INVESTIGATING` and takes an `outcome` of `CLEARED` or `VIOLATION`. Both outcomes apply the referee SoD wall: when `match_id` is non-null, the resolving investigator's `X-User-ID` must differ from that match's `assigned_referee_id`, else `ERR_SEGREGATION_OF_DUTIES`. A `CLEARED` outcome records `resolved_by_user_id` and `resolved_at` and moves the case to `RESOLVED_CLEARED`. A `VIOLATION` outcome records the same fields, sets `strike_issued` true, moves the case to `RESOLVED_VIOLATION`, appends a strike event containing the case's `integrity_case_id` and `issued_at` (set to the logical clock) to the player's `ac_strike_events`, and recomputes the player's `active_strike_count`.

The active strike count is the number of events in `ac_strike_events` whose `issued_at` is strictly after (now minus 365 days); a strike exactly 365 days old is expired. If the recomputed count reaches 3 — at exactly 3 the ban triggers, at 2 it does not — the player's `eligibility_status` moves to `BANNED`, which is terminal within a tournament season with no unban path. The ban then cascades: every `ACTIVE` `RosterSlot` for the player whose registration's tournament is in `REGISTRATION_LOCKED`, `SEEDED`, `IN_PROGRESS`, or `COMPLETED` moves to `INELIGIBLE`. For each affected registration, if the count of `ACTIVE` `STARTER` slots has dropped below the tournament's `roster_size`, the registration moves `LOCKED → FORFEITED`. For each forfeited registration, every non-terminal match where the registration is a participant — here meaning `PENDING`, `SCHEDULED`, `LOBBY_OPEN`, `LIVE`, `PAUSED`, `COMPLETED`, `UNDER_DISPUTE`, or `OVERTURNED` (a `CONFIRMED` match is not reopened) — moves to `FORFEIT` with the other participant recorded as winner, `forfeiting_registration_id` set to the forfeited registration, `completed_at` and `dispute_window_closes_at` set to the logical clock, and walkover propagation, and the affected servers' `booked_minutes` are recomputed.

Outside the strike cascade, an `OrganizerAdmin` may adjust a player's eligibility via an action of `SUSPEND` (moving `ELIGIBLE → SUSPENDED`) or `REINSTATE` (moving `SUSPENDED → ELIGIBLE`); a `SUSPEND` from any state other than `ELIGIBLE` or a `REINSTATE` from any state other than `SUSPENDED` is rejected with `ERR_VALIDATION` (HTTP 400). `BANNED` is reachable only through the strike cascade, never directly.

A new player starts with `eligibility_status` `ELIGIBLE` and an empty `ac_strike_events` list. A player's public profile carries `handle` (globally unique, case-sensitive — duplicates are rejected with `ERR_HANDLE_TAKEN`), `date_of_birth` as an ISO date in `YYYY-MM-DD` form, the player's home `region`, `eligibility_status`, the append-only `ac_strike_events` list, and the computed `active_strike_count`.

### 3.10. Broadcast Talent Booking and Settlement

A `BroadcastProducer` registers talent by supplying a globally unique `stage_name` (duplicates rejected with `ERR_HANDLE_TAKEN`), a `home_region`, a `day_rate_cents` interpreted as the rate per 8-hour day unit, and an optional `cross_region` flag (default false) indicating whether the talent may work outside their home region.

A `BroadcastProducer` books talent onto a shift window by supplying the `tournament_id`, `talent_id`, a `stage_label` (for example `MAIN` or `B-STREAM`), and the closed-interval shift endpoints `shift_start_at` and `shift_end_at`. The end must be strictly after the start (else `ERR_VALIDATION`). The talent region rule applies: when the talent's `home_region` differs from the tournament's `region`, the talent's `cross_region` must be true, else `ERR_TALENT_REGION_MISMATCH`. The talent window conflict rule treats each confirmed booking as the closed interval from `shift_start_at` to `shift_end_at`: two such intervals for the same talent among `CONFIRMED` bookings must be disjoint, and back-to-back bookings where the prior shift's end equals the next shift's start are a conflict (unlike the server window rule). A collision is rejected with `ERR_TALENT_WINDOW_CONFLICT`. A new booking lands in `TENTATIVE` with `fee_quote_cents` computed by the provisional talent-fee variant: the shift duration in hours is the difference between end and start in minutes divided by 60, taken exactly; the day units are that duration divided by 8 rounded up to a whole number; the quote is `day_rate_cents` multiplied by the day units, with no uplift, no overtime, and no royalty.

Confirming a booking moves `TENTATIVE → CONFIRMED` and requires the tournament to be in `SEEDED` or `IN_PROGRESS` (else `ERR_INVALID_BOOKING_STATUS`, HTTP 409); the closed-interval conflict check among other `CONFIRMED` bookings is re-applied at confirm time. Settling moves `CONFIRMED → SETTLED` and requires the tournament to be in `IN_PROGRESS` or `COMPLETED` (else `ERR_INVALID_BOOKING_STATUS`, HTTP 409). Cancelling moves either `TENTATIVE` or `CONFIRMED` to `CANCELLED`.

Settlement computes `fee_final_cents` by the final talent-fee variant, whose pinned evaluation order resolves a circular-looking royalty. Step 1 computes day units as the shift duration in hours divided by 8, rounded up. Step 2 computes base as `day_rate_cents` times day units. Step 3 applies the cross-region uplift: if the talent's `home_region` differs from the tournament's `region`, the base is multiplied by 1.15 and rounded half-up to integer cents; the uplift applies to the base only, never to overtime. Step 4 computes overtime as the number of hours by which the duration exceeds 8 (zero when the duration is 8 or less), multiplied by the hourly rate (`day_rate_cents` divided by 8), multiplied by 1.5, rounded half-up. Step 5 selects the royalty band from the post-uplift base only — never from the total, which is what makes the order load-bearing: a base below 200000 cents carries 0% royalty; a base of at least 200000 but below 500000 carries 5%; a base of at least 500000 carries 10%. The royalty is the base multiplied by the band percentage divided by 100, rounded half-up. Step 6 assembles the final fee as base plus overtime plus royalty. Identical inputs settle to a strictly larger `fee_final_cents` than `fee_quote_cents` whenever any of the uplift, overtime, or royalty components is nonzero.

### 3.11. Sponsor Deals and Activation Bonus

An `OrganizerAdmin` creates a sponsor deal by supplying the `tournament_id`, `sponsor_name`, the `contact_user_id` of the `SponsorManager` who will own activation, a `rights_tier` of `TITLE`, `PRESENTING`, or `SUPPORTING`, the `bonus_cents` that will be added to the prize pool at compute time if the deal is `ACTIVATED`, and a `content_rights` array that must be a subset of [`VOD`, `CLIPS`, `REPLAYS`, `LOGOS`]. A new deal lands in `PROPOSED` with `activated_at` null.

Contracting (`PROPOSED → CONTRACTED`) and voiding (from `PROPOSED`, `CONTRACTED`, or `ACTIVATED` to `VOID`) are `OrganizerAdmin`-only operations — a `SponsorManager` attempting either is rejected with `ERR_FORBIDDEN`. Activation (`CONTRACTED → ACTIVATED`) is performed by the owning `SponsorManager` — any other role, including `OrganizerAdmin`, is rejected with `ERR_FORBIDDEN`, and the deal's `contact_user_id` must equal the caller's `X-User-ID`, enforced with `ERR_OWNERSHIP_MISMATCH` — and records `activated_at` as the logical clock. Only deals `ACTIVATED` at compute time contribute `bonus_cents` to the pool total in the prize-pool waterfall.

## 4. Endpoint Definitions

New resources are created with HTTP 201; modifications to existing resources return HTTP 200. All endpoints are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical server clock | OrganizerAdmin |
| POST | /api/tournaments | Create a tournament in DRAFT | OrganizerAdmin |
| GET | /api/tournaments/{id} | Read a tournament | OrganizerAdmin, TournamentDirector, TeamManager, Player, Referee, AntiCheatInvestigator, BroadcastProducer, PayoutOfficer, SponsorManager |
| POST | /api/tournaments/{id}/advance | Advance tournament lifecycle to target_status | TournamentDirector |
| POST | /api/tournaments/{id}/fund | Add funding to the prize pool | OrganizerAdmin |
| POST | /api/tournaments/{id}/generate-bracket | Seed LOCKED registrations and build the match tree; regeneration supersedes (OCC-guarded) | TournamentDirector |
| POST | /api/tournaments/{id}/payout-records/compute | Run prize_pool_distribution in PROVISIONAL or FINAL mode; supersedes prior COMPUTED records (OCC-guarded) | PayoutOfficer |
| POST | /api/players | Register a player | OrganizerAdmin |
| GET | /api/players/{id} | Read a player | OrganizerAdmin, TournamentDirector, Player, AntiCheatInvestigator, PayoutOfficer |
| POST | /api/players/{id}/eligibility | Admin eligibility control: SUSPEND or REINSTATE | OrganizerAdmin |
| POST | /api/registrations | Create a team registration shell in DRAFT | OrganizerAdmin |
| GET | /api/registrations/{id} | Read a registration | OrganizerAdmin, TournamentDirector, TeamManager, PayoutOfficer |
| GET | /api/registrations | List registrations with filters tournament_id, status, captain_player_id | OrganizerAdmin, TournamentDirector, PayoutOfficer |
| POST | /api/registrations/{id}/submit | Submit registration for eligibility review | TeamManager |
| POST | /api/registrations/{id}/review | Eligibility decision on a SUBMITTED or APPEALED registration | TournamentDirector |
| POST | /api/registrations/{id}/appeal | Appeal a REJECTED registration (once) | TeamManager |
| POST | /api/roster-slots | Add a player to a DRAFT registration roster | TeamManager |
| POST | /api/roster-slots/{id}/remove | Remove a roster slot from a DRAFT registration | TeamManager |
| GET | /api/roster-slots/{id} | Read a roster slot | OrganizerAdmin, TournamentDirector, TeamManager |
| GET | /api/roster-slots | List roster slots with filters registration_id, player_id, status | OrganizerAdmin, TournamentDirector, TeamManager |
| POST | /api/servers | Register a game server instance | OrganizerAdmin |
| GET | /api/servers/{id} | Read a server instance | OrganizerAdmin, TournamentDirector, Referee |
| POST | /api/servers/{id}/maintenance | Maintenance control: ENTER or EXIT | OrganizerAdmin |
| GET | /api/servers | List servers with filters tournament_id, status | OrganizerAdmin, TournamentDirector, Referee |
| GET | /api/matches/{id} | Read a match | OrganizerAdmin, TournamentDirector, TeamManager, Referee, AntiCheatInvestigator |
| GET | /api/matches | List matches with filters tournament_id, server_id, next_match_id, home_registration_id, away_registration_id, winner_registration_id, status | OrganizerAdmin, TournamentDirector, TeamManager, Referee, AntiCheatInvestigator |
| POST | /api/matches/{id}/schedule | Assign server, start time, duration, referee to a PENDING match | TournamentDirector |
| POST | /api/matches/{id}/officiate | Referee match control: OPEN_LOBBY, START, PAUSE, RESUME, FORFEIT | Referee |
| POST | /api/matches/{id}/report-result | Report final score; match moves to COMPLETED and winner advances | Referee |
| POST | /api/matches/{id}/confirm-result | Second referee ratifies the result | Referee |
| POST | /api/disputes | File a dispute on a COMPLETED match within its dispute window | TeamManager |
| GET | /api/disputes/{id} | Read a dispute | OrganizerAdmin, TournamentDirector, TeamManager |
| GET | /api/disputes | List disputes with filters match_id, registration_id, status | OrganizerAdmin, TournamentDirector, TeamManager |
| POST | /api/disputes/{id}/adjudicate | Dispute workflow: START_REVIEW, RULE_UPHELD, RULE_OVERTURNED with remedy | TournamentDirector |
| POST | /api/disputes/{id}/appeal | Appeal a CLOSED_UPHELD dispute (once) | TeamManager |
| POST | /api/integrity-cases | Open an anti-cheat case against a player | AntiCheatInvestigator |
| GET | /api/integrity-cases/{id} | Read an integrity case | OrganizerAdmin, AntiCheatInvestigator, TournamentDirector |
| GET | /api/integrity-cases | List integrity cases with filters player_id, match_id, status | OrganizerAdmin, AntiCheatInvestigator, TournamentDirector |
| POST | /api/integrity-cases/{id}/resolve | Case workflow: BEGIN_INVESTIGATION or RESOLVE with outcome | AntiCheatInvestigator |
| POST | /api/talents | Register broadcast talent | BroadcastProducer |
| POST | /api/talent-bookings | Book talent onto a shift window | BroadcastProducer |
| GET | /api/talent-bookings/{id} | Read a talent booking | OrganizerAdmin, BroadcastProducer |
| GET | /api/talent-bookings | List talent bookings with filters tournament_id, talent_id, status | OrganizerAdmin, BroadcastProducer |
| POST | /api/talent-bookings/{id}/transition | Booking workflow: CONFIRM, SETTLE, CANCEL | BroadcastProducer |
| GET | /api/payout-records/{id} | Read a payout record | OrganizerAdmin, PayoutOfficer, Player |
| GET | /api/payout-records | List payout records with filters tournament_id, payee_player_id, registration_id, disbursement_status | OrganizerAdmin, PayoutOfficer, Player |
| POST | /api/payout-records/{id}/submit-docs | Payee submits tax documentation; resubmission allowed after REJECTED | Player |
| POST | /api/payout-records/{id}/verify-docs | PayoutOfficer verifies or rejects submitted docs | PayoutOfficer |
| POST | /api/payout-records/{id}/approve | Approve disbursement; withholding finalized; doc gates; SoD vs verifier | PayoutOfficer |
| POST | /api/payout-records/{id}/pay | Disburse an approved payout | PayoutOfficer |
| POST | /api/sponsor-deals | Create a sponsor deal | OrganizerAdmin |
| GET | /api/sponsor-deals/{id} | Read a sponsor deal | OrganizerAdmin, SponsorManager, TournamentDirector |
| GET | /api/sponsor-deals | List sponsor deals with filters tournament_id, status | OrganizerAdmin, SponsorManager, TournamentDirector |
| POST | /api/sponsor-deals/{id}/transition | Deal workflow: CONTRACT, ACTIVATE, VOID | OrganizerAdmin, SponsorManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_VALIDATION | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_TOURNAMENT_STATUS | 409 |
| ERR_INVALID_REGISTRATION_STATUS | 409 |
| ERR_INVALID_MATCH_STATUS | 409 |
| ERR_INVALID_DISPUTE_STATUS | 409 |
| ERR_INVALID_CASE_STATUS | 409 |
| ERR_INVALID_BOOKING_STATUS | 409 |
| ERR_INVALID_PAYOUT_STATUS | 409 |
| ERR_INVALID_DEAL_STATUS | 409 |
| ERR_MINOR_CURFEW_VIOLATION | 422 |
| ERR_GUARDIAN_DOCS_REQUIRED | 422 |
| ERR_TAX_DOCS_REQUIRED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_HANDLE_TAKEN | 409 |
| ERR_PLAYER_DOUBLE_ROSTERED | 409 |
| ERR_ROSTER_SIZE_VIOLATION | 422 |
| ERR_PLAYER_INELIGIBLE | 422 |
| ERR_SERVER_WINDOW_CONFLICT | 409 |
| ERR_TALENT_WINDOW_CONFLICT | 409 |
| ERR_TALENT_REGION_MISMATCH | 422 |
| ERR_PAUSE_LIMIT_EXCEEDED | 422 |
| ERR_NOT_MATCH_PARTICIPANT | 422 |
| ERR_APPEAL_EXHAUSTED | 422 |
| ERR_BRACKET_LOCKED_DOWNSTREAM | 409 |
| ERR_SERVER_IN_MAINTENANCE | 422 |
| ERR_INSUFFICIENT_FIELD | 422 |
| ERR_PRIZE_POOL_UNDERFUNDED | 422 |
| ERR_INTEGRITY_CASES_PENDING | 422 |
| ERR_PAYOUT_NOT_FINAL | 422 |
| ERR_REGISTRATION_WINDOW_CLOSED | 422 |
| ERR_DISPUTE_WINDOW_CLOSED | 422 |
| ERR_SCHEDULE_IN_PAST | 422 |
