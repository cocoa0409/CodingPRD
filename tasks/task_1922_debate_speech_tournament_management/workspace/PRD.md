# Debate & Speech Tournament Management API — Product Requirements Document

## 1. Introduction

Running an NSDA district tournament is an exercise in constrained allocation under deadline pressure. Schools register entries into event divisions, and every confirmed entry creates a judging debt: the tournament cannot begin unless each school covers its share of preliminary judging, whether by committing its own judges or by purchasing hired judge-rounds from a limited pool. Tabulation staff must then generate conflict-free pairings, collect and verify ballots under time pressure, compute standings with exacting tie-break discipline, and break the right field into elimination brackets — all while the tournament director drives the event through its phases and keeps the books balanced. Today this work lives in spreadsheets and hallway negotiations; mistakes in obligation math, pairing feasibility, or ballot handling surface hours later, when they are hardest to repair.

This document specifies an API that runs that entire operation as a single, consistent system. Registration posture gates everything: a school may confirm only when its judging obligation is fully covered, the tournament may lock registration only when every school is confirmed and satisfied, prelims may start only when rounds are scheduled, elims only when every preliminary round is tabulated and every bracket is determined, and results may be published only after completion and certified only after every hired-judge contract is settled. Two event families — debate and speech — share the platform but differ in pairing format, ballot content, scoring arithmetic, and advancement rules, and this specification keeps those differences exact. Optimistic concurrency controls protect the three highest-stakes writes (registration lock, pairing generation, and hired-round purchase) so that no operator acts on a registration graph that has moved since they last read it, and a strict segregation of duties separates the director, who owns configuration and phases, from the tabulation staff, who own pairings and ballot verification.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. The system recognizes exactly four roles: `TournamentDirector`, `TabStaff`, `SchoolCoach`, and `Judge`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once authenticated, a request whose role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `TournamentDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `TabStaff`. When `X-User-Role` is `SchoolCoach`, `X-User-ID` is the `id` of the acting `School`; ownership checks on any resource that references a school compare the resource's school foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting `Judge`; for ballot writes the pairing's assigned `judge_id` must equal `X-User-ID`, and a mismatch is likewise rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH`.

Duties are segregated. A `TournamentDirector` owns tournament configuration, phase transitions, rooms, logistics, hired-judge procurement and dispute resolution, but cannot verify or void ballots. `TabStaff` owns rounds, pairing generation, room and judge assignment, ballot verification and voiding, and break determination, but cannot drive tournament phases or publish results. A `SchoolCoach` manages the entries, judges, judge conflicts, and hired-judge contracts of their own school only. A `Judge` creates, submits, and recalls ballots only for pairings assigned to them; verification of any ballot is performed by `TabStaff`, never by the judge who submitted it.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless a more specific ordering is stated for a particular listing, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource — Tournament, School, EventDivision, Entry, Judge, Room, Round, Pairing, Ballot, HiredJudgeContract, and LogisticsOrder — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on any change to the resource's properties. `version` is a system-managed integer that increments by one on every mutation of the resource, including mutations caused by derived-field recomputation and cascade side effects initiated elsewhere.

Two resources are deliberately lighter. A `JudgeConflict` record and a `PairingEntry` record carry only `id` and `created_at`; both `updated_at` and `version` are absent on these two resources.

Version propagation is hierarchical: a mutation deep in the registration graph refreshes `updated_at` and increments `version` on every entity it touches. For example, confirming an entry increments the owning school's `version`, and any school-level mutation in turn increments the parent tournament's `version`. Clients that hold a previously read `version` must expect it to advance whenever such cascades occur.

### 2.5. The Logical Tournament Clock

Every temporal gate in the system reads a single logical UTC clock, never wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any explicit set operation the clock continues to read this default rather than falling back to wall-clock time. A `TournamentDirector`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; this operation mutates no entity.

Three windows are keyed to this clock. Opening registration requires the current logical UTC to be at or after the tournament's `registration_opens_at`, otherwise the request fails with `ERR_REGISTRATION_WINDOW_NOT_OPEN` (HTTP 409). Locking registration requires the current logical UTC to be at or after `registration_locks_at`, otherwise it fails with `ERR_REGISTRATION_WINDOW_CLOSED` (HTTP 409). Submitting a ballot requires the current logical UTC to be at or before the round's `ends_at` plus a grace period of 60 minutes, otherwise it fails with `ERR_BALLOT_WINDOW_CLOSED` (HTTP 409).

### 2.6. Optimistic Concurrency Control on the Registration Graph

Exactly three write operations carry an optimistic-concurrency expectation field, and no other endpoint accepts a version field.

Locking registration requires the request body to carry `expected_tournament_version` equal to the tournament's current `version`. Locking snapshots every school's obligation and coverage; if the tournament's `version` has advanced since the caller last observed it — because entries, judges, contracts, or school confirms have mutated — the snapshot basis is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Generating pairings for a round requires `expected_round_version` equal to the round's current `version`. If the round's `version` has advanced since the caller last observed it — for example because a ballot void reopened the round and recomputed entry statistics — the caller's standings and staffing view predates the latest mutation, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a hired-judge contract requires `expected_school_version` equal to the school's current `version`. The purchase is sized against the school's current shortfall; if the school's `version` has advanced since the caller last read it — an entry confirmed or withdrawn, a judge committed, another contract filled — the purchase basis is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The concurrency check is evaluated before any entity-state precondition on the same request, so a stale view is always reported as HTTP 412 rather than being masked by a 409 state error.

### 2.7. Validation Order and Priority

Every request is validated in a fixed pipeline order, and earlier failures mask later ones. First, the presence and validity of the authentication headers is checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the acting role is checked against the endpoint's role list (`ERR_FORBIDDEN`). Third, for `SchoolCoach` and `Judge` write endpoints, ownership is checked (`ERR_RESOURCE_OWNERSHIP_MISMATCH`). Fourth, the existence of every resource identifier in the path and body is validated left-to-right — path parameters first, then body fields in input order — and the first missing identifier produces its resource-specific not-found error: `ERR_TOURNAMENT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_JUDGE_CONFLICT_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_ROUND_NOT_FOUND`, `ERR_PAIRING_NOT_FOUND`, `ERR_PAIRING_ENTRY_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`, each at HTTP 404.

Fifth, the tournament phase gate is evaluated (`ERR_TOURNAMENT_PHASE_FORBIDDEN`, HTTP 409): writes into the registration graph are allowed only while the tournament is `REGISTRATION_OPEN`, pairing and tabulation operations only in their matching phase, and result publication only from `COMPLETED`. Sixth, the optimistic-concurrency expectation is compared (`ERR_STALE_VERSION`), always before entity-state checks as stated in §2.6. Seventh, entity-state preconditions and aggregate gates are evaluated: the per-entity state errors `ERR_SCHOOL_INVALID_STATE`, `ERR_ENTRY_INVALID_STATE`, `ERR_JUDGE_INVALID_STATE`, `ERR_ROUND_INVALID_STATE`, `ERR_PAIRING_INVALID_STATE`, `ERR_BALLOT_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`, and `ERR_ORDER_INVALID_STATE`, plus the aggregate gates `ERR_SCHOOLS_NOT_LOCK_READY`, `ERR_ROUNDS_NOT_SCHEDULED`, `ERR_ROUNDS_NOT_TABULATED`, `ERR_BREAKS_NOT_DETERMINED`, `ERR_UNPAID_CONTRACTS_REMAIN`, and `ERR_INSUFFICIENT_BREAK_CANDIDATES`, all at HTTP 409.

