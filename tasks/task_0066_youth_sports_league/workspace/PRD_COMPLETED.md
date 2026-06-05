# Youth Sports League API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Youth Sports League API, a back-office system that runs the full operational lifecycle of a community Little League: from the moment a parent registers a child through age verification, player evaluation, the team draft, the regular-season schedule, rainout makeups, the playoff bracket, and the final settlement of parent-volunteer deposits at season close.

The domain is unusually interconnected. A single league is a phased process that gates what its child resources may do at each stage, and many operations ripple outward — voiding a draft pick reopens a player and frees a roster slot; raining out a game releases its umpires; finalizing a playoff game eliminates a team from the bracket; closing the league refunds every family. The system is the authoritative record for eligibility (a player's *league age* relative to a fixed cutoff date), for competitive fairness (snake-draft ordering and playoff seeding), for scheduling integrity (field turnover buffers and referee double-booking), and for the small but real money that families post as refundable volunteer deposits.

Because several actors operate against the same data concurrently — admins advancing the draft while coaches submit picks, schedulers reshuffling rained-out games — the API leans on explicit version checks at the two contention points where stale writes would silently corrupt shared sequencing. The sections below define the global contract first, then the business logic that an implementer must reconstruct to behave correctly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted at the API root.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, or the role attempts to act on a resource it does not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `LeagueAdmin`, `Coach`, `Referee`, and `ParentGuardian`.

- A `LeagueAdmin` is the league operator and runs the bulk of administrative work: creating leagues, divisions, teams, fields and referees; advancing the league lifecycle; verifying ages; recording evaluations; withdrawing players; voiding draft picks; scheduling, starting, finalizing, raining out, rescheduling, and forfeiting games; proposing and releasing referee assignments; and settling volunteer commitments. When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

- A `Coach` makes draft picks for their own team and reads rosters and schedules. When `X-User-Role` is `Coach`, `X-User-ID` is an opaque coach identifier not tied to any persisted entity's `id`; instead it is matched against the `coach_user_id` recorded on a `Team` to decide ownership. A coach may record a draft pick only for a team whose `coach_user_id` equals the request's `X-User-ID`; otherwise the request is forbidden.

- A `Referee` confirms, declines, and checks in to their own assignments and reads the schedule. When `X-User-Role` is `Referee`, the role is entity-backed by `Referee`: `X-User-ID` is the `user_id` of the acting `Referee`. Ownership checks on any assignment compare the assignment's referee — resolved through `referee_id` to that `Referee`'s `user_id` — against `X-User-ID`.

- A `ParentGuardian` registers their own players, creates their own family account, pledges volunteer shifts, and reads their own family's records. When `X-User-Role` is `ParentGuardian`, the role is entity-backed by `Family`: `X-User-ID` is the `id` of the acting `Family`. Ownership checks on any resource that references a `Family` compare the resource's `family_id` to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific workflow states otherwise, every list endpoint returns resources sorted by their `created_at` timestamp in ascending order, with the resource `id` ascending as the deterministic tiebreaker when two resources share a `created_at`.

The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource — `League`, `Division`, `Family`, `Player`, `Team`, `DraftPick`, `Field`, `Referee`, `Game`, `RefereeAssignment`, and `VolunteerCommitment` — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Identifiers are never client-supplied.

Each of these entities also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and an integer `version` used for optimistic concurrency. The `version` starts at 1 when the resource is created and increases by exactly 1 on every mutation, including mutations that occur as a cascade triggered by another operation rather than by a direct request on that resource. In this domain all entities maintain `updated_at` and `version`; none are write-once.

### 2.5. Hierarchical Consistency and Cascading Effects

Many operations mutate more than one entity. Whenever an operation changes a secondary entity as a side effect, that secondary entity independently refreshes its own `updated_at` and increments its own `version` by 1, exactly as a direct mutation would. For example, advancing the league from `DRAFT` to `SEASON` transitions every `DRAFTED` player to `ROSTERED`, and each such player's `version` rises by 1; the league itself also increments its `version`. The same rule governs roster-count changes on teams, credit accrual on families, status changes cascaded onto referee assignments, and every other indirect effect described in §3.

Several counters and aggregates are computed rather than client-supplied and must be kept current as the underlying facts change: a league's `total_registered_players` (the number of players whose status is anything other than `WITHDRAWN`), a team's `roster_count` (players assigned to that team in status `DRAFTED` or `ROSTERED`), and a team's `wins`, `losses`, and `run_differential` (derived from that team's `FINAL` games). These are described in the workflows that drive them.

