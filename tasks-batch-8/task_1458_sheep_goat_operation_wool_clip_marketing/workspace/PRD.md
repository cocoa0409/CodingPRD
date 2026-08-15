# Sheep & Goat Operation and Wool Clip Marketing API — Product Requirements Document

## 1. Introduction

A western sheep and goat ranch runs on a tight annual rhythm: rams and bucks go in with the ewes and does, lambs and kids hit the ground roughly five months later, shearing crews sweep through in the spring, and the wool clip travels to a cooperative pool while lambs move to meat buyers timed against ethnic-holiday demand. Alongside the production cycle, the ranch grazes customer land under paid vegetation-management contracts, rotates its flocks across deeded pastures to break parasite cycles, and absorbs the occasional predator strike that must be verified before it can be written off. Every one of these activities leaves a paper trail today — notebooks, scale tickets, lab certificates, and pool statements — that no single system reconciles.

This document specifies a REST API, mounted under `/api`, that becomes the ranch's system of record for that entire operation. It tracks flocks and their breeding seasons down to individual birth records; schedules shearing crews and converts each completed shearing into a graded, core-tested, pool-consigned wool clip; books meat and breeding-stock sales with holiday premiums and auction commissions; administers deworming treatments with meat-withdrawal enforcement; runs the predator-loss verification pipeline that decrements the flock and can breach grazing contracts; and manages those contracts from draft through counter-offer to a completed, invoiced service window.

The API is deliberately opinionated about money (integer cents, round-half-up), time (a settable logical clock), and concurrency (explicit stale-version rejection on the two negotiated aggregates), so that the ranch office, the wool pool, and the grazing client each see exactly one version of the truth. Every mutation is immediately visible in the response that performs it; there are no deferred or eventually-consistent reads anywhere in the system.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or presenting a role string that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the same `ERR_FORBIDDEN` applies when a state transition exists but the caller's role is not the transition's designated actor.

Five roles exist. `RanchManager` is the ranch owner/operator and runs flocks, seasons, pastures, crews, shearing bookings, wool lots and grading, core-test disposition, consignment tendering and withdrawal, holiday windows, livestock sales and payment, loss verification, and grazing-contract drafting, negotiation, activation, and completion. `RangeHand` is the field hand who records births, grazing moves, parasite treatments and follow-ups, shearing tallies, predator losses, and truck loading and delivery. `WoolPoolOperator` is the wool pool staff member who submits core tests, posts lab results, and drives the consignment acceptance, advance, sale, and settlement pipeline. `GrazingClient` is the vegetation-management customer who counters and accepts grazing contracts. `PlatformAdmin` is the test-harness operator who owns the logical clock and nothing else.

For every role — `RanchManager`, `RangeHand`, `WoolPoolOperator`, `GrazingClient`, and `PlatformAdmin` alike — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it for audit and segregation-of-duties purposes (as `recorded_by_user_id` on a birth record, as `submitted_by_user_id` and `locked_by_user_id` on a core test, and as `reviewed_by_user_id` on a loss report) but never compares it to any entity's `id` for ownership decisions.

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

List endpoints accept two query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Results are always sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through any collection.

### 2.4. Resource Identity, Timestamps, and Change Tracking

Every persisted resource is addressed by an `id` that is a server-minted UUID with no type prefix. Every resource carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits. All resources except birth records additionally carry `updated_at`, in the same format and refreshed on every mutation, and `version`, an integer that increments by exactly 1 on every mutation of the resource, including every state transition. A birth record is the single exception: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it, because a birth record is never modified after it is logged.

### 2.5. The Logical Clock and Window Conventions

All temporal gates in the system — breeding-season advancement, move activation windows, contract service windows, withdrawal gates, and pasture rest periods — are evaluated against a logical clock, never against wall-clock time. A test-driving capability, reserved for `PlatformAdmin`, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any clock-setting call it continues to read that default.

Windows throughout the system are half-open intervals: the start bound is inclusive and the end bound is exclusive. A premium window, a service window, or a move's planned occupancy therefore includes its start instant and excludes its end instant, and two back-to-back windows that share a boundary instant do not overlap. Where the system counts days, it counts whole calendar days contained in the half-open window.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each requires the caller to present the version of the parent aggregate it last observed.

Recording a regrade on a wool lot requires the request to carry `expected_wool_lot_version`, holding the caller's last observed `version` of that lot. If the lot's current `version` no longer matches — because another writer has already regraded the lot, superseding the grade the caller based its estimate on — the regrade is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), preventing the caller from overwriting a grade it never observed.

Counter-offering a grazing contract requires the request to carry `expected_grazing_contract_version`, holding the caller's last observed `version` of that contract. If the contract's current `version` no longer matches — for example because the ranch re-proposed terms after the client last read the contract — the counter is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), even if the contract has meanwhile returned to a state from which countering is otherwise allowed.

No endpoint other than these two accepts a version field of any kind.

### 2.7. Money, Weight, and Measurement Precision

All monetary amounts are integer cents; any computed monetary value is rounded half-up to a whole cent at the point it is stored. Percentages that the system computes and stores — the lambing rate and the treatment efficacy — are rounded half-up to one decimal place. Micron measurements are expressed to two decimal places. Wool weights are expressed to two decimal places. Where a formula multiplies an unrounded intermediate (the clean-pounds figure in certified lot valuation), the intermediate is kept at full precision and rounding happens only once, at the final cent amount.

### 2.8. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and the first check that fails determines the error returned — a request that would fail several checks surfaces the earliest one, never a later one. The pipeline order is:

1. Authentication — both headers present and the role declared, else `ERR_UNAUTHENTICATED`.
2. Authorization — the caller's role permitted on the endpoint (and the designated actor for a transition), else `ERR_FORBIDDEN`.
3. Request shape — required fields present, enum values valid, numeric ranges respected (weights and acres strictly positive, head counts and `ewes_bred` at least 1, percentages between 0 and 100 inclusive), start dates strictly before end dates, and conditional field shapes satisfied (a `MEAT` sale carries `avg_weight_lbs` and `base_price_per_cwt_cents` and must not carry `per_head_price_cents`, while a `BREEDING` sale carries `per_head_price_cents` and must not carry the meat pair; a grazing move carries exactly one of `pasture_id` or `contract_id`), else `ERR_VALIDATION`.
4. Existence — path identifiers resolve left-to-right, then body foreign-key references (`flock_id`, `season_id`, `clip_id`, `lot_id`, `pasture_id`, `contract_id`, `crew_id`) resolve to existing rows, else `ERR_NOT_FOUND`.
5. Flock liveness — the target flock is still `ACTIVE` when any child record is created under it, else `ERR_FLOCK_RETIRED`.
6. State-machine legality — the requested transition exists from the entity's current state, with the special cases of scheduling against an `INACTIVE` crew (`ERR_CREW_INACTIVE`), loading an unpaid sale (`ERR_SALE_UNPAID`), and retiring a flock that still has busy children (`ERR_FLOCK_BUSY`).
7. Business safety rules — the meat-withdrawal gate and the core-test segregation-of-duties check.
8. Business temporal rules — season clock gates, the birth-record window, pasture overlap, crew overlap with its sanitation buffer, shearing feasibility, and contract window gates.
9. Business constraint rules — one-open-season, one-open-core-test, one-open-consignment, lot weight allocation, pasture capacity, contract head range, and birth-count arithmetic.
10. Business fiscal rules — head sufficiency and payment-amount equality.
11. Stale-version rejection — the two optimistic-concurrency rules of §2.6, evaluated last.