Business-rule checks then run in their own pinned relative order where several guard the same operation. When a judge is assigned to a pairing, the conflict-of-interest check (`ERR_JUDGE_CONFLICT_OF_INTEREST`) is evaluated before the buffered turnover check (`ERR_JUDGE_TURNOVER_CONFLICT`), so a conflicted judge is always reported as a conflict rather than a scheduling clash. Structural caps and uniqueness checks outrank fiscal checks: where both could apply, an entry-cap rejection (`ERR_SCHOOL_ENTRY_CAP_EXCEEDED`) is reported before a credit-ceiling rejection (`ERR_CREDIT_LIMIT_EXCEEDED`). On ballot writes, the low-point-win flag check (`ERR_LOW_POINT_WIN_NOT_FLAGGED`) outranks the per-field validity checks (`ERR_SPEAKER_POINTS_OUT_OF_RANGE`, `ERR_RANK_INVALID`, `ERR_DUPLICATE_RANK_IN_SECTION`, `ERR_WINNER_NOT_IN_PAIRING`).

### 2.8. Cross-Tournament Referential Integrity

Every entity referenced by an operation — school, division, entry, judge, room, round, pairing, contract, or logistics order — must belong to the same tournament as the operation's context. A request that mixes references across two tournaments is rejected with `ERR_CROSS_TOURNAMENT_REFERENCE` (HTTP 409). Existence (§2.7, step four) is validated before this integrity check, so a reference to a non-existent resource produces the resource's 404 rather than a cross-tournament rejection.

### 2.9. Monetary Precision, Rounding, and Pinned Arithmetic Order

All monetary values are integer cents; no fractional cents exist anywhere in the system. Where a calculation produces a non-integer — the per-entry late surcharge and the volume discount — the result is rounded to the nearest whole cent using round half up.

Two rounding orders are pinned and must not be reordered. The late-entry surcharge is computed and rounded per entry at the moment that entry is confirmed, and only then summed into the school's fee subtotal; summing base fees first and applying the surcharge to the sum is forbidden because it yields a different total. The volume discount is rounded per component — entry fees and judge fees are each multiplied by the tier percentage and rounded half up independently, then summed; rounding the combined discount amount is forbidden. The discount tier is selected on the pre-discount subtotal, and the selected tier does not change even though applying the discount may drop the final total below the threshold that selected it. Hired-judge fees use whole-cent rates and therefore require no rounding.

### 2.10. Parallel Tournament Axes and Cascade Consistency

A tournament carries two independent state axes. The phase axis `status` walks `DRAFT` → `REGISTRATION_OPEN` → `REGISTRATION_LOCKED` → `PRELIMS_ACTIVE` → `ELIMS_ACTIVE` → `COMPLETED`. The results axis `results_visibility` walks `HIDDEN` → `PUBLISHED` → `CERTIFIED`. They evolve independently: transitions on the results axis are gated on particular `status` values, but a results-axis transition never mutates `status`, and a phase transition never mutates `results_visibility`.

The system maintains hierarchical consistency automatically. Derived fields on a school — its obligation, coverage, shortfall, obligation posture, and invoice balance — are reconciled immediately whenever the underlying registration graph mutates: an entry confirmed or withdrawn, a judge committed or withdrawn, a contract filled, accepted, paid, cancelled, or auto-released. Likewise, entry statistics are recomputed whenever a round is tabulated or a verified ballot is voided. Where criteria on a related resource are satisfied or violated, the server transitions that resource itself — pairings become staffed or revert, a tabulated round reopens when a ballot is voided, entries cascade into competition when prelims start — without requiring an explicit client request on that specific resource. Every such reconciliation independently refreshes `updated_at` and increments `version` on each entity it touches, per §2.4.

## 3. Business Logic & Workflows

### 3.1. Tournament Configuration, Divisions, and Rooms

A `TournamentDirector` creates a tournament by supplying a `name` and the two registration window instants, `registration_opens_at` and `registration_locks_at`. Optional configuration includes `prelim_round_count` (default 4, an integer between 2 and 6 inclusive), `entry_fee_cents` (default 2500, never negative), `tournament_staff_count` (default 10, never negative), `late_fee_starts_at` (optional, absent by default), and `late_fee_surcharge_pct` (default 0.15, meaning a fifteen percent surcharge). A new tournament is born with `status` `DRAFT` and `results_visibility` `HIDDEN`. The `prelim_round_count` is not decorative: it is the multiplier in the judge-obligation calculation, it determines the break win threshold, and it bounds how many rounds a school-provided judge may commit to.

Within a tournament, the director creates event divisions. Each division carries an `event_type` of `DEBATE` or `SPEECH`, an `event_code`, and a `division` level of `VARSITY`, `JV`, or `NOVICE`. The `event_code` must belong to the family of its `event_type`: debate codes are `CX`, `LD`, and `PF`, while speech codes are `OO`, `EXT`, and `INF`; a code outside the family is rejected with `ERR_EVENT_CODE_TYPE_MISMATCH` (HTTP 422). Each division also carries two caps. The `per_school_entry_cap` (default 4, at least 1) limits how many non-withdrawn entries one school may hold in the division, and the `global_entry_cap` (default 32, at least 1) limits the division-wide non-withdrawn total. The derived `competing_entry_count` tracks how many of the division's entries currently sit in `COMPETING`, `ADVANCED`, `ELIMINATED`, or `FINISHED`, and `bracket_size` remains unset until breaks are determined — once set, it is always a power of two between 2 and 16 inclusive.

Rooms are created per tournament with a `name` and a `capacity` (default 30, at least 1). Capacity is informational; the system never rejects an assignment on capacity grounds. The divisions listing can be filtered by `tournament_id` and `event_type`, the rooms listing by `tournament_id`, and the schools listing by `tournament_id` and `status`.

When configuration is complete and the logical clock has reached `registration_opens_at`, the director opens registration, moving the tournament `DRAFT` → `REGISTRATION_OPEN`. Attempting this from any other phase yields `ERR_TOURNAMENT_PHASE_FORBIDDEN`; attempting it before the window yields `ERR_REGISTRATION_WINDOW_NOT_OPEN`. The transition increments the tournament's `version`.

### 3.2. Schools, Entries, Judges, and the Obligation Market

