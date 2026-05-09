# Sports Event Registration API — Product Requirements Document

## 1. Introduction

Competitive sports events are governed by a chain of inseparable concerns: who is eligible to enter, who plays whom, who officiates, who decides when scores stand, who pays out, and who answers when the laboratory says something is wrong. Today these concerns are stitched together with email threads, spreadsheets, and after-the-fact reconciliation; the moment a single dispute or doping positive surfaces, the entire ledger of rankings and payouts must be reconstructed by hand. The Sports Event Registration API exists to replace that scaffolding with a single integrity-preserving system of record that can take an event from a draft regulation document through to its archived sanctions and final prize-payment evidence.

The platform is intended for tournament organizers running single-elimination, round-robin, and tennis-style "best-of-sets" competitions across federated regional bodies. It must coordinate the work of organizers, referees, athletes, disciplinary officers, doping officers, and an appeals board — six populations whose actions are deliberately segregated from one another so that no single party can simultaneously enter a result, dispute it, decide on the dispute, and pay themselves out. Equally, the system is the integration backbone for downstream payment processing, governing-body archival, and athlete-facing IM notifications, all of which must observe a consistent view of the tournament state. Because doping and dispute outcomes can retroactively change rankings and prize allocations, the system is designed with explicit posture-driven gating, immutable audit logging for every result and sanction change, and a deterministic recomputation of prize money under the cascade of a sanction issued or revoked.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and contract guarantees that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two identifying headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. A request that is missing either header, or whose values are otherwise unrecognized, is rejected with `ERR_AUTH`. A request whose role is not authorized for the endpoint it is calling is rejected with `ERR_FORBIDDEN`.

The system recognizes six distinct roles, spelled exactly as follows: `Organizer`, `Referee`, `Participant`, `DisciplinaryOfficer`, `DopingOfficer`, and `AppealsBoard`.

