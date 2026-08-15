# Cheer & Dance Competition Management API — Product Requirements Document

## 1. Introduction

Running a varsity-style cheer and dance championship is an exercise in controlled choreography long before any athlete takes the mat. Divisions must be classified by discipline, skill level, and age grid; rosters must satisfy size floors and ceilings while respecting athlete crossover limits; judges must be empaneled, certified for the level they score, and kept firewalled from the appeals they later review. Once the event goes live, every routine produces measured durations, boundary observations, and safety legality calls that feed a weighted scoring model, a deduction pipeline with a two-round appeal loop, and ultimately a division ranking that determines which teams earn paid and at-large bids to the championship. Around the competition itself, warm-up mats must be booked without collisions and with mandatory rest before performance time, routine music must clear licensing review, and spectators buy session tickets under advance/gate pricing with group discounts and short payment holds.

This document specifies a REST API that orchestrates that entire operation. The intended operators are the event director staff who configure and run the competition, team coaches who manage rosters and music, three distinct judging roles with segregated duties, a music licensing reviewer, an eligibility officer, and spectators purchasing tickets. The API is mounted under `/api`. It governs the full lifecycle — event setup, registration, scheduling, live scoring, deduction appeals, bid distribution, and finalization — under a single logical clock so that time-sensitive rules (appeal windows, bid deadlines, ticket holds, price-tier cutoffs) are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelope, pagination, concurrency control, and the cross-cutting invariants that hold across every workflow in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Eight roles are recognized, spelled exactly as follows: `EventDirector`, `TeamCoach`, `Judge`, `HeadJudge`, `SafetyJudge`, `MusicCompliance`, `EligibilityOfficer`, and `Spectator`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the endpoint's authorized roles — or that fails the endpoint's ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role and are binding:

- When `X-User-Role` is `Judge`, `HeadJudge`, or `SafetyJudge`, `X-User-ID` is the `id` of the acting `Judge` entity; ownership and authorship checks on any resource that references a `Judge` (for example a score sheet's `judge_id`, a deduction's `applied_by_judge_id`, or an appeal's `decided_by_judge_id`) compare that foreign-key field to `X-User-ID`. The three roles share the same identity pool — a `HeadJudge`'s `X-User-ID` is still a `Judge.id` — which is what makes the segregation-of-duties comparisons in §3.6 meaningful.
- When `X-User-Role` is `TeamCoach`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity of its own; team ownership is established by recording it as `coach_user_id` on the `Team` at registration, and every coach-scoped operation (roster management, check-in, withdrawal, music submission, appeals, bid responses, warm-up booking) compares the team's `coach_user_id` to `X-User-ID`.
- When `X-User-Role` is `Spectator`, `X-User-ID` is likewise opaque; it is captured as `purchaser_user_id` on each `TicketOrder` at creation, and the pay/cancel ownership checks compare that stored field to `X-User-ID`.
- When `X-User-Role` is `EventDirector`, `MusicCompliance`, or `EligibilityOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared against any entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100, and `offset` defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` ascending (oldest first) — never ordered by random identifier. The `meta` envelope of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in this system — events, divisions, teams, athletes, roster entries, judges, performances, score sheets, deductions, appeals, bids, music submissions, sessions, ticket orders, and warm-up assignments — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-07-15T14:03:22.481Z`), set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including automatic mutations caused by cascades and recomputation.

All time-dependent rules in this document — the 45-minute appeal window, the 72-hour bid acceptance deadline, the 15-minute ticket hold, the advance/gate pricing cutoff, and the checkpoint sweeps — are evaluated against a **logical clock**, never the server wall clock. An admin-only test-driving capability, restricted to `EventDirector`, sets the logical clock to a supplied `to_iso8601` instant. Before any such call, the logical clock starts at a fixed default of `2026-08-01T00:00:00Z` and never falls back to wall-clock time. A score sheet's `submitted_at`, a bid's `offered_at`, and every `created_at` timestamp are all readings of this logical clock.

### 2.5. Optimistic Concurrency Control

Three write operations wholesale supersede existing derived state, and each is guarded by an optimistic-concurrency field on the request:

- Regenerating a division's schedule requires `expected_division_version` as a non-optional input field, carrying the client's last observed `version` of the `Division`. If another writer has advanced the division's version since the client last read it — a prior regeneration, or any other division mutation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller's view of the schedule predates a superseding regeneration and must be re-read.
- Amending an `APPLIED` deduction's quantity or skill tier requires `expected_deduction_version`, compared against the `Deduction`'s current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the deduction has changed (a status transition or a prior amendment) since the caller observed it.
- Re-running bid allocation for an event requires `expected_event_version`, compared against the `Event`'s current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because the event has been mutated (status transitions or a prior allocation) since the caller observed it, and re-running allocation supersedes the standing allocation.

Endpoints not listed here do not take a version field.

### 2.6. Validation Order

When a request violates several rules, the rejection is determined by a fixed priority order — the lowest-numbered applicable check wins, so a caller can never observe a business-rule error masking an authentication or shape error. The order is:

1. **Authentication** — the headers and role checks of §2.1 (`ERR_UNAUTHENTICATED`).
2. **Authorization and ownership** — role appears in the endpoint's authorized list; `TeamCoach` operations compare `X-User-ID` to the team's `coach_user_id`, spectator pay/cancel compares to the order's `purchaser_user_id`, and score-sheet edit or submit compares to the sheet's `judge_id` (`ERR_FORBIDDEN`).
3. **Request-body shape** — all required fields present, types correct, enum members valid, and payload-local ranges hold: `quantity` at least 1 and integral, `ends_at` strictly after `starts_at`, `min_age` not greater than `max_age`, `max_athletes` not less than `min_athletes`, `judge_ids` containing 3 to 9 elements, all score fields within 0 to 10, ticket `quantity` within 1 to 40 (`ERR_INVALID_INPUT`).
4. **Existence** — path identifiers resolve left-to-right, then request-body foreign keys (`event_id`, `division_id`, `team_id`, `athlete_id`, `session_id`, and so on) resolve (`ERR_NOT_FOUND`).
5. **OCC** — the `expected_*_version` comparisons of §2.5 (`ERR_STALE_VERSION`).
6. **Event state** — the operation is permitted in the event's current status (`ERR_EVENT_INVALID_STATE`, `ERR_EVENT_NOT_LIVE`).
7. **Team and roster state** — the team's registration and music dimensions permit the operation (`ERR_INVALID_STATE`, `ERR_MUSIC_NOT_VERIFIED`, `ERR_TEAM_NOT_CHECKED_IN`, `ERR_ROSTER_LOCKED`).
8. **Performance and score-sheet state** — the performance or sheet is in a state the operation accepts (`ERR_PERFORMANCE_NOT_PERFORMED`, `ERR_PERFORMANCE_INVALID_STATE`, `ERR_SCORE_SHEET_LOCKED`).
9. **Deduction and music-submission state** (`ERR_DEDUCTION_NOT_APPLIED`, `ERR_INVALID_STATE`, `ERR_MUSIC_STATE_CONFLICT`).
10. **Bid, ticket-order, warm-up, and appeal state** — accept/decline require `OFFERED` (`ERR_BID_NOT_OFFERED`); pay requires `HELD`, cancel requires `HELD` or `PAID`, warm-up release requires `BOOKED`, appeal resolve requires `SUBMITTED`, appeal resubmit requires `REJECTED` (`ERR_INVALID_STATE`); finalization and allocation completeness gates (`ERR_FINALIZE_BLOCKED`).
11. **Safety and segregation** — athlete age eligibility, crossover caps, judge certification, routine legality, reviewer/applier conflicts (`ERR_ATHLETE_AGE_INELIGIBLE`, `ERR_CROSSOVER_LIMIT_EXCEEDED`, `ERR_SAME_DIVISION_CROSSOVER`, `ERR_JUDGE_NOT_CERTIFIED`, `ERR_SKILL_WITHIN_LEGAL_LIMIT`, `ERR_REVIEWER_CONFLICT`, `ERR_SELF_VOID_FORBIDDEN`), all HTTP 422.
12. **Business constraints** — team/division classification, roster size floors and ceilings, panel membership and sheet uniqueness, quorum, pending appeals, schedule generation preconditions, warm-up overlap and rest (`ERR_DIVISION_MISMATCH`, `ERR_ROSTER_TOO_LARGE`, `ERR_ROSTER_TOO_SMALL`, `ERR_JUDGE_NOT_ON_PANEL`, `ERR_DUPLICATE_SCORE_SHEET`, `ERR_QUORUM_NOT_MET`, `ERR_PENDING_APPEALS`, `ERR_DIVISION_HAS_NO_TEAMS`, `ERR_INSUFFICIENT_WARM_UP_MATS`, `ERR_WARM_UP_OVERLAP`, `ERR_MIN_REST_VIOLATION`, `ERR_APPEAL_NOT_RESUBMITTABLE`).
13. **Temporal windows** — the appeal window, bid acceptance deadline, and ticket hold expiry (`ERR_APPEAL_WINDOW_CLOSED`, `ERR_BID_ACCEPTANCE_CLOSED`, `ERR_ORDER_HOLD_EXPIRED`).
14. **Fiscal capacity** — session seat availability (`ERR_SESSION_SOLD_OUT`).

### 2.7. Precision, Rounding, and Score Semantics

All point values in the scoring pipeline — category averages, weighted base scores, deduction points, provisional and official scores — are computed with decimal arithmetic and carried to exactly 2 decimal places using round-half-up. The rounding order for scores is pinned: per-category averages are **never** rounded; exactly one round-half-up to 2 decimal places is applied after the weighted sum is computed and scaled. Deduction points are likewise the product of quantity and snapshotted rate, rounded half-up once to 2 decimal places. Money is handled separately: all ticket amounts are integer cents, and the single rounding step in an order total is the group discount, rounded half-up to whole cents. Division ranks are integers. Warm-up geometry is expressed in whole seconds.

### 2.8. Bid Pool Conservation and Hierarchical Cascades

Each division is created with a championship bid pool whose size is `paid_bid_count` plus `at_large_bid_count`; that sum is the initial value of the division's `bid_pool_available`. The pool obeys a strict conservation invariant at all times: the number of bids whose status is `OFFERED` or `ACCEPTED`, plus `bid_pool_available`, always equals `paid_bid_count` plus `at_large_bid_count`. Whenever a bid leaves `OFFERED` or `ACCEPTED` for a terminal state — declined, expired, or revoked — `bid_pool_available` increases by one per freed slot, and a re-offer cascade runs immediately to attempt to fill it (§3.7).

Consistency is maintained by cascade, not by operator cleanup. Withdrawing or disqualifying a team cancels or excludes its performances, revokes its outstanding bids back into the pool, and re-runs re-offers; confirming a performance official locks its score sheets, re-ranks the division, and — when it completes the division — triggers initial bid allocation; overturning a deduction on an `OFFICIAL` performance recomputes the official score, re-ranks the division, and re-evaluates every outstanding offer against the new ranks. Each cascade independently mutates the affected resources, refreshing `updated_at` and incrementing `version` on each one it touches. Request payloads follow a silent-ignore convention: fields not declared for an endpoint are never persisted and never echoed, and fields that are system- or computed-sourced are ignored when supplied by a client.

## 3. Business Logic & Workflows

### 3.1. Event Setup: Divisions, Sessions, and the Judging Panel

An `EventDirector` begins by creating an **Event** with a `name`, a display `venue_name`, a `start_date` and `end_date` (the last competition date must not precede the first), and an `age_reference_date` — the single date on which every athlete's age is evaluated against division age grids. An event is born in `DRAFT` status and walks a strict lifecycle: `DRAFT` → `REGISTRATION_OPEN` when the director opens registration, `REGISTRATION_OPEN` → `REGISTRATION_CLOSED` when registration closes, `REGISTRATION_CLOSED` → `SCHEDULED` automatically once every division of the event has been scheduled, `SCHEDULED` → `LIVE` when the director takes the event live, and `LIVE` → `FINALIZED` at the end. Each of these transitions increments the event's `version` by one. Opening, closing, and going live each require the event to be in the declared source state; calling them from any other status is rejected with `ERR_EVENT_INVALID_STATE`.

Within an event, the director creates **Divisions** — the classification unit that ties together discipline, level, age grid, roster bounds, timing, judging panel, and bid endowment. A division carries a `name` (such as "Senior All Girl Level 3"), a `category` of either `CHEER` or `DANCE`, an integer `level` between 1 and 6 that doubles as the maximum legal skill tier for routines in that division, an inclusive age band from `min_age` to `max_age` evaluated as of the event's `age_reference_date`, and inclusive roster bounds `min_athletes` through `max_athletes`. Timing is configured by `routine_time_limit_seconds` (the cap whose overrun generates a time deduction) and `warmup_duration_seconds`, which defaults to 900 — fifteen minutes per warm-up slot. The division's `warmup_mats` is an ordered list of warm-up mat labels, and it must contain enough entries to cycle the warm-up pipeline: at least the warm-up duration divided by the performance pitch (the routine time limit plus a 180-second transition buffer), rounded up to a whole number. `schedule_start_at` anchors the first performance on the competition mat. The judging panel is declared as `judge_ids`, a list of 3 to 9 judge identifiers; quorum for scoring means every listed judge has a submitted sheet.

Deduction pricing is per division: `time_deduction_per_second` (default 0.5 points per full second over the time limit), `safety_deduction_points` (default 2.0 per safety occurrence), and `boundary_deduction_points` (default 0.25 per boundary occurrence). Championship bid endowment is set by `paid_bid_count` and `at_large_bid_count`, both defaulting to 0; their sum initializes `bid_pool_available` per the conservation invariant in §2.8, and `scheduled` (initially false) flips true when schedule generation succeeds.

**Judges** are created by the director with a `full_name` and a `certified_levels` list naming the integer levels (1 through 6) that judge is certified to score. Because the panel, safety, and head-judge roles all share the `Judge` identity pool, this single record is what both the panel check and the segregation checks consult.

**Sessions** structure spectator access. The director creates a session for an event with a `name` (for example, "Saturday AM"), a `starts_at` and `ends_at` (the close must be strictly after the open), and a `capacity` of at least one seat. A session continuously tracks three computed counters: `seats_held` (the sum of quantities across orders in `HELD` status), `seats_sold` (the sum across orders in `PAID` status), and `seats_available`, which is the capacity minus the other two. The compensating invariant `seats_available + seats_held + seats_sold == capacity` holds at every moment; every ticket-order transition in §3.8 is defined by how it moves quantity between these counters.

### 3.2. Registration: Teams, Athletes, and Roster Construction

While the event is in `REGISTRATION_OPEN`, a `TeamCoach` registers a **Team** by supplying the `event_id`, the target `division_id`, a `name`, the `organization` (gym, school, or studio), the team's `category` and `level`, and `coach_user_id` — which must equal the acting `X-User-ID`, since this field is what every later ownership check compares against. Classification is strict: the team's `level` must equal the division's `level`, its `category` must equal the division's `category`, and the division must belong to the same event the team names; any mismatch is rejected with `ERR_DIVISION_MISMATCH` (HTTP 422). Attempting to register while the event is not `REGISTRATION_OPEN` is rejected with `ERR_EVENT_INVALID_STATE`. A team is born with `reg_status` of `REGISTERED` and a parallel `music_status` of `PENDING`; these two dimensions evolve independently and must both be satisfied where §3.3 and §3.4 say so.

**Athletes** are global person records — a `full_name` and a `date_of_birth` — creatable by a `TeamCoach` or an `EligibilityOfficer`. An athlete's competitive age is the number of full years elapsed between `date_of_birth` and the event's `age_reference_date`.

A coach builds a roster by creating **RosterEntry** records naming a `team_id`, an `athlete_id`, and a `bib_number` unique within the team. Three business-safety gates apply at creation, each evaluated only over entries that are not removed. First, the athlete's age at the event's `age_reference_date` must fall within the division's inclusive `min_age`–`max_age` band, else `ERR_ATHLETE_AGE_INELIGIBLE`. Second, crossover caps: an athlete may appear on at most 2 teams within the same event — a third is rejected with `ERR_CROSSOVER_LIMIT_EXCEEDED` — and an athlete already rostered on another team in the *same division* is rejected outright with `ERR_SAME_DIVISION_CROSSOVER`. Third, the addition must not push the team's non-removed roster count above the division's `max_athletes` (`ERR_ROSTER_TOO_LARGE`). Roster entries are born with `eligibility_status` of `ACTIVE` and `checked_in` false. Entries may be soft-removed — the entry's `removed` flag set true — only while the team is still `REGISTERED`; once the roster is locked or beyond, removal attempts are rejected with `ERR_ROSTER_LOCKED`. Removed entries are excluded from all roster counts and crossover checks.

Eligibility review is a separate loop owned by the `EligibilityOfficer`, who flips an entry's `eligibility_status` between `ACTIVE` and `INELIGIBLE` via a payload carrying the desired `eligibility_status`. Both directions guard the roster bounds on the resulting count of non-removed `ACTIVE` entries: marking an entry `INELIGIBLE` while the team is `ROSTER_LOCKED` must not drop that count below `min_athletes` (`ERR_ROSTER_TOO_SMALL`), and restoring an entry to `ACTIVE` must not push it above `max_athletes` (`ERR_ROSTER_TOO_LARGE`). Eligibility changes are permitted only while the team is `REGISTERED` or `ROSTER_LOCKED`; from `CHECKED_IN` onward they are rejected with `ERR_ROSTER_LOCKED`.

### 3.3. Roster Lock, Music Licensing, and Team Check-In

When the roster is set, the coach locks it, moving the team from `REGISTERED` to `ROSTER_LOCKED`. Two gates apply, in priority order behind the general validation order: the event must still be `REGISTRATION_OPEN` — a team that missed the window is rejected under the event-state family as `ERR_EVENT_INVALID_STATE` — and the count of non-removed roster entries whose `eligibility_status` is `ACTIVE` must fall within the division's inclusive bounds — below `min_athletes` yields `ERR_ROSTER_TOO_SMALL`, above `max_athletes` yields `ERR_ROSTER_TOO_LARGE`. Locking increments the team's `version`.

Music licensing runs on the parallel dimension. The coach submits the routine's music with a `track_count` of at least 1, a `license_provider` name, and a `license_reference` proof code. Submission requires the team to still be in `REGISTERED` or `ROSTER_LOCKED` — withdrawn or disqualified teams cannot submit — and the team's latest submission must be absent or `FLAGGED`: submitting while the latest submission is `SUBMITTED` (still awaiting review) or already `VERIFIED` is rejected with `ERR_MUSIC_STATE_CONFLICT`. Each new submission arrives as a **MusicSubmission** in `SUBMITTED` status and immediately moves the team's `music_status` to `SUBMITTED`; when the submission replaces a `FLAGGED` predecessor, the old record transitions to `SUPERSEDED`.

A `MusicCompliance` reviewer then reviews a `SUBMITTED` submission with a `decision` payload. A `decision` of `VERIFIED` moves the submission to `VERIFIED` and the team's `music_status` to `VERIFIED`. A `decision` of `FLAGGED` requires a `reason` in the payload (its absence is `ERR_INVALID_INPUT`), records that reason in the submission's `flag_reason`, moves the submission to `FLAGGED`, and moves the team's `music_status` to `FLAGGED` — freeing the coach to submit a replacement. Reviewing a submission that is not currently `SUBMITTED` is rejected with `ERR_MUSIC_STATE_CONFLICT`.

On competition day, with the event `LIVE`, the coach checks the team in by listing the `athlete_ids` who are present. Every identifier in `athlete_ids` must map to a non-removed roster entry of this team (an unknown entry is `ERR_NOT_FOUND`), the team's `music_status` must be `VERIFIED` (else `ERR_MUSIC_NOT_VERIFIED`), the event must be `LIVE` (else `ERR_EVENT_NOT_LIVE`), and the count of listed entries whose `eligibility_status` is `ACTIVE` must be at least the division's `min_athletes` (else `ERR_ROSTER_TOO_SMALL`). A successful check-in sets `checked_in` true on each listed entry, moves the team from `ROSTER_LOCKED` to `CHECKED_IN`, and increments the team's `version`. When the team's performance later becomes `OFFICIAL`, the system automatically moves the team from `CHECKED_IN` to `COMPETED`.

Teams exit the competition through two doors with different cascades. A coach may **withdraw** their own team (ownership-checked against `coach_user_id`, else `ERR_FORBIDDEN`) from `REGISTERED`, `ROSTER_LOCKED`, or `CHECKED_IN`; from any other state the attempt is rejected with `ERR_INVALID_STATE`. Withdrawal moves the team to `WITHDRAWN`, cancels every `SCHEDULED` performance of the team (moving each to `CANCELLED`), revokes every `OFFERED` or `ACCEPTED` bid of the team to `REVOKED` — returning one slot to `bid_pool_available` per revoked bid and running the re-offer cascade of §3.7 for each freed slot — and increments the team's `version`. An `EventDirector` may **disqualify** a team from `REGISTERED`, `ROSTER_LOCKED`, `CHECKED_IN`, or even `COMPETED`. Disqualification moves the team to `DISQUALIFIED`, moves every non-`CANCELLED` performance of the team to `EXCLUDED` (post-competition disqualification of a `COMPETED` team therefore reaches back into already-`OFFICIAL` performances), recomputes the division ranking excluding the excluded performances, revokes the team's `OFFERED` or `ACCEPTED` bids with the same pool-and-re-offer cascade as withdrawal, and increments the team's `version`.

### 3.4. Scheduling: Performance Order and Warm-Up Geometry

Once registration is closed, the `EventDirector` generates each division's schedule. Generation requires at least one eligible team in the division — teams whose `reg_status` is `REGISTERED`, `ROSTER_LOCKED`, or `CHECKED_IN` — else `ERR_DIVISION_HAS_NO_TEAMS`; and it requires the warm-up mat count to satisfy the pipeline geometry — the number of `warmup_mats` entries must be at least the warm-up duration divided by the sum of `routine_time_limit_seconds` and 180 seconds, that division rounded up — else `ERR_INSUFFICIENT_WARM_UP_MATS`. When both fail, the no-teams rejection takes precedence and the mats check is reported second. Generation is also forbidden once any performance of the division has reached `PERFORMED` or beyond — the request is rejected with `ERR_INVALID_STATE`. As covered in §2.5, the request must carry `expected_division_version`.

The geometry is deterministic. The **performance pitch** is `routine_time_limit_seconds` plus a 180-second transition buffer, in whole seconds. Teams are ordered by their `created_at` ascending — registration order — and receive `performance_order` values 1 through N. Each created **Performance** records its `team_id` and `division_id`, and its `scheduled_start` is the division's `schedule_start_at` plus (order − 1) pitches. Team number *n* warms up on the mat at position (n − 1) modulo the number of `warmup_mats`, in a half-open window that ends 600 seconds (ten minutes of mandatory rest) before its `scheduled_start` and begins `warmup_duration_seconds` before that. These system-created **WarmUpAssignment** rows carry `source` of `SYSTEM`; the performances arrive in `SCHEDULED` status. Generation supersedes any prior schedule: existing `SCHEDULED` performances of the division are moved to `CANCELLED` and recreated fresh. Success sets the division's `scheduled` flag true, increments the division's `version`, and — when this was the last unscheduled division of the event — automatically advances the event from `REGISTRATION_CLOSED` to `SCHEDULED`.

Coaches may also book additional warm-up windows manually, supplying `event_id`, `team_id`, a `mat` label, and a `starts_at`/`ends_at` pair (with `ends_at` strictly after `starts_at`, else `ERR_INVALID_INPUT`). Manual assignments carry `source` of `MANUAL` and start `BOOKED`. Overlap is evaluated per (`event_id`, `mat`) pair over half-open intervals: a new window that intersects any `BOOKED` assignment on the same mat is rejected with `ERR_WARM_UP_OVERLAP`, while pure adjacency — one window's `ends_at` equal to the other's `starts_at` — does not overlap and is allowed. Independently of overlap, the rest rule applies: for the team's `SCHEDULED` performance, the window's `ends_at` plus 600 seconds must not be later than that performance's `scheduled_start`; violating it is `ERR_MIN_REST_VIOLATION`. Either the coach who owns the team may later **release** a `BOOKED` assignment (moving it to `RELEASED` and freeing the interval for future overlap checks); releasing from any other state is rejected with `ERR_INVALID_STATE`, and by anyone but the owning coach with `ERR_FORBIDDEN`.

### 3.5. Performance Day: Mark-Performed, Deductions, and Scoring

A `SafetyJudge` records that a routine happened by marking its performance performed, supplying the measured `actual_duration_seconds` and optionally `boundary_violations` (defaulting to 0). The operation requires the performance to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), the owning event to be `LIVE` (`ERR_EVENT_NOT_LIVE`), and the team to be `CHECKED_IN` (`ERR_TEAM_NOT_CHECKED_IN`). Marking performed moves the performance from `SCHEDULED` to `PERFORMED`, increments its `version`, and auto-creates **system deductions** from the raw measurements. If `actual_duration_seconds` exceeds the division's `routine_time_limit_seconds`, a `SYSTEM` deduction of `type` `TIME` is created with `quantity` equal to the number of full seconds over the limit and `rate_applied` snapshotted from the division's `time_deduction_per_second`. If `boundary_violations` is greater than zero, a `SYSTEM` deduction of `type` `BOUNDARY` is created with `quantity` equal to `boundary_violations` and `rate_applied` snapshotted from `boundary_deduction_points`. System deductions carry a null `applied_by_judge_id`.

A `SafetyJudge` may also apply a **manual deduction** against a performance that is `PERFORMED` or `SCORED`; against a still-`SCHEDULED` performance the request is `ERR_PERFORMANCE_NOT_PERFORMED`, and against an `OFFICIAL`, `EXCLUDED`, or `CANCELLED` performance it is `ERR_PERFORMANCE_INVALID_STATE`. The manual endpoint accepts `type` of `SAFETY` only — `TIME` and `BOUNDARY` are exclusively system-generated at mark-performed — together with a `quantity` of at least 1 and a `skill_tier` between 1 and 6 naming the observed skill tier. Routine legality is the gate: a `SAFETY` deduction is only valid when `skill_tier` exceeds the division's `level`; citing a skill at or below the division's level is legal at that level and is rejected with `ERR_SKILL_WITHIN_LEGAL_LIMIT`. Every deduction snapshots its applicable rate into `rate_applied` at creation — `safety_deduction_points` for `SAFETY`, `time_deduction_per_second` for `TIME`, `boundary_deduction_points` for `BOUNDARY` — and computes `points` as the quantity multiplied by the snapshotted rate, rounded half-up once to 2 decimal places. A deduction is born `APPLIED` with `source` of `MANUAL` or `SYSTEM`; the applying safety judge's identity is recorded in `applied_by_judge_id` for `MANUAL` rows. Creating a deduction immediately recomputes the performance's `provisional_score` (§3.6). An audit-trail read lists deductions filtered by an optional `applied_by_judge_id`.

Scoring begins once the panel goes to work. A `Judge` creates their own **ScoreSheet** against a `PERFORMED` or `SCORED` performance (the same `ERR_PERFORMANCE_NOT_PERFORMED` / `ERR_PERFORMANCE_INVALID_STATE` pair guards the state), supplying four category scores — `building_difficulty`, `building_execution`, `tumbling_difficulty`, and `overall_impression` — each a number from 0 to 10. Two panel checks apply at creation, in this order: the acting judge's `id` must appear in the division's `judge_ids` (else `ERR_JUDGE_NOT_ON_PANEL`), and no existing sheet may already exist for this (performance, judge) pair (else `ERR_DUPLICATE_SCORE_SHEET`). Certification is enforced at both creation and again at submission: the division's `level` must appear in the judge's `certified_levels`, else `ERR_JUDGE_NOT_CERTIFIED`. A new sheet is born in `DRAFT`, its `judge_id` pinned to the acting `X-User-ID`, its `performance_id` taken from the path.

A sheet is revised while in `DRAFT` by editing any subset of the four category fields; such an edit keeps the sheet in `DRAFT`. Submitting the sheet moves it from `DRAFT` to `SUBMITTED`, stamps `submitted_at` with the logical now, and requires the performance to be `PERFORMED` or `SCORED` — the certification re-check applies here as well. Editing a `SUBMITTED` sheet reopens it to `DRAFT`, but only while the performance is not yet `OFFICIAL`; once the performance is `OFFICIAL` every sheet is `LOCKED`, and any edit or submit attempt is rejected with `ERR_SCORE_SHEET_LOCKED`.

Quorum drives the performance's own lifecycle. When a submission completes the panel — every judge in `judge_ids` now holds a `SUBMITTED` sheet for the performance — the performance automatically moves from `PERFORMED` to `SCORED` and its `provisional_score` is computed and stored. Conversely, when a submitted sheet is reopened to `DRAFT` and quorum is lost, the performance automatically drops from `SCORED` back to `PERFORMED`, and the provisional score is recomputed over the remaining `SUBMITTED` sheets — nulling out entirely if fewer than 2 remain. An audit read also lists the sheets authored by a given judge and the sheets of a given performance.

### 3.6. Scores, Appeals, and the Deduction Lifecycle

The scoring model has two variants of the same formula. The **base score** takes, for each of the four categories, the values from every `SUBMITTED` sheet of the performance and averages them — a straight, unrounded mean. The weighted sum uses category weights of 0.30 for `building_difficulty`, 0.30 for `building_execution`, 0.20 for `tumbling_difficulty`, and 0.20 for `overall_impression` (weights summing to exactly 1.00); that weighted sum is multiplied by a scale factor of 10, and the single rounding step — half-up to 2 decimal places — happens only after this scaling. The **OFFICIAL** variant, used at confirm-official and on any post-official deduction overturn, adds one twist: when the panel supplies at least 5 submitted sheets for a category, exactly one highest and one lowest value (a single occurrence of each) are removed from that category's values before averaging. The **PROVISIONAL** variant, used while the performance is `PERFORMED` or `SCORED`, never trims — it averages however many `SUBMITTED` sheets exist — and it produces no value at all (a null `provisional_score`) while fewer than 2 submitted sheets remain. Identical sheet data therefore yields different base scores between the two variants whenever the panel has 5 or more sheets whose high and low values differ from the mean.

The **final score** subtracts deductions from the base, with a floor of zero — the result never goes negative. Which deductions count depends on the variant. PROVISIONAL counts deductions in `APPLIED`, `UNDER_APPEAL`, or `UPHELD` status; OFFICIAL counts only `APPLIED` and `UPHELD`, excluding `UNDER_APPEAL` deductions as unresolved. `OVERTURNED` and `VOIDED` deductions never count in any variant. Consequently, a deduction under appeal lowers the provisional score but not the official score, and identical raw data yields different final scores between variants whenever an appeal is in flight.

The **appeal loop** gives the coach recourse. The coach of the team owning the performance (ownership-checked, else `ERR_FORBIDDEN`) may appeal an `APPLIED` deduction by submitting a `note` argument and a `video_ref` evidence reference. The appeal window is strict: the logical now must be no later than 45 minutes after the deduction's `created_at`, the boundary inclusive; outside it the request is `ERR_APPEAL_WINDOW_CLOSED`. Appealing creates an **Appeal** — its `deduction_id` bound to the appealed deduction, its `round` set to 1, and its own status `SUBMITTED` — and moves the deduction from `APPLIED` to `UNDER_APPEAL`, which triggers a provisional recompute (the deduction still counts provisionally). Appealing a deduction not in `APPLIED` status is `ERR_DEDUCTION_NOT_APPLIED`.

A `HeadJudge` resolves a `SUBMITTED` appeal with a `decision`, subject to two segregation-of-duties checks: the acting head judge's `X-User-ID` (a `Judge.id`) must not equal the `judge_id` of any score sheet on the deduction's performance, and must not equal the deduction's `applied_by_judge_id`; either conflict is rejected with `ERR_REVIEWER_CONFLICT`. Resolving a non-`SUBMITTED` appeal is `ERR_INVALID_STATE`. A `decision` of `REJECTED` moves the appeal to `REJECTED` and the deduction to `UPHELD`, where it remains counted in all score variants. A `decision` of `ACCEPTED` moves the appeal to `ACCEPTED` and the deduction to `OVERTURNED`, excluding it from all score variants — and here the cascade runs deep: the provisional score is recomputed; and if the performance is already `OFFICIAL`, its `official_score` is recomputed, the division ranking is recomputed, and the bid re-evaluation step of §3.7 runs for the division, revoking `OFFERED` bids whose teams no longer earn a slot and re-offering what is freed. The cascade depth is Appeal → Deduction → Performance (score and rank) → Bid.

A coach whose round-1 appeal was `REJECTED` may escalate once: resubmitting the rejected appeal — again with a fresh `note` and `video_ref` — creates a new Appeal with `round` 2 in `SUBMITTED` status and moves the deduction from `UPHELD` back to `UNDER_APPEAL`. Resubmission is allowed only when the rejected appeal's `round` is 1; a round-2 appeal is terminal when rejected, and resubmitting it is rejected with `ERR_APPEAL_NOT_RESUBMITTABLE`. The same 45-minute inclusive window from the deduction's `created_at` governs resubmission (`ERR_APPEAL_WINDOW_CLOSED`), and the deduction must currently be `UPHELD` for the cycle to continue. An audit read lists appeals filtered by an optional `decided_by_judge_id`, which is set to the resolving head judge's identity when an appeal is resolved.

Independent of appeals, a `HeadJudge` may **void** an `APPLIED` deduction outright — but not one they applied themselves: the acting head judge's `X-User-ID` must differ from the deduction's `applied_by_judge_id` (`ERR_SELF_VOID_FORBIDDEN`), though a system-generated deduction, whose `applied_by_judge_id` is null, is voidable by any head judge. Voiding is forbidden once the performance is `OFFICIAL` (`ERR_PERFORMANCE_INVALID_STATE`), and requires the deduction to be `APPLIED` (`ERR_DEDUCTION_NOT_APPLIED`). A voided deduction moves to `VOIDED`, is excluded from every score variant, and triggers a provisional recompute. The safety judge may also **amend** an `APPLIED` deduction's `quantity` or `skill_tier`; per §2.5 the request must carry `expected_deduction_version`, the deduction must be `APPLIED`, and a successful amendment recomputes `points` from the new quantity against the frozen `rate_applied`, recomputes the provisional score, and increments the deduction's `version`.

### 3.7. Going Official: Rankings, Bids, and the Championship Waterfall

A `HeadJudge` confirms a `SCORED` performance official. The precondition chain is layered: from a `SCHEDULED` performance the call is `ERR_PERFORMANCE_NOT_PERFORMED`; from an `OFFICIAL` one, `ERR_PERFORMANCE_INVALID_STATE`; from `PERFORMED` — meaning the panel quorum is incomplete — `ERR_QUORUM_NOT_MET`; and from `SCORED` with any deduction of the performance still `UNDER_APPEAL`, `ERR_PENDING_APPEALS`. Confirmation performs a synchronized bundle of effects: the OFFICIAL score variant is computed and stored as `official_score`; the division ranking is recomputed and `rank_in_division` rewritten on every `OFFICIAL` sibling performance; every `SUBMITTED` score sheet of the performance moves to `LOCKED`; the owning team moves from `CHECKED_IN` to `COMPETED`; the performance's `version` increments; and if every non-`CANCELLED` performance of the division is now `OFFICIAL` or `EXCLUDED`, the division is complete and initial bid allocation runs for it.

**Division ranking** considers only performances in `OFFICIAL` status — `EXCLUDED`, `CANCELLED`, `SCORED`, and earlier states are omitted from the ranked set. Ordering is a four-level total order: higher `official_score` first; ties broken by fewer total deduction points counted under the OFFICIAL rule (deductions in `APPLIED` or `UPHELD`); then by the OFFICIAL-variant base score's `building_execution` category average, higher first; and finally by earlier `scheduled_start`. Ranks are 1-based integers written back onto every ranked performance, and they are recomputed whenever an official score changes or a performance enters or leaves the ranked set — including the post-official disqualification path of §3.3. A division's standings read returns its ranked `OFFICIAL` performances in `rank_in_division` ascending order.

**Bid allocation** is a waterfall over the division's ranks, with an eligibility filter applied throughout: a candidate must be the team of an `OFFICIAL` performance in the division, its `reg_status` must be neither `WITHDRAWN` nor `DISQUALIFIED`, and it must not already hold an `ACCEPTED` bid in any division of the event — one accepted bid per team per event.

- **INITIAL allocation** runs when a division completes or when the director re-runs allocation for the event (the OCC-guarded operation of §2.5, which revokes every standing `OFFERED` bid into the pool and re-offers per current ranks, leaving `ACCEPTED` bids untouched, increments the event's `version`, and returns the list of offered bid ids). `PAID` slots go to the top `paid_bid_count` eligible teams by rank, best rank first. `AT_LARGE` slots then go to the next eligible teams by rank whose `official_score` is at least 90 percent of the division-winning official score — the threshold computed as 0.90 times the winner's `official_score`, rounded half-up to 2 decimal places, and the comparison is inclusive. All `PAID` offers are evaluated before any `AT_LARGE` offer, and teams are considered in rank order; ties are impossible because the ranking is total. A team holding an `OFFERED` `AT_LARGE` bid remains eligible for a `PAID` slot — an upgrade. Each created **Bid** records its `division_id`, `team_id`, `kind` (`PAID` or `AT_LARGE`), the team's `rank_at_offer`, the `offered_at` logical timestamp, and an `acceptance_deadline` exactly 72 hours after the offer. If `bid_pool_available` is zero, allocation creates nothing.
- **REOFFER** runs whenever a slot returns to `bid_pool_available` — a decline, an expiry, or a revocation. The team whose action freed the slot is excluded from that re-offer, having already refused or lost it. A freed `PAID` slot is offered to the next-ranked eligible team with no score threshold; if that team holds an `OFFERED` `AT_LARGE` bid, that at-large bid is revoked as an upgrade and the freed at-large slot is itself re-offered by the same rule. A freed `AT_LARGE` slot goes to the next-ranked eligible team meeting the 90-percent threshold. If no eligible team exists, the slot remains in `bid_pool_available`.
- **REEVALUATE** runs when a deduction overturn changes ranks on an `OFFICIAL` performance: ranks are recomputed, every `OFFERED` bid in the division is revoked (pool credited accordingly), and INITIAL allocation runs against the new ranks. `ACCEPTED` bids are never revoked by re-evaluation — only a team withdrawal or disqualification touches them.

Bid responses belong to the owning coach. Accepting an `OFFERED` bid requires the logical now to be no later than the bid's `acceptance_deadline` — inclusive boundary, else `ERR_BID_ACCEPTANCE_CLOSED` — ownership of the bid's team (else `ERR_FORBIDDEN`), and a team `reg_status` that is neither `WITHDRAWN` nor `DISQUALIFIED` (else `ERR_INVALID_STATE`); the bid moves to `ACCEPTED`. Declining moves the bid to `DECLINED`, returns the slot to `bid_pool_available`, and immediately runs the re-offer step for the freed slot. Both operations require the bid to be `OFFERED` (`ERR_BID_NOT_OFFERED`). Bids also leave `OFFERED` without any coach action: the checkpoint sweep of §3.9 expires those whose deadline has passed (moving them to `EXPIRED` with the pool-and-re-offer cascade), and team withdrawal, disqualification, at-large-to-paid upgrade, and post-appeal re-evaluation revoke them (to `REVOKED`) with the same pool-and-re-offer treatment. An `ACCEPTED` bid can be revoked only by the withdrawal/disqualification cascade.

### 3.8. Spectator Ticketing

A `Spectator` buys tickets by creating a **TicketOrder** against a `session_id` with a `quantity` between 1 and 40 (the per-order maximum). Ticket sales are open while the event's status is `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `SCHEDULED`, or `LIVE`; outside those states the create is rejected with `ERR_EVENT_INVALID_STATE`. The order's price is snapshotted at creation and never recomputed afterwards. The order's `tier` is decided by an inclusive cutoff: orders created on or before the day that is 14 days before the event's `start_date` (the cutoff taken at 00:00:00Z) are `ADVANCE`; anything later is `GATE`. The snapshotted `unit_price_cents` is 1295 for `ADVANCE` and 1895 for `GATE`. The subtotal is the quantity multiplied by the unit price in exact integer cents. A group discount applies when the quantity is at least 20 (inclusive): 10 percent of the subtotal, rounded half-up once to whole cents, becomes `discount_cents`; otherwise `discount_cents` is zero. The order's `total_cents` is the subtotal minus the rounded discount. Note the rounding order is pinned to the order level — the discount is computed once on the whole subtotal, not per unit; under the (documented but never served) per-unit interpretation, 25 advance tickets would total 29150 cents instead of the correct 29137, so implementations must apply the discount to the subtotal.

Capacity is enforced at creation against the session's compensating invariant: the requested `quantity` must fit within `seats_available` — held plus sold plus requested must not exceed `capacity` — else `ERR_SESSION_SOLD_OUT`. A new order arrives with its `status` set to `HELD`, `purchaser_user_id` captured from the acting `X-User-ID`, adds its quantity to the session's `seats_held`, and sets `hold_expires_at` to 15 minutes after creation.

From `HELD`, the owning spectator pays: the logical now must be no later than `hold_expires_at`, inclusive (`ERR_ORDER_HOLD_EXPIRED`), and the actor must match `purchaser_user_id` (`ERR_FORBIDDEN`). Payment moves the order to `PAID`, subtracts the quantity from `seats_held`, and adds it to `seats_sold`. Cancellation from `HELD` moves the order to `CANCELLED` and releases the quantity from `seats_held`; cancellation from `PAID` moves it to `REFUNDED` and subtracts the quantity from `seats_sold`; cancellation from any other state, and payment from any state but `HELD`, are rejected with `ERR_ORDER_INVALID_STATE`. Orders that linger in `HELD` past their deadline are swept to `EXPIRED` by the checkpoint, releasing their held seats.

### 3.9. The Ops Checkpoint and Event Finalization

Two maintenance capabilities close out the operational loop. The **checkpoint** — an `EventDirector`-only sweep of a single event — expires every `OFFERED` bid of the event whose `acceptance_deadline` is earlier than the logical now, moving each to `EXPIRED`, crediting `bid_pool_available`, and running the re-offer cascade per freed slot; and it expires every `HELD` ticket order of the event whose `hold_expires_at` is earlier than the logical now, moving each to `EXPIRED` and releasing its seats from `seats_held`. The sweep reports back the counts as `expired_bid_count` and `expired_order_count`.

**Finalization** is the event's terminal act, moving it from `LIVE` to `FINALIZED` and incrementing its `version`. The director may finalize only when three conditions hold simultaneously: every performance of the event is in a terminal state (`OFFICIAL`, `EXCLUDED`, or `CANCELLED`); no appeal in `SUBMITTED` status exists for any deduction of the event; and no bid in `OFFERED` status exists for any division of the event. Any violation is rejected with `ERR_FINALIZE_BLOCKED`. The same gate guards the re-allocation operation of §3.7 in one respect: re-running bid allocation requires every division of the event to be complete — all non-`CANCELLED` performances `OFFICIAL` or `EXCLUDED` — and is likewise rejected with `ERR_FINALIZE_BLOCKED` when divisions are still in flight.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource (including all state transitions) return `200 OK`; the soft-delete of a roster entry returns `204 No Content`. Request and response bodies follow §2 and the narratives of §3 — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/events` | Create an event (status `DRAFT`) | EventDirector |
| GET | `/api/events/{id}` | Fetch one event | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| POST | `/api/events/{id}/open-registration` | Event `DRAFT` → `REGISTRATION_OPEN` | EventDirector |
| POST | `/api/events/{id}/close-registration` | Event `REGISTRATION_OPEN` → `REGISTRATION_CLOSED` | EventDirector |
| POST | `/api/events/{id}/go-live` | Event `SCHEDULED` → `LIVE` | EventDirector |
| POST | `/api/events/{id}/finalize` | Event `LIVE` → `FINALIZED` | EventDirector |
| POST | `/api/events/{id}/checkpoint` | Sweep expired bids and held ticket orders for the event | EventDirector |
| POST | `/api/events/{id}/allocate-bids` | Re-run bid allocation for every division (OCC-guarded) | EventDirector |
| GET | `/api/events/{id}/divisions` | List divisions of an event | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| GET | `/api/events/{id}/teams` | List teams of an event | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| GET | `/api/events/{id}/sessions` | List sessions of an event | EventDirector, TeamCoach, Spectator |
| GET | `/api/events/{id}/warm-up-assignments` | List warm-up assignments of an event | EventDirector, TeamCoach |
| POST | `/api/divisions` | Create a division (bid pool initialized) | EventDirector |
| GET | `/api/divisions/{id}` | Fetch one division | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| GET | `/api/divisions/{id}/standings` | Ranked `OFFICIAL` performances of the division | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| POST | `/api/divisions/{id}/generate-schedule` | Generate performance order and warm-up assignments (OCC-guarded) | EventDirector |
| GET | `/api/divisions/{id}/teams` | List teams of a division | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| GET | `/api/divisions/{id}/performances` | List performances of a division | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge |
| GET | `/api/divisions/{id}/bids` | List bids of a division | EventDirector, TeamCoach |
| POST | `/api/teams` | Register a team | TeamCoach |
| GET | `/api/teams/{id}` | Fetch one team | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge, MusicCompliance, EligibilityOfficer, Spectator |
| POST | `/api/teams/{id}/lock-roster` | Team `REGISTERED` → `ROSTER_LOCKED` | TeamCoach |
| POST | `/api/teams/{id}/check-in` | Team `ROSTER_LOCKED` → `CHECKED_IN`; marks listed entries checked in | TeamCoach |
| POST | `/api/teams/{id}/withdraw` | Team → `WITHDRAWN` with cascades | TeamCoach |
| POST | `/api/teams/{id}/disqualify` | Team → `DISQUALIFIED` with cascades | EventDirector |
| POST | `/api/teams/{id}/music-submissions` | Submit routine music (supersedes a `FLAGGED` predecessor) | TeamCoach |
| GET | `/api/teams/{id}/music-submissions` | List a team's music submissions | EventDirector, TeamCoach, MusicCompliance |
| GET | `/api/teams/{id}/roster-entries` | List roster entries of a team (removed excluded) | EventDirector, TeamCoach, EligibilityOfficer |
| GET | `/api/teams/{id}/performances` | List performances of a team | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge |
| GET | `/api/teams/{id}/bids` | List bids of a team | EventDirector, TeamCoach |
| GET | `/api/teams/{id}/warm-up-assignments` | List warm-up assignments of a team | EventDirector, TeamCoach |
| POST | `/api/music-submissions/{id}/review` | Music licensing review decision | MusicCompliance |
| POST | `/api/athletes` | Create an athlete record | TeamCoach, EligibilityOfficer |
| GET | `/api/athletes/{id}` | Fetch one athlete | EventDirector, TeamCoach, EligibilityOfficer |
| GET | `/api/athletes/{id}/roster-entries` | List roster entries of an athlete | EventDirector, TeamCoach, EligibilityOfficer |
| POST | `/api/roster-entries` | Add an athlete to a team roster | TeamCoach |
| GET | `/api/roster-entries/{id}` | Fetch one roster entry | EventDirector, TeamCoach, EligibilityOfficer |
| DELETE | `/api/roster-entries/{id}` | Soft-remove a roster entry | TeamCoach |
| POST | `/api/roster-entries/{id}/set-eligibility` | Eligibility review loop `ACTIVE` ↔ `INELIGIBLE` | EligibilityOfficer |
| POST | `/api/judges` | Create a judge with certified levels | EventDirector |
| GET | `/api/judges/{id}` | Fetch one judge | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge |
| GET | `/api/judges/{id}/score-sheets` | List score sheets authored by a judge | EventDirector, Judge, HeadJudge |
| GET | `/api/performances/{id}` | Fetch one performance (scores, rank, status) | EventDirector, TeamCoach, Judge, HeadJudge, SafetyJudge |
| POST | `/api/performances/{id}/mark-performed` | Record duration and boundary count; auto-create system deductions | SafetyJudge |
| POST | `/api/performances/{id}/score-sheets` | Judge creates own `DRAFT` score sheet | Judge |
| GET | `/api/performances/{id}/score-sheets` | List score sheets of a performance | EventDirector, Judge, HeadJudge |
| POST | `/api/performances/{id}/deductions` | Apply a manual `SAFETY` deduction | SafetyJudge |
| GET | `/api/performances/{id}/deductions` | List deductions of a performance | EventDirector, TeamCoach, HeadJudge, SafetyJudge |
| POST | `/api/performances/{id}/confirm-official` | Performance `SCORED` → `OFFICIAL` with scoring, ranking, and bid effects | HeadJudge |
| GET | `/api/score-sheets/{id}` | Fetch one score sheet | EventDirector, Judge, HeadJudge |
| PATCH | `/api/score-sheets/{id}` | Amend scores; reopens a `SUBMITTED` sheet to `DRAFT` | Judge |
| POST | `/api/score-sheets/{id}/submit` | Sheet `DRAFT` → `SUBMITTED`; may complete quorum | Judge |
| GET | `/api/deductions` | Filtered deduction list (audit trail by applying judge) | EventDirector, HeadJudge, SafetyJudge |
| GET | `/api/deductions/{id}` | Fetch one deduction | EventDirector, TeamCoach, HeadJudge, SafetyJudge |
| PATCH | `/api/deductions/{id}` | Amend quantity/skill tier of an `APPLIED` deduction (OCC-guarded) | SafetyJudge |
| POST | `/api/deductions/{id}/void` | Void an `APPLIED` deduction (not own application) | HeadJudge |
| POST | `/api/deductions/{id}/appeals` | Appeal a deduction with video evidence | TeamCoach |
| GET | `/api/deductions/{id}/appeals` | List appeals of a deduction (all rounds) | EventDirector, TeamCoach, HeadJudge |
| GET | `/api/appeals` | Filtered appeal list (audit trail by deciding judge) | EventDirector, HeadJudge |
| GET | `/api/appeals/{id}` | Fetch one appeal | EventDirector, TeamCoach, HeadJudge |
| POST | `/api/appeals/{id}/resolve` | Resolve an appeal (segregation-of-duties constrained) | HeadJudge |
| POST | `/api/appeals/{id}/resubmit` | Escalate a round-1 `REJECTED` appeal to round 2 | TeamCoach |
| GET | `/api/bids/{id}` | Fetch one bid | EventDirector, TeamCoach |
| POST | `/api/bids/{id}/accept` | Accept an `OFFERED` bid within its 72-hour window | TeamCoach |
| POST | `/api/bids/{id}/decline` | Decline an `OFFERED` bid; slot re-offers immediately | TeamCoach |
| POST | `/api/sessions` | Create a spectator session | EventDirector |
| GET | `/api/sessions/{id}` | Fetch one session (seat counters) | EventDirector, TeamCoach, Spectator |
| GET | `/api/sessions/{id}/ticket-orders` | List ticket orders of a session | EventDirector |
| POST | `/api/ticket-orders` | Create a `HELD` ticket order (price snapshot) | Spectator |
| GET | `/api/ticket-orders/{id}` | Fetch one ticket order | EventDirector, Spectator |
| POST | `/api/ticket-orders/{id}/pay` | `HELD` → `PAID` within the hold window | Spectator |
| POST | `/api/ticket-orders/{id}/cancel` | `HELD` → `CANCELLED` or `PAID` → `REFUNDED` | Spectator |
| POST | `/api/warm-up-assignments` | Book a warm-up window | TeamCoach |
| GET | `/api/warm-up-assignments/{id}` | Fetch one warm-up assignment | EventDirector, TeamCoach |
| POST | `/api/warm-up-assignments/{id}/release` | `BOOKED` → `RELEASED` | TeamCoach |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | EventDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives where the guarded workflow is described.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_INPUT` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EVENT_INVALID_STATE` | 409 |
| `ERR_EVENT_NOT_LIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TEAM_NOT_CHECKED_IN` | 409 |
| `ERR_MUSIC_NOT_VERIFIED` | 409 |
| `ERR_MUSIC_STATE_CONFLICT` | 409 |
| `ERR_ROSTER_LOCKED` | 409 |
| `ERR_PERFORMANCE_NOT_PERFORMED` | 409 |
| `ERR_PERFORMANCE_INVALID_STATE` | 409 |
| `ERR_SCORE_SHEET_LOCKED` | 409 |
| `ERR_DEDUCTION_NOT_APPLIED` | 409 |
| `ERR_APPEAL_NOT_RESUBMITTABLE` | 422 |
| `ERR_BID_NOT_OFFERED` | 409 |
| `ERR_BID_ACCEPTANCE_CLOSED` | 422 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_ORDER_HOLD_EXPIRED` | 422 |
| `ERR_FINALIZE_BLOCKED` | 409 |
| `ERR_ATHLETE_AGE_INELIGIBLE` | 422 |
| `ERR_CROSSOVER_LIMIT_EXCEEDED` | 422 |
| `ERR_SAME_DIVISION_CROSSOVER` | 422 |
| `ERR_JUDGE_NOT_CERTIFIED` | 422 |
| `ERR_JUDGE_NOT_ON_PANEL` | 422 |
| `ERR_SKILL_WITHIN_LEGAL_LIMIT` | 422 |
| `ERR_REVIEWER_CONFLICT` | 422 |
| `ERR_SELF_VOID_FORBIDDEN` | 422 |
| `ERR_DIVISION_MISMATCH` | 422 |
| `ERR_ROSTER_TOO_LARGE` | 422 |
| `ERR_ROSTER_TOO_SMALL` | 422 |
| `ERR_DUPLICATE_SCORE_SHEET` | 422 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_PENDING_APPEALS` | 422 |
| `ERR_DIVISION_HAS_NO_TEAMS` | 422 |
| `ERR_INSUFFICIENT_WARM_UP_MATS` | 422 |
| `ERR_WARM_UP_OVERLAP` | 409 |
| `ERR_MIN_REST_VIOLATION` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_SESSION_SOLD_OUT` | 409 |