Because earlier layers mask later ones, a shearing booking that names an unknown crew and also describes an infeasible window returns `ERR_NOT_FOUND`, not `ERR_SHEARING_WINDOW_INFEASIBLE`; and a regrade carrying a bad micron and a stale version returns the shape or OCC error only after every earlier layer has passed.

### 2.9. State Machines and Transition Authority

Every entity lifecycle below is a state machine. For any transition-style endpoint, two rejections are distinguished uniformly: when the requested `(from -> to)` pair exists but the caller's role is not the transition's actor, the request is rejected with `ERR_FORBIDDEN` (HTTP 403); when no such transition exists from the entity's current state, the request is rejected with the entity's own invalid-state error (HTTP 409) — `ERR_SEASON_INVALID_STATE`, `ERR_MOVE_INVALID_STATE`, `ERR_SHEARING_INVALID_STATE`, `ERR_LOT_INVALID_STATE`, `ERR_CORE_TEST_INVALID_STATE`, `ERR_CONSIGNMENT_INVALID_STATE`, `ERR_SALE_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, or `ERR_CONTRACT_INVALID_STATE`, as applicable. Terminal states accept no further transitions, and attempts to move out of them take the invalid-state error.

Every transition writes the new state, increments the entity's `version` by exactly 1, and refreshes `updated_at`; cascaded changes to other entities each increment that entity's `version` by 1 as well. The response of any mutation reflects the fully applied result, including all cascades, at once.

### 2.10. The Flock Headcount Ledger

A flock's `current_headcount` is never written directly. It is derived as the flock's `baseline_headcount`, plus the sum of `born_alive` over every birth record logged against any of the flock's seasons (regardless of season status), minus the sum of `head_lost` over the flock's loss reports in `VERIFIED` status, minus the sum of `head_count` over the flock's delivered `MEAT` sales, minus the sum of `actual_head_delivered` over the flock's delivered `BREEDING` sales. The value is initialized to `baseline_headcount` at flock creation and is recomputed on every read of the flock and immediately after every birth record, every loss verification, and every sale delivery. A projected headcount — which would additionally subtract sales still in `PENDING` or `LOADED` delivery status — is a reporting notion only and is never stored.

## 3. Business Logic & Workflows

### 3.1. Flocks and the Breeding Year

A `RanchManager` opens a flock by supplying a `flock_name` (unique across all flocks), a `species` of either `SHEEP` or `GOAT` (immutable once created), a `baseline_headcount` of at least 1, and optionally a `guardian_dog_count` recording the livestock guardian dogs currently assigned (defaulting to 0 and never negative). The flock is born `ACTIVE` in its `flock_status`, and its `current_headcount` is initialized to `baseline_headcount`. Flocks can be listed with `limit` and `offset` and filtered by `species` or `flock_status`; reading a single flock returns the computed `current_headcount` and the `withdrawal_until` gate described in §3.2.

Retirement is the flock's only transition, `ACTIVE -> RETIRED`, and it is guarded by a busy-children sweep: the flock must have no breeding season in `PLANNED`, `BREEDING`, `GESTATION`, `LAMBING`, or `WEANING`; no grazing move in `PLANNED` or `ACTIVE`; no shearing event in `SCHEDULED` or `IN_PROGRESS`; no livestock sale whose `delivery_status` is `PENDING` or `LOADED`; and no grazing contract in `DRAFT`, `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `ACTIVE`. Any violation is rejected with `ERR_FLOCK_BUSY` (HTTP 409). Symmetrically, once a flock is `RETIRED`, creating any child record under it — a season, a move, a treatment, a shearing event, a wool lot via its clip, a sale, a loss report, a contract — or logging births against its seasons is rejected with `ERR_FLOCK_RETIRED` (HTTP 409).

Within an active flock, the manager opens a breeding season with a `flock_id`, a `season_label` such as `2026-fall` (unique within the flock), an `ewes_bred` count of females exposed (at least 1), and a `breeding_start_date` strictly before the `breeding_end_date`. Only one open season per flock is permitted: creating a season while the same flock already has one in `PLANNED`, `BREEDING`, `GESTATION`, `LAMBING`, or `WEANING` is rejected with `ERR_OPEN_SEASON_EXISTS` (HTTP 409). On creation the system computes `expected_lambing_start` by adding the gestation length to `breeding_start_date` — 147 days for a `SHEEP` flock, 150 days for a `GOAT` flock — and the season starts in `PLANNED` `season_status` with `total_born`, `total_born_alive`, and `lambing_rate_pct` at zero.

The season advances through a gated chain, each step requested by the manager with a `to` target. `PLANNED -> BREEDING` requires the flock to be `ACTIVE`. `BREEDING -> GESTATION` requires the logical clock to have reached `breeding_end_date`. `GESTATION -> LAMBING` requires the clock to have reached `expected_lambing_start`. `LAMBING -> WEANING` requires the clock to have reached 45 days after `expected_lambing_start`. Each of the three clock gates is rejected with `ERR_SEASON_TOO_EARLY` (HTTP 422) when the clock has not yet arrived. `WEANING -> CLOSED` has no precondition. Cancellation is possible from `PLANNED` or from `BREEDING` (`PLANNED -> CANCELLED`, `BREEDING -> CANCELLED`); once the season reaches `GESTATION` the lambs or kids are already on the way and the season can no longer be cancelled, and any transition not defined from the current `season_status` is rejected with `ERR_SEASON_INVALID_STATE` (HTTP 409). Seasons are listed with `limit` and `offset`, filterable by `flock_id` and `season_status`, and a single season read returns the computed totals and lambing rate.

