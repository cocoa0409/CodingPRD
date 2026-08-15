# Gymnastics Meet Judging Administration API — Product Requirements Document

## 1. Introduction

A USA Gymnastics sanctioned meet compresses an unforgiving amount of coordination into a single weekend: sessions must be scheduled by level band, squads must rotate across four apparatus on a clock that cannot slip, panels of rated judges must be staffed without conflicts of interest, scores must be published inside strict inquiry windows, ties must be broken by rule rather than by argument, and only properly credentialed coaches may stand on the competition floor. This document specifies the Gymnastics Meet Judging Administration API, the system of record for running such a meet end to end — from the first draft of the schedule through the final award ceremony and the qualification of athletes to state, regional, and national meets.

The design centers on a single Meet aggregate whose posture gates every child activity, a logical clock that drives all time-based transitions so that meet flow is deterministic and replayable, optimistic concurrency control on the handful of writes where a stale observation would corrupt results, and score arithmetic pinned to three-decimal, round-half-up precision. Duties are segregated by role: the meet director runs the schedule and the gate, the meet referee runs the judging corps and the inquiry desk, panel chiefs enter and publish scores, coaches manage their athletes, and spectators watch it all through a live read model.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request with missing or malformed headers, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the acting role must be permitted to invoke the target endpoint; otherwise the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- `MeetDirector` — the meet organizer; owns meet, session, squad, rotation, and warm-up setup, scoring closure, finalization, award generation, ticket refunds, coach pass issuance and discipline, qualification confirmation and revocation, and the administrative clock.
- `MeetReferee` — the head judge; registers judges, builds judge panels, confirms, recuses, and releases panel assignments, resolves inquiries, and finalizes or voids scores.
- `JudgePanelChief` — the chief judge of one apparatus panel; enters, amends, and publishes scores for that apparatus.
- `Coach` — a club coach; enters gymnasts into sessions (a capability shared with the meet director), checks athletes in, scratches entries, files and withdraws inquiries, and declines qualification records.
- `GateAttendant` — gate staff; sells tickets (shared with the meet director), and scans and redeems spectator tickets.
- `Spectator` — the public; read-only access to meet data, sessions, live scores, scores, and awards.

Identity semantics differ by role. When `X-User-Role` is `JudgePanelChief`, `X-User-ID` is the `id` of the acting Judge; ownership checks on any resource that references a Judge compare the resource's foreign-key field to `X-User-ID` — most importantly, publishing a score requires the acting judge to hold a confirmed panel-chief assignment on the panel covering that apparatus and session. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting Coach; checks that bind an action to a specific coach — such as withdrawing an inquiry, which is restricted to the coach recorded as `filed_by_coach_id` — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `MeetDirector`, `MeetReferee`, `GateAttendant`, or `Spectator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Duties are deliberately segregated: a `JudgePanelChief` publishes scores but can never resolve inquiries on them; inquiry resolution belongs to the `MeetReferee` alone.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Most list endpoints additionally accept optional equality filters drawn from the listed resource's own fields. The meet list filters by `posture` and `sanction_year`; a meet's session list by `level_band` and `state`; the gymnast list by `competitive_level` and `home_gym`; a session's athlete-entry list by `entry_status` and `squad_id`; the coach list by `credential_state` and `affiliated_gym`; a meet's coach-pass list by `pass_state`; the judge list by `rating` and `affiliated_gym`; a session's judge-panel list by `apparatus` and `panel_state`; a panel's assignment list by `assignment_state`; a session's rotation list and a rotation's warm-up block list by `state`; an entry's score list by `apparatus` and `score_state`; a score's inquiry list by `inquiry_state`; a session's award list by `category` and `place`; a meet's ticket list by `ticket_state` and `ticket_class`; and an entry's qualification-record list by `qualification_state`.

### 2.4. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock, and every timestamp comparison in this document — window openings, expiry instants, credential cutoffs — is evaluated against it, never against wall-clock time. At startup the logical clock reads 2026-05-01T00:00:00Z. Time advances only when a `MeetDirector` invokes the administrative clock-setting capability with a target instant supplied as `to_iso8601`; the endpoint must be called to advance time, and the server never falls back to wall-clock, so meet flow is fully deterministic.

Advancing the logical clock is what fires the meet's time-driven transitions: sessions open warm-up and march-in at their configured offsets, rotations open warm-up sixty minutes before their scheduled start, warm-up blocks go live as their start times arrive, published scores finalize when their inquiry window lapses unchallenged, long-unreviewed inquiries expire, and the meet's own posture advances as its earliest session starts. These transitions are performed by the system itself as the clock crosses each threshold, not by any user action.

### 2.5. Meet Posture: The Master Gate

A Meet carries a derived `posture` — `DRAFT`, `SCHEDULED`, `WARMUP_OPEN`, `IN_COMPETITION`, `SCORING_CLOSED`, `FINALIZED`, or `ARCHIVED` — aggregated from the states of its sessions and the completeness of its scoring. The posture is a gate: a mutation of any child resource under a meet is permitted only while the parent posture allows it, and a child-mutating request made under a forbidding posture is rejected with `ERR_MEET_POSTURE_FORBIDS` (HTTP 409). Two illustrative corollaries: no score may be created or amended once the meet is `FINALIZED`, and no new session may be created once the meet has reached `IN_COMPETITION`.

Consistency flows in both directions across the hierarchy. When a meet-level transition fires it cascades downward — publishing a meet settles every session into `SCHEDULED`, and the opening of competition pushes every full judge panel to `ACTIVE`. When child activity completes it bubbles upward — closing a session re-evaluates the parent meet's posture, and a score reaching `FINAL` re-evaluates its parent rotation's path from `SCORING_CLOSED` to `FINALIZED`. Every such mutation, whether user-invoked or cascading, refreshes the affected resource's `updated_at` and increments its `version` by one.

### 2.6. Common Resource Properties

Every resource in the system — meets, sessions, squads, gymnasts, athlete entries, coaches, coach meet passes, judges, judge panels, panel assignments, rotations, warm-up blocks, scores, inquiries, awards, spectator tickets, and qualification records — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including cascading side effects.

A request body that is missing a required field or is malformed at the schema level is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any business rule is evaluated. A mutation attempted against an entity that has already reached a terminal state of its lifecycle is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 2.7. Score Arithmetic: Precision, Ranges, and Rounding

All score quantities are decimal numbers carried at exactly three decimal places, using round-half-up whenever a rounding step is defined. The judged inputs to a routine are bounded: `difficulty_score` and `execution_score` each lie between 0.000 and 10.000 inclusive, and `neutral_deduction` lies between 0.000 and 5.000 inclusive. A value outside its declared range, or expressed at finer than three-decimal precision, is rejected with `ERR_SCORE_FIELD_RANGE` (HTTP 422). A computed routine total can never be negative: any total that would fall below zero is floored at 0.000, because a routine cannot score less than nothing. Qualification thresholds are compared with an inclusive lower bound — a score exactly equal to a threshold meets it. Ranks, places, and ceremony sequence numbers are integers.

