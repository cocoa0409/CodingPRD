# Race Timing Results API — Product Requirements Document

## 1. Introduction

A race timing company is the evidentiary backbone of a competitive running event. Its responsibilities span the entire competitive timeline: athletes register and receive bibs and timing chips; mats are deployed at the start, at intermediate splits, and at the finish; every chip crossing is recorded; standings are derived on both a gun-time and a chip-time basis; age-group and overall awards are allocated; integrity threats such as did-not-finish, disqualification, and course-cutting are surveilled; disputes are heard inside a protest window; results are corrected and republished when warranted; and qualifying events are formally certified. Each of these steps leaves an audit trail that must survive scrutiny from athletes, race juries, and sanctioning bodies.

This document specifies the Race Timing Results API, mounted under `/race-timing`. Its central design premise is that results are never edited in place — they are re-derived. The append-only log of chip reads is the single source of truth, and every published standing, ranking, award, and qualification flag is a projection recomputed from that log. When a correction is approved, one read mutates and everything downstream is replayed: results, ranks, awards, race status, and even certification. Because disputes and corrections are unavoidable in live sport, the API hard-codes a thirty-minute protest window, an amendment loop that re-opens finalized races, and strict segregation of duties between the people who file disputes, the officials who resolve them, the director who locks the timing configuration, and the officer who certifies the outcome. All temporal rules — cutoffs, windows, deployment schedules — are evaluated against a controllable server-side logical clock, never the host wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to each operation is restricted by role; a caller whose role is not on an endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows. A `RaceDirector` owns the event lifecycle: race setup, the registration window, the timing lock, and result publication and finalization. A `TimingOperator` places mats, manages timing points, starts waves, and ingests chip reads. A `RegistrationClerk` runs registration intake, payments, bib and chip assignment, withdrawals, and files protests on behalf of participants. A `RaceOfficial` acts as referee and jury: raising and resolving result flags, resolving protests, and filing and adjudicating corrections. A `CertificationOfficer` issues certification for qualifying events and, per the segregation rule of §2.9, must never be the user who locked timing. A `Spectator` is a public viewer with read-only access to race detail, the live board, results, awards, and certifications.

For every one of these roles — `RaceDirector`, `TimingOperator`, `RegistrationClerk`, `RaceOfficial`, `CertificationOfficer`, and `Spectator` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on resources (for example as `locked_by_user_id` on a race, `filed_by_user_id` on a protest, `resolved_by_user_id` on a resolved protest, `adjudicated_by_user_id` on a correction, or `issued_by_user_id` on a certification), but it never compares `X-User-ID` against any entity's `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every deadline, cutoff, window, and stamp described in this document is evaluated against a server-maintained logical clock — never the host machine's wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A test-driving capability, available to all five staff roles (`RaceDirector`, `TimingOperator`, `RegistrationClerk`, `RaceOfficial`, `CertificationOfficer`) but not to `Spectator`, sets the clock to a caller-supplied `to_iso8601` instant and answers with the resulting `current_utc`. Window and cutoff comparisons use second-precision logical time, while device-stamped chip reads carry millisecond precision.

### 2.5. Common Resource Properties and the Append-Only Read Log

All primary resources — races, waves, timing points, registrations, chips, results, result flags, protests, corrections, certifications, and awards — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed counter that increments by one on every modification of the resource. It is the basis of the optimistic concurrency rule in §2.8.

Timing reads are the deliberate exception. The **TimingRead** log is append-only: a read carries only `id` and `created_at`; both `updated_at` and `version` are absent. Reads are created by ingest, are never deleted, and any later change to a read happens only through the correction mechanics of §3.7, never through a direct update.

### 2.6. Time Units, Precision, and Rounding

Durations and thresholds of record — `chip_time_ms`, `gun_time_ms`, `basis_time_ms`, and `qualifying_standard_ms` — are integer milliseconds and are never rounded. Ranks and award places are integers forming gap-free sequences starting at 1. Ages are integer years. The live results feed (§3.9) works in integer seconds, applying round-half-up at each pinned step of its projection; the exact rounding order is part of its specification. Course distances are expressed in kilometers as numbers.

### 2.7. Request Validation Pipeline

Every mutating request passes through a fixed validation pipeline, and the first failing stage produces the response. The stages run in this order: first authentication (the headers of §2.1), then role authorization, then existence of every referenced identifier per §2.10, then state-transition legality — immediately followed by the race-phase gates that close registration intake, freeze the timing configuration, and govern read ingest and flag handling — then optimistic concurrency where §2.8 applies, then segregation of duties per §2.9, then temporal business rules such as the protest window, the race cutoff, wave spacing, and device deployment windows, then structural constraints such as uniqueness and chip availability, then referential integrity of the dockets, and finally capacity and payment rules. Where several checks within one stage guard the same operation, §3 states their relative order explicitly alongside the workflow they protect.

### 2.8. Optimistic Concurrency Control on the Race

Two write operations carry an optimistic-concurrency obligation: publishing (or re-publishing) results, and adjudicating a correction. Each of these requests must include `expected_race_version`, a non-optional field carrying the race `version` the client last observed. If the race's current `version` has advanced beyond that observed value — for example because a correction was adjudicated, or results were published, since the client's last read — the request is rejected with `ERR_STALE_RACE_VERSION` (HTTP 412), preventing the client from acting on a view of the race it has not observed. No other endpoint accepts a version field; all other mutations execute without a concurrency token.