When `X-User-Role` is `Referee`, `X-User-ID` is the `id` of the acting `Referee` row; ownership checks on any resource that references a `Referee` (notably `RefereeAssignment.referee_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` row; ownership checks on any resource that references a `Participant` (notably `Dispute.filed_by_participant_id` and `Appeal.filed_by_user_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Organizer`, `DisciplinaryOfficer`, `DopingOfficer`, or `AppealsBoard`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `actor_user_id` on an `AuditLog` row written by these operators, or as the `actor_user_id` field in a `chain_log` entry on a `DopingSample` — but it does not compare it to any entity's `id`. Each role's responsibilities and segregation-of-duties constraints are described in §3.

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

For endpoints returning lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

The primary entities of the system — `Event`, `Participant`, `Referee`, `Match`, `RefereeAssignment`, `Dispute`, `RankingEntry`, `PrizePayment`, `DopingSample`, and `Appeal` — carry a shared set of system-managed fields:

- `id` (string): a system-generated UUID. The identifier carries no type prefix; it is the bare UUID.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer initialized to 1 on creation that increments by exactly 1 with every mutation, including system-driven mutations triggered by cascades and clock advance.

A small set of entities are write-once and therefore carry only `id` and `created_at`: `ResultEntry`, `SanctionRecord`, `AuditLog`, and `SyncEvent`. For these four, both `updated_at` and `version` are absent — they are not modified after insertion. `ResultEntry` rows can become "superseded" by a later `CORRECTION`, but that supersession is recorded by writing `superseded_by_id` on the older row at insert time of the newer row, not by mutating it later.

### 2.5. Optimistic Concurrency Control

Endpoints that mutate a specific resource by its identifier accept an optional `version` field in the request body. When `version` is supplied, the server compares it to the current persisted `version` of the targeted resource; on mismatch, the request is rejected with `ERR_VERSION_CONFLICT`. Omitting the `version` field skips the optimistic-concurrency check entirely, and the mutation proceeds against whatever the current server state is. This behavior is uniform across all `POST` operations that target a specific resource by its id (open, close-registration, draw, start, complete, cancel, withdraw, activate, revoke, custody, result, void, decide, dispute resolution, and clock advance — wherever `version?` appears in the request body).

### 2.6. Numeric Precision and Currency Handling

All monetary fields exposed to the API — `entry_fee_cents`, `entry_fee_paid_cents`, `prize_pool_cents`, `gross_amount_cents`, `tax_withheld_cents`, `forfeit_amount_cents`, `net_amount_cents`, `gross_prize_cents`, `net_prize_cents`, `prize_paid_total_cents`, `prize_forfeited_cents` — are integer counts of minor currency units. The `tax_withholding_pct` field on `Event` is a decimal number with exactly two decimal places, restricted to the inclusive range zero through fifty; values outside that range are rejected with `ERR_TAX_OUT_OF_RANGE`.

The `Event.settlement_currency` field is one of `USD`, `EUR`, `JPY`, or `GBP`, and pins the currency for both the entry fee and every prize payout under the event. For `USD`, `EUR`, and `GBP`, one minor unit is one hundredth of the major unit. For `JPY`, one minor unit is one yen — the system treats Japanese yen as having no fractional sub-unit, so all "cents" math still uses integers but with a per-currency denomination factor of 1 instead of 100.

All rounding in the system, wherever it is applied to a monetary or percentage figure, uses the half-up rule. The prize calculation pins the order of rounding explicitly: the per-rank gross is rounded first, then the per-row tax is rounded, in that order — see §3.6.

### 2.7. Hierarchical Path Validation

Many endpoints address resources nested inside parent resources — for example, the participant list under an event, the matches under an event, or the custody operations on a sample under doping. The server validates path identifiers strictly left-to-right: a request whose first identifier in the URL does not resolve to an existing row is rejected with `ERR_NOT_FOUND` before any later identifier is touched. A request whose URL identifiers all resolve, but whose body references a foreign key to a non-existent row (for example, a `referee_id` in a `RefereeAssignment` body, a `participant_id` in a doping-sample body, or a `sanction_id` in an appeal body), is rejected with `ERR_REFERENCE_NOT_FOUND`. The two errors are deliberately distinct so that test fixtures can distinguish a "wrong path" from a "dangling body reference".

### 2.8. State Posture and System-Wide Gating

Every event carries a derived `posture` whose value is one of `CLEAN`, `UNDER_REVIEW`, or `FROZEN`. Posture is recomputed deterministically on every status change of a `SanctionRecord` or `Appeal` traceable to the event via `DopingSample.event_id`. The rule is: count all `SanctionRecord` rows for samples in this event whose `status` is `ISSUED` or `APPEALED` (call this the open-sanctions count), and count all `Appeal` rows whose underlying sanction belongs to a sample in this event and whose `status` is `PENDING` (call this the pending-appeals count). If either the pending-appeals count is greater than zero, or any `SanctionRecord` for the event is in `APPEALED`, the posture is `FROZEN`. Otherwise, if the open-sanctions count is greater than zero, the posture is `UNDER_REVIEW`. Otherwise the posture is `CLEAN`.

A `FROZEN` posture gates a fixed set of operations: result submission for any match, the system-driven prize-payout transition that pays a `PrizePayment`, and event completion. In all three, the rejection code is `ERR_EVENT_FROZEN`. `UNDER_REVIEW` is an informational state — it does not by itself block any of these operations, but it indicates outstanding sanction work and is the default posture once a sanction is issued and before any appeal is filed.

### 2.9. Cascades, Hierarchical Consistency, and `updated_at`/`version` Mutation

Several lifecycle transitions produce cross-entity cascades — a single client call mutates more than one row. Whenever a cascade fires, every affected resource has its `updated_at` refreshed and its `version` incremented (subject to §2.4: the four common-fields-bare entities — `ResultEntry`, `SanctionRecord`, `AuditLog`, `SyncEvent` — are write-once and not subject to this rule). Cascade points are described inline in §3 alongside the workflows that drive them. Examples include: drawing an event creating `Match` rows and flipping participants from `REGISTERED` to `SEEDED`; cancelling an event in `OPEN` or `REGISTRATION_CLOSED` status converting in-flight participants to `WITHDRAWN`; locking a match propagating to `RankingEntry` recomputation and to the next-round match's seat assignment; a positive doping result auto-creating a `SanctionRecord`, disqualifying the participant, and forfeiting a previously-`SCHEDULED` `PrizePayment`; and an appeal being upheld restoring a forfeited payment to `SCHEDULED` with `forfeit_amount_cents` reset to zero.

### 2.10. Audit Logging and Outbox Synchronization

Two operations write `AuditLog` rows: any change to a match's locked scores after lock (driven by a dispute uphold with corrected scores) writes an entry of `kind` `RESULT_CHANGE` with `subject_kind` `MATCH`, `subject_id` set to the match id, `actor_user_id` and `actor_role` captured from the request headers, and `from_value`/`to_value` JSON snapshots of the locked-score fields before and after the change; and any change to a `SanctionRecord` lifecycle (issuance, appeal, final, revoke) writes an entry of `kind` `SANCTION_CHANGE` with `subject_kind` `SANCTION_RECORD` and the corresponding before/after snapshots. The audit log is append-only.

An outbox table of `SyncEvent` rows records every external integration. Each row carries `target_system` (one of `PAYMENT`, `GOVERNING_BODY`, `IM`), `kind` (one of `ENTRY_FEE_CHARGED`, `PRIZE_PAID`, `SANCTION_ARCHIVED`, `DRAW_ANNOUNCED`), a frozen JSON `payload` snapshot, and an `emitted_at` server timestamp. Outbox emission is described inline at the workflows that trigger it.

### 2.11. The Logical Clock and System-Driven Transitions

The system exposes an admin-only test-driving capability that advances a logical clock to a supplied `to` instant; only an `Organizer` may invoke it. Advancing the clock is the way several time-based transitions are exercised: registration auto-closing when `now()` reaches `registration_closes_at`, an event auto-starting when `now()` reaches `starts_at`, a `SCHEDULED` `PrizePayment` advancing to `PAID` when `now()` reaches `scheduled_pay_at`, and a `SanctionRecord` advancing from `ISSUED` to `FINAL` when `now()` is later than `created_at + 14 days` and no `Appeal` has been filed. A separate idempotent sweep capability runs all such recomputations and auto-state-machine advances exactly once per call without requiring the clock itself to move; both capabilities return a generic object envelope with no business payload.

### 2.12. Validation Priority and Evaluation Order

When multiple checks could fail on the same request, the server evaluates them in the order below, returning the first failure encountered. Tests rely on this order to disambiguate which `error_id` is returned when a request triggers more than one violation simultaneously.

1. Header presence — missing/unrecognized `X-User-ID`/`X-User-Role` returns `ERR_AUTH`.
2. Role permission — a recognized role attempting an operation it is not authorized for returns `ERR_FORBIDDEN`.
3. URL-path existence — a non-existent identifier in the URL path returns `ERR_NOT_FOUND`, evaluated left-to-right.
4. Body foreign-key existence — a body-referenced foreign key (`event_id`, `match_id`, `participant_id`, `referee_id`, `sample_id`, `submitted_by_assignment_id`, `replaces_assignment_id`, `filed_by_participant_id`, `filed_by_user_id`, `sanction_id`) that names a non-existent row returns `ERR_REFERENCE_NOT_FOUND`.
5. Source-state validity — an operation whose required source state does not match the current state of the targeted resource returns `ERR_INVALID_STATE`.
6. Posture gating — when the event's posture is `FROZEN` and the operation is one of the three gated operations (result submission, prize-payment system pay, event completion), the request returns `ERR_EVENT_FROZEN`.
7. Domain-specific business validations — applied in the priority order specified by the workflows in §3 and reproduced in the precedence rules of each subsection. In particular, when result submission is concerned: chain-of-custody monotonicity comes before segregation-of-duties on doping endpoints; conflict-of-interest comes before qualification on referee assignment; cross-verifier identity (rejecting a duplicate-referee second submission) comes before disagreement (rejecting a mismatched-score second submission), so the same referee submitting a non-matching second entry receives `ERR_DUPLICATE_REFEREE_ENTRY`, not `ERR_RESULT_DISAGREEMENT`.
8. Generic body validation — type mismatches, missing required fields, and other shape problems return `ERR_VALIDATION`.
9. Optimistic-concurrency — when a `version` is supplied and disagrees with the server's, return `ERR_VERSION_CONFLICT`.

### 2.13. Concurrency Guarantees

Several races have explicit serialization rules and pinned losers. Two referees racing to submit cross-verifying `ResultEntry` rows for the same match serialize first-writer-wins on the match's transition from `SCHEDULED` to `RESULT_PENDING`; the second submission whose scores disagree with the first is rejected with `ERR_RESULT_DISAGREEMENT`, the match remains in `RESULT_PENDING`, and no `Dispute` is auto-opened. An organizer revoking a `RefereeAssignment` while the same referee races to submit a result serializes first-writer-wins on the assignment's `status`; the loser receives `ERR_INVALID_STATE`. An organizer drawing an event concurrently with a participant withdraw serializes first-writer-wins on the event's transition to `DRAWN`; if the withdraw wins and `registered_count` falls below `capacity_min`, the draw is rejected with `ERR_REGISTRATION_BELOW_MIN`, and if the draw wins, the late withdraw still succeeds and cascades match voids. Two organizers concurrently completing the same event are serialized first-writer-wins on the event's transition to `COMPLETED`; the loser receives `ERR_INVALID_STATE`. Two doping officers concurrently appending custody rows to the same `DopingSample` are serialized by strict monotonicity on `chain_log[].at`; the loser whose appended `at` is less than or equal to the prior tail's `at` receives `ERR_CHAIN_OF_CUSTODY_BROKEN`. Finally, a participant filing an `Appeal` at the exact instant the 14-day deadline is being crossed by clock advance is given the inclusive boundary: an appeal POSTed when `now()` equals `created_at + 14 days` still succeeds, and the system `FINAL` transition runs only when `now()` is strictly later than `created_at + 14 days`; the late appeal rejection code is `ERR_APPEAL_WINDOW_CLOSED`.

## 3. Business Logic & Workflows

### 3.1. Event Definition, Opening, and Registration

An `Organizer` initiates a tournament by creating an `Event`. The creation payload supplies a free-text `name` between 1 and 120 characters, the discipline class `event_type` (one of `SINGLE_ELIM`, `ROUND_ROBIN`, or `SETS_MATCH` for tennis-style competitions), the host's two-letter uppercase ISO country code in `country_code`, a free-text `regulations_text` summary between 1 and 4000 characters, the registration window endpoints `registration_opens_at` (inclusive) and `registration_closes_at` (exclusive) with the latter strictly later than the former, and `starts_at` — the scheduled event start, which doubles as the bracket lock cutoff and must be greater than or equal to `registration_closes_at`. The fiscal envelope of the event is captured by `entry_fee_cents` (a non-negative integer per-participant entry fee), `settlement_currency` for both fees and payouts, `prize_pool_cents` (the total gross prize pool funded by the organizer), and `tax_withholding_pct` (two-decimal percentage applied to gross prize amounts; rejected with `ERR_TAX_OUT_OF_RANGE` if outside zero through fifty). Capacity bounds are set by `capacity_min` (at least 2) and `capacity_max` (no greater than 256 and at least as large as `capacity_min`). On creation the event sits in `DRAFT`, with derived fields `status`, `registered_count`, `prize_paid_total_cents`, and `posture` initialized to `DRAFT`, 0, 0, and `CLEAN` respectively.

Opening the event by the organizer transitions it from `DRAFT` to `OPEN`; the precondition is that the current time falls within the registration window — that is, `registration_opens_at` is at or before now and now is strictly before `registration_closes_at` — and that `capacity_max` is at least `capacity_min` and `capacity_min` is at least 2. Once `OPEN`, the system accepts registrations.

A registration is a POST under the event's `participants` collection submitted by an organizer, carrying `athlete_external_id` (the stable id from the governing-body roster), `display_name` (1–80 chars), `team_code` (exactly three uppercase letters or null for unaffiliated athletes), `country_code` (two-letter ISO), `world_ranking` (integer, lower being better; `null` is treated as worst), `region` (one of `AFC`, `CAF`, `CONCACAF`, `CONMEBOL`, `OFC`, `UEFA`), and `entry_fee_paid_cents`. Three things must be true at registration time: the registration window must be open (`registration_opens_at` at or before now and now strictly before `registration_closes_at`, otherwise `ERR_REGISTRATION_CLOSED`); `registered_count` must be strictly less than `capacity_max` (otherwise `ERR_CAPACITY_EXCEEDED`); and `entry_fee_paid_cents` must equal `entry_fee_cents` exactly — neither under nor overpayment is tolerated, with the rejection code `ERR_ENTRY_FEE_MISMATCH`. On success, the participant row is created with `status` `REGISTERED`, `bracket_seed` `null`, and prize accumulators `gross_prize_cents` and `net_prize_cents` and `final_rank` initialized to 0, 0, and `null` respectively. `Event.registered_count` increments and an outbox event of `kind` `ENTRY_FEE_CHARGED` is emitted to `PAYMENT`.

Registration closes either explicitly — by an organizer-driven transition from `OPEN` to `REGISTRATION_CLOSED` — or implicitly via a clock advance that crosses `registration_closes_at`. In both cases the precondition is that now is at or after `registration_closes_at`. After this transition, any further attempt to register a participant is rejected with `ERR_REGISTRATION_CLOSED`.

A participant's withdrawal is also possible. While the event is in `OPEN` or `REGISTRATION_CLOSED` and the participant is still `REGISTERED`, withdrawal flips the participant to `WITHDRAWN`, decrements `Event.registered_count`, and emits an outbox `ENTRY_FEE_CHARGED` event with a refund payload (the negative of `entry_fee_paid_cents`). When the event has already drawn and the participant is `SEEDED`, withdrawal is permitted only while the event itself is in `DRAWN` status; in that case every scheduled `Match` featuring the participant transitions to `VOIDED` (with the opponent treated as if drawing a bye), and every `RefereeAssignment` on those voided matches transitions to `REVOKED`.

### 3.2. The Draw, Seeding, and Bracket Generation

Once registration is closed and the field is set, the organizer triggers the draw to advance the event from `REGISTRATION_CLOSED` to `DRAWN`. The draw is gated by two preconditions: `registered_count` must be at least `capacity_min` (otherwise `ERR_REGISTRATION_BELOW_MIN`) and the event's `posture` must be `CLEAN` — that is, no `UNDER_REVIEW` or `FROZEN` gating is in effect. The draw runs the seeding algorithm deterministically across all `REGISTERED` participants at the moment of the call; late withdrawals processed before the draw lower the input set.

Seeding produces an integer `bracket_seed` from 1 to N, where N equals `registered_count`, by sorting participants ascending on a composite key. The first component of the key is a seeding-priority band: a participant whose `world_ranking` is non-null and at most 16 is in band 0; a participant whose `region` matches the host event's region (the region implied by the event's host `country_code`) is in band 1; everyone else is in band 2. Within a band, the second component is the negative of a per-participant ranking score: when `world_ranking` is non-null, the ranking score is 10000 minus `world_ranking` (so higher world ranks dominate); when `world_ranking` is `null`, the ranking score is 0. The third and final component, used only to break exact ties, is the participant's `id` in ascending UUID-lexicographic order. With seeds assigned in this sorted order, the system builds a single-elimination bracket of size two raised to the smallest integer power that is at least N; thus a 6-participant field uses a bracket of size 8, a 9-participant field uses 16, and so on, capped at the seeding constant of 256 maximum participants. Participants are paired so that seed 1 meets seed N, seed 2 meets seed N-1, and so on toward the middle of the bracket.

After the seed pairing is laid out, the avoidance pass scans first-round pairs left-to-right and refuses any pair whose two participants share a `team_code` or a `country_code`. On a conflict, the lower-seed slot of the conflicting pair is swapped with the next non-conflicting lower-seed participant downstream. The pass is single-sweep and deterministic. If a single sweep cannot resolve every first-round conflict, the draw aborts with `ERR_AVOIDANCE_INFEASIBLE`. When the field size N is strictly less than the bracket capacity, the top (capacity minus N) seeds receive byes in round 1: their `Match` rows are persisted with `away_participant_id` of `null` and a `status` of `BYE` at the moment of the draw transition, and their home participant moves from `SEEDED` to `ACTIVE` on the next round without playing a match.

The cascade on a successful draw is comprehensive: every `Participant` in `REGISTERED` advances to `SEEDED` and is assigned its `bracket_seed`; `Match` rows are created with `event_id`, `round_index` (starting at 1 for the first round, incremented for survivors even through bye rounds), `bracket_position` (1..N within the round), `home_participant_id` (the higher-seed participant), `away_participant_id` (the lower-seed participant, or `null` for a bye), `scheduled_start_at` and `scheduled_end_at` (assigned by the scheduling logic, with `scheduled_end_at` strictly later than `scheduled_start_at`), and an initial `status` of `SCHEDULED` (or `BYE` for bye rows whose `away_participant_id` is `null`); the locked-score and winner fields `locked_home_score`, `locked_away_score`, `locked_home_sets_won`, `locked_away_sets_won`, and `winner_participant_id` are initialized to `null`. Finally, a `SyncEvent` of `kind` `DRAW_ANNOUNCED` is emitted to `GOVERNING_BODY`.

The draw's scheduling layer must respect the participant time-conflict rule, which applies both at draw time and at any subsequent manual scheduling: the same participant cannot appear in two non-`VOIDED` matches whose `[scheduled_start_at, scheduled_end_at]` intervals overlap, and even adjacent intervals — where one match ends at the same instant the next begins — require a hard 30-minute gap before that participant can be rescheduled. Violations are rejected with `ERR_PARTICIPANT_TIME_CONFLICT`.

A draft event, an open event, or an event whose registration has closed may all be cancelled by the organizer. Cancellation from `DRAFT` is a status flip with no cascade. Cancellation from `OPEN` or `REGISTRATION_CLOSED` runs the same cascade in both cases: every participant in `REGISTERED`, `SEEDED`, or `ACTIVE` is converted to `WITHDRAWN`, and each such cascaded withdrawal itself emits a `ENTRY_FEE_CHARGED` outbox event to `PAYMENT` with a refund payload. Any `PrizePayment` rows that already exist and sit in `SCHEDULED` are cancelled to `CANCELLED` as part of the same cascade.

### 3.3. Referee Profiles and Match Assignment

A `Referee` is a separately-managed person record carrying `full_name`, `country_code`, `team_affiliation` (a three-letter team code or `null`), `qualifications` (a non-empty subset of the three event-type tokens `SINGLE_ELIM`, `ROUND_ROBIN`, `SETS_MATCH`), `grade` (one of `A`, `B`, or `C` with `A` highest), and `is_active` (defaulting to true; an inactive referee is never selected). Referees are created and listed by an organizer; the listing endpoint accepts an optional `qualification` filter and an optional `is_active` filter alongside pagination.

To officiate a match, the organizer creates a `RefereeAssignment` carrying the body fields `referee_id`, `role` (one of `HEAD`, `ASSISTANT`, `SUBSTITUTE`), and an optional `replaces_assignment_id` used when this row is a substitute activation that takes the place of an earlier assignment. The new row is persisted in `status` `ASSIGNED` and references the host `match_id` from the URL. Three cascading checks fire at assignment time, in this order: first, conflict-of-interest — the assignment is refused if the referee's `country_code` matches the country code of either of the match's participants, or if the referee's `team_affiliation` matches either participant's `team_code`, with the rejection code `ERR_CONFLICT_OF_INTEREST`; second, qualification — the assignment is refused if the referee's `qualifications` array does not include the event's `event_type`, with rejection code `ERR_REFEREE_NOT_QUALIFIED`; and third, scheduling — the assignment is refused if any other non-revoked assignment for the same referee covers an `[scheduled_start_at, scheduled_end_at]` interval that overlaps with this match's interval, with rejection code `ERR_REFEREE_TIME_CONFLICT`. The referee scheduling rule treats adjacent half-open intervals — where one match ends at the exact instant the next begins — as compatible without buffer; this is deliberately stricter than the participant scheduling rule of §3.2, which requires a 30-minute gap on adjacency.

An `ASSIGNED` row advances to `ACTIVATED` either automatically (when the match transitions to `RESULT_PENDING` upon first result entry) or explicitly by the organizer once the match's `scheduled_start_at` is at or before now. From either `ASSIGNED` or `ACTIVATED`, the organizer may revoke the assignment, transitioning it to `REVOKED`. While revocation is permitted from `ACTIVATED` unconditionally, revocation from `ASSIGNED` requires that the match itself be in `SCHEDULED` or `RESULT_PENDING`. When a revoked assignment held the `HEAD` or `ASSISTANT` role and a `SUBSTITUTE` row is queued on the same match, the system auto-promotes the substitute by creating a new `ASSIGNED` row with `replaces_assignment_id` set to the revoked assignment's `id`.

### 3.4. Result Submission, Cross-Verification, and Disputes

When the match's `scheduled_end_at` is at or before now and the event is not `FROZEN`, an `ACTIVATED` referee whose role is `HEAD` or `ASSISTANT` may submit a result. The submission body carries `submitted_by_assignment_id` (which must resolve to such a `RefereeAssignment` on this match), `home_score` and `away_score` (both non-negative integers), and, when the event's `event_type` is `SETS_MATCH`, `home_sets_won` and `away_sets_won`; a non-`SETS_MATCH` event leaves the sets-won fields `null`. The reported `kind` defaults to `REFEREE_SUBMISSION`; correction entries written by the dispute pathway carry `kind` `CORRECTION`.

The first valid `REFEREE_SUBMISSION` flips the match from `SCHEDULED` to `RESULT_PENDING` and persists the entry. The second submission, by a distinct referee, is the cross-verification step. Two checks run in this order on the second submission: first, the cross-verifying referee must be a distinct person from the first submitter — the second entry's `RefereeAssignment.referee_id` cannot equal the first entry's referee, and a violation is rejected with `ERR_DUPLICATE_REFEREE_ENTRY`; second, the second entry's `home_score` and `away_score` (and, for `SETS_MATCH`, its `home_sets_won` and `away_sets_won`) must equal the first entry's, and a disagreement is rejected with `ERR_RESULT_DISAGREEMENT`, with the match remaining in `RESULT_PENDING` and no dispute auto-opened. Both `home_score` and `away_score` are constrained to be non-negative.

When the second submission passes both checks, the match transitions from `RESULT_PENDING` to `LOCKED`. The locked scores are copied into `locked_home_score`, `locked_away_score`, and (for `SETS_MATCH`) `locked_home_sets_won` and `locked_away_sets_won`. The winner is computed and written to `winner_participant_id`. The cascade fires: the loser participant transitions from `ACTIVE` to `ELIMINATED`; the ranking calculation reruns and refreshes `points`, `goal_difference`, `away_goals`, `sets_won`, and `provisional_rank` on every applicable `RankingEntry`; and if a next-round `Match` exists, its `home_participant_id` or `away_participant_id` is set to the winner. A bye row is treated symmetrically: on event draw, when `away_participant_id` is `null`, the `Match` is persisted directly in `BYE` with `winner_participant_id` set to `home_participant_id` and the home participant scheduled to advance from `SEEDED` to `ACTIVE` on the next round.

Score validity for a `LOCKED` transition depends on the event's `event_type`. For `SINGLE_ELIM`, `home_score` and `away_score` must be unequal — exactly one side must win — otherwise the entry is rejected with `ERR_INVALID_SCORE`. For `ROUND_ROBIN`, equal scores are permitted (a draw). For `SETS_MATCH`, the entry is invalid if `home_sets_won` and `away_sets_won` are equal, or if either of those fields is `null`; both of those conditions are rejected with `ERR_INVALID_SCORE`. The score-validity check applies both to direct result submission and to the corrected scores supplied through a dispute uphold.

A participant may file a dispute on a match that is in `RESULT_PENDING` or `LOCKED` by submitting `filed_by_participant_id` and a `reason_text` between 1 and 1000 characters. The dispute is created in `OPEN`. If the match was `LOCKED` at the time of the filing, the match transitions to `DISPUTED` while preserving the snapshot of `locked_home_score`, `locked_away_score`, `locked_home_sets_won`, `locked_away_sets_won`, and `winner_participant_id` for restoration on a rejection. A `DisciplinaryOfficer` resolves an `OPEN` dispute by submitting a body carrying `uphold` (boolean) and, when uphold is true, the corrected scores `corrected_home_score`, `corrected_away_score`, and (for `SETS_MATCH`) `corrected_home_sets_won` and `corrected_away_sets_won`. A reject (uphold false) flips the dispute to `REJECTED` and the match back to `LOCKED` with the original snapshot restored. An uphold (uphold true) requires the corrected scores to satisfy the same `event_type` score-validity rule as a normal result submission; on success it persists a new `ResultEntry` of `kind` `CORRECTION`, sets the older `REFEREE_SUBMISSION` row's `superseded_by_id` to the new entry's `id`, writes a `RESULT_CHANGE` audit row whose `from_value` snapshots the old locked-score fields and whose `to_value` snapshots the new ones, updates the `locked_*` fields and possibly `winner_participant_id`, and on `Dispute` completion sets the dispute's `status` to `UPHELD` and `corrected_result_entry_id` to the id of the new `CORRECTION`. If the winner flips, the previously-active and previously-eliminated participants toggle states, and the ranking recomputes accordingly.

### 3.5. Ranking Calculation and Tie-Breaking

The system maintains a `RankingEntry` row per participant per event, carrying `event_id`, `participant_id`, the live aggregates `points`, `goal_difference`, `away_goals`, and `sets_won`, the live `provisional_rank`, and the (initially `null`) `final_rank`. The aggregates are computed across the set of `LOCKED` matches in the event in which the participant played one of the two sides. Withdrawn or disqualified participants are excluded from the ordering but their participated matches still contribute to opponents' aggregates; their `RankingEntry` rows are kept with `provisional_rank` of `null`.

The points formula varies by event type. For `SINGLE_ELIM`, a participant earns 3 points for each `LOCKED` match in which `winner_participant_id` is themselves and 0 otherwise. For `ROUND_ROBIN`, a participant earns 3 points for each match they win, 1 point for each match in which `locked_home_score` equals `locked_away_score` (a draw), and 0 otherwise. For `SETS_MATCH`, a participant accumulates the number of locked sets won on their side of each match — that is, `locked_home_sets_won` when they were the home side, or `locked_away_sets_won` when they were the away side. The team-game point constants are pinned at 3 points for a win and 1 point for a draw. Goal difference for a participant is the sum, over their `LOCKED` matches, of their own locked score minus their opponent's locked score (sign normalized to the participant's side). Away goals is the sum of locked scores recorded on the away side specifically, in matches where the participant was the away side. Sets won, populated only for `SETS_MATCH`, is the sum of locked sets won on the participant's side.