### 2.6. Resource Scoping and Nested Lookups

Resources live under a single owning league, and child resources additionally reference their parents through foreign-key fields carried in the request body or query string rather than in the URL path. When a request references resources — whether by a path identifier or by a body/query field — the system validates existence left to right and rejects the first identifier that does not resolve to an existing in-scope resource with `ERR_NOT_FOUND` (HTTP 404).

Beyond existence, referential consistency is enforced for creates that wire entities together: a player's requested division must belong to the same league as the player; a game's two teams must both belong to the game's stated division; a referee assignment's referee must belong to the same league as its game; and a draft pick's team and player must be in scope. A foreign key that points at an entity in the wrong league or division is rejected with `ERR_FK_SCOPE_MISMATCH` (HTTP 422). This referential check applies to player creation, game creation, assignment creation, and draft-pick creation.

### 2.7. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing header yields `ERR_UNAUTHENTICATED` before anything else. Authorization is second: a role not permitted for the operation (or acting outside its ownership) yields `ERR_FORBIDDEN`. Existence is third: any unresolved path or body reference yields `ERR_NOT_FOUND`. Foreign-key scope consistency is fourth, yielding `ERR_FK_SCOPE_MISMATCH`. State legality is fifth: if the target resource or its owning league is not in a state that permits the operation, the request yields `ERR_INVALID_STATE` (HTTP 409).

After those five system-level gates, domain checks apply in the order their workflows describe: the registration-window check (`ERR_REGISTRATION_WINDOW_CLOSED`), the age-eligibility check (`ERR_AGE_OUT_OF_RANGE`), the draft-turn check (`ERR_NOT_YOUR_PICK`), the last-pick check (`ERR_NOT_LAST_PICK`), the referee-present check for game start (`ERR_NO_REFEREE_CONFIRMED`), the referee time-overlap check (`ERR_REFEREE_TIME_CONFLICT`), the field-slot check (`ERR_FIELD_SLOT_CONFLICT`), the referee day-limit check (`ERR_REFEREE_DAY_LIMIT`), the roster-cap check (`ERR_ROSTER_FULL`), the no-ties check (`ERR_TIE_NOT_ALLOWED`), and the duplicate-family-email check (`ERR_DUPLICATE_FAMILY_EMAIL`). The optimistic-concurrency version check (`ERR_STALE_LEAGUE_VERSION` or `ERR_STALE_GAME_VERSION`) is evaluated after these business checks. The structural request-body check (`ERR_INVALID_REQUEST`, HTTP 400) covers malformed bodies, missing required fields, bad enum members, and numeric values outside their allowed ranges.

### 2.8. The League Phase Gate

The League's `status` enumeration — `SETUP`, `REGISTRATION`, `EVALUATION`, `DRAFT`, `SEASON`, `PLAYOFFS`, and the terminal `CLOSED` — is the master gate for the entire system. Every entity in this system carries its own `status` field tracking its lifecycle state. Child operations are only legal in the phases their workflows specify, and an operation attempted in the wrong league phase is rejected with `ERR_INVALID_STATE`. A new league always begins in `SETUP`. The phases advance strictly in the listed order; there is no skipping and no reverse. Each advance and each state-changing operation that is illegal for the current state surfaces as `ERR_INVALID_STATE`.

### 2.9. Scheduling Precision: Time Windows and Buffers

All scheduled instants — registration windows and game start/end times — are treated as half-open intervals `[start, end)`: the start instant is inclusive and the end instant is exclusive. Field-slot conflicts additionally fold in a per-field turnover buffer (see §3), and a touch exactly at a buffered boundary does not count as a conflict. Referee time-overlap, by contrast, uses the bare game intervals with no buffer. The server keeps a logical clock for window checks; an admin-only test-driving capability sets that clock to a supplied instant.

### 2.10. Monetary Precision

Money in this system — volunteer deposits, per-shift credits, accrued credit, and end-of-season refunds — is denominated in integer cents throughout; there are no fractional cents. Where a percentage fee must be applied, the result is rounded half up to a whole number of cents at the point the formula specifies (see §3 volunteer settlement). Evaluation scores, which are not monetary, use their own rounding rule described with the evaluation workflow: the blended score is rounded half up to two decimal places.