### 2.8. Optimistic Concurrency Control

Three writes in the system are guarded by optimistic concurrency control, because each acts on an entity another writer may legitimately have advanced since the caller last observed it:

- Publishing a score requires the request body to carry `expected_score_version`, the score's `version` as last observed by the panel chief. If another writer has since amended the score's inputs — a legitimate pre-publish amendment — the versions will not match, and the publish is rejected with `ERR_STALE_SCORE_VERSION` (HTTP 412).
- Resolving an inquiry requires `expected_inquiry_version`, the inquiry's `version` as last observed by the referee. If the inquiry has since been returned to the queue or had its resolution fields edited, the resolve is rejected with `ERR_STALE_INQUIRY_VERSION` (HTTP 412).
- Closing a session requires `expected_session_version`, the session's `version` as last observed by the meet director. A late score finalization or rotation close advances the session's version, so a close request carrying the older version is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412).

In each case the expected-version field is non-optional on that endpoint, and a mismatch means the caller's view of the entity is stale and must be refreshed before retrying. Endpoints not listed here do not accept a version field.

### 2.9. Validation Order and Error Priority

When several checks could reject the same request, they are evaluated in a fixed order and the earliest failure is the one reported. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then the existence of every path-templated resource identifier validated left to right (`ERR_RESOURCE_NOT_FOUND`, HTTP 404), then resolution of foreign keys referenced in the request body (`ERR_FK_NOT_FOUND`, HTTP 404). Only then do state gates apply: first the parent meet's posture (`ERR_MEET_POSTURE_FORBIDS`), then the entity-specific state precondition of the requested transition (`ERR_INVALID_STATE`, HTTP 409).

Business rules follow in category order — safety before temporal, temporal before constraint, constraint before referential, referential before fiscal. Concretely: coach credential validity (`ERR_COACH_CREDENTIAL_LAPSED`) and judge conflict-of-interest (`ERR_JUDGE_CONFLICT_OF_INTEREST`) are evaluated before the temporal checks (the inquiry window `ERR_INQUIRY_WINDOW_EXPIRED`, warm-up block overlap `ERR_WARMUP_BLOCK_OVERLAP`, rotation overlap `ERR_ROTATION_OVERLAP`, judge availability `ERR_JUDGE_UNAVAILABLE`, and the ticket scan window `ERR_TICKET_OUTSIDE_SCAN_WINDOW`), which precede the constraint checks (squad capacity `ERR_SQUAD_CAPACITY_EXCEEDED`, panel staffing `ERR_PANEL_UNDERSTAFFED`, the session window `ERR_SESSION_OUTSIDE_MEET_WINDOW`, score field ranges `ERR_SCORE_FIELD_RANGE`, inquiry resolution consistency `ERR_INQUIRY_RESOLUTION_INCONSISTENT`, ticket duplicate email `ERR_TICKET_DUPLICATE_EMAIL`, ticket price `ERR_TICKET_PRICE_MISMATCH`, and seat section `ERR_TICKET_SEAT_SECTION_INVALID`), which precede the referential checks (level-band compatibility `ERR_LEVEL_BAND_MISMATCH` and the double-entry rule `ERR_GYMNAST_DOUBLE_ENTERED`), which precede the fiscal checks (inquiry delta ranges `ERR_INQUIRY_DELTA_RANGE` and the refund window `ERR_REFUND_WINDOW_CLOSED`).

A few concrete consequences of this ordering: filing an inquiry checks the coach's credentials before the inquiry window; confirming a panel assignment reports a conflict of interest before it reports unavailability; issuing a ticket checks for a duplicate holder email, then price consistency, then seat-section validity; resolving an inquiry checks resolution consistency before delta ranges; and entering a gymnast into a session checks level-band compatibility before the double-entry rule.

### 2.10. Nested Resource Retrieval

The API enforces strict hierarchical validation for every request that targets a nested resource. When an endpoint path contains multiple resource identifiers — for example, a spectator ticket created beneath both a meet and a session — the system validates the identifiers sequentially from left to right and rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource; no later segment is evaluated. A request aimed at a session beneath a non-existent meet therefore fails on the meet identifier before the session is ever considered. The same left-to-right rule governs creation and modification of nested resources, so child validations never run inside a non-existent parent context.

## 3. Business Logic & Workflows

### 3.1. Meets, Sessions, and the Competitive Timetable

A `MeetDirector` opens a new meet by supplying its identity and policy: a `meet_name` that must be unique within the same `sanction_year`; the `sanction_year` itself (the USAG competitive season, for example 2026); a globally unique `sanction_number` that must consist of the literal prefix USAG-, followed by four digits, a hyphen, and four more digits; the `venue_name`; and the meet's `start_date` and `end_date` — the day-one open-of-doors and final-day close timestamps, where `end_date` must not precede `start_date`. Four policy knobs may be set at creation: `tiebreak_policy`, either `USAG_CLASSIC` or `NCAA_MODIFIED`, defaulting to `USAG_CLASSIC`; `qualifying_score_rule`, one of `ALL_AROUND_ONLY`, `PER_EVENT`, or `BOTH`, defaulting to `BOTH`; `inquiry_window_minutes`, the minutes after a score's publication during which a coach may file an inquiry, defaulting to 5; and `max_athletes_per_squad`, the squad size cap, defaulting to 12. A new meet rests in `DRAFT` posture.

Within the meet, the director creates one Session per competitive grouping. A session carries a `session_label` unique within the meet (something like "Session 1 — Level 4/5 Women"); a `level_band` drawn from `L2`, `L3`, `L4`, `L5`, `L6`, `L7`, `L8`, `L9`, `L10`, `XCEL_BRONZE`, `XCEL_SILVER`, `XCEL_GOLD`, `XCEL_PLATINUM`, or `XCEL_DIAMOND`; and its `scheduled_start` and `scheduled_end`. The session's window must sit inside the meet's: `scheduled_start` no earlier than the meet's `start_date`, and `scheduled_end` later than `scheduled_start` but no later than the meet's `end_date` plus a two-hour overflow buffer — a session declared outside that window, whether at creation or by a later update, is rejected with `ERR_SESSION_OUTSIDE_MEET_WINDOW`. Two timing offsets may be tuned per session: `warmup_open_offset_minutes`, defaulting to 90, and `march_in_offset_minutes`, defaulting to 15. The session's `apparatus_set` is an ordered list of exactly four elements, one per apparatus, each element naming an `apparatus` (`VAULT`, `UNEVEN_BARS`, `BALANCE_BEAM`, or `FLOOR_EXERCISE`) and a `flight_count`; each of the four apparatus must appear exactly once. Sessions are born in `SCHEDULED` state, and a session that has run its course records its close instant in `closed_at`.

Publishing the meet — moving its posture from `DRAFT` to `SCHEDULED` — is allowed only while the meet is `DRAFT`, only while every session's window satisfies the meet-window rule above, and only once every session has at least one squad assigned. Publication cascades: every session of the meet rests in `SCHEDULED` (a no-op for any session already there), every judge panel whose required judge count is already met moves from `FORMING` to `FULL`, and the meet's `version` increments by one.

