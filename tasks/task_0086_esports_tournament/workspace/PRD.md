# Esports Tournament API — Product Requirements Document

## 1. Introduction

Professional esports has outgrown the spreadsheet era. A modern tournament organiser must register hundreds of teams, vet thousands of players, negotiate exclusive and loan contracts under multi-party signing chains, sequence drafts and live matches across global time zones, adjudicate cheating-suspicion and unsportsmanlike-conduct disputes within a 72-hour appeal window, and ultimately distribute multi-currency prize pools that have been swollen by crowdfunding pledges — all while remaining auditable to publishers, sponsors, and tax authorities. The historical pain points are predictable: rosters mutate after lock deadlines, brackets republish without recomputing seeding, mid-tournament disqualifications stranded crowdfunded contributions in legal limbo, and after-the-fact appeals overturned rulings without ever reversing the FORFEITED matches or clawed-back prize allocations.

This document specifies the Esports Tournament Management API — a single source of truth for tournament configuration, team registration, player contracts, draft recording, referee adjudication, transfer negotiations, and prize distribution. The system is designed around four peer-role personas — the league-side operator, the team-side operator, the certified referee, and the player as a contract signatory — and around the principle that every irreversible business event (an UPHELD ruling, a LEAGUE_APPROVED transfer, a PAID prize payout) must be paired with a compensating reversal path so that an overturned appeal restores the bracket exactly as if the original ruling had never been entered.

Time inside this system is logical, not wall-clock. A LeagueAdmin can advance the server's notion of "now" to exercise roster-lock cascades, transfer-window expirations, and contract end-of-term transitions deterministically; the same advance triggers the appropriate side effects in the same order they would fire in production.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` (a stable identifier for the caller) and `X-User-Role` (one of the four values listed below, spelled exactly). When either header is missing, the request is rejected with `ERR_AUTH_MISSING`; when `X-User-Role` carries a value the system does not recognise, the response is `ERR_AUTH_INVALID_ROLE`. If the role is recognised but is not permitted to invoke the requested endpoint per the RBAC matrix, the response is `ERR_FORBIDDEN`.

The four roles are:

- **`LeagueAdmin`** — the league-side operator who configures tournaments, files identity verifications, assigns and rules on match incidents, approves transfers, and finalises prize pools. When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_user_id` on `AuditLogEntry` where a scaffold transition writes it) but does not compare it to any entity's `id`.
- **`TeamManager`** — the team-side operator who registers a team, builds the roster, files transfer offers, and appeals incidents. When `X-User-Role` is `TeamManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Ownership of a `TeamRegistration` is established at creation time by the rule that `X-User-ID` must equal the `manager_id` supplied in the request body; subsequent team-side actions on that registration (such as paying the entry fee, withdrawing, or filing player contracts for that team) require the caller's `X-User-ID` to match the same `manager_id`. The server may record this opaque id as `actor_user_id` on `AuditLogEntry`.
- **`Player`** — a player acting as a signatory on their own `PlayerContract`. When `X-User-Role` is `Player`, `X-User-ID` is the `id` of the acting `PlayerContract` party — specifically, it must equal the `player_id` field on the `PlayerContract` they are attempting to sign. Ownership checks on contract-signing endpoints compare `PlayerContract.player_id` to `X-User-ID`.
- **`Referee`** — a certified official who runs draft and live-match flow and files incidents. When `X-User-Role` is `Referee`, `X-User-ID` is the `id` (specifically, the `user_id`) of the acting `Referee`; ownership checks on any resource that references a `Referee` compare the resource's referee foreign-key field (for instance, the `referee_id` on `MatchIncident` or the assigned referee on a `Match`) to `X-User-ID`.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). The default sort order for every list endpoint is `created_at` ascending; secondary tie-breakers, when stated in §3, do not change the primary ordering rule. The four pagination fields in the response `meta` are `limit`, `offset`, `total_count` (the total number of rows matching the filter set, ignoring pagination), and `has_more` (true when more rows exist beyond the current page). List endpoints may additionally accept domain-specific filters as query parameters — for example, the tournament listing accepts `status` and `region`; the per-tournament match listing accepts `round` (filtering by `round_number`) and `status`; the audit-log listing accepts `subject_type`, `subject_id`, and `actor_user_id`.

### 2.4. Common Resource Properties

Every resource exposed by the API carries an `id` that is a server-minted UUID. The `id` value never carries a type prefix and is unique across the system. Resources whose entity definition includes the common audit fields additionally carry `created_at` and `updated_at` (both ISO 8601 UTC strings with three fractional digits) and `version` (a positive integer initialised to 1 at creation and incremented by one on every mutation, including state transitions). These common-field entities are `Tournament`, `TeamRegistration`, `PlayerContract`, `Match`, `MatchIncident`, `Referee`, `PrizePayout`, `TransferOffer`, and `TransferWindow`.

Four entities are deliberately append-only or singleton in nature and carry only `id` and `created_at` — both `updated_at` and `version` are absent on these rows. They are `IdentityVerification` (an immutable audit record submitted in a single shot), `DraftEvent` (an append-only ban/pick log), `CrowdfundContribution` (an immutable ledger row), `AuditLogEntry` (immutable system trail), and `Clock` (the singleton server-time record).

### 2.5. Numeric Precision and Currency

All monetary quantities are stored as integers in minor currency units (cents for `USD` and `EUR`, equivalent minor units for `KRW` and `CNY`). The four supported currencies — `USD`, `EUR`, `KRW`, `CNY` — appear as `entry_fee_currency` on `Tournament`, `compensation_currency` on `PlayerContract`, `transfer_fee_currency` on `TransferOffer`, and `payout_currency` on `PrizePayout`. Wherever a calculation rounds, the rounding mode is **half-up** and the result is an integer number of cents. Foreign-exchange conversions between currencies use a fixed conversion table and apply half-up rounding to the destination minor unit; chained conversions are never permitted — exactly one conversion per calculation slice.

Risk and ranking quantities are integer points. The contagion risk accumulator is rounded half-up to an integer at each ruling event. Seed numbers and step indices are integers; the bracket pairing produces a deterministic ordering of seeds.

### 2.6. Optimistic Concurrency Control

Endpoints that mutate an existing resource — notably every `PATCH` — accept an optional `version` field in the request body. When `version` is supplied, the server compares it against the stored row's `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted from the request body, the OCC check is skipped and the mutation proceeds against the current row. On every successful mutation the server increments `version` by one and refreshes `updated_at` to the current `Clock.now`.

### 2.7. Logical Time and Time-Gated Transitions

The system's clock is logical and represented by a singleton `Clock` resource whose `now` field is the only source of "current time" used by validation and state-machine rules. A `LeagueAdmin` can advance `Clock.now` to a supplied `to` timestamp; the advance triggers, in deterministic order, every time-gated transition whose precondition becomes true at the new moment: tournaments whose `roster_lock_deadline` has passed cascade their `REGISTRATION_OPEN` status to `ROSTER_LOCKED`, transfer offers whose `TransferWindow.closes_at` has passed move from `PROPOSED` to `EXPIRED`, and player contracts whose `term_end` has passed move from `ACTIVE` to `EXPIRED`. A complementary sweeper capability recomputes deferred booleans such as `roster_locked` and evaluates the auto-disqualify threshold against accumulated risk; both capabilities are admin-only.

