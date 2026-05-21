# Fantasy Football League API — Product Requirements Document

## 1. Introduction

The Fantasy Football League API powers a season-long competitive product in which a small group of friends, coworkers, or strangers operate franchise teams that draft real-world NFL players, set weekly lineups, trade and bid against each other for talent, and ultimately crown a champion through a single-elimination playoff bracket. The system must hold together three very different rhythms at once: the high-pressure burst of a live draft (whether English-auction or snake-order), the deliberative back-and-forth of trade negotiation and league-wide veto voting, and the steady week-by-week cadence of lineup locks, injury substitutions, waiver settlement, and scoring.

Two operator personas drive the system. A league-level **Commissioner** is the operational backbone — they create the league, register players into the catalog, advance the league clock that gates every time-sensitive cascade, run waiver sweeps, and submit the per-starter scores that close out each week. Per-team **Managers** make the actual game-play decisions: declaring keepers before draft day, drafting players when their pick comes up, setting their starting lineups, submitting FAAB waiver bids, proposing trades to their rivals, and voting to veto trades they consider unfair. The API exists to keep these two roles in honest tension — Managers compete inside rules the Commissioner enforces, and every consequential transition (locks, sweeps, trade execution, playoff seeding) is reproducible because it is gated by an explicit, server-tracked logical clock rather than wall time.

Two design tensions shape the requirements that follow. First, dollars and players in this system can move along multiple paths — auction bids, FAAB waiver bids, FAAB-included trades, and keeper carry-overs — and the same balance is touched by all of them, so debit ordering and refund semantics have to be exact. Second, almost every state change in the system is allowed to cascade: a single clock advance can fire weekly locks, inject injury replacements into starting lineups, sweep a backlog of waiver claims, execute a backlog of expired trades, cancel waiver bids for players who just got traded, and advance the league's lifecycle from regular season into the playoff bracket. The behavior of these cascades — what fires, in what order, and what each cascade leaves behind — is the core thing this PRD specifies.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply uniformly to every endpoint in the API. Section 3 layers domain workflows on top of these.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the role the user is acting under. Requests missing either header are rejected with `ERR_AUTH_MISSING`. The system recognizes exactly two role names — `Commissioner` and `Manager` — and any other value submitted in `X-User-Role` is rejected with `ERR_AUTH_INVALID_ROLE`. Once authentication passes, role-based authorization is applied according to the RBAC implied by §4: a header pair that authenticates correctly but maps to a role not permitted for the requested endpoint yields `ERR_FORBIDDEN`.

The two roles differ in how their `X-User-ID` is interpreted. When `X-User-Role` is `Commissioner`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. When `X-User-Role` is `Manager`, `X-User-ID` is the value stored in `Team.manager_user_id` for the acting franchise; ownership-gated actions resolve the acting `Manager`'s `team_id` by looking up the `Team` whose `manager_user_id` equals `X-User-ID`, and any operation that targets a `team_id` other than the one the acting `Manager` owns is rejected with `ERR_NOT_TEAM_OWNER`.

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

List endpoints accept two optional query parameters. The `limit` parameter caps the number of items in a single response: its default is 10, its minimum is 1, and its maximum is 100. The `offset` parameter declares how many items to skip and defaults to 0. Pagination parameters outside these bounds are rejected with `ERR_VALIDATION`.

Unless an endpoint explicitly states otherwise, list endpoints sort results by the resource's `created_at` ascending. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside its `meta` envelope.

### 2.4. Common Resource Properties

Most primary entities carry a uniform set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits — `created_at` is set once at creation, and `updated_at` is refreshed on every mutation. `version` is an integer that begins at 1 (or whatever the initial mutation count yields) and is incremented by one on every mutation of the resource.

Two entities in this system are immutable-with-respect-to-update once written and therefore omit `updated_at` and `version` entirely: `DraftPick` and `TradeVote`. These two carry `id` and `created_at` only. Every other entity — `League`, `Team`, `Player`, `RosterSlot`, `WaiverClaim`, `TradeProposal`, `MatchupWeek`, `KeeperDesignation` — carries the full set.

### 2.5. The League Logical Clock

Wall-clock time has no causal authority in this API. Every time-sensitive event — weekly lineup locks, waiver settlement, trade review expiry, and the lifecycle transition from regular season into the playoff bracket — is gated by the per-league logical clock stored on `League.now_ts`. The clock is never advanced by background timers. It is advanced only by an explicit Commissioner-only test-driving capability that takes a `target_ts` instant and sets `League.now_ts` to it, while running every cascade that was due before-or-at the new instant. The order in which these cascades fire inside a single clock-advance is fixed and exposed to the implementer in §3: weekly locks fire first, then waiver settlement runs for every claim whose `settle_ts` is reached, then trade reviews execute or expire as their `review_deadline_ts` is crossed, and finally a regular-season-to-playoffs transition may be evaluated.

While the league is in `DRAFT_PENDING` or `DRAFTING`, `current_week` is 0. It becomes 1 at the entry into `REGULAR_SEASON` and is incremented by one each time every `MatchupWeek` row for the current `week_number` has reached `SCORED`. When the final bracket round is scored, `current_week` is advanced to `regular_season_weeks + log2(playoff_team_count) + 1` as a sentinel.

### 2.6. Hierarchical Consistency and Cascades

