# Campus Rec Intramurals API — Product Requirements Document

## 1. Introduction

A campus recreation department runs a busy program: gym courts and fields that open and close on recurring weekly schedules, intramural leagues that move from registration through a regular season into playoffs, student officials who must be scheduled and paid, fitness classes with waitlists, and a front desk that rents lockers and lends equipment. Today these operations live in spreadsheets and paper waivers, and the friction shows up everywhere — double-booked courts, disputed game scores with no resolution path, officials paid the wrong amount after a forfeit, and members borrowing equipment while sitting on unpaid fines.

This document specifies a REST API that consolidates those operations into one deterministic system. The API manages member eligibility (waivers, memberships, injury holds), league and team lifecycle from registration to championship, game scheduling against facility availability, a fork-and-confirm score reporting workflow with dispute resolution, officials assignment and payroll, equipment checkout with late fees, locker rental, and group fitness classes with waitlist promotion. All time-based rules — term windows, waiver validity, lateness, report windows — evaluate against a controllable logical clock so that behavior is reproducible. Five peer roles share the surface: recreation administrators, league coordinators, facility managers, members, and staff, each owning a disjoint set of write operations.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. Header values are stripped of surrounding whitespace before evaluation, so a whitespace-only value counts as empty. If either header is missing or empty, or if `X-User-Role` is not one of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is valid but not permitted for the endpoint — or an entity-backed ownership check fails — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles, spelled exactly as the `X-User-Role` value must present them, are `RecAdmin`, `LeagueCoordinator`, `FacilityManager`, `Member`, and `Staff`.

`RecAdmin`, `LeagueCoordinator`, and `FacilityManager` are opaque operator identities: for each of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. `RecAdmin` is the campus recreation department administrator and owns configuration entities (member creation, leagues, facilities, staff, equipment pools, lockers, fitness classes), authoritative score and dispute resolution, medical clearance of injury reports, and control of the logical clock. `LeagueCoordinator` runs intramural league operations: the league lifecycle transitions, team registration and division placement, scheduling and rescheduling, forfeits, playoff launch, free-agent placement, officials assignment, and pay settlement. `FacilityManager` runs facility and equipment operations: closures, equipment returns and lost declarations, locker release, and filing injury reports.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign-key field to `X-User-ID`. A member may sign their own waiver, purchase memberships, pay fines, register as a free agent, register for classes, check out equipment, and rent lockers — all self-service only. A member who captains a team additionally acts on that team: adding roster entries, removing roster entries, withdrawing the team, and submitting score reports for the side their team plays on.

When `X-User-Role` is `Staff`, `X-User-ID` is the `id` of the acting `Staff`; ownership checks on any resource that references a `Staff` compare the resource's staff foreign-key field to `X-User-ID`. A staff member may respond to officiating assignments addressed to them and may complete fitness classes they instruct.

All five roles may call every read endpoint. Write authorization per endpoint is enumerated in §4.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10; a supplied `limit` below 1 or above 100 is clamped into that range rather than rejected, so the effective minimum is 1 and the maximum 100. `offset` defaults to 0; a negative `offset` is clamped to 0. A non-integer `limit` or `offset` is `ERR_VALIDATION`. Results are sorted by `created_at` ascending, with equal timestamps broken by creation order, and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. The `meta` envelope of a list response includes `limit`, `offset`, `total_count`, and `has_more`, in addition to the standard request identifiers. List endpoints also accept the filter parameters named against each of them in §4 (for example, listing memberships may be narrowed by `member_id`, `term`, `status`, or `supersedes_membership_id`; games by `league_id`, `facility_id`, `home_team_id`, `away_team_id`, `status`, `bracket_round`, `next_game_id`, or `forfeiting_team_id`; teams by `league_id`, `captain_member_id`, `division_name`, or `status`; roster entries by `team_id`, `member_id`, or `status`; injury reports by `member_id`, `game_id`, or `status`; officiating assignments by `game_id`, `staff_id`, or `status`; equipment pools by `item_type`; equipment checkouts by `member_id`, `equipment_pool_id`, or `status`; lockers by `rented_by_member_id`, `status`, or `size`; fitness classes by `instructor_staff_id`, `facility_id`, `status`, or `class_type`; and class registrations by `fitness_class_id`, `member_id`, or `status`).

### 2.4. The Logical Clock

The server maintains a logical clock, settable through an administrator-only test-driving capability that advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC). The call sets the clock to exactly the supplied instant — moving it backward is permitted, with no monotonicity check — and responds with an object carrying a single `current_utc` field holding the new logical time. Every server-generated timestamp — the envelope's `api_request_timestamp`, `created_at` and `updated_at`, stored score-report `reported_at` values, and pool-entry registration times — is rendered from this logical clock. Before any such call, the server startup default is exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time. Every time-based rule in this document — membership term windows, waiver academic-year validity, equipment lateness, game report windows, closure overlap — evaluates against this logical clock. Advancing the clock re-evaluates lazy membership expiry on subsequent reads and eligibility checks.

### 2.5. Common Resource Properties and Versioning

Every resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, and an `updated_at` timestamp, both ISO 8601 UTC with three fractional digits, plus a `version` integer that starts at 1 and increments by 1 on every mutation of that resource. Every datetime-valued field the API returns — not only `created_at` and `updated_at` but also domain datetimes such as the league window timestamps, game and fitness-class `start_at`/`end_at`, closure `start_at`/`end_at`, `due_at`, `returned_at`, and report or pool-entry timestamps — is rendered in this same format, ISO 8601 UTC with exactly three fractional digits (for example `2026-09-10T18:00:00.000Z`), whatever string format the client supplied the value in. Mutations that ripple through a parent-child relationship bump the parent's `version` as well where this document says so — for example, signing a waiver, purchasing a membership, and paying a fine each increment the member's `version`; opening registration, closing registration, starting the season, starting playoffs, cancelling the league, registering a free agent, placing a free agent, and scheduling a game each increment the league's `version`; creating a closure increments the facility's `version`.

**Optimistic concurrency control.** Three write operations are guarded against stale parent observations, and each requires a non-optional expected-version field in the request body:

- Purchasing a membership for a member must carry `expected_member_version` equal to the member's current `version`. Because purchasing supersedes any currently `ACTIVE` membership — legitimate renewal behavior — the guard exists so a client that priced the transaction against an older member aggregate (before a waiver re-signature or another purchase advanced the version) does not proceed on a stale read. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Scheduling a game within a league must carry `expected_league_version` equal to the league's current `version`; scheduling mutates the league aggregate and increments `League.version`, and a stale expectation means the client's view of existing games and division loads is out of date. Two games at disjoint times are both legitimate — only the stale view is rejected, with `ERR_STALE_VERSION` (HTTP 412).
- Creating a closure on a facility must carry `expected_facility_version` equal to the facility's current `version`; a closure bumps games and classes out of its window, and the set of colliding bookings may have changed since the client last read the facility. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

The expected-version check runs after existence checks and before state checks. No other endpoint accepts a version field.

### 2.6. Path Scoping and Referential Existence

Although the resource topology is flat, several writes are scoped under a parent path (for example, memberships under a member, games under a league, closures under a facility, registrations under a class). Path resource identifiers are validated for existence left to right; a missing path resource yields `ERR_NOT_FOUND` (HTTP 404). Requests to undeclared paths, and requests using an unsupported method on a declared path, are likewise rejected with `ERR_NOT_FOUND` (HTTP 404). Body-supplied foreign-key references are likewise validated for existence, and a `division_name` that does not refer to an entry of the league's `divisions` array yields `ERR_DIVISION_NOT_FOUND` (HTTP 404).

### 2.7. Monetary Precision and Rounding

