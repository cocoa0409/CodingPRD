# Fantasy Football League API — Product Requirements Document

## 1. Introduction

A fantasy football league is a long-running, multi-party negotiation that begins months before the NFL season and only winds down after the final bracket is decided. Commissioners run the league rulebook, team owners manage rosters, and a fixed pool of FAAB (Free-Agent Acquisition Budget) money circulates among teams across a calendar of waiver runs, trades, and weekly matchups. This document specifies the API that backs that machinery — its entities, lifecycles, and the precise arithmetic that decides who wins a waiver claim, what a keeper costs next year, and how an injury during a playoff week changes a team's score.

Three properties of the system deserve early framing because they shape every rule that follows. First, FAAB is a conserved pool: dollars debited from one team during a waiver win leave the team forever, but dollars transferred in a trade stay inside the league's total, so the sum of every team's FAAB balance never drifts from the league's starting total even as it moves between balance sheets. Second, the league transitions through a small set of statuses — setup, drafting, in-season, playoffs, complete — and almost every business operation gates on the current status, so the API surface for the same resource (a trade, a waiver claim, a roster mutation) is shaped by where the league is in its calendar. Third, the rulebook supports two draft formats and two tiebreak variants in the same league record, and the chosen variant changes both the valuations exposed to the draft board and the seeds assigned to the playoff bracket; the variants must be implemented as siblings, not as one default plus a special case.

The reader of this document is the engineer who will implement the REST API. The benchmark that grades that implementation reads the same prose and asserts every rule below — there are no hidden conventions and no separate field schema beyond what the narrative names.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If `X-User-Role` carries a value not in the two declared roles below, or names a role that is not permitted for the endpoint per §4's authorized-role column, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The same `ERR_FORBIDDEN` code is reused when a `TeamOwner` acts on a `Team` they do not own.

The two roles are:

