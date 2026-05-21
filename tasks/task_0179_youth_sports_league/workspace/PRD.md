# Youth Sports League API — Product Requirements Document

## 1. Introduction

The Youth Sports League platform supports the end-to-end operation of a community Little League: from the moment a parent submits a birth certificate to register a child, through tryouts and a snake-draft, into the regular season's weekly games and rainout makeups, finally to a single-elimination playoff bracket and the crowning of a season champion. League volunteers — predominantly parents — log the hours that keep the league running, and league administrators stitch all of these threads together while balancing youth-safety obligations such as coach background checks and age cut-offs.

This document specifies the API for that platform. It is written for engineers building the server, and it favours business-domain language over implementation detail. The document is organised as global cross-cutting principles first (Section 2), then narrative business workflows (Section 3), then a flat reference of HTTP endpoints (Section 4) and error codes (Section 5). Sections 2 and 3 carry the rules; sections 4 and 5 are summary tables.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (with the narrow exception of the test-driving clock endpoint and any future health probe) must carry two headers that together identify the caller: `X-User-ID` and `X-User-Role`. A request missing either header is rejected with `ERR_AUTH_REQUIRED` and HTTP 401. A request whose role lacks permission for the endpoint, or whose `X-User-ID` does not resolve to the expected entity for an entity-backed role, is rejected with `ERR_FORBIDDEN` and HTTP 403.

There are exactly four roles:

- **`LeagueAdmin`** — League operations staff. When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, in an `AuditEvent.actor_id` row) but does not compare it to any entity's `id`.
- **`Coach`** — Head coach of a team. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; ownership checks on any resource that references a `Coach` (for example, drafting onto a `Team`) compare the resource's `head_coach_id` to `X-User-ID`.
- **`Referee`** — A registered referee. When `X-User-Role` is `Referee`, `X-User-ID` is the `id` of the acting `Referee`; visibility filters on games compare each `Game`'s `referee_id` to `X-User-ID`.
- **`Guardian`** — A parent or legal guardian. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; ownership checks on a `Player` compare the player's `guardian_id` to `X-User-ID`, and ownership checks on a `VolunteerShift` compare the shift's `guardian_id` to `X-User-ID`.

For entity-backed roles, if `X-User-ID` does not resolve to an existing record of the matching entity type, the request is rejected with `ERR_FORBIDDEN`. A `Guardian` attempting to withdraw a player or cancel a shift that belongs to a different guardian is rejected with `ERR_NOT_OWNER`. A `Coach` attempting to draft onto a team whose `head_coach_id` is some other coach is rejected with `ERR_NOT_TEAM_OWNER`.

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