From there the clock takes over. When the logical clock reaches the earliest session's warm-up open instant — that session's `scheduled_start` minus its own `warmup_open_offset_minutes` — the meet's posture advances `SCHEDULED` → `WARMUP_OPEN`, and each session individually crosses `SCHEDULED` → `WARMUP_OPEN` as its own offset arrives. When the clock reaches the earliest session's `scheduled_start`, the meet advances `WARMUP_OPEN` → `IN_COMPETITION`; each session crosses into `IN_ROTATION` at its own scheduled start, and every judge panel in `FULL` goes `ACTIVE`. Each session then walks its own timeline: `WARMUP_OPEN` → `MARCH_IN` when the clock reaches `scheduled_start` minus `march_in_offset_minutes`; `MARCH_IN` → `IN_ROTATION` at `scheduled_start` itself, which also pushes the session's first rotation (the one whose `rotation_number` is 1) from `PENDING` into `WARMUP`; and `IN_ROTATION` → `SCORING` once every rotation of the session has reached `SCORING_CLOSED` or `FINALIZED`.

Closing the meet is a deliberate act. A `MeetDirector` closes scoring — posture `IN_COMPETITION` → `SCORING_CLOSED` — only when every session of the meet is `CLOSED`, every score in the meet is `FINAL` or `VOID`, and no inquiry remains `FILED` or `UNDER_REVIEW`. The closure cascades into the computations described in §3.7 and §3.8: award ordering runs, qualification records are generated, and every entry's all-around rank is computed. Finalization — `SCORING_CLOSED` → `FINALIZED` — requires that every award row of the meet has its `ceremony_order` assigned and that every qualification record has reached `CONFIRMED`, `DECLINED`, or `REVOKED`; from `FINALIZED` onward no further score mutations are accepted, a gate enforced by validation. A `FINALIZED` meet can finally be archived, reaching the terminal posture `ARCHIVED`.

### 3.2. Rosters, Entries, and Squad Assignment

Before anyone can be entered, the athletes themselves must exist. A `MeetDirector` registers a Gymnast with a globally unique `usag_member_number` (the uppercase letter A followed by exactly seven digits), the athlete's `legal_name`, a `date_of_birth` stored as UTC midnight (the athlete's competitive age is derived as of December 31 of the sanction year), the `competitive_level` at time of entry — the same enumeration as a session's `level_band` — and the `home_gym` the athlete represents.

Entering a gymnast into a session creates an AthleteEntry: the payload carries the `gymnast_id`, and the entry is born `REGISTERED`. Two guards apply, in this order. First, level-band compatibility: for the compulsory levels `L2` through `L5` the gymnast's `competitive_level` must match the session's `level_band` exactly, while the optional levels `L6` through `L10` and the XCEL bands may cross one band up or down — anything wider is rejected with `ERR_LEVEL_BAND_MISMATCH`. Second, the double-entry rule: the same gymnast must not already hold an entry in another session of the same meet whose `entry_status` is anything other than `SCRATCHED`; a violation is rejected with `ERR_GYMNAST_DOUBLE_ENTERED` (HTTP 409).

On meet day a `Coach` checks the athlete in — `REGISTERED` → `CHECKED_IN` — provided the coach holds a pass with floor access granted on the parent meet (a coach who holds no such pass is rejected with `ERR_COACH_CREDENTIAL_LAPSED`, HTTP 422) and the coach's `affiliated_gym` matches the gymnast's `home_gym`. When the session itself reaches `IN_ROTATION`, every checked-in entry advances to `COMPETING` automatically. An entry reaches its terminal `COMPLETED` state once all four of its apparatus scores have reached `FINAL` or `VOID`; at that moment its all-around total is computed and its qualification is evaluated, as §3.7 and §3.8 describe.

A coach (or the meet director) may scratch an entry from `REGISTERED`, `CHECKED_IN`, or `COMPETING`, supplying a `scratch_reason` of `INJURY`, `COACH_DECISION`, `NO_SHOW`, or `DISQUALIFICATION`. Scratching cascades: every score of the entry still in `DRAFT` transitions to `VOID`, and the parent squad's `athlete_count` is recomputed. For an entry scratched from `REGISTERED` or `CHECKED_IN` — before competition began — the conflict flags on every panel assignment in the session are recomputed as well. For an entry scratched from `COMPETING`, scores already past `DRAFT` are retained as historical record rather than voided.

Squads divide a session's field into rotating groups. Each squad is created beneath its session — recorded on the squad as `session_id` — and a Squad carries a `squad_label` unique within the session (for example "Squad A") and the `starting_apparatus` on which it begins the rotation — one of `VAULT`, `UNEVEN_BARS`, `BALANCE_BEAM`, or `FLOOR_EXERCISE`. Its `rotation_index` is its zero-based current position in the rotation order (0 through 3) and advances as rotations close; its `athlete_count` is the derived count of entries linked to the squad whose `entry_status` is `REGISTERED` or `CHECKED_IN`.

Squad assignment is a bulk selector the meet director runs over a session. Eligible entries are those in `REGISTERED` whose `squad_id` is still null; they are ranked by registration order — `created_at` ascending, first come, first served — with ties broken by the gymnast's `usag_member_number` in lexicographic ascending order, which keeps the run deterministic. Athletes are then grouped by `home_gym`, preserving that order, because the USAG team-cohesion rule requires athletes from the same club to rotate together. Each gym group is placed into the first squad whose current `athlete_count` plus the size of the group stays within the meet's `max_athletes_per_squad`; a group that fits nowhere is left unassigned, its entries keeping a null `squad_id`. The selector updates each assigned entry's `squad_id` and each squad's `athlete_count`. A direct attempt to assign an entry into a squad that would thereby exceed the cap is instead rejected with `ERR_SQUAD_CAPACITY_EXCEEDED`.

### 3.3. Coach Credentialing and Floor Access

A `MeetDirector` registers a Coach with a globally unique `usag_coach_number` (the uppercase letter C followed by exactly seven digits), a `legal_name`, the `affiliated_gym` the coach represents at the meet, and two credential expiries: `background_check_expiry` and `safety_cert_expiry`. A coach's `credential_state` begins at `PENDING_VERIFICATION` and moves to `CREDENTIALED` when the director verifies the record; the enumeration also includes `SUSPENDED` and `REVOKED` for the credential lifecycle's darker outcomes.

A coach works a meet through a CoachMeetPass, issued by the director for a specific meet via a payload naming the `coach_id`; the pass is born `ISSUED` with `issued_at` recorded by the system. Granting floor access — `ISSUED` → `FLOOR_ACCESS_GRANTED` — is permitted only while the pass is `ISSUED`, the coach's `background_check_expiry` and `safety_cert_expiry` both lie strictly in the future relative to the logical clock, and the coach's `credential_state` is `CREDENTIALED`; lapsed credentials are rejected with `ERR_COACH_CREDENTIAL_LAPSED` (HTTP 422). The grant stamps `floor_access_granted_at`, which remains null until then.

The director may suspend a granted pass, recording a `suspension_reason` of `CREDENTIAL_LAPSE`, `CONDUCT`, or `SAFE_SPORT_HOLD` — `FLOOR_ACCESS_GRANTED` → `FLOOR_ACCESS_SUSPENDED`. Suspension strips the coach's standing at the inquiry desk: every inquiry that coach filed that is still `FILED` is cascade-transitioned to `EXPIRED`. Reinstating — `FLOOR_ACCESS_SUSPENDED` → `FLOOR_ACCESS_GRANTED` — re-checks both credential expiries against the clock before access is restored. Revoking a pass — permitted from `ISSUED`, `FLOOR_ACCESS_GRANTED`, or `FLOOR_ACCESS_SUSPENDED` — sends it to the terminal `REVOKED` state and expires the coach's still-`FILED` inquiries in exactly the same way.

### 3.4. Judge Panels and Conflict-of-Interest Control

A `MeetReferee` registers a Judge with a globally unique `usag_judge_number` (the uppercase letter J followed by exactly seven digits), a `legal_name`, a `rating` of `BREVET`, `NATIONAL`, `USA`, `LEVEL_10`, `LEVEL_9`, `LEVEL_8`, `LEVEL_7`, `LEVEL_4_5`, or `XCEL`, the judge's `affiliated_gym` — the field that drives conflict-of-interest exclusion — and an availability window from `availability_start` to `availability_end`, where the end must be later than the start.

Each apparatus of each session is judged by a JudgePanel, created by the referee with a payload naming the `meet_id` and the `apparatus`. A panel is born `FORMING`, and its `required_judge_count` is computed from the apparatus under the USAG rule: `BALANCE_BEAM` and `FLOOR_EXERCISE` panels require four judges, while `VAULT` and `UNEVEN_BARS` panels require two. Panels fill through PanelAssignment rows, each linking a `judge_panel_id` and a `judge_id` in a `role` of `PANEL_CHIEF`, `D_JUDGE`, `E_JUDGE`, `LINE_JUDGE`, or `TIMER`, beginning in `PROPOSED` state.

The referee may also run the panel auto-assignment selector, which proposes a slate deterministically. A judge is eligible when their rating permits the session's level band — `BREVET`, `NATIONAL`, and `USA` ratings may judge any band, a `LEVEL_10` rating covers `L10` sessions and below, and the remaining ratings follow the same descending pattern — when their availability window fully covers the session's `scheduled_start` through `scheduled_end`, when they hold no confirmed assignment on another panel whose session overlaps this one in time, and when their `affiliated_gym` matches the `home_gym` of no athlete entered in the session. Eligible judges are ranked by rating tier descending — `BREVET` highest, then `NATIONAL`, `USA`, `LEVEL_10`, `LEVEL_9`, `LEVEL_8`, `LEVEL_7`, `LEVEL_4_5`, and `XCEL` lowest — with ties broken by `usag_judge_number` in lexicographic ascending order, and the selector takes the first `required_judge_count` of them, creating their assignments in `PROPOSED`. If the eligible pool is smaller than the panel's required count, the run fails with `ERR_INSUFFICIENT_JUDGE_POOL` (HTTP 422).

Every assignment carries a computed `conflict_flag`: true exactly when the judge's `affiliated_gym` matches the `home_gym` of some athlete entered in the session and the assignment is not `RECUSED`. The flag is computed when the assignment is created and recomputed whenever entries are added to or removed from the session. Confirming an assignment — `PROPOSED` → `CONFIRMED` — requires the flag to be false (a conflicted confirmation is rejected with `ERR_JUDGE_CONFLICT_OF_INTEREST`, HTTP 422) and requires the judge's availability window to cover the session's scheduled interval (otherwise `ERR_JUDGE_UNAVAILABLE`, HTTP 422). Each confirmation recomputes the parent panel's `panel_state`: a `FORMING` panel becomes `FULL` once its required count of confirmed judges is reached. A panel cannot go `ACTIVE` while short of its required confirmed count — including at the moment a rotation beneath it is opened for scoring; the shortfall is reported as `ERR_PANEL_UNDERSTAFFED` (HTTP 422). When competition begins, every `FULL` panel goes `ACTIVE` as part of the meet's cascade into `IN_COMPETITION`, and panels end their service `RELEASED`.

Recusal — `CONFIRMED` → `RECUSED` — is available when the assignment's `conflict_flag` has come back true or when the acting referee cites a conflict; recusal recomputes the parent panel's state and may drop a `FULL` panel back to `FORMING`. Release — the terminal `RELEASED` state — is permitted from either `RECUSED` or `CONFIRMED`.

### 3.5. Rotations, Warm-Up Blocks, and Meet-Day Flow

Each session competes as four Rotations, one per apparatus, following the Olympic order `VAULT` → `UNEVEN_BARS` → `BALANCE_BEAM` → `FLOOR_EXERCISE`, with every squad beginning on its own `starting_apparatus`. Rather than hand-scheduling, the meet director generates the set: the system creates the four rotations in `PENDING` state, numbered 1 through 4 by `rotation_number`, each naming its `apparatus` and its `scheduled_start` and `scheduled_end` (the end later than the start). A rotation's duration derives from the field size — the total `athlete_count` across the session's squads — at a per-athlete pace of 30 seconds on `VAULT`, 90 seconds on `UNEVEN_BARS`, 120 seconds on `BALANCE_BEAM`, and 90 seconds on `FLOOR_EXERCISE`: the total headcount times the apparatus pace, divided by 60 and rounded up to a whole number of minutes. The first rotation opens at the session's `scheduled_start`, and each subsequent rotation begins five minutes after its predecessor's `scheduled_end` — the changeover gap. Rotation intervals are half-open, so adjacent rotations may share a boundary timestamp without overlapping; any true overlap of scheduled intervals within a session — whether the rotations are declared one at a time or generated as a set — is rejected with `ERR_ROTATION_OVERLAP` (HTTP 422).

Warm-ups are scheduled as WarmupBlock rows inside the sixty-minute window preceding a rotation's `scheduled_start`. A block names its `rotation_id`, `squad_id`, and `apparatus`, with a `block_start` no earlier than sixty minutes before the rotation's scheduled start and a `block_end` later than `block_start` and no later than the rotation's scheduled start. Blocks may abut — one block's end coinciding with the next block's start is permitted — but any deeper overlap with another block on the same rotation is rejected with `ERR_WARMUP_BLOCK_OVERLAP` (HTTP 422), and this guard applies equally to a single hand-created block and to a generated set. Generating the blocks allocates the window squad by squad in ascending `rotation_index` order, ties broken by squad creation order: each squad's raw allotment is its `athlete_count` times two minutes, rounded up to a whole minute, then clamped to no less than eight minutes and no more than twenty. Allocation is a waterfall — if the remaining window cannot hold a squad's clamped allotment, that squad receives whatever minutes remain — and if minutes are still unallocated after every squad has been placed, the last squad's block absorbs the overflow. A block's `state` begins at `SCHEDULED`, moves to `IN_PROGRESS` when the clock reaches its `block_start`, and eventually resolves to `COMPLETE` or `SKIPPED`.

The rotation lifecycle rides the same clock. Sixty minutes before its `scheduled_start`, a `PENDING` rotation opens to `WARMUP`, and each of its still-`SCHEDULED` blocks flips to `IN_PROGRESS` as its own `block_start` arrives. Once every block of the rotation has resolved to `COMPLETE` or `SKIPPED`, the rotation holds at `TIMED_WARMUP_HELD`. The meet director then opens scoring — `TIMED_WARMUP_HELD` → `OPEN_FOR_SCORING` — which requires the judge panel covering this session and apparatus to be `ACTIVE` and the logical clock to have reached the rotation's `scheduled_start`; the opening stamps `actual_start`, which is null until then. Closing scoring — `OPEN_FOR_SCORING` → `SCORING_CLOSED` — requires that every athlete whose squad's starting-rotation mapping schedules them into this rotation either has a score recorded in `FINAL`, `PUBLISHED`, `UNDER_INQUIRY`, `INQUIRY_RESOLVED`, or `VOID`, or holds a `SCRATCHED` entry; the close stamps `actual_end` and advances the `rotation_index` of every squad in the rotation by one, moving them to their next apparatus. When every score of the rotation has reached `FINAL` or `VOID`, the rotation itself advances `SCORING_CLOSED` → `FINALIZED`, its terminal state.

### 3.6. Score Entry, Publication, and the Inquiry Process

Scoring begins when a `JudgePanelChief` records a routine: a payload naming the `rotation_id`, the `apparatus`, a `difficulty_score`, an `execution_score`, and optionally a `neutral_deduction` (defaulting to 0.000 when omitted) creates a Score beneath the athlete's entry in `DRAFT` state. The range and precision rules of §2.7 apply to every field at entry and at amendment. While a score remains in `DRAFT`, the panel chief may amend any of `difficulty_score`, `execution_score`, or `neutral_deduction`; each amendment increments the score's `version` by one. Once the score has left `DRAFT`, amendment is rejected with `ERR_SCORE_AMEND_AFTER_PUBLISH` (HTTP 409).

Publication — `DRAFT` → `PUBLISHED` — is the panel chief's act and is guarded three ways. The rotation the score was performed in must be `OPEN_FOR_SCORING`; the acting judge must hold a confirmed `PANEL_CHIEF` assignment on the panel for this apparatus and session; and the request must carry `expected_score_version` matching the score's current `version` under the optimistic-concurrency rule of §2.8. Publication stamps `published_at`, computes the score's `provisional_total` as the difficulty score plus the execution score minus the neutral deduction — rounded half-up to three decimal places and floored at 0.000 — and pushes the result to the live scoring display. From `PUBLISHED`, one of three things happens.

The quiet path is expiry: when the logical clock passes `published_at` plus the meet's `inquiry_window_minutes` with no inquiry in `FILED` or `UNDER_REVIEW`, the score finalizes itself — `PUBLISHED` → `FINAL` — setting `final_total` equal to `provisional_total`, stamping `finalized_at`, and prompting the parent rotation to re-evaluate its own path from `SCORING_CLOSED` to `FINALIZED`.

The challenged path begins when a `Coach` files an inquiry against a published score. Filing is permitted only while the score is `PUBLISHED`, only while the logical clock has not passed `published_at` plus the meet's `inquiry_window_minutes` — filing at exactly that boundary instant is allowed, filing after it is rejected with `ERR_INQUIRY_WINDOW_EXPIRED` (HTTP 422) — only while the filing coach holds a pass in `FLOOR_ACCESS_GRANTED` on the meet with both credential expiries still in the future (`ERR_COACH_CREDENTIAL_LAPSED` otherwise), and only while no other inquiry on the same score sits in `FILED` or `UNDER_REVIEW` (a second open inquiry is rejected with `ERR_INQUIRY_ALREADY_OPEN`, HTTP 409). The filing payload names the `filed_by_coach_id`; the Inquiry is born `FILED`, carrying the `score_id` of the challenged score with `filed_at` recorded, and the score itself moves `PUBLISHED` → `UNDER_INQUIRY`.

At the inquiry desk the `MeetReferee` begins review — `FILED` → `UNDER_REVIEW` — and may return the inquiry to the queue — `UNDER_REVIEW` → `FILED` — as long as no resolution has been written yet, a deliberate loop that lets the referee defer without deciding. Resolution is the OCC-guarded write of §2.8: the request must carry `expected_inquiry_version` matching the inquiry's current `version`, plus a `resolution` of `D_RAISED`, `D_UNCHANGED`, `E_ADJUSTED`, `DEDUCTION_REMOVED`, or `NO_CHANGE`, the deltas `d_score_delta`, `e_score_delta`, and `deduction_delta` (each defaulting to 0), and an optional free-text `resolution_reason` of at most 512 characters. The deltas are bounded: `d_score_delta` and `e_score_delta` each between -2.000 and +2.000 inclusive, `deduction_delta` between -5.000 and 0.000 inclusive; a delta outside its range is rejected with `ERR_INQUIRY_DELTA_RANGE`. Consistency is enforced before ranges: an inquiry may only resolve `UPHELD` when at least one of the three deltas is non-zero, and may only resolve `DENIED` when all three deltas are zero — an inconsistent combination is rejected with `ERR_INQUIRY_RESOLUTION_INCONSISTENT`.

An `UPHELD` resolution folds the deltas into the score: the adjusted difficulty (the original `difficulty_score` plus `d_score_delta`), the adjusted execution (`execution_score` plus `e_score_delta`), and the adjusted deduction (`neutral_deduction` plus `deduction_delta`) are summed — difficulty plus execution minus deduction — and the provisional total is recomputed from those adjusted components with rounding applied after the summation, half-up to three decimals and floored at zero; the score's `final_total` is then this recomputed provisional total. A `DENIED` resolution leaves the score untouched, its `final_total` equal to the unchanged `provisional_total`. Either way the inquiry records `resolved_at` and the score moves `UNDER_INQUIRY` → `INQUIRY_RESOLVED`, from which the referee finalizes it — `INQUIRY_RESOLVED` → `FINAL` — provided the linked inquiry sits in `UPHELD` or `DENIED`; finalization stamps `finalized_at` and prompts the parent rotation's re-evaluation.

Two softer exits exist. The filing coach — and only that coach — may withdraw a still-`FILED` inquiry, moving it `FILED` → `WITHDRAWN`. And if the logical clock passes `published_at` plus four times the meet's `inquiry_window_minutes` with the inquiry still `FILED` and unreviewed, the system expires it — `FILED` → `EXPIRED`. Both exits record `resolved_at` on the inquiry and return the score from `UNDER_INQUIRY` to `PUBLISHED`, its `final_total` still equal to `provisional_total`, where the ordinary expiry path to `FINAL` resumes. Finally, the referee may void a score that never should have been published: `DRAFT` → `VOID`, permitted only when the score's athlete entry is `SCRATCHED`. `FINAL` and `VOID` are the score's terminal states.