Ranks are produced by sorting participants ascending by a six-key sequence, taking the first non-tie key as the decisive one. The first key is the negative of `points` (more points wins); the second key is the negative of `goal_difference` (better difference wins); the third key, used only when comparing two specific tied peers, is the negative of head-to-head points — that is, the points the participant earned in their `LOCKED` matches against the peer alone; the fourth key is the negative of `away_goals` (more away goals wins); the fifth key is the negative of `sets_won` (more sets won wins), evaluated for `SETS_MATCH` events only and treated as zero for other event types but always evaluated in this slot regardless; and the sixth and last key is the participant's `id` in ascending UUID-lexicographic order, which always breaks any remaining tie deterministically. The tie-break depth is therefore six keys total. Keys four and five are evaluated in this strict order regardless of `event_type`.

The provisional variant runs on every match lock during `IN_PROGRESS`, populating `provisional_rank` and leaving `final_rank` `null`. The final variant runs once at the moment the event transitions from `IN_PROGRESS` to `COMPLETED` over the full set of `LOCKED` matches; at that instant `final_rank` is set equal to `provisional_rank`. Subsequent dispute corrections after completion never revise `final_rank` — only the audit log records the divergence.

### 3.6. Event Start, Completion, and Prize Calculation

The transition from `DRAWN` to `IN_PROGRESS` either fires when the organizer starts the event manually or via a clock advance crossing `starts_at`. Two preconditions hold: now is at or after `starts_at`, and every round-1 `Match` carries at least one `ASSIGNED` `RefereeAssignment` of role `HEAD`. On the transition every non-bye round-1 participant flips from `SEEDED` to `ACTIVE`.