Schools join a tournament when the director registers one with the tournament's `tournament_id`, a school `name`, and an optional `credit_limit_cents` ceiling; when the ceiling is absent, the school's spending is unlimited. A school is born `REGISTERED` with all derived figures at rest: `confirmed_entry_count` 0, `judge_obligation_rounds` 0, `covered_judge_rounds` 0, `shortfall_rounds` 0, `obligation_status` `SATISFIED`, and `invoice_balance_cents` 0.

With registration open, a `SchoolCoach` creates entries for their own school by providing the `school_id`, the target `division_id`, and a `competitor_name`. Entry creation is a registration-graph write, so it is permitted only while the tournament is `REGISTRATION_OPEN`. Both caps are enforced at creation against counts of non-`WITHDRAWN` entries: creation is allowed only while the school's current count in the division is strictly below `per_school_entry_cap`, otherwise `ERR_SCHOOL_ENTRY_CAP_EXCEEDED` (HTTP 409), and only while the division-wide count is strictly below `global_entry_cap`, otherwise `ERR_DIVISION_GLOBAL_CAP_REACHED` (HTTP 409). A new entry is born `REGISTERED` with `wins`, `losses`, `speaker_points_raw`, `speaker_points_adjusted`, `rank_points_raw`, `rank_points_adjusted`, and `opponent_strength` all 0, `prelim_rank` unset until the first tabulation, `has_received_bye` false, `seed` and `final_placement` and `qualification_points` unset, and `fee_charged_cents` 0. The entries listing can be filtered by `school_id`, `division_id`, and `status`.

Confirming an entry moves it `REGISTERED` → `CONFIRMED`, and a withdrawn entry may be re-confirmed on the same path (`WITHDRAWN` → `CONFIRMED`, a pre-lock-only cycle in which the fee is charged again). Confirm requires the tournament to be `REGISTRATION_OPEN` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and the entry to be in `REGISTERED` or `WITHDRAWN` (otherwise `ERR_ENTRY_INVALID_STATE`). At confirm time the entry's `fee_charged_cents` is computed: the base is the tournament's `entry_fee_cents`, and if `late_fee_starts_at` is set and the current logical UTC is at or after it, the charged fee is the base multiplied by one plus `late_fee_surcharge_pct`, rounded half up to a whole cent; otherwise the charged fee is the base. This rounding happens per entry at confirm time, before any summation, per §2.9. The recorded fee is an audit trail on the entry; the school's invoice includes it only while the entry's status is non-`WITHDRAWN`.

Confirm is also fiscally gated. If the school has a `credit_limit_cents` ceiling, the projected `invoice_balance_cents` after this confirm must not exceed it, otherwise the confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). On success, the school's `confirmed_entry_count`, `judge_obligation_rounds`, `shortfall_rounds`, `obligation_status`, and `invoice_balance_cents` are recomputed, the school's `version` increments, and the tournament's `version` increments as well.

The judge obligation is the heart of the quota market. For each division of the tournament, count the school's entries in `CONFIRMED`, `COMPETING`, `ADVANCED`, `ELIMINATED`, or `FINISHED`; a division with zero such entries is skipped. A debate division demands one judge per two such entries, rounded up to a whole judge; a speech division demands one judge per five such entries, rounded up. Each division's judge count is multiplied by the tournament's `prelim_round_count`, and the products sum to the school's `judge_obligation_rounds`. The ceiling is applied per division before the multiplication, never to the aggregate.

Schools cover the obligation with judges. A coach (or the director) registers a school-provided judge with the `tournament_id`, the `school_id`, and a `name`; for a coach, the `school_id` must equal their own school. A new judge is born `REGISTERED` with `judge_type` `SCHOOL_PROVIDED`, `commitment_rounds` 0, and `assigned_round_count` 0. Committing a judge moves them `REGISTERED` → `COMMITTED` and is allowed only while the tournament is `REGISTRATION_OPEN`; the judge must currently be `REGISTERED` (otherwise `ERR_JUDGE_INVALID_STATE`), and the supplied `commitment_rounds` must be between 1 and the tournament's `prelim_round_count` inclusive (otherwise `ERR_COMMITMENT_ROUNDS_INVALID`, HTTP 422). Withdrawing a judge moves `REGISTERED` → `WITHDRAWN` or `COMMITTED` → `WITHDRAWN`, again only while registration is open; withdrawing a committed judge drops the school's coverage by that judge's `commitment_rounds`. Coverage, shortfall, and posture recomputed on either action increment the school's `version` and touch the tournament's `version`.

A school's `covered_judge_rounds` is the sum of `commitment_rounds` over its `COMMITTED`, school-provided judges plus the `rounds_active` of its hired-judge contracts in `FILLED`, `CONFIRMED`, `DISPUTED`, or `PAID`. The `shortfall_rounds` is the amount by which `judge_obligation_rounds` exceeds `covered_judge_rounds`, never below zero; `obligation_status` is `SATISFIED` exactly when the shortfall is zero and `DEFICIENT` otherwise. A school read reflects these values recomputed as of the read.

Conflicts of interest are recorded as `JudgeConflict` rows by a coach or `TabStaff`, carrying the `judge_id`, the `school_id` whose entries the judge may not be assigned to, and an optional free-text `reason`. These records carry only `id` and `created_at` (§2.4), and their listing filters by `judge_id` and `school_id`. The judges listing filters by `tournament_id`, `school_id`, `judge_type`, and `status`.

A coach confirms their school — `REGISTERED` → `CONFIRMED` — only while the tournament is `REGISTRATION_OPEN`, only from `REGISTERED` (otherwise `ERR_SCHOOL_INVALID_STATE`), and only when the school's `obligation_status` is `SATISFIED` (otherwise `ERR_SCHOOL_OBLIGATION_DEFICIENT`, HTTP 409). Unconfirming reverses it to `REGISTERED` under the same phase gate. Both transitions increment the school's `version` and the tournament's `version`.

Withdrawing an entry (`CONFIRMED` → `WITHDRAWN`) is possible only before the lock, because it is a registration-graph write gated on `REGISTRATION_OPEN`; from any other entry state it yields `ERR_ENTRY_INVALID_STATE`. Withdrawal fires a three-link cascade. First, the entry leaves the invoice status set, so the school's `confirmed_entry_count` and `judge_obligation_rounds` are recomputed and the school's `version` increments. Second, the reduced obligation may leave the school with surplus hired coverage: the surplus is drained from the school's contracts in `REQUESTED` or `CONFIRMED` status, most recently created first, increasing each affected contract's `rounds_released` (never beyond its `rounds_requested`, so active rounds never fall below zero) and recomputing its fees; a `REQUESTED` contract drained to zero active rounds is automatically `CANCELLED`. Third, the contract fee changes feed a fresh recomputation of the school's `invoice_balance_cents`, with another `version` increment. The tournament's `version` increments as well.

