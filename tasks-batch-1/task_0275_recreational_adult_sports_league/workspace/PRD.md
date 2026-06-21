# Recreational Adult Sports League API — Product Requirements Document

## 1. Introduction

Community sports leagues live and die by the messy human logistics that surround the games themselves: captains assembling rosters from a mix of returning teammates and unattached free agents, an operations desk juggling field availability against turnover-cleaning windows, referees who must not be double-booked, and the inevitable disputes over a final score or a player's on-field behaviour. This API is the system of record for a recreational adult sports league that runs one or more seasons across several sports, organizes teams into skill-tiered divisions, schedules games at shared venues, staffs them with certified officials, tracks standings and seeds playoff brackets, and administers the money — registration fees and the prorated refunds that follow a withdrawal.

The product serves four operational constituencies whose authority is deliberately partitioned. League administrators own the season calendar, divisions, scheduling, venue and referee infrastructure, registration confirmations, and refunds. Team captains — who are themselves players — own their own team's registration, roster, reschedule requests, score submissions, score disputes, and conduct appeals. Referees own the assignments they hold and the authoritative confirmation of a game's score. A conduct officer adjudicates sportsmanship and disciplinary reports. The remainder of this document specifies the global request/response contract, the cross-cutting principles that govern consistency and money, and the detailed business workflows that tie these actors together.

Because the system makes time-sensitive decisions — whether a registration window is open, whether a withdrawal earns a full or partial refund, whether a game may be scored yet — the server maintains a controllable logical clock rather than reading wall-clock time directly. All temporal comparisons described below are evaluated against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `LeagueAdmin`, `TeamCaptain`, `Referee`, and `ConductOfficer`. When a recognized and authenticated caller attempts an operation their role is not permitted to perform — or an operation that requires ownership of the target resource which the caller does not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role, and ownership checks throughout the system depend on this binding:

- When `X-User-Role` is `TeamCaptain`, `X-User-ID` is the `id` of the acting `Player`. Ownership checks on any resource that references a `Player` compare that resource's player-valued foreign key to `X-User-ID`. In particular, a captain owns a team when the team's `captain_player_id` equals `X-User-ID`, and a captain may act on a game only when they own its `home_team_id` or `away_team_id`.
- When `X-User-Role` is `Referee`, `X-User-ID` is the `id` of the acting `Referee`. Ownership checks on any resource that references a `Referee` compare that resource's `referee_id` to `X-User-ID`; in particular, confirming a score is restricted to the referee who holds the game's `HEAD` assignment.
- When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; administrative authority is not ownership-scoped.
- When `X-User-Role` is `ConductOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_RANGE` (HTTP 422).

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp recorded with three fractional digits at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that occur as a side effect of an action on another resource. The `version` field is an integer that starts at 1 when the resource is created and increases by exactly one on every mutation; it is the basis for the optimistic concurrency control described in §2.6.

There is one deliberate exception. A `Payment` is an append-only ledger row: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never mutated. Every other entity — `Season`, `Division`, `Team`, `Player`, `RosterEntry`, `Venue`, `Referee`, `Game`, `RefereeAssignment`, and `ConductReport` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Hierarchical Consistency and Cascading Effects

The data model is a hybrid of a tree and cross-cutting peers. A `Season` owns its `Division` records; a `Division` owns its `Team` and `Game` records; a `Team` owns its `RosterEntry` and `Payment` records; a `Game` owns its `RefereeAssignment` records. Cutting across this tree, a `Game` references two teams and a `Venue`, a `RefereeAssignment` references a `Referee`, and a `ConductReport` references a `Player` and a `Game`. Players relate to teams many-to-many through the `RosterEntry` junction.

A single action frequently mutates more than one resource. Whenever the system writes a derived value onto a resource as a consequence of some other event — recomputing a division's `confirmed_team_count`, a team's `roster_size` or standings, a player's `conduct_points` — that write is a real mutation: it refreshes the affected resource's `updated_at` and increments its `version`. The detailed cascades (auto-promotion of waitlisted teams, release of referee assignments when a game is cancelled, suspension recomputation when conduct is adjudicated) are described in §3 alongside the workflows that trigger them, and each such secondary effect is part of the contract, not an optional optimization.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource, guarding against a client overwriting changes it has not yet observed. These are the only two endpoints that take a version field, and on them the version field is mandatory rather than optional.

Registering a team into a division requires the request body to carry `expected_division_version`, holding the `version` of the target `Division` that the client last read. A prior team registration, or an administrative edit to the division's roster bounds or `team_capacity`, legitimately advances the division's `version` and changes its `confirmed_team_count`. If `expected_division_version` does not equal the division's current `version`, the registration is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the division before it competes for a capacity slot.