An event reaches `COMPLETED` when an organizer triggers completion. Two preconditions hold: every non-bye `Match` in the event must be in `LOCKED` status, and there must be no `Dispute` whose `status` is `OPEN`. On completion the system runs the final-variant ranking calculation, sets each `RankingEntry.final_rank` to its current `provisional_rank`, copies that rank onto each participant's `final_rank` field, runs the prize calculation, and creates the corresponding `PrizePayment` rows.

The prize calculation distributes `Event.prize_pool_cents` across the top eight ranks by a tiered percentage schedule. Rank 1 receives 50% of the prize pool. Rank 2 receives 25%. Each of ranks 3 and 4 receives 10%. Each of ranks 5, 6, 7, and 8 receives 1.25%. Participants whose `final_rank` is greater than 8 receive 0.

The arithmetic is performed in integer minor-currency units to maintain exactness. For each ranked slot in turn — rank 1, then rank 2, then 3, 4, 5, 6, 7, 8 — the gross is computed by multiplying `prize_pool_cents` by the tier's percentage numerator, dividing by the tier's percentage denominator times 100, and rounding the resulting cents half-up. Any residual cent left over from rounding the eight allocations accumulates and is added to rank 1's allocation. After per-rank gross is fixed, the per-row tax withholding is computed: `tax_withheld_cents` is `gross_amount_cents` multiplied by `tax_withholding_pct` divided by 100, rounded half-up. Rounding order is pinned: per-rank gross first, per-row tax second.