Mutations in this system frequently change more than one resource. When a clock advance crosses the weekly lock instant of a scheduled `MatchupWeek`, the matchup transitions from `SCHEDULED` to `LOCKED`, the system snapshots every starter `RosterSlot` on both teams, sets each affected `RosterSlot.locked_until_ts` to the end of the week, and runs injury replacement for any starter whose `Player.status_tag` is `OUT`. When that same clock advance crosses the `review_deadline_ts` of an accepted trade with no winning veto, the trade transitions to `EXECUTED`, players and FAAB move between rosters, and every still-`PENDING` `WaiverClaim` whose `add_player_id` was a traded player is set to `CANCELED` carrying the error identifier `ERR_PLAYER_NO_LONGER_ELIGIBLE` — a two-step cascade originating in trade execution and terminating in a waiver-claim status update. When a waiver sweep awards a claim, every other still-`PENDING` claim for the same `add_player_id` is transitioned to `LOST` in the same sweep.

Every cascade that mutates a non-immutable resource refreshes that resource's `updated_at` and increments its `version`. This holds whether the mutation was directly initiated by the client or fired as a downstream cascade — a parent transition that cascades to children mutates the children just as if the children were mutated by an explicit request.

### 2.7. Nested Resource Resolution

URL paths in this API frequently nest a child under a parent — for example, `/leagues/{league_id}/teams/{team_id}`, `/teams/{team_id}/keepers/{keeper_id}`, or `/leagues/{league_id}/matchups/{week_number}/score`. Path identifiers are validated strictly left-to-right: a request for a child resource under a non-existent parent fails at the parent with `ERR_RESOURCE_NOT_FOUND` before the child is even consulted. The same principle applies to body-referenced foreign keys (such as `add_player_id`, `drop_player_id`, `send_player_ids`, `receive_player_ids`, `voting_team_id`, `proposing_team_id`, `counterparty_team_id`, `home_team_id`, `away_team_id`): a body whose foreign key points at a non-existent row is rejected with `ERR_REFERENCE_NOT_FOUND`, distinct from the 404 that applies to path identifiers.

### 2.8. Optimistic Concurrency Control

Any mutation that targets a single existing resource by its `id` may carry the resource's most recently observed `version` in the request body. If the supplied `version` differs from the value currently on the server, the request is rejected with `ERR_VERSION_CONFLICT`. If the body omits the `version` field altogether, the server skips the concurrency check and processes the mutation unconditionally. This applies, in particular, to `PATCH /teams/{team_id}/roster-slots/{slot_id}`, where a `Manager` typically reads the current slot, modifies it, and submits the mutation with the version they observed.

### 2.9. Validation Ordering

Validations are applied in a fixed priority order so that the error returned to the client is always the most fundamental violation present. The order, from highest priority to lowest, is: (1) presence of the auth headers `X-User-Role` and `X-User-ID`, surfaced as `ERR_AUTH_MISSING`; (2) recognition of the role name, surfaced as `ERR_AUTH_INVALID_ROLE`; (3) per-endpoint role authorization, surfaced as `ERR_FORBIDDEN`; (4) existence of path-referenced resources, left-to-right, surfaced as `ERR_RESOURCE_NOT_FOUND`; (5) existence of body-referenced foreign keys, surfaced as `ERR_REFERENCE_NOT_FOUND`; (6) team ownership for ownership-gated actions, surfaced as `ERR_NOT_TEAM_OWNER`; (7) state-machine preconditions, surfaced as `ERR_INVALID_STATE`; and (8) business safety, referential, constraint, temporal, and fiscal checks specific to the endpoint, each carrying its own error identifier as scattered through §3. Field-shape validation (`ERR_VALIDATION`) and version conflict (`ERR_VERSION_CONFLICT`) operate at the lowest priority — they only surface after every earlier check would have passed.

### 2.10. Numeric Precision and Rounding

All monetary balances and bid amounts in this system are integer dollars. `Team.faab_balance_dollars`, `Team.auction_balance_dollars`, `WaiverClaim.bid_dollars`, `DraftPick.price_dollars`, `KeeperDesignation.assigned_price_dollars`, `TradeProposal.send_faab_dollars`, and `TradeProposal.receive_faab_dollars` are all integers with no fractional component; addition and subtraction over them remains in integers and never requires rounding.

Scoring is the one place where decimals appear. `MatchupWeek.home_points` and `MatchupWeek.away_points` are stored to exactly two decimal places using "round half up". Critically, the rounding happens exactly once per team per week, after the sum of all that team's starter contributions has been computed — implementations that round each starter's contribution first and then sum the rounded values are wrong. `Team.points_for` is then the running sum of already-rounded per-week team totals.

Two calculations apply ceiling-style rounding. The keeper auction inflation calculation in §3 applies a ceiling once at the end of multiplication (multiply-then-ceiling, never ceiling-then-multiply). The trade veto percentage is computed via integer floor division — see §3 for the exact derivation, which is rounding-toward-zero rather than rounding-half-up.

### 2.11. FAAB and Auction Budget Principles

FAAB ("Free Agent Acquisition Budget") is a per-team season-long pool seeded at league activation from `League.faab_budget_dollars` and never automatically refilled. `Team.faab_balance_dollars` is initialized to that value when the `Team` row is created and is decremented only when a `WaiverClaim` is `AWARDED` (it is never decremented at claim submission). FAAB can also flow between teams as part of a trade execution, in which case the deduction and addition both happen atomically when the trade transitions to `EXECUTED`.