Submitting a score against a game requires the request body to carry `expected_game_version`, holding the `version` of the target `Game` that the client last read. Another actor may have already moved the game — a reschedule, a forfeit, or a competing score submission that advanced `score_status`. If `expected_game_version` does not equal the game's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a re-read before the scoreline is overwritten.

No other endpoint accepts or checks a version field.

### 2.7. Nested Resource Retrieval and Validation Ordering

Many paths name more than one resource — a game's referee assignments under a game, a division's games under a division. The system validates the referenced resources left-to-right: the season first, then the division, then the team or game, then any sub-resource. The first identifier in the path (or the body) that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any later identifier is examined and before any business rule is evaluated.

Validation across the whole API follows a fixed priority order so that a single request with several problems fails on a predictable one. The order is: authentication of the headers first (`ERR_UNAUTHENTICATED`); then role and ownership authorization (`ERR_FORBIDDEN`); then existence of every referenced resource (`ERR_NOT_FOUND`); then well-formedness of the request body (`ERR_INVALID_REQUEST`); then the optimistic-concurrency version check on the two endpoints that carry it (`ERR_STALE_VERSION`); then the season-phase gate (`ERR_SEASON_PHASE`); then the target resource's state validity for the requested transition (`ERR_INVALID_STATE`); then player-suspension eligibility (`ERR_PLAYER_SUSPENDED`); then matchup referential integrity (`ERR_INVALID_MATCHUP`); then referee double-booking (`ERR_REFEREE_DOUBLE_BOOKED`); then venue double-booking (`ERR_VENUE_DOUBLE_BOOKED`); then division capacity (`ERR_CAPACITY_EXCEEDED`); then roster rules (`ERR_ROSTER_RULE`); then refund integrity (`ERR_REFUND_EXCEEDS_FEE`); and finally uniqueness (`ERR_DUPLICATE`). When two checks could both fire on one request, the earlier one in this list is the one reported.

Body well-formedness, checked at the `ERR_INVALID_REQUEST` (HTTP 422) tier, covers: all required fields present, every enum value within its declared range, every submitted score being zero or greater, `field_index` falling within the inclusive range from 1 to the hosting venue's `field_count`, and `ends_at` being strictly later than `starts_at`.

### 2.8. Season-Phase Gating

The season's `registration_status` acts as a posture gate over child operations. Several operations are only meaningful in particular phases, and attempting them in the wrong phase is rejected with `ERR_SEASON_PHASE` (HTTP 409). A team may be registered into a division only while its season's `registration_status` is `OPEN`. A game may be scheduled or rescheduled, and a score may be submitted or confirmed, only in the phases described in §3 for each. Advancing a season to `PLAYOFFS` is itself gated on its preconditions. The precise phase that each operation requires is stated alongside that operation's narrative in §3; this subsection establishes that the gate exists and that its violation always surfaces as `ERR_SEASON_PHASE`.

### 2.9. Monetary Precision and the Fee Ledger

All money in the system is tracked in integer cents — there are no fractional cents and no floating-point money. Each `Payment` row is immutable once written and records a `kind` of either `FEE` or `REFUND`, an `amount_cents` (always a positive number of cents — for a refund this is the amount returned to the team), a `status` that is always `CAPTURED` at creation and is never subsequently changed, a `reason` drawn from `REGISTRATION`, `FULL_WITHDRAWAL`, `PARTIAL_WITHDRAWAL`, `NO_REFUND_WITHDRAWAL`, or `ADMIN_ADJUSTMENT`, and a `created_at` that doubles as the chronological ordering key for the ledger. The `team_id` ties the row to its team.

A team's financial position is derived from this ledger, never stored independently. Its `fee_charged_cents` is the sum of `amount_cents` over its `CAPTURED` `FEE` rows, and its `refund_issued_cents` is the sum of `amount_cents` over its `CAPTURED` `REFUND` rows. The governing fiscal invariant is that total refunds for a team can never exceed the captured fee minus refunds already issued; any automatic or administrative refund that would breach this floor-at-zero bound is rejected with `ERR_REFUND_EXCEEDS_FEE` (HTTP 409). Where a partial-refund computation involves a percentage, the system multiplies before it divides and truncates (floors) the resulting cents so that rounding never invents money.

### 2.10. Enumerations and the Logical Clock