### 2.8. Nested Resource Path Validation

URL paths are resolved strictly left to right. For a path such as `/tournaments/{tid}/team-registrations/{rid}` (illustrative), the `tid` segment is resolved first; if it does not match any row, the request fails with `ERR_NOT_FOUND` before `rid` is examined. Foreign-key references inside request bodies are validated next, and any unresolved reference also produces `ERR_NOT_FOUND`. This left-to-right resolution rule is reflected in the priority ordering of the validation chain described below.

### 2.9. Validation Priority and Cascade Semantics

Validation rules are evaluated in a fixed priority order, and the first failing rule determines the response error. The order is: header presence (`ERR_AUTH_MISSING`) first, then header-value validity (`ERR_AUTH_INVALID_ROLE`), then role-based endpoint permission (`ERR_FORBIDDEN`), then left-to-right path resolution (`ERR_NOT_FOUND`), then request-body foreign-key resolution (`ERR_NOT_FOUND`), then state-machine precondition (`ERR_INVALID_STATE`), then referee certification currency (`ERR_REFEREE_CERT_EXPIRED`), then the business-safety block (player age, region match, identity verification — `ERR_PLAYER_UNDERAGE`, `ERR_REGION_MISMATCH`, `ERR_IDENTITY_NOT_VERIFIED`), then the referential and temporal blocks (`ERR_WRONG_SIGNATORY`, `ERR_ROSTER_LOCKED`, `ERR_MATCH_NOT_IN_WINDOW`, `ERR_WINDOW_CLOSED`, `ERR_COOLING_OFF_ACTIVE`), then the constraint block (`ERR_DRAFT_STEP_OUT_OF_ORDER`, `ERR_TEAM_RANKING_INSUFFICIENT`, `ERR_MATCH_TIME_CONFLICT`, `ERR_REFEREE_DOUBLE_BOOKED`, `ERR_PRIZE_TIER_SUM_MISMATCH`, `ERR_PRIZE_POOL_INVARIANT`, `ERR_INSUFFICIENT_TEAMS`), then the fiscal block (`ERR_ENTRY_FEE_INSUFFICIENT`, `ERR_FINE_AMOUNT_REQUIRED`, `ERR_PAYOUT_BELOW_FLOOR`), then `ERR_TOURNAMENT_FULL`, and finally the OCC check (`ERR_VERSION_CONFLICT`).

State-machine mutations cascade as documented in §3. Every cascade hop increments the affected row's `version`, refreshes `updated_at`, and (where the rule explicitly states so) emits an `AuditLogEntry`. Two domains are audit-logged: `MATCH_INCIDENT` actions (file, assign, rule, appeal, appeal-decide, close) and `TRANSFER_OFFER` actions (approve transfer). Each audit row captures the actor's `actor_user_id`, the `actor_role` asserted in `X-User-Role` at the moment of the action, a human-readable `action` label, and a `payload` snapshot of the relevant fields immediately before and after the action.

### 2.10. Concurrency Serialization Contracts

The system guarantees serialised outcomes for six racing scenarios, each with a specific loser-error contract:

- When two `TeamManager` callers concurrently pay entry fees for the last open slot in a capped tournament, the system uses first-writer-wins on the count of `TeamRegistration` rows where `status` equals `REGISTERED`; the later writer receives `ERR_TOURNAMENT_FULL`.
- When a player-sign call and a manager-amendment call race on the same `PlayerContract`, the system serialises on `PlayerContract.status`; exactly one succeeds and the loser receives `ERR_INVALID_STATE`.
- When two referees file a `MatchIncident` for the same combination of `match_id`, `subject_id`, and `classification`, the unique constraint enforces first-writer-wins and the loser receives `ERR_DUPLICATE_INCIDENT`.
- When two report-result calls race for the same `Match` after both teams claim victory, only one transitions `LIVE` to `COMPLETED`; the loser receives `ERR_INVALID_STATE`.
- When two `LeagueAdmin` callers concurrently approve transfers for the same `player_id` within the same window, the second receives `ERR_COOLING_OFF_ACTIVE` because the first has already pinned the cooling-off invariant.
- When concurrent `DraftEvent` writes attempt to claim the same `step_index` within a match, the unique constraint on `(match_id, step_index)` enforces strict ordering and the loser receives `ERR_DRAFT_STEP_TAKEN`.

## 3. Business Logic & Workflows

### 3.1. Tournament Lifecycle and Configuration

A tournament begins as a `LeagueAdmin`-created `Tournament` row in `DRAFT` status. At creation, the admin supplies the public `name`, the `format` (one of `SWISS`, `DOUBLE_ELIMINATION`, `ROUND_ROBIN`, or `GROUP_PLAYOFFS`), the qualifying `region` (one of `NA`, `EU`, `APAC`, `SA`, or `GLOBAL`), the qualification gates `min_age` (defaulting to 16 years) and `min_team_ranking_points` (defaulting to zero), the financial parameters `entry_fee_cents`, `entry_fee_currency`, `base_prize_pool_cents`, `roster_lock_deadline` and `registration_deadline` (both ISO 8601 UTC), the `prize_tier_table` (an ordered list of `{placement, percentage_bps}` entries), the `ban_pick_sequence` (an ordered list of `{step, team, action}` blocks defining the draft order, with `team` drawn from `A` or `B` and `action` from `BAN` or `PICK`), the `map_pool` and `character_pool` lists, the `seeding_rule` (one of `RANKING`, `RANDOM`, or `REGIONAL_BALANCE`, defaulting to `RANKING`), the `max_teams` cap, and the `required_referee_level`. A read on a tournament additionally exposes the computed `crowdfunded_prize_pool_cents` (the sum of `CrowdfundContribution.amount_cents` across rows whose `status` is `COLLECTED`), the `total_prize_pool_cents` (the sum of `base_prize_pool_cents` and `crowdfunded_prize_pool_cents`), and `bracket_published_at` (null until the bracket is published, at which point it is set to `Clock.now`).

Opening registration moves the tournament from `DRAFT` to `REGISTRATION_OPEN`. The transition is admin-only and requires two preconditions to hold simultaneously: the `prize_tier_table` must have at least one entry, and the sum of every entry's `percentage_bps` plus the MVP allocation of 500 basis points (5% of the pool) must equal exactly 10000 basis points — failing this contract returns `ERR_PRIZE_TIER_SUM_MISMATCH`; additionally, `Clock.now` must be strictly earlier than `registration_deadline`, otherwise the response is `ERR_REGISTRATION_DEADLINE_PASSED`.

Locking the rosters advances the tournament from `REGISTRATION_OPEN` to `ROSTER_LOCKED`. The transition can be triggered manually by a `LeagueAdmin`, or it fires automatically the first time the logical clock advances to a moment at or after `roster_lock_deadline`. In either path, two cascades execute: every `TeamRegistration` whose `status` is `DRAFT` or `FEE_PENDING` under this tournament is moved to `WITHDRAWN`, and every `TeamRegistration` whose `status` is `REGISTERED` has its `roster_locked` flag flipped to true. The cascade is hop-by-hop — each affected registration has its own `version` incremented and `updated_at` refreshed.