All money amounts are integer cents. Wherever a division appears in a pay or fee formula, the result is rounded half-up to whole cents. Two rounding orders are pinned and must not be altered: prorated membership pricing rounds the weekly rate half-up to whole cents *before* multiplying by remaining weeks; instructor pay is rounded half-up *per session*, and term totals are sums of the already-rounded per-session values — never a sum of raw values rounded once. Sportsmanship ratings are the one non-integer quantity: they are rounded half-up to two decimal places.

### 2.8. Validation Priority Order

When a request fails multiple checks, the error returned is determined by a fixed priority order — lower priority number wins. The order is:

1. **Authentication** (`ERR_UNAUTHENTICATED`): headers present, non-empty, role declared.
2. **Authorization and ownership** (`ERR_FORBIDDEN`): role permitted for the endpoint; entity-backed ownership checks (a `Member` caller's `X-User-ID` must equal the path or body `member_id`; roster and score-report callers must be the team's captain; registration, checkout, locker, fine-payment, waiver, and membership actions are self-service; a `Staff` caller must be the assignment's official or the class's instructor). An ownership comparison that must read a persisted entity — a team's captaincy, an assignment's official, a class's instructor, a locker's renter, or the owning member of a membership or registration — is evaluated after that entity's existence check. Likewise, on member writes scoped under a non-member path parent — free-agent registration under a league, class registration under a class, locker rental under a locker — the path parent's existence check runs before the body `member_id` self-service comparison; on `/v1/members/{member_id}/...` paths and on parent-less self-service writes (equipment checkout, injury report), the caller-versus-`member_id` comparison precedes existence.
3. **Existence** (`ERR_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`): path identifiers left to right, then body foreign keys, then division membership.
4. **Request shape** (`ERR_VALIDATION`): required fields present; enum values valid; numeric ranges; interval well-formedness; conditional staff fields; fine-payment amounts; and the other field-level rules detailed in §3.
5. **Concurrency** (`ERR_STALE_VERSION`): the three OCC guards of §2.5.
6. **State preconditions** (`ERR_INVALID_STATE`, `ERR_MEMBER_SUSPENDED`, `ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`, `ERR_GAME_NOT_REPORTABLE`): evaluated path-scope first, then body-referenced entities — the league status gate, then team status, then member status, then the target resource's own transition legality.
7. **Waiver validity** (`ERR_WAIVER_INVALID`).
8. **Membership active** (`ERR_MEMBERSHIP_INACTIVE`): always evaluated after the waiver check.
9. **Temporal checks**, in this fixed sub-order: `ERR_GAME_IN_PAST`, then `ERR_FACILITY_OUTSIDE_HOURS`, then `ERR_FACILITY_CLOSED`, then `ERR_FACILITY_DOUBLE_BOOKED`, then `ERR_TEAM_TIME_CONFLICT`, then `ERR_CLASS_TIME_CONFLICT`, then `ERR_OFFICIAL_DOUBLE_BOOKED`.
10. **Constraint checks** (for example `ERR_TEAM_ALREADY_IN_LEAGUE`, `ERR_MEMBER_ALREADY_IN_LEAGUE`, `ERR_ALREADY_IN_POOL`, `ERR_CAPTAIN_REMOVAL_FORBIDDEN`, `ERR_DIVISION_SKILL_MISMATCH`, `ERR_TEAMS_NOT_IN_SAME_DIVISION`, `ERR_TIE_NOT_ALLOWED`, `ERR_FORFEITING_TEAM_INVALID`, `ERR_STAFF_NOT_OFFICIAL`, `ERR_STAFF_NOT_INSTRUCTOR`, `ERR_OFFICIAL_CERT_TOO_LOW`, `ERR_INSTRUCTOR_NOT_CERTIFIED`, `ERR_INJURY_GAME_MISMATCH`, `ERR_CLASS_ALREADY_REGISTERED`, `ERR_RENTAL_EXISTS`, `ERR_DUPLICATE_SCORE_REPORT`, `ERR_TOO_FEW_TEAMS`, `ERR_LEAGUE_NOT_READY_FOR_SEASON`, `ERR_PLAYOFFS_NOT_READY`, `ERR_NO_ELIGIBLE_TEAMS`).
11. **Capacity checks**, which always run after constraint checks: `ERR_LEAGUE_FULL`, `ERR_DIVISION_FULL`, `ERR_ROSTER_FULL`, `ERR_ASSIGNMENT_LIMIT_REACHED`, `ERR_EQUIPMENT_INSUFFICIENT`, `ERR_NO_TEAM_AVAILABLE`, `ERR_LOCKER_UNAVAILABLE`. A full fitness class is deliberately *not* an error — it produces a `WAITLISTED` registration.
12. **Fiscal gate** (`ERR_OUTSTANDING_FINES`): the outstanding-fines check on equipment checkout runs last of all.

### 2.9. Member Eligibility Gates

Five member-facing operations — adding a roster entry, registering as a free agent, registering for a fitness class, checking out equipment, and renting a locker — are eligibility-gated. Each requires, in order: the member's `status` must be `ACTIVE` (a member under an injury hold is `SUSPENDED` and is rejected with `ERR_MEMBER_SUSPENDED`); the member must hold a waiver valid for the current academic year per §3.1 (otherwise `ERR_WAIVER_INVALID`); and the member must hold a membership whose lazily evaluated status is `ACTIVE` (otherwise `ERR_MEMBERSHIP_INACTIVE`). Equipment checkout additionally requires that the member's `outstanding_fines_cents` be zero, enforced as the final check with `ERR_OUTSTANDING_FINES` (HTTP 402). Locker rental is explicitly *not* fine-gated.

### 2.10. Facility Booking Fit

Games and fitness classes are bookings against a facility and obey the same fit rules. A booking's start and end must land on a single calendar date. The facility's `operating_windows` — recurring weekly windows, each a `day_of_week` (0 for Monday through 6 for Sunday) with `open_minute` and `close_minute` expressed as minutes after midnight, where the open minute is at least 0 and strictly before the close minute, which is at most 1440 — must contain a window matching the booking's weekday such that the booking's exact start instant is at or after `open_minute` minutes after midnight and its exact end instant is at or before `close_minute` minutes after midnight — the comparison uses the full timestamp at second precision, not a minute-truncated one; ending exactly at the close minute is allowed. A booking that fits no single window is rejected with `ERR_FACILITY_OUTSIDE_HOURS` (HTTP 422). A booking that overlaps any closure interval is rejected with `ERR_FACILITY_CLOSED` (HTTP 409): closures are half-open intervals from their start up to but not including their end, so a booking overlaps a closure when the booking starts before the closure ends and the closure starts before the booking ends; a booking starting exactly at a closure's end is allowed. A booking that overlaps another `SCHEDULED` game or `SCHEDULED` fitness class at the same facility is rejected with `ERR_FACILITY_DOUBLE_BOOKED` (HTTP 409); bookings are half-open intervals, so adjacency — one booking's end equal to the other's start — is allowed with no buffer.

## 3. Business Logic & Workflows

### 3.1. Members, Waivers, and Memberships

A `RecAdmin` enrolls a participant by creating a `Member` with `email`, `full_name`, and `affiliation`. Email uniqueness is enforced case-insensitively across all members; a duplicate email is rejected with `ERR_VALIDATION` (HTTP 400). The `affiliation` is one of `STUDENT`, `FACULTY`, or `COMMUNITY` and drives fee tables throughout the system. A new member starts with `status` `ACTIVE`, `waiver_signed_date` null, `outstanding_fines_cents` zero, and `no_show_count` zero. The member's `status` is never mutated by a direct endpoint: it flips between `ACTIVE` and `SUSPENDED` only through the injury-report cascades of §3.7.

