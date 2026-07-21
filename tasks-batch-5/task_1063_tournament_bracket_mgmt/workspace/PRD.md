# Tournament Bracket Management API — Product Requirements Document

## 1. Introduction

Amateur competitive events live or die by the integrity of their brackets. A single mis-recorded score, a match confirmed by the same person who reported it, or a prize paid to the wrong finisher can unravel an entire weekend of play. This document specifies the Tournament Bracket Management API, a backend that runs the full arc of a grassroots tournament: it holds the venues and physical stations where matches are played, the streaming channels that broadcast them, and the players who compete; it opens and closes registration, checks competitors in against a deadline, seeds them, and generates a bracket appropriate to the chosen format; it schedules matches onto stations without collisions, records and independently confirms results, advances winners through the bracket graph, and adjudicates disputes that can void and replay a match; and finally it ranks finishers, allocates the prize pool, and withholds tax before the tournament is closed.

The system supports four competitive formats — single-elimination, double-elimination, round-robin, and Swiss — each with its own bracket topology and its own way of turning match outcomes into standings. Because money and fairness are at stake, several structural safeguards run throughout: a strict separation of duties so that no single operator both reports and confirms (or both confirms a match and later resolves its dispute), optimistic concurrency control so that stale views cannot silently overwrite fresh results, and two conservation invariants — one on participant headcount, one on prize money — that must hold after every cascade. A server-controlled logical clock underpins all time-sensitive rules so that behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request carries its caller identity in two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they act. The system recognizes exactly four roles: `Director`, `Referee`, `Player`, and `Public`.