### 2.9. Segregation of Duties

Two duties are deliberately split across different people. First, the official who resolves a protest must not be the clerk who filed it: protest resolution requires the acting `X-User-ID` to differ from the protest's recorded `filed_by_user_id`. Second, the officer who certifies a finalized race must not be the director who locked its timing configuration: certification requires the acting `X-User-ID` to differ from the race's `locked_by_user_id`. A violation of either rule is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.10. Referenced Resource Existence and Resolution Order

All resources in this API are peers linked by reference fields rather than nested creation URLs. Every identifier appearing in a request — each variable in the path and every `*_id` field in the body — must resolve to an existing resource. Resolution proceeds left to right, validating path identifiers first and body identifiers afterwards; the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404). Beyond mere existence, cross-resource references must be coherent: the wave named on a registration must belong to the race named on the same payload, and the read named on a protest or correction must belong to that operation's race. Coherence failures of this kind are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.11. Derived Standings and Immediate Consistency

The chip-read log is the system's ledger of fact; results, rankings, awards, and qualification flags are projections derived from it. Three events recompute those projections for the whole race, always synchronously inside the triggering request: publishing results, approving a correction, and confirming a result flag. Two cascade shapes recur throughout §3 — the correction cascade (read mutation, then recompute, then award swaps, then the race re-opening for amendment, then certification revocation) and the flag cascade (result exclusion followed by rank and award recompute) — and §3.7 details both. Every mutation in the system commits atomically within its request; there is no eventual consistency anywhere in this API.

## 3. Business Logic & Workflows

### 3.1. Race Setup: Waves and the Timing-Point Layout

A `RaceDirector` opens a new event by creating a **Race** with a display `name`, the scheduled `race_date`, the course `distance_km` in kilometers (which must be greater than zero), a `course_type` of either `CERTIFIED_COURSE` or `UNCERTIFIED_COURSE`, and a `course_time_limit_minutes` cutoff (also greater than zero). An optional `qualifying_standard_ms`, expressed in milliseconds, marks the race as a qualifying event; when it is absent, no qualification flags are computed. A new race starts in `DRAFT` with `amendment_count` at zero, and every lifecycle stamp — `timing_locked_at`, `provisional_published_at`, `protest_window_closes_at`, and `finalized_at` — is null, as are `locked_by_user_id` and the `timing_config_fingerprint`. Opening registration moves the race `DRAFT → REGISTRATION_OPEN`.

Waves structure the start. A `RaceDirector` creates each **Wave** with the `race_id` it belongs to, a `wave_index` start ordinal of at least 1, a `scheduled_start_time`, and a `max_capacity` greater than zero; the wave begins `SCHEDULED`, and its `actual_start_time` stays null until the wave is started. Two constraints guard creation, with the spacing rule evaluated first: the new `scheduled_start_time` must sit at least `WAVE_GAP_MINUTES` away from the scheduled start of every other wave of the same race — the absolute difference is compared, and equality is allowed — otherwise creation fails with `ERR_WAVE_SPACING_VIOLATION`. Only then is uniqueness checked: the `wave_index` must not already be used by another wave of the race, on pain of `ERR_WAVE_INDEX_TAKEN`.

A `TimingOperator` lays out the course with **TimingPoint** records, each carrying the `race_id`, a `point_index` course ordinal of at least 1, a `kind` of `START`, `SPLIT`, or `FINISH`, the `distance_km` from the start, the physical mat's `device_id`, and a deployment window running from `deploy_at` (inclusive) to `expected_teardown_at` (exclusive). New points start `PLANNED`. Within a race, the `point_index` is unique and must strictly increase with `distance_km`; a `START` point sits at distance zero, the `FINISH` point at exactly the race's `distance_km`, and every `SPLIT` strictly in between. Three checks guard timing-point creation, evaluated in this order — device scheduling, then window shape, then the configuration freeze. The deployment windows of any single `device_id` must never overlap across timing points: the windows are half-open, so one window's teardown at exactly the instant another begins is permitted, and any true overlap is rejected with `ERR_DEVICE_WINDOW_OVERLAP`. The window must be well-formed, with `expected_teardown_at` later than `deploy_at`, otherwise `ERR_INVALID_REQUEST`. And once the race's timing configuration is locked, creation is rejected with `ERR_TIMING_CONFIG_LOCKED`. Deploying the point addressed by `point_id` moves it `PLANNED → DEPLOYED`, and a point may also be deleted outright — but creation, deployment, and deletion are all permitted only while the race sits in `DRAFT` or `REGISTRATION_OPEN`; the same freeze rejects all three with `ERR_TIMING_CONFIG_LOCKED` afterwards.

### 3.2. Registration Intake: Payment, Confirmation, and Withdrawal

