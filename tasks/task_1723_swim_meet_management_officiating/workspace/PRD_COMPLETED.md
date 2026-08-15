# Swim Meet Officiating API — Product Requirements Document

## 1. Introduction

Running a USA Swimming club meet is an exercise in coordinated deadlines and irreversible decisions. Entries pour in from club coaches against a hard cutoff; qualifying times must be verified before anyone is seeded; heat sheets must be generated fairly and, when corrections arrive, torn up and regenerated; officials must be credentialed, assigned, and confirmed before a race may start; and once racing begins, the timing console, the stroke-and-turn judges, and the referee all write into the same record of what happened in the water. The errors that invalidate a meet after the fact are well known to anyone who has run one: a cut time verified against the wrong standard, an expired certification on deck, a disqualification confirmed by the same official who called it, a team total that quietly double-counts a rescored race.

This document specifies the Swim Meet Officiating API, the system of record for that workflow. It governs the full arc of a meet: configuration and entry collection, qualification verification, seeding and heat-sheet generation, deck coverage and official assignment, timing capture with backup reconciliation, disqualification adjudication under segregation of duties, scoring and team-point rollups under two tie policies, and meet-record challenges through ratification. Two principles shape every rule that follows. First, **posture gates everything**: where the meet and each event stand in their lifecycles determines which writes are lawful at any moment, and the lifecycle machines below are the authority. Second, **numbers are exact**: every race time is an integer count of centiseconds and every points figure is a decimal rounded half-up to two places, so that two faithful implementations of this specification produce identical results from identical inputs.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `MeetDirector`, `TeamCoach`, `TimingOperator`, `DeckOfficial`, `MeetReferee`, and `RecordsOfficer`. Endpoints documented as open to "Any" role accept a caller presenting any of these six; `Any` is a permission convention, not an assumable role. An authenticated caller whose role is not permitted for an endpoint — or who fails an ownership check — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `TeamCoach`, `X-User-ID` is the `id` of the acting Team. Ownership checks on any resource that references a Team — swimmers, entries, relay teams and their legs, protested disqualifications — compare the resource's team field to `X-User-ID`, and a coach acting on another club's resource fails the check.
- When `X-User-Role` is `DeckOfficial` or `MeetReferee`, `X-User-ID` is the `id` of the acting Official. Recording a disqualification requires that Official to hold a confirmed stroke-and-turn assignment on the event in question, and confirming one's own deck assignment requires `X-User-ID` to equal the assignment's `official_id`.
- When `X-User-Role` is `MeetDirector`, `TimingOperator`, or `RecordsOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`.