Several fields are constrained to fixed enumerations, and implementations must use these exact strings. A `Season` has a `sport` of `SOCCER`, `BASKETBALL`, `SOFTBALL`, or `VOLLEYBALL`, and a `registration_status` progressing through `DRAFT`, `OPEN`, `CLOSED`, `SCHEDULED`, `IN_PLAY`, `PLAYOFFS`, and `COMPLETE`. A `Division` has a `skill_tier` of `REC`, `INTERMEDIATE`, or `COMPETITIVE` and a `standings_tiebreaker` of either `HEAD_TO_HEAD` or `POINT_DIFFERENTIAL`. A `Team` has a `status` among `PENDING`, `CONFIRMED`, `WAITLISTED`, `WITHDRAWN_LOCKED`, `WITHDRAWN`, and `CANCELLED`. A `RosterEntry` has a `state` of `ACTIVE` or `RELEASED`; a `RefereeAssignment` has a `role` of `HEAD`, `ASSISTANT`, or `SCOREKEEPER` and a `state` of `ASSIGNED` or `RELEASED`. A `Game` carries two independent dimensions: a `schedule_status` among `SCHEDULED`, `RESCHEDULE_REQUESTED`, `FORFEITED`, `PLAYED`, and `CANCELLED`, and a `score_status` among `PENDING`, `SUBMITTED`, `CONFIRMED`, and `DISPUTED`, plus a `stage` of `REGULAR` or `PLAYOFF`. A `Player` has a `suspension_status` of `CLEAR`, `WARNED`, `SUSPENDED`, or `BANNED`. A `ConductReport` has a `severity` of `WARNING`, `YELLOW`, `RED`, or `ABUSE`, and a `status` among `FILED`, `UNDER_REVIEW`, `UPHELD`, `DISMISSED`, and `APPEALED`.

Time-sensitive decisions are made against a server-held logical clock, exposed on each season as `clock_now`. The clock is never advanced by the passage of real time; an administrator sets it explicitly through a dedicated test-driving capability that supplies a `to_iso8601` instant, and setting it updates `clock_now` for every season without bumping any `version`. Wherever this document speaks of "now," it means each season's `clock_now`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Season and Its Divisions

A `LeagueAdmin` opens a competition by creating a `Season`, supplying its `name`, its `sport`, the registration window bounds `registration_opens_at` and `registration_closes_at` (the close must be later than the open), and the refund schedule anchors `refund_full_cutoff_at` and an optional `refund_partial_pct`. The partial-refund percentage defaults to 50 when omitted and is an integer percent between 0 and 100. A new season is born in `DRAFT`, its `clock_now` initialized to its creation time, its `version` at 1.

Within a draft season the administrator defines one or more divisions, each created with a `name`, a `skill_tier`, the roster bounds `min_roster_size` (at least 1) and `max_roster_size` (no smaller than `min_roster_size`), a `team_capacity` (at least 2 — the maximum number of teams the division will ever confirm), a `registration_fee_cents` (zero or greater, the per-team fee), and an optional `standings_tiebreaker` that defaults to `HEAD_TO_HEAD`. The owning season is identified by the division's `season_id`. A fresh division starts with a `confirmed_team_count` of 0 and `version` 1.

The season's lifecycle is advanced one step at a time by the administrator naming a `target` phase, accompanied by `expected_season_version` and an optional `force` flag. Moving from `DRAFT` to `OPEN` requires that the season's `clock_now` has reached or passed `registration_opens_at` and that at least one division exists; once `OPEN`, teams may register. Moving from `OPEN` to `CLOSED` requires that `clock_now` has reached or passed `registration_closes_at`, unless the administrator supplies the force flag to close early; closing runs the registration-settlement cascade described in §3.2. Moving from `CLOSED` to `SCHEDULED` requires that every division under the season holds at least 2 `CONFIRMED` teams and that every `REGULAR` game already has `schedule_status` `SCHEDULED` with a venue, a `field_index`, and a `HEAD` referee assigned; once scheduled, games become immutable in venue and time except through the reschedule flow. Moving from `SCHEDULED` to `IN_PLAY` requires that `clock_now` has reached or passed the earliest game's `starts_at` in the season, and as a side effect every team still sitting in `WITHDRAWN_LOCKED` advances to the terminal `WITHDRAWN` so that standings exclude it. Moving from `IN_PLAY` to `PLAYOFFS` requires that every `REGULAR` game in every division has reached a settled result — either `score_status` `CONFIRMED`, or `schedule_status` `FORFEITED`, or `schedule_status` `CANCELLED` — and triggers, per division, a standings recomputation followed by bracket seeding that generates the `PLAYOFF` games. Moving from `PLAYOFFS` to the terminal `COMPLETE` requires that every `PLAYOFF` game has `score_status` `CONFIRMED` or `schedule_status` `FORFEITED`. Each successful transition increments the season's `version` by one. If the season's current phase does not match the requested transition's `from` state, the request fails with `ERR_INVALID_STATE`; if a transition's posture preconditions are not yet met — for instance starting playoffs while regular games are still unsettled — the request fails with `ERR_SEASON_PHASE`. When the blocker is specifically a schedule that is not yet complete enough to advance — a division that lacks its teams or games, or games that still lack confirmed scores when moving toward `SCHEDULED` or `PLAYOFFS` — the request is rejected with `ERR_SCHEDULE_INCOMPLETE` instead.