A `RegistrationClerk` registers a participant with a payload naming the `race_id`, the target `wave_id` (which must belong to that race), a `bib_number`, the `participant_name`, the `birth_date` as a year-month-day string, and a `gender` of `M` or `F`. Intake is gated on the race sitting in `REGISTRATION_OPEN`, and the identical gate covers payment and confirmation; it is evaluated before the uniqueness and capacity checks, so a closed race surfaces `ERR_RACE_REGISTRATION_CLOSED` rather than a later failure. The `bib_number` must be unique across every registration of the race in any lifecycle state — even a withdrawn athlete's bib stays retired — and a collision fails with `ERR_BIB_NUMBER_TAKEN`. Finally, wave occupancy is enforced: the number of registrations in the wave in any state other than `WITHDRAWN` must remain below the wave's `max_capacity`, and a full wave rejects with `ERR_WAVE_CAPACITY_FULL`.

Two attributes are computed at creation and never edited afterwards. `age_on_race_day` is the athlete's age in full years on the race date: the difference between the race year and the birth year, reduced by one when the race date's month and day fall earlier in the calendar than the birth month and day. The `birth_date` itself must fall strictly before the race's `race_date`. From that age, the `age_group` bracket label is derived: athletes younger than 20 fall into `1-19`; athletes 80 or older fall into `80+`; everyone else is placed in the five-year bracket beginning at the largest multiple of five that does not exceed their age, labeled with its lower and upper bounds — a 34-year-old lands in `30-34`. The boundaries are exact: an athlete who is exactly 20 on race day belongs to `20-24`, not `1-19`, and an athlete who is exactly 80 belongs to `80+`, not `75-79`. The bracket also names the athlete's award category: the prefix AG, the gender, and the bracket label with its dash replaced by an underscore, joined by underscores — `AG_F_30_34` for a 34-year-old woman.

A registration evolves along two independent dimensions. Its `lifecycle_status` begins at `REGISTERED`; its `payment_status` begins at `UNPAID`; and it holds no chip, with `chip_id` null. Recording a payment moves the payment dimension `UNPAID → PAID`, allowed for any registration that is not `WITHDRAWN` while the race remains in `REGISTRATION_OPEN`. Confirmation moves the lifecycle dimension `REGISTERED → CONFIRMED` and requires the payment to have arrived first — confirming while `payment_status` is anything other than `PAID` fails with `ERR_PAYMENT_REQUIRED`. Race-day check-in, covered in §3.3, moves `CONFIRMED → CHECKED_IN`.

Withdrawal moves a registration from `REGISTERED`, `CONFIRMED`, or `CHECKED_IN` into the terminal `WITHDRAWN` state, but only before the race goes live: once the race has reached `IN_PROGRESS`, `PROVISIONAL_PUBLISHED`, `FINALIZED`, or `AMENDMENT_OPEN`, withdrawal is rejected with `ERR_RACE_ALREADY_STARTED`. A paid registration is refunded as part of withdrawal, moving `PAID → REFUNDED`; an unpaid one simply closes. When a checked-in athlete withdraws, their chip is released back to the fleet as described in §3.3. The registration addressed by `reg_id` can be read back at any time, and the registration listing can be filtered by `race_id`, `wave_id`, `chip_id`, `lifecycle_status`, or `bib_number`.

### 3.3. The Chip Fleet and Race-Day Check-In

Chips are fleet assets. A `RegistrationClerk` registers each **Chip** with a fleet-wide unique `chip_code` — a duplicate code is refused with `ERR_CHIP_CODE_TAKEN` — and the chip begins `AVAILABLE` with no holder, its `current_registration_id` null. The chip listing can be filtered by `status`, `chip_code`, or `current_registration_id`, and the chip addressed by `chip_id` can be read directly.

Race-day check-in binds a chip to a confirmed athlete: a `RegistrationClerk` performs chip assignment for the registration addressed by `reg_id`, passing the chosen `chip_id` in the payload. Three conditions guard the binding, evaluated state-first. The registration must be `CONFIRMED` and its race must be in `TIMING_LOCKED` or `IN_PROGRESS` — a registration in any other lifecycle state, or a race outside that window, fails the state check with `ERR_INVALID_STATE`. The chip must be `AVAILABLE`, otherwise `ERR_CHIP_NOT_AVAILABLE`. And the registration must not already hold a chip, otherwise `ERR_CHIP_ALREADY_ASSIGNED`. A successful assignment moves the registration `CONFIRMED → CHECKED_IN`, moves the chip `AVAILABLE → ASSIGNED`, and links the two in both directions: the registration's `chip_id` is set, and the chip's `current_registration_id` points back.

Releasing a chip takes a `disposition` of either `RETURNED` or `LOST`, and requires the chip to be `ASSIGNED` — releasing anything else fails with `ERR_CHIP_NOT_ASSIGNED`. The two dispositions diverge deliberately. A `RETURNED` chip goes back to `AVAILABLE`, the athlete stays `CHECKED_IN` and may check in again with a different chip, and both links are cleared. A `LOST` chip leaves the fleet permanently — `LOST` is terminal — and the athlete is bumped back from `CHECKED_IN` to `CONFIRMED`, requiring a fresh check-in with a new chip; both links are cleared here as well. Withdrawal of a `CHECKED_IN` registration releases its chip along the `RETURNED` path: the chip becomes `AVAILABLE` and both links clear as part of the withdrawal.

### 3.4. Locking the Timing Configuration and Starting the Race