Segregation of duties binds the officiating roles together: the referee who rules on a disqualification — confirming, upholding, or overturning it — must never be the official who recorded the call. Any such attempt is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403); §3.8 carries the full rule.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100 — a `limit` below 1, or a non-integer `limit`, is rejected with `ERR_INVALID_REQUEST`, while a `limit` above 100 is silently capped at 100. `offset` sets the number of items skipped and defaults to 0; an `offset` below 0, or a non-integer `offset`, is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the size of the full filtered listing and `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

Most list endpoints also accept optional filters keyed to an owning resource: teams filter by `meet_id`; swimmers by `team_id`; events by `meet_id`; entries by `event_id`, `swimmer_id`, `relay_team_id`, or `team_id`; relay teams by `team_id`, `event_id`, or `entry_id`; relay legs by `swimmer_id` or `relay_team_id`; lane assignments by `event_id` or `entry_id`; officials by `meet_id`; official assignments by `official_id`; disqualifications by `reporting_official_id` or `resolved_by_referee_id`; and records by `event_id` or `challenger_entry_id`.

### 2.4. The Logical Clock

All time-sensitive decisions — entry-deadline admission, the close-entries guard, protest windows, recorded notification instants — are evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any explicit set, the logical clock reads exactly 2026-08-01T00:00:00Z at server startup, and it never falls back to wall-clock time thereafter. A test-driving capability open to any authenticated role advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; the set is unconditional, moving the clock to exactly the supplied instant — earlier or later — with no monotonicity guard. Business timestamps the system records, such as the coach-notification instant on a disqualification, are always logical-clock readings.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource and serves as the basis of optimistic concurrency control (§2.7).

One deliberate exception exists: a relay leg is a thin join record carrying only `id` and `created_at`; `updated_at` and `version` are absent from it entirely.

The Meet narrows the general version rule: a meet's `version` increments only on meet lifecycle transitions — opening entries, closing entries, seeding, reopening entries, completing, and finalizing — and on edits to the meet's configuration. Writes to other resources never move it.

### 2.6. Time Values and Points Precision

Every race-time quantity in the system — seed times, qualifying cuts, the four lane readings, reconciled final times, and record times — is an integer count of centiseconds (hundredths of a second), stored in fields whose names end in `_cs`. Fractional centiseconds exist nowhere in the timing pipeline.

Two rounding rules govern every computed number:

- Wherever the backup-button mean is needed, the two backup readings are averaged and the mean is rounded half-up to a whole centisecond **before** it feeds any comparison; reconciled final times always copy an already-integer source and are never re-rounded. §3.7 pins this ordering and shows why it matters.
- Every points figure — a result's `points` and each team's `provisional_points` and `official_points` — is rounded half-up to exactly two decimal places and rendered as a number with at most two decimal places.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, each against the `version` of its parent aggregate:

- A `POST /meets/{id}/seed` request must carry `expected_meet_version`, holding the `version` of the Meet the client last observed. If the meet's current `version` has advanced since — because an intervening reopen-and-close cycle or an earlier successful seed moved it — the seed is rejected with `ERR_STALE_VERSION` (HTTP 412). This check runs **before** any state-machine guard, so a stale request fails even when the meet is otherwise seedable; the client's heat-sheet plan was computed from an entry roster the meet no longer has.
- A `POST /events/{id}/complete` request must carry `expected_event_version`, holding the `version` of the SwimEvent the client last observed. If the event's current `version` has advanced since — typically an intervening referee reopen or a disqualification-driven rescore — the completion is rejected with `ERR_STALE_VERSION` (HTTP 412), again ahead of the state checks, because the client's view of which lanes are reconciled is stale.

Both fields are non-optional inputs on their respective operations. Endpoints not named here accept no version field at all.

### 2.8. Meet Posture, Cascades, and Derived State

Meet and event `status` act as gates: nearly every write in the system is lawful only while the enclosing Meet or SwimEvent stands in a specific posture, and the state machines of §3 define each gate exactly. When a high-level operation invalidates downstream work, the server performs the cascade itself rather than leaving reconciliation to clients: withdrawing a team scratches its entries and voids its lanes; confirming or overturning a disqualification can re-score a completed event; publishing an event promotes its results and may spawn a record challenge. Each cascade recomputes the derived figures it touches — team point totals and active-entry counts — as full recomputations from current data, never as incremental adjustments, so a re-derived figure always equals what a fresh calculation from the underlying rows would produce. Every resource mutated along the way has its `updated_at` refreshed and its `version` handled per §2.5.

### 2.9. Resource Addressing and Existence Validation

The API presents a flat topology: every entity lives in a top-level collection, and several operations hang a child collection beneath a parent path — an event's official assignments or records, a lane assignment's disqualifications. For any such request, path identifiers are validated for existence strictly left to right, and the request is rejected with the not-found identifier of the **first** missing resource before any later identifier is examined. Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404). A relay leg carries no dedicated not-found error of its own: a request addressing a missing relay-leg identifier is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Foreign-key references supplied in request bodies are validated for existence under the same discipline.

### 2.10. The Validation Pipeline

When several rules could reject the same request, the checks fire in a fixed order so the surfaced error is deterministic. The pipeline runs as follows, earlier tiers masking later ones:

1. **Authentication context** — the two headers are present and the role is declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization and ownership** — the role may perform the operation and owns the resource (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Segregation of duties** — on disqualification rulings, the caller is not the reporting official (`ERR_SEGREGATION_OF_DUTY`).
4. **Existence** — path identifiers left to right, then body foreign keys (the not-found errors of §2.9).
5. **Optimistic concurrency** — where an operation declares an expected-version field, it must match the parent's current `version` (`ERR_STALE_VERSION`); this tier deliberately precedes the state guards.
6. **State-machine posture** — the target resource stands in a state permitting the transition (the domain state errors: `ERR_MEET_INVALID_STATE`, `ERR_MEET_NOT_ACCEPTING_ENTRIES`, `ERR_EVENT_NOT_SEEDED`, `ERR_EVENT_NOT_IN_PROGRESS`, `ERR_EVENT_NOT_COMPLETED`, `ERR_ENTRY_NOT_SCRATCHABLE`, `ERR_ENTRY_NOT_UNSCRATCHABLE`, `ERR_ENTRY_NOT_VERIFIABLE`, `ERR_LANE_VOIDED`, `ERR_DQ_INVALID_STATE`, `ERR_RECORD_INVALID_STATE`, and their siblings).
7. **Official certification** — deck-assignment proposals (`ERR_CERTIFICATION_INVALID`).
8. **Entry window** — entry and relay creation against the logical clock (`ERR_ENTRY_DEADLINE_PASSED`).
9. **Protest windows** — disqualification protest and confirmation timing (`ERR_PROTEST_WINDOW_EXPIRED`, `ERR_PROTEST_WINDOW_OPEN`).
10. **Eligibility** — team standing first: a withdrawn club's swimmers are already inactive, so `ERR_TEAM_NOT_ACTIVE` always surfaces ahead of any swimmer-level failure; then age-band matching (`ERR_AGE_GROUP_INELIGIBLE`) and gender matching (`ERR_GENDER_INELIGIBLE`).
11. **Entry aggregate limit** — per-swimmer individual-entry cap (`ERR_SWIMMER_ENTRY_LIMIT`).
12. **Recovery buffer** — same-session scheduling gaps (`ERR_RECOVERY_WINDOW_VIOLATION`).
13. **Official double-booking** — overlapping deck assignments (`ERR_OFFICIAL_ASSIGNMENT_CONFLICT`).
14. **Relay structure** — leg numbering, swimmer uniqueness, and club membership (`ERR_RELAY_SWIMMER_DUPLICATE`, `ERR_RELAY_SWIMMER_TEAM_MISMATCH`).
15. **Aggregate gates spanning many resources** — undecided qualifications (`ERR_QUALIFICATION_UNDECIDED`), incomplete deck coverage (`ERR_OFFICIAL_COVERAGE_INCOMPLETE`), unresolved lanes (`ERR_UNRESOLVED_LANES_EXIST`), events not yet final (`ERR_EVENTS_NOT_OFFICIAL`), records still pending (`ERR_RECORDS_PENDING`), an incomplete four-leg roster (`ERR_RELAY_LEG_COUNT_INCOMPLETE`), a second live disqualification on one lane (`ERR_DQ_ALREADY_ACTIVE`), and a duplicate standing record (`ERR_RECORD_STANDING_EXISTS`).
16. **Readings payload sanity** — at least one timing value must be present (`ERR_INVALID_REQUEST`).

A request failing two checks always reports the earlier tier's error. Independently of this pipeline, malformed bodies, missing required fields, type mismatches, and invalid enum values are rejected with `ERR_INVALID_REQUEST` (HTTP 400) wherever they occur.

## 3. Business Logic & Workflows

### 3.1. Meet Configuration, Teams, and Swimmers

A `MeetDirector` brings a meet into existence with a `meet_name`, a `course` of `SCY`, `SCM`, or `LCM` (short-course yards, short-course meters, or long-course meters), a `start_date` marking the first day of competition, and an `entry_deadline_utc` fixing the instant after which entries close. The tuning knobs all carry defaults: `lane_count` defaults to 6, is rejected with `ERR_INVALID_REQUEST` when supplied below 1, and fixes both the number of lanes per heat and the chunk size seeding works in; `points_table` defaults to `[9, 7, 6, 5, 4, 3, 2, 1]` — nine points for first place down to one point for eighth — and its length sets the scoring depth; `relay_points_multiplier` defaults to 2; `max_individual_entries_per_swimmer` defaults to 4; `dq_protest_window_minutes` defaults to 30; `min_recovery_minutes` defaults to 20; and `timing_delta_threshold_cs` defaults to 30 centiseconds. The `scoring_tie_policy` is either `SPLIT` or `TOP`, defaults to `SPLIT`, and becomes immutable once the meet has been seeded. A new meet stands in `SETUP`.

The meet lifecycle runs `SETUP` → `ENTRIES_OPEN` → `ENTRIES_CLOSED` → `SEEDED` → `COMPLETED` → `OFFICIAL`, with one escape hatch: from `SEEDED` the director may reopen entries and return to `ENTRIES_OPEN`. Each step is an explicit director action, and a lifecycle action attempted from a posture that forbids it — opening entries when the meet is not in `SETUP`, for instance — is rejected with `ERR_MEET_INVALID_STATE`. Opening entries carries no precondition beyond posture. Closing entries requires the logical clock to have advanced strictly past `entry_deadline_utc`; entries are accepted inclusively at the deadline instant itself, so while the clock is at or before the deadline the close attempt fails with `ERR_ENTRY_WINDOW_STILL_OPEN`. Seeding, reopening, completing, and finalizing carry richer gates covered in §3.6 and §3.9. Every lifecycle transition increments the meet's `version` by one, as does any edit to the meet's configuration.

Clubs join the meet when the director registers a Team with its `meet_id`, a `team_code` unique within the meet (a duplicate is rejected with `ERR_INVALID_REQUEST`), and a `team_name`. A team is born `REGISTERED` with `provisional_points`, `official_points`, and `active_entry_count` all starting at zero. Withdrawal is the director's act and moves a team from `REGISTERED` to the terminal `WITHDRAWN`, but only while the meet stands in `SETUP`, `ENTRIES_OPEN`, `ENTRIES_CLOSED`, or `SEEDED`; once the meet is `COMPLETED` or `OFFICIAL`, withdrawal is refused with `ERR_MEET_ALREADY_COMPLETED`. A withdrawal attempted on a team already `WITHDRAWN` fails with `ERR_INVALID_REQUEST`, and this check fires ahead of the meet-posture gate. The withdrawal cascade is total: every swimmer of the team becomes `INACTIVE`; every entry of the team standing in `ENTERED` or `SEEDED` becomes `SCRATCHED`, and each such seeded entry's lane assignment flips to `VOIDED`; every relay team standing in `DECLARED` or `LEGS_LOCKED` becomes `SCRATCHED`, its entry and lane cascading in the same way; and the team's `active_entry_count` is recomputed, landing at zero.

A `TeamCoach` registers swimmers onto their own club's roster with `team_id`, `full_name`, `birth_date`, and a `gender` of `M` or `F`. At registration the system derives `age_on_meet_start` as the swimmer's whole years from `birth_date` to the meet's `start_date`, counting a birthday that falls exactly on the start date — a swimmer born 2014-08-15 at a meet starting 2026-08-15 registers as twelve years old. From that age comes the `age_group`: ten or younger maps to `TEN_AND_UNDER`, eleven or twelve to `ELEVEN_TWELVE`, thirteen or fourteen to `THIRTEEN_FOURTEEN`, and fifteen or older to `FIFTEEN_AND_OVER`. A swimmer is born `ACTIVE` and leaves that state only through the team-withdrawal cascade.

A team's `active_entry_count` tracks its live commitment load: it counts the team's entries standing in `ENTERED`, `SEEDED`, `FINISHED`, `DQ`, or `NO_SHOW`, and excludes anything `SCRATCHED`. The figure is recomputed, never adjusted by hand, whenever entries are created, scratched, restored from scratch, marked as no-shows, or caught in a relay-scratch or team-withdrawal cascade.

### 3.2. Defining the Event Program

Before entries open, the `MeetDirector` defines the event program. Each SwimEvent carries its `meet_id`, an `event_number` unique within the meet (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `gender` of `M`, `F`, or `MIXED`, an `age_group` drawn from the same four bands swimmers derive, a `stroke` of `FREESTYLE`, `BACKSTROKE`, `BREASTSTROKE`, `BUTTERFLY`, `INDIVIDUAL_MEDLEY`, `FREESTYLE_RELAY`, or `MEDLEY_RELAY`, and a `distance_meters`. The `is_relay` flag decides how the event takes entries: a relay event is entered exclusively through relay declarations (§3.4), never through the individual-entry path — the individual-entry write against a relay event fails with `ERR_INVALID_REQUEST`. An optional `qualifying_time_cs` sets the cut in centiseconds; a null cut marks a no-cut event in which every entry verifies (§3.3). The event's `session_date` scopes both the swimmer recovery buffer and official double-booking, while `scheduled_start_minute` and `scheduled_end_minute` position the race as minutes from midnight forming a half-open window — the start minute belongs to the event, the end minute does not — and the end must be strictly later than the start, failing with `ERR_INVALID_REQUEST` otherwise.

Every event is born `PENDING` and follows `PENDING` → `SEEDED` → `IN_PROGRESS` → `COMPLETED` → `OFFICIAL`, with two deviations: a seeded event falls back to `PENDING` if the meet's entries are reopened, and a completed event returns to `IN_PROGRESS` if the referee reopens it. `CANCELLED` is terminal and arrives only from seeding, when an event draws no verified entries at all (§3.6). An event's `version` increments on each of these transitions and on disqualification-driven rescores.

### 3.3. Entries, Eligibility, and Qualification

An EventEntry binds a swimmer — or, for relays, a relay team — to an event. Exactly one of `swimmer_id` and `relay_team_id` is ever populated: individual entries carry `swimmer_id`, while relay entries are created by the relay declaration itself with `relay_team_id` set (§3.4). A `TeamCoach` enters an individual swimmer with `event_id`, `swimmer_id`, and an optional `seed_time_cs` in centiseconds; an entry without a seed time swims as `NT` — "no time" — and seeds last.

Creation is gated first by the meet's posture and clock. Entries are accepted only while the meet stands in `ENTRIES_OPEN`; from any other posture the write fails with `ERR_MEET_NOT_ACCEPTING_ENTRIES`. Independently, the logical clock must not have passed `entry_deadline_utc` — a submission landing exactly at the deadline instant is still accepted, while anything later fails with `ERR_ENTRY_DEADLINE_PASSED`. Eligibility then applies three tests, with the team's standing checked first because a withdrawn club's swimmers are already inactive: the team must be `REGISTERED` (`ERR_TEAM_NOT_ACTIVE`), the swimmer's derived `age_group` must equal the event's `age_group` (`ERR_AGE_GROUP_INELIGIBLE`), and the swimmer's `gender` must match the event's `gender` unless the event is `MIXED`, which accepts any swimmer (`ERR_GENDER_INELIGIBLE`).

Two athlete-welfare limits follow. A swimmer may hold at most `max_individual_entries_per_swimmer` non-`SCRATCHED` individual entries in the meet — at the default of four, the fourth entry succeeds and the fifth is refused with `ERR_SWIMMER_ENTRY_LIMIT`. Separately, on any single `session_date`, a swimmer's individual events must respect the recovery buffer measured between their scheduled windows: the gap from the earlier event's end to the later event's start must be at least `min_recovery_minutes`, a gap exactly equal to the buffer is allowed, and any overlap between the two windows is always a violation, rejected as `ERR_RECOVERY_WINDOW_VIOLATION`.

A new entry stands `ENTERED` with `qualification_status` `UNVERIFIED`, and the team's `active_entry_count` is recomputed. Qualification lives on a parallel axis, orthogonal to entry `status`, and is decided by the `MeetDirector` through verification. Verification is lawful only while the meet stands in `ENTRIES_OPEN` or `ENTRIES_CLOSED` and the entry stands `ENTERED`; otherwise it fails with `ERR_ENTRY_NOT_VERIFIABLE`. Against a cut, the entry verifies — moving to `VERIFIED` — if and only if its `seed_time_cs` is less than or equal to `qualifying_time_cs`, with a seed exactly equal to the cut qualifying; a slower seed, or an `NT` entry with nothing to compare against the cut, is marked `REJECTED`. In a no-cut event every entry verifies, `NT` included. Every verification write refreshes the entry's `version`, even when the outcome leaves `qualification_status` unchanged. `REJECTED` entries are never seeded and never receive a lane assignment.

Coaches manage their entries through scratching and unscratching. An `ENTERED` entry scratches while the meet stands in `ENTRIES_OPEN` or `ENTRIES_CLOSED`; a `SEEDED` entry scratches while its event stands in `SEEDED`; from any other configuration the attempt fails with `ERR_ENTRY_NOT_SCRATCHABLE`, including an entry whose event has reached `IN_PROGRESS`, `COMPLETED`, `OFFICIAL`, or `CANCELLED`. Scratching a seeded entry voids its lane assignment — the lane's `lane_status` becomes `VOIDED` — and either scratch recomputes the team's `active_entry_count`. The reverse trip depends on what seeding left behind. Before seeding, a `SCRATCHED` entry unscratches back to `ENTERED` while the meet stands in `ENTRIES_OPEN` or `ENTRIES_CLOSED` and no lane-assignment row exists for it. After seeding, a `SCRATCHED` entry returns directly to `SEEDED` — but only while both the meet and its event stand in `SEEDED` and its `VOIDED` lane assignment still exists, in which case that lane is restored to `ACTIVE` with its original `heat_number` and `lane_number`. Any other configuration fails with `ERR_ENTRY_NOT_UNSCRATCHABLE`, and both flavors of restore recompute `active_entry_count`.

Two terminal facts about the entry axis are worth remembering. `NO_SHOW` is unconditionally terminal once reached (§3.7). And `FINISHED` and `DQ` become immutable the moment the entry's event reaches `OFFICIAL`, because the reopen and disqualification transitions that could move them exist only before publication.

### 3.4. Relay Declarations and Leg Management

Relays enter a meet through declaration, not through the individual-entry path. A `TeamCoach` declares a RelayTeam with `team_id`, the `event_id` of a relay event — one whose `is_relay` flag is true, a declaration against any other event failing with `ERR_INVALID_REQUEST` — a `relay_name` such as "A" or "B" that is unique for that club within that event (uniqueness is enforced against all of the club's relays in that event, scratched ones included, and a duplicate is rejected with `ERR_INVALID_REQUEST`), and an optional `seed_time_cs`. Declaration auto-creates the relay's EventEntry standing `ENTERED` with `UNVERIFIED` qualification and `relay_team_id` populated, records that entry on the relay's `entry_id`, and recomputes the team's `active_entry_count`. The new relay stands `DECLARED`. Declarations obey the same meet-posture and deadline gates as individual entries (`ERR_MEET_NOT_ACCEPTING_ENTRIES`, `ERR_ENTRY_DEADLINE_PASSED`), the declaring team must be active, and the relay's entry flows through the same verification action as any other entry.

Legs are managed while the relay stands `DECLARED`. The coach posts a `leg_number` from one through four together with a `swimmer_id` — a `leg_number` outside that range is rejected with `ERR_INVALID_REQUEST`; posting a `leg_number` that already exists replaces that leg's swimmer, and the write answers `201 Created` whether it adds a new leg or replaces an existing one. Once the relay is `LEGS_LOCKED` or `SCRATCHED`, leg writes fail with `ERR_RELAY_LEGS_LOCKED`. Each leg's swimmer must be an `ACTIVE` member of the relay's own team — a withdrawn club is refused with `ERR_TEAM_NOT_ACTIVE` and a swimmer from another club is refused with `ERR_RELAY_SWIMMER_TEAM_MISMATCH` — must satisfy the relay event's age band (`ERR_AGE_GROUP_INELIGIBLE`) and gender rule exactly as an individual entry would, a `MIXED` event accepting any swimmer (`ERR_GENDER_INELIGIBLE`), and may appear on at most one leg of the relay, duplicates being rejected as `ERR_RELAY_SWIMMER_DUPLICATE`. Relay legs are the system's thin join records: per §2.5 a leg carries only `id` and `created_at`.

Locking certifies the roster. A `DECLARED` relay locks to `LEGS_LOCKED` only when exactly four legs exist (`ERR_RELAY_LEG_COUNT_INCOMPLETE` otherwise), when the relay's own entry has reached `VERIFIED` (`ERR_QUALIFICATION_UNDECIDED` while undecided), and while the relay's event still stands in `PENDING` or `SEEDED` — once the event is underway the lock window has closed (`ERR_RELAY_LOCK_WINDOW_CLOSED`). A lock attempted on a relay no longer `DECLARED` fails with `ERR_RELAY_LEGS_LOCKED`, and the gates fire in a fixed order: the relay's posture, then the event's lock window, then the leg count, then the entry's verification.

A relay scratch removes the whole crew. From `DECLARED` a coach may scratch unconditionally. From `LEGS_LOCKED`, scratching remains possible only while the relay's event stands in `PENDING` or `SEEDED`; once the event is `IN_PROGRESS` or beyond, the attempt fails with `ERR_RELAY_NOT_SCRATCHABLE`. Either scratch cascades: the relay's entry, if `ENTERED` or `SEEDED`, becomes `SCRATCHED`; if that entry was seeded, its lane assignment is `VOIDED`; and the team's `active_entry_count` is recomputed. `SCRATCHED` is terminal for a relay team — scratching an already-`SCRATCHED` relay fails with `ERR_RELAY_NOT_SCRATCHABLE`.

### 3.5. Officials, Certifications, and Deck Coverage

The `MeetDirector` builds the officiating roster by registering each Official with `meet_id`, `full_name`, an `lsc_membership_id` unique within the meet (a duplicate is rejected with `ERR_INVALID_REQUEST`), a `certifications` list drawn from `REFEREE`, `STARTER`, `STROKE_TURN_JUDGE`, and `CHIEF_TIMER`, and a `certification_expires_on` date.

Assignments begin life as proposals. The director proposes an OfficialAssignment with an `official_id` and a `role_on_deck` of `REFEREE`, `STARTER`, `STROKE_TURN_JUDGE`, or `CHIEF_TIMER`, and the row is born `PROPOSED`. Two guards fire at proposal time. First, certification: the official's `certifications` must contain the proposed `role_on_deck`, and `certification_expires_on` must fall on or after the event's `session_date` — a certification expiring exactly on the session date remains valid — with failures rejected as `ERR_CERTIFICATION_INVALID`. Second, double-booking: the official's other assignments on the same `session_date`, whether `PROPOSED` or `CONFIRMED`, must not overlap the event's half-open scheduled window. Because each interval excludes its own end minute, back-to-back assignments whose windows merely touch — one ending exactly when the next begins — are lawful, while genuine overlaps fail with `ERR_OFFICIAL_ASSIGNMENT_CONFLICT`.

Confirmation belongs to the official themself: a `DeckOfficial` or `MeetReferee` whose `X-User-ID` equals the assignment's `official_id` confirms their own assignment, moving it from `PROPOSED` to `CONFIRMED`; confirming an assignment no longer `PROPOSED` fails with `ERR_INVALID_REQUEST`. The double-booking check fires again at confirmation, now measured against the official's `CONFIRMED` assignments only. Release is the director's prerogative: a `PROPOSED` assignment may always be released, while a `CONFIRMED` assignment may be released only while its event stands in `PENDING` or `SEEDED`; once the event is underway, release fails with `ERR_EVENT_ALREADY_UNDERWAY`. `RELEASED` is terminal, and releasing an already-`RELEASED` assignment fails with `ERR_INVALID_REQUEST`.

### 3.6. Closing Entries, Seeding, and the Heat Sheet

Once the entry deadline has passed on the logical clock, the director closes entries, moving the meet from `ENTRIES_OPEN` to `ENTRIES_CLOSED`; §3.1 covers the `ERR_ENTRY_WINDOW_STILL_OPEN` guard. Seeding then converts the decided entry roster into the heat sheet, and it is the first of the two OCC-guarded writes from §2.7: the request must carry `expected_meet_version` matching the meet's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` before any posture check runs. Posture itself requires the meet to stand in `ENTRIES_CLOSED` — seeding from anywhere else fails with `ERR_MEET_NOT_SEEDABLE` — and every entry in the meet must hold a decided qualification, `VERIFIED` or `REJECTED`, because a single `UNVERIFIED` row blocks the write with `ERR_QUALIFICATION_UNDECIDED`.

