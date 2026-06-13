# Sports Officiating Assignment API — Product Requirements Document

## 1. Introduction

Leagues that run competitive schedules face a recurring operational headache: matching a finite pool of certified officials to a stream of games, each of which needs a specific crew, while honouring travel limits, blackout windows, conflicts of interest, and rank requirements. The Sports Officiating Assignment API exists to make that matching reliable and auditable. It models the full arc of an officiating season — from configuring a league and registering its officials, through provisioning crew slots and offering them to eligible referees, to settling pay and reconciling penalties at season's end.

The system treats crew slots as a scarce resource that is competed for, reserved, committed, and — when an official declines, no-shows, or withdraws — released back into circulation for re-offer. Because several assignors and officials may be acting against the same game at once, the platform layers optimistic concurrency control over game-level writes so that a stale view of remaining capacity never silently overwrites a fresh one. Money and reliability are first-class concerns as well: every accepted assignment carries a provisional pay estimate frozen at offer time, while settlement recomputes a finalized figure that reflects the official's rank and reliability standing at the moment the game is closed. Throughout, the API maintains denormalized counters — crew fill counts, games worked, no-show tallies, reliability scores — so that operators always read a consistent, immediately reconciled picture of the season.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. These two checks run ahead of all other validation.

The system recognizes exactly four roles: `LeagueAdmin`, `Assignor`, `Official`, and `Evaluator`.

A `LeagueAdmin` configures leagues, registers officials, manages ranks and suspension, drives league posture, adjudicates penalty appeals, and controls the test clock. An `Assignor` owns game creation, crew provisioning, slot offers, locking, settlement, cancellation, and no-show recording. An `Official` is an officiating referee who owns their own availability, conflict declarations, and responses to offers (accepting, declining, or withdrawing), as well as appealing penalties. An `Evaluator` rates officials on completed assignments. All four roles may perform any read (GET) operation.

Three of the four roles carry an **opaque** identity. When `X-User-Role` is `LeagueAdmin`, `Assignor`, or `Evaluator`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server may accept and log it, but it does not compare it to any entity's `id`. The `Official` role is **entity-backed**: when `X-User-Role` is `Official`, `X-User-ID` is the `id` of the acting `Official`, and ownership checks on a resource that references an official compare the resource's official foreign key to `X-User-ID`. Concretely, when an official accepts, declines, withdraws, or appeals an assignment, the system requires that `X-User-ID` equal the assignment's `official_id`; a mismatch is rejected with `ERR_NOT_ASSIGNMENT_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by their creation timestamp, `created_at`, in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Most resources in this system are mutable and carry a common set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, in the same format, recording when the resource was last modified; it advances on every mutation.
- `version` — a system-managed integer that starts at its initial value and increments by one with every modification. It underpins the optimistic concurrency mechanism described in §2.6.

Leagues, Officials, Games, CrewSlots, Assignments, Availabilities, SeasonLedgers, and PenaltyAppeals all carry this full set. Two record types are deliberately leaner: a `ConflictDeclaration` and an `Evaluation` are immutable once written, so each carries only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field, and they are never the target of an update or a concurrency check.

When a derived or denormalized field changes on a resource (for example, a Game's `crew_filled_count`, or an Official's `reliability_score`), that change is itself a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Hierarchical Consistency and Reconciliation

Many operations ripple across more than one entity, and the system reconciles those effects immediately rather than lazily. The canonical chain runs Game → CrewSlot → Assignment, and effects propagate in both directions along it. When an official accepts an offer, the slot becomes filled, the owning game's `crew_filled_count` is recomputed, and — if that count reaches the game's `required_crew_size` — the game automatically advances from `OPEN` to `STAFFED` without any explicit request on the game itself. Conversely, when a filled slot is vacated by a decline, no-show, withdrawal, or cancellation, `crew_filled_count` is recomputed downward, and if it falls below `required_crew_size` the game automatically bubbles from `STAFFED` back to `OPEN` so the slot can be re-offered.

Each such reconciliation independently mutates the affected resource, advancing its `updated_at` and incrementing its `version`. Cascades can run several levels deep: cancelling a game releases every crew slot and cancels every live assignment on it, a depth-three propagation from game down through slots to assignments.

### 2.6. Optimistic Concurrency on Games

Because crew slots on a single game are competed for, the system protects game-level writes with optimistic concurrency control keyed on the game's `version`. Two write operations participate in this protection, and both require the caller to submit an `expected_game_version` field carrying the game version the caller last observed.