When every school is confirmed and satisfied, the director locks registration: `REGISTRATION_OPEN` → `REGISTRATION_LOCKED`. The lock requires the logical clock to be at or after `registration_locks_at` (otherwise `ERR_REGISTRATION_WINDOW_CLOSED`), requires every school of the tournament to be `CONFIRMED` with `obligation_status` `SATISFIED` (otherwise `ERR_SCHOOLS_NOT_LOCK_READY`), and carries the `expected_tournament_version` concurrency field per §2.6. Locking snapshots each school's `judge_obligation_rounds` for coverage evaluation from that point on; entries can no longer be confirmed or withdrawn. The transition increments the tournament's `version`.

### 3.3. Hired Judges: Contracts, Tiered Fees, and the School Invoice

When a school cannot cover its obligation with its own judges, its coach purchases hired judge-rounds by creating a contract with the `school_id`, the `rounds_requested`, and the `expected_school_version` concurrency field per §2.6. The purchase must be sized against the live shortfall: `rounds_requested` must be at least 1 and at most the school's current `shortfall_rounds`, otherwise the create is rejected with `ERR_HIRED_ROUNDS_EXCEED_SHORTFALL` (HTTP 422). A new contract is born `REQUESTED` with `rounds_released` 0, `hired_judge_id` unset, and `final_fee_cents` unset; its `rounds_active` is always `rounds_requested` minus `rounds_released`. Creating a contract increments the school's `version` and the tournament's `version`.

Pricing is tiered and chronological. At creation, `fee_quote_cents` is computed under the provisional-quote variant: consider every contract of the tournament in `REQUESTED`, `FILLED`, `CONFIRMED`, `DISPUTED`, or `PAID`, ordered by `created_at` ascending with ties broken by `rounds_requested` ascending, never by `id`. For a contract in that ordering, let the preceding load be the sum of `rounds_requested` over all contracts earlier in the ordering. The contract's premium rounds are the lesser of its own `rounds_requested` and the amount by which the preceding load plus its own `rounds_requested` exceeds 8 rounds, and never less than zero; the remainder of its rounds are base rounds. The fee is base rounds times 5000 cents plus premium rounds times 7500 cents. Because the provisional candidate set includes other schools' still-`REQUESTED` contracts, the quote can price some rounds at the premium rate that the final fee prices at base once those earlier requests never fill.

The final fee is computed under the final-invoice variant — same tiered formula, but the candidate set excludes `REQUESTED` contracts. It is produced when the school accepts the contract and is recomputed whenever the contract's rounds change through auto-release; it is frozen onto `final_fee_cents` and feeds the school invoice.

The director fills a `REQUESTED` contract — `REQUESTED` → `FILLED`, from any other state `ERR_CONTRACT_INVALID_STATE` — by providing a `judge_name`. Filling creates a `HIRED` judge directly in `COMMITTED` status, with `commitment_rounds` equal to the contract's `rounds_requested` (which may exceed `prelim_round_count`; the commitment ceiling applies only to school-provided commits), with no school affiliation (`school_id` is null), and records it as the contract's `hired_judge_id`. The school's `covered_judge_rounds` rises by the contract's `rounds_active`, shortfall and posture are recomputed, and both the school's and the tournament's `version` increment.

The coach then accepts the filled contract — `FILLED` → `CONFIRMED` — which computes `final_fee_cents` under the final-invoice variant and recomputes the school's invoice, incrementing both versions. From `CONFIRMED` the coach may dispute the contract (`CONFIRMED` → `DISPUTED`), and the director may resolve the dispute (`DISPUTED` → `CONFIRMED`, a cycle); both actions increment the school's `version` and change no fees, and a `DISPUTED` contract continues to count toward both coverage and the invoice. Paying a `CONFIRMED` contract moves it to `PAID` and subtracts its `final_fee_cents` from the school's `invoice_balance_cents`, incrementing both versions. The director may cancel a `REQUESTED` contract (`REQUESTED` → `CANCELLED`, manual cancel from any other state yields `ERR_CONTRACT_INVALID_STATE`), and the withdrawal cascade of §3.2 can cancel a drained `REQUESTED` contract automatically; either path recomputes the school's coverage and invoice and touches the tournament's `version`. The contracts listing filters by `school_id` and `status`.

The school invoice assembles as follows. The entry-fees component is the sum of `fee_charged_cents` over the school's entries in `CONFIRMED`, `COMPETING`, `ADVANCED`, `ELIMINATED`, or `FINISHED` — the invoice status set. The judge-fees component is the sum of `final_fee_cents` over contracts in `CONFIRMED`, `DISPUTED`, or `PAID`. Their sum is the pre-discount subtotal. The volume-discount tier is selected on that pre-discount value: a subtotal of at least 100000 cents earns 10 percent, a subtotal of at least 50000 cents earns 5 percent, and anything below earns nothing; per §2.9 the tier does not change even if applying it pulls the total back below the threshold. The discount itself is the rounded-half-up entry-fees portion plus the rounded-half-up judge-fees portion, computed per component before summation. Payments are the sum of `final_fee_cents` over `PAID` contracts. The school's `invoice_balance_cents` is the pre-discount subtotal minus the discount minus the payments.

### 3.4. Rounds, Pairing Generation, and Staffing

`TabStaff` schedules rounds by supplying the `division_id`, a `round_number` (at least 1, unique within its division — a duplicate yields `ERR_ROUND_NUMBER_EXISTS`, HTTP 409), a `kind` of `PRELIM` or `ELIM`, and the slot boundaries `starts_at` and `ends_at`, where `starts_at` must be strictly earlier than `ends_at`. A round is born `SCHEDULED` with `pairings_total` 0 and `pairings_verified_count` 0; ballots for the round are accepted until `ends_at` plus 60 minutes. The rounds listing filters by `division_id`, `kind`, and `status`.

Starting prelims moves the tournament `REGISTRATION_LOCKED` → `PRELIMS_ACTIVE`. It requires the tournament to be `REGISTRATION_LOCKED` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and every division holding at least 2 `CONFIRMED` entries to have at least one `SCHEDULED` `PRELIM` round (otherwise `ERR_ROUNDS_NOT_SCHEDULED`). On success every `CONFIRMED` entry cascades to `COMPETING`, and the tournament's `version` increments.

Generating pairings for a round is the pairing engine's entry point. The round must be `SCHEDULED` (otherwise `ERR_ROUND_INVALID_STATE`); a `PRELIM` round requires the tournament to be `PRELIMS_ACTIVE` and an `ELIM` round requires `ELIMS_ACTIVE` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`); and all prior-numbered rounds of the same kind within the division must already be `TABULATED` — earlier prelims before a later prelim, earlier elims before a later elim (otherwise `ERR_ROUND_INVALID_STATE`). The request carries `expected_round_version` per §2.6. On success the pairings and their membership records are created, `pairings_total` is set, the round's `version` increments, and the round becomes `PAIRED`. If the algorithm cannot find a complete valid arrangement, nothing is persisted and the request fails with `ERR_PAIRING_INFEASIBLE` (HTTP 409).

The pairing algorithm depends on phase and family; its eligible pool is the division's entries in `COMPETING` for a `PRELIM` round and in `ADVANCED` for an `ELIM` round. Every ordering in the engine falls back to `created_at` ascending as its final tie-break and never uses `id`.