A member signs the liability waiver through a self-service waiver-signing action, which sets `waiver_signed_date` to the logical current date and bumps the member's `version`. Re-signing simply overwrites the date. Waiver validity is defined over academic years: for a date in August through December, its academic year begins August 1 of that calendar year; for a date in January through July, its academic year began August 1 of the previous calendar year; an academic-year window runs from its August 1 start through the following July 31 inclusive. A waiver is valid exactly when `waiver_signed_date` is not null and the academic year of `waiver_signed_date` equals the academic year of the logical current date — a waiver signed on 2026-09-15 is valid from 2026-08-01 through 2027-07-31 and becomes stale on 2027-08-01.

A member purchases a `Membership` by naming a `term` — `FALL_2026`, `SPRING_2027`, or `SUMMER_2027` — and presenting `expected_member_version` per §2.5. Term windows are fixed: `FALL_2026` runs 2026-08-24 through 2026-12-11 (110 days, 16 weeks), `SPRING_2027` runs 2027-01-12 through 2027-05-07 (116 days, 17 weeks), and `SUMMER_2027` runs 2027-05-24 through 2027-08-06 (75 days, 11 weeks). Flat term fees are 6000 cents for `STUDENT`, 20000 cents for `FACULTY`, and 32000 cents for `COMMUNITY`.