The forfeiture rule applies after rounding. If a participant's `status` is `DISQUALIFIED`, or if any `SanctionRecord` whose `status` is `ISSUED` or `FINAL` exists for this participant in this event, then `forfeit_amount_cents` equals `gross_amount_cents` (a full forfeiture). Otherwise `forfeit_amount_cents` is 0. The net is the gross minus tax withheld minus forfeit, clamped at a non-negative floor of 0.

Each `PrizePayment` row carries `event_id`, `participant_id`, `gross_amount_cents`, `tax_withheld_cents`, `forfeit_amount_cents`, and `net_amount_cents`. Its `scheduled_pay_at` equals `Event.starts_at` plus 7 days (in seconds: 604800). The initial `status` is `SCHEDULED` for non-disqualified winners and `FORFEITED` for disqualified ones. For each `SCHEDULED` row, the system emits a `SyncEvent` of `kind` `PRIZE_PAID` to `PAYMENT` previewing the payout. The currency-denomination factor governs how minor units relate to major: `USD`, `EUR`, and `GBP` use 100; `JPY` uses 1.

A `SCHEDULED` `PrizePayment` advances to `PAID` automatically when the clock crosses `scheduled_pay_at`, provided the event's `posture` is `CLEAN`. The transition emits one `SyncEvent` of `kind` `PRIZE_PAID` to `PAYMENT` and a second of `kind` `PRIZE_PAID` to `IM` for the athlete-facing notice.