### 3.2. Team Registration, Confirmation, and the Closing Cascade

A `TeamCaptain` registers their team into a division while the season is `OPEN`, supplying the team's `name`, the `captain_player_id` (which must equal the caller's `X-User-ID`), and `expected_division_version`. The team is created in `PENDING`, the division's `version` is incremented, and the captain is automatically added to the team's roster as an `ACTIVE` `RosterEntry`. The team's `division_id` records which division it joined. A team name must be unique within its division among teams that are not `CANCELLED`; a clashing name is rejected with `ERR_DUPLICATE`. The stale-version handling on this registration is as described in §2.6.

Before a team can be confirmed it must satisfy two conditions and, where the division charges a fee, a third. Its `roster_size` — the count of its `ACTIVE` roster entries — must be at least the division's `min_roster_size`, the division's `confirmed_team_count` must still be below its `team_capacity`, and, when `registration_fee_cents` is greater than zero, a `CAPTURED` `FEE` payment of that amount must already exist for the team. An administrator may confirm a `PENDING` team explicitly, moving it to `CONFIRMED` and incrementing the division's recomputed `confirmed_team_count` by one. A confirm attempt that would push past `team_capacity` is rejected with `ERR_CAPACITY_EXCEEDED`; a confirm attempt with a roster below `min_roster_size` (or one that introduced a duplicate active player) is rejected with `ERR_ROSTER_RULE`; and a confirm of a fee-bearing division's team with no captured fee of the right amount is rejected with `ERR_FEE_REQUIRED`.

When the administrator transitions the season from `OPEN` to `CLOSED`, the system settles every `PENDING` team in one cascade. Teams meeting `min_roster_size` are auto-promoted to `CONFIRMED` in `created_at` ascending order, division by division, until that division's `team_capacity` is reached; once a division is full, its remaining roster-qualified `PENDING` teams become `WAITLISTED`. Any `PENDING` team below `min_roster_size` is moved to the terminal `CANCELLED`, and because such a team may have paid, a full `REFUND` payment is written for it through the withdrawal-refund calculation. Whenever a team is cancelled this way (or withdrawn before any fee was captured), its roster entries are moved to `RELEASED`, and each released player's free-agent status is recomputed.

A `WAITLISTED` team can later be promoted to `CONFIRMED` — either explicitly by an administrator or automatically when a confirmed team withdraws and frees a slot — provided the division's `confirmed_team_count` is still below `team_capacity` and the season's `registration_status` is `CLOSED` or `SCHEDULED`. This promotion also recomputes `confirmed_team_count` upward by one. For the purpose of capacity accounting, a division's `confirmed_team_count` counts teams whose status is `CONFIRMED` or `WITHDRAWN_LOCKED`.

### 3.3. Rosters, Players, and Free-Agency

Players exist independently of teams. Anyone registering a player supplies a `full_name` and an `email`; the email must be globally unique among players that are not `CANCELLED`, and a collision is rejected with `ERR_DUPLICATE`. A new player begins as a free agent with `conduct_points` of 0 and `suspension_status` `CLEAR`. The `is_free_agent` flag is derived: it is true exactly when the player has no `ACTIVE` roster entries, and it is recomputed whenever a roster entry is created or released.

A captain (or an administrator acting on the team) adds a player to a roster by supplying the `player_id`; this creates a `RosterEntry` in `ACTIVE` state for the team identified by `team_id`, then recomputes the player's `is_free_agent` and the team's `roster_size`. The entry's `is_captain` flag is true exactly when its `player_id` equals the team's `captain_player_id`. A player already holding an `ACTIVE` entry on the same team cannot be added a second time — the duplicate is rejected with `ERR_ROSTER_RULE` — and an add that would carry the team's `ACTIVE` count beyond `max_roster_size` is rejected with `ERR_CAPACITY_EXCEEDED`. Releasing a player — naming the target entry by its `roster_entry_id` in the path — moves that entry from `ACTIVE` to `RELEASED` and again recomputes the player's `is_free_agent` and the team's `roster_size`. A player who is currently `SUSPENDED` or `BANNED` may not be added to any roster, and may not be cited as participating in a game; such an attempt is rejected with `ERR_PLAYER_SUSPENDED`. Suspension eligibility is keyed to the game round, as detailed in §3.8.

### 3.4. Withdrawing a Team and Computing the Refund