Authentication is required on all endpoints except public read (GET) endpoints, player self-signup, and player self-registration; on those three the headers may be absent. When an endpoint does require authentication and the headers are missing or `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles differ both in privilege and in how `X-User-ID` is interpreted:

- When `X-User-Role` is `Director`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A Director is the hierarchical administrator: it owns tournament lifecycle operations, venue/station/channel creation, payout release, and the logical clock, and it may additionally perform every operation that a Referee or Player can. The server may record a Director's `X-User-ID` where a transition writes an actor field (for example as `reported_by_user_id`, `confirmed_by_user_id`, or `resolved_by_user_id` on the affected resource) but does not compare it to any entity's `id`.
- When `X-User-Role` is `Referee`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. A Referee officiates: it schedules, confirms, and replays matches, resolves disputes, and assigns broadcasts. Its `X-User-ID` may be recorded (as `reported_by_user_id`, `confirmed_by_user_id`, or `resolved_by_user_id`) but is never matched against an entity `id`.
- When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting `Player` entity. Ownership checks on any resource that references a `Player` compare the resource's foreign-key field to `X-User-ID`; for example, the player behind a `Registration` is the `Player` whose `id` equals that registration's `player_id`.
- When `X-User-Role` is `Public`, `X-User-ID` is an opaque, unauthenticated identifier. The `Public` role is limited to read access and to player self-signup; it holds no ownership over any entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. Each list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the number of matching records before pagination and `has_more` indicates whether records remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in this system — venues, stations, stream channels, players, tournaments, registrations, matches, stream assignments, payouts, and disputes — carries a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation. All resource types here participate in versioning; there is no resource that carries only `id` and `created_at`.

Two version fields carry special contractual weight and are described in §2.7: a match's `version` and a tournament's `version`. Whenever a rule below says a mutation "bumps the version" of a match or tournament, it means that integer increases by one and `updated_at` is refreshed on that same resource.

### 2.5. Nested Resource Retrieval and Referential Validation

Several paths address a resource nested under a parent, and several request bodies carry foreign-key identifiers. All identifiers are resolved left-to-right in the path first, then within the body. If any referenced entity does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first unresolved identifier; a request for a station listing under a non-existent venue, for instance, fails on the venue before the station collection is ever consulted. Existence checking (priority 3) precedes all state and business validation.

### 2.6. The Logical Clock and Temporal Windows

All time-dependent behavior reads a single server-controlled logical clock rather than wall-clock time, so that deadlines and windows are fully reproducible. On startup the clock is initialized to `2026-07-01T00:00:00Z`, which is deliberately earlier than every default fixture date. A Director advances the clock by supplying a `to_iso8601` instant to the clock-setting capability; the response reports the new `now`. The clock never falls back to wall-clock time even before it has been explicitly set. The only time-sensitive gate in the system is the check-in deadline (§3.3); it reads this logical `now`.

Venue operating hours and scheduling windows are expressed in minutes-after-midnight and in absolute instants respectively, and are validated as described in §2.10 and §3.4.

### 2.7. Optimistic Concurrency Control

Three mutating operations guard against acting on a stale view of a versioned parent, and each demands a client-supplied expected version as a required field.

Confirming a match requires `expected_match_version` in the request body, carrying the client's last observed `version` of that match. If it does not equal the match's current `version` — for example because a dispute resolution moved the match through `REPORTED → DISPUTED → REPORTED` and bumped its version, or a prior confirm already advanced it — the confirm is rejected with `ERR_STALE_MATCH_VERSION` (HTTP 412), so the operator never confirms an outdated result. Resolving a dispute likewise requires `expected_match_version` matching the current `version` of the disputed match; a mismatch is rejected with `ERR_STALE_MATCH_VERSION` (HTTP 412). Completing a tournament requires `expected_tournament_version` in the request body carrying the client's last observed tournament `version`; because bracket generation and payout cascades bump the tournament version, a completion carrying a stale value is rejected with `ERR_STALE_TOURNAMENT_VERSION` (HTTP 412), so the FINAL payout run never executes against a stale view. Endpoints other than these three take no expected-version field.

### 2.8. Monetary Precision and the Money-Conservation Invariant

All prize amounts are held as whole integer cents; there is no fractional-cent representation. Any calculation that produces cents from a percentage — a payout share or a tax withholding — is rounded half up to the nearest whole cent at the moment specified by that calculation, never deferred. Two rounding disciplines matter and are detailed in §3.8: payout shares are each rounded independently and the leftover remainder is pushed onto first place, and tax is rounded per individual payout row rather than on a summed pool.

A money-conservation invariant holds at all times: the sum of `gross_amount_cents` across every `Payout` whose `status` is not `VOID`, plus the tournament's `unallocated_prize_cents`, always equals the tournament's `prize_pool_cents`. Voiding a payout returns its gross to `unallocated_prize_cents`; the switch from provisional to final payouts voids every provisional row (returning their gross to the pool) before any final row is created.

### 2.9. Derived Counters and the Participant-Conservation Invariant

A tournament exposes several counters that are computed from its registrations and matches, not set directly by clients. `registered_count` is the number of registrations whose `status` is `REGISTERED` or `CHECKED_IN`. `checked_in_count` is the number of registrations whose `status` is `CHECKED_IN`. `alive_count` is the number of checked-in registrations not yet eliminated, and `eliminated_count` is the number of checked-in registrations eliminated from the bracket. After every match confirm or void cascade, a participant-conservation invariant must hold: `alive_count` plus `eliminated_count` always equals `checked_in_count`. Each confirm that eliminates a competitor moves exactly one registration from alive to eliminated (`alive_count` decreases by one, `eliminated_count` increases by one); an upheld-dispute void of an eliminating match moves exactly one registration back the other way (`alive_count` increases by one, `eliminated_count` decreases by one); a confirm followed by its compensating void leaves both counters unchanged.

### 2.10. Scheduling Windows, Overlap, and Turnover

The physical schedule is governed by two overlap disciplines that intentionally differ.

Station scheduling uses half-open time intervals `[scheduled_start, scheduled_end)` and a 15-minute turnover buffer between matches on the same station, reflecting the time needed to reset a table or court. Stream broadcasting uses closed intervals `[start_at, end_at]` on a channel and applies no buffer at all. The precise conflict conditions, including boundary behavior, are given in §3.4 and §3.7. A venue additionally constrains when a match may be scheduled: its `open_minute` and `close_minute` are minutes-after-midnight, with `0 <= open_minute < close_minute <= 1440`, and a match's window must fall within `[open_minute, close_minute)` with `scheduled_end` strictly after `scheduled_start`.

### 2.11. Validation Ordering and Cascading Reconciliation

When several checks guard one operation, they are evaluated in a fixed order so that the returned error is deterministic. The global ordering is: authentication (`ERR_UNAUTHENTICATED`) first, then authorization (`ERR_UNAUTHORIZED`), then existence of every referenced entity (`ERR_NOT_FOUND`), then the target's state precondition (`ERR_INVALID_STATE` and its more specific siblings), then business rules specific to the operation, and finally request-shape validation (`ERR_INVALID_REQUEST`) for missing required fields, wrong types, or invalid enum values. Per-operation orderings that refine this global rule are stated with each workflow in §3.

Many operations mutate more than one resource. The system performs these cascades synchronously and immediately: confirming a match advances a winner and may eliminate a loser and adjust tournament counters; resolving a dispute can void a match, which in turn compensates the bracket and cancels broadcasts; completing a tournament ranks finishers and rebuilds the payout set. Each affected resource independently has its `updated_at` refreshed (and, for matches and tournaments, its `version` bumped where the rules below say so).

## 3. Business Logic & Workflows

### 3.1. Building the Competitive Environment

Before any competition can run, a Director assembles the physical and broadcast infrastructure. A **venue** is created with a `name`, a postal `address`, and its operating window given as `open_minute` and `close_minute` (minutes-after-midnight, with the open strictly before the close and both within a single day of 1440 minutes). Within a venue, the Director adds **stations** — the tables or courts where matches are played — each carrying a human `label` and bound to its parent through `venue_id`. A station may be fetched directly or listed under its venue; listing a venue's stations reverse-reaches every station whose `venue_id` points at that venue.

Broadcasting infrastructure is a **stream channel**, created by a Director with a display `name` and a `platform` that must be one of `TWITCH`, `YOUTUBE`, or `FACEBOOK`.

**Players** are the competitors. A player self-signs-up (or is created by a Director) with a public `display_name` and a contact `email` that must be unique across all players. Two optional attributes shape later behavior: `rating`, an integer skill number defaulting to 1000 that drives rating-based seeding, and `tax_id_provided`, a boolean defaulting to false that records whether the player supplied a taxpayer identifier and therefore governs backup-withholding on their winnings.

### 3.2. Tournament Setup and the Registration Window

A Director creates a **tournament** in `DRAFT`. Creation fixes its `name`, the `venue_id` where matches will be played, the `format` (one of `SINGLE_ELIM`, `DOUBLE_ELIM`, `ROUND_ROBIN`, or `SWISS`), a hard capacity `max_participants` of at least 2, and the prize configuration: `prize_pool_cents` (zero or more) and `paid_places` (between 1 and 4 inclusive, defaulting to 2). Three enumerated policies may be supplied or left to their defaults: `seeding_method` (one of `RATING`, `RANDOM_STABLE`, `MANUAL`, defaulting to `RATING`), `tiebreak_method` (one of `SEED` or `GAME_DIFF`, defaulting to `SEED`), and `swiss_rounds` (an integer defaulting to 0, required to be at least 1 when the format is `SWISS` and ignored otherwise). Creation also records the informational window bounds `registration_open_at` and `registration_close_at` and the operative `check_in_deadline`. The system tracks `num_swiss_rounds_played` (how many Swiss rounds have been generated, starting at 0) as play proceeds. The lifecycle status begins at `DRAFT` and is server-managed thereafter; `payout_variant` starts at `NONE`.

A Director opens registration, moving the tournament `DRAFT → REGISTRATION_OPEN`; this requires the tournament to be in `DRAFT` and its venue to exist, and it stamps `registration_open_at` from the request body when one is provided. While the tournament is `REGISTRATION_OPEN`, players enter it. A **registration** is created with the `tournament_id` being entered, the `player_id` entering, and an optional `seed_input` (a requested manual seed, honored only under `MANUAL` seeding). A registration begins in `REGISTERED`; its `seed`, `checked_in_at`, `eliminated` flag (default false), and `final_placement` are all server-managed and are described where they are set. Creating a registration increments the tournament's `registered_count`. Registration is only accepted while the tournament is `REGISTRATION_OPEN` — an attempt in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Two capacity rules guard entry: at most `max_participants` registrations may be in the `REGISTERED`/`CHECKED_IN` set, so the entry that would be the (`max_participants` + 1)-th is rejected with `ERR_TOURNAMENT_FULL` (HTTP 409); and a player may hold at most one non-terminal registration per tournament, so a second concurrent entry is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP 409).

A Director closes registration, moving `REGISTRATION_OPEN → REGISTRATION_CLOSED`; this requires the tournament to be `REGISTRATION_OPEN`, and no new registrations are accepted afterward. A player may withdraw their own registration (a Director may also do so) as long as the registration is `REGISTERED` or `CHECKED_IN` and the tournament is not yet `IN_PROGRESS`; withdrawal moves the registration to `WITHDRAWN`, decrements `registered_count`, and additionally decrements `checked_in_count` when the registration had already checked in.

A Director may cancel a tournament that has not yet started — permitted only while its status is `DRAFT`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED` — moving it to `CANCELLED`. Cancellation voids any provisional payouts and recomputes `unallocated_prize_cents` back to the full `prize_pool_cents`; when cancelling from `REGISTRATION_OPEN` or `REGISTRATION_CLOSED` it additionally cascades every non-terminal registration to `WITHDRAWN`.