For a first-round preliminary debate, eligible entries are ordered by `created_at` ascending and paired adjacently — first with second, third with fourth, and so on. For later preliminary debate rounds, entries are ordered by the standings (§3.5), grouped into brackets of equal wins, and paired high-high within each bracket — first with second, third with fourth within the bracket. A bracket with an odd count sends its lowest-ordered entry down into the next lower bracket, where it is paired high-high there, and this cascading repair applies recursively.

Two hard constraints govern every preliminary debate arrangement: no pairing may match two entries of the same school, and no pairing may repeat a matchup that already occurred in an earlier `PRELIM` round of the division. When a proposed arrangement violates one, the resolution search swaps the conflicting pairing's second member with the next available entry in order and retries, exhaustively, guided by `created_at` order. If no complete valid arrangement exists, the generate fails with `ERR_PAIRING_INFEASIBLE` and persists nothing.

When the eligible count is odd, exactly one bye is awarded to the lowest-ordered entry whose `has_received_bye` is still false; if every eligible entry has already received a bye, the lowest-ordered entry overall receives it. A bye pairing is created directly in `VERIFIED` status with that entry as its winner and `is_bye` true, and it contributes a win plus a fixed award of 27 speaker points to the entry. In the round's pairing list, the bye pairing is emitted after all regular pairings.

Preliminary speech pairing ignores conflicts entirely. Eligible entries are ordered by standings — by `created_at` ascending for round one — and distributed into sections whose count is the eligible count divided by 7 and rounded up. Section sizes are kept as equal as possible: sizes may differ by at most one entry, and the larger sections come first. Distribution is serpentine by order — the first entry goes to the first section, the second to the second, onward to the last section, then the direction reverses and the following entries fill sections back toward the first, alternating direction with each pass. Same-school and rematch considerations never apply in speech; sections never reject for conflicts.

Elimination pairing is seeded. For debate, the field is guaranteed to be a power of two by break determination, and seed *i* is paired with the seed that is field-size-plus-one-minus-*i* — top seed against bottom seed, second seed against second-to-last, and so on. For speech, entries are distributed serpentine by seed into sections of at most 7; a field of 7 or fewer produces a single final section. Elimination rounds ignore same-school and rematch constraints by design.

Every pairing derives its `format` from its division's `event_type`: `HEAD_TO_HEAD` for debate, `SECTION` for speech. A pairing is born `PENDING_STAFFING` with `room_id` and `judge_id` unset, `is_bye` false, and `winner_entry_id` unset. Its membership is recorded as `PairingEntry` rows, each carrying the `pairing_id`, the `entry_id`, a `side`, and a 1-based `draw_position`; within a debate pairing the first-ordered entry is `AFF` and the second is `NEG`, while speech members are all `SPEAKER`. Membership listings are sorted by `draw_position` ascending within a pairing, and `PairingEntry` records carry only `id` and `created_at`. The pairings listing filters by `round_id`, `judge_id`, `room_id`, and `status`; the pairing-entries listing filters by `pairing_id` and `entry_id`.

Staffing a pairing means assigning it a room and a judge. Assigning a room is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409) exactly when another pairing in the same tournament already holds that room on a slot that overlaps under half-open interval semantics: the existing slot's `starts_at` is strictly earlier than the new slot's `ends_at` and the new slot's `starts_at` is strictly earlier than the existing slot's `ends_at`. Slots that merely touch — one's end equal to the other's start — do not overlap; there is no buffer requirement between room bookings.

Assigning a judge runs its checks in their pipeline positions. The judge must be `COMMITTED` (otherwise `ERR_JUDGE_INVALID_STATE`) and the pairing must be `PENDING_STAFFING` (otherwise `ERR_PAIRING_INVALID_STATE`). The conflict-of-interest check then comes before both the commitment-ceiling and turnover checks per §2.7: assigning a judge to a pairing that involves an entry of the judge's own school, or of any school recorded in that judge's `JudgeConflict` rows, is rejected with `ERR_JUDGE_CONFLICT_OF_INTEREST` (HTTP 409). Next, the judge's `assigned_round_count` — the number of pairings currently staffed by this judge, verified or not — must remain below the judge's `commitment_rounds`, otherwise the assignment fails with `ERR_JUDGE_OVER_COMMITTED` (HTTP 409); this structural ceiling is evaluated before the temporal turnover rule. Last, the turnover rule rejects the assignment with `ERR_JUDGE_TURNOVER_CONFLICT` (HTTP 409) when any other pairing staffed by the same judge has a slot that overlaps the new slot or is separated from it by a gap of less than 30 minutes on either side; a gap of exactly 30 minutes is allowed.

A successful judge assignment increments the judge's `assigned_round_count` by one. When both `room_id` and `judge_id` are set, the pairing moves `PENDING_STAFFING` → `STAFFED`. Unassigning a judge — from a `PENDING_STAFFING` or `STAFFED` pairing — decrements `assigned_round_count` by one as compensation, and a `STAFFED` pairing that loses its staffing reverts to `PENDING_STAFFING`; the same reversion happens when a room reassignment removes the room.

Once every non-bye pairing of a `PAIRED` round is `STAFFED`, opening ballots moves the round `PAIRED` → `BALLOTS_OPEN`; any unstaffed non-bye pairing blocks it with `ERR_ROUND_INVALID_STATE`. Opening cascades every non-bye pairing `STAFFED` → `BALLOT_RELEASED` and increments the round's `version`.

### 3.5. Ballots, Verification, and Standings

Ballots are authored by the assigned judge. Creating a ballot takes the `pairing_id` and produces a `DRAFT` ballot whose `judge_id` is set from the authenticated judge identity — the pairing's `judge_id` must equal the caller's `X-User-ID`, otherwise `ERR_RESOURCE_OWNERSHIP_MISMATCH`. The ballot's content depends on the family. A debate ballot carries a `winner_entry_id`, which must be a member of the pairing (otherwise `ERR_WINNER_NOT_IN_PAIRING`, HTTP 422), and a `speaker_points` map from each pairing member's entry id to an integer score between 20 and 30 inclusive; every pairing member must be present in the map, and a missing or out-of-range score yields `ERR_SPEAKER_POINTS_OUT_OF_RANGE` (HTTP 422). A speech ballot carries a `ranks` map from each section member's entry id to an integer rank between 1 and the section size inclusive; every section member must be present and in range (otherwise `ERR_RANK_INVALID`, HTTP 422), and two members sharing a rank in one ballot yields `ERR_DUPLICATE_RANK_IN_SECTION` (HTTP 422). The `allow_low_point_win` flag defaults to false. Field validity runs at creation and again at submission.

Debate enforces the point-win rule: the winner's total speaker points must be at least the loser's total, unless the ballot carries `allow_low_point_win` set to true. A ballot awarding the win to the lower-speaker-point entry without the flag is rejected with `ERR_LOW_POINT_WIN_NOT_FLAGGED` (HTTP 422), and like the field-validity rules this check runs both when the ballot is created and again when it is submitted; in both passes it outranks the field-validity checks per §2.7.