Withdrawal behaves differently depending on how far the team has progressed. A `PENDING` or `WAITLISTED` team that has never had a fee captured is simply cancelled: it moves to the terminal `CANCELLED`, its roster entries move to `RELEASED`, and each affected player's free-agent status is recomputed. This path is only available while no `CAPTURED` `FEE` payment exists for the team.

A `CONFIRMED` team withdraws into `WITHDRAWN_LOCKED`, and only while the season's `registration_status` is `CLOSED` or `SCHEDULED` and no game involving the team has yet reached a confirmed score. This withdrawal fires several effects at once: the refund calculation runs and writes a `REFUND` payment for the prorated amount; the division's `confirmed_team_count` is recomputed downward by one; every still-`SCHEDULED` game involving the team moves to `CANCELLED`, and each such cancelled game releases its referee assignments to `RELEASED`; and the highest-seeded `WAITLISTED` team in the same division (breaking ties by `created_at` ascending) is auto-promoted to `CONFIRMED`. A team sitting in `WITHDRAWN_LOCKED` is later moved to the terminal `WITHDRAWN` when the season reaches `IN_PLAY`, at which point standings exclude it. An attempt to withdraw a team whose state does not permit it is rejected with `ERR_INVALID_STATE`.

The refund amount follows a three-way rule, and the two readings of "before the first game" are pinned to the earlier of them. Begin from the refundable base, which is the team's captured fee total minus refunds already issued to it. If the season's `clock_now` is at or before the season's `refund_full_cutoff_at`, the entire refundable base is returned and the payment's `reason` is `FULL_WITHDRAWAL`. Otherwise, if no game involving the team has `schedule_status` `PLAYED` or `score_status` `CONFIRMED`, the refund is the refundable base multiplied by the season's `refund_partial_pct` and then divided by 100, with the cents truncated downward (multiply before dividing), and the `reason` is `PARTIAL_WITHDRAWAL`. Otherwise — the team already has a played or confirmed-score game — the refund is zero and the `reason` is `NO_REFUND_WITHDRAWAL`. A `REFUND` payment row is written whenever the computed refund is greater than zero; in the no-refund case an audit row of `amount_cents` 0 with `reason` `NO_REFUND_WITHDRAWAL` is still written. In every case the refund integrity bound of §2.9 holds, and a refund that would breach it is rejected with `ERR_REFUND_EXCEEDS_FEE`.

Captains and administrators capture the registration fee by writing a `FEE` payment with a supplied `amount_cents`; the row is recorded with `status` `CAPTURED` and `reason` `REGISTRATION`, after which the team's `fee_charged_cents` is recomputed. Separately, an administrator may post a manual refund by supplying an `amount_cents`; this writes a `REFUND` payment with `reason` `ADMIN_ADJUSTMENT`, but only when it stays within the captured-fee-minus-prior-refunds bound, recomputing the team's `refund_issued_cents`. A manual refund beyond the bound is likewise rejected with `ERR_REFUND_EXCEEDS_FEE`.

### 3.5. Venues, Referees, and Building the Schedule

Two pieces of infrastructure underpin scheduling. A `Venue` is created with a `name`, a `field_count` (at least 1, the number of independently bookable fields or courts), and an optional `turnover_buffer_minutes` (defaulting to 30) — the minimum gap that must separate two games on the same field. A `Referee` is created with a `full_name` and a `certified_sports` array naming the sports they may officiate.

An administrator schedules a game inside a division by naming the two teams `home_team_id` and `away_team_id`, the `venue_id` and the `field_index` at that venue, the `round_index` (a one-based season round number that is at least 1 and also serves as the suspension comparison index), the kickoff `starts_at` and scheduled end `ends_at` (the end strictly after the start), and an optional `stage` defaulting to `REGULAR`. The game's `division_id` records its division. A new game is born with `schedule_status` `SCHEDULED` and `score_status` `PENDING`; its `home_score` and `away_score` are null until a score is submitted, and its `forfeiting_team_id` is null until a forfeit charges one of the two teams. The two teams must differ, must both be `CONFIRMED`, and must belong to the same division as the game — a violation of any of these is rejected with `ERR_INVALID_MATCHUP`.

Scheduling enforces venue exclusivity with a turnover buffer. Two games on the same `venue_id` and `field_index` conflict when their time intervals, each lengthened at its end by the venue's `turnover_buffer_minutes`, intersect: treating an existing game as occupying from its `starts_at` until its `ends_at` plus the buffer, a new game from its own start to its own end plus the buffer conflicts when the new start falls before the existing buffered end and the existing start falls before the new buffered end. Because the buffer must physically separate the games, two games that merely abut — the new one starting exactly when the prior one ends — do conflict whenever the buffer is greater than zero. Different `field_index` values at the same venue never conflict with one another. Only games whose `schedule_status` is `SCHEDULED` or `RESCHEDULE_REQUESTED` participate in this check, and the game being edited is excluded from its own comparison. A venue conflict is rejected with `ERR_VENUE_DOUBLE_BOOKED`.