Before the first start gun, the `RaceDirector` locks the timing configuration, moving the race `REGISTRATION_OPEN → TIMING_LOCKED`. Locking is a completeness audit, and any shortfall rejects with `ERR_TIMING_CONFIG_INCOMPLETE`: the race must have at least one wave; exactly one `DEPLOYED` timing point of kind `START`; exactly one `DEPLOYED` timing point of kind `FINISH` whose `distance_km` equals the race's `distance_km`; and no timing point remaining in `PLANNED`. A successful lock stamps `timing_locked_at` with the logical now and records the acting operator in `locked_by_user_id` — a reference that certification later checks, per §2.9. It also captures the `timing_config_fingerprint`: for every deployed point, ordered by `point_index` ascending, a segment joining the point's index, kind, and distance in kilometers with colons, with the segments themselves joined by commas. From this moment, registration intake closes — new registrations, payments, and confirmations all fail the intake gate of §3.2 — and the timing-point layout is frozen per §3.1.

A `TimingOperator` starts each wave when it actually goes off, moving the wave addressed by `wave_id` from `SCHEDULED` to `STARTED`; the wave's race must already be in `TIMING_LOCKED` or `IN_PROGRESS`. The wave's `actual_start_time` is stamped with the logical now and becomes the gun-time basis for every registration seated in that wave. The first wave start of a race also moves the race itself `TIMING_LOCKED → IN_PROGRESS` automatically — there is no separate "start the race" action.

### 3.5. Read Ingest and Course-Cut Surveillance

Once the race is running, a `TimingOperator` ingests chip reads. Each read names the `timing_point_id` and the `chip_id`, and carries the device-stamped `read_timestamp` in UTC with millisecond precision. Reads are append-only per §2.5: created by ingest, never deleted, and the read addressed by `read_id` can be fetched directly or listed with filters on `timing_point_id`, `chip_id`, `status`, or `adjusted_by_correction_id`. Ingest is gated on the race being in `IN_PROGRESS`, `PROVISIONAL_PUBLISHED`, or `AMENDMENT_OPEN` — late reads remain admissible while results are provisional — and this gate is evaluated before deduplication: outside those three states, ingest fails with `ERR_READ_INGEST_CLOSED`. An exact duplicate, meaning the same point, chip, and timestamp already present on the log, fails with `ERR_DUPLICATE_READ`.

Every accepted read is classified at ingest. A read becomes `SCORED` when its chip is currently assigned to a `CHECKED_IN` registration of the same race as the timing point; otherwise it becomes `REJECTED` with `reject_reason` set to `CHIP_NOT_CHECKED_IN`. `REJECTED` is terminal — the read never contributes to any derivation — while `SCORED` reads feed everything downstream. A third status, `EXCLUDED`, is never an ingest outcome: it is applied later by approved corrections, which can also rewrite a read's `read_timestamp` and stamp `adjusted_by_correction_id` (§3.7); at ingest both `reject_reason` and `adjusted_by_correction_id` are null unless classification sets the former.

Each read classified `SCORED` is screened for course-cutting on the spot. When the read's point is a `SPLIT` or the `FINISH`, and the athlete already has a `SCORED` start read earlier than this read, the elapsed time between the start read and this read is compared against a floor: the point's `distance_km` multiplied by a minimum pace of two minutes per kilometer, expressed in milliseconds. An elapsed time strictly below the floor is physically implausible and raises an automatic `COURSE_CUT_SUSPECT` flag in `RAISED` state with `origin` `AUTO`; an elapsed time exactly equal to the floor raises nothing. When no scored start read exists yet, the check is skipped silently. At most one unresolved automatic `COURSE_CUT_SUSPECT` exists per registration at any time, and once one has been `CONFIRMED` the system raises no further automatic course-cut flags for that athlete. A second sweep runs at publish time (§3.6) to catch athletes who skipped a split mat entirely.

### 3.6. Publishing Results: Times, Ranks, and Awards

Publishing is the race's accounting moment, performed by the `RaceDirector`. The publish request carries `expected_race_version` under the concurrency rule of §2.8, and its checks are evaluated state first, then concurrency, then the cutoff. The race must be in `IN_PROGRESS` for a first publication or `AMENDMENT_OPEN` for a re-publication, and at least one of its waves must be `STARTED`. The cutoff requires the logical now to have reached the earliest `actual_start_time` among the started waves plus `course_time_limit_minutes`; the boundary is inclusive, so a publish attempted earlier fails with `ERR_RACE_CUTOFF_NOT_REACHED` while a publish at exactly the cutoff proceeds.

Publication runs a full recompute of the race in four pinned phases — the order matters, because flags drive exclusions and exclusions drive ranks. In the derivation phase, the system computes times for every `CHECKED_IN` registration from the read log. For a registration and its assigned chip, two anchor reads are located. The finishing anchor is the earliest `SCORED` read of that chip at the race's `FINISH` timing point; its `read_timestamp` becomes the result's `finish_timestamp` and serves as the tie-break input for ranking. The starting anchor is the `SCORED` read of the same chip at the race's `START` timing point with the latest `read_timestamp` that is still strictly earlier than the finishing anchor. `chip_time_ms` is the difference between the finishing anchor and the starting anchor; if either anchor is missing, `chip_time_ms` is null. `gun_time_ms` is the difference between the finishing anchor and the wave's `actual_start_time`; it is null when the wave has not been started or when no finishing anchor exists. `completed_splits` counts the distinct `SPLIT` timing points of the race at which the chip has at least one `SCORED` read. Reads in `EXCLUDED` or `REJECTED` status never contribute to any of these derivations.

In the exclusion phase, a registration is excluded if and only if it carries at least one `CONFIRMED` result flag of any `flag_type`; the result's `exclusion_reason` takes the `flag_type` of the earliest-created `CONFIRMED` flag, ordered by `created_at`. Exclusion is independent of timing data: a registration whose `chip_time_ms` is null is simply left unranked — no rank is assigned, but the registration is not excluded on that basis. In the ranking phase, two independent orderings are produced. The gun ranking considers every eligible — that is, non-excluded — registration whose `gun_time_ms` is not null, ordered by `gun_time_ms` ascending, with ties broken by `finish_timestamp` ascending and then by the registration's `created_at` ascending; `overall_rank_gun` is assigned 1 through N strictly, forming a gap-free sequence. The chip ranking is computed within each pairing of `gender` and `age_group` over eligible registrations whose `chip_time_ms` is not null, applying the identical tie-break chain to `chip_time_ms`; `age_group_rank_chip` runs 1 through M within the category, again with no gaps. In the write phase, ranks, times, `completed_splits`, and the `qualified` flag are written together: a result is marked `qualified` when the race defines `qualifying_standard_ms`, the result is not excluded, and its `chip_time_ms` is less than or equal to the standard — the boundary is inclusive.

The two rankings legitimately disagree. The gun ranking answers who crossed the finish line first on the wave's actual-start basis, so a later-wave athlete with a faster `chip_time_ms` still loses to an earlier-wave athlete with a faster `gun_time_ms`. The chip ranking answers who ran fastest mat-to-mat on a personal basis, and it alone feeds the age-group categories and the `qualified` flag; identical finish data can therefore crown different winners under the two schemes.

On first publication, a **Result** row is created `PROVISIONAL` for every `CHECKED_IN` registration — exactly one result per registration, denormalized with the `race_id` for race-scoped queries, with `revision` starting at 1, `qualified` starting false, ranks null until assigned, and `exclusion_reason` null. Re-publication moves every non-`EXCLUDED` result back to `PROVISIONAL` (including any that had been `AMENDED`), while `EXCLUDED` results recompute their times but remain `EXCLUDED` and unranked.

Publication also runs two integrity sweeps. Every `CHECKED_IN` registration with no `SCORED` finish read receives an automatic `DNF` flag in `RAISED` state, with at most one unresolved automatic `DNF` per registration. The missing-split sweep then examines each `CHECKED_IN` athlete's progress: taking the furthest timing point, by `point_index`, at which the athlete has a `SCORED` read, any `SPLIT` point before it without a `SCORED` read for that athlete raises an automatic `COURSE_CUT_SUSPECT`. These flags are raised, not confirmed — they exclude nobody until a `RaceOfficial` confirms them (§3.7), because the exclusion phase honors only `CONFIRMED` flags.

With ranks settled, awards are computed. The categories comprise `OVERALL_M` and `OVERALL_F`, plus one age-group category for every pairing of `gender` and `age_group` present among the eligible ranked finishers, named as described in §3.2. The overall categories are allocated on the `GUN` basis, candidates taken in `overall_rank_gun` ascending order; the age-group categories on the `CHIP` basis, candidates taken in `age_group_rank_chip` ascending order. Within each category, places 1 through 3 receive an award — or fewer when the eligible field runs shallower than three deep, and none at all when the eligible field is empty. Each award row records its `category`, its `place`, the winner's `registration_id`, the `basis`, and the winning time as `basis_time_ms` — the winner's `gun_time_ms` under the `GUN` basis or `chip_time_ms` under the `CHIP` basis — along with its `race_id`. When a recompute changes the winner of a category-and-place pairing, the existing non-`REVOKED` award moves to `REVOKED` and a replacement row is created `PROJECTED`; an award whose winner is unchanged is kept exactly as it is. At most one non-`REVOKED` award exists per race, category, and place at any moment.

Publication then stamps `provisional_published_at` with the logical now and sets `protest_window_closes_at` thirty minutes later, opening — or re-opening — the protest window of §3.7. The race moves to `PROVISIONAL_PUBLISHED`, and its `version` increments by one. Results can be read individually by `result_id` or listed with filters on `race_id`, `registration_id`, or `status`; the awards listing can be filtered by `category` or `status`, and the awards won by a single registration can be listed on the registration itself.

### 3.7. Flags, Protests, and Corrections: The Amendment Loop

Result flags are the race's integrity docket. A `RaceOfficial` raises one manually with the subject `registration_id`, a `flag_type` of `DNF`, `DQ`, or `COURSE_CUT_SUSPECT`, and an optional free-text `detail`; manual flags carry `origin` `MANUAL` and begin `RAISED`, while system-raised flags carry `origin` `AUTO` with the detail populated by the detection that produced them. Raising a flag, and later resolving it, both require the registration's race to be in `IN_PROGRESS`, `PROVISIONAL_PUBLISHED`, or `AMENDMENT_OPEN`; anywhere else the request fails the state gate with `ERR_INVALID_STATE`. Resolution takes an `outcome` of `CONFIRMED` or `DISMISSED`. A dismissal simply closes the flag in `DISMISSED`. A confirmation while the race is `PROVISIONAL_PUBLISHED` or `AMENDMENT_OPEN` triggers the flag cascade: the subject's result — whether `PROVISIONAL` or `OFFICIAL` — moves to `EXCLUDED`, its `exclusion_reason` takes the flag's `flag_type`, its ranks are nulled, and ranks and awards across the race are recomputed. Flags can be read individually by `flag_id` or listed with filters on `registration_id`, `flag_type`, or `status`.

During the protest window, a `RegistrationClerk` files a **Protest** on a participant's behalf, naming the `race_id`, the subject `registration_id` (which must already have a result in the race), the disputed `timing_read_id` (which must belong to that race), a `requested_action` of `EXCLUDE_READ`, `REINSTATE_READ`, or `ADJUST_READ_TIME`, a `corrected_timestamp` when — and only when — the requested action is `ADJUST_READ_TIME`, and a free-text `reason`. Filing requires the logical now to fall strictly before `protest_window_closes_at`: filing at or after the close fails with `ERR_PROTEST_WINDOW_CLOSED`, and the window check runs before the referential checks, which reject a subject without a result, a read from another race, or a missing adjustment timestamp with `ERR_INVALID_REQUEST`. A filed protest records the clerk in `filed_by_user_id` and begins `FILED`. Protests can be read individually by `protest_id` or listed with filters on `race_id`, `registration_id`, `status`, or `timing_read_id`.

A `RaceOfficial` resolves a protest with an `outcome` of `UPHELD` or `DISMISSED`. The race must be in `PROVISIONAL_PUBLISHED`, and the segregation rule of §2.9 forbids the filer from resolving their own protest; the state check runs first, then the duty check, which rejects a colliding resolver with `ERR_SOD_VIOLATION`. A dismissal closes the protest in `DISMISSED` with no further effect. An upheld protest is executable: the system immediately creates a **Correction** that is already `APPROVED`, taking its `kind` from the protest's `requested_action`, carrying the same `timing_read_id` and `corrected_timestamp`, and with `protest_id` pointing back at the protest — and the full correction cascade described below runs. Either way, the resolving official is recorded in `resolved_by_user_id`.

Officials can also act without a protest by filing a correction directly, naming the `race_id`, the `timing_read_id` of a read belonging to that race, a `kind` mirroring the protest actions — `EXCLUDE_READ`, `REINSTATE_READ`, or `ADJUST_READ_TIME` — a `corrected_timestamp` under the same conditional rule, and a `reason`; the correction begins `FILED`, with `protest_id` null and `adjudicated_by_user_id` unset. Not every kind is actionable on every read: `EXCLUDE_READ` requires the target read to be `SCORED`; `REINSTATE_READ` requires it to be `EXCLUDED`; and `ADJUST_READ_TIME` requires it to be `SCORED` with the corrected timestamp supplied. A mismatch fails with `ERR_CORRECTION_KIND_MISMATCH`, checked both at filing and again at adjudication. Adjudication takes a `decision` of `APPROVED` or `REJECTED` together with `expected_race_version` under the concurrency rule of §2.8; the checks run state first — the correction must be `FILED` and its race in `PROVISIONAL_PUBLISHED`, `FINALIZED`, or `AMENDMENT_OPEN` — then concurrency, then kind-actionability. A `REJECTED` decision closes the correction in `REJECTED` and still advances the race `version` by one; the adjudicating official is recorded in `adjudicated_by_user_id`.

An `APPROVED` decision fires the correction cascade. First, the read mutates: exclusion moves it `SCORED → EXCLUDED`; reinstatement moves it `EXCLUDED → SCORED`; adjustment keeps it `SCORED` while rewriting its `read_timestamp` and stamping `adjusted_by_correction_id` with the correction's id. Second, the full four-phase recompute of §3.6 re-runs, and any `OFFICIAL` result whose computed fields change moves to `AMENDED` with its `revision` incremented by one. Third, awards swap per §3.6: stale rows are `REVOKED` and replacements created `PROJECTED`, with `CONFIRMED` status restored only after a subsequent finalization. Fourth, the race itself re-opens, moving from `PROVISIONAL_PUBLISHED` or `FINALIZED` into `AMENDMENT_OPEN` with `amendment_count` incremented by one, and an `ISSUED` certification is automatically `REVOKED` with `revocation_reason` set to `CORRECTION_APPROVED`. Finally, the race `version` increments by one. The amendment loop closes when the director re-publishes per §3.6 and re-finalizes per §3.8. Corrections can be read individually by `correction_id` or listed with filters on `race_id`, `timing_read_id`, `status`, or `protest_id`.

### 3.8. Finalization and Certification

Once the protest window has run its course, the `RaceDirector` finalizes, moving the race `PROVISIONAL_PUBLISHED → FINALIZED`. Four gates guard the transition, evaluated in this order: the race state itself; the window check, which requires the logical now to be at or after `protest_window_closes_at` — the boundary is inclusive, and an earlier attempt fails with `ERR_PROTEST_WINDOW_OPEN`; the protest docket, which must hold zero `FILED` protests for the race, failing with `ERR_PROTESTS_OUTSTANDING`; and the flag docket, which must hold zero `RAISED` flags on any registration of the race, failing with `ERR_FLAGS_OUTSTANDING`. Finalization moves every `PROVISIONAL` result to `OFFICIAL`, every `PROJECTED` award to `CONFIRMED`, and stamps `finalized_at` with the logical now.