When a sanction is issued — either auto-issued from a positive doping result or manually — the system recomputes the affected `PrizePayment` rows under a distinct variant of the formula. The gross frozen at completion time is preserved as-is; the original tax withholding stays as-is; only the forfeiture flips, with `forfeit_amount_cents` set to `gross_amount_cents` and `status` to `FORFEITED`, and the net recomputed as gross minus the original tax minus the new forfeit. When a sanction is later revoked through a successful appeal, the cascade reverses: `forfeit_amount_cents` returns to 0, `net_amount_cents` is recomputed under the same gross-and-tax preservation rule, and `status` returns to `SCHEDULED`. This deliberate separation from the initial gross-first computation matters because re-running the gross-first variant on a partially-paid pool would produce different cents due to the rank-1 residual reallocation.

`Participant.gross_prize_cents` mirrors the gross prize accrued from the participant's `final_rank` and `Participant.net_prize_cents` mirrors the same row's net after tax and forfeitures. `Event.prize_paid_total_cents` is the sum of `PrizePayment.net_amount_cents` across rows whose `status` is `SCHEDULED` or `PAID`.

### 3.7. Doping Sampling, Custody, and Lab Results

A `DopingOfficer` opens a sampling-list entry under an event by submitting `participant_id` and `collected_at`. The new `DopingSample` row carries `event_id` (from the URL), the supplied `participant_id` and `collected_at`, an empty `chain_log`, an initial `status` of `COLLECTED`, and a `result_text` that defaults to `null`.