### 3.3. Check-In, Seeding, and Bracket Generation

Once registration is closed, competitors confirm attendance. A player checks in their own registration (a Director may also perform it), moving it `REGISTERED → CHECKED_IN`. Three conditions gate this transition and are evaluated in this order: the tournament must be in `REGISTRATION_CLOSED`, otherwise the check-in is rejected with `ERR_TOURNAMENT_NOT_IN_CHECKIN` (HTTP 409); the logical `now` must be at or before the tournament's `check_in_deadline` — the boundary is inclusive, so `now` exactly equal to the deadline is accepted while `now` strictly after it is rejected with `ERR_CHECKIN_CLOSED` (HTTP 409); and the registration must currently be `REGISTERED`. On success the system sets `checked_in_at` to the logical `now` and increments `checked_in_count`.

A Director then generates the bracket, moving the tournament `REGISTRATION_CLOSED → BRACKET_READY`. This requires the tournament to be `REGISTRATION_CLOSED` and at least two checked-in participants (and, when the format is `SWISS`, `swiss_rounds` of at least 1); a generation attempt with fewer than two checked-in participants, or a Swiss tournament configured with zero rounds, is rejected with `ERR_INSUFFICIENT_PARTICIPANTS` (HTTP 409). Only `CHECKED_IN` registrations enter the bracket; those still `REGISTERED` or already `WITHDRAWN` are set aside. Generation performs several coordinated effects: it assigns a seed to every checked-in registration, wires the match graph, initializes the alive/eliminated counters, runs the provisional payout, and bumps the tournament's `version` by one.