A finalized race on certified ground can then be attested by a `CertificationOfficer`. Each race owns exactly one **Certification** row, created on first issuance and reused on every re-issuance thereafter. Certification demands that the race be `FINALIZED`; that its `course_type` be `CERTIFIED_COURSE` — an `UNCERTIFIED_COURSE` race is refused with `ERR_COURSE_NOT_CERTIFIED`; that the dockets remain clean, with no `FILED` protest and no `RAISED` flag — conditions already implied by `FINALIZED` but re-checked at certification time; and, per §2.9, that the issuing officer is not the operator recorded in the race's `locked_by_user_id`. The checks run state first, then the duty rule — a collision fails with `ERR_SOD_VIOLATION` — then the course requirement. Issuance, including re-issuance from `REVOKED`, moves the row to `ISSUED`, stamps `issued_at` with the logical now, records `issued_by_user_id`, recomputes `qualified_count` as the number of results currently carrying `qualified` true, and clears `revocation_reason` to null. An approved correction revokes an `ISSUED` certification automatically per §3.7, and the race must be re-published, re-finalized, and re-certified to restore it.

### 3.9. The Live Results Feed

While a race is running, anyone — including a `Spectator` — can consult the live board, a forward-looking projection of the standings. The board answers with an `entries` array and a `generated_at` stamp taken from the logical clock, and accepts an optional `bib_number` filter for tracking a specific athlete.

The projection covers every `CHECKED_IN`, non-excluded registration that has a `SCORED` start read. The registration's `SCORED` reads are ordered by their timing point's `point_index` ascending, keeping only the earliest read at each point. For each consecutive pair of points, a segment pace in seconds per kilometer is computed as the elapsed time between the two reads divided by the distance between the two points, rounded half up to a whole second per kilometer — this per-segment rounding happens first. The projected pace is the mean of the last two segment paces, itself rounded half up to a whole second per kilometer; when only one segment exists, that segment's pace is used directly. The remaining distance is the race's `distance_km` minus the distance of the furthest point reached. The projected remaining time in seconds is the remaining distance multiplied by the projected pace, rounded half up to a whole second. The elapsed time at the last read is the difference between the last read and the start read, converted from milliseconds to seconds and rounded half up. The projected total is the sum of those elapsed seconds and the projected remaining seconds.

Entries are ordered by projected total ascending; ties break by elapsed seconds ascending, then by the registration's `created_at` ascending. The rounding order is pinned and non-negotiable: each segment is rounded before the mean is taken, and the mean is rounded before it is multiplied by the remaining distance — computing unrounded and rounding only at the end yields different seconds and is non-conformant. Registrations without a `SCORED` start read, and those that have already finished (a `SCORED` finish read exists), are listed separately from the projection, with finishers ordered by `chip_time_ms` ascending.

## 4. Endpoint Definitions