During `LAMBING`, the manager or a range hand logs each lambing or kidding batch as a birth record carrying `season_id`, `birth_date`, `births_reported`, `born_alive`, and `born_dead`. Three guards apply: the season must currently be in `LAMBING` (otherwise `ERR_SEASON_INVALID_STATE`); the `birth_date` must fall inside the lambing window running from `expected_lambing_start` through 45 days after it, inclusive (otherwise `ERR_BIRTH_OUTSIDE_WINDOW`, HTTP 422); and the arithmetic must balance — `births_reported` must equal the sum of `born_alive` and `born_dead`, with `births_reported` at least 1 and both components non-negative (otherwise `ERR_BIRTH_COUNT_MISMATCH`, HTTP 422). The server stamps `recorded_by_user_id` with the caller's `X-User-ID` for audit. Each birth record immediately recomputes the season's `total_born` (the sum of `births_reported` across the season's records), `total_born_alive` (the sum of `born_alive`), and `lambing_rate_pct` (the season's live-born total divided by `ewes_bred`, multiplied by 100, rounded half-up to one decimal place), and it feeds the flock headcount ledger of §2.10. Birth records are listed with `limit` and `offset`, filterable by `season_id`.

### 3.2. Pastures, Rotational Moves, and Parasite Control

The manager registers each deeded pasture with a unique `pasture_name`, an `acres` figure strictly above 0, a `carrying_capacity_head` of at least 1, and optionally a `rest_days` parasite-break period defaulting to 21 days (never negative). Reading a pasture returns two computed values: `occupied_head_count`, the sum of `head_count` over that pasture's moves currently in `ACTIVE` status, and `pasture_status`, which reads `OCCUPIED` while that count is above zero; otherwise `RESTING` while at least one `COMPLETED` move exists and the logical clock has not yet reached the most recently completed move's `move_end` plus the pasture's `rest_days` (when several moves tie on the latest `move_end`, the tie is broken by the latest `updated_at`); and `AVAILABLE` in every other case. Starting a move and later completing it returns `occupied_head_count` to exactly its pre-start value — occupancy is a compensating invariant, not a running estimate.

A grazing move is planned by the manager or a range hand with a `flock_id`, a `move_start` strictly before `move_end` (a half-open occupancy window), a `head_count` of at least 1, and exactly one destination: a `pasture_id` for an own-ranch rotation, or a `contract_id` for a vegetation-management engagement on customer land. Sending both, or neither, is a shape violation under §2.8. Own-ranch planning runs two checks: the pasture overlap rule rejects the new move with `ERR_PASTURE_OVERLAP` (HTTP 409) when another move on the same pasture in `PLANNED` or `ACTIVE` status has its `move_start` strictly before the new move's `move_end` while the new move's `move_start` is strictly before that move's `move_end` — because intervals are half-open, back-to-back moves that merely touch at a boundary are allowed; and the capacity rule rejects with `ERR_CAPACITY_EXCEEDED` (HTTP 422) when `head_count` exceeds the pasture's `carrying_capacity_head`.

Activation (`PLANNED -> ACTIVE`) is allowed to both the manager and the range hand and is gated four ways: the logical clock must have reached `move_start` but not yet `move_end`; for a contract move, the contract must currently be `ACTIVE`, otherwise `ERR_CONTRACT_INVALID_STATE` (HTTP 409); for a contract move, `head_count` must lie within the contract's `min_head` to `max_head` inclusive, otherwise `ERR_HEAD_OUT_OF_CONTRACT_RANGE` (HTTP 422); and for any move, `head_count` must not exceed the flock's `current_headcount`, otherwise `ERR_INSUFFICIENT_HEAD` (HTTP 422). Planning a contract move against a contract that is not `ACTIVE` is likewise rejected with `ERR_CONTRACT_INVALID_STATE`. Activating or completing (`ACTIVE -> COMPLETED`) an own-ranch move recomputes the pasture's `occupied_head_count` and `pasture_status` — completion may flip the pasture from `OCCUPIED` to `RESTING`. Contract moves never touch pasture occupancy, because customer land is not a `Pasture`. A move can be cancelled only from `PLANNED`, either explicitly by the manager or hand, or by the system cascades described in §3.7 and §3.8; any other transition attempt is rejected with `ERR_MOVE_INVALID_STATE` (HTTP 409). Moves are listed with `limit` and `offset`, filterable by `flock_id`, `pasture_id`, `contract_id`, and `move_status`.

Parasite control is recorded per flock. The manager or a range hand records a treatment with `product_name`, `treatment_date`, a `withdrawal_days` meat-withdrawal period (zero or more), and a `fecal_egg_count_before` EPG reading (zero or more). The system computes the treatment's `withdrawal_until` as `treatment_date` plus `withdrawal_days` calendar days, and recomputes the flock's `withdrawal_until` as the latest `withdrawal_until` among the flock's treatments whose withdrawal moment is strictly after the logical clock — treatments whose withdrawal has already passed do not extend the gate, and the flock value is null when no live withdrawal remains. That gate is enforced at meat-sale booking time in §3.6.

Fourteen days after treatment, a follow-up posts the `fecal_egg_count_after` reading (zero or more; null until posted). The system then computes `efficacy_pct` as the reduction from `fecal_egg_count_before` to `fecal_egg_count_after`, divided by `fecal_egg_count_before`, multiplied by 100 and rounded half-up to one decimal place; when `fecal_egg_count_before` is zero the efficacy is null rather than computed. A `resistance_flag` is set to true exactly when `efficacy_pct` is not null and is strictly below 80.0 — an efficacy of exactly 80.0 leaves the flag false. The follow-up write increments the treatment's `version`. Treatments are listed with `limit` and `offset`, filterable by `flock_id`, and a single treatment read returns the computed `withdrawal_until`, `efficacy_pct`, and `resistance_flag`.

### 3.3. Shearing Crews, Bookings, and Clip Intake

The manager registers a shearing crew with a unique `crew_name`, a `head_per_day_capacity` of at least 1 (the head the crew can shear per calendar day), and a `daily_rate_cents` day rate (zero or more). A crew starts `ACTIVE` in its `crew_status`. Taking a crew off the board (`ACTIVE -> INACTIVE`) is blocked while any of its events is still `SCHEDULED` or `IN_PROGRESS`, surfacing `ERR_CREW_BUSY` (HTTP 409).