### 2.11. Optimistic Concurrency at Contention Points

Two operations sit on shared sequences where a write prepared against a stale view would corrupt ordering, and both require an explicit version check.

Recording a draft pick targets the shared, league-wide snake-order sequence. The create request must carry `expected_league_version`, the `version` of the owning `League` that the client last observed. If another writer has advanced the league's `version` since then — every recorded or voided pick advances it — the request is rejected with `ERR_STALE_LEAGUE_VERSION` (HTTP 412), forcing the client to re-read before submitting a pick that would otherwise land out of order.

Rescheduling a rained-out game targets that game's own slot. The reschedule request must carry `expected_game_version`, the `version` of the target `Game` that the client last observed. If the game's `version` has advanced since the client read it — for instance because an earlier reschedule already moved it — the request is rejected with `ERR_STALE_GAME_VERSION` (HTTP 412), so the writer re-reads rather than overwriting the newer slot.

No other endpoint takes a version field; the concurrency check applies only to draft-pick creation and game reschedule.

## 3. Business Logic & Workflows

### 3.1. Standing Up a League and Its Structure

A `LeagueAdmin` opens the system by creating a `League`, supplying its `name`, the `season_year`, the `age_cutoff_date` (a `'YYYY-MM-DD'` date, by convention the August 31 league-age cutoff), and the registration window as `registration_open_iso` (inclusive) and `registration_close_iso` (exclusive). The admin may also set `draft_snake`; when omitted it defaults to true, meaning the draft order reverses each round, and when false the order repeats forward each round. A freshly created league is in `SETUP`, has `version` 1, a `total_registered_players` of 0, and a `draft_round_index` of 0.

Before registration can open, the admin defines the competitive structure. Each `Division` belongs to a league through its `league_id` and is created with a `name`, an inclusive eligible league-age band given by `min_league_age` and `max_league_age`, and a `roster_cap` capping how many players a team in that division may hold. Teams are created inside a division and carry both `division_id` and a denormalized `league_id`, a `name`, the opaque `coach_user_id` that owns the team's picks, and a `draft_slot` — the 1-based lottery position that fixes draft order within the division (expected to be unique per division by convention, though the server does not validate uniqueness at team creation). A team begins with `roster_count`, `wins`, `losses`, and `run_differential` all 0, and a `seed` that stays null until playoff seeding.

Fields and the referee pool are also set up here. A `Field` carries its owning `league_id`, a `name`, and a `turnover_buffer_minutes` value that defaults to 30 and defines the minimum gap required between the end of one game and the start of the next on that field. A `Referee` carries its `league_id`, the opaque `user_id` it presents in `X-User-ID`, a `full_name`, and a `max_games_per_day` value that defaults to 3 and caps how many confirmed assignments the referee may hold on a single UTC calendar day.

The admin moves the league forward one phase at a time by requesting an advance to a named `target` status. Leaving `SETUP` for `REGISTRATION` requires that at least one division already exist for the league. Each advance increments the league's `version` by 1. Advances out of order, or advances whose preconditions are unmet, are rejected with `ERR_INVALID_STATE`.

### 3.2. Family Accounts and Player Registration

A family account is created by a `ParentGuardian` (for their own family) or by a `LeagueAdmin`. A `Family` belongs to a league via `league_id` and is created with a `guardian_email`, a `guardian_name`, and a refundable `volunteer_deposit_cents` posted at registration. The family's accrued `volunteer_credit_cents` begins at 0 and, by construction, can never exceed the posted deposit. The `guardian_email` must be unique within the league; a second family attempting to reuse an email already present in that league is rejected with `ERR_DUPLICATE_FAMILY_EMAIL`.

Player registration is open to a `ParentGuardian` (registering their own child under their own family) or a `LeagueAdmin`, and is only legal while the league is in `REGISTRATION` and the current clock instant falls within the half-open window from `registration_open_iso` up to but not including `registration_close_iso`. A registration mutation attempted outside that window is rejected with `ERR_REGISTRATION_WINDOW_CLOSED`. A `Player` is created with its `league_id`, the registering `family_id`, the requested `division_id`, a `full_name`, a `birth_date` as `'YYYY-MM-DD'`, and optionally a `birth_certificate_ref` document reference. The player starts in status `REGISTERED`, and registering one recomputes the league's `total_registered_players` upward and increments the league's `version`.

