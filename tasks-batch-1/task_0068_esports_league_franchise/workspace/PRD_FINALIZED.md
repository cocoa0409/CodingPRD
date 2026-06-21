# Esports League Franchise API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform that runs a North American esports league modeled on the operational machinery of a professional basketball franchise system. The league is organized around discrete competitive **seasons**, each of which owns a roster of **teams**, a pool of **players**, and the financial scaffolding — salary caps, luxury taxes, sponsorship revenue, fines, and trade windows — that keeps competition balanced. Two distinct operators drive the system: the league office, which administers the season lifecycle and all league-wide financial levers, and individual team general managers, who build and reshape their own rosters within the constraints the league imposes.

The hard problems this platform exists to solve are problems of consistency. A roster move must respect a salary cap that is a finite, shared accounting fact. A trade is a two-party negotiation in which contracts physically change hands and both teams' payrolls must be recomputed atomically. A fine quietly accrues penalty points that, past a breakpoint, lock a team out of further roster activity until the points are reversed. Sponsorship money flows through a waterfall that must distribute to the last cent. Because several of these mutations are computed against a snapshot the actor read moments earlier, the platform uses optimistic concurrency to reject writes that would otherwise commit against a roster or pool that has since shifted underneath the caller. The remainder of this document defines the entities, the lifecycle state machines, the financial calculations, and the validation ordering that together make these guarantees precise.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which they act. If either header is absent, or if `X-User-Role` is not one of the two recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly two roles:

- **`LeagueCommissioner`** — the league operator. The commissioner administers seasons and every season lifecycle transition, registers teams and players, opens and closes trade windows, assesses and waives fines, creates and distributes sponsorships, and marks teams eliminated from the playoffs. When `X-User-Role` is `LeagueCommissioner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.
- **`TeamGM`** — a general manager acting for one specific team. When `X-User-Role` is `TeamGM`, `X-User-ID` is the `id` of the acting `Team`; ownership checks on any resource that references a `Team` compare the resource's relevant team foreign-key field to `X-User-ID`. A GM may sign, promote, and waive contracts for their own team, log call-up stints against their own team's two-way contracts, and propose, accept, reject, or withdraw trades on the side of the deal their team occupies.

Both roles may perform all GET reads. When a `TeamGM` attempts to mutate a resource that does not belong to the team whose `id` equals `X-User-ID` — waiving or promoting another team's contract, accepting or rejecting a trade in which their team is not the `to_team_id`, withdrawing a trade in which their team is not the `from_team_id`, signing a contract for a team that is not theirs, or logging a stint against a contract that is not on their team — the request is rejected with `ERR_NOT_TEAM_OWNER` (HTTP 403).

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0 and has a minimum of 0. A `limit` or `offset` outside these bounds is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400). Results are always returned sorted by `created_at` ascending. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count` (the total number of records matching the query before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Common Resource Properties

Most entities — `Season`, `Team`, `Player`, `Contract`, `Stint`, `Trade`, `Fine`, and `Sponsorship` — share four system-managed properties. Each carries an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp; an `updated_at` timestamp; and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits. The `version` begins at 1 on creation and increments by exactly 1 on each successful mutation of that resource; `updated_at` is refreshed to the mutation time whenever the resource changes. The `RevenueShare` entity is an exception: it is an immutable audit record carved at distribution time and carries only an `id` and a `created_at` — it has neither an `updated_at` nor a `version`.

### 2.5. Nested Resource Retrieval

Several read endpoints address a resource through a parent path segment — for example, the contracts, fines, or revenue shares belonging to a team, or the revenue shares carved from a sponsorship. Path parameters are validated left to right: the parent resource named earliest in the path is resolved first, and if any referenced resource along the path does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper segment or body reference is considered. The same left-to-right existence discipline applies to every resource referenced in a request, whether by path or by body, in the order season, team, player, contract, trade, fine, sponsorship.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and computed as integer cents. The payroll aggregation produces exact integer cents with no rounding. Where a calculation produces a fractional intermediate — the luxury tax tiers and the sponsorship league cut — the result is rounded half up to whole cents. The sponsorship waterfall floors each team's provisional share and then distributes the leftover cents one at a time so that the awarded shares sum exactly to the distributable amount, as detailed in §3.

### 2.7. Optimistic Concurrency on Cap-Consuming Writes

Two write operations consume a parent resource's accounting state and therefore require optimistic concurrency control. In each case the request must carry the version the actor last observed, and the write is rejected if that version no longer matches the parent's current `version`.

Accepting a trade is a write against the counterparty team's roster and payroll. The accept request must include `expected_to_team_version` carrying the `version` of the `to_team` (the accepting team) that the GM last read. If another roster mutation — a previously accepted trade, a waive, or a promotion — has advanced that team's `version` since the GM read it, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412), because the cap and roster math would otherwise be computed against a counterparty roster that has shifted underneath it.