Chain-of-custody is recorded as an append-only log of entries. Each custody append carries `action` (`DISPATCH` for the dispatch leg of the chain, `RECEIVE` for the receipt leg) and an `at` timestamp. The append rule is strict monotonicity: the new entry's `at` must be strictly greater than the most-recent entry's `at` already in `chain_log`; an append with an `at` less than or equal to the prior tail is rejected with `ERR_CHAIN_OF_CUSTODY_BROKEN`. Each appended entry records the acting officer in its `actor_user_id` field (taken from `X-User-ID`) alongside the action and the `at`. A first dispatch advances the sample from `COLLECTED` to `IN_TRANSIT`. A subsequent receive advances it from `IN_TRANSIT` to `RECEIVED`. While a sample is `COLLECTED`, the doping officer may also void it administratively, transitioning to `VOIDED`.

Once a sample is `RECEIVED`, the lab result is recorded by submitting a body carrying `positive` (boolean) and an optional `result_text` (the lab finding free-text). Segregation-of-duties is enforced at this point: the same `DopingOfficer` (compared by `X-User-ID`) who appended the `RECEIVE` custody entry is forbidden from submitting the lab result, with the rejection code `ERR_SEGREGATION_OF_DUTIES`. A negative result transitions the sample to `NEGATIVE` with no further side effect. A positive result transitions the sample to `POSITIVE` and triggers a wide cascade.

The positive cascade fires the following side effects atomically. A `SanctionRecord` is auto-created with `sample_id` set to this sample's id, `participant_id` denormalized from the sample's participant, and `status` `ISSUED`; its `prize_forfeited_cents` is a snapshot of the participant's existing `PrizePayment.gross_amount_cents` (or 0 if no `PrizePayment` row yet exists for this participant). The participant's `status` flips from `ACTIVE` to `DISQUALIFIED`. Every future `Match` featuring this participant transitions to `VOIDED`. Every existing `PrizePayment` for this participant with `status` `SCHEDULED` flips to `FORFEITED` with `forfeit_amount_cents` equal to `gross_amount_cents` and `net_amount_cents` set to 0. The ranking recomputes with this participant excluded from ordering. An `AuditLog` row of `kind` `SANCTION_CHANGE` is written. Finally, the event's `posture` recomputes per the rule in §2.8 — at this moment the new sanction is `ISSUED`, so the posture flips to `UNDER_REVIEW`.

### 3.8. Sanctions, Appeals, and the 14-Day Window

A `SanctionRecord` carries `sample_id`, `participant_id`, `ban_months` (an integer from 1 to 120 inclusive), `prize_forfeited_cents`, and a `status` that is one of `ISSUED`, `APPEALED`, `FINAL`, or `REVOKED` (with `ISSUED` initial and `FINAL`/`REVOKED` terminal). A participant may file an `Appeal` against the sanction within a strict 14-day window measured from the sanction's `created_at`. The appeal payload carries `sanction_id` and `ground_text` (1–2000 characters); the `filed_by_user_id` must equal `SanctionRecord.participant_id`. The window is inclusive on the closing edge: an appeal filed at the instant `now()` equals `created_at + 14 days` is still accepted; the system `FINAL` transition runs only when `now()` is strictly later than that instant. A late appeal, where `now()` is strictly later than `created_at + 14 days`, is rejected with `ERR_APPEAL_WINDOW_CLOSED`.

Filing an appeal moves the sanction from `ISSUED` to `APPEALED`. The cascade flips the event's `posture` to `FROZEN` (because per §2.8 any `APPEALED` sanction freezes the event), and writes an `AuditLog` of `kind` `SANCTION_CHANGE`.