Booking a shearing event pairs a `flock_id` with a `crew_id` over a window from `scheduled_start` to `scheduled_end` (start strictly before end) for an `expected_head` of at least 1 and at most the flock's `current_headcount`. Three booking rules then apply in order after the universal layers of §2.8. First, the crew must be `ACTIVE`, else `ERR_CREW_INACTIVE` (HTTP 409). Second, the sanitation-buffer overlap rule: the booking is rejected with `ERR_CREW_OVERLAP` (HTTP 409) when another event on the same crew in `SCHEDULED` or `IN_PROGRESS` status is separated from the new window by less than a full 24-hour buffer on both sides — the booking survives only if it starts at or later than 24 hours after the other event's end, or its own end is at or earlier than 24 hours before the other event's start. Unlike pasture moves, mere adjacency is forbidden here: back-to-back bookings without a 24-hour gap fail. Third, the feasibility rule: the number of whole calendar days contained in the half-open booking window, multiplied by the crew's `head_per_day_capacity`, must be at least `expected_head`, else `ERR_SHEARING_WINDOW_INFEASIBLE` (HTTP 422). So a booking that names an inactive crew and also describes an infeasible window surfaces `ERR_CREW_INACTIVE`, the earlier check.

A booked event starts in `SCHEDULED` `shearing_status`. The manager or a range hand moves it `SCHEDULED -> IN_PROGRESS` once the logical clock has reached `scheduled_start`, or cancels it from `SCHEDULED` (`SCHEDULED -> CANCELLED`); any other transition is rejected with `ERR_SHEARING_INVALID_STATE` (HTTP 409). Completion (`IN_PROGRESS -> COMPLETED`) records the floor tallies: a `shorn_head_count` of at least 1, a `greasy_weight_lbs` strictly above 0, and a `skirtings_weight_lbs` of zero or more but strictly below `greasy_weight_lbs`.

Completion fires the clip cascade: exactly one wool clip is created per completed shearing event, keyed by `shearing_event_id` (the relationship is one-to-one), with `flock_id` copied from the event and `greasy_weight_lbs` and `skirtings_weight_lbs` copied from the tallies. The clip is discoverable by filtering the clip list by `shearing_event_id`, which returns an array of length zero or one; the list also filters by `flock_id`. Every clip maintains a weight-conservation invariant, recomputed whenever lots are created, graded, or deleted: `allocated_weight_lbs` is the sum of `weight_lbs` over the clip's lots; `unallocated_weight_lbs` is `greasy_weight_lbs` minus `skirtings_weight_lbs` minus `allocated_weight_lbs`; and `clip_value_cents` is the sum of `effective_value_cents` over the clip's lots. The clip's `marketing_posture` summarizes its lots: `UNGRADED` when the clip has no lots at all; `GRADING` when lots exist but none is `CONSIGNED`, `SOLD`, or `SETTLED`; `MARKETING` when at least one lot is `CONSIGNED` or `SOLD`; and `SETTLED_OUT` when the clip has at least one lot, every lot is `SETTLED`, and `unallocated_weight_lbs` is exactly zero. Shearing events are listed with `limit` and `offset`, filterable by `flock_id`, `crew_id`, and `shearing_status`.

### 3.4. Wool Lot Grading and Core-Test Certification

Lots are baled off a clip by the manager, who supplies the `clip_id`, a `lot_code` unique within the clip, and a `weight_lbs` strictly above 0. The allocation rule caps `weight_lbs` at the clip's current `unallocated_weight_lbs` — exact equality is allowed and fully allocates the clip — and any excess is rejected with `ERR_WEIGHT_OVER_ALLOCATED` (HTTP 422). A lot starts in `DRAFT` `lot_status`, and while it remains `DRAFT` it can be deleted outright, which releases its weight back into the clip's unallocated balance as the compensating action for the weight invariant; deleting a lot in any other status is rejected with `ERR_LOT_INVALID_STATE` (HTTP 409).

Grading assigns the classer's visual estimate: grading a `DRAFT` lot with an `estimated_micron` strictly above 0 moves it `DRAFT -> GRADED`, bands its `grade_code`, and computes its `provisional_value_cents`. The grade bands key off `effective_micron` — the `certified_micron` when a locked core test exists for the lot, otherwise the `estimated_micron` — with lower bounds inclusive: strictly below 19.5 microns is `SUPERFINE`; 19.5 up to but not including 21.5 is `FINE` (so exactly 19.5 is `FINE`); 21.5 up to but not including 24.5 is `MEDIUM`; 24.5 up to but not including 27.5 is `STRONG`; and 27.5 or above is `COARSE` (so exactly 27.5 is `COARSE`). The provisional value multiplies `weight_lbs` by the greasy-pound price of the band — 380 cents per greasy pound for `SUPERFINE`, 330 for `FINE`, 260 for `MEDIUM`, 190 for `STRONG`, and 120 for `COARSE` — rounded half-up to a whole cent. Grading also recomputes the parent clip's allocation, value, and posture per §3.3.