When offering a slot, the request must include `expected_game_version`. If a prior offer or acceptance against a sibling slot has already advanced the game's version since the assignor last read it — for example, because a previous fill recomputed `crew_filled_count` or bubbled the game to `STAFFED` — then the submitted `expected_game_version` no longer matches the game's current `version`, and the offer is rejected with `ERR_STALE_GAME_VERSION` (HTTP 412). This prevents an assignor working from a stale picture of remaining capacity from overwriting state they have not observed.

Likewise, when an official accepts an offered assignment, the request must include `expected_game_version`. If another official's acceptance against a sibling slot has bumped the game version since this official last fetched the game, the acceptance carries an outdated version and is rejected with `ERR_STALE_GAME_VERSION` (HTTP 412). Locking and settling a game also compare the submitted `expected_game_version` against the game's current `version` and reject a mismatch with the same `ERR_STALE_GAME_VERSION` (HTTP 412).

A second, independent concurrency guard governs updates to an official's mutable profile. An update to an official must submit `expected_official_version`; if it does not equal the official's current `version`, the update is rejected with `ERR_STALE_OFFICIAL_VERSION` (HTTP 412). Endpoints not named here take no version field.

### 2.7. Nested and Reverse-Reachability Reads

Several read endpoints address a resource through a parent identifier in the path — for example, the crew slots of a game, the assignments of an official or a crew slot, the evaluations or appeals of an assignment, or the season ledgers of a league. For any request whose path contains a resource identifier, the system validates that identifier's existence before evaluating anything nested beneath it, working strictly left to right. A reference to a resource that does not exist — whether named in the path or the body — is rejected with `ERR_NOT_FOUND`. These reverse-reachability lists let a caller walk the entity graph without the API resorting to deep URL nesting; the underlying entities remain peers linked by foreign keys.

### 2.8. Money, Points, and Rounding

All monetary amounts in this system — league fees, accrued pay, mileage reimbursement — are integer cents, and all penalty figures are integer points. Wherever a calculation in §3 calls for rounding, the system uses the round-half-up convention, and rounding is applied at each individual rounding step named in the formula rather than only once at the end. Pay figures resolve to whole integer cents; penalty and reliability figures resolve to whole integer points. Evaluation ratings are the one place decimals survive: a mean rating is carried to exactly two decimal places, again using round-half-up.

### 2.9. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Ownership of an assignment by the acting official (`ERR_NOT_ASSIGNMENT_OWNER`) is checked next where it applies. Business-specific constraints follow, and structural input validity — required fields present, enums recognized, numeric ranges respected — is the last gate, surfacing `ERR_INVALID_REQUEST`. The ordering of the offer-time eligibility checks is spelled out within the offer workflow in §3, because their relative precedence is itself part of the contract.

## 3. Business Logic & Workflows

### 3.1. Standing Up a League and Its Officials

A `LeagueAdmin` opens the season by creating a league, supplying its `name`, its `sport` — one of `BASKETBALL`, `SOCCER`, `HOCKEY`, or `FOOTBALL` — and the economic baseline: a `base_game_fee_cents` figure (the per-official base fee in cents before any rank multiplier, which may not be negative) and a `mileage_rate_cents_per_mile` reimbursement rate (an integer number of cents per mile, also non-negative). Three postseason thresholds may be supplied or left to default: `postseason_min_games`, the minimum number of regular-season games an official must have worked to qualify, defaults to 8; `postseason_min_rating`, the minimum mean evaluation rating on the one-to-five scale, defaults to 3.5; and `postseason_max_noshows`, the most no-shows tolerated while staying eligible, defaults to 0. A freshly created league begins in `SETUP`. A league's `status` proceeds through `SETUP`, `OPEN`, `POSTSEASON`, and finally `ARCHIVED`.

The admin moves a league from `SETUP` to `OPEN` through an activation step; this transition is defined only from `SETUP`, and attempting it from any other state is rejected with `ERR_INVALID_STATE`. Later, the admin can drive the league from `OPEN` into `POSTSEASON` by starting the postseason, which is defined only from `OPEN`. Starting the postseason has an important side effect: it recomputes `postseason_eligible` for every official in the league, a league-to-officials cascade. Finally, the admin can archive a league, an `POSTSEASON → ARCHIVED` move defined only from `POSTSEASON`.