Distributing a sponsorship is a write against the sponsorship pool. The distribute request must include `expected_sponsorship_version` carrying the `version` of the sponsorship the commissioner last read. If the sponsorship's pool or league share was edited and its `version` advanced after the commissioner read it, the distribute is rejected with `ERR_STALE_VERSION` (HTTP 412), so the payout is never computed against an out-of-date pool.

Operations not named here — signing, promoting, and waiving carry a version field of their own as noted in §3, but trade reject, trade withdraw, fine assessment, fine waive, and the season lifecycle transitions take no version field.

### 2.8. Cascade and Consistency Discipline

The league runs on immediate consistency: every cap recomputation and every cross-entity cascade triggered by a request completes inside that same request before the response is returned. When a mutation touches more than one resource — a trade reassigning contracts and recomputing both teams' payrolls, a waive freeing a player, a fine flipping a team's posture — each affected resource's `version` is incremented and its `updated_at` refreshed as part of the single operation. The specific cascades are described alongside the workflows that trigger them in §3.

## 3. Business Logic & Workflows

### 3.1. The Season Lifecycle and the Trade Window

A season is the top-level container for all competition. The commissioner creates one by supplying a `name` (a label such as "2026 Spring Split") and a `salary_cap_cents`, the hard reference cap per team in cents above which payroll incurs luxury tax; the cap must be at least 1. Four further inputs are optional and carry defaults. The `roster_min`, the minimum number of `ACTIVE` standard contracts a team must carry to be playoff-eligible, defaults to 5 and must be at least 1. The `roster_max`, the maximum number of `ACTIVE` standard (non-two-way) contracts a team may carry, defaults to 8 and must be greater than or equal to `roster_min`. The `two_way_max`, the maximum number of `ACTIVE` two-way contracts a team may carry separately from the standard limit, defaults to 2 and must be at least 0. The `penalty_threshold`, the cumulative team penalty-point value at or above which a team's posture flips to `RESTRICTED`, defaults to 3 and must be at least 1. A newly created season begins life in `phase` `SETUP` with its `trade_window_state` initialized to `CLOSED`.

A season's `phase` moves through a fixed progression. Starting the regular season advances `phase` from `SETUP` to `REGULAR`; this is permitted only when the season is currently in `SETUP`, and it increments the season's `version` by 1. While the season is in `REGULAR`, the commissioner may toggle the trade window: this self-loop keeps `phase` at `REGULAR`, sets `trade_window_state` to the requested value — supplied as `trade_window_state`, either `OPEN` or `CLOSED` — and increments the season's `version` by 1. The toggle is valid only during `REGULAR`.

Starting the playoffs advances `phase` from `REGULAR` to `PLAYOFFS`. Three conditions must hold: the season is in `REGULAR`; the `trade_window_state` is `CLOSED`; and every team in the season carries at least `roster_min` `ACTIVE` `STANDARD` contracts. If any team falls short of `roster_min`, the transition is rejected with `ERR_PLAYOFF_PRECONDITION` (HTTP 409). On success the transition sets `phase` to `PLAYOFFS`, assigns each team a playoff `seed`, sets `eliminated` to false for every team in the season, and increments the season's `version` by 1. Seeding ranks the teams by `penalty_points` ascending, then by `payroll_active_cents` descending, then by `created_at` ascending; the `seed` is the 1-based position in that ranking, so a lower `seed` is a better seed.

Completing the season advances `phase` from `PLAYOFFS` to `COMPLETE`, a terminal phase. This requires that the season is in `PLAYOFFS` and that exactly one team in the season has `eliminated` equal to false — a single surviving champion. If more than one or zero non-eliminated teams remain, the request is rejected with `ERR_PLAYOFF_PRECONDITION` (HTTP 409). On success it sets `phase` to `COMPLETE` and increments the season's `version` by 1. Any season lifecycle transition attempted from the wrong `phase` is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Teams, Players, and Building a Roster