Auction dollars are a separate, draft-only resource that exists only when `League.draft_mode` is `AUCTION`. `Team.auction_balance_dollars` is set to `League.auction_budget_dollars` at the entry into `DRAFTING`, debited by `KeeperDesignation.assigned_price_dollars` for each locked keeper at that same transition, and debited by `DraftPick.price_dollars` for every auction pick made during the draft. The default for `League.auction_budget_dollars` is 200; for `SNAKE` leagues, this field has no operational effect.

Both balances must remain non-negative at every point in their lifetime.

### 2.12. Logical Clock and Test-Driving Endpoints

In addition to the clock-advance capability described in §2.5, the API exposes two further test-driving capabilities for deterministic test scenarios. A Commissioner-only waiver settlement capability accepts no body and runs the waiver sweep immediately for the league, applying the same algorithm as a clock-advance crossing a `settle_ts` boundary. A Commissioner-only player status capability lets the Commissioner flip a `Player.status_tag` (and optionally update `weekly_proj_points`) at any time, so injury cases can be set up before a lock fires. None of these test-driving capabilities advance wall time — only the clock-advance capability mutates `League.now_ts`.

## 3. Business Logic & Workflows

### 3.1. League Creation and Setup

A `Commissioner` opens the season by creating a new league. The creation payload carries everything that is static for the season's rules: a display `name` (1 to 80 characters), the `season_year` the league is playing (which must be 2020 or later), a `draft_mode` of either `SNAKE` or `AUCTION`, a `scoring_mode` of `STANDARD`, `HALF_PPR`, or `PPR`, a `team_count` that must be an even number in the inclusive range 4 to 16, a `roster_size` between 12 and 20 inclusive, a `starter_count` between 7 and 11 inclusive, an `ir_slots` count between 0 and 4 inclusive, a `faab_budget_dollars` value that must be in the inclusive range 0 to 1000, an optional `auction_budget_dollars` in the inclusive range 0 to 500 (defaulting to 200, and operationally meaningful only when `draft_mode` is `AUCTION`), a `keeper_mode` of `NONE`, `REDRAFT`, or `DYNASTY`, an optional `keeper_cap` defaulting to 0 (constrained to be in the inclusive range 0 to one less than `roster_size`), an optional `veto_quorum_pct` defaulting to 50 (in the inclusive range 25 to 100), an optional `trade_review_hours` defaulting to 48 (in the inclusive range 0 to 168), an optional `waiver_period_hours` defaulting to 48 (in the inclusive range 0 to 168), a `playoff_team_count` that must be exactly one of 2, 4, or 8, and a `regular_season_weeks` in the inclusive range 10 to 14. Field-shape and range violations are rejected with `ERR_VALIDATION`.

The newly created league is born in `DRAFT_PENDING` with `current_week` set to 0 and `now_ts` initialized to the league's `created_at` instant. After creation, the `Commissioner` registers franchises by adding `Team` rows under the league. Each team carries a display `name` between 1 and 60 characters that must be unique within the league, and a `manager_user_id` that the system will subsequently use to resolve "the acting Manager" for that team. The team's `faab_balance_dollars` is initialized at team creation to the league's `faab_budget_dollars`, its `auction_balance_dollars` starts at 0 (and is reset to `League.auction_budget_dollars` at the entry into `DRAFTING` if the league is `AUCTION`), `wins`, `losses`, and `points_for` start at 0, and `standing_seed` is null until the regular season completes. `draft_position` is null while the league is still `DRAFT_PENDING` and is assigned by the server (taking values 1 through `team_count`) when the league transitions to `DRAFTING`.

Players in the catalog are created and edited by the `Commissioner` only. Each `Player` carries a `full_name`, an `nfl_team` abbreviation (such as `KC`), a `position` drawn from `QB`, `RB`, `WR`, `TE`, `K`, `DST`, or `FLEX_RWT`, a health `status_tag` (initialized to `ACTIVE`, one of `ACTIVE`, `QUESTIONABLE`, `OUT`, or `IR_ELIGIBLE`), and an optional `weekly_proj_points` projection (defaulting to 0) used downstream by both injury replacement selection and waiver tiebreaking. The Commissioner can flip a player's `status_tag` (and optionally re-project `weekly_proj_points`) at any time; this has no immediate roster effect, but the value is read at the next weekly lock to drive injury replacement.

### 3.2. Keepers and the Carry-Over Economy