List endpoints accept two query parameters that control paging: `limit` and `offset`. The default `limit` is 10, with a minimum of 1 and a maximum of 100; the default `offset` is 0. Results are returned sorted by `created_at` in ascending order. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` block, where `total_count` reports the size of the unpaged result set and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix. Most resources also carry the audit trio `created_at`, `updated_at`, and `version`, where the two timestamps are ISO 8601 UTC strings with three fractional digits and `version` is an integer that starts at 1 on creation and is incremented by exactly one on every mutation. `created_at` is fixed at creation; `updated_at` is refreshed every time a mutation lands. The audit-trail records of the league — the `AuditEvent` rows — are an exception: they carry only `id` and `created_at`, with no `updated_at` and no `version`, because they are append-only and never re-edited.

Several endpoints accept an optional `version` field in the request body. When a client supplies it, the server compares the supplied integer to the current `version` of the target row: a match allows the mutation to proceed and the `version` is incremented in the same transaction; a mismatch causes the request to be rejected with `ERR_VERSION_CONFLICT` and HTTP 409 without any side effect being applied. If a client omits `version`, no concurrency check is performed and the latest version simply wins.

### 2.5. Nested Resource Path Validation

Endpoint paths frequently nest one resource under another (for example, transitions hanging off a season or a game). Path parameters are resolved strictly left to right: the outermost identifier is validated first, then each inner identifier in turn. A missing `Season` surfaces as `ERR_SEASON_NOT_FOUND`, a missing `Team` as `ERR_TEAM_NOT_FOUND`, a missing `Player` as `ERR_PLAYER_NOT_FOUND`, a missing `Game` as `ERR_GAME_NOT_FOUND`, and a missing `VolunteerShift` as `ERR_SHIFT_NOT_FOUND`, each returning HTTP 404. Body-supplied foreign keys — `guardian_id`, `head_coach_id`, `home_team_id`, `away_team_id`, `referee_id`, `forfeiting_team_id`, and so on — are checked after path validation and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404) when they do not resolve.

### 2.6. Validation Priority

When multiple validation failures could apply to a single request, the server evaluates checks in a fixed priority order, returning the first applicable failure rather than the most "interesting" one. Authentication is checked first (header presence, then RBAC, then entity-backed identity resolution), then existence (path-referenced entities left to right, then body-referenced foreign keys). Next come state-precondition checks: the generic source-state check (`ERR_INVALID_STATE`), the season-window check (`ERR_SEASON_NOT_DRAFT_OPEN`) where draft-era operations require a `DRAFT_OPEN` season, and the player-state check (`ERR_INVALID_PLAYER_STATE`) for player-targeted transitions. After state come the youth-safety gates — birth-certificate presence, age eligibility, and coach background checks. Temporal/scheduling checks (rainout window, field overlap, referee overlap and weekly cap, regular-season window, check-in window) follow. Quota and constraint checks (snake-draft seat, tier-A cap, uniqueness, ownership, opponent inequality) follow those. Cross-record referential rules (referee required for results, score validity, regular-season completeness, season-readiness for opening regular season) come last among business rules, and finally optimistic-concurrency mismatches (`ERR_VERSION_CONFLICT`) are evaluated. The practical consequence is that an `ERR_AUTH_REQUIRED` will always mask any other defect in the payload, and an existence failure will mask any state, safety, or temporal failure.

### 2.7. The Rainout Window and Field Booking Principle

A scheduled game owns a half-open slot on a field — written `[scheduled_start, scheduled_end)` and always exactly 90 minutes long, because `scheduled_end` is fixed as `scheduled_start` plus 90 minutes regardless of how `scheduled_start` is changed. Two slots on the same `field_id` are considered to collide if and only if one's start is strictly earlier than the other's end and vice versa; slots that exactly touch at the boundary — for example, `[10:00, 11:30)` followed by `[11:30, 13:00)` — do not collide and are both permitted. Postponing a game frees its slot immediately, and a cancelled game likewise no longer holds its slot, so the overlap check considers only games whose `status` is in the set { `SCHEDULED`, `COMPLETED`, `FORFEITED` } on the same field. A collision surfaces as `ERR_FIELD_OVERLAP`.

The rainout window itself is the calendar-day window inside which a postponed game must be re-slotted. Each season carries a `rainout_window_days` value (default 14, accepted in the range 1 through 60 inclusive, two decimals not relevant because it is an integer) and a reschedule's new `scheduled_start` must be strictly later than the game's `original_scheduled_start` and at the same time no later than `original_scheduled_start` plus `rainout_window_days` days. A reschedule beyond that boundary is rejected with `ERR_RAINOUT_WINDOW_EXCEEDED`. A game that has remained `POSTPONED` for longer than the rainout window — that is, the current logical clock is strictly later than `original_scheduled_start` plus `rainout_window_days` days — becomes eligible to be cancelled.

### 2.8. Referee Booking, Buffers, and the Weekly Cap

A referee may not be assigned to two games whose 90-minute slots overlap once a 30-minute buffer is added on either side of any existing assignment. Concretely, a candidate slot `[new_start, new_end)` collides with an existing assignment `[a, b)` (in `SCHEDULED` or `COMPLETED` status; `CANCELLED` assignments do not count) when `new_start` is strictly earlier than `b + 30 minutes` and at the same time `a − 30 minutes` is strictly earlier than `new_end`. A collision surfaces as `ERR_REFEREE_OVERLAP`. Each referee also carries a `weekly_assignment_cap` (default 5, allowed range 1 to 20 inclusive) measured per ISO week — Monday 00:00:00.000 UTC through the following Sunday 23:59:59.999 UTC. The count is taken across all of that referee's games in the same ISO week excluding `CANCELLED` games and excluding the game being edited; if assigning would push the count above the cap, the request is rejected with `ERR_REFEREE_WEEKLY_CAP_EXCEEDED`. A referee may decline new work entirely by setting `active` to false on their record.

### 2.9. Volunteer Crediting Principle

The league treats family volunteer participation as a season-wide accounting principle: each registered family is asked to contribute a configurable number of hours per season, captured on the owning season as `volunteer_hours_required_per_family` (default 6.0, range 0 to 100 inclusive, two decimals). A guardian's `volunteer_hours_logged` is the sum of `hours_credited` across that guardian's `APPROVED` `VolunteerShift` rows in the active season — where the active season is the most recent season whose `status` is not `CLOSED`. Shifts in `SCHEDULED`, `CHECKED_IN`, `NO_SHOW`, or `CANCELLED` contribute zero. The sum is computed at full precision and only the final total is rounded to two decimal places using half-up; rounding each row before summing would yield different totals when individual shifts cover sub-cent fractional hours, and that order matters. A guardian's `volunteer_status` is then derived from the comparison: when `volunteer_hours_logged` is at least `volunteer_hours_required_per_family`, the status is `FULFILLED`; otherwise, when `volunteer_hours_logged` is at least half of `volunteer_hours_required_per_family` (the half-of-required boundary is computed at full precision and compared with the at-least operator, so a guardian sitting exactly at half the required hours is `ON_TRACK`, not `DEFICIENT`), the status is `ON_TRACK`; otherwise the status is `DEFICIENT`.

### 2.10. Precision, Rounding, and Time

All datetimes are ISO 8601 UTC strings with three fractional digits, and the league treats all schedules as living in UTC; the `regular_season_start` value anchors at 00:00:00.000 of its calendar day and `regular_season_end` at 23:59:59.999 of its calendar day. Monetary or fractional-hour quantities are stored to two decimal places and any rounding uses the half-up rule. The tier-classification thresholds are interpreted with the at-least operator at the boundary points (so a score of exactly 85.0 is `TIER_A`, exactly 70.0 is `TIER_B`, exactly 50.0 is `TIER_C`). Win percentage during playoff seeding is rounded to four decimal places using half-up before any comparison.

Because much of the league's logic is time-gated, an administrator-only test-driving capability is provided that advances the logical clock to a supplied `to` instant; subsequent reads of "now" return that instant and time-gated transitions (recording a result, marking a no-show, approving a shift, opening the playoffs, cancelling a postponed game) become reachable. The clock endpoint is the only endpoint exempt from the standard `X-User-ID`/`X-User-Role` requirement in addition to a future health probe.

## 3. Business Logic & Workflows

### 3.1. The Season as a Container

Every league activity happens inside a `Season`. A `LeagueAdmin` creates a season with a human-readable `name` (1 to 120 characters, unique within the league), an `age_division` drawn from the set { `TBALL`, `MINORS`, `MAJORS`, `INTERMEDIATE`, `JUNIORS` }, and a four-field calendar: `min_birth_date` and `max_birth_date` define the age window for eligible players (inclusive on both ends), while `regular_season_start` and `regular_season_end` bound the calendar for regular-season scheduling. A `playoff_cutoff_date` is also captured at creation; it serves as the anchor the playoff sweep consults when deciding whether playoffs may begin and as the default scheduling anchor for the first round of the bracket. Optional inputs at creation are `rainout_window_days` and `volunteer_hours_required_per_family`, which default to 14 and 6.0 respectively.

A fresh season is born in `DRAFT_OPEN`. Three explicit lifecycle transitions, each performed by a `LeagueAdmin`, drive it through the rest of its life: opening the regular season advances `status` from `DRAFT_OPEN` to `REGULAR_SEASON`; opening the playoffs advances from `REGULAR_SEASON` to `PLAYOFFS`; closing the season advances from `PLAYOFFS` to `CLOSED`, the terminal state. Each transition refreshes `updated_at` and increments `version` on the season row.

Opening the regular season requires three preconditions: at least 4 teams must exist in the season, every one of those teams must have a `roster_count` of at least 8, and every player who is not `WITHDRAWN` must already be `DRAFTED`. The first two preconditions, in combination, surface as `ERR_SEASON_NOT_READY` when the league is too thin to play. The transition itself flips `status` to `REGULAR_SEASON` and, as part of the same transaction, auto-withdraws any player still sitting in `EVALUATED` (i.e., who completed evaluation but never got picked) — those players' `status` is moved to `WITHDRAWN` and an `AuditEvent` is recorded with `action` equal to `PLAYER_AUTO_WITHDRAWN`.

Opening the playoffs requires that the current logical clock is at or beyond the season's `playoff_cutoff_date` (use the clock-advance capability to drive that condition in tests) and that every regular-season game has reached a terminal status — that is, every regular-season `Game` has `status` in { `COMPLETED`, `FORFEITED`, `CANCELLED` }. If any regular game is still `SCHEDULED`, `POSTPONED`, or `RESCHEDULED`, the request fails with `ERR_REGULAR_SEASON_INCOMPLETE`. The transition triggers the playoff seeding sweep (Section 3.6) and the generation of the first-round bracket games.

Closing the season requires that exactly one team in the season has `playoff_status` equal to `CHAMPION` and every other team has `playoff_status` equal to `ELIMINATED`. The transition merely flips `status` to `CLOSED`; once closed, the season is the league's permanent record of that year.

### 3.2. Guardians, Players, and Age Verification

A `Guardian` is the league's contact for one or more registered players. The guardian is registered with `full_name` (1 to 160 characters), `email` (a valid address, unique across the league), and `phone` formatted as an E.164 number. Two derived fields hang off the guardian and refresh automatically as shifts are approved or cancelled: `volunteer_hours_logged` (cumulative approved hours, two decimals) and `volunteer_status` (one of `DEFICIENT`, `ON_TRACK`, `FULFILLED`, defaulting to `DEFICIENT`). A guardian may either self-register or be registered by a `LeagueAdmin`.

A `Player` is created with a `season_id` (the season they are registering for), the player's own `first_name` and `last_name` (each 1 to 80 characters), `birth_date` (date-only semantics at midnight UTC), `guardian_id` (the responsible guardian), and, optionally at creation, the `birth_certificate_uri` that will later be required to verify age. A newly registered player begins in `PENDING_VERIFICATION`.

Age verification — driven by a `LeagueAdmin` — moves the player from `PENDING_VERIFICATION` to `AGE_VERIFIED`. The verification accepts an optional `birth_certificate_uri` in the body, which is used when the player was registered without one; if neither the request nor the player's stored value provides a non-null URI, the request fails with `ERR_BIRTH_CERT_REQUIRED`. The player's `birth_date` must also fall inside the season's birth-date window — at or after `min_birth_date` and at or before `max_birth_date`, with both boundary dates eligible — and a player outside the window is rejected with `ERR_AGE_INELIGIBLE`. The verification is only valid while the season is in `DRAFT_OPEN`; an attempt after that surfaces as `ERR_SEASON_NOT_DRAFT_OPEN`.

A `LeagueAdmin` next records the tryout result, advancing the player from `AGE_VERIFIED` to `EVALUATED`. The body supplies `evaluation_score`, a one-decimal number between 0 and 100 inclusive. The transition stores the score on the player and computes `evaluation_tier` from it: a score of at least 85.0 yields `TIER_A`; otherwise a score of at least 70.0 yields `TIER_B`; otherwise a score of at least 50.0 yields `TIER_C`; anything below is `TIER_D`. Tier is null while the player is still `UNEVALUATED` in the colloquial sense (i.e., before reaching `EVALUATED`). Evaluation, like verification, requires the season to still be in `DRAFT_OPEN`.

A guardian may withdraw their own player while the player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or `EVALUATED`; the transition moves the player's `status` to `WITHDRAWN`, which is terminal. Withdrawal of a `DRAFTED` player is not permitted through this transition: the precondition requires the player's `status` to be different from `DRAFTED`, and an attempt is rejected with `ERR_INVALID_PLAYER_STATE`. A `LeagueAdmin` can also drive a withdrawal via the same operation; in either case, only the responsible guardian (matching `guardian_id`) — or an admin — may execute it, with a non-matching guardian receiving `ERR_NOT_OWNER`.

### 3.3. Teams, Coaches, and the Snake Draft

A `Coach` is registered with `full_name`, `email` (unique across the league), and the boolean `background_check_passed` (default false). The background check is more than bookkeeping: a coach cannot be assigned as head coach of any team unless their `background_check_passed` is true at the moment of team creation or head-coach reassignment, and any attempt with a coach lacking it is rejected with `ERR_COACH_NO_BACKGROUND_CHECK`.

A `Team` is created by a `LeagueAdmin` inside a season with a `name` (1 to 80 characters, unique within the season's teams), a `head_coach_id`, and a `draft_position` — a snake-draft seat number from 1 to 32 inclusive, also unique within the season. Duplicate names or duplicate draft positions in the same season surface as `ERR_TEAM_DUPLICATE`. Several derived fields hang off the team and update as players are drafted and games are played: `roster_count` is the count of `DRAFTED` players whose `team_id` points to this team; `tier_a_count` is the same count further filtered to `evaluation_tier` equal to `TIER_A`; `wins` and `losses` track the team's record (Section 3.5); and `playoff_seed` and `playoff_status` capture the bracket position once playoffs open.

Once teams and players exist, the draft proceeds as a snake draft, run by the head `Coach` of each team — or, when an override is required, by a `LeagueAdmin`. Whose turn it is at any moment is resolved arithmetically rather than by an explicit pointer. With N teams in the season and `picks_so_far` equal to the count of players in this season already in `DRAFTED` status, the zero-based round index is the integer quotient of `picks_so_far` divided by N and the zero-based seat index within that round is the remainder. When the round index is even (so round 1, round 3, and so on), the current seat is the seat index plus one, ascending from 1 to N; when the round index is odd, the current seat is N minus the seat index, descending from N back down to 1. A draft attempt by a coach whose team's `draft_position` does not equal the resolved current seat is rejected with `ERR_NOT_TEAMS_TURN`.

A draft pick advances the player from `EVALUATED` to `DRAFTED`. The request supplies the `player_id` of the picked player. The transition requires the season to still be in `DRAFT_OPEN` (otherwise `ERR_SEASON_NOT_DRAFT_OPEN`), the acting coach to match the team's `head_coach_id` (otherwise `ERR_NOT_TEAM_OWNER`), the player's `season_id` to equal the team's `season_id`, and the team's `draft_position` to match the snake-draft seat. The roster also enforces a cap of at most 3 `TIER_A` players per team: if the team's current `tier_a_count` is already 3 or more and the picked player's `evaluation_tier` is `TIER_A`, the pick is rejected with `ERR_TIER_A_CAP_EXCEEDED`. On a successful pick, the player's `team_id` is set to the team's `id`, `draft_pick_overall` is set to the next overall pick number across the season, and the player's `status` flips to `DRAFTED`. The team's `roster_count` is incremented by one and `tier_a_count` is recomputed (counting only players whose `team_id` matches this team and whose `status` is `DRAFTED` — withdrawn players, who in practice never reach `DRAFTED`, are excluded explicitly).

Two coaches racing to draft different players for the same team at the same time serialize on snake-draft seat advancement: the first writer wins, and the second's seat has already advanced, so the second receives `ERR_NOT_TEAMS_TURN`. Independently, a guardian who attempts to withdraw a player while a coach is mid-pick on that same player races to first-writer-wins on the player's `status`: exactly one of withdraw or draft succeeds, and the loser is rejected with `ERR_INVALID_PLAYER_STATE`.

### 3.4. Games — Scheduling and the Postpone/Reschedule Loop

A regular-season `Game` is scheduled by a `LeagueAdmin`. The request body supplies `season_id`, `home_team_id`, `away_team_id`, `field_id` (a 1- to 40-character opaque token identifying the physical diamond), and `scheduled_start`. The optional `game_type` defaults to `REGULAR`; the alternative is `PLAYOFF`, but playoff games are normally created by the bracket-generation sweep (Section 3.6) rather than by hand. The two team identifiers must be different — equal opponents surface as `ERR_INVALID_GAME_OPPONENTS` — and the `scheduled_start` of a regular game must fall inside the season's regular-season window (from `regular_season_start` at midnight UTC of that calendar day through `regular_season_end` at 23:59:59.999 UTC of that calendar day), with a date outside the window rejected as `ERR_GAME_OUT_OF_SEASON_WINDOW`. The server fixes `scheduled_end` as `scheduled_start` plus 90 minutes and snapshots the start as `original_scheduled_start`; the field-overlap principle (Section 2.7) is enforced; the game enters `SCHEDULED` with `referee_id`, `home_score`, `away_score`, and `bracket_round` all null.

Assigning a referee transitions occur at a separate endpoint and require the game to currently have `referee_id` of null. The body supplies `referee_id` and optionally `version`. The assignment runs the referee-buffer overlap check and the weekly-cap check (Section 2.8). Two operators attempting to assign referees to the same game at the same time serialize on a compare-and-set against `Game.referee_id`: exactly one assignment lands, and the loser is rejected with `ERR_GAME_REFEREE_ALREADY_ASSIGNED`.

Postponing a `SCHEDULED` game requires the season to be in either `REGULAR_SEASON` or `PLAYOFFS` and a `reason` from the set { `RAIN`, `FIELD_UNAVAILABLE`, `SAFETY` }; the request may also supply `version`. The transition does considerably more than flip a status — it is the trigger point for a cascade that radiates through the volunteer ledger. First, the game's `status` becomes `POSTPONED`. Second, `referee_id` is nulled so the referee is freed for that slot; the cascade depth here is one. Third, every `VolunteerShift` linked to this game (matching `game_id`) that is still in `SCHEDULED` is moved to `CANCELLED` — cascade depth two. Fourth, for each cancelled shift, the owning guardian's `volunteer_hours_logged` is recomputed via the guardian-sum rule (Section 2.9) — cascade depth three. Fifth, that guardian's `volunteer_status` is re-classified by the threshold rule — cascade depth four. Each touched entity has `updated_at` refreshed and `version` incremented.

Rescheduling moves a `POSTPONED` game back to `SCHEDULED`. The body supplies a new `scheduled_start` (strictly greater than the snapshotted `original_scheduled_start` and no later than `original_scheduled_start` plus `rainout_window_days` days; both boundaries are enforced and a violation is `ERR_RAINOUT_WINDOW_EXCEEDED`), optionally a `referee_id`, optionally an alternative `field_id`, and optionally `version`. The field-overlap and referee-overlap principles are re-evaluated against the new slot; `scheduled_end` is recomputed as the new start plus 90 minutes; `original_scheduled_start` is preserved across the reschedule. If `referee_id` is supplied, the new game pair is checked against the referee's existing assignments with the 30-minute buffer rule and the weekly cap; otherwise `referee_id` is left null and a new assignment is needed before the result can be recorded. The game then re-enters `SCHEDULED`, ready to be played, postponed again, or rescheduled again — the loop is unbounded so long as the rainout window allows. Two rescheduling operations that simultaneously target the same field at overlapping windows serialize first-writer-wins on field occupancy; the loser is rejected with `ERR_FIELD_OVERLAP`. A separate stale-write race — an operator carrying an old `version` value who collides with a fresher reschedule — is decided by the optimistic concurrency rule and the loser is rejected with `ERR_VERSION_CONFLICT`.

Cancelling a `POSTPONED` game is permitted only after the rainout window has elapsed — that is, the logical clock is strictly later than `original_scheduled_start` plus `rainout_window_days` days. The transition simply flips `status` to `CANCELLED`; neither team is awarded a win or a loss, and the cancelled game contributes zero to win/loss totals from that point on.

### 3.5. Game Day — Records, Forfeits, and Team Standings

Recording the result of a `SCHEDULED` game requires several preconditions to coincide. The body supplies `home_score` and `away_score`, both non-negative integers; ties are not permitted in Little League, so `home_score` and `away_score` must differ — an invalid pair (a negative score or equal scores) surfaces as `ERR_INVALID_SCORE`. The game's `referee_id` must be non-null at the moment of recording — a missing referee surfaces as `ERR_GAME_REFEREE_REQUIRED`. The logical clock must be at or beyond the game's `scheduled_end`. On success, the scores are written, `status` flips to `COMPLETED`, and the team-record aggregates are recomputed: the winning team's `wins` is incremented by one and the losing team's `losses` is incremented by one. The aggregation considers a `COMPLETED` game's winner as the team whose score is strictly greater than the other's, and a `FORFEITED` game's winner as the team that is not the `forfeiting_team_id`; `CANCELLED` games contribute zero to both totals.

Forfeiting a `SCHEDULED` game is a separate transition driven by a `LeagueAdmin` when a team cannot field a side. The body supplies `forfeiting_team_id`, which must equal either the `home_team_id` or the `away_team_id`. On success, the game's `status` becomes `FORFEITED`; the non-forfeiting team is awarded the win (its `wins` increments by one) and the forfeiting team takes the loss (its `losses` increments by one). For run-differential purposes, however, forfeited games contribute zero runs to both totals on both sides — they affect the win/loss column but not runs scored or allowed.

Two simultaneous results being recorded on the same game would race on the game row's `version`; the optimistic-concurrency rule routes the loser to `ERR_VERSION_CONFLICT`.

### 3.6. The Playoffs — Seeding, Bracket, and Champion

Opening the playoffs runs the seeding sweep. First, every team's win/loss aggregates are recomputed for consistency. Second, each team's winning percentage is calculated as `wins` divided by the sum of `wins` and `losses`; when both are zero, the percentage is defined to be 0.0. Teams are then ordered, in this priority: first by `win_pct` in descending order (rounded to four decimal places, half-up, before any comparison so that floating-point noise does not change ordering); then by head-to-head wins in descending order, where head-to-head wins are the count of `COMPLETED` games in which one tied team beat another tied team; then by run differential (runs scored minus runs allowed across `COMPLETED` games) in descending order; and finally, as a deterministic last-resort tiebreaker, by team `name` in lexicographic ascending order. The top 4 teams receive a `playoff_seed` of 1 through 4 in that sorted order and have their `playoff_status` flipped from `NOT_QUALIFIED` to `QUALIFIED`. Every remaining team has its `playoff_status` flipped directly from `NOT_QUALIFIED` to `ELIMINATED`.

Round 1 bracket games are then generated automatically as `Game` rows with `game_type` equal to `PLAYOFF` and `bracket_round` equal to 1. The pairings are seed 1 versus seed 4 and seed 2 versus seed 3 — the standard 4-team single-elimination shape. Each round-1 game is created in `SCHEDULED` with `scheduled_start` defaulting to the season's `playoff_cutoff_date` plus 7 days, with `field_id` set to the string token `TBD` (which is to be rescheduled to a real field later), and with `referee_id` null until separately assigned.

As each playoff game reaches a terminal state, the losing team's `playoff_status` is updated. On a `SCHEDULED` to `COMPLETED` transition of a `PLAYOFF` game, the loser's `playoff_status` flips from `QUALIFIED` to `ELIMINATED`. The same flip is applied on a `SCHEDULED` to `FORFEITED` transition: the forfeiting team is eliminated, and bracket advancement proceeds as it would for a completed game. If the just-terminated game is in the final round — the round number equal to the integer ceiling of the base-2 logarithm of the qualified count, which is 4 here, so round 2 — then the winner's `playoff_status` flips from `QUALIFIED` to `CHAMPION`, the terminal state. Otherwise, the system attempts to generate the next round: it locates the sibling game in the same `bracket_round` whose winner feeds the same next-round slot (in a 4-team bracket, the sibling of the 1-vs-4 game is the 2-vs-3 game); if the sibling has also reached `COMPLETED` or `FORFEITED`, a new `Game` is created with `game_type` equal to `PLAYOFF`, `bracket_round` set to the current round plus one, the two winners as `home_team_id` and `away_team_id`, `status` set to `SCHEDULED`, `scheduled_start` set to the larger of the two predecessor games' `scheduled_end` values plus 7 days, and `field_id` again set to the placeholder `TBD`. If the sibling has not yet terminated, the next-round game is deferred and will be created when the sibling does terminate. The cascade depth here can run to three (record-result → losing team's `playoff_status` change → champion or sibling-paired next-round game creation).

### 3.7. Volunteer Shifts — Scheduling, Check-In, Approval

A `VolunteerShift` is scheduled by a `Guardian` (for themselves) or by a `LeagueAdmin`. The body supplies `season_id`, `guardian_id`, `role` from the set { `SCOREKEEPER`, `CONCESSIONS`, `FIELD_PREP`, `UMPIRE_ASSIST`, `SETUP_TEARDOWN` }, `scheduled_start`, `scheduled_end`, and optionally `game_id` for shifts that are tied to a specific game (null for general non-game shifts). A new shift enters `SCHEDULED`.

Checking in is performed only by the owning guardian. The check-in is permitted in the window that opens 30 minutes before the shift's `scheduled_start` and closes 30 minutes after its `scheduled_end`: concretely, the logical clock must be at or after `scheduled_start` minus 30 minutes and at or before `scheduled_end` plus 30 minutes. A check-in outside that window — either too early or too late — is rejected with `ERR_CHECK_IN_OUTSIDE_WINDOW`. A successful check-in flips `status` from `SCHEDULED` to `CHECKED_IN`.

Approving a `CHECKED_IN` shift is the responsibility of a `LeagueAdmin` and is only permitted once the logical clock is at or beyond the shift's `scheduled_end`. The approval computes `hours_credited` as the difference between `scheduled_end` and `scheduled_start` expressed in hours (a 90-minute shift credits 1.50 hours), rounded to two decimal places half-up. The shift's `status` flips to `APPROVED`, the owning guardian's `volunteer_hours_logged` is recomputed by the guardian-sum rule (Section 2.9), and the guardian's `volunteer_status` is reclassified — a two-step cascade on every approval.

A `LeagueAdmin` may mark a `SCHEDULED` shift as `NO_SHOW`, but only after the grace window has closed — that is, the logical clock is strictly later than `scheduled_end` plus 30 minutes. The `status` flips to `NO_SHOW`, terminal.

A guardian may cancel their own `SCHEDULED` shift through a logical-delete operation that moves the shift to the terminal `CANCELLED` state. The same `CANCELLED` transition is also reached as a system cascade from a game postponement (Section 3.4), in which case the actor is the system rather than the guardian.

### 3.8. Audit Trail

Every significant state transition the league performs is recorded as an `AuditEvent` row. The audit event captures `entity_type` (the name of the affected entity), `entity_id` (the `id` of that entity), `actor_role` (the `X-User-Role` of the operator who performed the action), `actor_id` (the `X-User-ID`), `action` (an action keyword such as `PLAYER_DRAFTED` or `GAME_POSTPONED` — the auto-withdraw cascade during the open-regular-season transition writes `PLAYER_AUTO_WITHDRAWN`), and a free-form `details` object carrying any additional context. Audit events are append-only: they are stamped with `created_at` at write time but carry no `updated_at` and no `version`, because they are never re-edited.

A list of audit events is available to `LeagueAdmin`, filterable by `entity_type`, `entity_id`, and `action`, with the standard `limit` and `offset` paging controls.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; endpoints that mutate or read an existing resource respond with HTTP 200. All non-success outcomes use the error envelope from Section 2.2 with a 4xx status code. The HTTP method, path, and authorised role(s) of each endpoint are summarised below; the request bodies, responses, and side effects belong to the workflow narratives in Section 3 and the principles in Section 2.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/league/seasons` | Create a season (DRAFT_OPEN). | LeagueAdmin |
| GET | `/league/seasons/{id}` | Read a season. | LeagueAdmin, Coach, Referee, Guardian |
| POST | `/league/seasons/{id}/start-regular-season` | Open the regular season. | LeagueAdmin |
| POST | `/league/seasons/{id}/start-playoffs` | Open the playoffs (seeding + bracket gen). | LeagueAdmin |
| POST | `/league/seasons/{id}/close` | Close the season. | LeagueAdmin |
| POST | `/league/players` | Register a new player. | Guardian, LeagueAdmin |
| GET | `/league/players/{id}` | Read a player. | LeagueAdmin, Coach, Guardian |
| GET | `/league/players` | List players (filterable). | LeagueAdmin, Coach |
| POST | `/league/players/{id}/verify-age` | Verify age. | LeagueAdmin |
| POST | `/league/players/{id}/record-evaluation` | Record tryout score; compute tier. | LeagueAdmin |
| POST | `/league/players/{id}/withdraw` | Withdraw a player. | Guardian, LeagueAdmin |
| POST | `/league/teams` | Create a team. | LeagueAdmin |
| GET | `/league/teams/{id}` | Read a team. | LeagueAdmin, Coach, Referee, Guardian |
| POST | `/league/teams/{id}/draft-pick` | Draft a player onto this team. | Coach, LeagueAdmin |
| POST | `/league/coaches` | Register a coach. | LeagueAdmin |
| POST | `/league/referees` | Register a referee. | LeagueAdmin |
| POST | `/league/guardians` | Register a guardian. | LeagueAdmin, Guardian |
| GET | `/league/guardians/{id}` | Read a guardian (with derived volunteer_status). | LeagueAdmin, Guardian |
| POST | `/league/games` | Schedule a regular-season game. | LeagueAdmin |
| GET | `/league/games/{id}` | Read a game. | LeagueAdmin, Coach, Referee, Guardian |
| GET | `/league/games` | List games (filterable). | LeagueAdmin, Coach, Referee, Guardian |
| POST | `/league/games/{id}/assign-referee` | Assign a referee. | LeagueAdmin |
| POST | `/league/games/{id}/postpone` | Postpone a SCHEDULED game. | LeagueAdmin |
| POST | `/league/games/{id}/reschedule` | Reschedule a POSTPONED game. | LeagueAdmin |
| POST | `/league/games/{id}/cancel` | Cancel a POSTPONED game past rainout window. | LeagueAdmin |
| POST | `/league/games/{id}/record-result` | Record final score. | LeagueAdmin |
| POST | `/league/games/{id}/forfeit` | Mark a game forfeited. | LeagueAdmin |
| POST | `/league/volunteer-shifts` | Schedule a volunteer shift. | Guardian, LeagueAdmin |
| GET | `/league/volunteer-shifts/{id}` | Read a shift. | Guardian, LeagueAdmin |
| POST | `/league/volunteer-shifts/{id}/check-in` | Check in for a SCHEDULED shift. | Guardian |
| POST | `/league/volunteer-shifts/{id}/approve` | Approve a CHECKED_IN shift; credit hours. | LeagueAdmin |
| POST | `/league/volunteer-shifts/{id}/mark-no-show` | Mark a SCHEDULED shift NO_SHOW. | LeagueAdmin |
| DELETE | `/league/volunteer-shifts/{id}` | Cancel a SCHEDULED shift. | Guardian |
| POST | `/_clock/advance` | Advance the logical clock (test driver). | LeagueAdmin |
| GET | `/league/audit-events` | List audit events. | LeagueAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error appear in the narrative of Sections 2 and 3; this table maps each `error_id` to its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_TEAM_OWNER` | 403 |
| `ERR_SEASON_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_PLAYER_NOT_FOUND` | 404 |
| `ERR_GAME_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_PLAYER_STATE` | 409 |
| `ERR_SEASON_NOT_DRAFT_OPEN` | 409 |
| `ERR_BIRTH_CERT_REQUIRED` | 422 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_COACH_NO_BACKGROUND_CHECK` | 422 |
| `ERR_TIER_A_CAP_EXCEEDED` | 422 |
| `ERR_NOT_TEAMS_TURN` | 409 |
| `ERR_RAINOUT_WINDOW_EXCEEDED` | 422 |
| `ERR_FIELD_OVERLAP` | 409 |
| `ERR_REFEREE_OVERLAP` | 409 |
| `ERR_REFEREE_WEEKLY_CAP_EXCEEDED` | 422 |
| `ERR_GAME_REFEREE_ALREADY_ASSIGNED` | 409 |
| `ERR_GAME_REFEREE_REQUIRED` | 422 |
| `ERR_INVALID_SCORE` | 422 |
| `ERR_INVALID_GAME_OPPONENTS` | 422 |
| `ERR_GAME_OUT_OF_SEASON_WINDOW` | 422 |
| `ERR_CHECK_IN_OUTSIDE_WINDOW` | 422 |
| `ERR_TEAM_DUPLICATE` | 422 |
| `ERR_REGULAR_SEASON_INCOMPLETE` | 409 |
| `ERR_SEASON_NOT_READY` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |
