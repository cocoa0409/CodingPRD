# Scholastic Chess League API — Product Requirements Document

## 1. Introduction

A scholastic chess federation runs far more than games. Across a single season it must register school clubs and their coaches, collect membership dues against a deadline, schedule dual meets between clubs without calendar collisions, pair individual boards, keep every player's rating current through a replayable event history, run sectional tournaments with rating-banded eligibility, staff events with proctors, settle club accounts through an auditable ledger, rank teams for the postseason, and issue qualification bids for state and national championships. Each of these duties belongs to a different kind of operator — federation administrators, club coaches, proctors, a treasurer, and an auditor — and the system exists to let them act concurrently without ever corrupting one another's work.

This document specifies the Scholastic Chess League API, the system of record for that operation. All resources are mounted under the `/api` prefix. Three design commitments shape everything that follows. First, ratings are event-sourced: every confirmed game appends an immutable rating event, and a player's published rating is always a replay of that history rather than a mutable counter, so a reversed game result rewrites history cleanly. Second, club money lives in an append-only ledger where corrections are posted as reversing entries by a different operator than the original poster, never by editing rows. Third, the server runs on a logical clock that administrators set explicitly, so dues deadlines, early-bird windows, and bid expirations are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `FederationAdmin`, `ClubCoach`, `Proctor`, `Treasurer`, and `Auditor`. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to each operation is further restricted by role; an attempt to perform an action outside of the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Role identity works in two ways. When `X-User-Role` is `ClubCoach` or `Proctor`, `X-User-ID` is the `id` of the acting `Coach`; ownership checks on any resource that references a `Coach` — directly, or indirectly through the club that coach belongs to — compare the resource's foreign-key field to `X-User-ID`. A `ClubCoach` therefore operates only within the scope of their own club: its players, its memberships, meets in which the club is host or away, entries of its own players, disputes on its own meets, and bids issued to the club. A `Proctor` may confirm only the assignment whose `coach_id` equals their `X-User-ID`. When `X-User-Role` is `FederationAdmin`, `Treasurer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `posted_by_user_id` on a ledger entry) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — seasons, clubs, coaches, players, memberships, meets, pairings, disputes, tournaments, sections, entries, proctor assignments, qualification bids, standing snapshots, and travel stipends — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at its initial value on creation and increments by one with every mutation of the resource; it anchors optimistic concurrency control where §2.7 applies.

Two resources are deliberately immutable event rows and carry only `id` and `created_at`: a `LedgerEntry` and a `RatingEvent` have no `updated_at` and no `version` at all. The single post-creation mutation the server ever performs on a ledger row is setting its `reversed_by_id` when a reversal posts; the row's amount and type never change.

### 2.5. The Logical Clock

The server keeps a logical clock rather than consulting wall-clock time. Before any call has been made, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock on its own. A federation-administrator-only capability advances the clock: the caller supplies a `to_iso8601` instant, and the response echoes the new reading as `current_utc`. Every timestamp the system stamps — a membership's `paid_at`, a pairing's `confirmed_at`, the base instant from which a bid's `offer_deadline` is computed, and every deadline comparison in fee calculations — reads this clock.

Advancing the clock runs a housekeeping sweep: every qualification bid still in `OFFERED` whose `offer_deadline` is strictly earlier than the new clock reading becomes `EXPIRED`, and each expired individual bid triggers the promotion cascade described in §3.9. A bid whose deadline equals the new reading exactly survives the sweep.

### 2.6. Money, Ratings, and Rounding Discipline

All monetary values are integer cents; no fractional cents ever appear in requests or responses. Ratings are integers as well, while team game points are tracked in half-point units. Wherever a calculation requires rounding — entry fees, half-fee refunds, volume credits, and every rating update — the rule is round half up, defined as the floor of the value plus one half, applied identically to positive and negative values. This definition matters for negative operands: a negative half rounds toward zero.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed on the version of a parent resource the client last observed:

- Creating a pairing within a meet requires the request to carry `expected_meet_version` matching the meet's current `version`. Pairing creation supersedes any existing non-terminal pairing at the same round-and-board slot and is legitimate repeatedly while the meet is being arranged, so the only guard against a writer whose view of the meet is outdated is this check: a create whose `expected_meet_version` no longer matches because another pairing write has advanced the meet since the client observed it is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Posting a manual adjustment to a club's ledger requires `expected_club_version` matching the club's current `version`. A manual adjustment is always legitimate product-wise, so the OCC check is the sole guard: a post whose `expected_club_version` no longer matches because a prior ledger post advanced the club's version is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Finalizing a season's standings requires `expected_season_version` matching the season's current `version`. Finalizing replaces the prior snapshot set and may be repeated legitimately while the season is being closed; a finalize whose `expected_season_version` no longer matches because a prior finalize advanced the season is rejected with `ERR_STALE_VERSION` (HTTP 412).

Each of these version fields is a non-optional input on its endpoint. Endpoints not named in this section do not take a version field of any kind.

### 2.8. The Append-Only Club Ledger

Every club has a ledger, and every movement of money into or out of a club's account is a `LedgerEntry` row. Each row carries an `entry_type` drawn from `MEMBERSHIP_DUE`, `ENTRY_FEE`, `ENTRY_REFUND`, `TRAVEL_STIPEND`, `ADJUSTMENT`, and `REVERSAL`; a signed `amount_cents` in which credits are positive and debits negative and which may never be zero; an optional free-text `memo`; and the `posted_by_user_id` of the operator whose request created it. System flows post their own types — membership flows post `MEMBERSHIP_DUE`, tournament flows post `ENTRY_FEE` and `ENTRY_REFUND`, stipend flows post `TRAVEL_STIPEND` — while a manual post by the treasurer is permitted only with `entry_type` equal to `ADJUSTMENT`; any other type in a manual post is rejected with `ERR_INVALID_REQUEST`.

The club's `account_balance_cents` is always derived, never stored independently: it is the sum of `amount_cents` over every ledger row the club has, including reversing rows. Corrections therefore never edit history — a reversal is a new `REVERSAL` row whose amount is the negation of the original's, linked back to it through `reversal_of_id`, while the original row keeps its amount and has its `reversed_by_id` set to the reversal's id. A club's balance is allowed to go below zero only through a manual `ADJUSTMENT`; every ordinary charge flow validates funds before posting, as described in §3.2 and §3.7.

### 2.9. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers (for example, `/api/meets/{meetId}/pairings`), the system validates the existence of each identifier in sequential, left-to-right order, and the request is rejected immediately with `ERR_NOT_FOUND` at the first identifier that does not resolve. Body-supplied foreign keys — fields such as `club_id`, `player_id`, `season_id`, `host_club_id`, `away_club_id`, `white_player_id`, `black_player_id`, `coach_id`, `meet_id`, and `tournament_id` on creation payloads — resolve the same way: an unresolvable reference is rejected with `ERR_NOT_FOUND`.

### 2.10. Validation Order

Every request is evaluated against a fixed ladder of checks, and the first failing rung determines the error returned. The ladder, from first to last:

1. Presence of the authentication headers — a missing or empty `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Role permission — the caller's role must be listed for the endpoint, otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
3. Path identifiers resolve, left to right — otherwise `ERR_NOT_FOUND` (HTTP 404).
4. Body foreign-key references resolve — otherwise `ERR_NOT_FOUND` (HTTP 404).
5. Entity-backed ownership — a `ClubCoach` acting outside their club's scope, a `Proctor` confirming another coach's assignment, or a coach withdrawing a dispute they did not raise yields `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403).
6. Optimistic concurrency — a stale `expected_meet_version`, `expected_club_version`, or `expected_season_version` yields `ERR_STALE_VERSION` (HTTP 412).
7. Request shape — missing required fields, wrong types, out-of-range enum values, unknown fields, improperly ordered date ranges, a `reason` shorter than ten characters, a zero `amount_cents`, or round and board numbers outside a meet's configured bounds all yield `ERR_INVALID_REQUEST` (HTTP 400).
8. State checks — the target entity must be in a from-state of the requested transition, otherwise the per-entity state error (HTTP 409) such as `ERR_SEASON_INVALID_STATE`, `ERR_MEET_INVALID_STATE`, `ERR_PAIRING_INVALID_STATE`, `ERR_DISPUTE_INVALID_STATE`, `ERR_TOURNAMENT_INVALID_STATE`, `ERR_SECTION_INVALID_STATE`, `ERR_ENTRY_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_BID_INVALID_STATE`, `ERR_CLUB_INVALID_STATE`, `ERR_COACH_INVALID_STATE`, `ERR_PLAYER_INVALID_STATE`, `ERR_MEMBERSHIP_NOT_PAYABLE`, or `ERR_MEMBERSHIP_NOT_REFUNDABLE`. Where one operation guards two state machines — registering an entry touches both tournament and section — the tournament state check precedes the section state check.
9. Business integrity — writes attempted by or for a `SUSPENDED` club yield `ERR_CLUB_SUSPENDED` (HTTP 403); use of a `SUSPENDED` player in a pairing or entry yields `ERR_PLAYER_SUSPENDED` (HTTP 403); a ledger reversal requested by the operator who posted the original yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); a pairing confirmation by a coach of the reporting club yields `ERR_SAME_CLUB_CONFIRMATION` (HTTP 403).
10. Business referential rules — a pairing or entry for a player lacking a paid-or-waived membership yields `ERR_MEMBERSHIP_REQUIRED` (HTTP 409); pairing players assigned to the wrong club or color yield `ERR_PLAYER_CLUB_MISMATCH` (HTTP 409).
11. Business constraints — a rating outside a section's band (`ERR_RATING_OUT_OF_BAND`), a provisional player in a non-provisional section (`ERR_PROVISIONAL_NOT_ALLOWED`), a full section (`ERR_SECTION_FULL`), an over-capacity tournament (`ERR_TOURNAMENT_CAPACITY_EXCEEDED`), duplicate records (`ERR_DUPLICATE_ENTRY`, `ERR_DUPLICATE_MEMBERSHIP`, `ERR_DUPLICATE_STIPEND`), a meet pitting a club against itself (`ERR_SAME_CLUB_MEET`), or a second reversal of the same ledger row (`ERR_ALREADY_REVERSED`), all HTTP 409.
12. Business temporal rules — a calendar collision on a meet date (`ERR_MEET_DATE_CONFLICT`) or a proctor booked across the mandatory rest buffer (`ERR_PROCTOR_DOUBLE_BOOKED`), both HTTP 409.
13. Fiscal guard — a charge that would drive a club's balance below zero yields `ERR_INSUFFICIENT_FUNDS` (HTTP 402).

## 3. Business Logic & Workflows

### 3.1. Seasons, Clubs, and the People Inside Them

Everything in the league hangs off a **Season**. A `FederationAdmin` opens one by supplying a `name`, an inclusive `start_date`, and an inclusive `end_date` that must fall strictly after the start. The season's financial parameters come along at creation: a `dues_deadline` (an ISO 8601 UTC instant) that splits regular from late membership pricing, a positive `regular_due_cents`, a `late_due_cents` that must be at least the regular amount, and a non-negative `travel_base_cents` that seeds the travel stipend program. Three competitive parameters carry defaults: `provisional_game_threshold` defaults to 20 and must be at least 1, `base_rating` defaults to 800, and `state_bid_slots_per_region` defaults to 2 and must be at least 1. A new season begins in `REGISTRATION`, moves to `ACTIVE` when the administrator activates it, later to `FINALIZING` for postseason close-out, and finally to `COMPLETED`. Finalization is not one-way: reopening returns a `FINALIZING` season to `ACTIVE`, and the season may cycle between the two. Each of these transitions requires the season to be in exactly the listed from-state, otherwise the request fails with `ERR_SEASON_INVALID_STATE`. The seasons list supports filtering by `status`.

Clubs register into a season through the administrator, who supplies the `season_id`, a club `name`, the `school_name` the club represents, a `region_code` placing the club in a federation region (bid pools and standings are computed per season, and qualification per region), and a `travel_tier` of 1, 2, or 3 that multiplies the season's travel base. A new club starts with `account_balance_cents` at zero, `projected_travel_stipend_cents` at zero, and `status` of `GOOD_STANDING`. Standing is partly automatic and partly administrative: ledger activity flips a club between `GOOD_STANDING` and `DELINQUENT` as described in §3.2, while only a `FederationAdmin` may suspend a club or reinstate one. Suspension is permitted from either `GOOD_STANDING` or `DELINQUENT`; reinstatement returns the club to `GOOD_STANDING`, except that a club whose balance is still negative after reinstatement lands in `DELINQUENT` instead. Calling suspend or reinstate from any other state is rejected with `ERR_CLUB_INVALID_STATE`. While a club is `SUSPENDED`, writes that touch its roster, its meets, its tournament entries, or its bids are rejected with `ERR_CLUB_SUSPENDED`. The clubs list supports filtering by `season_id`, `status`, and `region_code`, and a single-club read exposes the computed balance, standing, and projected stipend alongside the stored fields.

A club's people are **Coaches** and **Players**. The administrator registers a coach with the owning `club_id`, a `full_name`, an `email`, and a `certification_level` of `CLUB`, `CERTIFIED`, or `SENIOR`; coaches begin `ACTIVE`. Deactivation moves a coach to `INACTIVE` and, as a cascade, releases every proctor assignment still `ASSIGNED` to that coach; reactivation restores `ACTIVE`. Either transition attempted from the wrong state fails with `ERR_COACH_INVALID_STATE`. The coaches list filters by `club_id` and `status`.

Players are registered by a `ClubCoach` of the owning club or by the administrator, with `club_id`, `full_name`, and a `grade_level` between 1 and 12 inclusive. Transfers may arrive with federation-seeded history: an optional `initial_rating`, which defaults to the `base_rating` of the season the club is registered in, and an optional `initial_rated_games`, which defaults to 0 and may not be negative. From these seeds the system derives the player's competitive profile: `rating` begins at the initial rating, `rated_games_played` begins at the seeded game count, `peak_rating` begins at the initial rating, `is_provisional` reports whether the player remains below the season's provisional threshold, and `performance_points` starts at 0. A player begins `ACTIVE`; a coach of the club or the administrator may deactivate to `INACTIVE` and reactivate back, while only the administrator may suspend a player from either `ACTIVE` or `INACTIVE`. Wrong-state calls fail with `ERR_PLAYER_INVALID_STATE`, and a `SUSPENDED` player may not be placed in a pairing or a tournament entry — such attempts fail with `ERR_PLAYER_SUSPENDED`. The fourth state, `GRADUATED`, is never set directly: the system grants it at season completion, as described in §3.9. The players list filters by `club_id`, `status`, and `is_provisional`.

### 3.2. Membership Dues, the Club Ledger, and Financial Standing

Before a player can compete, the club owes the federation a membership for the season. Creating a membership takes a `player_id` and a `season_id`; only one membership may exist per player-and-season pair, and a duplicate attempt is rejected with `ERR_DUPLICATE_MEMBERSHIP`. The invoiced `fee_cents` is computed at creation from the logical clock: a membership created at or before the season's `dues_deadline` pays `regular_due_cents`, and one created after pays `late_due_cents` — the boundary is inclusive, so a creation exactly at the deadline pays the regular amount. A new membership is `INVOICED`, with `paid_at` empty.

Three roles can settle an invoice — a `ClubCoach` of the player's club, the `Treasurer`, or a `FederationAdmin`. Payment requires the membership to be `INVOICED` (otherwise `ERR_MEMBERSHIP_NOT_PAYABLE`) and requires the club to afford it: if subtracting the fee would drive the club's `account_balance_cents` below zero, the payment is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402). A successful payment posts a `MEMBERSHIP_DUE` ledger entry debiting exactly `fee_cents` with `membership_id` set on the row, stamps `paid_at` from the logical clock, moves the membership to `PAID`, and then recomputes the club's balance and standing. The administrator may instead waive an `INVOICED` membership, moving it to `WAIVED` with no ledger activity; waiving from any other state also fails with `ERR_MEMBERSHIP_NOT_PAYABLE`. Finally, the `Treasurer` alone may refund a `PAID` membership, moving it to `REFUNDED`; the refund posts a second `MEMBERSHIP_DUE` entry crediting exactly `fee_cents` with `membership_id` set, and the club's balance and standing are recomputed. Refunding a membership that is not `PAID` fails with `ERR_MEMBERSHIP_NOT_REFUNDABLE`.

Every ledger post — payment, refund, entry fee, stipend, adjustment, or reversal — triggers the same reconciliation. The club's `account_balance_cents` is recomputed as the sum of `amount_cents` over all of the club's ledger rows, and then standing is re-evaluated: a club in `GOOD_STANDING` whose balance has fallen below zero flips to `DELINQUENT`, and a club in `DELINQUENT` whose balance has returned to zero or above flips back to `GOOD_STANDING`. Posts never change a `SUSPENDED` club's standing.

Two manual ledger operations exist, and both are deliberate about who may perform them. The `Treasurer` posts manual adjustments with an `entry_type` of `ADJUSTMENT`, a non-zero signed `amount_cents`, an optional `memo`, and the OCC field `expected_club_version` per §2.7; the server records the caller as `posted_by_user_id`, recomputes balance and standing, and increments the club's `version` by one. The `Auditor` — and only the auditor — corrects history: reversing a ledger entry creates a `REVERSAL` row whose amount is the exact negation of the original's, linked via `reversal_of_id`, with an optional `memo`, while the original row's `reversed_by_id` is set to point at the reversal. Segregation of duties is enforced: the auditor's `X-User-ID` must differ from the original row's `posted_by_user_id`, or the reversal fails with `ERR_SEGREGATION_OF_DUTIES`. An entry that has already been reversed — and any `REVERSAL` row itself — cannot be reversed; such attempts fail with `ERR_ALREADY_REVERSED`. A reversal likewise recomputes the club's balance and standing and increments the club's `version` by one. Ledger reads support filtering by `club_id`, `membership_id`, `entry_id`, `reversal_of_id`, and `entry_type`, in addition to the per-club ledger listing.

### 3.3. Meet Scheduling and Calendar Occupation

The regular season's competitive unit is the **Meet**: a dual encounter in which the host club holds the white pieces on every board and the away club holds black. A `ClubCoach` of the host club, or the administrator, creates a meet with `season_id`, `host_club_id`, `away_club_id`, a `scheduled_date`, a `rounds_count` of at least 1, and a `boards_count` of at least 1. The two clubs must differ — a meet pitting a club against itself is rejected with `ERR_SAME_CLUB_MEET` — and the meet begins in `DRAFT`.

Scheduling is the administrator's job and is where the calendar rules bite. Moving a meet from `DRAFT` to `SCHEDULED` runs four checks, with the meet's own state verified first (a meet not in `DRAFT` fails with `ERR_MEET_INVALID_STATE`): neither the host nor the away club may be `SUSPENDED` (`ERR_CLUB_SUSPENDED`); neither club may already occupy the `scheduled_date` with another meet in `SCHEDULED`, `PAIRINGS_PUBLISHED`, or `IN_PROGRESS` — occupation is whole-day, so any same-day overlap conflicts (`ERR_MEET_DATE_CONFLICT`); and the meet's season must be `ACTIVE` (`ERR_SEASON_INVALID_STATE`). Once scheduled, the meet holds that date for both clubs until it leaves the occupying states.

Plans change. A coach of either club or the administrator may postpone a `SCHEDULED` meet, moving it to `POSTPONED`; a postponed meet occupies no date at all, releasing the calendar slot for both clubs. The administrator may later reschedule a `POSTPONED` meet back to `SCHEDULED` by supplying a new `scheduled_date`; the rescheduling re-runs the suspension check on both clubs and the date-occupation check against the new date, with the same `ERR_CLUB_SUSPENDED` and `ERR_MEET_DATE_CONFLICT` rejections, and the meet-state check again comes first. Cancellation is terminal and available from `DRAFT`, `SCHEDULED`, or `POSTPONED` (any other state fails with `ERR_MEET_INVALID_STATE`): cancelling a meet cascades to every pairing of that meet still in `SCHEDULED` or `REPORTED`, moving each to `CANCELLED`, and releases every proctor assignment for the meet still in `ASSIGNED` or `CONFIRMED`, moving each to `RELEASED`. The meets list filters by `season_id`, `host_club_id`, `away_club_id`, and `status`.

### 3.4. Pairings, Results, and Confirmation

While a meet is in `DRAFT` or `SCHEDULED`, coaches of the two clubs and the administrator fill its board slots by creating **Pairings**; attempts while the meet is in any later or terminal state fail with `ERR_MEET_INVALID_STATE`. A pairing names a `round_number` between 1 and the meet's `rounds_count` and a `board_number` between 1 and its `boards_count` — numbers outside those bounds fail with `ERR_INVALID_REQUEST` — plus a `white_player_id` drawn from the host club and a `black_player_id` drawn from the away club. Putting a player on the wrong side of the board fails with `ERR_PLAYER_CLUB_MISMATCH`; seating a player who lacks a `PAID` or `WAIVED` membership for the season fails with `ERR_MEMBERSHIP_REQUIRED`; seating a `SUSPENDED` player fails with `ERR_PLAYER_SUSPENDED`. Slot assignment is last-write-wins by design: creating a pairing supersedes any existing non-terminal pairing at the same round-and-board slot, moving the old one to `REPLACED`, and this may happen repeatedly while the meet is being arranged. Because arrangement is iterative, the create carries the OCC field `expected_meet_version` per §2.7, and each successful create increments the meet's `version` by one. A new pairing starts in `SCHEDULED` with its `result` set to `UNREPORTED` and `was_confirmed` false. The pairings listings — both the global list and the per-meet list — filter by `meet_id`, `white_player_id`, `black_player_id`, and `status` on the global list.

Publication locks the grid. The administrator publishes pairings only from `SCHEDULED` (state checked first, `ERR_MEET_INVALID_STATE`), and only when every round-and-board slot in the full grid — every combination of round 1 through `rounds_count` and board 1 through `boards_count` — is covered by a pairing still in `SCHEDULED`; an incomplete grid fails with `ERR_INCOMPLETE_PAIRINGS`. Publication moves the meet to `PAIRINGS_PUBLISHED`. Starting the meet requires `PAIRINGS_PUBLISHED` (again state first) and at least one proctor assignment for the meet in `CONFIRMED`; without one, the start fails with `ERR_NO_CONFIRMED_PROCTOR`. The meet is then `IN_PROGRESS` and games may be reported.

Result reporting is a two-party handshake between the clubs. A `ClubCoach` of either the host or the away club reports the outcome of a board — the pairing must be in `SCHEDULED` (state checked first, `ERR_PAIRING_INVALID_STATE`) and the meet must be `IN_PROGRESS` (`ERR_MEET_INVALID_STATE`); a coach of any other club is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. The reported `result` — one of `WHITE_WIN`, `BLACK_WIN`, `DRAW`, `WHITE_FORFEIT_WIN`, `BLACK_FORFEIT_WIN`, or `DOUBLE_FORFEIT` — is recorded on the pairing along with the reporter's identity in `reported_by_coach_id`, and the pairing moves to `REPORTED`. Confirmation then requires a coach of the *other* club: the confirmer must belong to the host or away club and must not belong to the reporting coach's club, or the confirmation fails with `ERR_SAME_CLUB_CONFIRMATION`. A successful confirmation moves the pairing to `CONFIRMED`, sets `was_confirmed` to true, and stamps `confirmed_at` from the logical clock — and it is at this instant, not before, that ratings move. For a played result (`WHITE_WIN`, `BLACK_WIN`, or `DRAW`) the system creates two rating events, one per player, and recomputes both players' competitive fields as described in §3.5. For a forfeit result (`WHITE_FORFEIT_WIN`, `BLACK_FORFEIT_WIN`, or `DOUBLE_FORFEIT`) no rating events exist at all; the system recomputes only performance points — one point to the forfeit winner, zero to the loser, zero to both on a double forfeit — and the forfeit-loss tallies.

Completing the meet is the administrator's final step: the meet must be `IN_PROGRESS` (state first), and every pairing not already `REPLACED` or `CANCELLED` must be `CONFIRMED`, otherwise the completion fails with `ERR_UNCONFIRMED_PAIRINGS`. Completion moves the meet to `COMPLETED`, promotes each of the meet's `CONFIRMED` proctor assignments to `COMPLETED`, and recomputes `projected_travel_stipend_cents` for both clubs, because a completed meet now counts toward the stipend formulas of §3.9.

### 3.5. Rating Events, Replays, and Performance Points

Ratings in this league are an append-only history, not a number someone edits. Each time a pairing reaches `CONFIRMED` with a played result, the system appends one `RatingEvent` per player. An event records the `player_id`, the originating `pairing_id`, the `season_id`, the `formula_variant` that was applied (`PROVISIONAL` or `ESTABLISHED`), the `opponent_rating_snapshot` — the opponent's rating frozen at the original confirmation, never recomputed afterward — the player's `score` from their own perspective (1 for a win, one half for a draw, 0 for a loss), the `k_factor` used (empty for provisional events, which have no K), the `rating_before` and `rating_after` the event produced, and the `confirmed_at` instant that orders it. Events begin `EFFECTIVE` and leave that state only when a dispute overturn voids them, as described in §3.6. The rating-events list filters by `player_id`, `pairing_id`, `season_id`, and `status`.

The update formula has two variants, selected per player per event. Let the player's games-before count be their seeded `initial_rated_games` plus the count of their prior `EFFECTIVE` events. When that count is below the season's `provisional_game_threshold`, the `PROVISIONAL` variant applies — a running average with no K-factor: the new rating is the player's pre-event rating multiplied by the games-before count, plus the opponent's snapshot rating, plus a 400-point swing scaled by twice the score minus one (so a win adds 400 points, a draw adds nothing, and a loss subtracts 400), the whole sum divided by the games-before count plus one, and the quotient rounded half up to a whole number. When the games-before count is at least the threshold, the `ESTABLISHED` variant applies — an Elo expectation with a tiered K: the expected score is one divided by the quantity one plus ten raised to the power of the opponent's snapshot rating minus the player's pre-event rating, that difference divided by 400; K is 32 while the pre-event rating is below 2100, 24 while it is at least 2100 and below 2400, and 16 once it reaches 2400; and the new rating is the pre-event rating plus the round-half-up of K multiplied by the actual score minus the expected score. Both variants clamp the outcome to the rating floor of 100 and the rating ceiling of 2900: a computed rating below the floor becomes 100, and one above the ceiling becomes 2900. The two variants genuinely diverge — identical pre-event ratings, opponents, and scores produce different new ratings depending on which side of the threshold the player stands.

A player's published fields are always a replay, recomputed whenever one of their events is created or voided. The replay takes the player's `EFFECTIVE` events ordered by `confirmed_at` ascending, breaking ties by the creating pairing's `created_at` ascending — never by event id. Starting from `rating` equal to `initial_rating` and a game count equal to `initial_rated_games`, each event in order rebases: the event's `rating_before` becomes the running rating, its `rating_after` is recomputed by the update formula against the frozen `opponent_rating_snapshot` and the event's `score` with the running game count as games-before, and then the running rating advances to that `rating_after` and the game count grows by one. Because the opponent snapshot is frozen at original confirmation, each player's replay is self-contained — no other player's history is consulted. After the pass, the player's `rating` is the running value, `rated_games_played` is the running count, `peak_rating` is the maximum of the `initial_rating` and every effective event's `rating_after`, and `is_provisional` reports whether the final count is still below the season's threshold.

Alongside ratings, each player accumulates `performance_points`, recomputed in full from sources whenever results change: three points for each confirmed meet game the player won, one point for each confirmed draw, one point for each confirmed forfeit win, nothing for a loss or a double forfeit, and two points for each of the player's tournament entries that has reached `CHECKED_IN` or `FINISHED`. Only pairings in `CONFIRMED` status belonging to meets that are `IN_PROGRESS` or `COMPLETED` count toward these tallies.

### 3.6. Disputes and Adjudication

When a club believes a reported result is wrong, a `ClubCoach` of either participating club disputes the pairing. The pairing must be in `REPORTED` or `CONFIRMED` (state checked first, `ERR_PAIRING_INVALID_STATE`), and a coach outside the two clubs is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`. The dispute payload carries a `reason` of at least ten characters — anything shorter fails with `ERR_INVALID_REQUEST` — and the system creates a `Dispute` in `OPEN` with the caller recorded as `raised_by_coach_id`, while the pairing moves to `DISPUTED`.