**Seeding** assigns each checked-in registration a 1-based `seed` (integer seeds running 1 through `checked_in_count`), determined by `seeding_method`. Under `RATING`, candidates are ordered by the player's `rating` from highest to lowest, breaking ties by `created_at` from earliest to latest (creation time is the only tiebreak; resource `id` is never used). Under `MANUAL`, candidates are ordered by `seed_input` ascending, then by `created_at` ascending. Under `RANDOM_STABLE`, candidates are ordered purely by `created_at` ascending, giving a deterministic insertion-order "shuffle". Walking the resulting order, the first registration receives `seed` 1, the second `seed` 2, and so on.

**Bracket generation** creates the `Match` rows for the format. Each match records which sub-bracket it lives in via `bracket` (one of `MAIN`, `WINNERS`, `LOSERS`, `GRAND_FINAL`), its 1-based `round_number` within that bracket, and its 0-based `slot_index` within the round. Advancement edges are self-referential: `next_match_id` points at the match the winner advances into and `next_slot` (`HOME` or `AWAY`) names which competitor slot the winner fills, while `loser_next_match_id` and `loser_next_slot` describe where a loser drops in double-elimination. For `SINGLE_ELIM`, a standard seeded single-elimination bracket is built over the next power of two greater than or equal to the participant count, byes going to the top seeds, and per-round pairing following canonical bracket order (seed 1 against the lowest, seed 2 against the next-lowest, and so on); the winner edge wires up the tree and the final match has a null `next_match_id`. For `DOUBLE_ELIM`, the winners bracket is built the same way, each winners-bracket loss dropping the loser along `loser_next_match_id` into a losers-bracket match, and the `GRAND_FINAL` is fed by the winners-final winner into its `HOME` slot and the losers-final winner into its `AWAY` slot. For `ROUND_ROBIN`, one `MAIN`-bracket match is created for every unordered pair of participants — that is, participant count times participant count minus one, divided by two — with round numbers laid out by the circle method, and in every match the lower-seeded registration is pinned as home while the higher-seeded is away (deterministic; never random). For `SWISS`, only round 1 is generated at this time, pairing the top half of the seed order against the bottom half with the lower seed as home; later Swiss rounds are not auto-generated. Generation also initializes `alive_count` to `checked_in_count` and `eliminated_count` to 0.