Regrading is a deliberate two-step. Moving a `GRADED` lot into `REGRADING` is refused with `ERR_DUPLICATE_ACTIVE_TEST` (HTTP 409) while the lot has any core test in `SUBMITTED`, `RESULTED`, or `LOCKED`. Recording the regrade moves the lot `REGRADING -> GRADED`, requires a fresh `estimated_micron` strictly above 0, and is one of the system's two optimistic-concurrency points: the request must carry `expected_wool_lot_version` equal to the lot's current `version`, and a mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412) exactly as §2.6 describes. A successful regrade stores the new estimate, rebands `grade_code`, recomputes `provisional_value_cents`, and increments the lot's `version`. The lot's remaining transitions are driven by the consignment pipeline of §3.5: consignment moves it `GRADED -> CONSIGNED` (or `WITHDRAWN -> CONSIGNED` when a previously withdrawn lot is re-consigned), the pool sale moves it `CONSIGNED -> SOLD`, settlement moves it `SOLD -> SETTLED` (also recomputing the clip's `marketing_posture`), and consignment withdrawal moves it `CONSIGNED -> WITHDRAWN`. Lots are listed with `limit` and `offset`, filterable by `clip_id` and `lot_status`, and a single lot read exposes the full value stack — `estimated_micron`, `certified_micron`, `certified_yield_pct`, `effective_micron`, `grade_code`, `provisional_value_cents`, `certified_value_cents`, and `effective_value_cents`.

Independent certification comes from the wool pool's core lab. A `WoolPoolOperator` submits a core test for a lot with `lot_id` and a `lab_ref` certificate reference; submission is allowed only while the lot is `GRADED` or `CONSIGNED` (otherwise `ERR_LOT_INVALID_STATE`, HTTP 409) and only while no other test of the same lot sits in `SUBMITTED`, `RESULTED`, or `LOCKED` (otherwise `ERR_DUPLICATE_ACTIVE_TEST`, HTTP 409) — and under the pipeline ordering, a submission naming an unknown lot surfaces `ERR_NOT_FOUND` before either of those business checks runs. The server records the caller as `submitted_by_user_id`. The operator then posts the lab numbers — `measured_micron` strictly above 0, `clean_yield_pct` between 0 and 100, and `vegetable_matter_pct` between 0 and 100 (the two percentages inclusive at both ends) — moving the test `SUBMITTED -> RESULTED` and storing all three values, which remain null until then.

Locking is the ranch's acceptance of the lab result and is performed by the manager under segregation of duties: the `X-User-ID` of the locking manager must differ from the test's `submitted_by_user_id`, else `ERR_CORE_TEST_SOD` (HTTP 403). A successful lock (`RESULTED -> LOCKED`) stamps `locked_by_user_id` and fires a two-link cascade. Link one reprices the lot: `certified_micron` takes `measured_micron`, `certified_yield_pct` takes `clean_yield_pct`, `grade_code` is rebanded from the certified micron, and `certified_value_cents` is computed on a clean basis — the lot's `weight_lbs` multiplied by `certified_yield_pct` divided by 100, kept at full precision without intermediate rounding, then multiplied by the clean-pound price of the certified band (720 cents per clean pound for `SUPERFINE`, 640 for `FINE`, 520 for `MEDIUM`, 400 for `STRONG`, and 280 for `COARSE`) and rounded half-up to a whole cent; from that moment `effective_value_cents` is the certified value, superseding the provisional one, and the lot's `version` increments. Link two reaches the consignment: if the lot currently has a consignment in `ACCEPTED` or `ADVANCED`, that consignment's `version` increments, and when it is `ADVANCED` its `pending_clawback_cents` is set to the excess of `advance_cents` over 70 percent of the new `certified_value_cents` (that product rounded half-up), or zero when the certified value has grown enough to cover the advance. A test can also be rejected — from `SUBMITTED` or from `RESULTED` — moving it to `REJECTED`, after which a fresh core test may be created for the lot. Any transition outside this machine is rejected with `ERR_CORE_TEST_INVALID_STATE` (HTTP 409). Core tests are listed with `limit` and `offset`, filterable by `lot_id` and `test_status`.

### 3.5. Pool Consignment, Advances, and Settlement

The manager tenders a `GRADED` or `WITHDRAWN` lot to a wool pool by creating a consignment with `lot_id` and a `pool_ref` sale-season identifier such as `WWPA-2026A`; tendering moves the lot to `CONSIGNED`. A lot may have only one open consignment at a time — creating one while another consignment of the same lot is `TENDERED`, `ACCEPTED`, `ADVANCED`, or `SOLD` is rejected with `ERR_CONSIGNMENT_ALREADY_OPEN` (HTTP 409). The new consignment starts in `TENDERED` `consignment_status` with `advance_cents`, `pending_clawback_cents`, and `clawback_cents` at zero and the sale fields null.

From `TENDERED`, the pool operator either accepts (`TENDERED -> ACCEPTED`) or rejects (`TENDERED -> REJECTED`); rejection is cross-entity, returning the lot from `CONSIGNED` to `GRADED` and incrementing the lot's `version`. Once `ACCEPTED`, the operator may post the advance (`ACCEPTED -> ADVANCED`): `advance_cents` becomes 70 percent of the lot's `effective_value_cents` at that moment — certified when a locked core test exists, provisional otherwise — rounded half-up to a whole cent. Withdrawal is the manager's exit: from `ACCEPTED` it simply moves the consignment to `WITHDRAWN` and the lot from `CONSIGNED` to `WITHDRAWN`; from `ADVANCED` it additionally performs the full clawback, setting `clawback_cents` equal to `advance_cents` as the compensating action for the advance invariant, with the same lot transition.

The pool operator records the auction outcome on an `ADVANCED` consignment by submitting `sale_gross_cents` (zero or more), moving the consignment to `SOLD` and the lot from `CONSIGNED` to `SOLD` in the same step. Settlement (`SOLD -> SETTLED`, again the operator) prices the pool's fee and closes the lot. The fee is tiered on the pool's total consigned weight: the system first sums `weight_lbs` over every consignment sharing the same `pool_ref` whose status is `ACCEPTED`, `ADVANCED`, `SOLD`, or `SETTLED`, including the lot being settled; that total determines the tier — strictly below 10,000 pounds the fee is 6.5 percent, from 10,000 pounds up to but not including 25,000 pounds it is 5.0 percent (so a pool total of exactly 10,000 pounds lands in the 5.0 percent band), and at 25,000 pounds or more it is 4.0 percent. `pool_fee_cents` is then `sale_gross_cents` multiplied by the tier percentage divided by 100, rounded half-up to a whole cent, and `settlement_cents` is `sale_gross_cents` minus `pool_fee_cents` minus `advance_cents` in integer arithmetic — which may be negative, in which case the grower repays the difference. Settlement moves the lot `SOLD -> SETTLED`, increments both versions, and recomputes the clip's `marketing_posture`. Every undefined consignment transition is rejected with `ERR_CONSIGNMENT_INVALID_STATE` (HTTP 409). Consignments are listed with `limit` and `offset`, filterable by `lot_id`, `pool_ref`, and `consignment_status`.

The pool statement is a computed read keyed by `pool_ref`, available to the manager and the pool operator. It aggregates only the pool's `SETTLED` consignments and reports `pool_ref`, `consignment_count`, `total_sale_gross_cents`, `total_pool_fee_cents`, `total_advance_cents`, and `total_settlement_cents`. Rounding order is pinned: each lot's fee and settlement are rounded to whole cents first, and the statement sums those already-rounded per-lot figures — never sum-then-round. A `pool_ref` with no consignments at all is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 3.6. Livestock Sales, Holiday Premiums, and Delivery

Ethnic-holiday demand is published ahead of the season: the manager creates holiday windows with a unique `holiday_name` (for example `EID_AL_ADHA`, `EASTER`, `ORTHODOX_EASTER`, or `CHRISTMAS`), a half-open premium window from `window_start` (inclusive) to `window_end` (exclusive), a `premium_pct` between 0 and 100 applied to the gross of qualifying `ETHNIC_MARKET` sales, and a `min_head` volume gate of at least 1 — sales at or above `min_head` earn the full premium, smaller lots earn half.

A sale is booked by the manager with a `flock_id`, a `sale_type` of `MEAT` or `BREEDING`, a `channel` of `AUCTION`, `DIRECT`, or `ETHNIC_MARKET`, a `head_count` of at least 1 and at most the flock's `current_headcount` (otherwise `ERR_INSUFFICIENT_HEAD`, HTTP 422), and a `scheduled_date`. The conditional field shape of §2.8 applies: `MEAT` bookings must supply `avg_weight_lbs` and `base_price_per_cwt_cents` (both strictly positive) and must not supply `per_head_price_cents`; `BREEDING` bookings are exactly the inverse, supplying `per_head_price_cents` (strictly positive) and neither meat field. The optional `shrink_pct` pencil-shrink percentage (0 to 100, default 0) is applied only when the channel is `DIRECT`. One safety gate stands in front of every `MEAT` booking: when the flock's `withdrawal_until` (§3.2) is set, the `scheduled_date` must fall on or after it — a sale scheduled on the exact withdrawal expiry moment is allowed, and anything earlier is rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 422).