Submitting moves a ballot `DRAFT` → `SUBMITTED`. The ballot must be `DRAFT` (otherwise `ERR_BALLOT_INVALID_STATE`), and the pairing must be `BALLOT_RELEASED` — a cross-entity gate whose failure surfaces as `ERR_PAIRING_INVALID_STATE` — and the logical clock must be at or before the round's `ends_at` plus 60 minutes (otherwise `ERR_BALLOT_WINDOW_CLOSED`). A successful submission moves the pairing `BALLOT_RELEASED` → `BALLOT_SUBMITTED` and stamps `submitted_at` — unset until the first submission — with the logical UTC of this most recent draft-to-submitted transition. A judge may recall a submitted ballot — `SUBMITTED` → `DRAFT`, otherwise `ERR_BALLOT_INVALID_STATE` — which reverts the pairing to `BALLOT_RELEASED`.

Verification is the tab room's exclusive lever. `TabStaff` verifies a `SUBMITTED` ballot — otherwise `ERR_BALLOT_INVALID_STATE` — moving it to `VERIFIED`; the pairing moves `BALLOT_SUBMITTED` → `VERIFIED`, the round's `pairings_verified_count` increments, and for debate the pairing's `winner_entry_id` is set from the ballot. Voiding is the correction path: `TabStaff` voids a `VERIFIED` ballot, moving it to its terminal `VOIDED` state. A void fires a three-link cascade: the pairing reverts `VERIFIED` → `BALLOT_RELEASED` with its winner cleared and `pairings_verified_count` decremented; if the pairing's round was already `TABULATED`, the round auto-reverts `TABULATED` → `BALLOTS_OPEN` (incrementing the round's `version`) so a replacement ballot can be entered; and every affected entry's statistics are recomputed excluding the `VOIDED` ballot — wins, `speaker_points_raw` and `speaker_points_adjusted`, `rank_points_raw` and `rank_points_adjusted`, `opponent_strength`, and `prelim_rank` all refreshed. The void never touches any school's invoice.

Tabulating a round moves it `BALLOTS_OPEN` → `TABULATED` and requires every pairing of the round to be `VERIFIED` (otherwise `ERR_ROUND_INVALID_STATE`). Tabulation recomputes entry statistics and, for elimination rounds, resolves placements (§3.6); it increments the round's `version`. The ballots listing filters by `pairing_id`, `judge_id`, and `status`.

The recomputation at tabulation is exact. For a debate entry, each contribution is the speaker points awarded by one `VERIFIED` ballot of the entry's preliminary pairings, plus one bye-award contribution of 27 points per bye received; `VOIDED` ballots never contribute. The entry's `speaker_points_raw` is the plain sum of all contributions. Its `speaker_points_adjusted` is the high-low-adjusted variant: with at least three contributions, the raw sum minus the maximum contribution minus the minimum contribution; with fewer than three, it equals the raw sum — identical data, different number. `wins` counts the `VERIFIED` ballots the entry won plus its bye awards; `losses` counts the `VERIFIED` ballots where the entry was a pairing member but not the winner.

For a speech entry, each `VERIFIED` ballot contributes 8 minus the rank the ballot gave the entry. `rank_points_raw` is the sum of those contributions, and `rank_points_adjusted` applies the same high-low rule — with at least three `VERIFIED` ballots, the raw sum minus the largest minus the smallest contribution, otherwise the raw sum. The entry's first-place count, used in tie-breaking, is the number of `VERIFIED` ballots in which it received rank 1.

Opponent strength is debate-only and computed in a pinned order: at tabulate time, all wins for the division are recomputed first, and only then is each entry's `opponent_strength` evaluated as the sum of the current wins of its distinct preliminary opponents. Bye rounds contribute no opponent, and speech entries always have `opponent_strength` 0.

Standings order the division's entries in `COMPETING`, `ADVANCED`, `ELIMINATED`, or `FINISHED`. Debate sorts by `wins` descending, then `speaker_points_adjusted` descending, then `opponent_strength` descending, then `speaker_points_raw` descending, with `created_at` ascending as the final tie-break — `id` is never used, so ties are impossible. Speech sorts by `rank_points_adjusted` descending, then `rank_points_raw` descending, then first-place count descending, then `created_at` ascending. An entry's `prelim_rank` is its 1-based position in that order after the latest tabulated preliminary round, and remains unset until the first tabulation. The division standings read returns entries sorted by `prelim_rank` ascending, with unranked entries last, ordered among themselves by `created_at` ascending.

### 3.6. Breaks, Elimination Rounds, and Final Placements

When a division's prelims are complete, `TabStaff` determines its breaks. The tournament must be `PRELIMS_ACTIVE` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and every `PRELIM` round of the division must be `TABULATED` (otherwise `ERR_ROUNDS_NOT_TABULATED`). Let *n* be the number of the division's entries still `COMPETING`; fewer than 4 such entries fails with `ERR_INSUFFICIENT_BREAK_CANDIDATES` (HTTP 409). The win threshold is derived from the tournament's `prelim_round_count`: divide the round count by two, round down, and add one — a 4-round tournament requires 3 wins, and a 5-round tournament also requires 3. Debate candidates are the entries whose `wins` are at least the threshold; meeting the threshold exactly qualifies, while one win fewer does not. Speech candidates are simply all `COMPETING` entries of the division.

The bracket size is then pinned arithmetically. The size cap is the largest power of two not exceeding half of *n* rounded down, and never above 16. The division's `bracket_size` is the largest power of two not exceeding the smaller of the size cap and the candidate count; if that result is below 2, determination fails with `ERR_INSUFFICIENT_BREAK_CANDIDATES`. The advancing set is the first `bracket_size` entries of the division's standings order restricted to candidates: each becomes `ADVANCED` and receives a `seed` from 1 to `bracket_size` in standings order. Every other `COMPETING` entry becomes `ELIMINATED` with `final_placement` `NON_BREAKING`.

Starting elims moves the tournament `PRELIMS_ACTIVE` → `ELIMS_ACTIVE`. Beyond the phase gate itself, it requires every `PRELIM` round of every division to be `TABULATED` (otherwise `ERR_ROUNDS_NOT_TABULATED`) and every division whose `competing_entry_count` is at least 2 to have its `bracket_size` set (otherwise `ERR_BREAKS_NOT_DETERMINED`, HTTP 409).

Elimination rounds are paired per §3.4 and tabulated per §3.5, with one addition: tabulating an elim round resolves placements. Let *F* be the number of `ADVANCED` entries in the division at the start of that elim round. A debate loser takes a tier from *F*: with *F* equal to 2 the loser is `RUNNER_UP`; with *F* from 3 to 4 inclusive, `SEMIFINALIST`; with *F* from 5 to 8 inclusive, `QUARTERFINALIST`; with *F* from 9 to 16 inclusive, `OCTOFINALIST`. Debate winners stay `ADVANCED`. In speech, the top two of each section stay `ADVANCED` and the remaining section members take the same *F*-based tier — except in the final section (a field of at most 7 with no further elim rounds), where ranks 3 and 4 become `SEMIFINALIST` and ranks 5 through 7 become `QUARTERFINALIST`. Every eliminated entry's `final_placement` is set at this moment.

Completing the tournament moves it `ELIMS_ACTIVE` → `COMPLETED`, gated on every `ELIM` round of every division being `TABULATED` (otherwise `ERR_ROUNDS_NOT_TABULATED`, plus the phase gate). Completion resolves the top of each division. In debate, the single still-`ADVANCED` entry becomes `FINISHED` with `final_placement` `CHAMPION`. In speech, the still-`ADVANCED` entries — the top two of the final section — are ordered by the final section's ballot ranks: rank 1 becomes `FINISHED` and `CHAMPION`, rank 2 becomes `FINISHED` and `RUNNER_UP`. The tournament's `version` increments.

### 3.7. Publishing Results and Certifying Qualifications

Publication and certification walk the results axis, never the phase axis. Publishing results requires the tournament's `status` to be `COMPLETED` and its `results_visibility` to be `HIDDEN` (either failure yields `ERR_TOURNAMENT_PHASE_FORBIDDEN`), and moves the axis `HIDDEN` → `PUBLISHED`. At that moment, every entry of the tournament not in `REGISTERED` receives its `qualification_points` from the placement tier table: `CHAMPION` earns 10, `RUNNER_UP` 8, `SEMIFINALIST` 6, `QUARTERFINALIST` 4, `OCTOFINALIST` 2, and `NON_BREAKING` 1; `WITHDRAWN` entries receive 0. The points are computed once at publication, are immutable afterwards, and remain unset before it.

Certifying qualifications requires `results_visibility` `PUBLISHED` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and every hired-judge contract of every school in the tournament to be in `PAID` or `CANCELLED` (otherwise `ERR_UNPAID_CONTRACTS_REMAIN`, HTTP 409). Certification moves the axis `PUBLISHED` → `CERTIFIED`. Each of these transitions increments the tournament's `version`.

### 3.8. Hosting Logistics: Catering and Awards

The director manages hosting logistics through orders created with a `tournament_id` and a `kind` of `CATERING` or `AWARDS`. At most one non-`FULFILLED` order of each kind may exist per tournament; a conflicting create is rejected with `ERR_ORDER_KIND_EXISTS` (HTTP 409). An order is born `DRAFT` with `headcount_demand`, `meal_count`, and `awards_count` at 0 and both `frozen_meal_count` and `frozen_awards_count` unset; while it remains `DRAFT` its live demand fields recompute on every registration-graph mutation.

A catering order's `headcount_demand` is the number of the tournament's entries in `COMPETING`, `ADVANCED`, `ELIMINATED`, or `FINISHED`, plus the number of its `COMMITTED` judges, plus the tournament's `tournament_staff_count`. Its `meal_count` adds a ten percent buffer and rounds up to a whole meal. An awards order's `awards_count` is the sum of `bracket_size` over the tournament's divisions whose `bracket_size` is set.

Submitting an order moves it `DRAFT` → `SUBMITTED` (from any other state, `ERR_ORDER_INVALID_STATE`) and freezes the demand: `frozen_meal_count` snapshots the live `meal_count` and `frozen_awards_count` snapshots the live `awards_count`. After submission the live fields keep recomputing as the graph mutates, but the frozen fields never change. Submitting an awards order additionally requires the tournament to be `ELIMS_ACTIVE` or `COMPLETED` and every division with a `competing_entry_count` of at least 2 to have its `bracket_size` set (otherwise `ERR_BREAKS_NOT_DETERMINED`). Fulfilling moves a `SUBMITTED` order to `FULFILLED` (otherwise `ERR_ORDER_INVALID_STATE`). The orders listing filters by `tournament_id` and `kind`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request and response bodies are not repeated here — §2 and §3 define them through the workflow narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tournaments` | Create a tournament (born `DRAFT`, results `HIDDEN`) | TournamentDirector |
| GET | `/tournaments` | List tournaments | Any authenticated role |
| GET | `/tournaments/{id}` | Get a tournament | Any authenticated role |
| POST | `/tournaments/{id}/open-registration` | Open registration (`DRAFT` → `REGISTRATION_OPEN`) | TournamentDirector |
| POST | `/tournaments/{id}/lock-registration` | Lock registration (`REGISTRATION_OPEN` → `REGISTRATION_LOCKED`) | TournamentDirector |
| POST | `/tournaments/{id}/start-prelims` | Start prelims (`REGISTRATION_LOCKED` → `PRELIMS_ACTIVE`) | TournamentDirector |
| POST | `/tournaments/{id}/start-elims` | Start elims (`PRELIMS_ACTIVE` → `ELIMS_ACTIVE`) | TournamentDirector |
| POST | `/tournaments/{id}/complete` | Complete the tournament (`ELIMS_ACTIVE` → `COMPLETED`) | TournamentDirector |
| POST | `/tournaments/{id}/publish-results` | Publish results (`HIDDEN` → `PUBLISHED`) | TournamentDirector |
| POST | `/tournaments/{id}/certify-qualifications` | Certify qualifications (`PUBLISHED` → `CERTIFIED`) | TournamentDirector |
| POST | `/schools` | Register a school into a tournament | TournamentDirector |
| GET | `/schools` | List schools | Any authenticated role |
| GET | `/schools/{id}` | Get a school with computed obligation and invoice fields | Any authenticated role |
| POST | `/schools/{id}/confirm` | Confirm a school (`REGISTERED` → `CONFIRMED`) | SchoolCoach |
| POST | `/schools/{id}/unconfirm` | Unconfirm a school (`CONFIRMED` → `REGISTERED`) | SchoolCoach |
| POST | `/divisions` | Create an event division | TournamentDirector |
| GET | `/divisions` | List divisions | Any authenticated role |
| GET | `/divisions/{id}` | Get a division | Any authenticated role |
| POST | `/divisions/{id}/determine-breaks` | Determine the division's elimination bracket | TabStaff |
| GET | `/divisions/{id}/standings` | Get division standings | Any authenticated role |
| POST | `/entries` | Create an entry | SchoolCoach |
| GET | `/entries` | List entries | Any authenticated role |
| GET | `/entries/{id}` | Get an entry with computed statistics | Any authenticated role |
| POST | `/entries/{id}/confirm` | Confirm (or re-confirm) an entry | SchoolCoach |
| POST | `/entries/{id}/withdraw` | Withdraw a confirmed entry (pre-lock) | SchoolCoach |
| POST | `/judges` | Register a school-provided judge | SchoolCoach, TournamentDirector |
| GET | `/judges` | List judges | Any authenticated role |
| GET | `/judges/{id}` | Get a judge | Any authenticated role |
| POST | `/judges/{id}/commit` | Commit a judge for a number of rounds | SchoolCoach |
| POST | `/judges/{id}/withdraw` | Withdraw a judge (pre-lock) | SchoolCoach |
| POST | `/judge-conflicts` | Record a judge conflict of interest | SchoolCoach, TabStaff |
| GET | `/judge-conflicts` | List judge conflicts | Any authenticated role |
| GET | `/judge-conflicts/{id}` | Get a judge conflict | Any authenticated role |
| POST | `/rooms` | Create a room | TournamentDirector |
| GET | `/rooms` | List rooms | Any authenticated role |
| GET | `/rooms/{id}` | Get a room | Any authenticated role |
| POST | `/rounds` | Create a round (`SCHEDULED`) | TabStaff |
| GET | `/rounds` | List rounds | Any authenticated role |
| GET | `/rounds/{id}` | Get a round | Any authenticated role |
| POST | `/rounds/{id}/generate-pairings` | Generate the round's pairings (`SCHEDULED` → `PAIRED`) | TabStaff |
| POST | `/rounds/{id}/open-ballots` | Open ballots (`PAIRED` → `BALLOTS_OPEN`) | TabStaff |
| POST | `/rounds/{id}/tabulate` | Tabulate the round (`BALLOTS_OPEN` → `TABULATED`) | TabStaff |
| GET | `/pairings` | List pairings | Any authenticated role |
| GET | `/pairings/{id}` | Get a pairing | Any authenticated role |
| POST | `/pairings/{id}/assign-room` | Assign a room to a pairing | TabStaff |
| POST | `/pairings/{id}/assign-judge` | Assign a judge to a pairing | TabStaff |
| POST | `/pairings/{id}/unassign-judge` | Remove the judge from a pairing | TabStaff |
| GET | `/pairing-entries` | List pairing memberships | Any authenticated role |
| GET | `/pairing-entries/{id}` | Get a pairing membership | Any authenticated role |
| POST | `/ballots` | Create a draft ballot for an assigned pairing | Judge |
| GET | `/ballots` | List ballots | Any authenticated role |
| GET | `/ballots/{id}` | Get a ballot | Any authenticated role |
| POST | `/ballots/{id}/submit` | Submit a draft ballot | Judge |
| POST | `/ballots/{id}/recall` | Recall a submitted ballot | Judge |
| POST | `/ballots/{id}/verify` | Verify a submitted ballot | TabStaff |
| POST | `/ballots/{id}/void` | Void a verified ballot | TabStaff |
| POST | `/hired-judge-contracts` | Purchase hired judge-rounds against the school's shortfall | SchoolCoach |
| GET | `/hired-judge-contracts` | List hired-judge contracts | Any authenticated role |
| GET | `/hired-judge-contracts/{id}` | Get a hired-judge contract | Any authenticated role |
| POST | `/hired-judge-contracts/{id}/fill` | Fill a contract with a hired judge (`REQUESTED` → `FILLED`) | TournamentDirector |
| POST | `/hired-judge-contracts/{id}/accept` | Accept a filled contract (`FILLED` → `CONFIRMED`) | SchoolCoach |
| POST | `/hired-judge-contracts/{id}/dispute` | Dispute a confirmed contract (`CONFIRMED` → `DISPUTED`) | SchoolCoach |
| POST | `/hired-judge-contracts/{id}/resolve-dispute` | Resolve a dispute (`DISPUTED` → `CONFIRMED`) | TournamentDirector |
| POST | `/hired-judge-contracts/{id}/pay` | Pay a confirmed contract (`CONFIRMED` → `PAID`) | SchoolCoach |
| POST | `/hired-judge-contracts/{id}/cancel` | Cancel a requested contract (`REQUESTED` → `CANCELLED`) | TournamentDirector |
| POST | `/logistics-orders` | Create a logistics order (`CATERING` or `AWARDS`) | TournamentDirector |
| GET | `/logistics-orders` | List logistics orders | Any authenticated role |
| GET | `/logistics-orders/{id}` | Get a logistics order | Any authenticated role |
| POST | `/logistics-orders/{id}/submit` | Submit an order, freezing its demand counts | TournamentDirector |
| POST | `/logistics-orders/{id}/fulfill` | Mark a submitted order fulfilled | TournamentDirector |
| POST | `/_clock/set_current_utc` | Advance the logical UTC clock | TournamentDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_TOURNAMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_DIVISION_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_JUDGE_NOT_FOUND` | 404 Not Found |
| `ERR_JUDGE_CONFLICT_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_ROUND_NOT_FOUND` | 404 Not Found |
| `ERR_PAIRING_NOT_FOUND` | 404 Not Found |
| `ERR_PAIRING_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_BALLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TOURNAMENT_PHASE_FORBIDDEN` | 409 Conflict |
| `ERR_SCHOOL_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_JUDGE_INVALID_STATE` | 409 Conflict |
| `ERR_ROUND_INVALID_STATE` | 409 Conflict |
| `ERR_PAIRING_INVALID_STATE` | 409 Conflict |
| `ERR_BALLOT_INVALID_STATE` | 409 Conflict |
| `ERR_CONTRACT_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_SCHOOL_OBLIGATION_DEFICIENT` | 409 Conflict |
| `ERR_SCHOOLS_NOT_LOCK_READY` | 409 Conflict |
| `ERR_ROUNDS_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ROUNDS_NOT_TABULATED` | 409 Conflict |
| `ERR_BREAKS_NOT_DETERMINED` | 409 Conflict |
| `ERR_UNPAID_CONTRACTS_REMAIN` | 409 Conflict |
| `ERR_INSUFFICIENT_BREAK_CANDIDATES` | 409 Conflict |
| `ERR_PAIRING_INFEASIBLE` | 409 Conflict |
| `ERR_JUDGE_CONFLICT_OF_INTEREST` | 409 Conflict |
| `ERR_LOW_POINT_WIN_NOT_FLAGGED` | 422 Unprocessable Entity |
| `ERR_SCHOOL_ENTRY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_DIVISION_GLOBAL_CAP_REACHED` | 409 Conflict |
| `ERR_EVENT_CODE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_ROUNDS_INVALID` | 422 Unprocessable Entity |
| `ERR_ROUND_NUMBER_EXISTS` | 409 Conflict |
| `ERR_ORDER_KIND_EXISTS` | 409 Conflict |
| `ERR_SPEAKER_POINTS_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_RANK_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RANK_IN_SECTION` | 422 Unprocessable Entity |
| `ERR_WINNER_NOT_IN_PAIRING` | 422 Unprocessable Entity |
| `ERR_HIRED_ROUNDS_EXCEED_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_JUDGE_TURNOVER_CONFLICT` | 409 Conflict |
| `ERR_JUDGE_OVER_COMMITTED` | 409 Conflict |
| `ERR_REGISTRATION_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_REGISTRATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BALLOT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CROSS_TOURNAMENT_REFERENCE` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