Publishing the bracket transitions `ROSTER_LOCKED` to `BRACKET_PUBLISHED`. Publication requires at least two `TeamRegistration` rows in `REGISTERED` status — otherwise `ERR_INSUFFICIENT_TEAMS` — and, for `RANKING` seeding, the `ranking_points_snapshot` must already be pinned on every registered team. Publication runs the bracket pairing calculation, assigns a `seed_number` to every registered team, creates the round-1 `Match` rows per the format's pairing rules, fills any bye slot, sets `bracket_published_at` to `Clock.now`, and assigns the appropriate `team_a_id`, `team_b_id`, and `is_bye` per match.

The bracket pairing calculation is a two-stage operation. Stage one orders the registered teams. When `seeding_rule` is `RANKING`, the order is by descending `ranking_points_snapshot`, then by ascending `created_at`, then by ascending `id`. When `seeding_rule` is `RANDOM`, the order is a deterministic shuffle keyed by the tournament's `id` so that a given tournament always produces the same random order on re-publication. When `seeding_rule` is `REGIONAL_BALANCE`, the order interleaves teams across regions round-robin to spread regions evenly across the bracket, with descending `ranking_points_snapshot` and then ascending `id` as the within-region tie-break. Stage two derives pairings from the ordered set per `format`: for `SWISS` and `DOUBLE_ELIMINATION` the round-one pairings are seed 1 against seed N, seed 2 against seed N-1, and so on inward; for `ROUND_ROBIN` the round-one rotation pairs the standard round-robin schedule's first slate; for `GROUP_PLAYOFFS` the ordered teams are snake-drafted into groups of four and the round-one pairings are the first slate of each group. When the registered team count is odd, exactly one team receives a bye. The bye assignment intentionally diverges by format: in `DOUBLE_ELIMINATION` the lowest-seed-number (best-ranked) team receives the bye; in `SWISS` the lowest-ranked (highest-seed-number) team receives the bye. The bye match is created with `is_bye` true, the bye recipient placed in either `team_a_id` or `team_b_id` and the other side left null, and `winner_team_id` pre-set to the non-null side so the bye recipient advances automatically.

Publication validates that no pair of created matches involving either of the same teams overlaps on the half-open interval `[scheduled_start, scheduled_end)`; an overlap rejects publication with `ERR_MATCH_TIME_CONFLICT`.

Starting the tournament transitions `BRACKET_PUBLISHED` to `IN_PROGRESS` and is admin-driven without preconditions. Completion transitions `IN_PROGRESS` to `COMPLETED` and can be triggered manually by a `LeagueAdmin` or fire automatically when every `Match` row reaches a terminal state (`COMPLETED`, `FORFEITED`, or `DISQUALIFIED`); manual completion requires the same condition — otherwise `ERR_MATCHES_INCOMPLETE`. On completion, the system computes the provisional prize allocation and emits one `PrizePayout` row in `PROVISIONAL` status per `prize_tier_table` entry plus one row for the MVP award (see §3.6).

Finally, distribution transitions `COMPLETED` to `PRIZES_DISTRIBUTED`. Distribution requires that every `PrizePayout` for the tournament has already reached `FINALIZED` status — otherwise `ERR_PRIZE_POOL_NOT_FINALIZED` — and that the sum of `PrizePayout.gross_amount_cents` across the tournament equals `total_prize_pool_cents` exactly, otherwise `ERR_PRIZE_POOL_INVARIANT`. The transition cascades every payout from `FINALIZED` to `PAID`. Cancellation is a parallel branch from `REGISTRATION_OPEN`: it moves the tournament to `CANCELLED` (a terminal state) with a free-text `reason`, refunds every `TeamRegistration` in `FEE_PENDING` or `REGISTERED` (their `entry_fee_paid_cents` is reversed and `status` becomes `WITHDRAWN`), and reverses every `CrowdfundContribution` whose `status` is `COLLECTED` to `REFUNDED`.

### 3.2. Team Registration, Qualification, and the Entry-Fee Settlement

A `TeamManager` registers a team by submitting `team_name`, `manager_id`, `region`, optional `logo_url`, and `sponsors` (a list of `{name, tier}` entries whose `tier` is one of `GOLD`, `SILVER`, or `BRONZE`). Registration is only accepted while the parent tournament is in `REGISTRATION_OPEN`; otherwise the response is `ERR_REGISTRATION_NOT_OPEN`. The `X-User-ID` header must equal the supplied `manager_id`, and the `team_name` must be unique within the tournament among registrations whose `status` is not `WITHDRAWN`, otherwise `ERR_DUPLICATE_TEAM_NAME`. A successful registration creates the row in `DRAFT` status with `entry_fee_paid_cents` zero, `roster_locked` false, and `seed_number` unset; the `tournament_id` is taken from the path.

The team then files its `PlayerContract` rows under that registration (covered in §3.3) and, once at least five `MAIN`-slot players are bound to the team and identity-verified, submits the entry-fee payment to advance from `FEE_PENDING` to `REGISTERED`. (The transition from `DRAFT` to `FEE_PENDING` happens implicitly the moment the first qualifying contract is bound; the registration is in `FEE_PENDING` while awaiting payment.) The payment endpoint accepts `amount_cents` and `currency` as the submitted-payment description. The system converts the submitted amount into `entry_fee_currency` at the fixed FX table, accumulates it into `entry_fee_paid_cents`, and then evaluates qualification.

Qualification has four gates, all of which must hold for the `FEE_PENDING → REGISTERED` transition to fire. First, the cumulative `entry_fee_paid_cents` (after FX conversion to `entry_fee_currency`) must be at least `Tournament.entry_fee_cents`; otherwise `ERR_ENTRY_FEE_INSUFFICIENT`. Second, the team must have at least five `PlayerContract` rows bound to it with `roster_slot` equal to `MAIN`, every one of which has `identity_verified` set to true; otherwise `ERR_ROSTER_INCOMPLETE`, and if any single player's `identity_verified` is still false the more specific `ERR_IDENTITY_NOT_VERIFIED` is returned per the priority order. Third, every main-roster player's `player_age` must be at least `Tournament.min_age` (the boundary is inclusive — a player exactly at the minimum passes); otherwise `ERR_PLAYER_UNDERAGE`. Fourth, the team's `region` must equal `Tournament.region`, or `Tournament.region` must be `GLOBAL`; otherwise `ERR_REGION_MISMATCH`. The aggregate ranking gate is then evaluated: the `ranking_points_snapshot` is computed as the sum of `PlayerContract.ranking_points` across the `MAIN`-slot players whose contract `status` is `ACTIVE` or `PENDING_SIGNATURES` (substitute slots are excluded), and the snapshot must be at least `Tournament.min_team_ranking_points` (strict-less rejects; values equal to the threshold pass) — otherwise `ERR_TEAM_RANKING_INSUFFICIENT`. The snapshot is then pinned on the registration: subsequent roster changes do not retroactively alter the value the qualification gate was evaluated against. A successful payment also enforces the tournament cap: the count of registrations whose `status` is `REGISTERED` must remain at or below `max_teams` — otherwise `ERR_TOURNAMENT_FULL`.