The `AppealsBoard` resolves the appeal by submitting `uphold` (boolean). On uphold false (the appeal is dismissed) the appeal flips to `DISMISSED`, the sanction transitions from `APPEALED` to `FINAL`, the event's `posture` is recomputed (without an `APPEALED` sanction it returns to `UNDER_REVIEW` unless other open sanctions exist), and an `AuditLog` of `kind` `SANCTION_CHANGE` is written. On uphold true (the appeal is granted) the appeal flips to `UPHELD` and the sanction transitions from `APPEALED` to `REVOKED`. The cascade on a revoke is the reverse of the issuance cascade: the participant's status returns from `DISQUALIFIED` to `ELIMINATED` if the event is already `COMPLETED`, otherwise to `ACTIVE`; any `PrizePayment` in `FORFEITED` returns to `SCHEDULED` with `forfeit_amount_cents` set to 0 and `net_amount_cents` recomputed from the preserved gross and original tax (per §3.6's variant rule); the event's `posture` is recomputed (with neither an `APPEALED` nor an `ISSUED` sanction outstanding for this sample, posture returns to `CLEAN` if all is clear); and an `AuditLog` of `kind` `SANCTION_CHANGE` is written.

If no appeal is filed, the system advances the sanction from `ISSUED` to `FINAL` automatically when the clock crosses `created_at + 14 days` and no `Appeal` exists. The cascade recomputes the event's `posture` and emits a `SyncEvent` of `kind` `SANCTION_ARCHIVED` to `GOVERNING_BODY`.

### 3.9. Audit and Outbox Visibility

Audit log listings, scoped by `kind`, `subject_kind`, and `subject_id` query filters with the standard `limit` and `offset`, are accessible to organizers, disciplinary officers, and the appeals board. Outbox event listings, scoped by `target_system` and `kind`, are accessible to organizers. Both views are read-only; the entries themselves are written exclusively by the cascades described in §3.4, §3.7, and §3.8 and the prize-payment payouts of §3.6.

## 4. Endpoint Definitions

Endpoints that introduce a new top-level resource (an event, a participant, a referee, a referee assignment, a result entry, a dispute, a doping sample, an appeal) return `201 Created`. Endpoints that mutate an existing resource (every state transition, custody append, lab result, dispute resolution, appeal decision, clock advance, sweep, and every list/get) return `200 OK`. Read endpoints likewise return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/events` | Create a new event in `DRAFT`. | Organizer |
| GET | `/events/{event_id}` | Read a single event. | Organizer, Referee, Participant, DisciplinaryOfficer, DopingOfficer, AppealsBoard |
| GET | `/events` | List events with optional filtering by status and country code. | Organizer, Referee, Participant, DisciplinaryOfficer, DopingOfficer, AppealsBoard |
| POST | `/events/{event_id}/open` | Transition event from `DRAFT` to `OPEN`. | Organizer |
| POST | `/events/{event_id}/close-registration` | Transition event from `OPEN` to `REGISTRATION_CLOSED` (manual override). | Organizer |
| POST | `/events/{event_id}/draw` | Transition event from `REGISTRATION_CLOSED` to `DRAWN`; runs bracket seeding. | Organizer |
| POST | `/events/{event_id}/start` | Transition event from `DRAWN` to `IN_PROGRESS`. | Organizer |
| POST | `/events/{event_id}/complete` | Transition event from `IN_PROGRESS` to `COMPLETED`; computes final ranking and prize payments. | Organizer |
| POST | `/events/{event_id}/cancel` | Cancel event from `DRAFT`, `OPEN`, or `REGISTRATION_CLOSED`. | Organizer |
| POST | `/events/{event_id}/participants` | Register a participant under the event. | Organizer |
| GET | `/events/{event_id}/participants` | List participants for an event. | Organizer, Referee, Participant, DisciplinaryOfficer, DopingOfficer |
| POST | `/participants/{participant_id}/withdraw` | Withdraw a participant. | Organizer |
| POST | `/referees` | Create a referee profile. | Organizer |
| GET | `/referees` | List referees with optional qualification and active filters. | Organizer |
| POST | `/matches/{match_id}/referee-assignments` | Assign a referee to a match. | Organizer |
| POST | `/referee-assignments/{assignment_id}/activate` | Activate an assigned referee. | Organizer |
| POST | `/referee-assignments/{assignment_id}/revoke` | Revoke a referee assignment. | Organizer |
| GET | `/events/{event_id}/matches` | List matches for an event. | Organizer, Referee, Participant, DisciplinaryOfficer |
| POST | `/matches/{match_id}/results` | Referee submits a result; cross-verification gates lock. | Referee |
| POST | `/matches/{match_id}/disputes` | Participant files a dispute on a match. | Participant |
| POST | `/disputes/{dispute_id}/resolve` | Officer upholds (with optional corrected scores) or rejects a dispute. | DisciplinaryOfficer |
| POST | `/events/{event_id}/doping-samples` | Open a sampling-list entry for a participant. | DopingOfficer |
| POST | `/doping-samples/{sample_id}/custody` | Append a chain-of-custody entry. | DopingOfficer |
| POST | `/doping-samples/{sample_id}/result` | Submit lab result (positive or negative). | DopingOfficer |
| POST | `/doping-samples/{sample_id}/void` | Void a doping sample administratively. | DopingOfficer |
| GET | `/sanctions/{sanction_id}` | Read a sanction record. | DisciplinaryOfficer, AppealsBoard, Participant |
| POST | `/appeals` | Participant files an appeal against a sanction. | Participant |
| POST | `/appeals/{appeal_id}/decide` | Appeals board upholds or dismisses an appeal. | AppealsBoard |
| GET | `/events/{event_id}/rankings` | Read provisional or final rankings. | Organizer, Referee, Participant, DisciplinaryOfficer |
| GET | `/events/{event_id}/prize-payments` | List prize payments for an event. | Organizer, Participant, DisciplinaryOfficer |
| GET | `/audit-logs` | List audit log entries. | Organizer, DisciplinaryOfficer, AppealsBoard |
| GET | `/sync-events` | List outbox events. | Organizer |
| POST | `/_clock/advance` | Advance the logical clock to a supplied instant. | Organizer |
| POST | `/_sweep/run` | Run all idempotent system sweeps once. | Organizer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVENT_FROZEN` | 409 |
| `ERR_REGISTRATION_CLOSED` | 409 |
| `ERR_REGISTRATION_BELOW_MIN` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_AVOIDANCE_INFEASIBLE` | 422 |
| `ERR_INVALID_SCORE` | 422 |
| `ERR_DUPLICATE_REFEREE_ENTRY` | 409 |
| `ERR_RESULT_DISAGREEMENT` | 409 |
| `ERR_REFEREE_NOT_QUALIFIED` | 422 |
| `ERR_CONFLICT_OF_INTEREST` | 422 |
| `ERR_REFEREE_TIME_CONFLICT` | 409 |
| `ERR_PARTICIPANT_TIME_CONFLICT` | 409 |
| `ERR_ENTRY_FEE_MISMATCH` | 422 |
| `ERR_TAX_OUT_OF_RANGE` | 422 |
| `ERR_CHAIN_OF_CUSTODY_BROKEN` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 422 |