Booking computes and stores `booked_price_cents`, the amount the buyer must pay. For `MEAT` sales the pipeline runs in a pinned order — gross, then premium, then commission, then total. Gross is `head_count` multiplied by `avg_weight_lbs`, multiplied by the shrink factor (one minus `shrink_pct` hundredths for `DIRECT`, or one — no shrink — for the other channels), multiplied by `base_price_per_cwt_cents` and divided by 100 to convert the per-hundredweight price, rounded half-up to whole cents. The premium applies only to `ETHNIC_MARKET`: the system selects the holiday window whose half-open interval contains `scheduled_date`, ranking eligible windows by highest `premium_pct` first and breaking ties by the earliest `window_start` and then the earliest `created_at`; when no window applies, `premium_pct_applied` is 0 and `applied_holiday_name` is null. When a window applies, `premium_pct_applied` is the window's full `premium_pct` when `head_count` reaches the window's `min_head`, or half of `premium_pct` when it falls short, and the selected window's `holiday_name` is stored in `applied_holiday_name`; the premium itself is the gross multiplied by `premium_pct_applied` and divided by 100, rounded half-up. The commission applies only to `AUCTION`: 3.5 percent of the gross, rounded half-up, but capped at 15,000 cents — the commission is the lesser of the two figures. The booked total is gross plus premium minus commission. For `BREEDING` sales there is no shrink, premium, or commission: the booked total is simply `head_count` multiplied by `per_head_price_cents`.

A sale carries two independent state dimensions, `payment_status` and `delivery_status`, which evolve separately. Payment starts `UNPAID` and moves `UNPAID -> PAID` when the manager records a payment whose `amount_cents` equals the `booked_price_cents` exactly — any other amount is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422) — and only while `delivery_status` is `PENDING` or `LOADED`; a payment attempted on a `CANCELLED` or `DELIVERED` sale is rejected with `ERR_SALE_INVALID_STATE` (HTTP 409). Delivery starts `PENDING`. Loading the truck (`PENDING -> LOADED`, manager or hand) requires payment to be `PAID`, else `ERR_SALE_UNPAID` (HTTP 409). Delivery (`LOADED -> DELIVERED`, manager or hand) requires the actuals: `actual_total_weight_lbs`, the scale weight, for `MEAT`, or `actual_head_delivered` for `BREEDING` — each null until this point. Delivery computes `settled_price_cents`, the settled variant of the same pricing pipeline run on actuals: for `MEAT`, the gross is recomputed from `actual_total_weight_lbs` in place of the booked `head_count`-times-`avg_weight_lbs` figure (shrink, premium, and commission rules unchanged); for `BREEDING`, it is `actual_head_delivered` multiplied by `per_head_price_cents`. The settled price diverges from `booked_price_cents` whenever the actuals differ from the booking. Delivery also decrements the flock per the headcount ledger of §2.10 — by `head_count` for `MEAT`, by `actual_head_delivered` for `BREEDING` — incrementing the flock's `version`. Cancelling is allowed only from `PENDING` (`PENDING -> CANCELLED`, manager); when the sale is already `PAID`, cancellation refunds it in the same step (`PAID -> REFUNDED`) as compensation. A cancel attempted after loading, or any operation that does not match the current dimension states, is rejected with `ERR_SALE_INVALID_STATE`. Sales are listed with `limit` and `offset`, filterable by `flock_id` and `delivery_status`, and a single sale read returns both dimensions plus all price fields.

### 3.7. Predator Losses and Verification Fallout

When carcasses are found, the manager or a range hand files a loss report with `flock_id`, `loss_date`, a `head_lost` of at least 1 and at most the flock's `current_headcount` (otherwise `ERR_INSUFFICIENT_HEAD`), a `predator_type` of `COYOTE`, `MOUNTAIN_LION`, `BEAR`, `DOG`, `EAGLE`, or `UNKNOWN`, and a `guardian_on_duty` flag recording whether a guardian animal was with the bunch — context for the review alongside the flock's `guardian_dog_count`, but never a gate on the outcome. The report starts in `REPORTED` `report_status`.

Verification is the manager's desk workflow. Moving `REPORTED -> UNDER_REVIEW` stamps `reviewed_by_user_id` with the caller's `X-User-ID`. From `UNDER_REVIEW` the manager either verifies (`UNDER_REVIEW -> VERIFIED`) or dismisses (`UNDER_REVIEW -> DISMISSED`); dismissal is also available directly from `REPORTED`. Any other transition is rejected with `ERR_REPORT_INVALID_STATE` (HTTP 409).

Verification fires the heaviest cascade in the system, three links deep. Link one writes the loss into the flock ledger: `current_headcount` drops by `head_lost` and the flock's `version` increments. Link two sweeps the flock's grazing contracts: every contract in `ACTIVE` status whose `min_head` now exceeds the reduced headcount has its `breach_flag` set to true and its `version` incremented. Link three cleans up the breached contracts' books: every grazing move whose `contract_id` is one of the newly breached contracts and whose `move_status` is still `PLANNED` is moved to `CANCELLED`, each incrementing its own `version`. A report that is dismissed touches nothing. Loss reports are listed with `limit` and `offset`, filterable by `flock_id` and `report_status`.

### 3.8. Vegetation-Management Grazing Contracts

The manager drafts a grazing contract with a `flock_id`, the customer's `client_org_name`, a free-text `parcel_name` describing the customer land (customer parcels are never `Pasture` rows), a half-open service window from `service_window_start` (inclusive) to `service_window_end` (exclusive, start strictly before end), a `rate_per_head_day_cents` strictly above 0, a head band from `min_head` (at least 1) to `max_head` (at least `min_head`), and a `target_cover_reduction_pct` between 0 and 100 for the performance bonus. The contract starts in `DRAFT` `contract_status` with `terms_version` at 1, `breach_flag` false, and `achieved_cover_reduction_pct`, `head_days`, and `invoice_cents` null until completion.