Withdrawal is a manager-driven exit from registration. From `FEE_PENDING` or `REGISTERED`, the manager calls the withdrawal endpoint and the registration transitions to `WITHDRAWN` provided `Clock.now` is strictly before `roster_lock_deadline` and the tournament is below `ROSTER_LOCKED`; otherwise `ERR_ROSTER_LOCKED`. Withdrawal from `REGISTERED` emits a compensating refund event that reduces the tournament-level revenue ledger by the same amount that was originally credited — the entry-fee conservation invariant must hold across the full lifecycle.

### 3.3. Player Contracts and the Multi-Party Signing Chain

A `TeamManager` files a `PlayerContract` in `DRAFT` status by supplying `player_id`, `player_legal_name`, `player_age`, the `team_id` to bind to, the `contract_type` (one of `EXCLUSIVE`, `LOAN`, or `FREE_AGENT`), the `roster_slot` (`MAIN` or `SUBSTITUTE`), the dates `term_start` and `term_end` (with `term_end` strictly greater than `term_start` — otherwise `ERR_INVALID_CONTRACT_TERM`), the `monthly_compensation_cents` and `compensation_currency`, the `dispute_resolution_clause` (one of `ARBITRATION`, `LITIGATION`, or `MEDIATION`, defaulting to `ARBITRATION`), the player's `ranking_points` snapshot from the external ranking service, and the `required_signatories` array. The `required_signatories` is an ordered list of `{party}` entries whose `party` value is `PLAYER`, `TEAM_MANAGER`, or `LEAGUE_ADMIN`; it pins the order in which the contract must be signed. The contract initially has `identity_verified` false, an empty `signatures` array, and `signed_version_id` null.

Identity verification is filed against a contract by a `LeagueAdmin`, who supplies the `document_hash`, the `jurisdiction` (an ISO-3166 alpha-2 country code — this value pins the tax-withholding rate later applied to MVP and special-award payouts), the verification `status` (either `VERIFIED` or `REJECTED`), and a `rejection_reason` (required when `status` is `REJECTED`). The server records the parent contract reference as `contract_id` on the verification row alongside the submitted `player_id`. A row in `VERIFIED` status flips the parent contract's `identity_verified` to true; a `REJECTED` row records the audit-style reason but does not flip the flag. The `IdentityVerification` row is immutable once written: only `id`, `created_at`, and the submitted fields (plus the system-set `contract_id`) are stored; there is no `updated_at` or `version` on this entity.

Initiating signing transitions the contract from `DRAFT` to `PENDING_SIGNATURES`. Three preconditions must hold simultaneously: the contract's `identity_verified` must be true (otherwise `ERR_IDENTITY_NOT_VERIFIED`), `term_end` must be strictly greater than `term_start` (otherwise `ERR_INVALID_CONTRACT_TERM`), and `required_signatories` must be non-empty (otherwise `ERR_NO_SIGNATORIES`). Each intermediate signature loops from `PENDING_SIGNATURES` back to `PENDING_SIGNATURES`: the current `signatures` length must be strictly less than the `required_signatories` length, and the calling role must match `required_signatories[len(signatures)].party` — that is, the party expected at the current index. A mismatch rejects with `ERR_WRONG_SIGNATORY`. Each successful sign appends `{party, signed_by_user_id, signed_at}` to `signatures`, where `signed_by_user_id` is the caller's `X-User-ID` and `signed_at` is `Clock.now`.

The final signature transitions `PENDING_SIGNATURES` to `ACTIVE`. After the append, the `signatures` length must equal the `required_signatories` length; additionally, the `TeamRegistration` referenced by `team_id` must not be in `WITHDRAWN` or `DISQUALIFIED` — otherwise `ERR_TEAM_NOT_ELIGIBLE`. On `ACTIVE`, the system pins `signed_version_id` to the current `version` value of the contract — this freezes the exact version that every party signed.

Amendments are filed against an `ACTIVE` contract by the `TeamManager`, who supplies `proposed_changes` describing the proposed modification. The amendment transition moves the contract from `ACTIVE` to `AMENDMENT_PENDING`, and as a side effect clears `signed_version_id` to null — a pending amendment invalidates the previously frozen signed version. Preconditions are that `signed_version_id` is currently not null and `Clock.now` is strictly earlier than `term_end`. The amendment is then routed for re-signing by every required party. Once all `required_signatories` have re-signed the amended terms, a `LeagueAdmin` approves the amendment to transition the contract from `AMENDMENT_PENDING` back to `ACTIVE`; the approval re-pins `signed_version_id` to the new current `version`.

A `LeagueAdmin` can terminate an `ACTIVE` contract to `TERMINATED` by supplying a `reason`; the precondition is that the supplied reason is non-empty and the `dispute_resolution_clause` has been invoked (this is recorded as part of the audit payload). If the terminated contract was bound to a `REGISTERED` team in a `MAIN` slot, the system marks the registration's roster as incomplete: the team is no longer eligible to play future matches, and any scheduled match the team has a place in will forfeit on play attempt. A contract automatically transitions from `ACTIVE` to `EXPIRED` when the logical clock advances to a moment at or after `term_end`.

### 3.4. Match Draft, Live Play, and Result Reporting

Once the bracket is published, each `Match` exists in `SCHEDULED` status. A match has a `round_number`, a `bracket_position`, `team_a_id` and `team_b_id` (one of which is null when `is_bye` is true), `scheduled_start` and `scheduled_end` (the latter is `scheduled_start` plus the format-rule slot duration and pins overlap detection), and starts with `winner_team_id` and `forfeit_reason` unset.

A `LeagueAdmin` may adjust a match's `scheduled_start` and `scheduled_end` while it is still `SCHEDULED`. The adjustment runs the same overlap check that publication performed: the new interval, evaluated as half-open `[scheduled_start, scheduled_end)`, must not overlap any other non-`FORFEITED` match on the same tournament involving either of the two teams — otherwise `ERR_MATCH_TIME_CONFLICT`. The adjustment is OCC-checked against the supplied `version`.

Referees themselves are administered separately: a `LeagueAdmin` registers a referee with `user_id`, `full_name`, `certification_level` (one of `L1`, `L2`, or `L3`), and `certification_expiry`. The referee must hold a `certification_level` that equals or exceeds the parent tournament's `required_referee_level` to officiate any match in that tournament. The admin may update a referee's `status` (transitioning between `ACTIVE` and `SUSPENDED`), `certification_level`, and `certification_expiry` via the OCC-protected referee patch endpoint.

A `LeagueAdmin` assigns a `Referee` to a match by supplying `referee_user_id`. The assignment runs the referee-double-booking check: the assigned referee may not already be allocated to any other match whose buffered interval (`scheduled_start` minus 15 minutes through `scheduled_end` plus 15 minutes) overlaps the current match's identically buffered interval — otherwise `ERR_REFEREE_DOUBLE_BOOKED`. The 15-minute buffer is added on both ends, so two adjacent matches with no gap between them double-book the referee even though their raw intervals do not overlap.