Operations that create a new resource — a race, wave, timing point, registration, chip, timing read, result flag, protest, or correction — return `201 Created`. Operations that modify an existing resource, advance a state machine, or read data return `200 OK`. Removing a timing point returns `204 No Content` with no response body. Readers must reconstruct full request and response shapes from the narratives of §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/race-timing/_clock/set_current_utc` | Set the logical clock (test-driving capability) | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer |
| POST | `/race-timing/races` | Create a race (starts `DRAFT`) | RaceDirector |
| GET | `/race-timing/races/{race_id}` | Read a race | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| GET | `/race-timing/races/{id}/waves` | List waves of a race | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| GET | `/race-timing/races/{id}/timing-points` | List timing points of a race | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer |
| GET | `/race-timing/races/{id}/certifications` | List certifications of a race (zero or one row) | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| GET | `/race-timing/races/{id}/awards` | List awards of a race | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| POST | `/race-timing/races/{race_id}/open-registration` | Move a race `DRAFT → REGISTRATION_OPEN` | RaceDirector |
| POST | `/race-timing/races/{race_id}/lock-timing` | Lock the timing configuration (`REGISTRATION_OPEN → TIMING_LOCKED`) | RaceDirector |
| POST | `/race-timing/races/{race_id}/publish-results` | Compute results and open/re-open the protest window (OCC-guarded) | RaceDirector |
| POST | `/race-timing/races/{race_id}/finalize-results` | Finalize results after the protest window (`PROVISIONAL_PUBLISHED → FINALIZED`) | RaceDirector |
| POST | `/race-timing/races/{race_id}/certify` | Issue or re-issue the race certification | CertificationOfficer |
| GET | `/race-timing/races/{race_id}/live-board` | Live results feed and spectator tracking | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| POST | `/race-timing/waves` | Create a wave (starts `SCHEDULED`) | RaceDirector |
| POST | `/race-timing/waves/{wave_id}/start` | Start a wave (`SCHEDULED → STARTED`) | TimingOperator |
| POST | `/race-timing/timing-points` | Create a timing point (starts `PLANNED`) | TimingOperator |
| POST | `/race-timing/timing-points/{point_id}/deploy` | Deploy a timing point (`PLANNED → DEPLOYED`) | TimingOperator |
| DELETE | `/race-timing/timing-points/{point_id}` | Remove a timing point (pre-lock only) | TimingOperator |
| POST | `/race-timing/registrations` | Register a participant into a wave with a bib | RegistrationClerk |
| GET | `/race-timing/registrations/{reg_id}` | Read a registration | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer |
| GET | `/race-timing/registrations` | List and filter registrations | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer |
| POST | `/race-timing/registrations/{reg_id}/pay` | Record payment (`UNPAID → PAID`) | RegistrationClerk |
| POST | `/race-timing/registrations/{reg_id}/confirm` | Confirm a paid registration (`REGISTERED → CONFIRMED`) | RegistrationClerk |
| POST | `/race-timing/registrations/{reg_id}/assign-chip` | Assign a chip at race-day check-in (`CONFIRMED → CHECKED_IN`) | RegistrationClerk |
| POST | `/race-timing/registrations/{reg_id}/withdraw` | Withdraw a registration (releases chip, refunds payment) | RegistrationClerk |
| POST | `/race-timing/chips` | Register a chip into the fleet (starts `AVAILABLE`) | RegistrationClerk |
| GET | `/race-timing/chips/{chip_id}` | Read a chip | RaceDirector, RegistrationClerk, TimingOperator |
| GET | `/race-timing/chips` | List and filter chips | RaceDirector, RegistrationClerk, TimingOperator |
| POST | `/race-timing/chips/{chip_id}/deassign` | Release an assigned chip (`RETURNED` or `LOST` disposition) | RegistrationClerk |
| POST | `/race-timing/timing-reads` | Ingest a chip read (append-only; classified at ingest) | TimingOperator |
| GET | `/race-timing/timing-reads/{read_id}` | Read a timing read | RaceDirector, TimingOperator, RaceOfficial |
| GET | `/race-timing/timing-reads` | List and filter timing reads | RaceDirector, TimingOperator, RaceOfficial |
| GET | `/race-timing/results/{result_id}` | Read a result | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| GET | `/race-timing/results` | List and filter results | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |
| POST | `/race-timing/result-flags` | Manually raise a result flag (`MANUAL` origin) | RaceOfficial |
| GET | `/race-timing/result-flags/{flag_id}` | Read a result flag | RaceDirector, RaceOfficial, TimingOperator |
| GET | `/race-timing/result-flags` | List and filter result flags | RaceDirector, RaceOfficial, TimingOperator |
| POST | `/race-timing/result-flags/{flag_id}/resolve` | Confirm or dismiss a raised flag | RaceOfficial |
| POST | `/race-timing/protests` | File a protest during the protest window | RegistrationClerk |
| GET | `/race-timing/protests/{protest_id}` | Read a protest | RaceDirector, RegistrationClerk, RaceOfficial |
| GET | `/race-timing/protests` | List and filter protests | RaceDirector, RegistrationClerk, RaceOfficial |
| POST | `/race-timing/protests/{protest_id}/resolve` | Uphold or dismiss a filed protest (segregation of duties) | RaceOfficial |
| POST | `/race-timing/corrections` | File a results correction directly | RaceOfficial |
| GET | `/race-timing/corrections/{correction_id}` | Read a correction | RaceDirector, RaceOfficial |
| GET | `/race-timing/corrections` | List and filter corrections | RaceDirector, RaceOfficial |
| POST | `/race-timing/corrections/{correction_id}/adjudicate` | Approve or reject a filed correction (OCC-guarded) | RaceOfficial |
| GET | `/race-timing/registrations/{id}/awards` | List awards won by a registration | RaceDirector, TimingOperator, RegistrationClerk, RaceOfficial, CertificationOfficer, Spectator |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_RACE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_RACE_REGISTRATION_CLOSED` | 409 Conflict |
| `ERR_WAVE_CAPACITY_FULL` | 409 Conflict |
| `ERR_BIB_NUMBER_TAKEN` | 409 Conflict |
| `ERR_WAVE_INDEX_TAKEN` | 409 Conflict |
| `ERR_WAVE_SPACING_VIOLATION` | 409 Conflict |
| `ERR_DEVICE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TIMING_CONFIG_LOCKED` | 409 Conflict |
| `ERR_TIMING_CONFIG_INCOMPLETE` | 409 Conflict |
| `ERR_PAYMENT_REQUIRED` | 409 Conflict |
| `ERR_CHIP_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CHIP_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_CHIP_NOT_ASSIGNED` | 409 Conflict |
| `ERR_CHIP_CODE_TAKEN` | 409 Conflict |
| `ERR_RACE_ALREADY_STARTED` | 409 Conflict |
| `ERR_DUPLICATE_READ` | 409 Conflict |
| `ERR_READ_INGEST_CLOSED` | 409 Conflict |
| `ERR_RACE_CUTOFF_NOT_REACHED` | 409 Conflict |
| `ERR_PROTEST_WINDOW_CLOSED` | 409 Conflict |
| `ERR_PROTEST_WINDOW_OPEN` | 409 Conflict |
| `ERR_PROTESTS_OUTSTANDING` | 409 Conflict |
| `ERR_FLAGS_OUTSTANDING` | 409 Conflict |
| `ERR_COURSE_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CORRECTION_KIND_MISMATCH` | 409 Conflict |