An administrator staffs a game by assigning a referee, supplying the `referee_id` and an optional `role` (defaulting to `HEAD`); the assignment is created in `ASSIGNED` state and references its game through `game_id`. A referee cannot hold two `ASSIGNED` assignments whose games' half-open time intervals — from `starts_at` up to but not including `ends_at` — overlap. Two such intervals conflict when the first starts strictly before the second ends and the second starts strictly before the first ends; back-to-back games that share only the boundary instant (one ending exactly as the next begins) do not conflict for a referee, because no turnover buffer applies to an official moving between games. The referee's own game under edit is excluded from the comparison. A referee conflict is rejected with `ERR_REFEREE_DOUBLE_BOOKED`. An administrator may also release an assignment — naming the target by its `assignment_id` in the path — moving it from `ASSIGNED` to `RELEASED`.

### 3.6. The Reschedule Flow

A captain whose team is involved in a game may request that it be moved, provided the season's `registration_status` is `SCHEDULED` or `IN_PLAY`, the game's `score_status` is still `PENDING`, and the requesting captain owns the game's `home_team_id` or `away_team_id`. The request advances the game's `schedule_status` from `SCHEDULED` to `RESCHEDULE_REQUESTED`; no other field changes, and no make-up row is created.

An administrator approves the make-up by supplying a new `venue_id`, `field_index`, `starts_at`, and `ends_at`. Approval moves the same game row from `RESCHEDULE_REQUESTED` back to `SCHEDULED` and updates its `venue_id`, `field_index`, `starts_at`, and `ends_at` to the new slot — the game moves; it is not duplicated. Approval re-runs both overlap checks against the new slot: the venue buffered-interval check and the referee half-open-interval check for every assignment the game retains, with the game itself excluded from each. The new `starts_at` must also lie in the future relative to the season's `clock_now`. A venue collision at the new slot is rejected with `ERR_VENUE_DOUBLE_BOOKED`, a referee collision with `ERR_REFEREE_DOUBLE_BOOKED`, and an attempt to reschedule a game that is not in `RESCHEDULE_REQUESTED` with `ERR_INVALID_STATE`.

### 3.7. Scoring, Confirmation, Disputes, and Forfeits

Scoring is the game's second, independent dimension, evolving in `score_status` while `schedule_status` follows its own track. A captain of a participating team or a referee submits a score by supplying `home_score`, `away_score`, and `expected_game_version`. Submission is permitted only when the game's `schedule_status` is `SCHEDULED`, the season's `clock_now` has reached or passed the game's `starts_at`, and both scores are zero or greater. A successful submission records `home_score` and `away_score`, advances `score_status` from `PENDING` to `SUBMITTED`, and increments the game's `version` by one; the stale-version handling is as described in §2.6. A submission against a game in the wrong state is rejected with `ERR_INVALID_STATE`.

The assigned head referee confirms a submitted score, which requires that a `HEAD` referee assignment in `ASSIGNED` state exists for the game and that the acting referee is that assignment's referee. Confirmation advances `score_status` from `SUBMITTED` to `CONFIRMED` and, as a cross-dimension cascade, flips the game's `schedule_status` to the terminal `PLAYED`, releases the game's referee assignments to `RELEASED`, and recomputes standings for both teams. A losing captain — the captain of whichever team trails under the submitted scoreline — may instead dispute a `SUBMITTED` score, moving `score_status` to `DISPUTED`. From `DISPUTED`, the head referee re-submits a corrected score (the same action and preconditions as the original submission), overwriting `home_score` and `away_score` and returning the game to `SUBMITTED`.

A game may be forfeited from `SCHEDULED` by an administrator or by a captain, supplying the `forfeiting_team_id`, which must be either the `home_team_id` or the `away_team_id`; otherwise the request is rejected with `ERR_INVALID_MATCHUP`. Forfeit is permitted only while the game's `score_status` is `PENDING` or `SUBMITTED`. The forfeit moves `schedule_status` to the terminal `FORFEITED` and `score_status` to `CONFIRMED` in one step, records the charged team in `forfeiting_team_id` (discoverable by filtering the games list on that field), credits the non-forfeiting team with a forfeit win and the forfeiting team with a loss, recomputes standings for both teams, and releases the game's referee assignments to `RELEASED`. A game may also be moved to the terminal `CANCELLED` by the system when a participating team withdraws or the schedule is rebuilt; cancellation likewise releases the game's referee assignments to `RELEASED`.

### 3.8. Standings, Tiebreakers, and Playoff Seeding