When a league is created, the system also stands up its season-ledger scaffolding. Registering an official is a separate `LeagueAdmin` operation that ties the official to a league through `league_id` and records the official's `full_name`, a home location given as `home_lat` and `home_lon` (decimal degrees, used for travel-radius math), and an optional `max_travel_miles` cap (defaulting to 50) beyond which the official will not be auto-eligible for games by great-circle distance. The official's `rank` may be supplied and defaults to `ROOKIE`; the rank ladder runs `ROOKIE`, `CERTIFIED`, `SENIOR`, `MASTER` and sets both pay multiplier and referee eligibility. Every official starts with a `status` of `ACTIVE`; the only other value is `SUSPENDED`, which blocks new offers. Registering an official also creates that official's `SeasonLedger` row for the league with `penalty_points` initialized to 0.

Several official fields are read-only and maintained by the system: `games_worked_count` (the number of this official's assignments that reached `COMPLETED` this season), `noshow_count` (the count that reached `NO_SHOW`), `penalty_points` (the running penalty total from declines and no-shows, mirroring the season ledger), `mean_rating` (the mean evaluation score over completed assignments, carried to two decimals, null when no evaluations exist), `reliability_score` (a denormalized gauge, described in §3.7), and `postseason_eligible` (the derived eligibility flag, described in §3.8). A `LeagueAdmin` may update an official's mutable fields — promoting `rank`, adjusting `max_travel_miles`, or toggling `status` — but only by submitting the official's current version as `expected_official_version`; a mismatch is rejected with `ERR_STALE_OFFICIAL_VERSION` and a successful update increments the official's `version` by one.

### 3.2. Officials Publishing Availability and Conflicts

Before an official can be offered work, the system needs to know when they are free. An `Official` (or a `LeagueAdmin` acting on their behalf) declares an availability window tied to an official via `official_id`, bounded by `window_start_utc` and `window_end_utc`. A window is a half-open interval — the start is inclusive and the end is exclusive — and the end must be strictly later than the start; a window whose `window_end_utc` is not strictly after its `window_start_utc` is rejected with `ERR_INVALID_REQUEST`. The window's `kind` defaults to `AVAILABLE`; the alternative, `BLACKOUT`, carves time back out of availability. A window's `status` begins `ACTIVE` and can later be moved to `WITHDRAWN`, retiring it from consideration; withdrawal is the only state transition a window supports.

Officials also publish conflicts of interest, recorded as immutable conflict declarations. A declaration names the conflicted official via `official_id` and a `scope` of either `TEAM` or `OFFICIAL`. A `TEAM`-scoped declaration must carry a `team_name` (and no peer) identifying a team the official cannot officiate; an `OFFICIAL`-scoped declaration must carry a `peer_official_id` (and no team name) identifying a peer the official cannot share a crew with. A scope that does not match the field supplied — a `TEAM` scope without a `team_name`, or an `OFFICIAL` scope without a `peer_official_id` — is rejected with `ERR_INVALID_REQUEST`. Conflict declarations may be created by either an `Official` or a `LeagueAdmin`, and once written they are never modified.

### 3.3. Building a Game and Provisioning Its Crew

An `Assignor` creates a game against a league through `league_id`, naming the `home_team` and `away_team`, fixing the venue with `venue_lat` and `venue_lon`, and setting the kickoff with `start_utc`. The scheduled length is `duration_minutes`, which defaults to 120 and must be strictly positive; together with the start it defines the game's occupied interval, running from `start_utc` to `start_utc` plus the duration. The crew size is given by `required_crew_size`, which must be at least 1. A game may be flagged `is_postseason` (defaulting to false), which turns on the postseason eligibility gate when slots are offered. A new game begins in `DRAFT`, and its `status` traverses `DRAFT`, `OPEN`, `STAFFED`, `LOCKED`, `COMPLETED`, and `CANCELLED`.

While the game is still in `DRAFT`, the assignor provisions its crew slots, one at a time. Each slot belongs to a game via `game_id` and is created with a `position` — `REFEREE`, `ASSISTANT`, or `OBSERVER` — and an optional `slot_fee_multiplier` (defaulting to 1.0) that scales the league base fee for that position. A slot's `status` runs `VACANT`, `OFFERED`, `FILLED`, and `RELEASED`, beginning at `VACANT`. While live, a slot tracks the assignment currently holding it through `current_assignment_id`, a back-pointer to the non-terminal assignment; it is null whenever the slot is `VACANT` or `RELEASED`.

Opening a game advances it from `DRAFT` to `OPEN`. This is only permitted when the game is in `DRAFT` (otherwise `ERR_INVALID_STATE`), when its league is `OPEN` (otherwise `ERR_LEAGUE_NOT_OPEN`), and when the number of crew slots provisioned exactly equals `required_crew_size` (otherwise `ERR_CREW_NOT_PROVISIONED`). Once open, the slots remain `VACANT` but become offerable.

### 3.4. Offering a Slot and Running the Eligibility Gauntlet

Offering a vacant slot to an official is the heart of the system, and it is the operation that runs the full eligibility check. An `Assignor` offers a slot by naming the candidate via `official_id` and supplying `expected_game_version` for the optimistic-concurrency check described in §2.6. The offer is defined only from a slot in `VACANT` (otherwise `ERR_SLOT_NOT_VACANT`) on a game whose `status` is `OPEN` (otherwise `ERR_GAME_NOT_OPEN`). When it succeeds, the system creates an assignment in `OFFERED`, sets the slot's `current_assignment_id`, advances the slot from `VACANT` to `OFFERED`, freezes the assignment's `distance_miles` and `provisional_pay_cents` at this moment, and increments the game's `version` by one.

Before any of that happens, the offer must clear a sequence of business checks, evaluated in this order:

1. **Suspension.** The candidate official's `status` must be `ACTIVE`; a `SUSPENDED` official cannot receive a new offer and the request is rejected with `ERR_OFFICIAL_SUSPENDED`.
2. **Rank eligibility.** If the slot's `position` is `REFEREE`, the official's `rank` must be `SENIOR` or `MASTER`; a lower rank is rejected with `ERR_RANK_INELIGIBLE`.
3. **Conflict of interest.** The official must have no `TEAM`-scoped conflict naming this game's `home_team` or `away_team`, and no `OFFICIAL`-scoped conflict with any official already `FILLED` on the same game; a violation of either is rejected with `ERR_CONFLICT_OF_INTEREST`.
4. **Availability cover.** The game's occupied interval (from `start_utc` to `start_utc` plus `duration_minutes`, treated as half-open with the end excluded) must lie entirely inside at least one of the official's `ACTIVE` `AVAILABLE` windows and must not intersect any `ACTIVE` `BLACKOUT` window; otherwise the offer is rejected with `ERR_OUTSIDE_AVAILABILITY`.
5. **Double-booking.** The game's interval must not overlap the interval of any other game on which this official already holds an `OFFERED` or `ACCEPTED` assignment; overlap is measured closed on the start and open on the end, so two games that merely touch at an endpoint do not conflict. A clash is rejected with `ERR_OFFICIAL_DOUBLE_BOOKED`.
6. **Travel radius.** The great-circle distance between the official's home location and the game's venue must be at most the official's `max_travel_miles`; a longer trip is rejected with `ERR_OUTSIDE_TRAVEL_RADIUS`.
7. **Postseason gate.** If the game's `is_postseason` flag is set, the candidate must currently be `postseason_eligible`; an ineligible official is rejected with `ERR_NOT_POSTSEASON_ELIGIBLE`.

The frozen `distance_miles` is the great-circle distance in miles between the official's home (`home_lat`, `home_lon`) and the venue (`venue_lat`, `venue_lon`), carried to two decimal places. The assignment's `mileage_cents` reimbursement is that distance rounded to the nearest whole mile (round-half-up) multiplied by the league's `mileage_rate_cents_per_mile`.

### 3.5. Provisional Pay at Offer Time

At the instant an offer is made, the assignment's `provisional_pay_cents` is frozen as a forward-looking estimate, computed entirely from values known at offer time and from the official's rank as it stands at that moment. The estimate is built in steps. First, a rank multiplier is selected by the official's `rank`: `ROOKIE` maps to 1.0, `CERTIFIED` to 1.25, `SENIOR` to 1.5, and `MASTER` to 2.0. The pay base is the league's `base_game_fee_cents` multiplied by the slot's `slot_fee_multiplier`. The game pay is that base multiplied by the rank multiplier, rounded half-up to whole cents. If the game's `is_postseason` flag is set, this game pay is then multiplied by a postseason uplift factor of 1.20 and again rounded half-up to whole cents — the uplift is applied to the game pay before mileage is added. Finally, the mileage component (the rounded-to-whole-mile `distance_miles` multiplied by `mileage_rate_cents_per_mile`) is added to the game pay to yield `provisional_pay_cents`.

Because the rank multiplier here is read at offer time and frozen, an official who is promoted between the offer and settlement will see the provisional estimate diverge from the eventual settled figure; the provisional number deliberately reflects only what was known when the slot was offered.

### 3.6. Responding to an Offer: Accept, Decline, Withdraw

An assignment links a crew slot, a game, and an official: its `crew_slot_id` names the slot, its `game_id` is copied from the slot at offer time, and its `official_id` names the candidate. An assignment's `status` runs through `OFFERED`, `ACCEPTED`, `DECLINED`, `CANCELLED`, `COMPLETED`, and `NO_SHOW`, beginning at `OFFERED`.

When an `Official` accepts an offer — a move defined only from `OFFERED` — the system verifies that the acting official owns the assignment (its `official_id`, else `ERR_NOT_ASSIGNMENT_OWNER`), that the game is still `OPEN` (else `ERR_GAME_NOT_OPEN`), and that no already-`ACCEPTED` assignment for this official overlaps this game's interval (else `ERR_OFFICIAL_DOUBLE_BOOKED`). Acceptance also carries `expected_game_version` and is subject to the stale-version rejection of §2.6. On success the assignment advances `OFFERED → ACCEPTED`, the slot advances `OFFERED → FILLED`, the game's `crew_filled_count` is recomputed, and the game may bubble `OPEN → STAFFED` if the crew is now complete; the game's `version` increments by one.

Declining an offer is likewise defined only from `OFFERED` and likewise requires the acting official to own the assignment (`ERR_NOT_ASSIGNMENT_OWNER`). A decline advances the assignment `OFFERED → DECLINED`, assesses a decline penalty into `penalty_assessed_points` (computed as described in §3.9), adds that figure to the official's `SeasonLedger.penalty_points`, and recomputes the official's `penalty_points` and `reliability_score`. The slot then returns from `OFFERED` to `VACANT`, its `current_assignment_id` is cleared, and it becomes offerable again — the cyclic re-offer loop that lets a slot be put back on the market.

An official may also withdraw from an assignment they have already accepted, provided the game has not yet been locked. Withdrawal is defined only from `ACCEPTED`, requires ownership (`ERR_NOT_ASSIGNMENT_OWNER`), and is permitted only while the game is `OPEN` or `STAFFED`; attempting it once the game is `LOCKED` is rejected with `ERR_GAME_LOCKED`. A withdrawal is treated as a late decline: it advances the assignment `ACCEPTED → CANCELLED`, assesses the same decline-penalty calculation into `penalty_assessed_points`, adds it to `SeasonLedger.penalty_points`, returns the slot to `VACANT`, recomputes `crew_filled_count`, and may bubble the game `STAFFED → OPEN`.

### 3.7. No-Shows, Penalties, and Reliability

After a game has started, an `Assignor` may record that an official failed to appear. Recording a no-show is defined only from an `ACCEPTED` assignment (else `ERR_INVALID_STATE`), requires the game to be in `STAFFED` or `LOCKED` (else `ERR_INVALID_STATE`), and requires the game to have actually started — its `start_utc` must be at or before the current clock (else `ERR_GAME_NOT_STARTED`). A no-show advances the assignment `ACCEPTED → NO_SHOW`, computes a no-show penalty into `penalty_assessed_points` (see §3.9), adds it to `SeasonLedger.penalty_points`, and recomputes the official's `noshow_count`, `penalty_points`, and `reliability_score`. The slot returns to `VACANT` and `crew_filled_count` is recomputed; if the game was `STAFFED` it may bubble back to `OPEN`, whereas a `LOCKED` game simply remains `LOCKED` carrying a now-vacant slot.

An official's `reliability_score` is a denormalized gauge recomputed on any change to their season-ledger `penalty_points`. It is 100 minus the season ledger's `penalty_points`, floored at 0 — never negative and never above 100. The official's own `penalty_points` field mirrors the season ledger's accumulated total.

### 3.8. How Penalties Are Sized

Both penalty calculations resolve to whole integer points using round-half-up.

The **decline penalty** (applied on a decline and on a withdrawal, since a withdrawal is a late decline) is sized from three inputs: how much lead time remains before the game, how many penalised declines the official has already accrued this season, and whether the game is postseason. Lead time is the number of hours between the game's `start_utc` and the current clock, which may be negative if the game is already in the past. A base penalty is chosen by lead time: if fewer than 24 hours remain, the base is 8 points (a late decline); otherwise if fewer than 72 hours remain, the base is 4 points; otherwise the base is 1 point. An escalation is then added on top: it is the number of the official's prior penalised declines — that is, this official's terminal assignments carrying a positive `penalty_assessed_points` created before this one, ordered by `created_at` ascending — capped at 3, multiplied by 2 points each. The base plus escalation is then multiplied by a postseason factor of 2.0 if the game is postseason (otherwise by 1.0), and the result is rounded half-up to whole points.

The **no-show penalty** (applied when an accepted assignment becomes a no-show) starts from a base of 15 points. An escalation is added equal to the number of this official's prior no-shows — their `NO_SHOW` assignments created before this one, ordered by `created_at` ascending — capped at 3, multiplied by 5 points each. The base plus escalation is then multiplied by a postseason factor of 2.0 when the game is postseason (otherwise by 1.0), and rounded half-up to whole points.

### 3.9. Locking, Settling, and Finalized Pay

When a crew is complete, an `Assignor` locks the game, a `STAFFED → LOCKED` move that is permitted only when the game is in `STAFFED` (else `ERR_INVALID_STATE`) and its `crew_filled_count` equals `required_crew_size` (else `ERR_CREW_INCOMPLETE`). Locking carries `expected_game_version`, freezes all filled slots so that no further offers are accepted, and increments the game's `version` by one.

Settling a game is the season's payday. It is defined only from `LOCKED` (else `ERR_INVALID_STATE`) and only once the game has started — its `start_utc` must be at or before the current clock (else `ERR_GAME_NOT_STARTED`). Settlement carries `expected_game_version`. It advances the game `LOCKED → COMPLETED`, drives each filled slot's `ACCEPTED` assignment to `COMPLETED` with its `final_pay_cents` computed, accrues those amounts into the season ledgers, recomputes the game's `settlement_total_cents`, recomputes each official's `games_worked_count`, and increments the game's `version` by one.

The `final_pay_cents` is computed at settlement and, unlike the provisional estimate, reads the official's rank as of settlement time. A rank multiplier is selected by the official's settlement-time `rank` on the same scale as the provisional calculation (`ROOKIE` 1.0, `CERTIFIED` 1.25, `SENIOR` 1.5, `MASTER` 2.0). The pay base is again the league's `base_game_fee_cents` multiplied by the slot's `slot_fee_multiplier`, and the game pay is that base times the rank multiplier, rounded half-up to whole cents. If the game is postseason, the game pay is multiplied by the same 1.20 uplift and rounded half-up to whole cents. Then a reliability deduction is applied that has no counterpart in the provisional estimate: if the official's `penalty_points` as of settlement is at least 10, the game pay is reduced to 90 percent of itself — that is, multiplied by the difference between one and a deduction fraction of 0.10 — and rounded half-up to whole cents. The mileage component (the offer-frozen `distance_miles` rounded to whole miles times `mileage_rate_cents_per_mile`) is added last to yield `final_pay_cents`. Until a game is settled, every assignment's `final_pay_cents` is 0, and a game's `settlement_total_cents` is 0; after settlement, `settlement_total_cents` is the sum of `final_pay_cents` over the game's completed assignments.

Settlement accrual obeys a pay-conservation invariant: each official's `SeasonLedger.total_pay_accrued_cents` increases by the sum of their settled `final_pay_cents`, and `total_mileage_accrued_cents` increases by the sum of their settled `mileage_cents`. Because the provisional estimate is frozen at offer time while the finalized figure reflects settlement-time rank and the reliability deduction, the two figures diverge whenever an official's rank changed or their penalty points crossed the deduction threshold between offer and settlement.

### 3.10. Cancelling a Game

An `Assignor` may cancel a game from any of `DRAFT`, `OPEN`, `STAFFED`, or `LOCKED`; attempting cancellation from a terminal state is rejected with `ERR_INVALID_STATE`. Cancellation drives the game to `CANCELLED`, moves every non-terminal assignment on the game to `CANCELLED` with no penalty assessed, releases every crew slot to `RELEASED`, and increments the game's `version` by one. This is the depth-three cascade noted in §2.5: the game's terminal transition pulls its slots and their live assignments along with it. A slot that was `VACANT`, `OFFERED`, or `FILLED` at cancellation time moves to `RELEASED`; where a slot still held a live assignment, that assignment is driven to `CANCELLED` as part of the release.

### 3.11. Evaluations and Mean Rating

Once an assignment is `COMPLETED`, an `Evaluator` may rate it. An evaluation targets an assignment via `assignment_id` and carries a `score` on the one-to-five scale (the score must be at least 1.0 and at most 5.0, else `ERR_INVALID_REQUEST`) plus an optional `comment`. The evaluated official is captured on the evaluation as `official_id`, copied from the assignment. An evaluation may target only a `COMPLETED` assignment, and only one evaluation may exist per assignment; rating a non-completed assignment or adding a second evaluation to one already rated is rejected with `ERR_ASSIGNMENT_NOT_COMPLETED`. Appending an evaluation recomputes the official's `mean_rating`.

The `mean_rating` is computed with a pinned order that matters: first each individual evaluation `score` (over the official's completed-assignment evaluations) is rounded half-up to two decimal places, then the arithmetic mean of those rounded values is taken, and that mean is rounded half-up to two decimal places. This is round-per-item, then average, then round — not average-the-raw-scores-then-round. When the official has no evaluations, `mean_rating` is null.

### 3.12. Postseason Eligibility

An official's `postseason_eligible` flag is derived and recomputed when the league starts its postseason and on demand through the eligibility read. An official is eligible only when all of the following hold at once: their `games_worked_count` is at least the league's `postseason_min_games`; their `mean_rating` is not null and is at least the league's `postseason_min_rating`; their `noshow_count` is at most the league's `postseason_max_noshows`; and their `status` is `ACTIVE`. If any one of these fails, the official is not eligible. The eligibility read returns the official with this breakdown — games worked, mean rating, no-show count, and the resulting eligibility — recomputed at read time.

### 3.13. Appealing a Penalty

An `Official` may appeal the penalty on one of their own assignments. An appeal targets an assignment via `assignment_id` and states the grounds in `reason`; the appealing official is captured as `official_id`, copied from the assignment, and the acting user must own that assignment (`ERR_NOT_ASSIGNMENT_OWNER`). An appeal may be filed only against an assignment in `DECLINED` or `NO_SHOW` whose `penalty_assessed_points` is greater than 0, and at most one appeal that is `PENDING` or `UPHELD` may exist per assignment; an attempt that violates either condition is rejected with `ERR_NOT_APPEALABLE`. A new appeal's `status` begins `PENDING`, with `reversed_points` at 0; the lifecycle terminates at `UPHELD` or `DENIED`.

A `LeagueAdmin` adjudicates. Upholding an appeal is defined only from `PENDING`, and additionally requires that the appealed assignment is still in `DECLINED` or `NO_SHOW` (else `ERR_INVALID_STATE`). Upholding sets `reversed_points` to the appealed assignment's `penalty_assessed_points`, subtracts that figure from the official's `SeasonLedger.penalty_points` (floored at 0), and recomputes the official's `penalty_points` and `reliability_score`. If the appealed assignment was a `NO_SHOW`, the official's `noshow_count` is also recomputed excluding that assignment, which can in turn change `postseason_eligible` — a cascade from appeal through the official's no-show count to eligibility. The system holds a penalty-conservation invariant: a season ledger's `penalty_points` always equals the sum of `penalty_assessed_points` over terminal assignments minus the sum of `reversed_points` over upheld appeals.

Denying an appeal is the divergent branch. It is defined only from `PENDING`, leaves `reversed_points` at 0, advances the appeal `PENDING → DENIED`, and makes no change to any ledger — the explicit contrast with the upheld branch, which alone reverses points.

### 3.14. The Test Clock

Several transitions are gated on time — settlement and no-show recording both require the game to have started. To make those gates exercisable deterministically, a `LeagueAdmin` capability sets the server's logical current UTC clock to a supplied `to_iso8601` instant. All comparisons against "the current clock" throughout this document read from that logical clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state-transition actions, return `200 OK`. Every endpoint emits the standard envelope of §2.2 and is subject to the authentication, authorization, and validation rules of §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/leagues` | Create a league and its season-ledger scaffolding | LeagueAdmin |
| GET | `/leagues` | List leagues | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/leagues/{id}` | Get a league | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/leagues/{id}/season-ledgers` | List season-ledger rows for a league | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/leagues/{id}/activate` | Activate a league (SETUP → OPEN) | LeagueAdmin |
| POST | `/leagues/{id}/start-postseason` | Start postseason (OPEN → POSTSEASON); recompute eligibility | LeagueAdmin |
| POST | `/leagues/{id}/archive` | Archive a league (POSTSEASON → ARCHIVED) | LeagueAdmin |
| POST | `/officials` | Register an official and create their season-ledger row | LeagueAdmin |
| GET | `/officials` | List/filter officials | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/officials/{id}` | Get an official with computed fields | LeagueAdmin, Assignor, Official, Evaluator |
| PATCH | `/officials/{id}` | Update mutable official fields | LeagueAdmin |
| GET | `/officials/{id}/eligibility` | Postseason eligibility breakdown | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/officials/{id}/assignments` | List assignments for an official | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/officials/{id}/ledger` | List season-ledger rows for an official | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/availabilities` | Declare an availability or blackout window | Official, LeagueAdmin |
| GET | `/availabilities` | List/filter availability windows | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/availabilities/{id}` | Get an availability window | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/availabilities/{id}/withdraw` | Withdraw a window (ACTIVE → WITHDRAWN) | Official, LeagueAdmin |
| POST | `/conflict-declarations` | Declare a conflict of interest | LeagueAdmin, Official |
| GET | `/conflict-declarations` | List/filter conflict declarations | LeagueAdmin, Assignor, Official |
| GET | `/conflict-declarations/{id}` | Get a conflict declaration | LeagueAdmin, Assignor, Official |
| POST | `/games` | Create a game (DRAFT) | Assignor |
| GET | `/games` | List/filter games | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/games/{id}` | Get a game with computed counters | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/games/{id}/crew-slots` | Provision a crew slot on a DRAFT game | Assignor |
| GET | `/games/{id}/crew-slots` | List crew slots for a game | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/games/{id}/open` | Open a game (DRAFT → OPEN) | Assignor |
| POST | `/games/{id}/lock` | Lock a game (STAFFED → LOCKED) | Assignor |
| POST | `/games/{id}/settle` | Settle a game (LOCKED → COMPLETED) | Assignor |
| POST | `/games/{id}/cancel` | Cancel a game; cascade-release crew | Assignor |
| GET | `/crew-slots/{id}` | Get a crew slot | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/crew-slots/{id}/assignments` | List assignment history for a crew slot | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/crew-slots/{id}/offer` | Offer the slot to an official; run eligibility; OCC on game | Assignor |
| GET | `/assignments` | List/filter assignments by FK | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/assignments/{id}` | Get an assignment | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/assignments/{id}/accept` | Accept an offered assignment; OCC on game | Official |
| POST | `/assignments/{id}/decline` | Decline an offered assignment; assess penalty | Official |
| POST | `/assignments/{id}/withdraw` | Withdraw an accepted assignment; assess late-decline penalty | Official |
| POST | `/assignments/{id}/no-show` | Record a no-show after game start | Assignor |
| POST | `/assignments/{id}/evaluations` | Rate a completed assignment | Evaluator |
| GET | `/assignments/{id}/evaluations` | List evaluations for an assignment | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/assignments/{id}/appeals` | Appeal the penalty on a declined or no-show assignment | Official |
| GET | `/assignments/{id}/appeals` | List penalty appeals for an assignment | LeagueAdmin, Assignor, Official, Evaluator |
| GET | `/penalty-appeals/{id}` | Get a penalty appeal | LeagueAdmin, Assignor, Official, Evaluator |
| POST | `/penalty-appeals/{id}/uphold` | Uphold an appeal; reverse assessed points | LeagueAdmin |
| POST | `/penalty-appeals/{id}/deny` | Deny an appeal; no ledger change | LeagueAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | LeagueAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LEAGUE_NOT_OPEN` | 409 Conflict |
| `ERR_GAME_NOT_OPEN` | 409 Conflict |
| `ERR_GAME_LOCKED` | 409 Conflict |
| `ERR_GAME_NOT_STARTED` | 409 Conflict |
| `ERR_CREW_NOT_PROVISIONED` | 409 Conflict |
| `ERR_CREW_INCOMPLETE` | 409 Conflict |
| `ERR_SLOT_NOT_VACANT` | 409 Conflict |
| `ERR_OFFICIAL_SUSPENDED` | 409 Conflict |
| `ERR_RANK_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_AVAILABILITY` | 422 Unprocessable Entity |
| `ERR_OFFICIAL_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_OUTSIDE_TRAVEL_RADIUS` | 422 Unprocessable Entity |
| `ERR_NOT_POSTSEASON_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_NOT_COMPLETED` | 409 Conflict |
| `ERR_NOT_APPEALABLE` | 409 Conflict |
| `ERR_NOT_ASSIGNMENT_OWNER` | 403 Forbidden |
| `ERR_STALE_GAME_VERSION` | 412 Precondition Failed |
| `ERR_STALE_OFFICIAL_VERSION` | 412 Precondition Failed |