Seeding processes each event of the meet in `event_number` ascending order. The candidate set for an event is its entries standing in `ENTERED` with qualification `VERIFIED`; `REJECTED` entries are never seeded and receive no lane assignment. An event with no candidates moves straight to `CANCELLED`, its `version` incrementing, and processing continues with the next event. Survivors are sorted by `seed_time_cs` ascending, with `NT` entries placed after all timed entries; ties between equal seed times break by the entry's `created_at`, earliest first, and the entry's `id` is never used as a tie-break.

Heat construction counts the number of heats as the candidate count divided by the meet's `lane_count`, rounded up to a whole number. Heat numbers run from 1 — the slowest heat — up to the highest number, the fastest heat. Filling proceeds fastest-first: the fastest `lane_count` candidates form the highest-numbered heat, the next chunk the heat below it, and so on down to heat 1, which holds the remainder and may run partially filled. Within a heat, lanes are dealt middle-out: the fastest candidate receives the most preferred lane, and preference orders lanes by absolute distance from the pool's midpoint — the midpoint lying at half of one more than `lane_count` — with equidistant pairs resolved in favor of the lower-numbered lane. Under the default six-lane pool the preference order is lane 3, then 4, then 2, then 5, then 1, then 6; in an eight-lane pool it runs 4, 5, 3, 6, 2, 7, 1, 8.

Each seeded candidate's entry moves from `ENTERED` to `SEEDED`, and the system creates its LaneAssignment with `lane_status` `ACTIVE` and `reconciliation_status` `PENDING_READINGS`, stamped with the dealt `heat_number` and `lane_number`. When every event has been processed, seeded events stand `SEEDED` with incremented versions, empty events stand `CANCELLED`, and the meet itself moves to `SEEDED` with its `version` incremented. From this point the meet's `scoring_tie_policy` is frozen. The heat sheet itself is a computed read over this state, returning the `event_id` and a `heats` array grouping the event's seeded lane assignments by heat: only `ACTIVE` lane assignments appear, each heat entry carries its `heat_number` and a `lanes` array sorted by `lane_number` ascending, the heats are ordered by `heat_number` ascending, and an event with no active seeded lanes yields an empty `heats` array.

Reopening is the escape hatch for late corrections, moving the meet from `SEEDED` back to `ENTRIES_OPEN`. It is lawful only while no event of the meet has reached `IN_PROGRESS`, `COMPLETED`, or `OFFICIAL` — otherwise `ERR_EVENTS_ALREADY_UNDERWAY` — and it is destructive by design: every lane assignment of the meet is hard-deleted; every `SEEDED` entry returns to `ENTERED` while `SCRATCHED` entries stay scratched; every `SEEDED` event returns to `PENDING` with its `version` incrementing, while `CANCELLED` events remain cancelled; and `entry_deadline_utc` is replaced with the supplied `new_entry_deadline_utc`. The meet's `version` increments as with any lifecycle step — which is exactly why a stale `expected_meet_version` cannot survive a reopen-and-close cycle.

### 3.7. Running Events: Timing, Reconciliation, and No-Shows

Starting a race is the director's call and moves the event from `SEEDED` to `IN_PROGRESS`. Three gates apply: the meet must stand in `SEEDED` (`ERR_MEET_NOT_SEEDED`); the event itself must stand in `SEEDED`, so starting a `PENDING` or `CANCELLED` event fails with `ERR_EVENT_NOT_SEEDED`; and deck coverage must be complete — at least one `CONFIRMED` assignment with `role_on_deck` `REFEREE` and at least one `CONFIRMED` assignment with `role_on_deck` `STROKE_TURN_JUDGE` must exist for the event, failing which the start is refused with `ERR_OFFICIAL_COVERAGE_INCOMPLETE`. A started event's `version` increments.

While the event runs, the `MeetReferee` may mark a seeded entry as a no-show, moving it from `SEEDED` to the unconditionally terminal `NO_SHOW`; the entry's lane is `VOIDED` and the team's `active_entry_count` recomputed. Marking outside an `IN_PROGRESS` event fails with `ERR_EVENT_NOT_IN_PROGRESS`, as does marking an entry not standing `SEEDED`.

Timing capture belongs to the `TimingOperator`. Each lane assignment accumulates up to four readings: `pad_cs` from the primary touchpad, `backup1_cs` and `backup2_cs` from the two backup buttons, and `watch_cs` from the manual stopwatch, the tertiary source. Every submission must carry at least one of the four, or it fails with `ERR_INVALID_REQUEST`; the lane must be `ACTIVE` (`ERR_LANE_VOIDED` rejects readings on a voided lane); and the event must be `IN_PROGRESS` (`ERR_EVENT_NOT_IN_PROGRESS`). The operator may also supply `pad_status` — `VALID`, `INVALID`, or `UNKNOWN`, defaulting to `UNKNOWN` — to flag a touchpad malfunction. Readings may be submitted whenever the lane is `ACTIVE` and the event `IN_PROGRESS`, regardless of the lane's current `reconciliation_status`; each submission merges into the lane's accumulated readings and re-runs the auto-confirm evaluation below, settling the lane `AUTO_CONFIRMED` or `MANUAL_REVIEW` afresh.

Reconciliation begins the moment readings arrive. The **backup mean** is computed by averaging `backup1_cs` and `backup2_cs` and rounding the mean half-up to a whole centisecond, and this rounding happens **first**, before any comparison: the delta check below uses the rounded value, and any final time always copies an already-integer source without a second rounding. The ordering is load-bearing. Consider a pad reading of 2543 centiseconds with backups of 2510 and 2515: the raw mean is 2512.5, which sits 30.5 centiseconds from the pad and would exceed a 30-centisecond threshold, but the rounded mean is 2513, which sits exactly 30 away — at the threshold, not beyond it — so the lane auto-confirms. The rounded-first reading is authoritative.

A submission auto-confirms — moving the lane from `PENDING_READINGS` to `AUTO_CONFIRMED` — when all of the following hold: the pad reading is present, `pad_status` is not `INVALID`, both backups are present, and the absolute difference between `pad_cs` and the rounded backup mean does not exceed the meet's `timing_delta_threshold_cs`. An auto-confirmed lane records `reconciled_variant` `PRIMARY_PRIORITY` and copies `pad_cs` into `final_time_cs`. Any submission falling short of those conditions — pad missing or flagged `INVALID`, a backup absent, or the delta strictly greater than the threshold — parks the lane in `MANUAL_REVIEW` with `final_time_cs` still null.