Negotiation is a bounded cycle. The manager proposes (`DRAFT -> PROPOSED`), which requires the flock's `current_headcount` to be at least `min_head`, else `ERR_INSUFFICIENT_HEAD` (HTTP 422). The client counters (`PROPOSED -> COUNTERED`) through the system's second optimistic-concurrency point: the request must carry `expected_grazing_contract_version` matching the contract's current `version`, else `ERR_STALE_CONTRACT_VERSION` (HTTP 412) per §2.6. Any term fields supplied with the counter — `rate_per_head_day_cents`, `min_head`, `max_head`, `service_window_start`, or `service_window_end` — overwrite the standing terms, and `terms_version` increments by 1 on every counter. The ranch may then adopt the countered terms as the standing proposal (`COUNTERED -> PROPOSED`), or accept the client's counter outright (`COUNTERED -> ACCEPTED`); the client for its part accepts a standing proposal (`PROPOSED -> ACCEPTED`). Either party may cancel — moving the contract to `CANCELLED` — from `DRAFT`, `PROPOSED`, `COUNTERED`, or `ACCEPTED`. Activation (`ACCEPTED -> ACTIVE`) is the manager's step and is window-gated: the logical clock must sit inside the service window — at or after `service_window_start` and strictly before `service_window_end` — else `ERR_CONTRACT_WINDOW_CLOSED` (HTTP 422). Every transition not defined from the current state is rejected with `ERR_CONTRACT_INVALID_STATE` (HTTP 409).

While a contract is `ACTIVE`, the flock works the parcel through contract grazing moves (§3.2) whose `contract_id` points at the contract; activation of each such move enforces the contract head band and the contract's `ACTIVE` status. Completion (`ACTIVE -> COMPLETED`) is the manager's step once the logical clock has reached `service_window_end` — earlier completion is rejected with `ERR_CONTRACT_WINDOW_CLOSED` — and carries the measured `achieved_cover_reduction_pct` between 0 and 100.

Completion computes the invoice in a pinned order. First, `head_days` sums, over the contract's moves in `COMPLETED` status only (`PLANNED` and `CANCELLED` moves are excluded), each move's `head_count` multiplied by its overlap days — the whole calendar days in the intersection of the move's half-open occupancy window and the contract's half-open service window, that is, from the later of `move_start` and `service_window_start` up to but not including the earlier of `move_end` and `service_window_end`, with a move lying entirely outside the service window contributing zero. Second, the gross is `head_days` multiplied by `rate_per_head_day_cents`. Third, the bonus applies when `achieved_cover_reduction_pct` reaches `target_cover_reduction_pct` — exact equality qualifies — and is the lesser of 10 percent of the gross (rounded half-up) and 250,000 cents, or zero when the target is missed. Fourth, the penalty is 20 percent of the gross, rounded half-up, when `breach_flag` is true, else zero. Fifth, `invoice_cents` is the gross plus the bonus minus the penalty, and both `head_days` and `invoice_cents` are stored on the completed contract. Completion then cascades across the contract's remaining moves: every move still `PLANNED` becomes `CANCELLED`, and every move still `ACTIVE` becomes `COMPLETED`, each incrementing its own `version`. Contracts are listed with `limit` and `offset`, filterable by `flock_id` and `contract_status`.

## 4. Endpoint Definitions