The commissioner registers a team within a season by supplying its `season_id`, a `name`, and a `market_size_weight` — the sponsorship revenue-share weight used by the revenue waterfall, which must be at least 1. A team's `name` must be unique within its season under case-sensitive exact matching; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A new team starts with `payroll_active_cents` at 0, `penalty_points` at 0, `posture` `OPEN`, `seed` null, and `eliminated` false. The `payroll_active_cents`, `penalty_points`, `posture`, `seed`, and `eliminated` fields are all system-maintained and never set directly by input.

Players belong to the same season-scoped pool. The commissioner registers a free agent by supplying a `season_id` and a `handle`, the player's gamertag, which must be unique within the season under case-sensitive exact matching; a duplicate handle is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A player's `status` begins at `FREE_AGENT` and becomes `SIGNED` only while the player holds an `ACTIVE` contract.

A general manager builds the roster by signing free agents. A sign supplies `team_id`, `player_id`, `base_salary_cents`, `contract_type`, `term_start`, and `term_end`. The `base_salary_cents` is the annual base salary in cents and must be at least 1. The `contract_type` is either `STANDARD`, which counts toward the salary cap, or `TWO_WAY`, which is cap-exempt while it remains unpromoted. The `term_start` and `term_end` are ISO 8601 UTC dates marking the inclusive start and end of the contract term; `term_end` must be greater than or equal to `term_start`. A successful sign creates a contract in `status` `ACTIVE` with `two_way_promoted` false, sets the player's `status` to `SIGNED`, recomputes the signing team's `payroll_active_cents`, and increments the team's `version` by 1.

Several conditions guard a sign. The player must currently be a `FREE_AGENT` with no other `ACTIVE` contract; signing a player who already holds an `ACTIVE` contract is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). The contract's closed term `[term_start, term_end]` must not overlap any existing `ACTIVE` contract for the same `player_id`; for this check, touching endpoints — where one contract's `term_end` equals another's `term_start` — do count as overlapping, and a violation is rejected with `ERR_CONTRACT_TERM_OVERLAP` (HTTP 409). The roster limits described in §3.3 also apply. Field-value violations — a `base_salary_cents` below 1, an invalid `contract_type`, or a `term_end` earlier than `term_start` — are rejected with `ERR_INVALID_FIELD_VALUE` (HTTP 422); a missing required field is rejected with `ERR_VALIDATION` (HTTP 400).

### 3.3. The Salary Cap, Roster Limits, and the Two-Way Exemption

A team's cap-counting payroll, `payroll_active_cents`, is the sum of `base_salary_cents` over every contract on the team whose `status` is `ACTIVE` and which counts toward the cap. A contract counts toward the cap when its `contract_type` is `STANDARD`, or when its `contract_type` is `TWO_WAY` and its `two_way_promoted` flag is true. `WAIVED` contracts are excluded entirely, and an unpromoted two-way contract contributes nothing. This sum is exact integer cents with no rounding, and it is recomputed for any affected team on every sign, waive, promotion, and trade acceptance.

The roster carries two independent capacity limits, both enforced after any move that adds to the roster. The count of `ACTIVE` `STANDARD` contracts — which, for the purpose of this count, includes promoted two-way contracts — may not exceed the season's `roster_max`. The count of `ACTIVE` unpromoted `TWO_WAY` contracts may not exceed the season's `two_way_max`. A move that would push either count past its limit is rejected with `ERR_ROSTER_LIMIT_EXCEEDED` (HTTP 409). These limits are checked on a sign, on a promotion, and on a trade acceptance. The `roster_min` floor, by contrast, is never enforced on roster moves; it is checked only when the playoffs are started.

A two-way contract begins cap-exempt and becomes cap-counting only when its GM promotes it. Promotion is a self-loop that keeps the contract `ACTIVE` while flipping `two_way_promoted` to true so that the contract's `base_salary_cents` joins the cap-counting payroll. Promotion requires that the contract is `ACTIVE`, that its `contract_type` is `TWO_WAY`, that `two_way_promoted` is currently false, that the acting GM owns the contract's team, and that the team's `posture` is `OPEN`. It is further gated by the standard roster limit: after promotion — treating this contract as standard-counting — the team's `ACTIVE` standard count may not exceed `roster_max`, else `ERR_ROSTER_LIMIT_EXCEEDED`. A promotion request carries `expected_team_version`; however the OCC stale-version rejection in §2.7 applies specifically to trade acceptance and sponsorship distribution. On success a promotion sets `two_way_promoted` to true, recomputes the team's `payroll_active_cents` to include this contract's `base_salary_cents`, and increments both the contract's `version` and the team's `version` by 1.