Starting the draft transitions the match from `SCHEDULED` to `DRAFT_IN_PROGRESS`. Three preconditions hold simultaneously: the calling `Referee`'s `user_id` must equal `X-User-ID`, the referee's `status` must be `ACTIVE`, and `Clock.now` must be strictly earlier than `certification_expiry` — otherwise `ERR_REFEREE_CERT_EXPIRED`; the same expiry check is also enforced when filing a `MatchIncident`. `Clock.now` must lie in the half-open interval `[scheduled_start, scheduled_end)` — otherwise `ERR_MATCH_NOT_IN_WINDOW`. And both `team_a_id` and `team_b_id` must be populated, which is equivalent to saying `is_bye` is false; bye matches skip the draft.

During the draft, each call appends a `DraftEvent` to the match. The caller supplies `step_index`, `action` (`BAN` or `PICK`), `side` (`A` or `B`), `target_type` (`MAP` or `CHARACTER`), `target_name`, and an optional `anomaly_type`. The system stamps `recorded_by_user_id` with the calling referee's `X-User-ID`. The strict-ordering rule is that the submitted `step_index` must equal the next expected step, which is computed as the count of `DraftEvent` rows already recorded for this match whose `anomaly_type` is null plus one — otherwise `ERR_DRAFT_STEP_OUT_OF_ORDER`. When `anomaly_type` is `DISCONNECT`, the system inserts the row as a placeholder, the step still counts, and the match's `scheduled_end` is extended by a 60-second grace window. When `anomaly_type` is `MISCLICK`, the previous `DraftEvent` at index `step_index - 1` filed by the same `side` is voided (its effective count is decremented), and the new event must claim the step index immediately preceding the next-expected step (`next_expected_step - 1`). The count of `DraftEvent` rows must equal the length of the tournament's `ban_pick_sequence` before the draft can be completed; once it does, the referee completes the draft (or the final draft-event step implicitly does so), and the match transitions from `DRAFT_IN_PROGRESS` to `LIVE`.

Once `LIVE`, the referee reports the result by supplying `winner_team_id`, which must equal either `team_a_id` or `team_b_id`. The transition `LIVE → COMPLETED` is the canonical happy path; if it is the last match in the tournament's bracket, the parent tournament's `IN_PROGRESS → COMPLETED` precondition becomes satisfiable. From `LIVE`, the referee or a `LeagueAdmin` may instead forfeit the match by supplying `forfeit_reason` and `winner_team_id`; the match moves to `FORFEITED`. A `SCHEDULED` match can also move to `FORFEITED` automatically when the team-disqualification cascade fires before play starts.

### 3.5. Incident Filing, Rulings, and the Appeal Cycle

A certified `Referee` files a `MatchIncident` by supplying `match_id`, `subject_type` (one of `PLAYER`, `TEAM`, or `MATCH`), `subject_id` (the id of the matching entity per `subject_type`), `classification` (one of `LATENCY`, `CHEATING_SUSPICION`, `UNSPORTSMANLIKE_CONDUCT`, or `RULE_VIOLATION`), the `evidence` array (a list of `{kind, uri, hash}` entries whose `kind` is `REPLAY`, `LOG`, or `SCREENSHOT`), and `referee_id`, which must equal `X-User-ID`. The incident is initialised with `ruling` `PENDING`, `penalty_type` `NONE`, `appeal_count` zero, and `status` `FILED`. Filing emits an `AuditLogEntry` with `subject_type` `MATCH_INCIDENT` and `action` label "FILE", capturing the relevant before/after payload.

A `LeagueAdmin` assigns the incident for review, transitioning `FILED → UNDER_REVIEW`. The assignment re-validates the filing referee's certification was valid at file time and appends an `AuditLogEntry` with action label "ASSIGN_REVIEW".

The admin then rules: `UNDER_REVIEW → RULED` requires a supplied ruling value (`UPHELD` or `DISMISSED`) and, when the ruling is `UPHELD`, a `penalty_type` (one of `WARNING`, `FORFEIT`, `DISQUALIFICATION`, or `FINE`). If `penalty_type` is `FINE`, the `fine_amount_cents` must be strictly greater than zero (the boundary is exclusive — a submitted value of zero rejects with `ERR_FINE_AMOUNT_REQUIRED`) and is denominated in the tournament's `entry_fee_currency`. The ruling emits an `AuditLogEntry` with action label `"RULE_UPHELD"` or `"RULE_DISMISSED"`. When the ruling is `UPHELD` with `penalty_type` `FINE`, a fine-ledger row debits the team's deposit; the named-quantity invariant is that the sum of all fine-ledger rows equals the sum of all UPHELD-fine `fine_amount_cents` across the system. When the ruling is `UPHELD` with `penalty_type` `DISQUALIFICATION` and `subject_type` `TEAM`, the cascade described next is kicked off.

The team-disqualification cascade is a three-hop transitive operation. Hop one moves the `TeamRegistration.status` from `REGISTERED` to `DISQUALIFIED`. Hop two visits every non-terminal `Match` whose `team_a_id` or `team_b_id` equals the disqualified team's id and moves it to `FORFEITED`, setting `winner_team_id` to the other side and `forfeit_reason` to a label that names the originating incident; every forfeited match in turn emits a bracket-advance event that adjusts the downstream `Match.team_a_id` and `Match.team_b_id` per the format's pairing rule. Hop three visits every `PrizePayout` already emitted in `PROVISIONAL` status whose `team_id` equals the disqualified team's id, sets its `gross_amount_cents` to zero, and moves its `status` to `CLAWED_BACK`. Every affected row across all three hops has its `version` incremented and `updated_at` refreshed; the cascade is the chain of mutations the test suite uses to verify the bracket and prize-pool invariants.

The contagion risk accumulator updates on every `UNDER_REVIEW → RULED` transition with `ruling` `UPHELD`. The team's accumulated risk is first decayed by a half-life of 30 days from the last update: the previous risk value is multiplied by 0.5 raised to the power of the number of days elapsed since the previous decay event divided by 30. The decayed value is then added to a per-ruling delta. The delta is the product of two factors: a base weight determined by the penalty (1 for `WARNING`, 3 for `FINE`, 5 for `FORFEIT`, 10 for `DISQUALIFICATION`) and a classification multiplier (1.0 for `LATENCY`, 1.5 for `UNSPORTSMANLIKE_CONDUCT`, 2.0 for `RULE_VIOLATION`, 3.0 for `CHEATING_SUSPICION`). The sum is rounded half-up to an integer at the end, and the result becomes the new accumulated risk. When the accumulated risk crosses 50 risk points, the sweeper capability evaluates whether the team should be auto-disqualified.

Appeals are filed by a `TeamManager` whose registration is the subject of the ruling. The transition `RULED → APPEALED` requires the current `appeal_count` to be strictly less than one (the maximum is one appeal cycle — otherwise `ERR_APPEAL_LIMIT_REACHED`) and `Clock.now` to be strictly earlier than the moment of the ruling plus 72 hours (otherwise `ERR_APPEAL_WINDOW_CLOSED`). The appellant supplies the `grounds` for the appeal. The side effect is that `appeal_count` is incremented by one.