The **provisional payout** runs as part of generation and is detailed in §3.8; it creates `PROVISIONAL` payout rows projected from the seeds and sets `payout_variant` to `PROVISIONAL`.

A Director starts the tournament, moving `BRACKET_READY → IN_PROGRESS`; round-1 matches that already have both competitor slots filled become eligible to be scheduled.

### 3.4. Scheduling Matches on Stations

Play is physically placed by a Referee (or a Director), who schedules a `PENDING` match onto a station and time window, moving it `PENDING → SCHEDULED`. The request supplies the `station_id`, the `scheduled_start`, and the `scheduled_end`. A cascade of conditions must hold, checked in this order after existence: the match must be `PENDING` and its tournament `IN_PROGRESS`; both `home_registration_id` and `away_registration_id` must be populated; both competitors must currently be `CHECKED_IN`, otherwise the schedule is rejected with `ERR_COMPETITOR_NOT_CHECKED_IN` (HTTP 409); the station's `venue_id` must equal the tournament's `venue_id`, otherwise `ERR_STATION_WRONG_VENUE` (HTTP 409); the window must lie within the venue's operating hours with `scheduled_end` strictly after `scheduled_start`, otherwise `ERR_OUTSIDE_VENUE_HOURS` (HTTP 422); and the window must not collide with another match on the same station, otherwise `ERR_STATION_OVERLAP` (HTTP 409). On success the system records `station_id`, `scheduled_start`, and `scheduled_end`.

The **station overlap** test treats each match window as the half-open interval `[scheduled_start, scheduled_end)` and applies the 15-minute turnover buffer on both sides. For the target station and a proposed window, a conflict exists if there is any other match on that station in `SCHEDULED`, `REPORTED`, `CONFIRMED`, or `DISPUTED` status (voided matches are ignored) whose interval, once expanded by the buffer, still overlaps the proposal: concretely, the proposed start falls before that match's end plus 15 minutes, and that match's start falls before the proposed end plus 15 minutes. The buffer means the gap between two matches must be at least 15 minutes; two matches exactly 15 minutes apart do not conflict, while back-to-back matches touching at a shared instant do conflict (half-open intervals with a zero gap collide).

### 3.5. Reporting, Confirming, and Advancing the Bracket

Once a match has been played, its result is entered in two independent steps that enforce separation of duties.

First, a **report**: a competitor of the match or a Referee moves the match `SCHEDULED → REPORTED` by supplying `home_score` and `away_score`. The scores must differ — ties are not permitted in bracket play, so equal scores are rejected with `ERR_TIE_NOT_ALLOWED` (HTTP 422) — and the reporter must be either a competitor of the match or a Referee, otherwise the report is rejected with `ERR_NOT_A_COMPETITOR` (HTTP 403). The system records the two scores and stamps `reported_by_user_id` with the reporter's `X-User-ID`.

Second, a **confirm**: a Referee or Director moves the match `REPORTED → CONFIRMED`. This carries `expected_match_version` for the optimistic-concurrency check of §2.7 and is subject to separation of duties — the confirming `X-User-ID` must differ from `reported_by_user_id`, otherwise the confirm is rejected with `ERR_SOD_SELF_CONFIRM` (HTTP 409). On success the system sets `winner_registration_id` to the higher-scoring competitor and `loser_registration_id` to the other, records `confirmed_by_user_id`, and bumps the match `version` by one. It then cascades the bracket: the winner is written into the `next_slot` of the match named by `next_match_id`, and if that fills both slots on the downstream match, that match becomes eligible to be scheduled. Under `DOUBLE_ELIM` the loser is dropped into the `loser_next_slot` of the match named by `loser_next_match_id`; under single-elimination, round-robin, or a final match, the losing registration is instead eliminated — moved `CHECKED_IN → ELIMINATED` with its `eliminated` flag set true, `alive_count` decremented, and `eliminated_count` incremented. When the confirmed match was the final (its `next_match_id` is null and its `bracket` is `MAIN` or `GRAND_FINAL`), the winner's path toward champion is marked for resolution at completion.