- **`Commissioner`** — the league operator. The `Commissioner` runs league lifecycle transitions (start draft, finalize draft, advance week, start playoffs, finalize season), schedules and resolves matchups, seeds players into the global pool, reports and clears injuries, and serves as the final approver for trades that survive the veto window. When `X-User-Role` is `Commissioner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.
- **`TeamOwner`** — the owner of exactly one `Team`. A `TeamOwner` manages that single team's roster, lineup, waiver claims, trade proposals, and veto votes. When `X-User-Role` is `TeamOwner`, `X-User-ID` is the `id` of the acting `Team`; ownership checks on any resource that references a `Team` compare the resource's `team_id` (or `proposing_team_id`, `target_team_id`, `voter_team_id`, depending on the resource) to `X-User-ID`. A `TeamOwner` whose `X-User-ID` does not match the relevant team is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters: `limit` defaults to 10, has a minimum of 1, and has a maximum of 100; `offset` defaults to 0 and has a minimum of 0. Requests outside these ranges are rejected with `ERR_INVALID_REQUEST` (HTTP 400). The sort order for every list endpoint is `created_at` ascending — never any entity's `id`, which is explicitly excluded as a tiebreak anywhere in the system. The `meta` block on a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all matching rows after filters but before slicing, and `has_more` is true when more rows exist beyond the current window.

### 2.4. Common Resource Properties

Every entity carries a server-minted `id` that is a UUID string with no type prefix. Most entities also carry three system fields: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that begins at 1 on insert and increments by 1 on every mutation of the row. The `created_at` field is fixed at insert; `updated_at` is refreshed whenever any field on the row changes. The one exception is `VetoVote`, which is an immutable audit record — it carries only `id` and `created_at`, with no `updated_at` and no `version`. When the prose below says "a `Trade.version` is bumped" or "`Team.version += 1`", it is shorthand for incrementing that integer and refreshing the row's `updated_at`.

### 2.5. Optimistic Concurrency Control

Two endpoints are guarded by stale-version rejection because the entity they mutate can be invisibly advanced by other actors between a client's read and write.

The first is finalizing a trade. Any request that drives a trade from `PENDING_VETO` to `EXECUTED` must carry an `expected_trade_version` field whose value matches the target trade's current `version`. If a veto vote was recorded against the trade since the commissioner last read it — bumping `Trade.version` and pushing `veto_votes_count` closer to the threshold — the commissioner's view of "no vetoes yet" is stale, and the finalize is rejected with `ERR_STALE_TRADE_VERSION` (HTTP 412) before any roster swap is applied. This is purely a stale-version check; it does not depend on requests arriving "simultaneously".

The second is cancelling a waiver claim. Any request that drives a `WaiverClaim` from `SUBMITTED` to `CANCELLED` must carry an `expected_waiverclaim_version` field matching the claim's current `version`. If the league advanced the week between the owner's read and the cancel — and the system batch already drove the claim to `WON`, `LOST_BID`, or `INVALID` — the cancel against a now-terminal claim is rejected with `ERR_STALE_WAIVER_VERSION` (HTTP 412), not silently no-op'd. As with the trade guard, the framing is stale-version rejection, not race resolution.

Every lifecycle transition endpoint exposes an `expected_<entity>_version` field corresponding to its target entity (`expected_league_version` for League transitions, `expected_team_version` for team mutations, `expected_player_version` for injury reports and clears, `expected_playoffmatchup_version` for matchup start and finalize). For the two guards above, mismatch returns the dedicated stale-version error; for the remaining version-carrying endpoints, mismatch is rejected with `ERR_INVALID_STATE` (HTTP 409) because the discrepancy means the underlying state has moved past the caller's view. Endpoints not listed as taking a version field never take one.

### 2.6. Precision, Rounding, and Cents

Three numeric conventions hold across the system. First, all FAAB amounts are integer cents — `League.faab_budget_cents`, `Team.faab_balance_cents`, `Trade.faab_offered_cents`, `WaiverClaim.bid_cents`, `DraftPick.cost_cents`, and `League.total_faab_pool_cents` are all whole-number cent quantities and never carry a fractional value. Second, every monetary or score figure exposed to clients as a decimal is rounded half-up to 2 decimal places (the variant that rounds 0.005 to 0.01, never to 0.00). Third, where a calculation involves an intermediate round (per-line-item or per-player) followed by an aggregate round, the order is pinned and must be preserved exactly as the relevant subsection of §3 describes — collapsing per-line rounding into a single final round will produce different cents on asymmetric inputs and is incorrect.

### 2.7. Validation Priority

When multiple validations could reject the same request, they fire in a fixed priority order so that the returned `error_id` is deterministic and downstream test fixtures see the most-fundamental failure first. The order is, from first-checked to last-checked: header presence (`ERR_UNAUTHENTICATED`); role permission and team-ownership match (`ERR_FORBIDDEN`); path-id existence, validated left-to-right across the URL so `/leagues/{id}/finalize-trade/{trade_id}` resolves `{id}` before `{trade_id}` (`ERR_NOT_FOUND`); body foreign-key existence within the same league (`ERR_NOT_FOUND`); the target entity's own state machine precondition (`ERR_INVALID_STATE`); cross-entity state preconditions such as the league being in-season for a trade or the player not being released for a waiver (`ERR_CROSS_ENTITY_STATE`); the IR-only-on-IR-slot safety check (`ERR_INVALID_STARTER_PLAYER`); the segregation-of-duty check on veto voters (`ERR_VETO_SELF_INTEREST`); the trade-roster referential checks (`ERR_TRADE_PLAYER_NOT_ON_ROSTER`); the drop-player referential check (`ERR_DROP_PLAYER_NOT_ON_ROSTER`); the trade-during-game temporal lock (`ERR_TRADE_LOCKED_DURING_GAME`); the waiver-week temporal check (`ERR_INVALID_WAIVER_WEEK`); the roster-cap constraint (`ERR_ROSTER_OVER_CAP`); the keeper-limit constraint (`ERR_KEEPER_OVER_LIMIT`); the FAAB-sufficiency check for waivers (`ERR_FAAB_INSUFFICIENT`); the FAAB-sufficiency check for trades (also `ERR_FAAB_INSUFFICIENT`); the auction-bid constraint (`ERR_AUCTION_BID_INVALID`); and finally the catch-all well-formed-request check that covers missing fields, enum values out of range, and numeric ranges (`ERR_INVALID_REQUEST`). When two validations from different priority levels could both fire, the lower-priority one is never observed.

### 2.8. Hierarchical Consistency and Cascade Semantics

Several state transitions reach beyond the entity they primarily mutate. A draft pick promotes the picked player onto the picking team and the league treasury moves under auction rules; a waiver win debits the winner's FAAB and may invalidate that same team's other open claims if the balance hits zero; a trade execution swaps players and FAAB across two teams in one atomic step; a regular-season matchup completion increments the standings rows on both teams; a playoff matchup completion auto-creates the next-round matchup. Every such cascade is described in the workflow narrative that owns it (§3) — there are no implicit cascades beyond what is written. Whenever a row is mutated by a cascade, its `version` increments by 1 and `updated_at` is refreshed; if a single endpoint causes two transitions on the same row (the trade-accept path that walks `PROPOSED → ACCEPTED → PENDING_VETO` inside one request), `Trade.version` increments twice.

### 2.9. Nested Path Resolution

Endpoints with nested path parameters (for example, the commissioner's trade-finalize endpoint under a league, or the team-scoped lineup, IR, and release endpoints) resolve their path ids left-to-right. The outer id is checked first against `ERR_NOT_FOUND`; only when it resolves does the inner id check run. Where the inner resource must belong to the outer (a trade is finalized through the league that owns it; a player is placed on IR through the team that currently owns the player), a mismatch is also `ERR_NOT_FOUND` rather than a forbidden — the resource simply does not exist in that scope.

### 2.10. Reverse-Reachability Lists

Several child entities are reachable both through their own collection endpoints and through a parent-scoped list. Roster slots and veto votes are the two examples: roster slots can be listed flat and filtered by `team_id` or `player_id` or `slot_type`, and they can also be retrieved as the roster-slot listing under a team; veto votes can be listed flat and filtered by `trade_id` or `voter_team_id`, and they can also be retrieved as the veto-vote listing under a trade. Both views return the same rows in `created_at` ascending order.

## 3. Business Logic & Workflows

### 3.1. Standing Up a League

A league begins life when a `Commissioner` creates it. The creation payload carries the league's `name` (a non-empty 1–80 character string, trimmed), its `draft_type` which is one of `SNAKE` or `AUCTION`, the structural roster numbers, the FAAB endowment, the veto and keeper rules, and the playoff settings. The roster structure is described by `roster_size` (between 2 and 20, the total of starter plus bench slots — IR slots do not count toward this total), `starter_slot_count` (between 1 and 11, never larger than `roster_size`), and `ir_slot_count` (between 0 and 3 additional slots reserved for injured-reserve placement). The fiscal endowment is `faab_budget_cents` (between 0 and 1,000,000 cents, i.e. up to $10,000 per team), and on league start each team's `faab_balance_cents` is initialized from this number. The veto rule is captured by `veto_threshold`, which must be at least 1 and strictly less than the eventual team count in the league. The keeper rule is `keeper_limit`, between 0 and 6, capping how many dynasty keepers a team may carry into next season. The playoff settings are `playoff_team_count`, which must be one of 2, 4, or 8 and at most the team count, and `tiebreak_rule`, which is either `STANDARD` or `DIVISION_FIRST`. On creation, the league's `status` is `SETUP`, its `current_week` is 0, and its `total_faab_pool_cents` is 0 — the pool baseline is established later, at draft start.

Adding teams happens while the league is still in `SETUP`. The commissioner posts a team payload carrying `display_name` (1–40 characters, unique within the league when compared case-insensitively, against `ERR_INVALID_REQUEST` on collision) and `division` (a 1–20 character label used by the division-first tiebreak). Initially the team's computed fields — `faab_balance_cents`, `waiver_priority`, `wins`, `losses`, `total_points_for`, `total_points_against`, `intra_division_wins`, `playoff_seed` — are 0 (or 1 for the version counter), and `keeper_player_ids` is an empty array.

Players are seeded by the commissioner into a global pool. Each player carries a `full_name` (1–80 characters), a `position` from the enumeration `QB`, `RB`, `WR`, `TE`, `K`, or `DEF`, an `nfl_team` of two or three uppercase letters or the special value `FA` for free agents, a weekly `projected_points` between 0 and 50 with two decimals, and a position-level `replacement_value` baseline between 0 and 30 with two decimals — the latter is the VBD anchor used by the snake-draft valuation. A fresh player begins with `status` `ACTIVE` and a null `current_team_id`.

When the commissioner starts the draft, the league must have at least two teams, its configured `playoff_team_count` must not exceed the actual team count, and its `veto_threshold` must be strictly less than that team count; a violation surfaces as `ERR_INVALID_STATE`. The transition flips `status` from `SETUP` to `DRAFTING`, sets every team's `faab_balance_cents` equal to the league's `faab_budget_cents`, and pins the league's `total_faab_pool_cents` to `faab_budget_cents` multiplied by the team count — this number is the conserved baseline that every later FAAB movement (waiver debits and trade transfers) must preserve. Each team's `waiver_priority` is also assigned at this moment in order of `Team.created_at` ascending: the team created first gets priority 1, the second priority 2, and so on; lower priority numbers mean higher precedence for waiver tiebreaks.

### 3.2. The Draft Itself: Two Variants, One Codebase

During `DRAFTING`, picks arrive through a single endpoint that takes the `league_id`, the picking `team_id`, the chosen `player_id`, the `round` number (1 through 20), the `overall_pick` ordinal (which must be at least 1 and strictly monotonically increasing across the league's draft), the `cost_cents` amount, and the optional `keeper_round` and `is_keeper` fields. The `cost_cents` semantics depend entirely on the league's `draft_type` and a violation is rejected with `ERR_AUCTION_BID_INVALID`: in a `SNAKE` league, every pick's `cost_cents` must be exactly 0; in an `AUCTION` league, every pick's `cost_cents` must be at most the picking team's remaining `faab_balance_cents` minus a one-dollar (100-cent) reserve for each still-unfilled roster slot the team has — so a team that has 5 slots left to fill must keep at least 400 cents in reserve to bid on each of the next four slots after this one. The `is_keeper` flag defaults to false; when true, the pick reuses a keeper slot retained from the prior season, and `keeper_round` (between 1 and 20, otherwise null) records the round at which the player would cost under next season's keeper rule.

Draft valuation is exposed through two read endpoints. The draft board returns one entry per player ordered by computed value descending, with the response carrying the active `variant` string so callers can tell which formula was applied; a per-player lookup returns the same `value` for a single player along with the same `variant` indicator. The two variants share the same inputs and produce different valuations:

- The **snake** variant fires when `draft_type` equals `SNAKE`. It is pure value-based drafting: for each player, the value is the player's `projected_points` minus their `replacement_value`, rounded half-up to two decimal places. FAAB is not involved.
- The **auction** variant fires when `draft_type` equals `AUCTION`. The system first builds the top pool: all players in the league's universe ordered by `projected_points` descending with ties broken by `created_at` ascending (never by id), limited in size to `roster_size` multiplied by the team count. The pool's `projected_points` are summed into a total. Each player's share of the pool is their `projected_points` divided by that total, with the share treated as zero if the total is zero (a defensive guard against the empty-pool edge case). The player's value is then the league's `faab_budget_cents` divided by 100 (so the unit is dollars, not cents) multiplied by that share, rounded half-up to two decimal places. Two players with identical `projected_points` therefore get different values if the pool size or pool sum differs between leagues.

Filling the draft is what closes it: the commissioner can finalize the draft only when every team in the league has exactly `roster_size` draft pick rows recorded for the league and the `draft_type` has not been changed mid-draft. Finalizing flips the league `status` from `DRAFTING` to `IN_SEASON`, sets `current_week` to 1, and walks every recorded draft pick to create a corresponding roster slot under the picking team with `slot_type` of `BENCH` and to set the picked player's `current_team_id` to that team.

### 3.3. The Weekly Heartbeat

In-season operation is paced by week advancement. Each call to advance the week is permitted only when the league still has regular-season weeks remaining — the league's `current_week` must be strictly less than 17 minus the number of bracket rounds implied by `playoff_team_count` (a 2-team bracket has 1 round, 4 teams have 2 rounds, 8 teams have 3 rounds) — and every regular matchup scheduled for the current week must be in `COMPLETED` state. When both conditions hold, the system processes every submitted waiver claim for the current week (described in §3.4), then increments the league's `current_week` by 1. A request that violates either condition is rejected with `ERR_INVALID_STATE`.

When the regular season is over — `current_week` equals 17 minus the bracket-round count, plus 1, with every regular matchup completed — the commissioner moves the league from `IN_SEASON` to `PLAYOFFS`. This transition computes `playoff_seed` for the top teams and auto-creates the round-1 bracket matchups (described in §3.7). When the final bracket matchup (the one whose `round` equals the base-2 logarithm of `playoff_team_count` — 1 for a 2-team bracket, 2 for 4 teams, 3 for 8 teams) reaches `COMPLETED`, the commissioner finalizes the season, moving the league to `COMPLETE`. The finalize-season step locks every team's `keeper_player_ids` so next season's dynasty cost calculation can run against a frozen list. The league has now reached its terminal state.

### 3.4. Free-Agent Acquisition: FAAB and Waivers

A `TeamOwner` claims a free agent or a player on waivers by submitting a waiver claim during the league's `IN_SEASON` phase. The submission payload carries the owning `league_id`, the claiming `team_id`, the targeted `player_id`, the `bid_cents` amount (which at submission must be at most the team's current `faab_balance_cents`, otherwise `ERR_FAAB_INSUFFICIENT`), an optional `drop_player_id` for the player the team will drop if the claim wins (which, if supplied, must currently be on the claiming team's roster, otherwise `ERR_DROP_PLAYER_NOT_ON_ROSTER`), and the `processing_week` value, which the claimant copies from the league's current week — claims for past weeks and for future weeks are equally invalid and rejected with `ERR_INVALID_WAIVER_WEEK`. The waiver target player must not be `RELEASED`; the player's `status` must be one of `ACTIVE`, `INJURED`, or `IR_PLACED` at evaluation time, or the claim is later marked invalid. On submission the claim's `state` is `SUBMITTED` and the claim records the team's current `waiver_priority` into `priority_at_submission` for later tiebreaking.

An owner may cancel their own claim while it is still `SUBMITTED` (advancing the claim's `state` to `CANCELLED`); the cancellation request carries `expected_waiverclaim_version`, and a mismatch with the claim's current `version` — for example because the league advanced the week and the system batch already moved the claim to `WON`, `LOST_BID`, or `INVALID` — is rejected with `ERR_STALE_WAIVER_VERSION`. The acting `TeamOwner` must own the claim's team.

The waiver batch runs as part of advancing the week. The batch examines every `SUBMITTED` claim whose `processing_week` equals the league's `current_week` and resolves them through three passes. The first pass marks claims `INVALID` if the targeted player's `status` is `RELEASED`, or the team's `faab_balance_cents` is below the claim's `bid_cents`, or a prior same-team winning claim earlier in this batch has already drained the team's FAAB to zero. The second pass processes the remaining claims, grouped by `player_id`, picking one winner per group through a three-key sort: claims are ordered by `bid_cents` descending first; ties are broken by `priority_at_submission` ascending (lower priority number wins); remaining ties are broken by `WaiverClaim.created_at` ascending — never by `WaiverClaim.id`. Across the groups, winners are committed in `created_at` order: each commit debits the winning team's `faab_balance_cents` by `bid_cents`, sets the target player's `current_team_id` to the winning team, creates a roster slot with `slot_type` `BENCH`, deletes the optional drop player's roster slot and nulls that player's `current_team_id`, advances the claim's `state` to `WON`, and rotates the winning team's `waiver_priority` to the lowest priority (reverse-Robin, so the team that won drops behind everyone else). Crucially, if a team's `faab_balance_cents` reaches 0 mid-batch, every still-pending `SUBMITTED` claim for that same team within the same `processing_week` is auto-marked `INVALID` before the third pass — this is a cascade-depth-3 chain (group winner selection → winner commit → same-team invalidation), and it is the reason claims are committed in `created_at` order rather than parallel. The third pass marks every remaining same-player loser as `LOST_BID` with no FAAB debit, conserving the league's `total_faab_pool_cents`.

After a successful waiver, the team's non-IR roster slot count must still not exceed `roster_size`, or the claim is rejected with `ERR_ROSTER_OVER_CAP` — owners who already hold a full roster must always supply `drop_player_id` to make room.

### 3.5. Roster, Lineup, and Injury Choreography

A team's roster slots come in three flavors: a `STARTER` slot scores for the team in the current week, a `BENCH` slot does not score, and an `IR` slot is reserved exclusively for players whose `status` is `INJURED` or `IR_PLACED`. Lineup changes are made by the owning `TeamOwner` through the set-lineup endpoint, which takes a `starter_player_ids` array (the team's chosen starters for the upcoming week) and `expected_team_version` for OCC. The endpoint marks every listed player's roster slot as `STARTER` and every other non-IR slot as `BENCH`. Starters are never allowed to be in `IR_PLACED` status — the safety check fires for both set-lineup and matchup-start, rejecting with `ERR_INVALID_STARTER_PLAYER` if a starter has `IR_PLACED` status or if a listed `starter_player_ids` member is not actually on the team's roster.

Injuries are reported by the commissioner against a specific player. Reporting an injury moves the player from `ACTIVE` to `INJURED`; if the player is currently in a `STARTER` slot for the locked week, the upcoming score evaluation will apply the injury penalty described in §3.6 rather than the player's full projection. Clearing an injury (also a commissioner action) moves the player back from `INJURED` to `ACTIVE` outright.

A `TeamOwner` may place an `INJURED` player on injured reserve by calling the team-scoped IR-placement endpoint with the `player_id` and `expected_team_version`. The target player must currently belong to the acting team and must be in `INJURED` status, and the team's IR usage must still have room — the count of the team's roster slots with `slot_type` of `IR` must be strictly less than the league's `ir_slot_count`. The transition moves the player's `status` from `INJURED` to `IR_PLACED` and changes the player's roster slot from whatever it was (typically `BENCH`) to `IR`, which frees a non-IR slot. The reverse move — activating from IR — is also team-owner-driven, takes the same `player_id` and `expected_team_version`, and moves the player from `IR_PLACED` back to `ACTIVE` with the slot returning to `BENCH`. Activation gates on the post-activation non-IR slot count not exceeding `roster_size`, otherwise `ERR_ROSTER_OVER_CAP`.

Releasing a player is a separate, terminal action that a `TeamOwner` may invoke against a player on their roster whose `status` is `ACTIVE`. The release passes the player briefly through `RELEASED` then immediately back to `ACTIVE` with `current_team_id` nulled, removing every roster slot row that referenced the player on the releasing team; the player returns to the free-agent pool and is available for waiver claims by other teams.

### 3.6. Matchup Scoring and Injury Replacement

Matchups are the league's per-week scoring unit. The commissioner creates a matchup carrying its `week` (between 1 and 17), `matchup_type` (`REGULAR` or `PLAYOFF`), `round` (0 for a regular matchup, otherwise 1 for quarterfinal, 2 for semifinal, 3 for final), the `home_team_id`, and the `away_team_id` (which must differ from `home_team_id`). On creation the `state` is `SCHEDULED`, both `home_score` and `away_score` are 0, and `winner_team_id` is null.

Starting a matchup moves it from `SCHEDULED` to `IN_PROGRESS`. The league's `current_week` must equal the matchup's `week`, and for a `PLAYOFF` matchup both teams must already carry a `playoff_seed` greater than 0. Starting locks every `STARTER` roster slot for both teams by writing the current week into `week_locked` — the locked roster is what scoring will run against, regardless of injuries that occur after the start.

Finalizing a matchup moves it from `IN_PROGRESS` to `COMPLETED`. The request may supply `home_score` and `away_score` directly (for example, after manual entry of real-world scoring) or omit them, in which case the system computes both via the injury-replacement projection. Whether supplied or computed, the values must satisfy the two-decimal half-up rounding rule.

The injury-replacement projection runs across each team's locked starter slots — those `RosterSlot` rows where `slot_type` is `STARTER` and `week_locked` equals the matchup's `week` and the slot belongs to one of the two participating teams. The player's `status` is sampled at finalize time, not at start time — an injury reported between start and finalize will affect the score. For each locked starter slot, the contribution begins as the slot's player's `projected_points`. If the player's `status` is `ACTIVE`, that value is taken as-is. If the player's `status` is `INJURED`, the contribution becomes the projection minus an injury penalty of 4.0 points, with a floor of 0 (so an injured player with a projection below 4.0 contributes 0, not a negative). If the player's `status` is `IR_PLACED` — an invalid configuration for a starter that nevertheless can happen if the player is moved to IR after the start lock — the contribution is treated as 0, the replacement-level fallback. Each per-line-item contribution is rounded half-up to two decimal places first; the per-line-rounded contributions are then summed for the team; the team's running sum is then itself rounded half-up to two decimal places to produce the final `home_score` (or `away_score`). The pinned order is: round per line, sum, then round the sum — a single final round over the unrounded sum is incorrect because asymmetric rounding accumulates a different last cent. The injury penalty of 4.0 points is a fixed system constant.

Once both scores are settled, the matchup's `winner_team_id` is assigned to the team with the higher score; if the two scores are equal, the winner is the team with the higher `total_points_for` measured at the start of this matchup — never a coin flip and never null at `COMPLETED`. For a `REGULAR` matchup, the cascade fires on the standings: the winner's `wins` increments by 1 and `total_points_for` is incremented by its score and `total_points_against` by the opponent's score; the loser's `losses` increments by 1 with the same point-aggregate updates; if the two teams share the same `division`, the winner's `intra_division_wins` also increments by 1. For a `PLAYOFF` matchup where the current `round` is less than the bracket's final round, finalizing also auto-creates the next-round matchup pairing this winner against the winner of the parallel bracket position — this is the bracket-advancement cascade that the §3.7 narrative builds on.

### 3.7. Playoff Bracket Seeding and Tiebreaks

Moving the league from `IN_SEASON` to `PLAYOFFS` computes `playoff_seed` for the top teams in one pass and auto-creates the round-1 matchups pairing seeds 1 against N, 2 against N-1, and so on, where N is `playoff_team_count`. Seeding uses one of two variants, chosen by the league's `tiebreak_rule`, both operating over the same input — all team rows for this league at the end of the regular season — with `created_at` ascending as the always-final tiebreak (never team `id`):

- The **standard** variant fires when `tiebreak_rule` equals `STANDARD`. Teams are sorted by `wins` descending first, then by `total_points_for` descending, then by `created_at` ascending. The top `playoff_team_count` teams receive seeds 1 through N in that sort order. Intra-division record is ignored.
- The **division-first** variant fires when `tiebreak_rule` equals `DIVISION_FIRST`. Teams are sorted by `wins` descending first, then by `intra_division_wins` descending, then by `total_points_for` descending, then by `created_at` ascending. The top `playoff_team_count` teams receive seeds 1 through N in that sort order. Two teams with identical `wins` and `total_points_for` but different intra-division records can therefore re-order between the standard and division-first variants — that is the entire point of the second variant.

Teams not in the top `playoff_team_count` keep `playoff_seed` at 0.

Playoff matchups then walk the bracket as described in §3.6 — start locks the starter rosters; finalize sets the winner and, if a round below the final round, auto-creates the next-round matchup. When the final-round matchup completes, the league is ready for season finalize.

### 3.8. Trades and the Veto Window

A trade is proposed by a `TeamOwner` during `IN_SEASON`. The proposal carries the owning `league_id`, the `proposing_team_id`, the `target_team_id` (which must differ from the proposer), an array `players_offered` of 1 to 5 player ids the proposer would send (every member must currently sit on the proposer's roster, otherwise `ERR_TRADE_PLAYER_NOT_ON_ROSTER`), an array `players_requested` of 1 to 5 player ids the target would send (with the symmetric roster check against the target's roster), and an optional `faab_offered_cents` amount of FAAB to transfer from proposer to target on execute (defaulting to 0; must be at most the proposing team's current `faab_balance_cents`, otherwise `ERR_FAAB_INSUFFICIENT`). The newly created trade carries `state` `PROPOSED`, `veto_votes_count` of 0, and a null `accepted_at`.

From `PROPOSED` the trade has three exits. The proposing team's owner may withdraw it, moving it to the terminal `WITHDRAWN`. The target team's owner may reject it, moving it to the terminal `REJECTED`. The target team's owner may accept it, in which case the trade's `state` advances from `PROPOSED` to `ACCEPTED` and `accepted_at` is set to the current system UTC; the system then immediately, within the same request, auto-transitions the trade from `ACCEPTED` to `PENDING_VETO` with `veto_votes_count` reset to 0 — `Trade.version` increments twice across the two transitions. The roster-presence and FAAB-sufficiency checks fire again at accept time, since the world may have moved since the trade was first proposed. The `Commissioner` does not accept trades; only the target team's owner does.

While the trade is `PENDING_VETO`, any neutral `TeamOwner` — neither the proposer nor the target — may cast a vote against it. The vote payload supplies the `voter_team_id`, the `vote` value (which must be `VETO` or `ALLOW`), and `expected_trade_version` for OCC. A voter that is the proposer or the target is rejected with `ERR_VETO_SELF_INTEREST`. Each recorded `VETO` vote increments `Trade.veto_votes_count` by 1; an `ALLOW` vote is recorded but does not. When `veto_votes_count + 1` first reaches the league's `veto_threshold` upon recording a new `VETO` vote — that is, after this vote is committed, the count would be at or above the threshold — the trade auto-transitions to the terminal `VETOED`, no roster swap occurs, and FAAB is unchanged. The `VETOED` state is the no-op terminal: it cleanly ends the trade without touching the league's balance sheet.

If the veto window passes without enough vetoes, the commissioner finalizes the trade. The finalize gate requires that the trade's `state` is `PENDING_VETO`, the league's `status` is `IN_SEASON`, no `PlayoffMatchup` with this league's id is currently `IN_PROGRESS` (otherwise `ERR_TRADE_LOCKED_DURING_GAME`), `Trade.veto_votes_count` is still strictly less than `League.veto_threshold`, and the OCC field `expected_trade_version` matches the trade's current `version` (otherwise `ERR_STALE_TRADE_VERSION`, HTTP 412 — the typical reason being that a new `VETO` vote landed between the commissioner's read and the finalize call, bumping the version and possibly tipping the count over the threshold). The roster-presence and FAAB-sufficiency checks fire one last time. The finalize moves the trade to `EXECUTED` and applies the swap in one step: each player in `players_offered` has `current_team_id` set to the target team and their roster slot moved across (with the old slot deleted and a new `BENCH` slot created under the target); each player in `players_requested` is moved symmetrically to the proposer; if `faab_offered_cents` is greater than 0, that amount is debited from the proposer's `faab_balance_cents` and credited to the target's, preserving the league's `total_faab_pool_cents` exactly. Both team rows and every affected player row have their `version` bumped and `updated_at` refreshed.

A commissioner or owner may also inspect a trade's fairness via the fairness-read capability, which returns a score, the proposer's offered value, and the target's requested value. The computation rounds each player's `projected_points` half-up to one decimal place first, sums the rounded values per side, then rounds the per-side sum half-up to two decimal places to get `offered_value` and `requested_value`; the FAAB delta is `faab_offered_cents` divided by 100 (so dollars, not cents); the final `fairness_score` is the absolute value of `offered_value` plus the FAAB delta minus `requested_value`, rounded half-up to two decimal places. The order — round per player to 1 decimal, sum, round the sum to 2 decimals, then form the final figure with the FAAB delta and a final 2-decimal round — is pinned; collapsing the per-player round into the final round changes the result on asymmetric trades.

### 3.9. Dynasty Keepers Across Seasons

At any point during the in-season phase, a `TeamOwner` may update their team's `keeper_player_ids` — the array of player ids designated for retention into next season. The update payload carries the new `keeper_player_ids` array and `expected_team_version`; the array's length must not exceed the league's `keeper_limit`, and every member must currently be on the acting team's roster, otherwise `ERR_KEEPER_OVER_LIMIT`. Updating the array recomputes each keeper's dynasty cost on the team's existing draft picks.

The dynasty cost computation works per team. The team's `keeper_player_ids` are walked in `Player.created_at` ascending order — never by player `id`. The first keeper in that order gets a cost equal to their `round` from the prior season's draft pick row; the second gets a cost equal to that prior-season round minus 1; the third minus 2; and so on for the index of the player in the sorted list. Every cost is floored at 1, so a player whose prior round was 3 and who is the team's fifth keeper still costs round 1, not round -2. The floor constant is the keeper-floor round, value 1, applied via the `max` operation against the subtracted figure. The result is written back to each keeper's draft-pick row as `keeper_round`. This computation runs both when an owner updates their keeper list during the season and again when the commissioner finalizes the season — the finalize-season step locks the list and re-runs the cost computation one final time so the entries that next season's draft will consult are pinned.

### 3.10. System Test-Driving and Determinism

For deterministic testing, the commissioner can drive the server's clock with a test-driving capability that takes a single `to_iso8601` field and sets the server's current UTC reference for downstream system timestamps. The endpoint is namespaced under the test-driving path. Setting the clock affects subsequent timestamps such as `Trade.accepted_at`; it does not retroactively rewrite already-committed timestamps. A commissioner is the only role permitted to use this capability.

## 4. Endpoint Definitions

The endpoints below are the entire public API. Responses follow §2.2's envelope; pagination on list endpoints follows §2.3. Status codes are 201 for new-resource creation (a fresh league, team, player, draft pick, waiver claim, trade, veto vote, or matchup row), 200 for every other success including state-mutating action endpoints, and the 4xx codes catalogued in §5 for failures. Path parameters resolve left-to-right.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/leagues` | Create a new league in setup state. | `Commissioner` |
| GET | `/leagues/{id}` | Read a league by id. | `Commissioner`, `TeamOwner` |
| GET | `/leagues` | List leagues. | `Commissioner`, `TeamOwner` |
| POST | `/leagues/{id}/start-draft` | Move league from setup to drafting. | `Commissioner` |
| POST | `/leagues/{id}/finalize-draft` | Move league from drafting to in-season. | `Commissioner` |
| POST | `/leagues/{id}/advance-week` | Advance current week and run waiver batch. | `Commissioner` |
| POST | `/leagues/{id}/start-playoffs` | Move league from in-season to playoffs, seed teams, create round-1 matchups. | `Commissioner` |
| POST | `/leagues/{id}/finalize-season` | Move league from playoffs to complete, lock keepers. | `Commissioner` |
| GET | `/leagues/{id}/draft-board` | Computed read: per-player draft valuation under the league's variant. | `Commissioner`, `TeamOwner` |
| GET | `/players/{id}/draft-value` | Computed read: draft value for a single player. | `Commissioner`, `TeamOwner` |
| POST | `/leagues/{id}/teams` | Create a team under a league (setup phase only). | `Commissioner` |
| GET | `/teams/{id}` | Read a team by id. | `Commissioner`, `TeamOwner` |
| GET | `/teams` | List teams. | `Commissioner`, `TeamOwner` |
| PATCH | `/teams/{id}/keepers` | Update team's keeper designation list. | `TeamOwner` |
| POST | `/teams/{team_id}/set-lineup` | Set starter/bench assignment for the team's current roster. | `TeamOwner` |
| POST | `/teams/{team_id}/place-on-ir` | Move an injured player to IR. | `TeamOwner` |
| POST | `/teams/{team_id}/activate-from-ir` | Move an IR-placed player back to bench. | `TeamOwner` |
| POST | `/teams/{team_id}/release-player` | Release an active player back to the free-agent pool. | `TeamOwner` |
| GET | `/teams/{id}/roster-slots` | List roster slots for a team. | `Commissioner`, `TeamOwner` |
| POST | `/players` | Create a player in the global pool. | `Commissioner` |
| GET | `/players/{id}` | Read a player by id. | `Commissioner`, `TeamOwner` |
| GET | `/players` | List players. | `Commissioner`, `TeamOwner` |
| POST | `/players/{id}/report-injury` | Mark a player as injured. | `Commissioner` |
| POST | `/players/{id}/clear-injury` | Clear a player's injury back to active. | `Commissioner` |
| POST | `/draft-picks` | Submit a draft pick during drafting. | `Commissioner`, `TeamOwner` |
| GET | `/draft-picks/{id}` | Read a draft pick by id. | `Commissioner`, `TeamOwner` |
| GET | `/draft-picks` | List draft picks. | `Commissioner`, `TeamOwner` |
| POST | `/waiver-claims` | Submit a FAAB waiver claim. | `TeamOwner` |
| GET | `/waiver-claims/{id}` | Read a waiver claim by id. | `Commissioner`, `TeamOwner` |
| GET | `/waiver-claims` | List waiver claims. | `Commissioner`, `TeamOwner` |
| POST | `/waiver-claims/{id}/cancel` | Cancel a submitted waiver claim before processing. | `TeamOwner` |
| POST | `/trades` | Propose a trade during in-season. | `TeamOwner` |
| GET | `/trades/{id}` | Read a trade by id. | `Commissioner`, `TeamOwner` |
| GET | `/trades` | List trades. | `Commissioner`, `TeamOwner` |
| POST | `/trades/{id}/accept` | Target team accepts a proposed trade (and trade auto-advances into the veto window). | `TeamOwner` |
| POST | `/trades/{id}/reject` | Target team rejects a proposed trade. | `TeamOwner` |
| POST | `/trades/{id}/withdraw` | Proposing team withdraws a proposed trade. | `TeamOwner` |
| POST | `/trades/{id}/veto-votes` | Record a veto vote against a pending-veto trade. | `TeamOwner` |
| POST | `/leagues/{id}/finalize-trade/{trade_id}` | Commissioner finalizes a pending-veto trade past the veto window, applying the roster and FAAB swap. | `Commissioner` |
| GET | `/trades/{id}/fairness` | Computed read: trade fairness score. | `Commissioner`, `TeamOwner` |
| GET | `/trades/{trade_id}/veto-votes` | List veto votes for a trade. | `Commissioner`, `TeamOwner` |
| GET | `/veto-votes/{id}` | Read a single veto vote row by id. | `Commissioner`, `TeamOwner` |
| GET | `/veto-votes` | List veto vote rows. | `Commissioner`, `TeamOwner` |
| GET | `/roster-slots/{id}` | Read a single roster slot row by id. | `Commissioner`, `TeamOwner` |
| GET | `/roster-slots` | List roster slot rows. | `Commissioner`, `TeamOwner` |
| POST | `/leagues/{id}/matchups` | Create a regular or playoff matchup. | `Commissioner` |
| GET | `/matchups/{id}` | Read a matchup by id. | `Commissioner`, `TeamOwner` |
| GET | `/matchups` | List matchups. | `Commissioner`, `TeamOwner` |
| POST | `/matchups/{id}/start` | Move matchup from scheduled to in-progress and lock starters. | `Commissioner` |
| POST | `/matchups/{id}/finalize` | Move matchup from in-progress to completed, compute scores, cascade standings or next bracket round. | `Commissioner` |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's logical clock. | `Commissioner` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_INVALID_STARTER_PLAYER` | 422 |
| `ERR_VETO_SELF_INTEREST` | 422 |
| `ERR_TRADE_PLAYER_NOT_ON_ROSTER` | 422 |
| `ERR_DROP_PLAYER_NOT_ON_ROSTER` | 422 |
| `ERR_TRADE_LOCKED_DURING_GAME` | 409 |
| `ERR_INVALID_WAIVER_WEEK` | 422 |
| `ERR_ROSTER_OVER_CAP` | 422 |
| `ERR_KEEPER_OVER_LIMIT` | 422 |
| `ERR_FAAB_INSUFFICIENT` | 422 |
| `ERR_AUCTION_BID_INVALID` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_TRADE_VERSION` | 412 |
| `ERR_STALE_WAIVER_VERSION` | 412 |