A `LeagueAdmin` decides the appeal, transitioning `APPEALED → RULED` and supplying `decision`, `new_ruling`, and `new_penalty_type`. When the decision overturns the prior ruling, the system performs the full compensating reversal: the incident's `ruling` becomes `OVERTURNED`, `penalty_type` becomes `NONE`, and every cascade hop triggered by the prior `UPHELD` is reversed in the opposite order — the team moves from `DISQUALIFIED` back to `REGISTERED`, every `FORFEITED` match that the cascade had created returns to its prior state, and every `PrizePayout` that had been set to `CLAWED_BACK` returns to `PROVISIONAL` with its original `gross_amount_cents` restored. The contagion-risk reversal subtracts the exact delta originally added (with no re-decay), so the rule-plus-appeal cycle leaves the named quantity unchanged modulo natural decay between the two events. Closing the incident transitions `RULED → CLOSED` once `appeal_count` equals 1 or `Clock.now` has reached the ruling moment plus 72 hours, whichever comes first.

Two referees filing on the same `(match_id, subject_id, classification)` triple race against the system's unique constraint; the loser receives `ERR_DUPLICATE_INCIDENT`. A racing player-sign and manager-amendment on the same contract serialise on `PlayerContract.status` and the loser receives `ERR_INVALID_STATE`. Two report-result calls racing for a `Match` serialise on the `LIVE → COMPLETED` transition; the loser receives `ERR_INVALID_STATE`.

### 3.6. Prize Pool Computation, Tax Withholding, and Payout Settlement

When a tournament transitions `IN_PROGRESS → COMPLETED`, the system computes the provisional prize allocation in a single pass. The eligible team set is every `TeamRegistration` under the tournament whose `status` is `REGISTERED` or `DISQUALIFIED` — the provisional pass is forward-looking and assumes disqualifications may still be appealed and overturned. The eligible set is sorted by ascending final placement, then by descending `ranking_points_snapshot`, then by ascending `id` as the deterministic tie-break. The total prize pool is taken as `total_prize_pool_cents`, which equals `base_prize_pool_cents` plus the sum of every `CrowdfundContribution.amount_cents` whose `status` is `COLLECTED`.

For each entry in the `prize_tier_table` sorted by ascending `placement`, the system emits one `PrizePayout` row: `team_id` is set to the team at the corresponding position in the sorted set, `award_kind` is set to `PLACEMENT`, `placement` is set to the tier's placement value, and `gross_amount_cents` is computed as `total_prize_pool_cents` multiplied by the tier's `percentage_bps`, divided by 10000, and rounded half-up to an integer number of cents at the row level — one round per row, not at any intermediate step. An MVP row is then emitted: `award_kind` is set to `MVP`, `player_id` is set to the highest-aggregate-score player across the tournament (the deterministic tie-break is the lexicographically smallest `player_id`), and `gross_amount_cents` is computed as `total_prize_pool_cents` multiplied by the MVP allocation of 500 basis points (5%), divided by 10000, and rounded half-up. The 500-basis-point MVP allocation is the same value the `prize_tier_table` sum invariant accounts for. Every provisional row starts in `PROVISIONAL` status with `tax_withheld_cents` zero and `net_amount_cents` zero — these are computed only at finalisation.

Finalisation transitions every payout from `PROVISIONAL` to `FINALIZED` via a tournament-scoped endpoint. Two preconditions hold: the tournament's `status` must be `COMPLETED` (otherwise `ERR_TOURNAMENT_NOT_COMPLETED`); and the gross amount on each row, recomputed via the final-pass algorithm, must match the row's existing value — otherwise `ERR_PRIZE_FINAL_MISMATCH`. The final-pass algorithm differs from the provisional pass in exactly one respect: the eligible team set is restricted to `TeamRegistration` rows whose `status` is `REGISTERED` only. Placements collapse upward — placement N is taken by the N-th remaining team, so disqualified holes do not waste prize tiers. When no disqualifications have occurred between provisional emission and finalisation, the two algorithms produce identical numbers on each row; when they have, the provisional row for a disqualified team is the one whose `gross_amount_cents` is zero in `CLAWED_BACK` status, and the final pass reallocates that slot's percentage to the next team upward.

At the moment of `PROVISIONAL → FINALIZED`, the recipient's jurisdiction is pinned and the tax-withholding calculation locks `tax_withheld_cents`. For a `PLACEMENT` payout, the recipient jurisdiction is taken from the registered manager's identity record — specifically, the `IdentityVerification.jurisdiction` of the `TeamRegistration.manager_id`. For an `MVP` or special-award payout, the recipient jurisdiction is the `IdentityVerification.jurisdiction` of the player's `PlayerContract`. The jurisdiction code, an ISO-3166 alpha-2 string, selects a tiered withholding bracket from the system table. The supported tables are:

- `US`: a first tier at 24% (2400 basis points) for taxable amounts up to 1,000,000.00 USD (`up_to_cents` 100,000,000), then a second tier at 37% (3700 basis points) for the remainder up to the practical cap (`up_to_cents` 999,999,999,999).
- `DE`: a single tier at 45% (4500 basis points) covering taxable amounts up to 50,000,000.00 EUR (`up_to_cents` 5,000,000,000).
- `KR`: a first tier at 22% (2200 basis points) for taxable amounts up to 1,000,000.00 KRW-equivalent (`up_to_cents` 100,000,000), a second tier at 35% (3500 basis points) for the slice up to 5,000,000.00 (`up_to_cents` 500,000,000), and a third tier at 45% (4500 basis points) for any remainder up to the practical cap.
- `CN`: a single tier at 20% (2000 basis points) covering taxable amounts up to the practical cap.

The withholding is evaluated by walking the bracket in ascending order of `up_to_cents`. For each tier, the system computes the slice in cents as the greater of zero and the lesser of the remaining taxable amount and the tier's `up_to_cents`, minus the previous tier's `up_to_cents`; the tax contribution from this slice is the slice multiplied by the tier's `rate_bps`, divided by 10000, and rounded half-up to an integer number of cents. The slice tax is accumulated into the running total. After the slice is processed, the previous-tier marker is set to this tier's `up_to_cents`, and if the remaining taxable amount is now at or below the tier's `up_to_cents`, the walk terminates. Rounding is applied at every slice — the sum of slice taxes is the final tax in `entry_fee_currency`.

Foreign-exchange conversion to `payout_currency` happens after tax computation, so the tax floor is preserved in the recipient currency. The tax in source currency is multiplied by the FX rate from `entry_fee_currency` to `payout_currency` (from the fixed table at conversions including `USD`→`USD`=1.0, `USD`→`EUR`=0.92, `USD`→`KRW`=1350.0, `USD`→`CNY`=7.20, `EUR`→`USD`=1.09, `EUR`→`EUR`=1.0, `EUR`→`KRW`=1465.0, `EUR`→`CNY`=7.83, `KRW`→`USD`=0.00074, `KRW`→`EUR`=0.00068, `KRW`→`KRW`=1.0, `KRW`→`CNY`=0.0053, `CNY`→`USD`=0.139, `CNY`→`EUR`=0.128, `CNY`→`KRW`=187.5, `CNY`→`CNY`=1.0) and rounded half-up to integer minor units; the gross amount is converted in the same way; and `net_amount_cents` is the converted gross minus the converted tax.