**Standings** are computed on demand and again at completion. For each checked-in registration, only its `CONFIRMED` matches are considered (matches in `PENDING`, `SCHEDULED`, `REPORTED`, `DISPUTED`, or `VOIDED` are excluded). Its wins are the confirmed matches where it is the `winner_registration_id` and its losses are those where it is the `loser_registration_id`; match points are the wins times 3 plus the losses times 0 (a win is worth three points, a loss zero, and the draw value of one point is never earned because ties cannot occur). Its games-for is the sum of its own score across those confirmed matches (its `home_score` when it played home, its `away_score` when away) and its games-against is the sum of the opponent's score across the same matches; the game difference is games-for minus games-against. Registrations are ranked by match points from highest to lowest. Ties on match points are broken by `tiebreak_method`: under `SEED`, the lower `seed` ranks higher and game difference is ignored; under `GAME_DIFF`, the larger game difference ranks higher first, and only then does the lower `seed` break a remaining tie — so under `GAME_DIFF` a lower seed can finish above a higher seed. When a seed is somehow absent, `created_at` is the ultimate fallback; resource `id` is never used as a tiebreak.

### 3.6. Disputes, Voiding, and Replay

A competitor may challenge a result. A player (or a Director) raises a **dispute** by supplying the `match_id`, the `raised_by_registration_id` of the challenger, and a free-text `reason`; the dispute begins in `OPEN`. A dispute may only be raised on a match that is `REPORTED` or `CONFIRMED`, otherwise it is rejected with `ERR_MATCH_NOT_DISPUTABLE` (HTTP 409); and at most one `OPEN` dispute may exist for a match at a time, so a second concurrent challenge is rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409). When the disputed match is still `REPORTED`, raising the dispute freezes it, moving the match `REPORTED → DISPUTED`; while `DISPUTED`, the match cannot be confirmed.

A Referee or Director resolves the dispute by supplying an `outcome` of either `UPHELD` or `REJECTED`, an optional `resolution_note`, and `expected_match_version` for the optimistic-concurrency check against the disputed match. Resolution is guarded by separation of duties in a second dimension: the resolving `X-User-ID` must differ from the disputed match's `confirmed_by_user_id` (meaningful only once the match has been confirmed), otherwise it is rejected with `ERR_SOD_CONFIRMER_RESOLVE` (HTTP 409) — the referee who confirmed a match may not also resolve its dispute. Either outcome records `resolved_by_user_id` and `resolution_note` and bumps the disputed match's `version` by one.

A `REJECTED` outcome moves the dispute `OPEN → REJECTED` and unfreezes the match, moving it `DISPUTED → REPORTED` so it may be confirmed again. An `UPHELD` outcome moves the dispute `OPEN → UPHELD` and voids the match, but the void's consequences differ by the match's prior state. If the match was still `DISPUTED` (never confirmed), it moves `DISPUTED → VOIDED`, its scores are cleared, and any `SCHEDULED` stream assignment for that match is cascaded to `CANCELLED`. If the match had already been `CONFIRMED`, it moves `CONFIRMED → VOIDED` with a full compensation cascade: the advanced winner is pulled back out of the `next_slot` of its `next_match` (that downstream match reverts toward `PENDING` if it thereby loses a filled slot); the losing registration that had been eliminated is reverted `ELIMINATED → CHECKED_IN` with `alive_count` incremented and `eliminated_count` decremented; `winner_registration_id`, `loser_registration_id`, and both scores are cleared; and any `SCHEDULED` stream assignment for the match is cancelled. In both cases the participant-conservation invariant of §2.9 is preserved.

A voided match can be replayed. A Referee or Director resets a `VOIDED` match to `PENDING`, moving it `VOIDED → PENDING`, provided both competitor slots are still populated; the match is then available to be scheduled again, closing the `DISPUTED → VOIDED → PENDING` cycle.

### 3.7. Broadcasting

A Referee or Director assigns a match to a channel for a broadcast window by supplying the `match_id`, the `channel_id`, and the closed broadcast interval `start_at` and `end_at` (with `end_at` strictly after `start_at`). The assignment begins in `SCHEDULED`. The target match must be in a broadcastable state — `SCHEDULED`, `REPORTED`, `CONFIRMED`, or `DISPUTED` — and never `PENDING` or `VOIDED`, otherwise the assignment is rejected with `ERR_MATCH_NOT_SCHEDULABLE_STREAM` (HTTP 409). The channel must be free during the requested window, otherwise the assignment is rejected with `ERR_CHANNEL_OVERLAP` (HTTP 409).

The **stream overlap** test treats each broadcast as a closed interval `[start_at, end_at]` and applies no turnover buffer. For the target channel and a proposed interval, a conflict exists if there is any other `SCHEDULED` assignment on that channel (cancelled assignments are ignored) such that the proposed start is strictly before that assignment's end and that assignment's start is strictly before the proposed end. Because the comparisons are strict, touching endpoints are allowed: an assignment that ends at exactly the instant another begins does not conflict. As noted in §3.6, an assignment's `status` is cascaded to `CANCELLED` when its broadcast match is voided.