Standings are computed for each team over the games that count: regular-stage games in the team's division that have reached a settled result, meaning `score_status` `CONFIRMED` or `schedule_status` `FORFEITED`. Games still `PENDING`, `SUBMITTED`, or `DISPUTED`, and any `CANCELLED` game, are excluded. Over that set, a team's `wins` is the number of games in which its own score exceeded its opponent's, its `losses` the number in which its score was lower, and its `draws` the number in which the scores were level (a forfeit never produces a draw). Its `points_for` is the sum of its own scores across those games and its `points_against` the sum of opponents' scores. League `points` are three for each win, one for each draw, and zero for each loss. A forfeited game contributes a win to the non-forfeiting team scored as three to nothing and a loss to the forfeiting team. Standings recompute whenever a score is confirmed, a game is forfeited, or a confirmed team is locked into withdrawal.

When the season enters `PLAYOFFS`, each division ranks its `CONFIRMED` teams to assign seeds. The primary key in every case is `points`, highest first. The remaining tiebreak chain depends on the division's `standings_tiebreaker`. Under `HEAD_TO_HEAD`, ties are broken in this order: by `points`, then by head-to-head points (the league points each tied team earned only in regular games played strictly among the tied teams), then by goal difference (`points_for` minus `points_against`), then by `points_for`, and finally by `created_at` earliest-first. Under `POINT_DIFFERENTIAL`, the chain is: by `points`, then by goal difference (`points_for` minus `points_against`), then by `points_for`, then by head-to-head points, and finally by `created_at` earliest-first. In both chains `created_at` ascending is the final deterministic tie-break and the `id` is never used for ordering. A team's seed is its one-based position in this sorted order, and the first playoff round pairs seed N against the seed at position (count plus one minus N).

### 3.9. Conduct Reports, Discipline, and Suspensions

A referee, administrator, or conduct officer files a conduct report against a player by supplying the `game_id` of the game in which the incident occurred, the cited `player_id`, and a `severity`. The report opens in `FILED` with `points` of 0. A conduct officer reviews it into `UNDER_REVIEW`, then either upholds it or dismisses it. Upholding (`UNDER_REVIEW` to `UPHELD`) sets the report's `points` to the base value for its severity and recomputes the cited player's `conduct_points` and suspension. Dismissing from review (`UNDER_REVIEW` to `DISMISSED`, a terminal state) leaves the report's `points` at 0 and the player's `conduct_points` untouched.

After a report is upheld, the captain of a team that rosters the cited player — verified by an `ACTIVE` roster entry on a team that captain captains — may appeal it, moving it from `UPHELD` to `APPEALED`. An appealed report keeps counting: its `points` and the player's `conduct_points` are unchanged while appealed, so an appeal does not by itself lift a suspension. A conduct officer resolves an appeal either by denying it — `APPEALED` back to `UPHELD`, with the player's `conduct_points` and suspension unchanged because the points were already counted — or by granting it — `APPEALED` to the terminal `DISMISSED`, which resets the report's `points` to 0, recomputes the player's `conduct_points` downward, and re-evaluates suspension, which may lift it. A transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