A lane in `MANUAL_REVIEW` is settled by the operator choosing a reconciliation `variant`. Under `PRIMARY_PRIORITY`, the first available source wins in this order: the pad reading if present and not flagged `INVALID`; then the rounded backup mean if both backups are present; then `backup1_cs`; then `backup2_cs`; then `watch_cs`. Under `BACKUP_MEAN_PRIORITY`, the rounded backup mean leads — when both backups exist — followed by the pad reading if present and valid, then `backup1_cs`, `backup2_cs`, and finally `watch_cs`. Identical readings therefore yield a different `final_time_cs` under the two variants whenever the pad and the rounded backup mean disagree. The chosen chain always yields a time, because the readings requirement guarantees at least one value exists somewhere on it. Resolving moves the lane to `RESOLVED`, records the chosen `variant` in `reconciled_variant`, computes `final_time_cs` from the chain, and applies an optionally supplied `pad_status` update — the update landing **before** the chain is walked, so flagging the pad `INVALID` in the resolve request itself removes the pad from consideration for this resolution. Resolution, like readings, requires the event to be `IN_PROGRESS`, and a resolve attempted on a lane not standing `MANUAL_REVIEW` fails with `ERR_LANE_NOT_RECONCILED`.

The `MeetReferee` holds the timing veto: reopening a lane's timing returns it from `RESOLVED` or `AUTO_CONFIRMED` to `MANUAL_REVIEW`, clearing both `final_time_cs` and `reconciled_variant` to null, and is lawful only while the event remains `IN_PROGRESS` (`ERR_EVENT_NOT_IN_PROGRESS`); reopening a lane standing anywhere else fails with `ERR_LANE_NOT_RECONCILED`. Note that `lane_status` runs on a parallel dimension from `reconciliation_status`: a lane flips from `ACTIVE` to `VOIDED` on scratch, no-show, and withdrawal cascades, and returns from `VOIDED` to `ACTIVE` only through the seeded unscratch restore of §3.3.

### 3.8. Disqualifications: From the Call to the Ruling

A disqualification begins on deck. A `DeckOfficial` records a call against a specific lane assignment — identified in the payload as `lane_assignment_id` — supplying a `dq_code` of `FALSE_START`, `FLY_ARMS_ALTERNATING`, `BACK_FINISH_NOT_ON_BACK`, `BR_KICK_DOWNWARD_WHIP`, `IM_ORDER_VIOLATION`, `TURN_NO_TOUCH`, or `RELAY_EARLY_TAKEOFF`, together with free-text `call_notes`. Four gates guard the recording. The lane's `reconciliation_status` must be `AUTO_CONFIRMED` or `RESOLVED` (`ERR_LANE_NOT_RECONCILED`); the event must stand in `IN_PROGRESS` or `COMPLETED` (`ERR_EVENT_NOT_IN_PROGRESS`); no other non-terminal disqualification may already exist on the same lane (`ERR_DQ_ALREADY_ACTIVE`); and the caller's `X-User-ID` must belong to an Official of this meet holding a `CONFIRMED` `STROKE_TURN_JUDGE` assignment on this event (`ERR_INSUFFICIENT_PERMISSIONS`). A recorded call stands in `RECORDED`, with `reporting_official_id` taken from the caller's `X-User-ID`.

Notification comes next: the `MeetReferee` marks the call `RECORDED` → `COACH_NOTIFIED`, stamping `notified_at` with the current logical-clock reading. From there the coach's clock starts. A `TeamCoach` may protest, moving the call to `PROTESTED`, provided the logical clock has not advanced beyond `notified_at` plus the meet's `dq_protest_window_minutes` — a protest landing exactly at the window's end is still accepted, and anything later fails with `ERR_PROTEST_WINDOW_EXPIRED`.

Rulings belong to the `MeetReferee` and always under segregation of duties: the confirming, upholding, or overturning referee's `X-User-ID` must differ from `reporting_official_id`, with violations rejected as `ERR_SEGREGATION_OF_DUTY`, and the ruling referee's identity is recorded in `resolved_by_referee_id`, which therefore always differs from `reporting_official_id`. An unprotested call is confirmed once its protest window has fully elapsed — the logical clock must have advanced strictly past `notified_at` plus `dq_protest_window_minutes`, and an attempt earlier fails with `ERR_PROTEST_WINDOW_OPEN` — moving `COACH_NOTIFIED` → `CONFIRMED`. A protested call is either upheld (`PROTESTED` → `UPHELD`) and then confirmed (`UPHELD` → `CONFIRMED`), or overturned (`PROTESTED` → `OVERTURNED`). `CONFIRMED` and `OVERTURNED` are terminal, and any transition attempted from a posture that forbids it — confirming straight from `RECORDED`, or protesting an already-`PROTESTED` call — fails with `ERR_DQ_INVALID_STATE`.

Confirmation detonates a four-level cascade. The Disqualification itself settles at `CONFIRMED`; the EventEntry tied to the sanctioned lane moves to `DQ` — from `SEEDED` when the event has not yet completed, or from `FINISHED` after completion. If the event is already `COMPLETED`, that entry's Result is rewritten to `DQ_EXCLUDED` with its `place` set to null, its `final_time_cs` set to null, and its `points` to 0.00, and the event is re-scored: the surviving `FINISHED` entries are re-placed from first through last and their points recomputed per the scoring rules of §3.9. The `provisional_points` of every affected team are then recomputed, and whenever a rescore occurs the event's `version` increments.

Overturning runs the mirror cascade. The Disqualification settles at `OVERTURNED`; the entry returns from `DQ` to `FINISHED`, but only when the disqualification had actually been confirmed — overturning a call that never reached confirmation leaves the entry's status untouched. If the event is `COMPLETED`, the event is re-scored with the restored time back in the ranking; `provisional_points` is recomputed for the affected teams; and the event's `version` increments on the rescore.

### 3.9. Scoring, Publication, Records, and Meet Completion

Completing an event is the second OCC-guarded write of §2.7: the request carries `expected_event_version` matching the event's current `version`, with mismatches rejected as `ERR_STALE_VERSION` before the posture checks. The event must stand in `IN_PROGRESS`, and every lane assignment whose `lane_status` is `ACTIVE` must have reached `AUTO_CONFIRMED` or `RESOLVED` — a single unreconciled lane blocks completion with `ERR_UNRESOLVED_LANES_EXIST`. Completion then scores the race. A Result row is created for every entry that finished the race: entries whose swims are clean are created in `UNOFFICIAL`, while entries already carrying a confirmed disqualification are created directly in `DQ_EXCLUDED` with a null `place`, a null `final_time_cs`, and `points` of 0.00; scratched and no-show entries produce no Result row; an entry restored to `FINISHED` by a pre-completion overturn (§3.8) and still without a Result receives an `UNOFFICIAL` row copying its lane's reconciled figure. Each Result copies its `final_time_cs` from the lane's reconciled figure and denormalizes the `team_id` from the swimmer's or relay's club alongside its `entry_id` and `event_id`. Scored entries move from `SEEDED` to `FINISHED`, the `provisional_points` of every team with entries in the event are recomputed, and the event's `version` increments.