A minimum-payout floor applies in `payout_currency`. If the computed net is strictly less than 100 cents (the `MIN_PAYOUT_FLOOR_CENTS` constant — equivalent to 1.00 unit of the payout currency), the system reduces the withheld tax by exactly the shortfall (capped at the existing tax so it never falls below zero) and recomputes net so that net equals 100 cents. The recipient's preferred `payout_currency` defaults to `entry_fee_currency`, but a team-side payout preference may override it (in which case the override is applied at finalise time and pinned). The `jurisdiction` snapshot is written onto the `PrizePayout` row at finalise time. If, after applying the floor adjustment, the net still cannot be brought up to the floor (because the gross itself is below the floor in the destination currency), the finalisation rejects with `ERR_PAYOUT_BELOW_FLOOR`.

Distribution moves each payout from `FINALIZED` to `PAID` via the tournament-level cascade described in §3.1. A clawback from `PROVISIONAL` to `CLAWED_BACK` may also fire from the team-disqualification cascade: the row's `gross_amount_cents` is set to zero and the remaining funds return to the tournament's `total_prize_pool_cents` pool for redistribution to remaining placements during the final pass.

### 3.7. Crowdfunding Contributions and Transfers Between Teams

A `LeagueAdmin` files crowdfunding contributions to a tournament by supplying `contributor_user_id`, `amount_cents`, and a `status` (initially `PLEDGED` or `COLLECTED`). The contribution is an immutable ledger row that carries only `id`, `created_at`, and the submitted fields; there is no `updated_at` or `version`. A new row in `COLLECTED` status recomputes the tournament's `crowdfunded_prize_pool_cents` (the sum of `amount_cents` across all `COLLECTED` rows under the tournament) and therefore `total_prize_pool_cents`. Rows in `PLEDGED` or `REFUNDED` status do not contribute to the pool; a tournament cancellation cascade moves every `COLLECTED` row to `REFUNDED`.

A `LeagueAdmin` opens a `TransferWindow` by supplying `name`, `opens_at`, `closes_at`, and `cooling_off_days` (defaulting to 30). The window is enforced as a half-open interval: a transfer event is valid only when `opens_at <= Clock.now` and `Clock.now < closes_at`. Outside this interval, any operation gated by the window rejects with `ERR_WINDOW_CLOSED`. The `cooling_off_days` value defines the per-player serialization invariant: once a player has had a `TransferOffer` reach `LEAGUE_APPROVED`, no offer with the same `player_id` may reach `LEAGUE_APPROVED` again until at least `cooling_off_days` have elapsed since the previous approval.

A `TeamManager` proposes a transfer by supplying `player_id`, `from_team_id`, `to_team_id`, `window_id`, `transfer_fee_cents`, and `transfer_fee_currency`. The new offer enters `PROPOSED` status with `from_team_decision_at`, `to_team_decision_at`, and `league_decision_at` unset and `history` empty. Proposal requires the window to be open and the cooling-off invariant on `player_id` to hold — otherwise `ERR_COOLING_OFF_ACTIVE`. The `from_team` may counter the offer (transitioning `PROPOSED → COUNTERED` with a new `transfer_fee_cents` and `transfer_fee_currency`; the prior terms and counter terms are appended to `history` as `{round, by, action, terms, at}` entries with `action` of `COUNTER`), accept it (`PROPOSED → ACCEPTED_BY_FROM` or `COUNTERED → ACCEPTED_BY_FROM`, side-effect: `from_team_decision_at = Clock.now`), or reject it (`PROPOSED → REJECTED` with a free-text `reason`).

Once the `from_team` has accepted, the `to_team` co-accepts to transition `ACCEPTED_BY_FROM → ACCEPTED_BY_BOTH`, which requires the window to still be open and sets `to_team_decision_at = Clock.now`. A `LeagueAdmin` then approves the transfer with a `decision`, transitioning `ACCEPTED_BY_BOTH → LEAGUE_APPROVED`. The approval requires that the cooling-off invariant on `player_id` still holds (the second of two same-player approvers within `cooling_off_days` receives `ERR_COOLING_OFF_ACTIVE`) and that the player's current `PlayerContract.status` is `ACTIVE` — otherwise `ERR_CONTRACT_NOT_ACTIVE`. The side effects are a three-hop transitive operation: hop one reassigns the `PlayerContract.team_id` from `from_team_id` to `to_team_id` (preserving the named quantity that the sum across all teams of active main-roster size minus opening-day total equals the sum of net transfers); hop two updates the transfer-fee ledger so that `to_team.entry_fee_paid_cents` is debited by `transfer_fee_cents` (FX-converted from `transfer_fee_currency` to the tournament's `entry_fee_currency` with half-up rounding) and `from_team` is credited by the same amount; hop three appends an `AuditLogEntry` with `subject_type` `TRANSFER_OFFER`, `action` label "APPROVE_TRANSFER", `actor_user_id` set to the admin's `X-User-ID`, `actor_role` set to `LeagueAdmin`, and a `payload` snapshot of the offer immediately before and after. The admin may instead reject from `ACCEPTED_BY_BOTH`, transitioning to `REJECTED`. A `PROPOSED` offer that crosses its window's `closes_at` transitions automatically to `EXPIRED` on the next clock advance. The audit log can be queried with the filters `subject_type`, `subject_id`, `actor_user_id`, plus the standard `limit` and `offset` pagination parameters.

## 4. Endpoint Definitions