### 3.8. Completion, Final Placement, and Payouts

A Director completes the tournament, moving it `IN_PROGRESS → COMPLETED`. Completion carries `expected_tournament_version` for the optimistic-concurrency check of §2.7 and requires that every match be terminal — that is, every match is `CONFIRMED` or `VOIDED`, with no `PENDING`, `SCHEDULED`, `REPORTED`, or `DISPUTED` match remaining; if any match is non-terminal the completion is rejected with `ERR_MATCHES_INCOMPLETE` (HTTP 409). On success the tournament's `version` is bumped by one.

Completion assigns a `final_placement` to every checked-in registration. Placements are dense integers running 1 through `checked_in_count`, with `tiebreak_method` resolving equals exactly as in the standings ranking. In the elimination formats, placement is derived from the round of elimination — the champion is 1, the runner-up is 2, the two semifinal losers share places 3 and 4 (their order settled by the standings tiebreak among them), and so on. In round-robin and Swiss, placement is simply the standings order. The unique first-place finisher is moved `CHECKED_IN → CHAMPION` and has its `final_placement` set to 1.

Payouts are allocated twice over a tournament's life, and the field structure is identical between runs. Each `Payout` records the paying `tournament_id`, the `registration_id` of the finisher it rewards (which may be null for a projected provisional slot with no known finisher yet), the 1-based `placement` it rewards, a `variant` of `PROVISIONAL` or `FINAL`, and the money fields `gross_amount_cents`, `tax_withheld_cents`, and `net_amount_cents`; each payout begins with `status` `PENDING`. The number of rewarded placements equals `paid_places`, which selects the percentage split from the fixed table: one paid place gives the whole pool to first (100 percent); two places split 70 percent and 30 percent; three places split 50, 30, and 20 percent; four places split 40, 30, 20, and 10 percent. The rounding order is pinned: for each rewarded placement in turn, its gross is `prize_pool_cents` multiplied by that placement's percentage and rounded half up to whole cents, computed independently — never by summing first and rounding once. After all placement grosses are computed, the leftover remainder — `prize_pool_cents` minus the sum of the rounded grosses — is added onto first place's gross, so first place absorbs the rounding remainder. For each created payout, `gross_amount_cents` is this figure, tax withholding is applied, and `status` is `PENDING`; the tournament's `unallocated_prize_cents` is then set to `prize_pool_cents` minus the sum of `gross_amount_cents` across payouts whose `status` is not `VOID`.

The two runs differ only in how a placement maps to a finisher. The **provisional** run happens at bracket generation (`payout_variant` `PROVISIONAL`): each placement is projected onto the registration whose `seed` equals that placement (seed 1 is projected first place, and so on), which may be null when unknown, and the amounts are estimates. The **final** run happens at completion (`payout_variant` `FINAL`): each placement maps to the registration whose `final_placement` equals it, which can differ from the provisional projection whenever a lower seed finishes higher. At completion the system voids all provisional payouts (returning their gross to the pool per §2.8), runs the final allocation to create the `FINAL` rows, sets `payout_variant` to `FINAL`, and recomputes `unallocated_prize_cents`.

**Tax withholding** is computed per payout row, never on the summed pool. The rate depends on the finisher's player: when that player's `tax_id_provided` is true the rate is 0 percent, and when it is false the rate is 24 percent (backup withholding). For each payout, `tax_withheld_cents` is `gross_amount_cents` multiplied by the applicable rate and rounded half up to whole cents, and `net_amount_cents` is `gross_amount_cents` minus `tax_withheld_cents`.

Finally, a Director marks a payout paid, moving its `status` `PENDING → PAID`. This is permitted only when the payout is a `FINAL` variant belonging to a `COMPLETED` tournament; an attempt to pay a non-final payout, or one whose tournament is not completed, is rejected with `ERR_PAYOUT_NOT_FINAL` (HTTP 409).

## 4. Endpoint Definitions