For transparency a team's payroll can be read on demand, returning four figures: the cap-counting payroll `payroll_active_cents`, the full-roster commitment `full_commitment_cents`, the season's `salary_cap_cents`, and the computed `luxury_tax_cents`. The full-roster commitment is a second variant of the payroll sum: it adds `base_salary_cents` over all `ACTIVE` contracts regardless of type or promotion state, so unpromoted two-way salaries are included. The full commitment therefore exceeds the cap-counting payroll by exactly the total of all unpromoted two-way base salaries on the team.

### 3.4. Waiving Contracts and Freeing Players

A GM may waive any `ACTIVE` contract their team holds, moving the contract from `ACTIVE` to the terminal `WAIVED` status. Waiving requires that the contract is `ACTIVE`, that the acting GM owns the contract's team, and that the team's `posture` is `OPEN`; a waive on a contract that is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409). A waive request carries `expected_team_version`. On success the contract's `status` becomes `WAIVED`, the team's `payroll_active_cents` is recomputed (the waived contract no longer contributes), and both the contract's `version` and the team's `version` are incremented by 1.

Waiving may also free the player. When, after the waive, no other `ACTIVE` contract references the contract's `player_id`, that player's `status` is set back to `FREE_AGENT`. This is the only path by which a `SIGNED` player returns to `FREE_AGENT`: the player becomes free precisely when their last `ACTIVE` contract is waived. If the player still has another `ACTIVE` contract elsewhere, their status is unchanged.

### 3.5. Two-Way Call-Up Stints

A two-way contract carries a record of the periods during which its player is called up to the active roster. A GM logs a call-up by supplying the `contract_id`, a `starts_at`, and an `ends_at`. The referenced contract must be `ACTIVE` and of `contract_type` `TWO_WAY`, and it must belong to the acting GM's team. The stint's `player_id` is not supplied by the caller; it is denormalized from the contract's `player_id` at creation time and recorded on the stint. The `starts_at` marks the inclusive start of the call-up and `ends_at` its exclusive end; `ends_at` must be strictly greater than `starts_at`, and a violation is rejected with `ERR_INVALID_FIELD_VALUE` (HTTP 422).

Stints for the same player may not overlap. The check treats each stint as the half-open interval `[starts_at, ends_at)`: a new stint is rejected with `ERR_STINT_OVERLAP` (HTTP 409) if its interval overlaps any existing stint for the same `player_id`. Because the interval is half-open, adjacency is explicitly allowed — a new stint whose `starts_at` equals an existing stint's `ends_at`, or whose `ends_at` equals an existing stint's `starts_at`, does not overlap and is accepted.

### 3.6. The Trade Window and Negotiating a Trade

Trades move contracts between two teams and are gated by the season's trade window. A GM proposes a trade by supplying the `season_id` whose window governs the deal, the `from_team_id` (the proposing team, which must be the GM's own team), the `to_team_id` (the counterparty that must accept), and two arrays of contract ids: `contract_ids_out`, the contracts leaving the from-team, and `contract_ids_in`, the contracts leaving the to-team. A trade is created in `status` `PROPOSED`.

Proposing a trade requires that the season's `trade_window_state` is `OPEN`; a proposal while the window is `CLOSED` is rejected with `ERR_TRADE_WINDOW_CLOSED` (HTTP 409). The trade assets are validated: every id in `contract_ids_out` must reference an `ACTIVE` contract currently on the from-team, every id in `contract_ids_in` must reference an `ACTIVE` contract currently on the to-team, and the two lists may not both be empty — `contract_ids_out` may be empty only if `contract_ids_in` is non-empty, and vice versa. Any violation of these asset rules is rejected with `ERR_INVALID_TRADE_ASSETS` (HTTP 422).

From `PROPOSED`, a trade forks into one of three terminal outcomes, and each outcome is owned by a specific side. The counterparty GM — the owner of `to_team_id` — may accept or reject; the proposing GM — the owner of `from_team_id` — may withdraw. All three transitions require the trade to still be `PROPOSED`, else `ERR_INVALID_STATE` (HTTP 409); and each enforces ownership of the correct side, else `ERR_NOT_TEAM_OWNER` (HTTP 403).

Rejecting moves the trade from `PROPOSED` to `REJECTED`. It requires only that the trade is `PROPOSED` and that the acting GM owns the `to_team_id`. No contracts are reassigned and no payroll changes; the trade's `version` is incremented by 1. Withdrawing moves the trade from `PROPOSED` to `WITHDRAWN`. It requires that the trade is `PROPOSED` and that the acting GM owns the `from_team_id`. Likewise no contracts move and no payroll changes; the trade's `version` is incremented by 1.

### 3.7. Accepting a Trade: Cascades and Stale-Version Rejection

Accepting is the consequential branch of the fork, moving the trade from `PROPOSED` to `ACCEPTED` and physically reassigning the contracts. Acceptance is permitted only when a set of conditions all hold. The trade must still be `PROPOSED`. The acting GM must own the `to_team_id`. The season's `trade_window_state` must be `OPEN`, else `ERR_TRADE_WINDOW_CLOSED` (HTTP 409). Both involved teams must have `posture` `OPEN`; if either is `RESTRICTED`, the accept is rejected with `ERR_TEAM_RESTRICTED` (HTTP 409). Every contract in `contract_ids_out` must still be `ACTIVE` and still on the from-team, and every contract in `contract_ids_in` must still be `ACTIVE` and still on the to-team, else `ERR_INVALID_TRADE_ASSETS` (HTTP 422). After the swap, each team's `ACTIVE` standard count must remain within `roster_max` and its `ACTIVE` two-way count within `two_way_max`, else `ERR_ROSTER_LIMIT_EXCEEDED` (HTTP 409); note that `roster_min` is not enforced on a trade. The salary cap itself is soft for trades — there is no hard payroll rejection, since the cap is enforced through luxury tax rather than a roster block.

The accept request must carry `expected_to_team_version`, the `version` of the accepting team that the GM last read. If another roster mutation has advanced the to-team's `version` since then, the accept is rejected with `ERR_STALE_VERSION` (HTTP 412); a second sequential accept still carrying the old version sees a counterparty roster that has shifted underneath it and whose cap and roster math would be stale.

On a successful accept, the cascade runs in full inside the request. Each contract in `contract_ids_out` has its `team_id` reassigned to the `to_team_id`, and each contract in `contract_ids_in` has its `team_id` reassigned to the `from_team_id`; the reassigned contracts stay `ACTIVE` — there is no separate traded status, a re-homed contract simply continues as `ACTIVE` under its new team. Both teams' `payroll_active_cents` are recomputed. The `version` of the from-team and the `version` of the to-team are each incremented by 1. The trade's `status` becomes `ACCEPTED` and its `version` is incremented by 1.

### 3.8. Fines, Penalty Points, and the Posture Gate