Adjudication belongs to the federation. The administrator first opens review, moving the dispute from `OPEN` to `UNDER_REVIEW` (any other state fails with `ERR_DISPUTE_INVALID_STATE`), and then resolves it with an `outcome` of `UPHELD` or `OVERTURNED` plus optional `resolution_notes`. The two outcomes are mirror images with strict payload rules. For `UPHELD`, `resolved_result` must be absent — supplying one fails with `ERR_INVALID_REQUEST` — and the reported result stands: the pairing returns from `DISPUTED` to `CONFIRMED`, and if it had never been confirmed before the dispute, its rating side effects are applied now, exactly as on a first confirmation. For `OVERTURNED`, `resolved_result` is required and must not be `UNREPORTED` — violations fail with `ERR_INVALID_REQUEST` — and the pairing returns to `CONFIRMED` with its `result` replaced by the resolved result. The overturn then cascades in a fixed order: first the pairing's result is replaced; second, if the pairing's `was_confirmed` is true, the two original rating events become `VOIDED`; third, each affected player is replayed per §3.5; fourth, if the new result is a played one, two fresh rating events are created with opponent snapshots taken *after* the void-replay, and both players are replayed again. If the pairing had never been confirmed, there is nothing to void: instead `was_confirmed` becomes true, `confirmed_at` is stamped, and the rating side effects of the (possibly resolved) result are applied directly.