Places and points follow a single ranking discipline. The scored set is the event's `FINISHED` entries with non-null `final_time_cs`, ordered fastest first; the lane assignment's `created_at` orders the display between equal times but never the ranking, because identical times **always** tie for place. Ranking follows competition rules: equal times share the same place, and the place awarded to the next distinct time advances by the size of the tie — two swimmers tied for second are both placed second, and the next distinct finisher is placed fourth. Entries in `DQ`, `NO_SHOW`, or `SCRATCHED` are excluded entirely. The base points for a place come from the meet's `points_table`, counting its first element as first place; places deeper than the table's length earn zero. Ties are settled by the meet's `scoring_tie_policy`. Under `SPLIT`, each member of a tied group of size k at place p receives the sum of the base points across the k places the tie covers, divided by k, rounded half-up to two decimal places — a two-way tie at second under the default table splits seven and six, yielding 6.50 points each. Under `TOP`, each tied result receives the base points of the place at which the tie occurred — the same tie pays 7.00 each — while the following place still advances by the size of the tie. For relay events, the result's points are multiplied by the meet's `relay_points_multiplier` after tie handling, with the product rounded half-up to two decimal places. A non-tied, non-relay result simply earns its place's base points rendered at two decimal places. A result's `place` and `points` are null and 0.00 respectively whenever the row stands `DQ_EXCLUDED`.

Team totals roll up from results and are always recomputed from the rows, never adjusted incrementally. A team's `provisional_points` are the sum of `points` across **all** of its Result rows — `UNOFFICIAL` and `OFFICIAL` alike, with `DQ_EXCLUDED` rows contributing 0.00 — rounded half-up to two decimal places; its `official_points` are the same sum restricted to `OFFICIAL` rows only. The recomputation fires at event completion, event reopen, disqualification-driven rescores, and publication, and the team's `version` increments whenever the figure changes.

Publication and reopening bracket the official window. The director publishes a `COMPLETED` event — the requirement failing with `ERR_EVENT_NOT_COMPLETED` from any other posture — but only once every disqualification on the event's lane assignments has reached `CONFIRMED` or `OVERTURNED`; a live call blocks publication with `ERR_DQ_NOT_TERMINAL`. Publication promotes every `UNOFFICIAL` Result to `OFFICIAL`, recomputes `official_points` for every team holding official results in the event, runs the record-challenge check below, and increments the event's `version`. The referee's reopen runs the other way: from `COMPLETED` back to `IN_PROGRESS`, hard-deleting all of the event's Result rows, returning `FINISHED` entries to `SEEDED` while `DQ` entries stay disqualified, recomputing the affected teams' `provisional_points`, and incrementing the event's `version`.

Record challenges fire only at publication. The standing record for an event is its MeetRecord in `CURRENT` status — zero or one exists. Challengers are the event's `OFFICIAL`, non-`DQ_EXCLUDED` results whose `final_time_cs` is strictly faster than the standing record's `record_time_cs`; a time exactly equal to the record does not break it. When a standing record exists and at least one challenger beats it, publication auto-creates exactly one MeetRecord in `PENDING_VERIFICATION`: its `record_time_cs` is the fastest challenger time — ties among equal fastest challenger times breaking by the challenging result's `created_at`, earliest first — its holder is that result's swimmer `full_name` or, for a relay, the relay team's `relay_name`, its `holder_team` is the club's `team_code`, its `set_on_date` is the event's `session_date`, and its `challenger_entry_id` points at the challenging entry. With no standing record, publication creates nothing — record-keeping starts from explicit standing-record creation. A per-entry results read returns the zero-or-one Result belonging to an entry as an `array` envelope holding zero or one Result objects.

The `RecordsOfficer` administers the record book. A standing record is created explicitly against an event with `record_time_cs`, `holder_name`, `holder_team`, and `set_on_date`, and is born `CURRENT` with a null `challenger_entry_id` — but only while no `CURRENT` record exists for that event, or the creation fails with `ERR_RECORD_STANDING_EXISTS`. Challenges follow `PENDING_VERIFICATION` → `SUBMITTED` on verification, and `SUBMITTED` → `CURRENT` on ratification; ratification supersedes the prior `CURRENT` record of the same event to `SUPERSEDED` and auto-rejects any slower still-pending challenges for that event to `REJECTED`. At most one challenge exists per event at a time, because publication fires once per event. Rejection moves a `PENDING_VERIFICATION` or `SUBMITTED` record to `REJECTED`. `SUPERSEDED` and `REJECTED` are terminal, and a record transition attempted from a posture that forbids it fails with `ERR_RECORD_INVALID_STATE`.