### 3.7. Closing the Session: All-Around Totals, Awards, and Ceremony Order

When a session has reached `SCORING` — all four rotations closed or finalized — the meet director closes it, an OCC-guarded write carrying `expected_session_version` per §2.8. Closure requires that every score linked to entries in the session is `FINAL` or `VOID` and that no inquiry on any such score remains `FILED` or `UNDER_REVIEW`. The close stamps the session's `closed_at`, runs the award-ordering computation for the session, runs the qualification evaluation for each of its entries, and bubbles up to re-evaluate the parent meet's posture.

An entry's `all_around_total` is the sum of the `final_total` of its four apparatus scores that reached `FINAL`; a `VOID` apparatus — one scratched out from under the athlete — contributes 0.000, so a partial all-around is still well defined. Because each per-apparatus final is already at three-decimal precision, the rounding order is pinned: the per-apparatus finals are summed and the sum is then rounded half-up to three decimal places — never a sum of unrounded intermediates. The entry's `all_around_rank` is its one-based rank within the session by `all_around_total` descending and remains null until the session is `CLOSED`.

Awards are generated for a closed session by the meet director, supplying an `award_depth_per_category` that says how deep each podium runs. Award rows span five `category` values — `VAULT`, `UNEVEN_BARS`, `BALANCE_BEAM`, `FLOOR_EXERCISE`, and `ALL_AROUND` — with `place` running from 1 (gold) through 2 (silver) and 3 (bronze) up to the meet's award depth, each row pointing at its recipient entry via `athlete_entry_id` and stamped with `awarded_at`. Within each apparatus category, ranking is by `final_total` among the session's `FINAL` scores on that apparatus; the all-around category ranks entries by their `all_around_total`.

Ties are broken by the meet's `tiebreak_policy`. Under `USAG_CLASSIC`, tied totals are broken by the higher `execution_score`, then by the higher `difficulty_score`, then by the lower `neutral_deduction`; scores still tied after the full chain share a rank, and the next rank is skipped — two routines tied for second both receive place 2, and the next award given is place 4. Under `NCAA_MODIFIED`, a tie on the ranked total shares the rank immediately, with no execution-difficulty-deduction cascade. In both policies, ordering among fully tied rows falls back to creation order for deterministic presentation. Each score receives its `tiebreak_rank` — its one-based rank within its apparatus and session after the policy has run, null until the session is `CLOSED` — and an `is_tied` flag, true exactly when another score on the same apparatus in the same session carries an identical `final_total`, computed during award ordering. An Award whose recipient was selected through the tie-break chain rather than by raw score ordering is marked `was_tiebroken`.

The ceremony itself is sequenced by `ceremony_order`, an integer computed as the category's index times 100, plus the highest place awarded in that category minus the award's own place, plus one. Category indexes are `VAULT` 0, `UNEVEN_BARS` 1, `BALANCE_BEAM` 2, `FLOOR_EXERCISE` 3, and `ALL_AROUND` 4 — so within each category the deepest place is presented first and gold last, categories proceed in Olympic order, and the all-around awards, the most prestigious, always close the ceremony.

### 3.8. Qualification to the Next Meet

Qualification is evaluated when an entry completes and again at session close, and it is governed by the meet's `qualifying_score_rule`. The all-around thresholds are the USAG mobility scores, compared with an inclusive lower bound. A gymnast at `L4` or `L5` qualifies to a `STATE` meet with an all-around total of at least 32.000. At `L6`, `L7`, or `L8`, an all-around total of at least 34.000 qualifies to `STATE`, and at least 35.500 qualifies to `REGIONAL`. At `L9` or `L10`, at least 34.500 qualifies to `STATE`, at least 36.000 qualifies to `REGIONAL`, and — for `L10` only — at least 37.500 qualifies to `NATIONAL`. Independently of the all-around, a single-apparatus `final_total` of at least 9.000 qualifies the athlete to `STATE` on the strength of that event alone; a score of exactly 32.000 or exactly 9.000 qualifies, because every threshold comparison includes its boundary.

How the two paths combine depends on the rule. Under `ALL_AROUND_ONLY`, only the all-around thresholds count and the per-event rule is suppressed. Under `PER_EVENT`, only the single-apparatus rule applies and the all-around total is ignored. Under `BOTH`, either path qualifies. The entry's `qualified_for_next_meet` flag records the outcome — false until the session is `CLOSED` — and its `qualification_mobility_score` pins the specific score that drove the decision: under `PER_EVENT` the athlete's best single-event total; under `ALL_AROUND_ONLY` the `all_around_total`; and under `BOTH`, the higher of the `all_around_total` and the best event total when the event path fired, otherwise the `all_around_total`.

A qualifying entry gains a QualificationRecord in `PROVISIONAL` state, naming the `target_meet_level` it qualified for (`STATE`, `REGIONAL`, or `NATIONAL`) and pinning both the `qualifying_score_used` — the score value that met the threshold — and the `threshold_applied`, the threshold constant it was compared against, frozen at computation time for auditability. The meet director confirms a provisional record — `PROVISIONAL` → `CONFIRMED`, stamping `confirmed_at` — only while the parent entry is `COMPLETED` and the meet's posture is `SCORING_CLOSED` or `FINALIZED`. The athlete's own coach may instead decline it — `PROVISIONAL` → `DECLINED` — provided the coach holds floor access on the meet and the coach's `affiliated_gym` matches the gymnast's `home_gym`. And if a previously `FINAL` score for the entry is later found erroneous and corrected in a way that drops the athlete below the threshold, the director revokes the record — `CONFIRMED` → `REVOKED`, the audit path.

### 3.9. Spectator Admission and the Live Scoring Display

Spectators are admitted on SpectatorTicket rows, issued for one meet and one session — a ticket grants admission to a single session only. Issuance captures the `holder_name`, the `holder_email` (stored lowercase), a `ticket_class` of `GENERAL_ADMISSION`, `RESERVED`, `VIP`, or `COMP`, an optional `seat_section`, and a `price_cents` face value in cents. Three checks apply at issuance, in this order. The holder email must be unique within the session among tickets whose `ticket_state` is not `VOID`; a duplicate is rejected with `ERR_TICKET_DUPLICATE_EMAIL` (HTTP 409). The price must agree with the class: a `COMP` ticket must carry a `price_cents` of exactly 0 and every other class a positive price; a mismatch is rejected with `ERR_TICKET_PRICE_MISMATCH`. And the seat section must agree with the class: `RESERVED` and `VIP` tickets require a `seat_section`, while `GENERAL_ADMISSION` and `COMP` tickets must leave it null; a violation is rejected with `ERR_TICKET_SEAT_SECTION_INVALID`. A new ticket is born `ISSUED`.