The coach who raised a dispute may retract it while it is still `OPEN`: withdrawal requires the caller to be exactly the coach in `raised_by_coach_id` (anyone else is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`, and a dispute no longer `OPEN` fails with `ERR_DISPUTE_INVALID_STATE`). Withdrawal moves the dispute to `WITHDRAWN` and restores the pairing without touching ratings: the pairing returns to `CONFIRMED` if its `was_confirmed` is true, and to `REPORTED` otherwise. The disputes list filters by `pairing_id`, `raised_by_coach_id`, and `status`.

### 3.7. Tournaments: Sections, Entries, and Fees

Alongside dual meets, the federation runs **Tournaments**. The administrator creates one with a `season_id`, an optional `host_club_id`, a `name`, an inclusive `start_date` and an inclusive `end_date` that may equal the start, a non-negative `entry_fee_cents`, a `capacity` of at least 1 bounding the total non-withdrawn entries across all sections, and optionally an early-bird scheme: an `early_bird_deadline` instant and an `early_bird_discount_pct` fraction between 0 and 1. The discount percentage is required exactly when the deadline is set and must be absent otherwise; violations fail with `ERR_INVALID_REQUEST`. A tournament begins in `DRAFT`, opens for registration (`REGISTRATION_OPEN`), closes (`REGISTRATION_CLOSED`), may reopen to `REGISTRATION_OPEN` again, starts (`RUNNING`), and completes (`COMPLETED`) — each step guarded by `ERR_TOURNAMENT_INVALID_STATE` from the wrong state. Starting requires `REGISTRATION_CLOSED` (state checked first) and at least one `CONFIRMED` proctor assignment for the tournament, otherwise `ERR_NO_CONFIRMED_PROCTOR`; the start also closes every section still `OPEN` or `LOCKED`. Completion requires `RUNNING` and moves every entry still `REGISTERED` or `CHECKED_IN` to `FINISHED` while promoting the tournament's `CONFIRMED` proctor assignments to `COMPLETED`.

Cancellation is the heavy path. The administrator may cancel from `DRAFT`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, or `RUNNING`, and the cancel unwinds money in a four-link cascade: first, every entry in `REGISTERED` or `CHECKED_IN` becomes `WITHDRAWN` with `refund_cents` set to the full `fee_cents` regardless of tournament state; second, for each withdrawn entry an `ENTRY_REFUND` ledger entry crediting exactly that entry's fee posts with `entry_id` set; third, each affected club's `account_balance_cents` is recomputed; fourth, each club's standing auto-transition is applied. The same cancel also moves sections in `OPEN` or `LOCKED` to `CLOSED` and releases the tournament's proctor assignments in `ASSIGNED` or `CONFIRMED` to `RELEASED`.

Sections slice a tournament by strength. Each section is created with a `name`, an inclusive lower rating bound `min_rating` and an inclusive upper bound `max_rating` that must be at least the minimum, an `allow_provisional` flag defaulting to false, and a `max_entries` of at least 1. A section opens in `OPEN` with `current_entries` at zero; that counter always reflects the count of entries in `REGISTERED`, `CHECKED_IN`, or `FINISHED`. The administrator may lock an `OPEN` section to `LOCKED` and unlock it back; both directions fail with `ERR_SECTION_INVALID_STATE` from the wrong state. The terminal `CLOSED` is never set directly — the system closes sections when the tournament starts or is cancelled. The sections lists filter by `tournament_id` and `status`.

Entry creation is the densest guarded write in the system, performed by a `ClubCoach` registering one of their players by `player_id`. Its checks run in the ladder order of §2.10, and within the state rung the order is pinned: the tournament must be `REGISTRATION_OPEN` first (`ERR_TOURNAMENT_INVALID_STATE`), and only then is the section checked to be `OPEN` (`ERR_SECTION_INVALID_STATE`). Interleaved with those gates: the player must hold a `PAID` or `WAIVED` membership for the season (`ERR_MEMBERSHIP_REQUIRED`), must not be `SUSPENDED` (`ERR_PLAYER_SUSPENDED`), and their club must not be `SUSPENDED` (`ERR_CLUB_SUSPENDED`); the player's current `rating` must fall within the section's inclusive band (`ERR_RATING_OUT_OF_BAND`); a provisional player may enter only if the section allows it (`ERR_PROVISIONAL_NOT_ALLOWED`); the section must have room — `current_entries` equal to `max_entries` means full (`ERR_SECTION_FULL`); the tournament's total non-withdrawn entries across all sections must remain within `capacity` (`ERR_TOURNAMENT_CAPACITY_EXCEEDED`); and the player may hold only one non-`WITHDRAWN` entry per section (`ERR_DUPLICATE_ENTRY`). Because uniqueness excludes withdrawn rows, a player who withdrew may re-enter the same section later.

The charged `fee_cents` is computed at creation. When the tournament has an early-bird deadline and the logical clock reads at or before it — the boundary is inclusive — the fee is the round-half-up of `entry_fee_cents` multiplied by one minus `early_bird_discount_pct`; otherwise the full `entry_fee_cents` is charged. Rounding order is pinned: each entry's fee is rounded to whole cents at creation, and a club's total charge is the sum of the per-entry rounded fees, never a rounding of the unrounded sum. Creation then debits the club: if subtracting the fee would drive `account_balance_cents` below zero, the entry is rejected with `ERR_INSUFFICIENT_FUNDS`; otherwise an `ENTRY_FEE` ledger entry posts for exactly `fee_cents` with `entry_id` set, the club's balance and standing are recomputed, and the section's `current_entries` grows by one. The new entry is `REGISTERED` with `refund_cents` at zero.

Withdrawal is a coach action from `REGISTERED` or `CHECKED_IN` — anything else fails with `ERR_ENTRY_INVALID_STATE` — and the refund is tiered by the tournament's status at withdrawal time and by the path taken. A manual withdrawal while the tournament is `REGISTRATION_OPEN` refunds the full fee; while `REGISTRATION_CLOSED`, half the fee rounded half up; while `RUNNING` or `COMPLETED`, nothing. Two overrides sit on top of that table: a manual withdrawal from `CHECKED_IN` always refunds zero regardless of tournament state, and the tournament-cancel cascade always refunds the full fee regardless of state. Whenever the computed `refund_cents` is positive, an `ENTRY_REFUND` ledger entry posts crediting that amount with `entry_id` set, and the club's balance and standing are recomputed; either way the section's `current_entries` shrinks by one and the entry becomes `WITHDRAWN`. Finally, on-site check-in moves an entry from `REGISTERED` to `CHECKED_IN`; it is performed by a `Proctor` or the administrator, requires the entry to be `REGISTERED` (state checked first, `ERR_ENTRY_INVALID_STATE`) and the tournament to be `RUNNING` (`ERR_TOURNAMENT_INVALID_STATE`), and awards the player two `performance_points`. The entries lists filter by `section_id`, `player_id`, and `status`; the tournaments list filters by `season_id`, `host_club_id`, and `status`.

### 3.8. Proctoring and Event Staffing

Meets and tournaments are staffed by coaches serving as proctors. The administrator creates a `ProctorAssignment` naming a `coach_id` and an `event_type` of `MEET` or `TOURNAMENT`; a `meet_id` is required exactly when the type is `MEET` and a `tournament_id` exactly when it is `TOURNAMENT`, with mismatches rejected as `ERR_INVALID_REQUEST`. Double-booking is prevented with a rest buffer: if the coach already holds an assignment in `ASSIGNED` or `CONFIRMED` whose event interval — a meet occupies its single `scheduled_date`, a tournament the span from its `start_date` through its `end_date` — expanded by one rest day on each side intersects the new event's interval, the assignment is rejected with `ERR_PROCTOR_DOUBLE_BOOKED`. A new assignment begins `ASSIGNED`.

From there the lifecycle is small but strict. The assigned coach confirms their own duty: acting with the `Proctor` role, their `X-User-ID` must equal the assignment's `coach_id` (otherwise `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`) and the assignment must be `ASSIGNED` (state checked first, `ERR_ASSIGNMENT_INVALID_STATE`); confirmation moves it to `CONFIRMED`. The administrator may release an assignment from either `ASSIGNED` or `CONFIRMED`, moving it to `RELEASED`, and the same release happens automatically when the underlying event is cancelled — for a meet, its assignments in `ASSIGNED` or `CONFIRMED`; for a tournament, likewise — while a coach's deactivation releases only that coach's assignments still `ASSIGNED`. When the staffed event completes, a `CONFIRMED` assignment becomes `COMPLETED`. When a confirmed proctor fails to appear, the administrator marks the assignment `NO_SHOW`, a transition permitted only from `CONFIRMED`. The assignments list filters by `coach_id`, `meet_id`, `tournament_id`, and `status`.

### 3.9. Closing the Season: Standings, Stipends, Invoices, and Qualification Bids

Team standings are always computable and only sometimes snapshotted. For each club of a season, over meets with status `COMPLETED` only, board points accrue per `CONFIRMED` pairing: a `WHITE_WIN` gives the host 1 and the away 0; a `BLACK_WIN` gives the host 0 and the away 1; a `DRAW` gives each side one half; a `WHITE_FORFEIT_WIN` gives the host 1 and the away 0; a `BLACK_FORFEIT_WIN` gives the host 0 and the away 1; and a `DOUBLE_FORFEIT` gives neither side anything. Each side's `forfeit_losses` grow by one for every game it loses by forfeit, with a double forfeit charging both sides. A meet's `game_points` are the sum of its board points, and `match_points` follow from comparing the two clubs' game points: 2 for more, 1 for an exact tie, 0 for fewer. The `sonneborn_berger` tiebreak sums, over the club's completed meets, the opponent's final season `match_points` multiplied by the club's own match result against that opponent (1 for a win, one half for a tie, 0 for a loss). Ranking follows a pinned cascade with no randomness: `match_points` descending; then head-to-head match points descending, applied only when exactly two clubs are tied on match points and skipped — contributing nothing — for larger tied groups; then `sonneborn_berger` descending; then `game_points` descending; then `forfeit_losses` ascending; and finally the club's `created_at` ascending, so the earlier-registered club ranks higher — ids are never used as a tiebreak.

The live standings read recomputes all of this on every call and returns it as a `standings` array. Snapshotting is a separate administrator action available only while the season is `FINALIZING`: it carries the OCC field `expected_season_version` per §2.7, deletes any prior snapshots of the season, writes one `StandingSnapshot` per club — each recording `season_id`, `club_id`, `match_points`, `game_points`, `sonneborn_berger`, `forfeit_losses`, the computed `rank`, and an `is_final` flag that is always true, since snapshots are always final — increments the season's `version` by one, and returns the created set. The snapshots list filters by `season_id` and `club_id`.

Travel money comes in two flavors from the same formula family. The forward-looking figure, exposed on every club read as `projected_travel_stipend_cents`, is the club's `travel_tier` multiplied by the season's `travel_base_cents` multiplied by the smaller of ten and the count of the club's meets this season in `SCHEDULED`, `PAIRINGS_PUBLISHED`, `IN_PROGRESS`, or `COMPLETED`. The actual stipend, posted by the `Treasurer` while the season is `FINALIZING` (any other season state fails with `ERR_SEASON_INVALID_STATE`), counts only `COMPLETED` meets: `meets_counted` is the smaller of ten and the club's completed-meet count, and `amount_cents` is the tier times the base times `meets_counted`. One stipend may exist per season-and-club pair; a second posting is rejected with `ERR_DUPLICATE_STIPEND`. When the computed amount is positive, a `TRAVEL_STIPEND` ledger entry credits it and the club's balance and standing recompute, with the row linked as `ledger_entry_id`; when the amount is zero, no ledger row is posted at all and `ledger_entry_id` stays empty. With identical underlying data, a scheduled-but-uncompleted meet makes the projected figure larger than the actual one. The stipends list filters by `season_id`, `club_id`, and `ledger_entry_id`.

A club's season invoice answers "what did this club owe us?" with a volume credit, and its evaluation order is pinned because the credit tier keys on the pre-credit subtotal. First, `dues_subtotal_cents` sums `fee_cents` over the memberships of the club's players for the season that are `PAID` — memberships that are `WAIVED`, `INVOICED`, or `REFUNDED` contribute zero. Second, `entries_subtotal_cents` sums, over all tournament entries of the club's players in the season's tournaments, each entry's `fee_cents` minus its `refund_cents`. Third, the subtotal is the sum of those two. Fourth, the `credit_tier_pct` is 0.10 when the subtotal reaches 80,000 cents, else 0.05 when it reaches 40,000 cents, else 0 — the boundaries are inclusive, so a subtotal of exactly 40,000 cents earns the five-percent tier while 39,999 cents earns nothing. Fifth, `volume_credit_cents` is the round-half-up of the subtotal multiplied by the tier; rounding happens only at this step. Sixth, `total_cents` is the subtotal minus the credit. The invoice read takes a `season_id` query parameter and returns all five figures.

Postseason **Qualification Bids** are generated in bulk by the administrator while the season is `FINALIZING` (otherwise `ERR_SEASON_INVALID_STATE`). For `INDIVIDUAL_STATE` bids, a player is eligible when they are `ACTIVE`, their club is not `SUSPENDED`, their membership for the season is `PAID` or `WAIVED`, their `performance_points` have reached at least 6, and they hold no existing bid for the season in `OFFERED` or `ACCEPTED`. The eligible pool is grouped by the club's `region_code`, ranked by a pinned order — `performance_points` descending, then `rating` descending, then `rated_games_played` descending, then the player's `created_at` ascending, with ids never used — and generation offers bids to the top `state_bid_slots_per_region` players of each region. For `TEAM_STATE` bids, generation offers one bid per region to the club ranked first by the standings cascade among that region's clubs. Every generated bid begins `OFFERED` with an `offer_deadline` exactly seven days after the logical clock; team and national bids carry no `player_id`.

A bid is answered by a `ClubCoach` of the club on the bid. Acceptance requires the bid to be `OFFERED` (state checked first, `ERR_BID_INVALID_STATE`), the bid's season to be `ACTIVE` or `FINALIZING` (`ERR_SEASON_INVALID_STATE`), and the coach to belong to the bid's club (`ERR_FORBIDDEN_RESOURCE_OWNERSHIP`); the bid becomes `ACCEPTED`. Accepting a `TEAM_STATE` bid has a knock-on: when the club's `account_balance_cents` is zero or positive, the system immediately creates a `NATIONAL` bid for the same club, `OFFERED` with a deadline seven days from the clock. Declining requires the same `OFFERED` state and ownership checks and moves the bid to `DECLINED`; when a declined bid is `INDIVIDUAL_STATE`, the system promotes the single highest-ranked player in the same region who satisfies the full eligibility filter and has no `INDIVIDUAL_STATE` bid for the season in any status — `OFFERED`, `ACCEPTED`, `DECLINED`, and `EXPIRED` all exclude — creating them a fresh `OFFERED` bid, or creating nothing when the pool is empty. The same promotion follows when the clock sweep of §2.5 expires an individual bid. The bids list filters by `season_id`, `club_id`, `player_id`, `status`, and `bid_type`.

Completion is the season's final gate. The administrator completes a season only from `FINALIZING` — the state check comes first, with `ERR_SEASON_INVALID_STATE` — and two further conditions must hold in order: at least one standing snapshot must exist for the season (`ERR_STANDINGS_NOT_FINAL`), and no dispute in `OPEN` or `UNDER_REVIEW` may remain on pairings of the season's meets (`ERR_OPEN_DISPUTES_EXIST`). On success the season becomes `COMPLETED`, and every `ACTIVE` player of the season's clubs whose `grade_level` is 12 is moved to `GRADUATED`.

## 4. Endpoint Definitions

Operations that create a new resource — a season, club, coach, player, membership, ledger entry (including a reversal), meet, pairing, dispute, tournament, section, entry, proctor assignment, a generated bid set, a standings snapshot set, or a travel stipend — return `201 Created`. Operations that transition or otherwise modify an existing resource return `200 OK`, as do all reads and the clock-setting capability. In the table below, "All roles" means all five roles defined in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock; sweeps expired bids | FederationAdmin |
| POST | `/api/seasons` | Create a season | FederationAdmin |
| GET | `/api/seasons` | List seasons | All roles |
| GET | `/api/seasons/{seasonId}` | Get a season | All roles |
| POST | `/api/seasons/{seasonId}/activate` | Move a season REGISTRATION → ACTIVE | FederationAdmin |
| POST | `/api/seasons/{seasonId}/finalize` | Move a season ACTIVE → FINALIZING | FederationAdmin |
| POST | `/api/seasons/{seasonId}/reopen` | Move a season FINALIZING → ACTIVE | FederationAdmin |
| POST | `/api/seasons/{seasonId}/complete` | Complete a FINALIZING season | FederationAdmin |
| GET | `/api/seasons/{seasonId}/standings` | Live computed standings for the season | All roles |
| POST | `/api/seasons/{seasonId}/standings/finalize` | Snapshot standings (replaces prior set) | FederationAdmin |
| POST | `/api/seasons/{seasonId}/bids/generate` | Bulk-generate individual and team bids | FederationAdmin |
| POST | `/api/clubs` | Register a club for a season | FederationAdmin |
| GET | `/api/clubs` | List clubs | All roles |
| GET | `/api/clubs/{clubId}` | Get a club with computed balance, standing, and projected stipend | All roles |
| POST | `/api/clubs/{clubId}/suspend` | Suspend a club in GOOD_STANDING or DELINQUENT | FederationAdmin |
| POST | `/api/clubs/{clubId}/reinstate` | Reinstate a SUSPENDED club | FederationAdmin |
| GET | `/api/clubs/{clubId}/season-invoice` | Computed season invoice with volume credit | FederationAdmin, ClubCoach, Treasurer, Auditor |
| POST | `/api/coaches` | Create a coach | FederationAdmin |
| GET | `/api/coaches` | List coaches | All roles |
| GET | `/api/coaches/{coachId}` | Get a coach | All roles |
| POST | `/api/coaches/{coachId}/deactivate` | Deactivate a coach; releases ASSIGNED assignments | FederationAdmin |
| POST | `/api/coaches/{coachId}/reactivate` | Reactivate an INACTIVE coach | FederationAdmin |
| POST | `/api/players` | Create a player (coach limited to own club) | ClubCoach, FederationAdmin |
| GET | `/api/players` | List players | All roles |
| GET | `/api/players/{playerId}` | Get a player with computed rating fields | All roles |
| POST | `/api/players/{playerId}/deactivate` | Move a player ACTIVE → INACTIVE | ClubCoach, FederationAdmin |
| POST | `/api/players/{playerId}/reactivate` | Move a player INACTIVE → ACTIVE | ClubCoach, FederationAdmin |
| POST | `/api/players/{playerId}/suspend` | Suspend an ACTIVE or INACTIVE player | FederationAdmin |
| POST | `/api/memberships` | Create a membership (fee computed at creation) | ClubCoach, FederationAdmin |
| GET | `/api/memberships` | List memberships | All roles |
| GET | `/api/memberships/{membershipId}` | Get a membership | All roles |
| POST | `/api/memberships/{membershipId}/pay` | Pay an INVOICED membership; debits the club ledger | ClubCoach, Treasurer, FederationAdmin |
| POST | `/api/memberships/{membershipId}/waive` | Waive an INVOICED membership | FederationAdmin |
| POST | `/api/memberships/{membershipId}/refund` | Refund a PAID membership; credits the club ledger | Treasurer |
| POST | `/api/clubs/{clubId}/ledger-entries` | Post a manual ADJUSTMENT entry | Treasurer |
| GET | `/api/clubs/{clubId}/ledger-entries` | List ledger entries of a club | All roles |
| GET | `/api/ledger-entries` | List ledger entries with filters | All roles |
| GET | `/api/ledger-entries/{ledgerEntryId}` | Get a ledger entry | All roles |
| POST | `/api/ledger-entries/{ledgerEntryId}/reverse` | Post a REVERSAL negating the original entry | Auditor |
| POST | `/api/meets` | Create a meet in DRAFT | ClubCoach, FederationAdmin |
| GET | `/api/meets` | List meets | All roles |
| GET | `/api/meets/{meetId}` | Get a meet | All roles |
| POST | `/api/meets/{meetId}/schedule` | Schedule a DRAFT meet with standing and date checks | FederationAdmin |
| POST | `/api/meets/{meetId}/postpone` | Postpone a SCHEDULED meet; releases the date | ClubCoach, FederationAdmin |
| POST | `/api/meets/{meetId}/reschedule` | Reschedule a POSTPONED meet to a new date | FederationAdmin |
| POST | `/api/meets/{meetId}/cancel` | Cancel a meet; cascades to pairings and assignments | FederationAdmin |
| POST | `/api/meets/{meetId}/pairings` | Create a pairing; supersedes the slot's prior pairing | ClubCoach, FederationAdmin |
| GET | `/api/meets/{meetId}/pairings` | List pairings of a meet | All roles |
| POST | `/api/meets/{meetId}/publish-pairings` | Publish pairings; requires full grid coverage | FederationAdmin |
| POST | `/api/meets/{meetId}/start` | Start a published meet; requires a CONFIRMED proctor | FederationAdmin |
| POST | `/api/meets/{meetId}/complete` | Complete a meet; requires all live pairings CONFIRMED | FederationAdmin |
| GET | `/api/pairings` | List pairings with filters | All roles |
| GET | `/api/pairings/{pairingId}` | Get a pairing | All roles |
| POST | `/api/pairings/{pairingId}/report-result` | Report a board result while the meet is IN_PROGRESS | ClubCoach |
| POST | `/api/pairings/{pairingId}/confirm` | Confirm a result by the other club's coach | ClubCoach |
| POST | `/api/pairings/{pairingId}/dispute` | Dispute a REPORTED or CONFIRMED pairing | ClubCoach |
| GET | `/api/disputes` | List disputes | All roles |
| GET | `/api/disputes/{disputeId}` | Get a dispute | All roles |
| POST | `/api/disputes/{disputeId}/open-review` | Move a dispute OPEN → UNDER_REVIEW | FederationAdmin |
| POST | `/api/disputes/{disputeId}/resolve` | Resolve a dispute UPHELD or OVERTURNED | FederationAdmin |
| POST | `/api/disputes/{disputeId}/withdraw` | Withdraw an OPEN dispute by the raising coach | ClubCoach |
| POST | `/api/tournaments` | Create a tournament in DRAFT | FederationAdmin |
| GET | `/api/tournaments` | List tournaments | All roles |
| GET | `/api/tournaments/{tournamentId}` | Get a tournament | All roles |
| POST | `/api/tournaments/{tournamentId}/open-registration` | Move a tournament DRAFT → REGISTRATION_OPEN | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/close-registration` | Move a tournament REGISTRATION_OPEN → REGISTRATION_CLOSED | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/reopen-registration` | Reopen a REGISTRATION_CLOSED tournament | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/start` | Start a tournament; closes sections; requires a CONFIRMED proctor | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/complete` | Complete a RUNNING tournament | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/cancel` | Cancel a tournament; full-refund cascade | FederationAdmin |
| POST | `/api/tournaments/{tournamentId}/sections` | Create a section with an inclusive rating band | FederationAdmin |
| GET | `/api/tournaments/{tournamentId}/sections` | List sections of a tournament | All roles |
| GET | `/api/sections` | List sections with filters | All roles |
| GET | `/api/sections/{sectionId}` | Get a section | All roles |
| POST | `/api/sections/{sectionId}/lock` | Lock an OPEN section | FederationAdmin |
| POST | `/api/sections/{sectionId}/unlock` | Unlock a LOCKED section | FederationAdmin |
| POST | `/api/sections/{sectionId}/entries` | Register a player into a section; debits the club ledger | ClubCoach |
| GET | `/api/sections/{sectionId}/entries` | List entries of a section | All roles |
| GET | `/api/entries` | List entries with filters | All roles |
| GET | `/api/entries/{entryId}` | Get an entry | All roles |
| POST | `/api/entries/{entryId}/withdraw` | Withdraw an entry; refund per tier | ClubCoach |
| POST | `/api/entries/{entryId}/check-in` | Check in a REGISTERED entry while the tournament runs | Proctor, FederationAdmin |
| POST | `/api/proctor-assignments` | Assign a coach as proctor to a meet or tournament | FederationAdmin |
| GET | `/api/proctor-assignments` | List proctor assignments | All roles |
| GET | `/api/proctor-assignments/{assignmentId}` | Get a proctor assignment | All roles |
| POST | `/api/proctor-assignments/{assignmentId}/confirm` | Confirm an assignment; only the assigned coach may confirm | Proctor |
| POST | `/api/proctor-assignments/{assignmentId}/release` | Release an ASSIGNED or CONFIRMED assignment | FederationAdmin |
| POST | `/api/proctor-assignments/{assignmentId}/mark-no-show` | Mark a CONFIRMED proctor as no-show | FederationAdmin |
| GET | `/api/qualification-bids` | List qualification bids | All roles |
| GET | `/api/qualification-bids/{bidId}` | Get a qualification bid | All roles |
| POST | `/api/qualification-bids/{bidId}/accept` | Accept an OFFERED bid; team accepts may spawn a NATIONAL bid | ClubCoach |
| POST | `/api/qualification-bids/{bidId}/decline` | Decline an OFFERED bid; individual declines promote the next player | ClubCoach |
| GET | `/api/rating-events` | List rating events | All roles |
| GET | `/api/rating-events/{ratingEventId}` | Get a rating event | All roles |
| GET | `/api/standings-snapshots` | List standing snapshots | All roles |
| GET | `/api/standings-snapshots/{snapshotId}` | Get a standing snapshot | All roles |
| POST | `/api/travel-stipends` | Post the actual travel stipend for a club | Treasurer |
| GET | `/api/travel-stipends` | List travel stipends | All roles |
| GET | `/api/travel-stipends/{stipendId}` | Get a travel stipend | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SEASON_INVALID_STATE` | 409 Conflict |
| `ERR_CLUB_INVALID_STATE` | 409 Conflict |
| `ERR_COACH_INVALID_STATE` | 409 Conflict |
| `ERR_PLAYER_INVALID_STATE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_PAYABLE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_MEET_INVALID_STATE` | 409 Conflict |
| `ERR_PAIRING_INVALID_STATE` | 409 Conflict |
| `ERR_DISPUTE_INVALID_STATE` | 409 Conflict |
| `ERR_TOURNAMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SECTION_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_BID_INVALID_STATE` | 409 Conflict |
| `ERR_CLUB_SUSPENDED` | 403 Forbidden |
| `ERR_PLAYER_SUSPENDED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_SAME_CLUB_CONFIRMATION` | 403 Forbidden |
| `ERR_MEMBERSHIP_REQUIRED` | 409 Conflict |
| `ERR_PLAYER_CLUB_MISMATCH` | 409 Conflict |
| `ERR_RATING_OUT_OF_BAND` | 409 Conflict |
| `ERR_PROVISIONAL_NOT_ALLOWED` | 409 Conflict |
| `ERR_SECTION_FULL` | 409 Conflict |
| `ERR_TOURNAMENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 Conflict |
| `ERR_DUPLICATE_STIPEND` | 409 Conflict |
| `ERR_SAME_CLUB_MEET` | 409 Conflict |
| `ERR_ALREADY_REVERSED` | 409 Conflict |
| `ERR_MEET_DATE_CONFLICT` | 409 Conflict |
| `ERR_PROCTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDS` | 402 Payment Required |
| `ERR_INCOMPLETE_PAIRINGS` | 409 Conflict |
| `ERR_NO_CONFIRMED_PROCTOR` | 409 Conflict |
| `ERR_UNCONFIRMED_PAIRINGS` | 409 Conflict |
| `ERR_STANDINGS_NOT_FINAL` | 409 Conflict |
| `ERR_OPEN_DISPUTES_EXIST` | 409 Conflict |