If `keeper_mode` is `REDRAFT` or `DYNASTY`, a `Manager` may declare keepers before the draft starts. A declaration submits a `player_id` and a `season_year` (which must match the league's `season_year`) under the manager's team, and the system creates a `KeeperDesignation` row in `DECLARED`. Each team's outstanding declarations may not exceed `League.keeper_cap`; a declaration that would push the team above the cap is rejected with `ERR_KEEPER_CAP_EXCEEDED`. While the league remains in `DRAFT_PENDING`, the owning `Manager` may revoke a `DECLARED` keeper, transitioning it to `REVOKED`; the revoke action requires that the acting manager own the keeper's team and that the league is still `DRAFT_PENDING`. A revoked designation never converts.

The cost of each keeper is computed eagerly at declaration time so the manager can see what the carry-over will charge them. The two cost forms depend on `draft_mode`. For `SNAKE` leagues, the system computes `assigned_round`: it looks up the prior-season `DraftPick.round_number` for this `team_id` and `player_id` pairing if one exists, treats an undrafted free-agent keeper as if they had been picked in round number `regular_season_weeks + 5` (effectively the last round), subtracts 1 from that prior round, and then takes the larger of that result and 1 (so a first-round prior pick still costs at least round 1). For `AUCTION` leagues, the system computes `assigned_price_dollars`: it looks up the prior-season auction `price_dollars` for the same pairing, defaults to 1 if no prior price exists or the prior price was 0, multiplies the prior price by an inflation factor of 1.10, applies a single ceiling rounding at the very end of the multiplication (multiplying first and then taking the ceiling of the product, never the other way around), and takes the larger of that result and 1. While the league is `DRAFT_PENDING`, the `assigned_round` field is null for `AUCTION` leagues and the `assigned_price_dollars` field is null for `SNAKE` leagues.

When the league transitions out of `DRAFT_PENDING` into `DRAFTING`, every `KeeperDesignation` still in `DECLARED` is locked: its status moves to `LOCKED`. For `AUCTION` leagues, the locked keeper's `assigned_price_dollars` is immediately debited from the owning team's `auction_balance_dollars` (a depth-two cascade originating from start-draft and reaching `Team`). For `SNAKE` leagues, the system inserts a `DraftPick` row marked `is_keeper` set to true with `round_number` equal to `assigned_round` and `overall_pick_index` allocated to the round-position the keeper occupies in the snake order. At the entry into `REGULAR_SEASON`, the system transitions every `LOCKED` designation to `CONVERTED` and the kept `player_id` is recorded as a `RosterSlot` for the keeping team during the finish-draft fanout.

### 3.3. The Draft

Starting the draft is a `Commissioner`-only transition from `DRAFT_PENDING` into `DRAFTING`. It requires three things to be true: the count of `Team` rows must exactly equal `League.team_count`, the count of `DECLARED` `KeeperDesignation` rows for each individual team must not exceed `League.keeper_cap`, and the server itself must be the one assigning each team's `draft_position` (which it does at the moment of this transition, taking the values 1 through `team_count`). The transition fans out three side-effects: each team's `auction_balance_dollars` is set to `League.auction_budget_dollars` for `AUCTION` leagues (and to 0 otherwise), every `DECLARED` keeper is locked with its associated price or round commitment as described in §3.2, and the league enters `DRAFTING` with `current_week` still at 0.

Within `DRAFTING`, picks are submitted one at a time by `Manager` accounts. Each `DraftPick` submission references a `team_id` and a `player_id`, and (for `AUCTION` leagues) a `price_dollars`. For `SNAKE` leagues, the system enforces strict turn order: only the team whose pick is next in the snake sequence may submit a pick, and any attempt by a non-next team is rejected with `ERR_NOT_YOUR_TURN`; `AUCTION` leagues skip this check entirely because bids are open. The `round_number` and `overall_pick_index` for a pick are assigned by the system: `round_number` reflects the snake round (1-indexed) for `SNAKE` and is left at 0 for `AUCTION` since rounds are not meaningful there, and `overall_pick_index` is the league-wide sequence number from 1 up through `team_count * (roster_size - ir_slots)` for `SNAKE` (matching creation order for `AUCTION`). The `is_keeper` flag is false on a manually submitted pick; it is only true on the keeper-derived picks inserted at start-draft. For `AUCTION` picks, `price_dollars` is the winning bid and is debited from the team's `auction_balance_dollars` on insert.

Two cross-cutting constraints apply on every pick. First, position eligibility: the `Player.position` must be compatible with the position the team is drafting them into — `FLEX_RWT` covers `RB`, `WR`, and `TE`, and any incompatibility is rejected with `ERR_POSITION_INELIGIBLE`. Second, the auction budget floor: for `AUCTION` picks, the submitted `price_dollars` may not exceed the team's `auction_balance_dollars` minus one dollar per remaining required pick (so the team always retains at least 1 dollar per remaining roster slot it still owes); a violation is rejected with `ERR_AUCTION_BUDGET_EXCEEDED`. Two managers racing to draft the same `player_id` are serialized by a first-writer-wins guarantee on the league-scoped unique `(league_id, player_id)` constraint over `DraftPick`; the loser receives `ERR_PLAYER_ALREADY_DRAFTED`.

Finishing the draft is a separate `Commissioner`-only transition from `DRAFTING` into `REGULAR_SEASON`. It requires that the total `DraftPick` count equals `team_count` multiplied by `(roster_size - ir_slots)`, and that every `DraftPick.player_id` is unique across the league. Its side-effects are sweeping: `current_week` is set to 1, every drafted `(team_id, player_id)` pair is materialized as a `RosterSlot` row with `slot_type` set to `BENCH`, every `LOCKED` `KeeperDesignation` is transitioned to `CONVERTED`, and `MatchupWeek` rows are auto-generated by round-robin scheduling for weeks 1 through `regular_season_weeks` for the regular season.

### 3.4. Rosters and Lineup Setting

Once the league enters `REGULAR_SEASON`, every team holds a roster represented by `RosterSlot` rows. Each slot pairs a `team_id` with a `player_id` and declares a `slot_type` of `STARTER`, `BENCH`, or `IR`. Starter slots additionally carry a `position_label` — values like `QB1`, `RB1`, `RB2`, `WR1`, `WR2`, `WR3`, `TE1`, `K1`, `DST1`, or `FLEX` for a flex slot — while `BENCH` and `IR` slots have `position_label` set to null. A slot also tracks `locked_until_ts`, the moment up to which the slot can be freely mutated; once `League.now_ts` is at or beyond that value, the slot becomes immutable for the rest of the week.

A `Manager` modifies their team's lineup by patching a roster slot: the request body may submit a new `slot_type`, a new `position_label`, or both, along with the optional `version` for OCC. The system enforces four protections on every such patch. (a) If `MatchupWeek.status` for the team's current-week matchup is already `LOCKED` — that is, if the weekly lock has fired — the mutation is rejected with `ERR_LINEUP_LOCKED`. (b) A slot may only carry `slot_type` `IR` when the player it holds has `Player.status_tag` either `OUT` or `IR_ELIGIBLE`; promoting a healthy player to IR is rejected with `ERR_IR_INELIGIBLE`. (c) After the mutation, the team must have exactly `League.starter_count` starter slots, and the bench may not exceed `roster_size - starter_count - ir_slots`; violations surface as `ERR_ROSTER_SHAPE_INVALID`. (d) The per-position starter limits must hold — for a default 10-starter setup, exactly one `QB`, two `RB`, three `WR`, one `TE`, one `FLEX` (where `FLEX` accepts `RB`, `WR`, or `TE`), one `K`, and one `DST`; a violation is rejected with `ERR_POSITION_CONSTRAINT`. The placement must also respect basic position eligibility (`Player.position` matching the slot's `position_label` root, with `FLEX_RWT` players satisfying `FLEX`); incompatible placements yield `ERR_POSITION_INELIGIBLE`.

### 3.5. Weekly Lock, Injury Replacement, and Scoring

The weekly cadence rests on the `MatchupWeek` rows. Each `MatchupWeek` belongs to a league and a `week_number`, has a `home_team_id` and an `away_team_id`, and reaches `LOCKED` and then `SCORED` as the week progresses. It also carries `home_points`, `away_points`, an `is_playoff` flag (true for bracket weeks, false otherwise; defaulting to false), and a `bracket_round` integer (1 for the first playoff round, 2 for the semifinal, and so on; null when `is_playoff` is false).

A clock advance that crosses the configured lock instant of a `SCHEDULED` `MatchupWeek` whose `week_number` equals `League.current_week` transitions the matchup to `LOCKED`, provided the league is currently in `REGULAR_SEASON` or `PLAYOFFS`. The lock side-effect snapshots every starter `RosterSlot` on both teams and writes the end-of-week instant into each affected slot's `locked_until_ts`. While snapshotting, the system runs **injury replacement**: for every starter slot whose `Player.status_tag` is `OUT`, the system searches that team's bench for a replacement candidate. A candidate is any `BENCH` `RosterSlot` on the same team whose player has a `status_tag` that is neither `OUT` nor `IR_ELIGIBLE` and whose position is eligible for the starter's `position_label`. Position eligibility splits into two cases: for any strict starter label (`QB1`, `RB1`, `RB2`, `WR1`, `WR2`, `WR3`, `TE1`, `K1`, `DST1`), the candidate's `Player.position` must match the slot's label root (`RB` for `RB1` or `RB2`, `WR` for any `WR` label, and so on); for a `FLEX` slot, the candidate's position must be `RB`, `WR`, or `TE` regardless of which position originally occupied the slot. Candidates are then ordered by `weekly_proj_points` descending with the player's `id` ascending as a deterministic tiebreaker, and the top candidate is chosen. The swap exchanges both `slot_type` and `position_label` between the injured starter slot and the chosen bench slot, so the bench player becomes the starter and the injured player moves to the bench. If no candidate exists, the injured starter remains a starter and contributes 0 to the team's scoring that week. Two clock-advance calls that both cross the same week's lock boundary are serialized by first-writer-wins on the `MatchupWeek.status` transition from `SCHEDULED` to `LOCKED`; the losing call sees `LOCKED` already in place and is rejected with `ERR_INVALID_STATE`.

Scoring is a `Commissioner`-only action that closes a `LOCKED` week. The Commissioner supplies a `scores` array carrying one entry per starter — each entry containing the `player_id`, the `actual_points` that player earned, and (for `HALF_PPR` and `PPR` modes) the `receptions_credited`. The system computes per-team totals by iterating over each team's `STARTER` `RosterSlot` rows in the snapshot, taking that starter's `actual_points`, adding 0.5 times the `receptions_credited` for `HALF_PPR` mode or 1.0 times the `receptions_credited` for `PPR` mode (and adding nothing for `STANDARD`), and accumulating into a running per-team sum. After both team sums are complete, the system applies "round half up" to two decimal places exactly once per team to produce `home_points` and `away_points`. The winner is the team with the strictly larger rounded points value; a tie goes to whichever team's `id` is lexicographically smaller. The winning team's `wins` and the losing team's `losses` are incremented by 1; both teams' `points_for` are incremented by their respective rounded totals. If the matchup was a playoff and not the final round, the system generates the next-round `MatchupWeek` rows by pairing winners by seed. The matchup transitions to `SCORED`; once every `MatchupWeek` for the current `week_number` is `SCORED`, `current_week` is incremented by 1.

### 3.6. Waivers and FAAB Bidding

Between weeks, managers can attempt to acquire players who are not on any roster by submitting `WaiverClaim` rows. Each claim names a `team_id`, an `add_player_id`, an optional `drop_player_id` (null when no drop is required), a `bid_dollars` value (which may be 0, in which case the claim has the lowest tiebreak priority), and a `settle_ts` — the earliest `League.now_ts` at which the sweep may resolve the claim. When the claim is created the server stamps a `priority_seed`: a tiebreak number where lower wins, seeded from inverse-standings so the team with the worst record gets `priority_seed` 1.

Six validations gate submission. The submitted `settle_ts` must be strictly greater than `League.now_ts` (a same-instant or past `settle_ts` is rejected with `ERR_WAIVER_SETTLE_IN_PAST`). The `bid_dollars` may not exceed the submitting team's current `faab_balance_dollars`; an over-bid is rejected with `ERR_FAAB_INSUFFICIENT`. The submission does not debit FAAB — debits happen only on award. When `League.waiver_period_hours` is greater than 0, the `add_player_id` must currently be in the waivers period — either the player's `status_tag` is `OUT`, or the player was dropped from a roster within the last `waiver_period_hours` hours — and an attempt to bid on a fully-free-agent player is rejected with `ERR_PLAYER_NOT_IN_WAIVERS` (managers are expected to use the free-agent add path for those players instead). The `add_player_id` may not already be on any roster in the league; an attempt to bid on a rostered player surfaces as `ERR_PLAYER_ALREADY_ROSTERED`. When `drop_player_id` is null, the team must currently have at least one open roster slot relative to `League.roster_size`; otherwise the submission is rejected with `ERR_ROSTER_FULL`. Two waiver claims for the same `add_player_id` submitted simultaneously do not race at submit time — both persist as `PENDING`, and resolution is deterministic at sweep time.

Sweep resolution runs through the waiver settlement capability or as a side-effect of a clock advance that reaches a `settle_ts`. The algorithm walks every `PENDING` claim whose `settle_ts` is at or before `League.now_ts`, groups claims by `add_player_id`, and, within each group, sorts claims by `bid_dollars` descending with ties broken by `priority_seed` ascending and a final tiebreak of `created_at` ascending. The sweep then walks the sorted list and selects the first claim whose team still has `faab_balance_dollars` at least equal to its `bid_dollars` and whose team either has roster headroom under `roster_size` or supplied a non-null `drop_player_id`; claims that fail either condition are skipped without being failed. The winning claim transitions to `AWARDED`, the team's `faab_balance_dollars` is decremented by the winning `bid_dollars`, the optional `drop_player_id` is removed from the team's roster, and a fresh `RosterSlot` row is inserted for the `add_player_id` with `slot_type` `BENCH`. Every other still-`PENDING` claim for the same `add_player_id` is transitioned to `LOST` in the same sweep — a depth-two cascade where subsequent sweeps would not reconsider those rows. PENDING claims whose `settle_ts` is still in the future are untouched.

The waiver variant under `League.waiver_period_hours` equal to 0 is distinct: there is no waiver wire at all, so the sweep is skipped entirely; in that variant, a submitted "claim" must be auto-failed (all newly created claims that would have settled in the future become `LOST`) and free-agent adds happen inline at submit time with no FAAB consumed. When `waiver_period_hours` is greater than 0, bids remain blind — no manager can see another's `bid_dollars` until the sweep completes.

The owning `Manager` may also cancel a `PENDING` claim before its `settle_ts` is reached; this requires that the acting manager own the claim's team and that `League.now_ts` be strictly less than the claim's `settle_ts`, and it transitions the claim to `CANCELED`. The system may also cancel a `PENDING` claim itself: when a trade execution moves the claim's `add_player_id` off the free-agent pool, every still-`PENDING` claim for that player is transitioned to `CANCELED` carrying the error identifier `ERR_PLAYER_NO_LONGER_ELIGIBLE`. A trade execution and a concurrent waiver sweep that both touch the same player are serialized per-league at the application boundary by first-writer-wins on the `RosterSlot` row; the losing operation observes that the player is no longer a free agent and the associated claim ends in `LOST` with `ERR_PLAYER_NO_LONGER_ELIGIBLE`.

### 3.7. Trades and the Veto Process

A `Manager` proposes a trade by submitting a `TradeProposal` carrying the `proposing_team_id`, the `counterparty_team_id`, a non-empty `send_player_ids` array (every player on the proposer's current roster), a non-empty `receive_player_ids` array (every player on the counterparty's current roster), and optional `send_faab_dollars` and `receive_faab_dollars` (each defaulting to 0). At most one direction of FAAB may be non-zero: a proposal where both `send_faab_dollars` and `receive_faab_dollars` are non-zero is rejected with `ERR_TWO_WAY_FAAB_FORBIDDEN`. A send-side or receive-side player who is not currently on the relevant team's roster is rejected with `ERR_PLAYER_NOT_ON_ROSTER`, and the same check is re-applied at acceptance time as well. A new proposal is created in `OFFERED` with `veto_count` initialized to 0 and `review_deadline_ts` not yet set.

The counterparty has three open responses. Accepting transitions the proposal from `OFFERED` to `ACCEPTED_PENDING_REVIEW` and is permitted only to a manager whose team equals `counterparty_team_id`; at acceptance time the system re-checks that all `send_player_ids` are still on the proposer's roster, all `receive_player_ids` are still on the counterparty's roster, and the proposer's `faab_balance_dollars` is at least `send_faab_dollars` and the counterparty's is at least `receive_faab_dollars`. On acceptance, the system sets `review_deadline_ts` to `League.now_ts` plus `League.trade_review_hours` hours and resets `veto_count` to 0. Rejecting transitions to `REJECTED` and is also restricted to the counterparty. Canceling transitions to `CANCELED` and is restricted to the proposer; once the trade has moved past `OFFERED`, the proposer can no longer cancel.

During the `ACCEPTED_PENDING_REVIEW` window, every other team in the league — that is, every team other than the proposer and counterparty — may cast a single `TradeVote` carrying a `voting_team_id` and a `vote` of either `VETO` or `APPROVE`. A vote from the proposer or counterparty, or a second vote from a team that has already voted on this trade, is rejected with `ERR_NOT_ELIGIBLE_VOTER`. A vote cast on a trade that is not in `ACCEPTED_PENDING_REVIEW` (because it is still `OFFERED`, or already `VETOED`, `EXECUTED`, `REJECTED`, `EXPIRED`, or `CANCELED`) is rejected with `ERR_TRADE_NOT_OPEN_FOR_VOTING`. Each accepted vote is recorded with the league-clock `cast_at_ts`. Votes are immutable once written: `TradeVote` carries `id`, `trade_proposal_id`, `voting_team_id`, `vote`, and `cast_at_ts`, and no `updated_at` or `version`.

The veto threshold is computed deterministically. The eligible voter pool is `team_count` minus 2 — every team in the league other than the proposer and counterparty. The veto percentage is the count of `VETO` votes for this proposal multiplied by 100 and then integer-divided (floor division, rounding toward zero) by the eligible voter pool. The threshold is considered crossed when this integer percentage is greater than or equal to `League.veto_quorum_pct`. Equality with the quorum counts as crossed; strictly less does not. When the threshold is first crossed by a newly inserted `VETO` vote and the trade is still inside its review window (`League.now_ts` is strictly less than `review_deadline_ts`), the trade transitions immediately from `ACCEPTED_PENDING_REVIEW` to `VETOED` with no player or FAAB movement. Two votes that arrive in quick succession both crossing the threshold are serialized by first-writer-wins on `TradeProposal.status`: whichever vote is processed first crosses the threshold and transitions the trade to `VETOED`, and the second sees the state already changed and is rejected with `ERR_TRADE_NOT_OPEN_FOR_VOTING`.

When a clock advance crosses `review_deadline_ts` on a trade that is still in `ACCEPTED_PENDING_REVIEW`, the system evaluates the proposal. If the veto percentage is strictly below `League.veto_quorum_pct` (and `League.now_ts` is at or beyond `review_deadline_ts`), the trade transitions to `EXECUTED` and its side-effects fan out: each `send_player_ids` entry is moved to the counterparty's roster as `BENCH` with `position_label` null, each `receive_player_ids` entry is moved to the proposer's roster as `BENCH` with `position_label` null, and any non-zero FAAB transfer is applied (the sending team's `faab_balance_dollars` is decremented and the receiving team's incremented by the matching amount, in whichever direction the non-zero value points). As described in §3.6, every still-`PENDING` `WaiverClaim` whose `add_player_id` is one of the traded players is then transitioned to `CANCELED` with `ERR_PLAYER_NO_LONGER_ELIGIBLE` — the second hop of a depth-two cascade originating in the trade. If, however, when the clock crosses `review_deadline_ts`, any of the original preconditions is no longer satisfied (a traded player is no longer on the expected roster, or either team's FAAB is now below the required transfer), the trade transitions to `EXPIRED` with no movement.

### 3.8. The Regular Season → Playoffs → Completion Lifecycle

While the league is in `REGULAR_SEASON`, weekly cadence proceeds as described in §3.5: each week locks at its configured lock instant, each week is scored, and `current_week` ticks forward each time every `MatchupWeek` for that week is `SCORED`. A clock advance whose `target_ts` corresponds to a `target_week` strictly greater than `regular_season_weeks` triggers the transition from `REGULAR_SEASON` to `PLAYOFFS`; this transition requires that every `MatchupWeek` with `week_number` at or below `regular_season_weeks` is `SCORED` and that `current_week` equals `regular_season_weeks`. The transition computes each team's `standing_seed`: teams are sorted by `wins` descending, with `points_for` descending as the first tiebreaker and `Team.created_at` ascending as the final tiebreaker; the sorted teams are numbered from 1 (best) upward, and the value is written to each team's `standing_seed`. The transition then generates the playoff bracket as single-elimination `MatchupWeek` rows for `log2(playoff_team_count)` rounds, taking the top `playoff_team_count` seeds, with `is_playoff` set to true and standard 1-versus-8, 2-versus-7 (and so on) bracket seeding for the first round.

Playoff weeks score the same way as regular-season weeks (with the same lock and injury-replacement cascades from §3.5), and `bracket_round` is set on each generated `MatchupWeek` to 1 for the first playoff round, 2 for the semifinal, and so on. When a non-final playoff matchup is scored, the system generates the next round's `MatchupWeek` rows by pairing winners by seed. When the final-round `MatchupWeek` is `SCORED` and the clock advance crosses past it, the league transitions from `PLAYOFFS` to `COMPLETED` and `current_week` is set to the sentinel value `regular_season_weeks + log2(playoff_team_count) + 1`.

The final lifecycle step is archival. A `Commissioner` may archive a league whose status is `COMPLETED`, transitioning it to `ARCHIVED` (the terminal state). Archival cancels every still-`PENDING` `WaiverClaim` in the league (status to `CANCELED`) and converts every still-open `TradeProposal` (those in `OFFERED` or `ACCEPTED_PENDING_REVIEW`) to `REJECTED`.

## 4. Endpoint Definitions

Operations that create a new resource — a new `League`, `Team`, `Player`, `DraftPick`, `WaiverClaim`, `TradeProposal`, `KeeperDesignation`, or `TradeVote` — return `201 Created`. All other operations, including state-machine transitions, lineup patches, and read operations, return `200 OK`. List endpoints accept the standard `limit` and `offset` query parameters described in §2.3 unless explicitly stated otherwise.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/leagues` | Create a new league in `DRAFT_PENDING`. | Commissioner |
| GET    | `/leagues/{league_id}` | Fetch a league. | Commissioner, Manager |
| POST   | `/leagues/{league_id}/start-draft` | Transition the league from `DRAFT_PENDING` to `DRAFTING`. | Commissioner |
| POST   | `/leagues/{league_id}/finish-draft` | Transition the league from `DRAFTING` to `REGULAR_SEASON`. | Commissioner |
| POST   | `/leagues/{league_id}/archive` | Transition the league from `COMPLETED` to `ARCHIVED`. | Commissioner |
| POST   | `/leagues/{league_id}/_clock/advance` | Test-driving capability: advance `League.now_ts` to a supplied `target_ts` and run all due cascades (weekly locks, waiver sweeps, trade execution/expiry, regular-season → playoffs evaluation). | Commissioner |
| POST   | `/leagues/{league_id}/_waivers/process` | Test-driving capability: run waiver settlement now (also auto-runs on clock advance crossing any `settle_ts`). | Commissioner |
| POST   | `/leagues/{league_id}/teams` | Create a team within a `DRAFT_PENDING` league. | Commissioner |
| GET    | `/leagues/{league_id}/teams` | List teams in the league. | Commissioner, Manager |
| GET    | `/leagues/{league_id}/teams/{team_id}` | Fetch a team. | Commissioner, Manager |
| PATCH  | `/teams/{team_id}/roster-slots/{slot_id}` | Move a player between `STARTER`, `BENCH`, and `IR`, or change a starter's `position_label`. | Manager |
| POST   | `/players` | Register a player in the league-wide catalog. | Commissioner |
| GET    | `/players` | List players, optionally filtered by `position` and/or `status_tag`. | Commissioner, Manager |
| POST   | `/players/{player_id}/status` | Test-driving capability: update a player's `status_tag` (and optionally `weekly_proj_points`). | Commissioner |
| POST   | `/leagues/{league_id}/draft-picks` | Record a draft pick (`SNAKE`: next-up team only; `AUCTION`: any team within budget). | Manager |
| GET    | `/leagues/{league_id}/draft-picks` | List picks in order. | Commissioner, Manager |
| POST   | `/teams/{team_id}/keepers` | Declare a keeper while the league is `DRAFT_PENDING`. | Manager |
| GET    | `/teams/{team_id}/keepers` | List a team's declared/locked keepers. | Commissioner, Manager |
| POST   | `/teams/{team_id}/keepers/{keeper_id}/revoke` | Revoke a `DECLARED` keeper before the draft starts. | Manager |
| POST   | `/leagues/{league_id}/waivers` | Submit a FAAB waiver claim. | Manager |
| GET    | `/leagues/{league_id}/waivers` | List claims, optionally filtered by `team_id` and `status`. | Commissioner, Manager |
| POST   | `/waivers/{waiver_id}/cancel` | Owning manager cancels their `PENDING` claim before its `settle_ts`. | Manager |
| POST   | `/leagues/{league_id}/trades` | Propose a trade. | Manager |
| GET    | `/leagues/{league_id}/trades` | List trades, optionally filtered by `status` and `team_id`. | Commissioner, Manager |
| POST   | `/trades/{trade_id}/accept` | Counterparty accepts → `ACCEPTED_PENDING_REVIEW`. | Manager |
| POST   | `/trades/{trade_id}/reject` | Counterparty rejects → `REJECTED`. | Manager |
| POST   | `/trades/{trade_id}/cancel` | Proposer cancels their own `OFFERED` trade. | Manager |
| POST   | `/trades/{trade_id}/votes` | Cast a `VETO` or `APPROVE` vote during the review window. | Manager |
| GET    | `/leagues/{league_id}/matchups` | List matchups, optionally filtered by `week_number` and/or `is_playoff`. | Commissioner, Manager |
| POST   | `/leagues/{league_id}/matchups/{week_number}/score` | Submit per-starter `scores` to settle a `LOCKED` week. | Commissioner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_MISSING` | 401 Unauthorized |
| `ERR_AUTH_INVALID_ROLE` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_TEAM_OWNER` | 403 Forbidden |
| `ERR_NOT_ELIGIBLE_VOTER` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_PLAYER_ALREADY_DRAFTED` | 409 Conflict |
| `ERR_PLAYER_ALREADY_ROSTERED` | 409 Conflict |
| `ERR_PLAYER_NOT_ON_ROSTER` | 422 Unprocessable Entity |
| `ERR_PLAYER_NO_LONGER_ELIGIBLE` | 409 Conflict |
| `ERR_PLAYER_NOT_IN_WAIVERS` | 422 Unprocessable Entity |
| `ERR_LINEUP_LOCKED` | 409 Conflict |
| `ERR_IR_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ROSTER_SHAPE_INVALID` | 422 Unprocessable Entity |
| `ERR_ROSTER_FULL` | 422 Unprocessable Entity |
| `ERR_POSITION_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_POSITION_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_FAAB_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_AUCTION_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WAIVER_SETTLE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_KEEPER_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NOT_YOUR_TURN` | 409 Conflict |
| `ERR_TWO_WAY_FAAB_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_TRADE_NOT_OPEN_FOR_VOTING` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