A player's `conduct_points` is the sum, across all reports cited against them whose `status` is `UPHELD` or `APPEALED`, of the base value for each report's severity. The base values are one point for `WARNING`, two for `YELLOW`, four for `RED`, and eight for `ABUSE`. Suspension is then derived from `conduct_points` by instantaneous threshold, each comparison being "at or above": at 12 or more points the player is `BANNED` and their `suspended_until_game_index` is set to 9999; otherwise at 6 or more points the player is `SUSPENDED` and their `suspended_until_game_index` is set to the larger of its current value and the triggering game's `round_index` plus 2 (the two-game suspension span); otherwise at 3 or more points the player is `WARNED` with `suspended_until_game_index` left unchanged; otherwise the player is `CLEAR` with `suspended_until_game_index` reset to 0. The triggering game is the game referenced by the report whose upholding crossed the threshold. A player is ineligible for any game whose `round_index` is less than or equal to their `suspended_until_game_index`; a `suspended_until_game_index` of 0 means not suspended. These eligibility gates are what the `ERR_PLAYER_SUSPENDED` rejection in §3.3 enforces.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, score submissions, withdrawals, and releases — return `200 OK`. List and retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/seasons` | Create a season (DRAFT) | LeagueAdmin |
| GET    | `/seasons/{id}` | Get a season | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| POST   | `/seasons/{id}/transition` | Advance the season lifecycle; `target` selects the transition (OCC on season version) | LeagueAdmin |
| POST   | `/seasons/{id}/divisions` | Create a division under a season | LeagueAdmin |
| GET    | `/seasons/{id}/divisions` | List divisions under a season | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/divisions/{id}` | Get a division | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/divisions/{id}/standings` | Computed standings (ordered seed list) for the division | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| POST   | `/divisions/{id}/games` | Schedule a game in a division (venue overlap checked) | LeagueAdmin |
| GET    | `/divisions/{id}/games` | List games in a division | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| POST   | `/divisions/{id}/teams` | Register a team into a division (OCC on division version) | TeamCaptain |
| GET    | `/divisions/{id}/teams` | List teams in a division | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/teams/{id}` | Get a team | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/teams` | List teams filtered by captain | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| POST   | `/teams/{id}/pay-fee` | Capture the registration fee for a team | TeamCaptain, LeagueAdmin |
| POST   | `/teams/{id}/confirm` | Confirm a PENDING or WAITLISTED team | LeagueAdmin |
| POST   | `/teams/{id}/withdraw` | Withdraw a team; refund and cascades depend on status/phase | TeamCaptain, LeagueAdmin |
| POST   | `/teams/{id}/refund-adjustment` | Admin manual refund row (bounded by captured fee minus prior refunds) | LeagueAdmin |
| GET    | `/teams/{id}/payments` | Ledger rows for a team | LeagueAdmin, TeamCaptain |
| POST   | `/teams/{id}/roster` | Add a player to a team roster | TeamCaptain, LeagueAdmin |
| GET    | `/teams/{id}/roster` | List roster entries for a team | LeagueAdmin, TeamCaptain, Referee |
| DELETE | `/teams/{id}/roster/{roster_entry_id}` | Release a player from a roster | TeamCaptain, LeagueAdmin |
| POST   | `/players` | Register a player (free agent by default) | LeagueAdmin, TeamCaptain |
| GET    | `/players/{id}` | Get a player | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/players/{id}/roster-entries` | List roster entries for a player | LeagueAdmin, TeamCaptain, Referee |
| POST   | `/venues` | Create a venue | LeagueAdmin |
| GET    | `/venues/{id}` | Get a venue | LeagueAdmin, TeamCaptain, Referee |
| POST   | `/referees` | Create a referee | LeagueAdmin |
| GET    | `/referees/{id}` | Get a referee | LeagueAdmin, Referee |
| GET    | `/referees/{id}/assignments` | List a referee's assignments | LeagueAdmin, Referee |
| GET    | `/games/{id}` | Get a game | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| GET    | `/games` | List games filtered by team/venue/forfeiting team | LeagueAdmin, TeamCaptain, Referee, ConductOfficer |
| POST   | `/games/{id}/request-reschedule` | Request a reschedule (SCHEDULED → RESCHEDULE_REQUESTED) | TeamCaptain |
| POST   | `/games/{id}/reschedule` | Approve a reschedule to a new slot | LeagueAdmin |
| POST   | `/games/{id}/forfeit` | Forfeit a game; awards forfeit win, recomputes standings | LeagueAdmin, TeamCaptain |
| POST   | `/games/{id}/submit-score` | Record a score (OCC on game version) | TeamCaptain, Referee |
| POST   | `/games/{id}/confirm-score` | Confirm a submitted score; flips schedule to PLAYED | Referee |
| POST   | `/games/{id}/dispute-score` | Dispute a submitted score (losing captain) | TeamCaptain |
| POST   | `/games/{id}/referee-assignments` | Assign a referee to a game (referee overlap checked) | LeagueAdmin |
| GET    | `/games/{id}/referee-assignments` | List a game's assignments | LeagueAdmin, Referee |
| DELETE | `/games/{id}/referee-assignments/{assignment_id}` | Release a referee assignment | LeagueAdmin |
| POST   | `/conduct-reports` | File a conduct report against a player in a game | Referee, LeagueAdmin, ConductOfficer |
| GET    | `/conduct-reports/{id}` | Get a conduct report | LeagueAdmin, ConductOfficer, TeamCaptain, Referee |
| GET    | `/conduct-reports` | List conduct reports filtered by player or game | LeagueAdmin, ConductOfficer, Referee |
| POST   | `/conduct-reports/{id}/transition` | Adjudicate a report; `target` selects the transition | ConductOfficer, TeamCaptain |
| POST   | `/_clock/set_current_utc` | Set the server clock for window/refund/eligibility decisions | LeagueAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEASON_PHASE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAYER_SUSPENDED` | 409 |
| `ERR_INVALID_MATCHUP` | 409 |
| `ERR_REFEREE_DOUBLE_BOOKED` | 409 |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROSTER_RULE` | 409 |
| `ERR_REFUND_EXCEEDS_FEE` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_FEE_REQUIRED` | 409 |
| `ERR_SCHEDULE_INCOMPLETE` | 409 |
| `ERR_PAGINATION_RANGE` | 422 |