Creation of a new stand-alone resource or a new resource added to a collection returns `201 Created`; state transitions and other modifications of an existing resource return `200 OK`. Reads return `200 OK`. "Any" in the Authorized Role(s) column denotes `Director`, `Referee`, `Player`, and `Public`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/venues` | Create a venue | Director |
| GET | `/venues/{id}` | Fetch a venue | Any |
| POST | `/venues/{id}/stations` | Add a station to a venue | Director |
| GET | `/venues/{id}/stations` | List stations of a venue | Any |
| GET | `/stations/{id}` | Fetch a station | Any |
| POST | `/stream-channels` | Create a streaming channel | Director |
| GET | `/stream-channels/{id}` | Fetch a stream channel | Any |
| POST | `/players` | Register a player account | Public, Director |
| GET | `/players/{id}` | Fetch a player | Any |
| POST | `/tournaments` | Create a tournament in DRAFT | Director |
| GET | `/tournaments` | List tournaments | Any |
| GET | `/tournaments/{id}` | Fetch a tournament (with computed counters) | Any |
| POST | `/tournaments/{id}/open-registration` | Open registration | Director |
| POST | `/tournaments/{id}/close-registration` | Close registration | Director |
| POST | `/tournaments/{id}/generate-bracket` | Seed, build bracket, provisional payouts | Director |
| POST | `/tournaments/{id}/start` | Start the tournament | Director |
| POST | `/tournaments/{id}/complete` | Complete; final placements and payouts | Director |
| POST | `/tournaments/{id}/cancel` | Cancel a not-yet-started tournament | Director |
| GET | `/tournaments/{id}/standings` | Computed standings | Any |
| GET | `/tournaments/{id}/matches` | List matches of a tournament | Any |
| GET | `/tournaments/{id}/registrations` | List registrations of a tournament | Any |
| POST | `/registrations` | Enter a player into a tournament | Player, Director |
| GET | `/registrations/{id}` | Fetch a registration | Any |
| GET | `/registrations` | List/filter registrations | Any |
| POST | `/registrations/{id}/check-in` | Check in a registration | Player, Director |
| POST | `/registrations/{id}/withdraw` | Withdraw a registration | Player, Director |
| GET | `/matches/{id}` | Fetch a match | Any |
| GET | `/matches` | List/filter matches | Any |
| POST | `/matches/{id}/schedule` | Schedule a match on a station/window | Referee, Director |
| POST | `/matches/{id}/report` | Report scores | Player, Referee |
| POST | `/matches/{id}/confirm` | Confirm a reported match | Referee, Director |
| POST | `/matches/{id}/replay` | Reset a voided match to pending | Referee, Director |
| POST | `/stream-assignments` | Assign a match to a channel window | Referee, Director |
| GET | `/stream-assignments/{id}` | Fetch a stream assignment | Any |
| GET | `/stream-assignments` | List/filter stream assignments | Any |
| POST | `/disputes` | Raise a dispute on a match | Player, Director |
| GET | `/disputes/{id}` | Fetch a dispute | Any |
| GET | `/disputes` | List/filter disputes | Any |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (uphold/reject) | Referee, Director |
| GET | `/payouts/{id}` | Fetch a payout | Any |
| GET | `/payouts` | List/filter payouts | Any |
| POST | `/payouts/{id}/pay` | Mark a final payout paid | Director |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Director |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TOURNAMENT_NOT_IN_CHECKIN` | 409 |
| `ERR_CHECKIN_CLOSED` | 409 |
| `ERR_STATION_WRONG_VENUE` | 409 |
| `ERR_SOD_SELF_CONFIRM` | 409 |
| `ERR_SOD_CONFIRMER_RESOLVE` | 409 |
| `ERR_COMPETITOR_NOT_CHECKED_IN` | 409 |
| `ERR_TIE_NOT_ALLOWED` | 422 |
| `ERR_NOT_A_COMPETITOR` | 403 |
| `ERR_OUTSIDE_VENUE_HOURS` | 422 |
| `ERR_STATION_OVERLAP` | 409 |
| `ERR_CHANNEL_OVERLAP` | 409 |
| `ERR_MATCH_NOT_SCHEDULABLE_STREAM` | 409 |
| `ERR_TOURNAMENT_FULL` | 409 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_INSUFFICIENT_PARTICIPANTS` | 409 |
| `ERR_MATCHES_INCOMPLETE` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_MATCH_NOT_DISPUTABLE` | 409 |
| `ERR_PAYOUT_NOT_FINAL` | 409 |
| `ERR_STALE_MATCH_VERSION` | 412 |
| `ERR_STALE_TOURNAMENT_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