At the gate, a `GateAttendant` scans the ticket — `ISSUED` → `SCANNED`, stamping `scanned_at` — which is permitted only while the meet's posture is `WARMUP_OPEN` or `IN_COMPETITION` and the logical clock lies within the scan window: no earlier than two hours before the session's `scheduled_start` and no later than its `scheduled_end`; a scan outside that window is rejected with `ERR_TICKET_OUTSIDE_SCAN_WINDOW`. A scanned ticket is then redeemed — `SCANNED` → `REDEEMED`, stamping `redeemed_at` — completing admission. Two administrative exits exist from `ISSUED`: the meet director may refund a ticket while the logical clock is still before the session's `scheduled_start` — after doors open, refunds are rejected with `ERR_REFUND_WINDOW_CLOSED` — and may void a ticket while the meet is still in `DRAFT`. `REDEEMED`, `REFUNDED`, and `VOID` are terminal.

Throughout the meet, a public live scoring read model exposes each session's current state of play: every score in `PUBLISHED` or `FINAL`, the rotation currently in progress, and the running leaderboard. It is a read model only — score publication refreshes it, and it is the surface a `Spectator` watches — with no write path of its own.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api/v1` prefix shown in the paths below. Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. The request and response payloads of each endpoint are defined by the narratives of §3; this table is only an index of method, path, purpose, and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/meets` | Create a Meet in DRAFT posture | MeetDirector |
| GET | `/api/v1/meets` | List meets with pagination and optional filters | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator, GateAttendant |
| GET | `/api/v1/meets/{id}` | Get one Meet | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator, GateAttendant |
| POST | `/api/v1/meets/{id}/publish` | Transition Meet DRAFT → SCHEDULED | MeetDirector |
| POST | `/api/v1/meets/{id}/close-scoring` | Transition Meet IN_COMPETITION → SCORING_CLOSED | MeetDirector |
| POST | `/api/v1/meets/{id}/finalize` | Transition Meet SCORING_CLOSED → FINALIZED | MeetDirector |
| POST | `/api/v1/meets/{id}/archive` | Transition Meet FINALIZED → ARCHIVED | MeetDirector |
| POST | `/api/v1/meets/{id}/sessions` | Create a Session within a Meet | MeetDirector |
| GET | `/api/v1/meets/{id}/sessions` | List sessions for a meet | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| GET | `/api/v1/sessions/{id}` | Get one Session | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| POST | `/api/v1/sessions/{id}/close` | Transition Session SCORING → CLOSED (OCC-guarded) | MeetDirector |
| POST | `/api/v1/sessions/{id}/squads` | Create a Squad within a Session | MeetDirector |
| GET | `/api/v1/sessions/{id}/squads` | List squads for a session | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| GET | `/api/v1/squads/{id}` | Get one Squad | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| GET | `/api/v1/squads/{id}/athlete-entries` | List athlete entries assigned to a squad | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| POST | `/api/v1/sessions/{id}/assign-squads` | Run squad assignment across REGISTERED entries | MeetDirector |
| POST | `/api/v1/gymnasts` | Register a Gymnast (master record) | MeetDirector |
| GET | `/api/v1/gymnasts` | List gymnasts | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/gymnasts/{id}` | Get one Gymnast | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/sessions/{id}/athlete-entries` | Enter a gymnast into a session | MeetDirector, Coach |
| GET | `/api/v1/sessions/{id}/athlete-entries` | List entries for a session | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| GET | `/api/v1/gymnasts/{id}/athlete-entries` | List entries for a gymnast | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/athlete-entries/{id}` | Get one AthleteEntry | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| POST | `/api/v1/athlete-entries/{id}/check-in` | AthleteEntry REGISTERED → CHECKED_IN | Coach |
| POST | `/api/v1/athlete-entries/{id}/scratch` | AthleteEntry → SCRATCHED | Coach, MeetDirector |
| POST | `/api/v1/coaches` | Register a Coach (master record) | MeetDirector |
| GET | `/api/v1/coaches` | List coaches | MeetDirector, MeetReferee |
| GET | `/api/v1/coaches/{id}` | Get one Coach | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/coaches/{id}/verify` | Coach PENDING_VERIFICATION → CREDENTIALED | MeetDirector |
| POST | `/api/v1/meets/{id}/coach-meet-passes` | Issue a coach pass for a meet | MeetDirector |
| GET | `/api/v1/meets/{id}/coach-meet-passes` | List coach passes for a meet | MeetDirector, MeetReferee |
| GET | `/api/v1/coaches/{id}/coach-meet-passes` | List passes held by a coach | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/coach-meet-passes/{id}` | Get one CoachMeetPass | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/coach-meet-passes/{id}/grant-floor-access` | Pass ISSUED → FLOOR_ACCESS_GRANTED | MeetDirector |
| POST | `/api/v1/coach-meet-passes/{id}/suspend` | Pass FLOOR_ACCESS_GRANTED → FLOOR_ACCESS_SUSPENDED | MeetDirector |
| POST | `/api/v1/coach-meet-passes/{id}/reinstate` | Pass FLOOR_ACCESS_SUSPENDED → FLOOR_ACCESS_GRANTED | MeetDirector |
| POST | `/api/v1/coach-meet-passes/{id}/revoke` | Pass → REVOKED | MeetDirector |
| POST | `/api/v1/judges` | Register a Judge (master record) | MeetReferee |
| GET | `/api/v1/judges` | List judges | MeetDirector, MeetReferee |
| GET | `/api/v1/judges/{id}` | Get one Judge | MeetDirector, MeetReferee |
| POST | `/api/v1/sessions/{id}/judge-panels` | Create a JudgePanel for (session, apparatus) | MeetReferee |
| GET | `/api/v1/sessions/{id}/judge-panels` | List panels for a session | MeetDirector, MeetReferee, JudgePanelChief |
| GET | `/api/v1/meets/{id}/judge-panels` | List panels for a meet | MeetDirector, MeetReferee, JudgePanelChief |
| GET | `/api/v1/judge-panels/{id}` | Get one JudgePanel | MeetDirector, MeetReferee, JudgePanelChief |
| POST | `/api/v1/judge-panels/{id}/auto-assign` | Run the judge panel selector to propose assignments | MeetReferee |
| GET | `/api/v1/judge-panels/{id}/assignments` | List assignments for a panel | MeetDirector, MeetReferee, JudgePanelChief |
| GET | `/api/v1/judges/{id}/panel-assignments` | List assignments held by a judge | MeetDirector, MeetReferee |
| GET | `/api/v1/panel-assignments/{id}` | Get one PanelAssignment | MeetDirector, MeetReferee, JudgePanelChief |
| POST | `/api/v1/panel-assignments/{id}/confirm` | PanelAssignment PROPOSED → CONFIRMED | MeetReferee |
| POST | `/api/v1/panel-assignments/{id}/recuse` | PanelAssignment CONFIRMED → RECUSED | MeetReferee |
| POST | `/api/v1/panel-assignments/{id}/release` | PanelAssignment → RELEASED | MeetReferee |
| POST | `/api/v1/sessions/{id}/rotations/generate` | Generate the four Rotation rows for a session | MeetDirector |
| GET | `/api/v1/sessions/{id}/rotations` | List rotations for a session | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| GET | `/api/v1/rotations/{id}` | Get one Rotation | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| POST | `/api/v1/rotations/{id}/open-scoring` | Rotation TIMED_WARMUP_HELD → OPEN_FOR_SCORING | MeetDirector |
| POST | `/api/v1/rotations/{id}/close-scoring` | Rotation OPEN_FOR_SCORING → SCORING_CLOSED | MeetDirector |
| POST | `/api/v1/rotations/{id}/warmup-blocks` | Create a single WarmupBlock | MeetDirector |
| POST | `/api/v1/rotations/{id}/warmup-blocks/generate` | Generate warm-up blocks for all squads of a rotation | MeetDirector |
| GET | `/api/v1/rotations/{id}/warmup-blocks` | List warm-up blocks for a rotation | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/squads/{id}/warmup-blocks` | List warm-up blocks for a squad | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/warmup-blocks/{id}` | Get one WarmupBlock | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/athlete-entries/{id}/scores` | Create a Score row in DRAFT for an entry and apparatus | JudgePanelChief |
| GET | `/api/v1/athlete-entries/{id}/scores` | List scores for an entry | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| GET | `/api/v1/rotations/{id}/scores` | List scores for a rotation | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| GET | `/api/v1/scores/{id}` | Get one Score | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| PUT | `/api/v1/scores/{id}` | Amend a DRAFT score's input fields | JudgePanelChief |
| POST | `/api/v1/scores/{id}/publish` | Score DRAFT → PUBLISHED (OCC-guarded) | JudgePanelChief |
| POST | `/api/v1/scores/{id}/void` | Score DRAFT → VOID | MeetReferee |
| POST | `/api/v1/scores/{id}/finalize` | Score INQUIRY_RESOLVED → FINAL | MeetReferee |
| POST | `/api/v1/scores/{id}/inquiries` | File an inquiry; Score PUBLISHED → UNDER_INQUIRY | Coach |
| GET | `/api/v1/scores/{id}/inquiries` | List inquiries for a score | MeetDirector, MeetReferee, JudgePanelChief, Coach |
| GET | `/api/v1/coaches/{id}/inquiries` | List inquiries filed by a coach | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/inquiries/{id}` | Get one Inquiry | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/inquiries/{id}/begin-review` | Inquiry FILED → UNDER_REVIEW | MeetReferee |
| POST | `/api/v1/inquiries/{id}/return-to-queue` | Inquiry UNDER_REVIEW → FILED | MeetReferee |
| POST | `/api/v1/inquiries/{id}/resolve` | Inquiry UNDER_REVIEW → UPHELD or DENIED (OCC-guarded) | MeetReferee |
| POST | `/api/v1/inquiries/{id}/withdraw` | Inquiry FILED → WITHDRAWN | Coach |
| GET | `/api/v1/sessions/{id}/awards` | List awards for a session | MeetDirector, MeetReferee, Coach, Spectator |
| GET | `/api/v1/athlete-entries/{id}/awards` | List awards for an entry | MeetDirector, MeetReferee, Coach, Spectator |
| GET | `/api/v1/awards/{id}` | Get one Award | MeetDirector, MeetReferee, Coach, Spectator |
| POST | `/api/v1/sessions/{id}/awards/generate` | Generate Award rows for a closed session | MeetDirector |
| POST | `/api/v1/meets/{id}/sessions/{id}/spectator-tickets` | Issue a spectator ticket | MeetDirector, GateAttendant |
| GET | `/api/v1/meets/{id}/spectator-tickets` | List tickets for a meet | MeetDirector, GateAttendant |
| GET | `/api/v1/sessions/{id}/spectator-tickets` | List tickets for a session | MeetDirector, GateAttendant |
| GET | `/api/v1/spectator-tickets/{id}` | Get one SpectatorTicket | MeetDirector, GateAttendant |
| POST | `/api/v1/spectator-tickets/{id}/scan` | Ticket ISSUED → SCANNED | GateAttendant |
| POST | `/api/v1/spectator-tickets/{id}/redeem` | Ticket SCANNED → REDEEMED | GateAttendant |
| POST | `/api/v1/spectator-tickets/{id}/refund` | Ticket ISSUED → REFUNDED | MeetDirector |
| POST | `/api/v1/spectator-tickets/{id}/void` | Ticket ISSUED → VOID (meet DRAFT only) | MeetDirector |
| GET | `/api/v1/athlete-entries/{id}/qualification-records` | List qualification records for an entry | MeetDirector, MeetReferee, Coach |
| GET | `/api/v1/qualification-records/{id}` | Get one QualificationRecord | MeetDirector, MeetReferee, Coach |
| POST | `/api/v1/qualification-records/{id}/confirm` | QualificationRecord PROVISIONAL → CONFIRMED | MeetDirector |
| POST | `/api/v1/qualification-records/{id}/decline` | QualificationRecord PROVISIONAL → DECLINED | Coach |
| POST | `/api/v1/qualification-records/{id}/revoke` | QualificationRecord CONFIRMED → REVOKED | MeetDirector |
| GET | `/api/v1/sessions/{id}/live-scores` | Public live scoring read model: published and final scores, current rotation, leaderboard | MeetDirector, MeetReferee, JudgePanelChief, Coach, Spectator |
| POST | `/api/v1/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-05-01T00:00:00Z) | MeetDirector |