All endpoints live under the `/api` prefix. Resource-creating calls return 201 with the created resource; modifications, transitions, and action calls return 200 with the updated resource; the single deletion endpoint returns 204 with no body. All other request/response detail is defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/flocks | Create a flock with its baseline headcount | RanchManager |
| GET | /api/flocks | List flocks with pagination and optional filters | RanchManager, RangeHand, WoolPoolOperator, GrazingClient |
| GET | /api/flocks/{id} | Read one flock including computed current_headcount and withdrawal_until | RanchManager, RangeHand, WoolPoolOperator, GrazingClient |
| POST | /api/flocks/{id}/retire | Retire a flock once it has no busy children | RanchManager |
| POST | /api/breeding-seasons | Open a breeding/lambing season for a flock (one open season per flock) | RanchManager |
| GET | /api/breeding-seasons | List seasons, filterable by flock and status | RanchManager, RangeHand |
| GET | /api/breeding-seasons/{id} | Read one season including computed totals and lambing rate | RanchManager, RangeHand |
| POST | /api/breeding-seasons/{id}/transitions | Advance or cancel the season (to: BREEDING, GESTATION, LAMBING, WEANING, CLOSED, CANCELLED) | RanchManager |
| POST | /api/birth-records | Log a lambing/kidding batch against a LAMBING season | RanchManager, RangeHand |
| GET | /api/birth-records | List birth records, filterable by season | RanchManager, RangeHand |
| GET | /api/birth-records/{id} | Read one birth record | RanchManager, RangeHand |
| POST | /api/pastures | Create a pasture with carrying capacity | RanchManager |
| GET | /api/pastures/{id} | Read one pasture including occupancy and status | RanchManager, RangeHand |
| POST | /api/grazing-moves | Plan a rotation move (own-ranch via pasture, or contract grazing via contract) | RanchManager, RangeHand |
| GET | /api/grazing-moves | List moves, filterable by flock, pasture, contract, and status | RanchManager, RangeHand, GrazingClient |
| GET | /api/grazing-moves/{id} | Read one move | RanchManager, RangeHand, GrazingClient |
| POST | /api/grazing-moves/{id}/transitions | Move lifecycle (to: ACTIVE, COMPLETED, CANCELLED) | RanchManager, RangeHand |
| POST | /api/parasite-treatments | Record a deworming treatment with withdrawal days and pre-treatment EPG | RanchManager, RangeHand |
| GET | /api/parasite-treatments | List treatments, filterable by flock | RanchManager, RangeHand |
| GET | /api/parasite-treatments/{id} | Read one treatment including withdrawal and efficacy computations | RanchManager, RangeHand |
| POST | /api/parasite-treatments/{id}/follow-up | Post the 14-day follow-up EPG; computes efficacy and resistance flag | RanchManager, RangeHand |
| POST | /api/shearing-crews | Register a shearing crew | RanchManager |
| GET | /api/shearing-crews/{id} | Read one crew | RanchManager, RangeHand |
| POST | /api/shearing-crews/{id}/deactivate | Take a crew off the board (blocked while booked) | RanchManager |
| POST | /api/shearing-events | Book a shearing window for a flock with a crew | RanchManager |
| GET | /api/shearing-events | List shearing events, filterable by flock, crew, and status | RanchManager, RangeHand |
| GET | /api/shearing-events/{id} | Read one shearing event | RanchManager, RangeHand |
| POST | /api/shearing-events/{id}/transitions | Shearing lifecycle (to: IN_PROGRESS, CANCELLED) | RanchManager, RangeHand |
| POST | /api/shearing-events/{id}/complete | Complete the shearing with tallies; creates the wool clip | RanchManager, RangeHand |
| GET | /api/wool-clips | List clips, filterable by flock and shearing event | RanchManager, RangeHand, WoolPoolOperator |
| GET | /api/wool-clips/{id} | Read one clip including weight reconciliation and marketing posture | RanchManager, RangeHand, WoolPoolOperator |
| POST | /api/wool-lots | Bale a lot off a clip (weight allocation check) | RanchManager |
| GET | /api/wool-lots | List lots, filterable by clip and status | RanchManager, RangeHand, WoolPoolOperator |
| GET | /api/wool-lots/{id} | Read one lot including grade and value fields | RanchManager, RangeHand, WoolPoolOperator |
| POST | /api/wool-lots/{id}/grade | Grade a DRAFT lot | RanchManager |
| POST | /api/wool-lots/{id}/transitions | Lot lifecycle (to: REGRADING) | RanchManager |
| POST | /api/wool-lots/{id}/regrade | Record the regrade (REGRADING to GRADED); stale-version guarded | RanchManager |
| DELETE | /api/wool-lots/{id} | Delete a DRAFT lot, releasing its weight allocation | RanchManager |
| POST | /api/core-tests | Submit a core-sample test for a GRADED or CONSIGNED lot | WoolPoolOperator |
| GET | /api/core-tests | List core tests, filterable by lot and status | RanchManager, WoolPoolOperator |
| GET | /api/core-tests/{id} | Read one core test | RanchManager, WoolPoolOperator |
| POST | /api/core-tests/{id}/results | Post lab results (SUBMITTED to RESULTED) | WoolPoolOperator |
| POST | /api/core-tests/{id}/transitions | Test disposition (to: LOCKED, REJECTED); locking enforces segregation of duties and fires the repricing cascade | RanchManager |
| POST | /api/consignments | Tender a GRADED or WITHDRAWN lot to a wool pool | RanchManager |
| GET | /api/consignments | List consignments, filterable by lot, pool, and status | RanchManager, WoolPoolOperator |
| GET | /api/consignments/{id} | Read one consignment | RanchManager, WoolPoolOperator |
| POST | /api/consignments/{id}/transitions | Consignment lifecycle (to: ACCEPTED, REJECTED, ADVANCED, WITHDRAWN, SETTLED) | RanchManager, WoolPoolOperator |
| POST | /api/consignments/{id}/sell | Record the pool sale gross for an ADVANCED consignment | WoolPoolOperator |
| GET | /api/pool-statements/{pool_ref} | Computed pool statement: per-lot rounded settlements summed | RanchManager, WoolPoolOperator |
| POST | /api/holiday-windows | Publish an ethnic-holiday premium window for the meat channel | RanchManager |
| POST | /api/livestock-sales | Book a meat or breeding-stock sale; computes the booked price | RanchManager |
| GET | /api/livestock-sales | List sales, filterable by flock and delivery status | RanchManager, RangeHand |
| GET | /api/livestock-sales/{id} | Read one sale (both state dimensions and price fields) | RanchManager, RangeHand |
| POST | /api/livestock-sales/{id}/record-payment | Record full payment of the booked price | RanchManager |
| POST | /api/livestock-sales/{id}/load | Load the truck; requires payment recorded | RanchManager, RangeHand |
| POST | /api/livestock-sales/{id}/deliver | Deliver with scale ticket or head count; computes the settled price and decrements the flock | RanchManager, RangeHand |
| POST | /api/livestock-sales/{id}/cancel | Cancel a PENDING sale; refunds when already paid | RanchManager |
| POST | /api/loss-reports | Report a predator loss | RanchManager, RangeHand |
| GET | /api/loss-reports | List loss reports, filterable by flock and status | RanchManager, RangeHand |
| GET | /api/loss-reports/{id} | Read one loss report | RanchManager, RangeHand |
| POST | /api/loss-reports/{id}/transitions | Loss verification (to: UNDER_REVIEW, VERIFIED, DISMISSED); verification fires the headcount, breach, and move cascade | RanchManager |
| POST | /api/grazing-contracts | Draft a vegetation-management grazing contract | RanchManager |
| GET | /api/grazing-contracts | List contracts, filterable by flock and status | RanchManager, GrazingClient |
| GET | /api/grazing-contracts/{id} | Read one contract | RanchManager, GrazingClient |
| POST | /api/grazing-contracts/{id}/transitions | Negotiation and lifecycle (to: PROPOSED, ACCEPTED, ACTIVE, CANCELLED) | RanchManager, GrazingClient |
| POST | /api/grazing-contracts/{id}/counter | Client counter-offer (PROPOSED to COUNTERED); stale-version guarded; bumps terms_version | GrazingClient |
| POST | /api/grazing-contracts/{id}/complete | Complete an ACTIVE contract after the window; computes head-days and invoice | RanchManager |
| POST | /api/_clock/set_current_utc | Test-driving endpoint: set the logical clock (startup default 2026-08-01T00:00:00Z) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the identifier-to-status map only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_FLOCK_RETIRED | 409 |
| ERR_FLOCK_BUSY | 409 |
| ERR_SEASON_INVALID_STATE | 409 |
| ERR_SEASON_TOO_EARLY | 422 |
| ERR_OPEN_SEASON_EXISTS | 409 |
| ERR_BIRTH_OUTSIDE_WINDOW | 422 |
| ERR_BIRTH_COUNT_MISMATCH | 422 |
| ERR_MOVE_INVALID_STATE | 409 |
| ERR_PASTURE_OVERLAP | 409 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_HEAD_OUT_OF_CONTRACT_RANGE | 422 |
| ERR_SHEARING_INVALID_STATE | 409 |
| ERR_CREW_INACTIVE | 409 |
| ERR_CREW_BUSY | 409 |
| ERR_CREW_OVERLAP | 409 |
| ERR_SHEARING_WINDOW_INFEASIBLE | 422 |
| ERR_LOT_INVALID_STATE | 409 |
| ERR_WEIGHT_OVER_ALLOCATED | 422 |
| ERR_CORE_TEST_INVALID_STATE | 409 |
| ERR_DUPLICATE_ACTIVE_TEST | 409 |
| ERR_CORE_TEST_SOD | 403 |
| ERR_CONSIGNMENT_INVALID_STATE | 409 |
| ERR_CONSIGNMENT_ALREADY_OPEN | 409 |
| ERR_SALE_INVALID_STATE | 409 |
| ERR_SALE_UNPAID | 409 |
| ERR_WITHDRAWAL_ACTIVE | 422 |
| ERR_INSUFFICIENT_HEAD | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_REPORT_INVALID_STATE | 409 |
| ERR_CONTRACT_INVALID_STATE | 409 |
| ERR_CONTRACT_WINDOW_CLOSED | 422 |
| ERR_STALE_LOT_VERSION | 412 |
| ERR_STALE_CONTRACT_VERSION | 412 |