On registration the system computes the player's `league_age`. League age is the number of completed years from `birth_date` to the league's `age_cutoff_date`: take the cutoff year minus the birth year, and if the player's birth month-and-day falls after the cutoff's month-and-day, subtract one additional year because the player has not yet had their birthday relative to the cutoff. The result is a whole number of years.

A player who is no longer participating may be withdrawn by a `LeagueAdmin`, moving them to the terminal `WITHDRAWN` status and recomputing the league's `total_registered_players` downward (a decrease of one). Withdrawal is reachable from `REGISTERED`, from `AGE_VERIFIED`, and from `EVALUATED`. Withdrawing a `REGISTERED` or `AGE_VERIFIED` player carries no further precondition, but withdrawing an `EVALUATED` player is permitted only if that player holds no `ACTIVE` draft pick — an undrafted player. Because withdrawal is a registration mutation, it is legal only while the owning league is in `REGISTRATION` (otherwise `ERR_INVALID_STATE`, checked before the window) and is further confined to the open registration window (otherwise `ERR_REGISTRATION_WINDOW_CLOSED`).

### 3.3. Age Verification and Evaluation

Before a player can advance, a `LeagueAdmin` verifies their age, moving a `REGISTERED` player to `AGE_VERIFIED`. Verification requires that the player's `birth_certificate_ref` be present (non-null) — a player may not leave `REGISTERED` without proof of birth date. Verification also rechecks eligibility: the player's `league_age` must fall within the inclusive band of their division, at least the division's `min_league_age` and at most its `max_league_age`. A player whose league age falls below the minimum or above the maximum is rejected with `ERR_AGE_OUT_OF_RANGE`. A successful verification increments the player's `version`.

Once the league has advanced to `EVALUATION`, a `LeagueAdmin` records evaluation scores, moving an `AGE_VERIFIED` player to `EVALUATED`. Evaluation requires the league to be in `EVALUATION` and requires all three raw scores — `eval_speed`, `eval_hitting`, and `eval_fielding` — to be provided, each an integer from 20 to 80 inclusive. From these the system computes the player's `eval_score` as a weighted blend: hitting contributes half its value, fielding contributes three-tenths of its value, and speed contributes two-tenths of its value (that is, `eval_hitting` times 0.50, plus `eval_fielding` times 0.30, plus `eval_speed` times 0.20). This blended score is rounded half up to two decimal places exactly once, at this step. The rounded `eval_score` then determines the player's draft `tier`: a score of at least 70.00 is tier `A`; otherwise a score of at least 55.00 is tier `B`; otherwise a score of at least 40.00 is tier `C`; any lower score is tier `D`. The lower bounds are inclusive. Evaluation increments the player's `version`.

Advancing the league from `EVALUATION` to `DRAFT` requires that every non-withdrawn player be in `EVALUATED` status — none may still be `REGISTERED` or `AGE_VERIFIED`. The advance sets `draft_round_index` to 0 and increments the league's `version`.

### 3.4. The Snake Draft