The commissioner disciplines teams through fines. Assessing a fine supplies the `team_id` charged, the `player_id` the fine is attributed to, an `amount_cents` (the monetary penalty, which must be at least 1), and a `penalty_points` value (the points this fine adds to the team's cumulative total, which must be at least 1). The attributed player must be `SIGNED` to a contract on the charged team. A fine is created in `status` `ASSESSED`. On assessment, the fine's `penalty_points` are added to the team's cumulative `penalty_points` and the team's `version` is incremented by 1.

Penalty points drive a posture gate. A team's `posture` is `OPEN` normally and flips to `RESTRICTED` the moment its accumulated `penalty_points`, after the assessing fine is applied, reaches or exceeds the season's `penalty_threshold`; this flip increments the team's `version` by 1. A `RESTRICTED` posture is a lockout: it blocks that team from accepting trades, waiving contracts, and promoting contracts — the three roster mutations guarded by the posture gate — each rejected with `ERR_TEAM_RESTRICTED` (HTTP 409).

The commissioner may waive a fine, moving it from `ASSESSED` to `WAIVED`. Waiving requires the fine to be `ASSESSED`, else `ERR_INVALID_STATE` (HTTP 409). On a waive, the fine's `penalty_points` are subtracted back from the team's cumulative `penalty_points`, and both the fine's `version` and the team's `version` are incremented by 1. If this reversal drops the team's `penalty_points` below the season's `penalty_threshold` while the team is `RESTRICTED`, the team's `posture` returns to `OPEN`, lifting the lockout, and the team's `version` is incremented for that flip as well.

### 3.9. Sponsorship Revenue and the Distribution Waterfall

The commissioner creates a sponsorship pool by supplying a `season_id`, a `sponsor_name`, a `pool_cents` (the total revenue in cents to be shared, which must be at least 1), and an optional `league_share_pct`, the fraction the league retains off the top before the team waterfall runs. The `league_share_pct` defaults to 0.40 and must be at least 0 and strictly less than 1; a value outside this range is rejected with `ERR_INVALID_FIELD_VALUE` (HTTP 422). A sponsorship begins in `status` `PENDING`.

Distributing the pool moves the sponsorship from `PENDING` to `DISTRIBUTED`, runs the waterfall, and creates one revenue-share record per team in the season. Distribution requires the sponsorship to be `PENDING`, else `ERR_INVALID_STATE` (HTTP 409), and the season to contain at least one team. As described in §2.7, the request must carry `expected_sponsorship_version` matching the sponsorship's current `version`, else `ERR_STALE_VERSION` (HTTP 412). On success the sponsorship's `status` becomes `DISTRIBUTED` and its `version` is incremented by 1.

The waterfall takes the league cut first, off the gross pool. The league cut is `pool_cents` multiplied by `league_share_pct`, rounded half up to whole cents. The distributable amount is the pool minus that league cut; the team waterfall divides only this post-cut distributable, never the gross pool. Every team whose `season_id` matches the sponsorship's season participates, with no posture or status filter — eliminated and `RESTRICTED` teams still share. The total weight is the sum of `market_size_weight` over all participating teams. Each team's raw provisional share is the distributable multiplied by that team's `market_size_weight` divided by the total weight; each team is provisionally awarded the floor of its raw share. The leftover — the distributable minus the sum of the floored shares — is then distributed one cent at a time, walking the teams in order of `market_size_weight` descending, breaking ties by `created_at` ascending, and cycling through that order until the remainder is exhausted. The result is that the awarded shares sum exactly to the distributable amount.

Each created revenue share records the `sponsorship_id` it was carved from, the `team_id` receiving it, the `amount_cents` allocated to that team by the waterfall, and the `weight_used` — the team's `market_size_weight` snapshotted at distribution time for audit.

### 3.10. Playoff Progression

Once a season is in `PLAYOFFS`, the commissioner records the outcome of each series by marking the losing team eliminated. Eliminating a team sets its `eliminated` flag to true and increments the team's `version` by 1; the flag gates further playoff progression. The season can be completed only once exactly one team remains with `eliminated` false, as covered in §3.1.

### 3.11. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority so that the reported error is deterministic. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Next, role permission for the operation is checked, yielding `ERR_FORBIDDEN_ROLE` if the role is not allowed. Then existence of every referenced resource is validated left to right, yielding `ERR_NOT_FOUND`. Ownership follows — a `TeamGM` acting outside their own team yields `ERR_NOT_TEAM_OWNER`. Then the target's state legality for the requested transition is checked, yielding `ERR_INVALID_STATE`. Optimistic concurrency is checked next on the cap-consuming writes, yielding `ERR_STALE_VERSION`. The trade-window gate follows, yielding `ERR_TRADE_WINDOW_CLOSED`. Then the posture gate, yielding `ERR_TEAM_RESTRICTED`. Then uniqueness constraints, yielding `ERR_DUPLICATE_RESOURCE`. Then trade-asset membership, yielding `ERR_INVALID_TRADE_ASSETS`. Then roster limits, yielding `ERR_ROSTER_LIMIT_EXCEEDED`. Then playoff preconditions, yielding `ERR_PLAYOFF_PRECONDITION`. Required-field presence and pagination well-formedness yield `ERR_VALIDATION`. Field-value validity yields `ERR_INVALID_FIELD_VALUE`. Contract-term overlap yields `ERR_CONTRACT_TERM_OVERLAP`, and stint overlap yields `ERR_STINT_OVERLAP`. Earlier checks take precedence: a request failing multiple checks surfaces the highest-priority failure, so for example an authentication failure masks every later check and a state-legality failure surfaces before a roster-limit failure.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Creating a new resource returns HTTP 201; fetching, listing, and all state-transition or computed-read operations return HTTP 200. Request bodies, response bodies, and side effects are intentionally not repeated here — they are specified in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/seasons` | Create a season in SETUP | LeagueCommissioner |
| GET | `/seasons/{id}` | Fetch a season | LeagueCommissioner, TeamGM |
| POST | `/seasons/{id}/start-regular` | Advance phase SETUP to REGULAR | LeagueCommissioner |
| POST | `/seasons/{id}/trade-window` | Open or close the trade window (REGULAR only) | LeagueCommissioner |
| POST | `/seasons/{id}/start-playoffs` | Advance phase REGULAR to PLAYOFFS; assign seeds | LeagueCommissioner |
| POST | `/seasons/{id}/complete` | Advance phase PLAYOFFS to COMPLETE | LeagueCommissioner |
| POST | `/teams` | Create a team in a season | LeagueCommissioner |
| GET | `/teams/{id}` | Fetch a team | LeagueCommissioner, TeamGM |
| GET | `/teams` | List teams; filter by season_id | LeagueCommissioner, TeamGM |
| GET | `/teams/{id}/payroll` | Computed read: payroll, full commitment, luxury tax | LeagueCommissioner, TeamGM |
| GET | `/teams/{id}/contracts` | List contracts on this team | LeagueCommissioner, TeamGM |
| GET | `/teams/{id}/fines` | List fines against this team | LeagueCommissioner, TeamGM |
| GET | `/teams/{id}/revenue-shares` | List revenue shares for this team | LeagueCommissioner, TeamGM |
| POST | `/teams/{id}/eliminate` | Mark a team eliminated from the playoffs | LeagueCommissioner |
| POST | `/players` | Register a free-agent player in a season | LeagueCommissioner |
| GET | `/players/{id}` | Fetch a player | LeagueCommissioner, TeamGM |
| GET | `/players` | List players; filter by season_id | LeagueCommissioner, TeamGM |
| POST | `/contracts` | Sign a free agent to a team | TeamGM |
| GET | `/contracts/{id}` | Fetch a contract | LeagueCommissioner, TeamGM |
| GET | `/contracts` | List contracts; filter by team_id or player_id | LeagueCommissioner, TeamGM |
| POST | `/contracts/{id}/promote` | Promote a TWO_WAY contract to count toward the cap | TeamGM |
| POST | `/contracts/{id}/waive` | Waive a contract; may free the player | TeamGM |
| POST | `/stints` | Log a two-way call-up stint against a contract | TeamGM |
| GET | `/stints/{id}` | Fetch a stint | LeagueCommissioner, TeamGM |
| GET | `/stints` | List stints; filter by contract_id or player_id | LeagueCommissioner, TeamGM |
| POST | `/trades` | Propose a trade between two teams | TeamGM |
| GET | `/trades/{id}` | Fetch a trade | LeagueCommissioner, TeamGM |
| GET | `/trades` | List trades; filter by season_id, from_team_id, or to_team_id | LeagueCommissioner, TeamGM |
| POST | `/trades/{id}/accept` | Counterparty accepts; reassigns contracts, recomputes payroll | TeamGM |
| POST | `/trades/{id}/reject` | Counterparty rejects | TeamGM |
| POST | `/trades/{id}/withdraw` | Proposer withdraws | TeamGM |
| POST | `/fines` | Assess a fine against a team/player | LeagueCommissioner |
| GET | `/fines/{id}` | Fetch a fine | LeagueCommissioner, TeamGM |
| GET | `/fines` | List fines; filter by team_id or player_id | LeagueCommissioner, TeamGM |
| POST | `/fines/{id}/waive` | Waive a fine; reverses penalty points | LeagueCommissioner |
| POST | `/sponsorships` | Create a sponsorship pool | LeagueCommissioner |
| GET | `/sponsorships/{id}` | Fetch a sponsorship | LeagueCommissioner, TeamGM |
| GET | `/sponsorships` | List sponsorships; filter by season_id | LeagueCommissioner, TeamGM |
| GET | `/sponsorships/{id}/revenue-shares` | List shares carved from this sponsorship | LeagueCommissioner, TeamGM |
| POST | `/sponsorships/{id}/distribute` | Distribute the pool across all season teams | LeagueCommissioner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_TEAM_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TRADE_WINDOW_CLOSED | 409 |
| ERR_TEAM_RESTRICTED | 409 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_INVALID_TRADE_ASSETS | 422 |
| ERR_ROSTER_LIMIT_EXCEEDED | 409 |
| ERR_PLAYOFF_PRECONDITION | 409 |
| ERR_INVALID_FIELD_VALUE | 422 |
| ERR_CONTRACT_TERM_OVERLAP | 409 |
| ERR_STINT_OVERLAP | 409 |
| ERR_VALIDATION | 400 |