The fee calculation uses the logical clock's date as the purchase date. Purchasing within the first seven days of the term — day 1 through day 7, inclusive — yields `pricing_variant` `FULL` and a `fee_cents` equal to the flat affiliation term fee. Purchasing on day 8 or later yields `pricing_variant` `PRORATED`: the weekly rate is computed by dividing the affiliation term fee by the term's whole-week count (the term's inclusive day count divided by 7, rounded up) and rounding that weekly rate half-up to whole cents *first*; the remaining-week count is the number of days from the purchase date through the term end, inclusive, divided by 7 and rounded up; `fee_cents` is then the rounded weekly rate *multiplied* by the remaining weeks. This round-then-multiply order deliberately diverges from a naive daily-proration interpretation. Purchasing after the term's end date is rejected with `ERR_VALIDATION`; purchasing before the term start is allowed and is charged at `FULL`.

A membership starts `ACTIVE`. If the member already has an `ACTIVE` membership, the new purchase is a create-with-supersede: the prior membership moves to `SUPERSEDED`, the new membership becomes the member's unique active one, and its `supersedes_membership_id` points at the superseded row. Lazy expiry is applied to the member's existing memberships before the supersede target is chosen, so a prior membership whose term has lapsed flips to `EXPIRED` instead of `SUPERSEDED`, and the new membership's `supersedes_membership_id` is then null. At most one membership per member is `ACTIVE` at any time; `SUPERSEDED`, `CANCELLED`, and `EXPIRED` are terminal. A membership addressed by its `membership_id` may be cancelled by its owning member or a `RecAdmin` while `ACTIVE`; cancellation transitions it to `CANCELLED`, issues no refund, and the member immediately loses membership-gated eligibility on subsequent checks (attempting to cancel a non-`ACTIVE` membership is `ERR_INVALID_STATE`). Expiry is lazy: on every read of a membership and on every eligibility check, if the logical current date is after the term's end date, the membership is treated as `EXPIRED` — the term's end date itself is still inclusive-active. The flip is persisted: the observing read or check sets `status` to `EXPIRED` and increments the membership's `version`. Lazy expiry also runs on the cancellation path, so a term-lapsed membership is already `EXPIRED` when the `ACTIVE`-only cancellation check runs.

Members settle debts through fine payments: a self-service payment carries `amount_cents`, which must be greater than zero and no more than the member's current `outstanding_fines_cents` (violations are `ERR_VALIDATION`); the amount is subtracted from `outstanding_fines_cents` and the member's `version` increments. The balance never goes negative. The payment responds with the updated member object.

### 3.2. League Setup, Team Registration, and Rosters

A `RecAdmin` creates a `League` in `DRAFT` status, supplying `name`; a `sport` of `BASKETBALL`, `SOCCER`, `VOLLEYBALL`, `FLAG_FOOTBALL`, or `DODGEBALL`; a `divisions` array whose entries each carry a `name` unique within the league, a `capacity` of at least 1, and `skill_min`/`skill_max` bounds with 1 at the low end, 10 at the high end, and `skill_min` no greater than `skill_max`; a registration window `registration_open_at` strictly before `registration_close_at`, which must fall at or before `season_start_at`; a season with `season_start_at` strictly before `season_end_at`; `team_capacity` no less than `min_teams`; `min_teams` at least 2; and `roster_max` no less than `roster_min`, with `roster_min` at least 1. Violations of these shapes are `ERR_VALIDATION`. The `divisions` array may be empty at creation; opening registration later requires it to be non-empty. A new league's `free_agent_pool` is empty.

A `LeagueCoordinator` opens registration, moving the league `DRAFT → REGISTRATION_OPEN`; this requires the `divisions` array to be non-empty (otherwise `ERR_LEAGUE_NOT_READY_FOR_SEASON`) and the registration/season date chain above to hold (otherwise `ERR_VALIDATION`). While the league is `REGISTRATION_OPEN`, the coordinator registers teams: each `Team` is created with `league_id`, `name`, `captain_member_id`, and a self-assessed `skill_rating` from 1 to 10, and begins in `REGISTERED` status with `division_name` null and all counters (`wins`, `losses`, `ties`, `points`, `forfeit_count`, `sportsmanship_points_total`, `sportsmanship_rating_count`, `active_roster_count`) at zero. Team creation is refused when the league is not `REGISTRATION_OPEN` (`ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`), when the captain already captains a non-`WITHDRAWN` team in the same league (`ERR_TEAM_ALREADY_IN_LEAGUE`), or when the league already holds `team_capacity` teams in any status other than `WITHDRAWN` (`ERR_LEAGUE_FULL`). Team creation creates no roster entries — not even one for the captain: the roster starts empty, and a `CAPTAIN` entry arises only when the captain is added through the roster-add path below, never automatically.

While the league is `REGISTRATION_OPEN` (otherwise `ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`) and the team is `REGISTERED` or `PLACED` (otherwise `ERR_INVALID_STATE`), the team's captain may add players, supplying a `member_id`. The added member must clear the eligibility gates of §2.9 (suspension, waiver, membership), must not already hold an `ACTIVE` roster entry on any team of the same league (`ERR_MEMBER_ALREADY_IN_LEAGUE`), and the add must not push the team's `active_roster_count` beyond the league's `roster_max` (`ERR_ROSTER_FULL`). A successful add creates an `ACTIVE` roster entry — `CAPTAIN` if the member is the team's captain, else `PLAYER` — and increments the team's `active_roster_count`. An entry, addressed by its `roster_entry_id`, may be removed by the team's captain or a `LeagueCoordinator` while the entry is `ACTIVE` and the team's roster is still unlocked (team `REGISTERED` or `PLACED`); removal transitions the entry to `REMOVED` and decrements `active_roster_count`. The captain's own entry can never be removed — any attempt is rejected with `ERR_CAPTAIN_REMOVAL_FORBIDDEN` — and removals against a locked roster or a non-`ACTIVE` entry are `ERR_INVALID_STATE`.

Individual players without a team self-register into the league's free-agent pool by supplying their `member_id` and optionally a `preferred_division_name` — which, when present, must be a non-empty string naming one of the league's divisions (otherwise `ERR_DIVISION_NOT_FOUND`); the league must be `REGISTRATION_OPEN` (otherwise `ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`), the member must clear the eligibility gates, must not already hold an `ACTIVE` roster entry in the league (`ERR_MEMBER_ALREADY_IN_LEAGUE`), and must not already have a `POOLED` entry in this league (`ERR_ALREADY_IN_POOL`). A successful registration appends a `POOLED` entry — recording `member_id`, `preferred_division_name`, the logical registration time as `registered_at`, and status — to `free_agent_pool`, bumps the league's `version`, and responds with HTTP 201 carrying the updated league object. A coordinator may later place a `POOLED` free agent: the selector considers teams of the league in `REGISTERED` or `PLACED` status whose `active_roster_count` is below `roster_max`; if the pool entry's `preferred_division_name` is set, only teams whose `division_name` equals it remain candidates — strictly, with no fallback to other divisions; candidates are ranked by `active_roster_count` ascending with ties broken by earlier team `created_at`; the head receives a new `ACTIVE` `PLAYER` roster entry, the pool entry becomes `PLACED`, and the team's `active_roster_count` increments. An empty candidate set is rejected with `ERR_NO_TEAM_AVAILABLE`. Placing a member who has no pool entry in the league is `ERR_NOT_FOUND`; placing one whose entry exists but is not `POOLED` is `ERR_INVALID_STATE`. A successful placement responds with HTTP 200 carrying the newly created roster entry. A free agent pool entry may also become `WITHDRAWN` when the league is cancelled.

### 3.3. Scheduling: Divisions, Facilities, and Games

Once registration closes, the coordinator closes registration, moving the league `REGISTRATION_OPEN → SCHEDULING`; this requires at least `min_teams` teams in `REGISTERED` or `PLACED` status (otherwise `ERR_TOO_FEW_TEAMS`). During `SCHEDULING`, the coordinator places each `REGISTERED` team into a division: the league must be `SCHEDULING` (otherwise `ERR_INVALID_STATE`), the named division must exist in the league's `divisions` (otherwise `ERR_DIVISION_NOT_FOUND`), the team's `skill_rating` must lie within the division's `skill_min`–`skill_max` bounds, both bounds inclusive (otherwise `ERR_DIVISION_SKILL_MISMATCH`, which is checked *before* capacity), and the division must currently hold fewer teams than its `capacity` — counting the league's teams in `PLACED`, `ACTIVE`, or `SUSPENDED` status bearing that `division_name` (otherwise `ERR_DIVISION_FULL`). Placement sets the team's `division_name` and moves it `REGISTERED → PLACED`.

Starting the season (`SCHEDULING → IN_SEASON`) requires at least `min_teams` teams in `REGISTERED` or `PLACED` (otherwise `ERR_TOO_FEW_TEAMS`), every such team to have been placed — a lingering `REGISTERED` team without a division fails with `ERR_LEAGUE_NOT_READY_FOR_SEASON` — and every `PLACED` team to have `active_roster_count` at least `roster_min` (likewise `ERR_LEAGUE_NOT_READY_FOR_SEASON`). On success, every `PLACED` team becomes `ACTIVE` and rosters lock: roster additions and removals are rejected while a team is `ACTIVE` or `SUSPENDED`.

Facilities are created by a `RecAdmin` with a `name`, a `kind` of `COURT`, `FIELD`, `ROOM`, or `POOL`, and the recurring `operating_windows` of §2.10; a new facility has an empty `closures` list. A `FacilityManager` creates a closure by supplying `start_at`, `end_at` (which must be strictly after `start_at`, otherwise `ERR_VALIDATION`), a `reason`, and `expected_facility_version` per §2.5; the closure is recorded as a half-open interval with a generated `closure_id`, its creation triggers the deep cascade of §3.9, and the call responds with HTTP 201 carrying the updated facility.

Games are scheduled by a `LeagueCoordinator` within a league, supplying `home_team_id`, `away_team_id`, `facility_id`, `start_at`, `end_at`, and `expected_league_version` per §2.5. The league must be `SCHEDULING`, `IN_SEASON`, or `PLAYOFFS` (otherwise `ERR_INVALID_STATE`). The two teams must differ (`home_team_id` equal to `away_team_id` is `ERR_VALIDATION`) and must share the same non-null `division_name` (otherwise `ERR_TEAMS_NOT_IN_SAME_DIVISION`); the game records that shared division as its own `division_name`. A team that is `SUSPENDED` or `WITHDRAWN` cannot be scheduled (`ERR_INVALID_STATE`). The `start_at` must be at or after the logical now (otherwise `ERR_GAME_IN_PAST`, HTTP 422), `end_at` must be strictly after `start_at` and on the same local date, and the slot must satisfy §2.10's facility fit, closure, and double-booking rules. Neither team may already have a `SCHEDULED` game whose half-open interval overlaps the candidate at any facility (`ERR_TEAM_TIME_CONFLICT`). A created game is born `SCHEDULED` with `bracket_round` `REGULAR`; its `duration_minutes` is the difference between `end_at` and `start_at` in whole minutes, any sub-minute remainder discarded; `report_home`, `report_away`, `final_home_score`, `final_away_score`, `actual_duration_minutes`, `forfeiting_team_id`, and `next_game_id` are all null. Creating the game increments the league's `version`.

A coordinator may reschedule a game, supplying a new `start_at`, `end_at`, and optionally a new `facility_id`. The game being rescheduled is itself excluded from the double-booking and team-conflict scans, and a game that currently has no facility — a playoff shell — must be given a `facility_id` in the reschedule body (otherwise `ERR_VALIDATION`). Rescheduling from `SCHEDULED` first cancels all of the game's `ASSIGNED` or `ACCEPTED` officiating assignments with provisional pay reversed, then applies the new time; rescheduling from `RESCHEDULE_REQUIRED` — including the playoff shells of §3.5, which are born without times and are scheduled exactly this way — simply applies the new time. Either way, the league must be `SCHEDULING`, `IN_SEASON`, or `PLAYOFFS` (otherwise `ERR_INVALID_STATE`), and the new slot passes the same validations as creation: not in the past (`ERR_GAME_IN_PAST`), within one operating window (`ERR_FACILITY_OUTSIDE_HOURS`), outside closures (`ERR_FACILITY_CLOSED`), free of facility double-booking (`ERR_FACILITY_DOUBLE_BOOKED`), and free of team conflicts (`ERR_TEAM_TIME_CONFLICT`). A successful reschedule leaves the game `SCHEDULED` with `start_at`, `end_at`, and `facility_id` replaced and `duration_minutes` recomputed.

### 3.4. Game Day: Score Reports, Disputes, and Forfeits

Once the logical clock reaches a `SCHEDULED` game's `start_at`, either side's captain may file a score report carrying `side` (`HOME` or `AWAY`), `home_score`, `away_score`, and an `opponent_sportsmanship` rating; the scores must be non-negative integers and the rating an integer from 1 to 5 (violations are `ERR_VALIDATION`). Reporting before the game's start is rejected with `ERR_GAME_NOT_REPORTABLE` (HTTP 409), as is a report filed against a game in any status other than `SCHEDULED` or `PLAYED_PENDING_CONFIRM`; a caller who is not the captain of the reported side's team is `ERR_FORBIDDEN`. The first report moves the game `SCHEDULED → PLAYED_PENDING_CONFIRM` and stores it as `report_home` or `report_away` according to the reporting side. Each stored report records `home_score`, `away_score`, `opponent_sportsmanship`, and a `reported_at` timestamp — the side is implied by which field holds it — and the second report is stored too, so a game confirmed by agreement carries both reports.

The game then waits for the opposing captain. A second report from the *same* side is rejected with `ERR_DUPLICATE_SCORE_REPORT`. A second report from the opposing side whose `home_score` and `away_score` exactly match the stored report confirms the game: it moves `PLAYED_PENDING_CONFIRM → FINAL`, and the result effects below apply, with each team credited a received sportsmanship rating equal to the opponent report's `opponent_sportsmanship`. One caveat: on a playoff game (any `bracket_round` other than `REGULAR`), a matching report with equal scores is rejected with `ERR_TIE_NOT_ALLOWED` — playoff games cannot end tied. A second report from the opposing side whose scores do *not* exactly match moves the game `PLAYED_PENDING_CONFIRM → DISPUTED`; both reports are kept, and no standings or sportsmanship effects apply yet.

A `RecAdmin` resolves any `PLAYED_PENDING_CONFIRM` or `DISPUTED` game through finalization, supplying authoritative `home_score`, `away_score`, `home_sportsmanship`, `away_sportsmanship`, and `actual_duration_minutes`; the scores must be non-negative integers, the sportsmanship ratings integers from 1 to 5, and `actual_duration_minutes` a non-negative integer (violations are `ERR_VALIDATION`), and finalizing a game in any other status is `ERR_INVALID_STATE`. Finalization moves the game to `FINAL` using the coordinator-supplied scores; the home team is credited the finalize call's `home_sportsmanship` and the away team its `away_sportsmanship` as received ratings; and `actual_duration_minutes` is recorded, where it will drive final official pay per §3.6. On a playoff game, finalized equal scores are `ERR_TIE_NOT_ALLOWED`.

The **result effects** of a game reaching `FINAL` are: the higher-scored team's `wins` increments by 1 and its `points` by 3; the loser's `losses` increments by 1; on equal scores — possible only in the `REGULAR` round — both teams' `ties` increment by 1 and both gain 1 `points`. Each received sportsmanship rating (from either the matching-report path or the finalize path) adds its value to the receiving team's `sportsmanship_points_total` and increments `sportsmanship_rating_count`. A team's `sportsmanship_rating` is then its `sportsmanship_points_total` divided by `sportsmanship_rating_count`, rounded half-up to two decimal places; while a team has received no ratings, the rating is null and is treated as 0.00 for playoff eligibility. When a game finalizes, any of its officiating assignments in `ACCEPTED` move to `WORKED` (assignments still `ASSIGNED` are unchanged). Finally, the suspension sweep below runs on both teams.

A game-time forfeit may be declared by a `LeagueCoordinator` from `SCHEDULED` or `RESCHEDULE_REQUIRED` — including playoff shells — once the logical clock has reached `start_at` (earlier attempts are `ERR_GAME_NOT_REPORTABLE`; a `RESCHEDULE_REQUIRED` playoff shell has no `start_at` and so carries no time gate — it may be forfeited at any time), supplying a `forfeiting_team_id` that must be either the home or the away team (otherwise `ERR_FORFEITING_TEAM_INVALID`, HTTP 422). The game becomes `FORFEITED` with `forfeiting_team_id` recorded. The forfeiting team's `losses` increments by 1, its `forfeit_count` increments by 1, and it receives an automatic sportsmanship 1: `sportsmanship_points_total` up by 1 and `sportsmanship_rating_count` up by 1. The opponent's `wins` increments by 1 and its `points` by 3, with no sportsmanship entry. Officials handling differs sharply by trigger: on a *manual* declare-forfeit, `ACCEPTED` assignments move to `WORKED` — leaving them eligible for the flat forfeit fee at settlement — while `ASSIGNED` assignments are `CANCELLED` with provisional pay reversed; on a *system* cascade-forfeit (suspension or withdrawal, below), every non-terminal assignment is `CANCELLED` with provisional pay reversed and nobody becomes `WORKED`. Either way the suspension sweep runs on the forfeiting team, and playoff bracket advancement treats a `FORFEITED` game like a `FINAL` one, with the non-forfeiting team as winner.

The **suspension sweep** fires whenever a finalize or forfeit has incremented a team's `forfeit_count`: if the team is `ACTIVE` and its `forfeit_count` has reached 3, the team moves `ACTIVE → SUSPENDED` and every one of its remaining `SCHEDULED` or `RESCHEDULE_REQUIRED` games is cascade-forfeited — each becomes `FORFEITED` with `forfeiting_team_id` set to the suspended team, per-game forfeit effects apply (standings and the automatic sportsmanship 1), except that all non-terminal officiating assignments on those games are `CANCELLED` with pay reversed and nobody is marked `WORKED`. A coordinator may reinstate a `SUSPENDED` team while its league is `IN_SEASON` (either condition failing is `ERR_INVALID_STATE`); reinstatement does **not** reset `forfeit_count`, so a later finalize or forfeit that re-evaluates the threshold while the count is still at least 3 will re-suspend the team.

A team may be withdrawn by its captain or a coordinator. Withdrawing from `REGISTERED` or `PLACED` simply moves the team to `WITHDRAWN`. Withdrawing from `ACTIVE` or `SUSPENDED` additionally cascade-forfeits the team's remaining `SCHEDULED` and `RESCHEDULE_REQUIRED` games exactly as the suspension sweep does — standings and automatic sportsmanship effects per game, all non-terminal assignments `CANCELLED` with pay reversed, nobody `WORKED`. Teams reaching the end of a completed league move to `COMPLETED`; `WITHDRAWN` and `COMPLETED` are terminal.

### 3.5. Playoffs

When the regular season's games are all resolved, the coordinator launches playoffs, moving the league `IN_SEASON → PLAYOFFS`. This is refused while any game of the league is still `SCHEDULED`, `RESCHEDULE_REQUIRED`, `PLAYED_PENDING_CONFIRM`, or `DISPUTED` (`ERR_PLAYOFFS_NOT_READY`). Eligibility is computed over the league's `ACTIVE` teams: a team is eligible when its status is `ACTIVE`, its `sportsmanship_rating` — with null treated as 0.00 — is at least 3.00 (a rating of exactly 3.00 is eligible), and its `forfeit_count` is at most 1 (exactly 1 forfeit is eligible). If fewer than 2 teams league-wide are eligible, the launch fails with `ERR_NO_ELIGIBLE_TEAMS`.

Seeding ranks the eligible teams of each division by, in order: `points` descending; head-to-head points descending among tied teams (only points earned in games between the tied teams count); `sportsmanship_rating` descending with null treated as 0.00; `forfeit_count` ascending; and finally team `created_at` ascending. A division with 4 or more eligible teams produces two `SEMIFINAL` games — seed 1 at home against seed 4 away, and seed 2 at home against seed 3 away. A division with 2 or 3 eligible teams produces a single `CHAMPIONSHIP` game, seed 1 at home against seed 2 away. A division with fewer than 2 eligible teams produces no bracket. If no division produces a bracket — possible when at least two teams are eligible league-wide but no single division holds two — the league still moves to `PLAYOFFS` and remains there, since the completion rule below only fires off a championship resolution. System-created playoff games bypass the usual initial state and are born `RESCHEDULE_REQUIRED` with `facility_id`, `start_at`, and `end_at` null and `division_name` null; a coordinator schedules them through the reschedule action of §3.3.

When a `SEMIFINAL` game reaches `FINAL` or `FORFEITED` and its sibling semifinal of the same league and division is also `FINAL` or `FORFEITED`, the system auto-creates the division's `CHAMPIONSHIP` game — home is the higher-seeded winner, away is the other winner, status `RESCHEDULE_REQUIRED` — and sets `next_game_id` on both semifinals to point at it. When a `CHAMPIONSHIP` game resolves such that every division bracket produced at playoff launch now has its championship in `FINAL` or `FORFEITED`, the league automatically moves `PLAYOFFS → COMPLETED`, and every team still `ACTIVE` or `SUSPENDED` moves to `COMPLETED`.

A coordinator may also cancel the league outright from `DRAFT`, `REGISTRATION_OPEN`, `SCHEDULING`, or `IN_SEASON`. Cancellation cascades: every game in `SCHEDULED`, `RESCHEDULE_REQUIRED`, `PLAYED_PENDING_CONFIRM`, or `DISPUTED` becomes `CANCELLED`; every `ASSIGNED` or `ACCEPTED` officiating assignment on those games becomes `CANCELLED` with its provisional pay subtracted back out of the official's `payroll_pending_cents`; every team in `REGISTERED`, `PLACED`, `ACTIVE`, or `SUSPENDED` becomes `WITHDRAWN`; and every `POOLED` free-agent pool entry becomes `WITHDRAWN`.

### 3.6. Officials and Payroll

A `RecAdmin` creates `Staff` with `full_name`, a `staff_role` of `OFFICIAL` or `INSTRUCTOR` (immutable after creation), and a `base_hourly_rate_cents` greater than zero that feeds both official pay formulas and instructor payroll. The conditional fields differ by role: `certification_level` is required exactly when the role is `OFFICIAL` — an integer from 1 to 3 — and forbidden when the role is `INSTRUCTOR`; `certified_class_types` is required non-empty exactly when the role is `INSTRUCTOR` — a subset of the class-type enum — and forbidden when the role is `OFFICIAL`. Raw conditional-field violations are `ERR_VALIDATION`; the contextual errors `ERR_STAFF_NOT_OFFICIAL` and `ERR_STAFF_NOT_INSTRUCTOR` apply only in assignment and class contexts. New staff start with `payroll_pending_cents` and `payroll_paid_cents` at zero.

A `LeagueCoordinator` assigns an official to a `SCHEDULED` game (a game in any other status is `ERR_INVALID_STATE`) by supplying `staff_id`. The target must be an `OFFICIAL` (otherwise `ERR_STAFF_NOT_OFFICIAL`, HTTP 422). For a `SEMIFINAL` or `CHAMPIONSHIP` game the official's `certification_level` must be at least 2 (otherwise `ERR_OFFICIAL_CERT_TOO_LOW`); regular-season games require only level 1 or better. A game may carry at most 2 non-terminal assignments — `ASSIGNED`, `ACCEPTED`, or `WORKED` (otherwise `ERR_ASSIGNMENT_LIMIT_REACHED`). The candidate is also checked against the official's travel buffer: considering each of the official's other assignments in `ASSIGNED`, `ACCEPTED`, or `WORKED` whose game is `SCHEDULED`, `PLAYED_PENDING_CONFIRM`, `DISPUTED`, `FINAL`, or `FORFEITED`, the candidate conflicts unless the gap between the candidate and that game's interval is at least 30 minutes in one direction or the other; a gap of exactly 30 minutes is allowed, while 29 is rejected with `ERR_OFFICIAL_DOUBLE_BOOKED` (HTTP 409). Playoff shells without scheduled times do not participate in this check.

A created assignment starts `ASSIGNED`. Its `provisional_pay_cents` is estimated at creation: the game's `duration_minutes` multiplied by the official's `base_hourly_rate_cents` and by a certification multiplier — 1.0 at level 1, 1.25 at level 2, 1.5 at level 3 — divided by 60, rounded half-up to whole cents. The provisional amount is added to the official's `payroll_pending_cents`, which aggregates the provisional pay of all the official's assignments in `ASSIGNED`, `ACCEPTED`, or `WORKED` status.

The assigned official responds to an assignment, addressed by its `officiating_assignment_id`, with `response` `ACCEPT` or `DECLINE`; only the assignee may respond (`ERR_FORBIDDEN` otherwise) and only while the assignment is `ASSIGNED` (`ERR_INVALID_STATE` otherwise). Accepting moves the assignment `ASSIGNED → ACCEPTED`. Declining moves it to `DECLINED` and subtracts its provisional pay back out of `payroll_pending_cents`. Assignments are also cancelled by the system — on game reschedule, facility-closure bumps, league/withdrawal/suspension cascades, or an `ASSIGNED`-at-forfeit — each time with the provisional pay reversed.

Once an assignment reaches `WORKED` — via game finalization or a manual forfeit — the coordinator settles it. Settlement requires `WORKED` status (otherwise `ERR_INVALID_STATE`) and computes `final_pay_cents`: if the game is `FINAL`, the billable minutes are the game's `actual_duration_minutes` when recorded, otherwise its `duration_minutes`, multiplied by the base rate and certification multiplier, divided by 60, and rounded half-up; if the game is `FORFEITED`, the official is paid a flat one hour at the base rate with *no* certification multiplier and duration ignored — so the same assignment can settle for less than its provisional. Settlement moves the assignment `WORKED → PAID`, subtracts `provisional_pay_cents` from `payroll_pending_cents`, and adds `final_pay_cents` to `payroll_paid_cents`. `PAID`, `DECLINED`, and `CANCELLED` are terminal.

A staff member's `payroll_paid_cents` aggregates across two rails: the official rail just described (final pay of `PAID` assignments) plus the instructor rail (the `instructor_pay_cents` of `COMPLETED` fitness classes, §3.8), which pays directly to paid and never passes through pending.

### 3.7. Injury Reports and Participation Holds

A member or a `FacilityManager` files an `InjuryReport` with `member_id`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, and a free-text `description`; a `Member` caller may file only for themselves — the body's `member_id` must equal `X-User-ID` (otherwise `ERR_FORBIDDEN`). An optional `game_id` gives game context, in which case the member must hold an `ACTIVE` roster entry on the home or away team of that game (otherwise `ERR_INJURY_GAME_MISMATCH`). The report is born `REPORTED`.

Severity `MODERATE` or `SEVERE` is a **hold report**: filing one moves the member `ACTIVE → SUSPENDED`, and the cascade continues — every class registration of the member in `REGISTERED` status whose class is `SCHEDULED` and starts after the logical now is cancelled, and each such cancellation runs the waitlist promotion of §3.8 on its class. Cancelled registrations are *not* restored on later clearance. A `MINOR` report imposes no hold.

A `RecAdmin` clears a `REPORTED` report, addressed by its `injury_report_id`, supplying a `clearance_note` that is recorded on the report as it moves to `CLEARED`; clearing a non-`REPORTED` report is `ERR_INVALID_STATE`. If, after clearing, no other report of the member remains `REPORTED` with hold severity, the member moves `SUSPENDED → ACTIVE`.

### 3.8. Fitness Classes and Instructor Payroll

A `RecAdmin` creates a `FitnessClass` with `title`; a `class_type` of `YOGA`, `SPIN`, `PILATES`, `HIIT`, or `ZUMBA`; `instructor_staff_id`; `facility_id`; `start_at` and `end_at`; and a `capacity` of at least 1. The instructor must be an `INSTRUCTOR` (otherwise `ERR_STAFF_NOT_INSTRUCTOR`) whose `certified_class_types` include the class's `class_type` (otherwise `ERR_INSTRUCTOR_NOT_CERTIFIED`). The temporal rules mirror game scheduling: `start_at` at or after the logical now (`ERR_GAME_IN_PAST`), `end_at` after `start_at` on the same local date, and the facility fit, closure, and double-booking rules of §2.10. `duration_minutes` is derived as the difference in whole minutes, any sub-minute remainder discarded as for games. A new class is `SCHEDULED` with `registered_count` and `waitlist_count` at zero, and its `instructor_pay_estimate_cents` is computed immediately as the duration in minutes times the instructor's `base_hourly_rate_cents`, divided by 60, rounded half-up — with no attendance bonus. `instructor_pay_cents` and `attendance_count` stay null until completion.

A member self-registers for a class with their `member_id` — registrations are accepted only while the class is `SCHEDULED` (otherwise `ERR_INVALID_STATE`) — subject to the eligibility gates of §2.9, the uniqueness rule that the member must not already hold a `REGISTERED` or `WAITLISTED` registration for the same class (`ERR_CLASS_ALREADY_REGISTERED`), and a time-conflict rule: the member must not hold a `REGISTERED` registration in another `SCHEDULED` class whose half-open interval overlaps the candidate (`ERR_CLASS_TIME_CONFLICT`). The new registration's initial status is capacity-dependent: `REGISTERED` when the class's `registered_count` is below `capacity` at creation — incrementing `registered_count` — and `WAITLISTED` otherwise, incrementing `waitlist_count`. A full class is not an error.

A registration in `REGISTERED` or `WAITLISTED`, addressed by its `class_registration_id`, may be cancelled by the member or a `RecAdmin` (a registration in any other status is `ERR_INVALID_STATE`). Cancelling a `WAITLISTED` entry simply decrements `waitlist_count`. Cancelling a `REGISTERED` entry decrements `registered_count` and then runs **waitlist promotion**: among the class's `WAITLISTED` registrations, the head is the one with the earliest registration `created_at`, ties broken by the candidate member's earlier `created_at`; the head is promoted to `REGISTERED`, decrementing `waitlist_count` by 1 while `registered_count` returns to its prior value — the seat is handed off, and the two counts are conserved. An empty waitlist makes promotion a no-op. Promotion never runs for a class that is `CANCELLED` or `COMPLETED`.

After the logical clock reaches a `SCHEDULED` class's `end_at`, the class's instructor or a `RecAdmin` completes it (before `end_at`, or on a non-`SCHEDULED` class, is `ERR_INVALID_STATE`; a `Staff` caller who is not the class's `instructor_staff_id` is `ERR_FORBIDDEN`), optionally listing `no_show_registration_ids`. When present, `no_show_registration_ids` must be an array (otherwise `ERR_VALIDATION`); ids that do not name a `REGISTERED` registration of the class are ignored. Completion moves every `REGISTERED` registration to `ATTENDED`, except those listed, which become `NO_SHOW` and increment their member's `no_show_count`; every `WAITLISTED` registration becomes `CANCELLED`. The class's `attendance_count` is set to the number of `ATTENDED` registrations, and the class moves `SCHEDULED → COMPLETED`.

Final instructor pay is computed at completion: the fill ratio is `attendance_count` divided by `capacity`; the bonus is 20 percent when the fill is at least 0.80, else 10 percent when the fill is at least 0.50, else zero — bounds inclusive, so a capacity-10 class with 8 attendees fills at exactly 0.80 and earns the 20 percent bonus. `instructor_pay_cents` is the duration times the base hourly rate, times one plus the bonus, divided by 60, rounded half-up to whole cents per session. The amount is added directly to the instructor's `payroll_paid_cents` — the instructor rail never passes through pending — and term payroll totals sum the already-rounded per-session values.

Classes are never manually cancelled. A facility closure whose half-open interval overlaps a `SCHEDULED` class's interval cancels the class: every `REGISTERED` and `WAITLISTED` registration becomes `CANCELLED`, no waitlist promotion runs (the class is dead), no instructor pay accrues, and the class's `registered_count` and `waitlist_count` are reset to zero.

### 3.9. Equipment, Lockers, Fines, and Facility Closures

A `RecAdmin` creates an `EquipmentPool` with an `item_type` — `BASKETBALL`, `VOLLEYBALL`, `SOCCER_BALL`, `TENNIS_RACKET`, `BADMINTON_SET`, or `YOGA_MAT`, unique across pools (a duplicate `item_type` is `ERR_VALIDATION`) — a `total_qty` of at least 1, a `daily_late_fee_cents` of at least 0, and a `unit_replacement_cents` of at least 1. `available_qty` starts equal to `total_qty`, and the pool maintains the invariant that `available_qty` plus the quantities of all checkouts still `OUT` equals `total_qty`.

A member checks out equipment by supplying `equipment_pool_id`, `member_id`, a `quantity` of at least 1, and a `due_at` strictly after the logical now (a deadline at or before now is `ERR_VALIDATION`). The eligibility gates of §2.9 apply, the requested `quantity` must not exceed the pool's `available_qty` (otherwise `ERR_EQUIPMENT_INSUFFICIENT`), and — as the last check of all — the member's `outstanding_fines_cents` must be zero (otherwise `ERR_OUTSTANDING_FINES`). A created checkout is `OUT` and decrements `available_qty` by `quantity`.

A `FacilityManager` processes a return on an `OUT` checkout addressed by its `equipment_checkout_id` (any other status is `ERR_INVALID_STATE`). The return stamps `returned_at` with the logical now, restores `quantity` to the pool's `available_qty`, computes `late_fee_cents`, and adds that fee to the member's `outstanding_fines_cents`. The late fee's rounding order is pinned: the seconds late are the logical now minus `due_at`, floored at zero — a return exactly at `due_at` is on time; the days late are the seconds late divided by 86400 rounded *up*, so even one second late counts as a full day; the raw fee is the days late times the pool's `daily_late_fee_cents` times the checkout `quantity`; and `late_fee_cents` is the raw fee capped at `quantity` times the pool's `unit_replacement_cents` — the ceiling is replacement value. An on-time return yields a fee of 0.

A `FacilityManager` may instead declare an `OUT` checkout lost. The member's `outstanding_fines_cents` increases by `quantity` times the pool's `unit_replacement_cents`, and the pool's `total_qty` is permanently decremented by `quantity` — `available_qty` is unchanged, because the units have left the pool for good. The checkout becomes `LOST`; `RETURNED` and `LOST` are terminal.

Lockers are created by a `RecAdmin` with a unique `locker_number` of at least 1 (a duplicate is `ERR_VALIDATION`) and a `size` of `S`, `M`, or `L`, and are born `AVAILABLE`. A member rents an `AVAILABLE` locker, addressed by its `locker_id`, for a `term`, subject to the eligibility gates of §2.9 — explicitly without the outstanding-fines check — and the rule that the member may hold at most one `RENTED` locker at a time (otherwise `ERR_RENTAL_EXISTS`); renting a non-`AVAILABLE` locker is `ERR_LOCKER_UNAVAILABLE`. Rental records `rented_by_member_id` and `rental_term` on the locker, moves it `AVAILABLE → RENTED`, and computes `rental_fee_cents` as a flat per-term fee by affiliation — 1500 cents for `STUDENT`, 1500 cents for `FACULTY`, 3000 cents for `COMMUNITY` — with no proration. The current renter or a `FacilityManager` releases a `RENTED` locker (releasing a non-`RENTED` locker is `ERR_INVALID_STATE`), returning it to `AVAILABLE` and clearing `rented_by_member_id`, `rental_term`, and `rental_fee_cents` to null.

Finally, the facility-closure cascade ties several of these workflows together. When a closure is created, every `SCHEDULED` game whose half-open interval overlaps the closure moves to `RESCHEDULE_REQUIRED`, and its `ASSIGNED` or `ACCEPTED` officiating assignments are `CANCELLED` with each provisional amount subtracted from the official's `payroll_pending_cents`. Every `SCHEDULED` fitness class overlapping the closure is cancelled as described in §3.8. The closure is appended to the facility's `closures` and the facility's `version` increments.

## 4. Endpoint Definitions

All endpoints are mounted under the `/v1` prefix. Creating a new resource returns HTTP 201; operations that modify an existing resource, and all reads, return HTTP 200. Request and response payloads follow the narratives of §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/members | Create a member | RecAdmin |
| GET | /v1/members/{member_id} | Get a member | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/members/{member_id}/waiver-sign | Sign (or re-sign) the liability waiver | Member |
| POST | /v1/members/{member_id}/memberships | Purchase a membership (create-with-supersede; OCC-guarded) | Member |
| GET | /v1/memberships/{membership_id} | Get a membership | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/memberships | List memberships (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/memberships/{membership_id}/cancel | Cancel an ACTIVE membership (no refund) | Member, RecAdmin |
| POST | /v1/members/{member_id}/fine-payments | Pay down outstanding fines | Member |
| POST | /v1/injury-reports | Report an injury; MODERATE/SEVERE imposes a participation hold | Member, FacilityManager |
| GET | /v1/injury-reports/{injury_report_id} | Get an injury report | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/injury-reports | List injury reports (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/injury-reports/{injury_report_id}/clear | Clear a report; conditional member reinstatement | RecAdmin |
| POST | /v1/leagues | Create a league (DRAFT) with divisions | RecAdmin |
| GET | /v1/leagues/{league_id} | Get a league (includes free_agent_pool and divisions) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/leagues/{league_id}/open-registration | DRAFT → REGISTRATION_OPEN | LeagueCoordinator |
| POST | /v1/leagues/{league_id}/close-registration | REGISTRATION_OPEN → SCHEDULING; requires >= min_teams | LeagueCoordinator |
| POST | /v1/leagues/{league_id}/start-season | SCHEDULING → IN_SEASON; locks rosters | LeagueCoordinator |
| POST | /v1/leagues/{league_id}/start-playoffs | IN_SEASON → PLAYOFFS; creates bracket games | LeagueCoordinator |
| POST | /v1/leagues/{league_id}/cancel | Cancel league; cascades to games, assignments, teams, pool | LeagueCoordinator |
| POST | /v1/leagues/{league_id}/free-agents | Member self-registers into the free-agent pool | Member |
| POST | /v1/leagues/{league_id}/place-free-agent | Place a POOLED free agent onto a team | LeagueCoordinator |
| POST | /v1/teams | Register a team into a league | LeagueCoordinator |
| GET | /v1/teams/{team_id} | Get a team | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/teams | List teams (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/teams/{team_id}/place-division | Place a REGISTERED team into a division | LeagueCoordinator |
| POST | /v1/teams/{team_id}/reinstate | SUSPENDED → ACTIVE (does not reset forfeit_count) | LeagueCoordinator |
| POST | /v1/teams/{team_id}/withdraw | Withdraw a team; cascade-forfeits when ACTIVE/SUSPENDED | Member, LeagueCoordinator |
| POST | /v1/teams/{team_id}/roster-entries | Captain adds a player | Member |
| GET | /v1/roster-entries/{roster_entry_id} | Get a roster entry | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/roster-entries | List roster entries (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/roster-entries/{roster_entry_id}/remove | Remove an ACTIVE roster entry; captain's entry unremovable | Member, LeagueCoordinator |
| POST | /v1/facilities | Create a facility with weekly operating windows | RecAdmin |
| GET | /v1/facilities/{facility_id} | Get a facility (includes closures) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/facilities/{facility_id}/closures | Create a closure (OCC-guarded; deep cascade) | FacilityManager |
| POST | /v1/leagues/{league_id}/games | Schedule a regular-season game (OCC-guarded) | LeagueCoordinator |
| GET | /v1/games/{game_id} | Get a game (includes reports and final scores) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/games | List games (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/games/{game_id}/reschedule | Move a game to a new slot; schedules playoff shells | LeagueCoordinator |
| POST | /v1/games/{game_id}/score-reports | Captain reports score + opponent sportsmanship | Member |
| POST | /v1/games/{game_id}/finalize | RecAdmin authoritative result | RecAdmin |
| POST | /v1/games/{game_id}/declare-forfeit | Game-time forfeit | LeagueCoordinator |
| POST | /v1/staff | Create a staff member (OFFICIAL or INSTRUCTOR) | RecAdmin |
| GET | /v1/staff/{staff_id} | Get a staff member (payroll aggregates) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/games/{game_id}/officiating-assignments | Assign an official to a SCHEDULED game | LeagueCoordinator |
| GET | /v1/officiating-assignments/{officiating_assignment_id} | Get an officiating assignment | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/officiating-assignments | List officiating assignments (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/officiating-assignments/{officiating_assignment_id}/respond | Assigned official accepts or declines | Staff |
| POST | /v1/officiating-assignments/{officiating_assignment_id}/settle | Settle a WORKED assignment | LeagueCoordinator |
| POST | /v1/equipment-pools | Create an equipment pool (item_type unique) | RecAdmin |
| GET | /v1/equipment-pools/{equipment_pool_id} | Get an equipment pool | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/equipment-pools | List equipment pools (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/equipment-checkouts | Member checks out equipment | Member |
| GET | /v1/equipment-checkouts/{equipment_checkout_id} | Get a checkout | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/equipment-checkouts | List checkouts (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/equipment-checkouts/{equipment_checkout_id}/return | Return a checkout; computes late fee | FacilityManager |
| POST | /v1/equipment-checkouts/{equipment_checkout_id}/report-lost | Declare a checkout lost; charges replacement | FacilityManager |
| POST | /v1/lockers | Create a locker | RecAdmin |
| GET | /v1/lockers/{locker_id} | Get a locker | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/lockers | List lockers (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/lockers/{locker_id}/rent | Rent an AVAILABLE locker for a term | Member |
| POST | /v1/lockers/{locker_id}/release | Release a RENTED locker | Member, FacilityManager |
| POST | /v1/fitness-classes | Create a one-off dated class | RecAdmin |
| GET | /v1/fitness-classes/{fitness_class_id} | Get a class | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/fitness-classes | List classes (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/fitness-classes/{fitness_class_id}/registrations | Member registers; WAITLISTED when full | Member |
| GET | /v1/class-registrations/{class_registration_id} | Get a registration | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| GET | /v1/class-registrations | List registrations (filtered) | RecAdmin, LeagueCoordinator, FacilityManager, Member, Staff |
| POST | /v1/class-registrations/{class_registration_id}/cancel | Cancel a registration; promotes waitlist head | Member, RecAdmin |
| POST | /v1/fitness-classes/{fitness_class_id}/complete | Complete the class; marks attendance; pays instructor | Staff, RecAdmin |
| POST | /v1/_clock/set_current_utc | Set the logical clock (ISO8601 UTC) | RecAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_MEMBERSHIP_INACTIVE | 409 |
| ERR_WAIVER_INVALID | 422 |
| ERR_OUTSTANDING_FINES | 402 |
| ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS | 409 |
| ERR_TOO_FEW_TEAMS | 409 |
| ERR_LEAGUE_NOT_READY_FOR_SEASON | 409 |
| ERR_LEAGUE_FULL | 409 |
| ERR_DIVISION_NOT_FOUND | 404 |
| ERR_DIVISION_FULL | 409 |
| ERR_DIVISION_SKILL_MISMATCH | 422 |
| ERR_TEAM_ALREADY_IN_LEAGUE | 409 |
| ERR_MEMBER_ALREADY_IN_LEAGUE | 409 |
| ERR_ROSTER_FULL | 422 |
| ERR_CAPTAIN_REMOVAL_FORBIDDEN | 422 |
| ERR_ALREADY_IN_POOL | 409 |
| ERR_NO_TEAM_AVAILABLE | 409 |
| ERR_GAME_IN_PAST | 422 |
| ERR_FACILITY_OUTSIDE_HOURS | 422 |
| ERR_FACILITY_CLOSED | 409 |
| ERR_FACILITY_DOUBLE_BOOKED | 409 |
| ERR_TEAM_TIME_CONFLICT | 409 |
| ERR_TEAMS_NOT_IN_SAME_DIVISION | 422 |
| ERR_GAME_NOT_REPORTABLE | 409 |
| ERR_DUPLICATE_SCORE_REPORT | 409 |
| ERR_TIE_NOT_ALLOWED | 422 |
| ERR_FORFEITING_TEAM_INVALID | 422 |
| ERR_PLAYOFFS_NOT_READY | 409 |
| ERR_NO_ELIGIBLE_TEAMS | 409 |
| ERR_STAFF_NOT_OFFICIAL | 422 |
| ERR_STAFF_NOT_INSTRUCTOR | 422 |
| ERR_OFFICIAL_CERT_TOO_LOW | 422 |
| ERR_OFFICIAL_DOUBLE_BOOKED | 409 |
| ERR_ASSIGNMENT_LIMIT_REACHED | 422 |
| ERR_INSTRUCTOR_NOT_CERTIFIED | 422 |
| ERR_EQUIPMENT_INSUFFICIENT | 409 |
| ERR_LOCKER_UNAVAILABLE | 409 |
| ERR_RENTAL_EXISTS | 409 |
| ERR_CLASS_ALREADY_REGISTERED | 409 |
| ERR_CLASS_TIME_CONFLICT | 409 |
| ERR_INJURY_GAME_MISMATCH | 422 |