The endpoints below summarise the API surface. New resources are created with status code 201; in-place modifications and state transitions use 200. Request bodies, response envelopes, and side effects must be reconstructed by cross-referencing §3 narratives — this table intentionally omits them.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /tournaments | Create Tournament in DRAFT | LeagueAdmin |
| GET | /tournaments/{tid} | Read Tournament with computed fields | LeagueAdmin, TeamManager, Referee, Player |
| GET | /tournaments | List Tournaments with pagination/filter | LeagueAdmin, TeamManager, Referee, Player |
| POST | /tournaments/{tid}/open-registration | Transition DRAFT→REGISTRATION_OPEN | LeagueAdmin |
| POST | /tournaments/{tid}/lock-rosters | Transition REGISTRATION_OPEN→ROSTER_LOCKED | LeagueAdmin |
| POST | /tournaments/{tid}/publish-bracket | Compute seeding, create round-1 Matches | LeagueAdmin |
| POST | /tournaments/{tid}/start | Transition BRACKET_PUBLISHED→IN_PROGRESS | LeagueAdmin |
| POST | /tournaments/{tid}/complete | Transition IN_PROGRESS→COMPLETED | LeagueAdmin |
| POST | /tournaments/{tid}/finalize-prize-pool | Finalize every PrizePayout | LeagueAdmin |
| POST | /tournaments/{tid}/distribute-prizes | Transition COMPLETED→PRIZES_DISTRIBUTED | LeagueAdmin |
| POST | /tournaments/{tid}/cancel | Cancel Tournament; refund cascade | LeagueAdmin |
| POST | /tournaments/{tid}/team-registrations | Create TeamRegistration | TeamManager |
| GET | /team-registrations/{rid} | Read TeamRegistration | LeagueAdmin, TeamManager |
| POST | /team-registrations/{rid}/pay-entry-fee | Submit entry-fee payment; transition FEE_PENDING→REGISTERED | TeamManager |
| POST | /team-registrations/{rid}/withdraw | Withdraw before roster-lock | TeamManager |
| POST | /player-contracts | Create PlayerContract in DRAFT | TeamManager |
| GET | /player-contracts/{cid} | Read PlayerContract | LeagueAdmin, TeamManager, Player |
| POST | /player-contracts/{cid}/identity-verifications | File IdentityVerification | LeagueAdmin |
| POST | /player-contracts/{cid}/initiate-signing | Transition DRAFT→PENDING_SIGNATURES | TeamManager |
| POST | /player-contracts/{cid}/sign | Append a signature; final sign triggers ACTIVE | Player, TeamManager, LeagueAdmin |
| POST | /player-contracts/{cid}/amendments | File contract amendment; transition ACTIVE→AMENDMENT_PENDING | TeamManager |
| POST | /player-contracts/{cid}/amendments/{aid}/approve | Approve amendment; AMENDMENT_PENDING→ACTIVE | LeagueAdmin |
| POST | /player-contracts/{cid}/terminate | Terminate ACTIVE contract | LeagueAdmin |
| GET | /matches/{mid} | Read Match | LeagueAdmin, TeamManager, Referee, Player |
| GET | /tournaments/{tid}/matches | List Matches in a tournament | LeagueAdmin, TeamManager, Referee, Player |
| PATCH | /matches/{mid} | Adjust scheduled_start/scheduled_end before LIVE | LeagueAdmin |
| POST | /matches/{mid}/assign-referee | Assign Referee to a Match | LeagueAdmin |
| POST | /matches/{mid}/start-draft | SCHEDULED→DRAFT_IN_PROGRESS | Referee |
| POST | /matches/{mid}/draft-events | Append draft event (ban/pick) | Referee |
| POST | /matches/{mid}/complete-draft | DRAFT_IN_PROGRESS→LIVE | Referee |
| POST | /matches/{mid}/report-result | LIVE→COMPLETED with winner | Referee |
| POST | /matches/{mid}/forfeit | Manual forfeit | Referee, LeagueAdmin |
| GET | /matches/{mid}/draft-events | Read full draft history | LeagueAdmin, TeamManager, Referee, Player |
| POST | /match-incidents | File MatchIncident | Referee |
| GET | /match-incidents/{iid} | Read MatchIncident | LeagueAdmin, TeamManager, Referee |
| POST | /match-incidents/{iid}/assign | FILED→UNDER_REVIEW | LeagueAdmin |
| POST | /match-incidents/{iid}/rule | UNDER_REVIEW→RULED with ruling + penalty | LeagueAdmin |
| POST | /match-incidents/{iid}/appeal | RULED→APPEALED | TeamManager |
| POST | /match-incidents/{iid}/appeal-decide | APPEALED→RULED (with overturn branch) | LeagueAdmin |
| POST | /match-incidents/{iid}/close | RULED→CLOSED | LeagueAdmin |
| POST | /referees | Register a Referee | LeagueAdmin |
| GET | /referees/{rfid} | Read Referee | LeagueAdmin, TeamManager |
| PATCH | /referees/{rfid} | Update Referee (suspend, renew cert) | LeagueAdmin |
| POST | /tournaments/{tid}/crowdfund-contributions | Pledge or collect a contribution | LeagueAdmin |
| POST | /transfer-windows | Create a TransferWindow | LeagueAdmin |
| GET | /transfer-windows/{wid} | Read TransferWindow | LeagueAdmin, TeamManager |
| POST | /transfer-offers | Propose a transfer | TeamManager |
| GET | /transfer-offers/{oid} | Read TransferOffer | LeagueAdmin, TeamManager |
| POST | /transfer-offers/{oid}/counter | Counter the offer | TeamManager |
| POST | /transfer-offers/{oid}/accept | Accept by from_team | TeamManager |
| POST | /transfer-offers/{oid}/co-accept | ACCEPTED_BY_FROM→ACCEPTED_BY_BOTH | TeamManager |
| POST | /transfer-offers/{oid}/reject | Reject the offer | TeamManager, LeagueAdmin |
| POST | /transfer-offers/{oid}/league-approve | ACCEPTED_BY_BOTH→LEAGUE_APPROVED | LeagueAdmin |
| GET | /audit-log | List audit entries with filters | LeagueAdmin |
| POST | /_clock/advance | Advance Clock.now to the supplied `to` instant | LeagueAdmin |
| POST | /_sweep/run | Trigger the deferred-action sweeper | LeagueAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_REGISTRATION_NOT_OPEN | 409 |
| ERR_REGISTRATION_DEADLINE_PASSED | 409 |
| ERR_DUPLICATE_TEAM_NAME | 409 |
| ERR_ROSTER_LOCKED | 409 |
| ERR_ROSTER_INCOMPLETE | 422 |
| ERR_PLAYER_UNDERAGE | 422 |
| ERR_REGION_MISMATCH | 422 |
| ERR_TEAM_RANKING_INSUFFICIENT | 422 |
| ERR_IDENTITY_NOT_VERIFIED | 422 |
| ERR_INVALID_CONTRACT_TERM | 422 |
| ERR_NO_SIGNATORIES | 422 |
| ERR_WRONG_SIGNATORY | 422 |
| ERR_TEAM_NOT_ELIGIBLE | 409 |
| ERR_ENTRY_FEE_INSUFFICIENT | 402 |
| ERR_TOURNAMENT_FULL | 409 |
| ERR_INSUFFICIENT_TEAMS | 422 |
| ERR_PRIZE_TIER_SUM_MISMATCH | 422 |
| ERR_TOURNAMENT_NOT_COMPLETED | 409 |
| ERR_PRIZE_FINAL_MISMATCH | 409 |
| ERR_PRIZE_POOL_INVARIANT | 409 |
| ERR_PRIZE_POOL_NOT_FINALIZED | 409 |
| ERR_PAYOUT_BELOW_FLOOR | 422 |
| ERR_MATCH_NOT_IN_WINDOW | 409 |
| ERR_MATCH_TIME_CONFLICT | 409 |
| ERR_REFEREE_CERT_EXPIRED | 403 |
| ERR_REFEREE_DOUBLE_BOOKED | 409 |
| ERR_DRAFT_STEP_OUT_OF_ORDER | 422 |
| ERR_DRAFT_STEP_TAKEN | 409 |
| ERR_DUPLICATE_INCIDENT | 409 |
| ERR_FINE_AMOUNT_REQUIRED | 422 |
| ERR_APPEAL_LIMIT_REACHED | 409 |
| ERR_APPEAL_WINDOW_CLOSED | 409 |
| ERR_WINDOW_CLOSED | 409 |
| ERR_COOLING_OFF_ACTIVE | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_MATCHES_INCOMPLETE | 409 |