Two final gates close the meet. Completing the meet moves it from `SEEDED` to `COMPLETED` and requires every event of the meet to stand in `OFFICIAL` or `CANCELLED`; anything short fails with `ERR_EVENTS_NOT_OFFICIAL`. Finalizing moves from `COMPLETED` to `OFFICIAL` and requires that no record of the meet remain in `PENDING_VERIFICATION` or `SUBMITTED`; pending records block finalization with `ERR_RECORDS_PENDING`. Each step increments the meet's `version`, and `OFFICIAL` is the meet's terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every lifecycle transition, ruling, and reconciliation write — return `200 OK`. Request and response payloads for each operation are defined by the workflows of §3; this table is an index of method, path, purpose, and authorized roles only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/meets` | Create a meet | MeetDirector |
| GET | `/meets/{id}` | Get a meet | Any |
| POST | `/meets/{id}/open-entries` | Open entries: `SETUP` → `ENTRIES_OPEN` | MeetDirector |
| POST | `/meets/{id}/close-entries` | Close entries once the deadline has passed | MeetDirector |
| POST | `/meets/{id}/seed` | Generate the heat sheet for all events (OCC-guarded) | MeetDirector |
| POST | `/meets/{id}/reopen-entries` | Return to `ENTRIES_OPEN`, wiping lane assignments | MeetDirector |
| POST | `/meets/{id}/complete` | Complete the meet once all events are final | MeetDirector |
| POST | `/meets/{id}/finalize` | Move the meet to `OFFICIAL` once records are settled | MeetDirector |
| POST | `/teams` | Register a team | MeetDirector |
| GET | `/teams/{id}` | Get a team | Any |
| GET | `/teams` | List teams | Any |
| POST | `/teams/{id}/withdraw` | Withdraw a team and cascade its entries | MeetDirector |
| POST | `/swimmers` | Register a swimmer | TeamCoach |
| GET | `/swimmers/{id}` | Get a swimmer | Any |
| GET | `/swimmers` | List swimmers | Any |
| POST | `/events` | Create an event | MeetDirector |
| GET | `/events/{id}` | Get an event | Any |
| GET | `/events` | List events | Any |
| POST | `/events/{id}/start` | Start an event: `SEEDED` → `IN_PROGRESS` | MeetDirector |
| POST | `/events/{id}/complete` | Complete an event and score results (OCC-guarded) | MeetDirector |
| POST | `/events/{id}/reopen` | Reopen a completed event, deleting its results | MeetReferee |
| POST | `/events/{id}/publish` | Publish results and run record challenges | MeetDirector |
| GET | `/events/{id}/heat-sheet` | Computed heat sheet: seeded lanes grouped by heat | Any |
| GET | `/events/{id}/results` | List results for an event | Any |
| GET | `/events/{id}/official-assignments` | List official assignments for an event | Any |
| GET | `/events/{id}/records` | List records for an event | Any |
| POST | `/entries` | Create an individual entry | TeamCoach |
| GET | `/entries/{id}` | Get an entry | Any |
| GET | `/entries` | List entries | Any |
| POST | `/entries/{id}/verify` | Verify or reject the entry's qualifying time | MeetDirector |
| POST | `/entries/{id}/scratch` | Scratch an entry, freeing its lane | TeamCoach |
| POST | `/entries/{id}/unscratch` | Restore a scratched entry | TeamCoach |
| POST | `/entries/{id}/mark-no-show` | Mark a seeded entry as a no-show | MeetReferee |
| GET | `/entries/{id}/result` | Get the zero-or-one result for an entry | Any |
| POST | `/relay-teams` | Declare a relay team, auto-creating its entry | TeamCoach |
| GET | `/relay-teams/{id}` | Get a relay team | Any |
| GET | `/relay-teams` | List relay teams | Any |
| POST | `/relay-teams/{id}/legs` | Add or replace a relay leg | TeamCoach |
| GET | `/relay-teams/{id}/legs` | List the legs of a relay team | Any |
| GET | `/relay-legs/{id}` | Get a relay leg | Any |
| GET | `/relay-legs` | List relay legs | Any |
| POST | `/relay-teams/{id}/lock` | Lock the four-leg roster | TeamCoach |
| POST | `/relay-teams/{id}/scratch` | Scratch a relay team and its entry | TeamCoach |
| GET | `/lane-assignments/{id}` | Get a lane assignment | Any |
| GET | `/lane-assignments` | List lane assignments | Any |
| POST | `/lane-assignments/{id}/readings` | Submit timing readings; auto-confirm or park for review | TimingOperator |
| POST | `/lane-assignments/{id}/resolve` | Resolve a lane under review with a chosen variant | TimingOperator |
| POST | `/lane-assignments/{id}/reopen-timing` | Reopen a settled lane's timing | MeetReferee |
| GET | `/lane-assignments/{id}/disqualifications` | List disqualifications on a swim | Any |
| GET | `/teams/{id}/results` | List results for a team | Any |
| POST | `/officials` | Roster an official | MeetDirector |
| GET | `/officials/{id}` | Get an official | Any |
| GET | `/officials` | List officials | Any |
| POST | `/events/{id}/official-assignments` | Propose an official assignment | MeetDirector |
| GET | `/official-assignments/{id}` | Get an official assignment | Any |
| GET | `/official-assignments` | List official assignments | Any |
| POST | `/official-assignments/{id}/confirm` | Assigned official confirms their own assignment | DeckOfficial, MeetReferee |
| POST | `/official-assignments/{id}/release` | Release an assignment | MeetDirector |
| POST | `/lane-assignments/{id}/disqualifications` | Record a disqualification call on a swim | DeckOfficial |
| GET | `/disqualifications/{id}` | Get a disqualification | Any |
| GET | `/disqualifications` | List disqualifications | Any |
| POST | `/disqualifications/{id}/notify-coach` | Mark the coach notified | MeetReferee |
| POST | `/disqualifications/{id}/protest` | Protest a notified call within the window | TeamCoach |
| POST | `/disqualifications/{id}/confirm` | Confirm a call, detonating the scoring cascade | MeetReferee |
| POST | `/disqualifications/{id}/uphold` | Uphold a protested call | MeetReferee |
| POST | `/disqualifications/{id}/overturn` | Overturn a protested call, restoring the swim | MeetReferee |
| POST | `/events/{id}/records` | Create the standing record for an event | RecordsOfficer |
| GET | `/records/{id}` | Get a record | Any |
| GET | `/records` | List records | Any |
| POST | `/records/{id}/verify` | Move a challenge to `SUBMITTED` | RecordsOfficer |
| POST | `/records/{id}/ratify` | Ratify a challenge as the standing record | RecordsOfficer |
| POST | `/records/{id}/reject` | Reject a pending challenge | RecordsOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock | Any |

## 5. Error Code Catalogue

Trigger conditions for each error live with the rules that raise them in §2 and §3; this catalogue enumerates identifiers and status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTY` | 403 Forbidden |
| `ERR_MEET_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_SWIMMER_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_RELAY_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_LANE_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFICIAL_NOT_FOUND` | 404 Not Found |
| `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISQUALIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEET_NOT_ACCEPTING_ENTRIES` | 409 Conflict |
| `ERR_ENTRY_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_MEET_NOT_SEEDABLE` | 409 Conflict |
| `ERR_MEET_NOT_SEEDED` | 409 Conflict |
| `ERR_EVENTS_ALREADY_UNDERWAY` | 409 Conflict |
| `ERR_EVENTS_NOT_OFFICIAL` | 409 Conflict |
| `ERR_MEET_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_EVENT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_EVENT_ALREADY_UNDERWAY` | 409 Conflict |
| `ERR_ENTRY_NOT_SCRATCHABLE` | 409 Conflict |
| `ERR_ENTRY_NOT_UNSCRATCHABLE` | 409 Conflict |
| `ERR_LANE_VOIDED` | 409 Conflict |
| `ERR_DQ_NOT_TERMINAL` | 409 Conflict |
| `ERR_DQ_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DQ_INVALID_STATE` | 409 Conflict |
| `ERR_RELAY_LEG_COUNT_INCOMPLETE` | 409 Conflict |
| `ERR_RELAY_LEGS_LOCKED` | 409 Conflict |
| `ERR_RELAY_LOCK_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RELAY_NOT_SCRATCHABLE` | 409 Conflict |
| `ERR_RELAY_SWIMMER_DUPLICATE` | 409 Conflict |
| `ERR_RELAY_SWIMMER_TEAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RECORD_INVALID_STATE` | 409 Conflict |
| `ERR_RECORD_STANDING_EXISTS` | 409 Conflict |
| `ERR_RECORDS_PENDING` | 409 Conflict |
| `ERR_ENTRY_DEADLINE_PASSED` | 409 Conflict |
| `ERR_PROTEST_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_PROTEST_WINDOW_OPEN` | 409 Conflict |
| `ERR_CERTIFICATION_INVALID` | 422 Unprocessable Entity |
| `ERR_AGE_GROUP_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_GENDER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_TEAM_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_SWIMMER_ENTRY_LIMIT` | 409 Conflict |
| `ERR_RECOVERY_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_OFFICIAL_ASSIGNMENT_CONFLICT` | 409 Conflict |
| `ERR_OFFICIAL_COVERAGE_INCOMPLETE` | 409 Conflict |
| `ERR_QUALIFICATION_UNDECIDED` | 409 Conflict |
| `ERR_UNRESOLVED_LANES_EXIST` | 409 Conflict |
| `ERR_LANE_NOT_RECONCILED` | 409 Conflict |
| `ERR_EVENT_NOT_SEEDED` | 409 Conflict |
| `ERR_EVENT_NOT_COMPLETED` | 409 Conflict |
| `ERR_MEET_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_NOT_VERIFIABLE` | 409 Conflict |