## 5. Error Code Catalogue

The following table enumerates every error identifier the API may return. The conditions that trigger each error are defined by the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MEET_POSTURE_FORBIDS` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_SCORE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INQUIRY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SESSION_VERSION` | 412 Precondition Failed |
| `ERR_COACH_CREDENTIAL_LAPSED` | 422 Unprocessable Entity |
| `ERR_JUDGE_CONFLICT_OF_INTEREST` | 422 Unprocessable Entity |
| `ERR_JUDGE_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_JUDGE_POOL` | 422 Unprocessable Entity |
| `ERR_PANEL_UNDERSTAFFED` | 422 Unprocessable Entity |
| `ERR_INQUIRY_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INQUIRY_ALREADY_OPEN` | 409 Conflict |
| `ERR_INQUIRY_RESOLUTION_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_INQUIRY_DELTA_RANGE` | 422 Unprocessable Entity |
| `ERR_WARMUP_BLOCK_OVERLAP` | 422 Unprocessable Entity |
| `ERR_ROTATION_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SESSION_OUTSIDE_MEET_WINDOW` | 422 Unprocessable Entity |
| `ERR_SCORE_FIELD_RANGE` | 422 Unprocessable Entity |
| `ERR_SQUAD_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LEVEL_BAND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GYMNAST_DOUBLE_ENTERED` | 409 Conflict |
| `ERR_TICKET_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_TICKET_PRICE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TICKET_SEAT_SECTION_INVALID` | 422 Unprocessable Entity |
| `ERR_TICKET_OUTSIDE_SCAN_WINDOW` | 422 Unprocessable Entity |
| `ERR_REFUND_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SCORE_AMEND_AFTER_PUBLISH` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