With the league in `DRAFT`, teams select evaluated players one pick at a time. A draft pick may be recorded by a `LeagueAdmin` or by the owning `Coach` (whose `X-User-ID` must equal the team's `coach_user_id`). The request supplies the `league_id`, the selecting `team_id`, the chosen `player_id`, and the `expected_league_version` described in §2.11. A successful pick creates a `DraftPick` carrying its `league_id`, `team_id`, and `player_id`, with a system-assigned `round_number` and `overall_number`, and an initial status of `ACTIVE`.

Pick order follows the snake rule within the division. Order the division's teams by `draft_slot` ascending (the slot is unique and is always the ordering key — never the `id`); let the team count be the number of teams in the division. Count the picks already made in the division as the number of `ACTIVE` draft picks there. The current round number is that pick count divided by the team count, taken as a whole number (floor), plus 1; the zero-based position within the round is the pick count modulo the team count. When `draft_snake` is true and the round number is even, the expected `draft_slot` is the team count minus the zero-based position (the round runs in reverse); otherwise the expected `draft_slot` is the zero-based position plus 1 (the round runs forward). The submitting team's `draft_slot` must equal that expected slot; if it does not, the pick is rejected with `ERR_NOT_YOUR_PICK`. The `overall_number` assigned to the pick is the prior pick count plus 1, and `round_number` is the round computed above.

Recording a pick drives the selected player from `EVALUATED` to `DRAFTED`: the player's `team_id` is set to the drafting team, the team's `roster_count` rises by 1, and the player's `version` increments. The draft may not push a team past its division's `roster_cap`; a pick that would make `roster_count` reach or exceed the cap is rejected with `ERR_ROSTER_FULL`. Each recorded pick advances the league's `version`, which is what makes the `expected_league_version` check meaningful across the shared sequence.

A `LeagueAdmin` may undo a mistake by voiding a pick while the league is in `DRAFT`. Only the most recent `ACTIVE` pick — the one with the highest `overall_number` — may be voided; an attempt to void any earlier pick is rejected with `ERR_NOT_LAST_PICK`. The pick must itself be `ACTIVE`. Voiding moves the `DraftPick` to the terminal `VOIDED` status and reverts the player from `DRAFTED` back to `EVALUATED`: the player's `team_id` is cleared to null and the team's `roster_count` falls by 1, with the player's `version` incrementing on the revert. This revert is the cyclic edge of the player lifecycle. Voiding a pick also advances the league's `version`.

Advancing the league from `DRAFT` to `SEASON` requires that every non-withdrawn player be `DRAFTED` or `ROSTERED` — no evaluated player may remain undrafted. The advance cascades every `DRAFTED` player to `ROSTERED` (each such player's `version` increments) and increments the league's `version`.

### 3.5. Scheduling and Playing Games

Games are scheduled by a `LeagueAdmin` once teams exist. A `Game` is created with its `league_id`, the `division_id` both teams share, a `home_team_id` and an `away_team_id`, the `field_id` venue, the scheduled `start_iso` (inclusive) and `end_iso` (exclusive), and optionally a `game_type` that defaults to `REGULAR` and may instead be `PLAYOFF`. When `game_type` is `PLAYOFF`, a `playoff_round` (the 1-based bracket round) is required; for regular games it is null. The game begins `SCHEDULED` with a `rainout_count` of 0, `home_runs` and `away_runs` null, and `winner_team_id` null.

At creation, and again at reschedule, the new time window is checked against the field for conflicts. Treat each existing non-terminal game on the same field as occupying a buffered window: subtract the field's `turnover_buffer_minutes` from its start and add the same buffer to its end. The new game `[start_iso, end_iso)` conflicts with such an existing game when the new start falls before the existing game's buffered end and the existing game's buffered start falls before the new end — that is, the buffer is applied symmetrically on both sides, so games may not be packed closer than the turnover gap. A touch exactly at a buffered boundary does not conflict (the comparison is strict). Only games whose status is not `FINAL`, `FORFEITED`, or `RAINED_OUT` occupy the field for this purpose. A conflicting slot is rejected with `ERR_FIELD_SLOT_CONFLICT`.

Starting a game moves it from `SCHEDULED` to `IN_PROGRESS` and is performed by a `LeagueAdmin` only while the league is in `SEASON` or `PLAYOFFS`. A game may not start unless at least one of its referee assignments is `CONFIRMED` or `CHECKED_IN`; starting without a confirmed umpire is rejected with `ERR_NO_REFEREE_CONFIRMED`. Starting increments the game's `version`.

Finalizing a game moves it from `IN_PROGRESS` to the terminal `FINAL` and is performed by a `LeagueAdmin`, who supplies the final `home_runs` and `away_runs`. Both run totals must be provided and non-negative, and they must differ — ties are not allowed and equal scores are rejected with `ERR_TIE_NOT_ALLOWED`. Finalizing sets `winner_team_id` to the team with more runs and updates both teams' standings: the winner's `wins` and the loser's `losses` each rise by 1, and each team's `run_differential` absorbs its own runs minus its opponent's runs. If the game is a `PLAYOFF` game, the losing team is eliminated — no further bracket games are created for it — while the winner advances through the bracket. Finalizing increments the game's `version`.

### 3.6. Rainouts, Makeups, and Forfeits

When weather intervenes, a `LeagueAdmin` rains out a `SCHEDULED` game while the league is in `SEASON` or `PLAYOFFS`, moving it to `RAINED_OUT`. The rainout releases the umpires: every `PROPOSED` or `CONFIRMED` referee assignment on the game transitions to `RELEASED` (each released assignment increments its own `version`). Any `PLEDGED` volunteer commitments on the game stay `PLEDGED` and carry over to the makeup. The rainout increments the game's `version`.

A rained-out game returns to play through a reschedule, performed by a `LeagueAdmin`, which moves it from `RAINED_OUT` back to `SCHEDULED` at a new slot. The reschedule supplies a new `start_iso` and `end_iso` and the `expected_game_version` described in §2.11. The makeup window is re-checked for field conflicts using the same buffered-overlap rule as creation, and a conflicting makeup is rejected with `ERR_FIELD_SLOT_CONFLICT`. A successful reschedule updates `start_iso` and `end_iso` to the makeup slot, raises `rainout_count` by 1, and increments the game's `version`. This SCHEDULED → RAINED_OUT → SCHEDULED cycle is what makes the game lifecycle cyclic.

A `SCHEDULED` game may instead be forfeited by a `LeagueAdmin`, who names the `forfeiting_team_id`; this moves the game to the terminal `FORFEITED` status with no precondition. The forfeit sets `winner_team_id` to the non-forfeiting team and adjusts standings — the non-forfeiting team gains a win and the forfeiting team a loss — while `run_differential` is left unchanged. As with a rainout, every non-terminal referee assignment on the game transitions to `RELEASED`. The forfeit increments the game's `version`.

### 3.7. Referee Assignments

A `LeagueAdmin` proposes an umpire for a game by creating a `RefereeAssignment`, supplying the `game_id`, the `referee_id`, and optionally a `role` that defaults to `PLATE` and may instead be `BASE`. The assignment begins in `PROPOSED`.

The named referee then acts on their own assignment. A `Referee` confirms a `PROPOSED` assignment, moving it to `CONFIRMED`, subject to two checks evaluated in this fixed order (matching §2.7). First, the referee may not be double-booked in time: confirming is rejected with `ERR_REFEREE_TIME_CONFLICT` if the referee has any other `CONFIRMED` or `CHECKED_IN` assignment whose game's time window overlaps this game's window. Second, the referee may not exceed their `max_games_per_day`: confirming is rejected with `ERR_REFEREE_DAY_LIMIT` if the referee already holds that many `CONFIRMED` or `CHECKED_IN` assignments on the game's UTC calendar day. That time overlap uses the bare game intervals with no buffer — two assignments conflict when this game's start falls before the other game's end and the other game's start falls before this game's end; touching exactly at a boundary does not conflict. Confirming increments the assignment's `version`.

A `Referee` may instead decline a `PROPOSED` assignment, moving it to the terminal `DECLINED` status. A `Referee` checks in to a `CONFIRMED` assignment, moving it to `CHECKED_IN`, provided the owning game is `IN_PROGRESS` or `SCHEDULED`. Both transitions increment the assignment's `version`. Separately, a `LeagueAdmin` may release a `CONFIRMED` assignment, moving it to the terminal `RELEASED` status; releases also occur as the cascade from game rainout and forfeit described above. A `PROPOSED` assignment may likewise be moved to `RELEASED` as part of those same cascades. Every such transition increments the assignment's `version`.

### 3.8. Volunteer Commitments and Season Close

Parents earn back their deposit by volunteering. A `ParentGuardian` (for their own family) or a `LeagueAdmin` pledges a shift by creating a `VolunteerCommitment` against a game, supplying the `game_id`, the `family_id`, a `role` that is one of `SCOREKEEPER`, `CONCESSIONS`, or `FIELD_PREP`, and the `credit_cents` refundable value of the shift fixed at creation. The commitment begins `PLEDGED`.

After the game has been played, a `LeagueAdmin` settles each pledged shift, but only once the owning game is `FINAL`. Fulfilling a commitment moves it from `PLEDGED` to the terminal `FULFILLED` status and credits the family: the family's `volunteer_credit_cents` becomes the smaller of (its current credit plus this commitment's `credit_cents`) and the family's posted `volunteer_deposit_cents`. The cap is applied on each fulfillment as the running credit accrues, not as a single cap at season end, so a family's credit never exceeds its deposit. Fulfilling increments the commitment's `version`. Alternatively, a `LeagueAdmin` marks a pledged shift as a no-show — also only when the owning game is `FINAL` — moving it to the terminal `NO_SHOW` status; a no-show accrues no credit and increments the commitment's `version`.

Advancing the league from `SEASON` to `PLAYOFFS` requires that no regular-season game remain unplayed: no `REGULAR` game may still be `SCHEDULED` or `IN_PROGRESS` (only the `SCHEDULED` and `IN_PROGRESS` statuses block the advance; a `REGULAR` game in any other status — `FINAL`, `FORFEITED`, or `RAINED_OUT` — does not). The advance computes each team's playoff `seed` within its division and increments the league's `version`. Seeding ranks the teams in a division using each team's accumulated standings — its stored `wins`, `losses`, and `run_differential` as they stand at the moment of the advance (these reflect all `FINAL` regular-season results plus any forfeit wins and losses; no playoff games have been finalized yet at this transition). A team's win percentage is its `wins` divided by the sum of its `wins` and `losses`, treated as 0 when it has played no decided games. The seeding has two variants. When `draft_snake` is true (the default competitive bracket), teams are ranked primarily by win percentage descending; ties are then broken by `run_differential` descending, and any remaining ties by `created_at` ascending (never by `id`). When `draft_snake` is false (the recreational bracket), the primary key is instead total `wins` descending — raw win count rather than win percentage — with the same secondary tiebreakers of `run_differential` descending then `created_at` ascending. Seeds run 1 upward within each division.

Advancing the league from `PLAYOFFS` to the terminal `CLOSED` status requires that no `PLAYOFF` game remain `SCHEDULED` or `IN_PROGRESS`. Closing settles every family's refund. For one family, gather its `FULFILLED` volunteer commitments in `created_at` ascending order; for each, compute a 5% administrative fee on that commitment's `credit_cents`, rounded half up to a whole number of cents, and add the commitment's credit minus that fee to a running net total. The fee is rounded per commitment and then the net amounts are summed — the fee is never computed on a pre-summed total. The family's refund is the smaller of that running net total and the family's `volunteer_deposit_cents`. This settled refund is written back to the family's `volunteer_credit_cents` field, replacing the accrued credit, and each settled family's `version` increments. Closing increments the league's `version`.

### 3.9. Test-Driving the Clock

For deterministic testing of the time-window rules, a `LeagueAdmin` may use an admin-only capability that sets the server's current UTC instant to a supplied `now_iso`. This logical clock is what the registration-window check and any other time comparison consult.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or modify an existing one — including lifecycle advances, state transitions, and settlement actions — return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/leagues` | Create a league (status SETUP) | LeagueAdmin |
| GET | `/leagues/{leagueId}` | Get a league | LeagueAdmin, Coach, Referee, ParentGuardian |
| POST | `/leagues/{leagueId}/advance` | Advance the league lifecycle to a target status | LeagueAdmin |
| POST | `/_clock/set` | Test-driving: set the server's current UTC instant | LeagueAdmin |
| POST | `/divisions` | Create a division | LeagueAdmin |
| GET | `/divisions` | List divisions (filterable by league) | LeagueAdmin, Coach, Referee, ParentGuardian |
| GET | `/divisions/{divisionId}` | Get a division | LeagueAdmin, Coach, Referee, ParentGuardian |
| POST | `/families` | Create a family with a refundable volunteer deposit | LeagueAdmin, ParentGuardian |
| GET | `/families` | List families (filterable by league) | LeagueAdmin, ParentGuardian |
| GET | `/families/{familyId}` | Get a family | LeagueAdmin, ParentGuardian |
| POST | `/players` | Register a player (status REGISTERED) | LeagueAdmin, ParentGuardian |
| GET | `/players` | List players (filterable) | LeagueAdmin, Coach, ParentGuardian |
| GET | `/players/{playerId}` | Get a player | LeagueAdmin, Coach, ParentGuardian |
| POST | `/players/{playerId}/verify-age` | Verify a player's age (REGISTERED → AGE_VERIFIED) | LeagueAdmin |
| POST | `/players/{playerId}/evaluate` | Record evaluation scores (AGE_VERIFIED → EVALUATED) | LeagueAdmin |
| POST | `/players/{playerId}/withdraw` | Withdraw a player (→ WITHDRAWN) | LeagueAdmin |
| POST | `/teams` | Create a team in a division | LeagueAdmin |
| GET | `/teams` | List teams (filterable) | LeagueAdmin, Coach, Referee, ParentGuardian |
| GET | `/teams/{teamId}` | Get a team (standings and seed) | LeagueAdmin, Coach, Referee, ParentGuardian |
| POST | `/draft-picks` | Record a snake-draft pick | LeagueAdmin, Coach |
| GET | `/draft-picks` | List draft picks (filterable) | LeagueAdmin, Coach |
| GET | `/draft-picks/{pickId}` | Get a draft pick | LeagueAdmin, Coach |
| POST | `/draft-picks/{pickId}/void` | Void the most recent active draft pick | LeagueAdmin |
| POST | `/fields` | Create a field/venue | LeagueAdmin |
| GET | `/fields` | List fields (filterable by league) | LeagueAdmin, Coach, Referee, ParentGuardian |
| GET | `/fields/{fieldId}` | Get a field | LeagueAdmin, Coach, Referee, ParentGuardian |
| POST | `/referees` | Register a referee in the league pool | LeagueAdmin |
| GET | `/referees` | List referees (filterable by league) | LeagueAdmin, Referee |
| GET | `/referees/{refereeId}` | Get a referee | LeagueAdmin, Referee |
| POST | `/games` | Schedule a game (status SCHEDULED) | LeagueAdmin |
| GET | `/games` | List games (filterable) | LeagueAdmin, Coach, Referee, ParentGuardian |
| GET | `/games/{gameId}` | Get a game | LeagueAdmin, Coach, Referee, ParentGuardian |
| POST | `/games/{gameId}/start` | Start a game (SCHEDULED → IN_PROGRESS) | LeagueAdmin |
| POST | `/games/{gameId}/finalize` | Finalize a game with scores (IN_PROGRESS → FINAL) | LeagueAdmin |
| POST | `/games/{gameId}/rainout` | Mark a game rained out (SCHEDULED → RAINED_OUT) | LeagueAdmin |
| POST | `/games/{gameId}/reschedule` | Reschedule a rained-out game (RAINED_OUT → SCHEDULED) | LeagueAdmin |
| POST | `/games/{gameId}/forfeit` | Forfeit a scheduled game (SCHEDULED → FORFEITED) | LeagueAdmin |
| POST | `/assignments` | Propose a referee assignment (status PROPOSED) | LeagueAdmin |
| GET | `/assignments` | List assignments (filterable) | LeagueAdmin, Referee |
| GET | `/assignments/{assignmentId}` | Get a referee assignment | LeagueAdmin, Referee |
| POST | `/assignments/{assignmentId}/confirm` | Confirm own assignment (PROPOSED → CONFIRMED) | Referee |
| POST | `/assignments/{assignmentId}/decline` | Decline own assignment (PROPOSED → DECLINED) | Referee |
| POST | `/assignments/{assignmentId}/check-in` | Check in to own assignment (CONFIRMED → CHECKED_IN) | Referee |
| POST | `/assignments/{assignmentId}/release` | Release a confirmed assignment (CONFIRMED → RELEASED) | LeagueAdmin |
| POST | `/volunteer-commitments` | Pledge a volunteer shift (status PLEDGED) | LeagueAdmin, ParentGuardian |
| GET | `/volunteer-commitments` | List commitments (filterable) | LeagueAdmin, ParentGuardian |
| GET | `/volunteer-commitments/{commitmentId}` | Get a volunteer commitment | LeagueAdmin, ParentGuardian |
| POST | `/volunteer-commitments/{commitmentId}/fulfill` | Fulfill a commitment (PLEDGED → FULFILLED) | LeagueAdmin |
| POST | `/volunteer-commitments/{commitmentId}/mark-no-show` | Mark a commitment no-show (PLEDGED → NO_SHOW) | LeagueAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_FK_SCOPE_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 409 |
| `ERR_AGE_OUT_OF_RANGE` | 422 |
| `ERR_NOT_YOUR_PICK` | 409 |
| `ERR_NOT_LAST_PICK` | 409 |
| `ERR_ROSTER_FULL` | 409 |
| `ERR_NO_REFEREE_CONFIRMED` | 409 |
| `ERR_REFEREE_TIME_CONFLICT` | 409 |
| `ERR_REFEREE_DAY_LIMIT` | 409 |
| `ERR_FIELD_SLOT_CONFLICT` | 409 |
| `ERR_TIE_NOT_ALLOWED` | 422 |
| `ERR_DUPLICATE_FAMILY_EMAIL` | 409 |
| `ERR_STALE_LEAGUE_VERSION` | 412 |
| `ERR_STALE_GAME_VERSION` | 412 |
