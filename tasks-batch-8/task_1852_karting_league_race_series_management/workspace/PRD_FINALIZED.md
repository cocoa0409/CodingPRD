# Karting League & Race Series Management API — Product Requirements Document

## 1. Introduction

Karting clubs that run multi-round championships live or die on arithmetic and procedure: class eligibility by age and weight, rental-fleet availability, per-round points with discarded low scores, protest handling, and the end-of-season tiebreak that decides who lifts the trophy at the awards banquet. Done by hand on spreadsheets, each of these steps is a recurring source of disputes — a mis-weighed kart, a misapplied drop round, a steward ruling on their own report.

This document specifies the Karting League & Race Series Management API, mounted under the `/karting` prefix, which digitizes that championship operation end to end. It covers season and class configuration, driver registration and licensing, the rental kart fleet, race events from registration through grid lock and scoring, technical inspection with weight compliance, an incident-review protocol with a strict separation between reporting and adjudication, championship standings with drop rounds and countback, and practice-track booking with two billing models. The API serves four acting roles and is built around immediate consistency: every computed figure — fees collected, points, standings — reflects the latest committed change on the next read.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The recognized roles are exactly `LeagueAdmin`, `RaceDirector`, `Steward`, and `Driver`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (403).

The identity carried by `X-User-ID` depends on the role. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver resource; ownership checks on any resource that references a Driver — an entry, a practice booking, an appeal — compare the resource's `driver_id` to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. When `X-User-Role` is `LeagueAdmin`, `RaceDirector`, or `Steward`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `inspector_user_id` on a technical inspection, or as `reporter_user_id` and `adjudicator_user_id` on an incident — but never compares it to any entity's `id`.

Two ownership-flavored rules sit above the endpoint role lists. Segregation of duties in the judicial flow: the steward adjudicating an incident must not be the official who reported it — if the adjudicator's `X-User-ID` equals the incident's `reporter_user_id`, the ruling is rejected with `ERR_SELF_ADJUDICATION` (403). An appeal may be filed only by the driver of the entry the incident was filed against; any other driver draws `ERR_NOT_ENTRY_DRIVER` (403). Driver-scoped mutations — paying an entry fee, withdrawing an entry, and checking in, checking out, or cancelling a practice booking — may be performed only by the owning `Driver`, with `LeagueAdmin` additionally able to pay, withdraw, and cancel bookings on a driver's behalf.

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

List endpoints accept the `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Unless otherwise specified, list responses are sorted by `created_at` in ascending order.

The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — seasons, classes, drivers, karts, events, entries, sessions, results, incidents, and practice bookings — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation and never changed.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a server-managed integer that increments by exactly one whenever the resource is modified. Lifecycle calls that change a resource's status — activation, finalization, grid lock, payment, withdrawal, check-in, and the like — are ordinary mutations for this purpose: each refreshes `updated_at` and advances `version` by one.

Technical inspections are the deliberate exception. An inspection record is append-only and carries only `id` and `created_at`; both `updated_at` and `version` are absent, because an inspection is never modified after it is recorded.

### 2.5. Weights, Points, and Money: Precision Rules

Three unit systems run through the API, each with fixed precision. Weights — a driver's `body_weight_kg`, a class's `min_combined_weight_kg`, an inspection's `measured_combined_weight_kg` — are recorded to one decimal place and compared exactly as given; the weigh-in comparison performs no rounding. Ages are reckoned in whole years, always rounded down. Points are integers with no rounding at any stage — `points_awarded`, `event_points`, and both standings totals. Times are integer milliseconds (`best_lap_ms`, `total_time_ms`), while penalties are whole seconds accumulated in `penalty_seconds_applied`. Money is integer cents throughout — `entry_fee_cents`, `collected_fees_cents`, and a booking's `fee_cents`. The single rounding event in the system is metered practice billing, which rounds half-up to whole cents once per booking at check-out (§3.8).

### 2.6. Optimistic Concurrency Control on Event and Session Writes

Two write operations are guarded by optimistic concurrency control, each keyed to the parent resource named in its path. Creating a session under an event requires the request to carry `expected_event_version` holding the event `version` the client last observed. Submitting a result batch to a session requires `expected_session_version` holding the session `version` the client last observed. If the presented value does not equal the parent resource's current `version` — because another write, such as an earlier session creation or result submission, has advanced it since the client last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Both of these writes themselves advance the parent's `version` by one, so a client that has just written must re-read the parent before writing again. No other endpoint accepts a version field; on every other resource the `version` is server-managed and read-only.

### 2.7. Nested Resource Retrieval and Parent Scoping

Requests that target nested resources are validated left to right along the path. The server resolves each path identifier — `season_id`, `class_id`, `event_id`, `entry_id`, `session_id`, `incident_id`, `driver_id`, `kart_id`, `booking_id` — in path order and rejects the request with `ERR_NOT_FOUND` (404) at the first identifier that does not correspond to an existing resource, without examining later segments. Existence alone is not enough: every referenced child must belong to the declared parent scope — a class must belong to the addressed season, an event to its season, an entry to its event, a session to its event. An identifier that exists but sits under a different parent is likewise answered with `ERR_NOT_FOUND`.

### 2.8. Validation Order and Error Precedence

When several checks could fail on the same request, the server evaluates them in a fixed order and answers with the first failing tier:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is recognized (`ERR_UNAUTHENTICATED`). Applies to every endpoint.
2. **Authorization and ownership** — the role is permitted for the endpoint, and the segregation-of-duties and driver-ownership rules of §2.1 hold (`ERR_FORBIDDEN`, `ERR_SELF_ADJUDICATION`, `ERR_NOT_ENTRY_DRIVER`). Applies to every endpoint.
3. **Body well-formedness** — required fields are present, enum values are valid, `end_time` is strictly after `start_time`, a `RENTAL` entry carries `kart_id` while an `OWNER_DRIVER` entry omits it, and `penalty_seconds` is present and positive exactly when `penalty_kind` is `TIME_SECONDS` (`ERR_INVALID_REQUEST`). Applies to every endpoint.
4. **Existence and scope** — every path identifier and referenced resource exists within its declared parent scope (`ERR_NOT_FOUND`). Applies to every endpoint.
5. **Stale-version guard** — `expected_event_version` or `expected_session_version` matches the parent resource's current `version` (`ERR_STALE_VERSION`). Applies only to the two OCC-guarded writes of §2.6.
6. **State preconditions** — the target resources sit in states that permit the operation: the season `ACTIVE` for event creation and registration opening (`ERR_SEASON_NOT_ACTIVE`); the event `REGISTRATION_OPEN` for entry creation (`ERR_EVENT_REGISTRATION_CLOSED`); the driver `ACTIVE` for entries and practice bookings (`ERR_DRIVER_NOT_ACTIVE`); the kart `AVAILABLE` for entries and bookings (`ERR_KART_UNAVAILABLE`); no open incidents at event finalization (`ERR_OPEN_INCIDENTS`); no prior appeal on the incident (`ERR_APPEAL_LIMIT`); the session `CLOSED` for result submission and for scoring, with scoring from a non-closed session surfaced as `ERR_SESSION_NOT_CLOSED`; every `GRID_LOCKED` entry holding a result at scoring time (`ERR_RESULTS_INCOMPLETE`); every non-`WITHDRAWN` entry in `TECH_PASSED` at grid lock (`ERR_TECH_NOT_PASSED`); and any other invalid from-state for a requested transition (`ERR_INVALID_STATE`). Applies to state-transition and guarded endpoints.
7. **Class and equipment eligibility** — age window and license consistency (`ERR_CLASS_MISMATCH`), rental permission (`ERR_RENTAL_NOT_ALLOWED`), kart class eligibility (`ERR_KART_CLASS_INELIGIBLE`). Applies only to entry creation.
8. **Booking overlap** — the requested window against the kart's committed schedule (`ERR_BOOKING_OVERLAP`). Applies only to practice-booking creation.
9. **Uniqueness and capacity** — one non-`WITHDRAWN` entry per driver per event (`ERR_DUPLICATE_ENTRY`), unique `round_number` per season (`ERR_DUPLICATE_ROUND`), unique class `code` per season (`ERR_DUPLICATE_CLASS_CODE`), one result row per entry per batch (`ERR_DUPLICATE_RESULT`), a kart not already assigned to a non-`WITHDRAWN` entry of the same event (`ERR_KART_UNAVAILABLE`), and the track capacity ceiling (`ERR_TRACK_CAPACITY_EXCEEDED`). Applies to the creation endpoints.
10. **Fiscal gate** — every non-`WITHDRAWN` entry's fee settled (`ERR_ENTRY_FEE_UNPAID`). Applies only to grid lock.

Because earlier tiers mask later ones, an unauthenticated caller never learns which business rule the request would have broken, a stale-version rejection surfaces before any state precondition is examined, and grid lock's unpaid-fee gate is consulted only after every other check has passed.

### 2.9. The Season Treasury: Fees, Payment, and Refunds

The season doubles as the bookkeeper for entry fees. When an entry is created, the class's `entry_fee_cents` is copied onto the entry as a snapshot — later fee changes on the class do not retroactively alter existing entries — and the entry's `fee_status` begins at `UNPAID`. Settling the fee moves `fee_status` to `PAID`; withdrawal or event cancellation moves a `PAID` fee to `REFUNDED`. The season's `collected_fees_cents` is a derived figure, defined as the sum of `entry_fee_cents` over all of the season's entries whose `fee_status` is `PAID`, recomputed as payments and refunds land: a payment adds the entry's fee to the total, and a refund subtracts it. `UNPAID` and `REFUNDED` entries contribute nothing to the treasury.

### 2.10. Half-Open Booking Windows, Kart Overlap, and Track Capacity

Practice bookings reserve half-open windows: a booking occupies its kart from `start_time` inclusive up to, but not including, `end_time`. Two windows that merely touch — one ending exactly when the other begins — do not intersect. A new booking for a kart is rejected with `ERR_BOOKING_OVERLAP` (409) when its window intersects any existing booking of the same kart in `RESERVED` or `CHECKED_IN` status; `COMPLETED` and `CANCELLED` bookings occupy nothing.

The track as a whole also enforces a capacity ceiling, `TRACK_CAPACITY_KARTS`: a booking is rejected with `ERR_TRACK_CAPACITY_EXCEEDED` (409) when the count of bookings — across all karts, in `RESERVED` or `CHECKED_IN` status — whose windows intersect the requested window has already reached that ceiling. The same status filter drives the fleet's availability read model: a kart's booked minutes for a given day are the sum of the whole-minute window lengths of its `RESERVED` and `CHECKED_IN` bookings on that day, with `COMPLETED` and `CANCELLED` bookings contributing zero.

## 3. Business Logic & Workflows

### 3.1. Season Setup: Seasons, Classes, and the Points Scheme

A `LeagueAdmin` opens a championship by creating a season with a display `name`, a competition `year`, the `drop_rounds` count governing how many of each driver's lowest-scoring rounds are discarded in the final standings (a non-negative integer, defaulting to 0), the `points_scheme`, and optionally `fastest_lap_bonus_points` (an integer, defaulting to 0). The `points_scheme` is an array of integers read by finishing position: the first element is the base points for a first-place finish, the second element for second place, and so on, and any finishing position beyond the array's length earns zero base points. A new season's `status` is `SCHEDULED`, and its derived counters `rounds_completed` and `collected_fees_cents` read zero until events complete and fees are paid.

Classes are the season's eligibility and pricing units. A `LeagueAdmin` creates them under a season with a `code` — one of `CADET`, `JUNIOR`, `SENIOR`, or `HEAVY`, unique within the season, with a repeat refused as `ERR_DUPLICATE_CLASS_CODE` — an inclusive age window from `min_age` to `max_age`, the `min_combined_weight_kg` a driver-and-kart combination must meet on the scales (a positive number), the per-event `entry_fee_cents` (a non-negative integer of cents), and `rental_kart_allowed`, which admits or refuses rental entries. Each class echoes its parent `season_id`.

Activation moves the season `SCHEDULED → ACTIVE` and requires at least one class to exist; activating a classless season fails with `ERR_INVALID_STATE`. Season-gated configuration — creating events, opening registration, and any class change — is permitted only while the season is `ACTIVE` and is otherwise refused with `ERR_SEASON_NOT_ACTIVE`. Finalization moves `ACTIVE → FINALIZED` once at least one child event has itself reached `FINALIZED`; from that moment the final standings, computed with drop rounds and the championship tiebreak of §3.7, become the authoritative rank basis in place of the provisional totals. Concluding the awards moves `FINALIZED → AWARDS_CONCLUDED`: the banquet is held, each class's champion is the rank-1 row of its final standings, and the season is locked — any further class or event creation is refused with `ERR_INVALID_STATE`. Each of these three lifecycle calls advances the season's `version` by one.

### 3.2. Drivers and the Rental Fleet

Anyone may join the league by registering as a driver: a `Driver` self-registers, or a `LeagueAdmin` registers on their behalf, supplying `full_name`, `date_of_birth` as an ISO calendar date (the basis for class age checks at each event date), a positive `body_weight_kg`, and a `license_type` of `RENTAL` or `OWNER`. New drivers start `PENDING`. A `LeagueAdmin` promotes a driver `PENDING → ACTIVE`, may suspend with `ACTIVE → SUSPENDED`, and may reinstate with `SUSPENDED → ACTIVE`; each change advances the driver's `version`. Only `ACTIVE` drivers may enter events or book practice time — a `PENDING` or `SUSPENDED` driver attempting either is refused with `ERR_DRIVER_NOT_ACTIVE`.

The rental fleet is managed alongside the roster. A `LeagueAdmin` adds karts with a unique `fleet_number` and `eligible_class_codes`, the list of class codes the kart may race in; a kart starts `AVAILABLE`. Taking a kart out of service (`AVAILABLE → IN_MAINTENANCE`) and retiring it (`AVAILABLE` or `IN_MAINTENANCE → RETIRED`, a terminal state) share a no-active-reference precondition: the kart must not be referenced by any entry in `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, `TECH_PASSED`, or `GRID_LOCKED`, nor by any practice booking in `RESERVED` or `CHECKED_IN`; violating that precondition is refused with `ERR_INVALID_STATE`. Maintenance concludes with `IN_MAINTENANCE → AVAILABLE`. A kart that is not `AVAILABLE` cannot be assigned to a new entry or booking (`ERR_KART_UNAVAILABLE`).

### 3.3. Race Events and Entry Registration

Within an `ACTIVE` season, a `LeagueAdmin` schedules rounds as events, each with a `round_number` (a positive integer unique within the season — a repeat draws `ERR_DUPLICATE_ROUND`), an `event_date` (the reference date for driver age eligibility), and a `track_name`. Events begin `SCHEDULED`, and the season gate applies: attempting to create an event in a season that is not `ACTIVE` is refused with `ERR_SEASON_NOT_ACTIVE`. Opening registration moves the event `SCHEDULED → REGISTRATION_OPEN`, again gated on an `ACTIVE` season. The `RaceDirector` starts the event — `REGISTRATION_OPEN → IN_PROGRESS` — which requires at least one entry already in `TECH_PASSED` or `GRID_LOCKED` and immediately closes registration: any further entry creation fails with `ERR_EVENT_REGISTRATION_CLOSED`.

Entries are created while registration is open, by a `LeagueAdmin` or by a `Driver` for themselves, with a payload naming the `driver_id`, the `class_id` of a class in the event's season, the `entry_type` — `RENTAL` or `OWNER_DRIVER` — and, for rentals, the `kart_id`. Body rules come first: a `RENTAL` entry must carry `kart_id` and an `OWNER_DRIVER` entry must omit it, with violations answered by `ERR_INVALID_REQUEST`. Eligibility is then enforced in full at creation time. The driver's age in whole years at the `event_date` — the span from `date_of_birth` to `event_date`, reckoned at 365.25 days per year and rounded down — must fall within the class's inclusive window from `min_age` to `max_age`, else `ERR_CLASS_MISMATCH`. License and entry type must agree: a `RENTAL`-licensed driver may only file `RENTAL` entries, and an `OWNER_DRIVER` entry demands an `OWNER` license — mismatches are likewise `ERR_CLASS_MISMATCH`. A `RENTAL` entry into a class whose `rental_kart_allowed` is false is refused with `ERR_RENTAL_NOT_ALLOWED`, and the chosen kart's `eligible_class_codes` must contain the entry's class code, else `ERR_KART_CLASS_INELIGIBLE`. The kart must be `AVAILABLE` and not already assigned to another non-`WITHDRAWN` entry of the same event (`ERR_KART_UNAVAILABLE`), the driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), and a driver may hold at most one non-`WITHDRAWN` entry per event (`ERR_DUPLICATE_ENTRY`).

A created entry starts `ENTERED`, with its `entry_fee_cents` snapshotted from the class and its `fee_status` `UNPAID`. Settling the fee — by the owning driver or a `LeagueAdmin` — moves `fee_status` from `UNPAID` to `PAID` and adds the fee to the season's `collected_fees_cents`. Withdrawal, by the owning driver or a `LeagueAdmin`, moves an entry from `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, or `TECH_PASSED` to `WITHDRAWN`; `GRID_LOCKED` and `DISQUALIFIED` entries can no longer withdraw (`ERR_INVALID_STATE`). A withdrawn entry whose fee was `PAID` is refunded — `fee_status` becomes `REFUNDED` and the season total gives the fee back — and a rental entry's kart assignment for the event is released. Each entry carries its `event_id` for addressability, and its derived `tech_fail_count` and `event_points` track inspection failures (§3.4) and sporting yield (§3.5).

The remaining event lifecycle belongs to the officials. Completion — `IN_PROGRESS → COMPLETED`, by the `RaceDirector` — requires every child session to be `SCORED`. Finalization — `COMPLETED → FINALIZED` — requires that no incident of the event remains in `REPORTED`, `UNDER_REVIEW`, or `APPEALED` (`ERR_OPEN_INCIDENTS`); on finalization every result of the event's sessions that is still `PROVISIONAL` or `AMENDED` becomes `FINAL`, and the event counts toward the standings. A `LeagueAdmin` may instead cancel an event from `SCHEDULED`, `REGISTRATION_OPEN`, or `IN_PROGRESS`: the cancellation cascades, moving every child entry in `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, `TECH_PASSED`, or `GRID_LOCKED` to `WITHDRAWN`, refunding each withdrawn entry whose `fee_status` was `PAID` with `collected_fees_cents` recomputed accordingly, and excluding the event from all standings calculations. A `COMPLETED` or `FINALIZED` event cannot be cancelled (`ERR_INVALID_STATE`). Each of these event lifecycle calls advances the event's `version` by one.

### 3.4. Technical Inspection, Weight Compliance, and Grid Locking

A `RaceDirector` records each weigh-in against an entry, supplying the scale reading `measured_combined_weight_kg` (a positive number) and optional free-text `notes`; the server stamps the record with the caller's opaque identifier as `inspector_user_id` and keeps the entry's `entry_id` alongside. The `outcome` is computed, never asserted: the reading earns a `PASS` when it is greater than or equal to the class's `min_combined_weight_kg`, with exact equality on the scale passing, and anything below the minimum earns a `FAIL`. Inspection records are append-only, listed in recording order, and — per §2.4 — carry no `updated_at` or `version`.

Recording an inspection drives the entry's technical state machine. From `ENTERED` (the first inspection), from `TECH_FAILED` (a re-inspection), or from `TECH_PASSED` or `GRID_LOCKED` (a post-race re-weigh), the entry moves into `TECH_CHECK` and immediately resolves by outcome: a `PASS` settles it at `TECH_PASSED`, while a `FAIL` settles it at `TECH_FAILED` and adds one to the entry's `tech_fail_count`. The count is cumulative over the entry's life in the event, and the second failed inspection disqualifies the entry outright — `DISQUALIFIED`, a terminal state. A `FAIL` recorded against a `GRID_LOCKED` entry — the post-race weight failure — likewise disqualifies immediately, regardless of the count. Before the count reaches two, the re-inspection loop is open-ended: an entry may cycle `TECH_FAILED → TECH_CHECK → TECH_PASSED` as many times as the officials allow.

Disqualification, however it arrives, strips the entry's sporting yield for the event without rewriting history: every result the entry holds in the event's sessions has its `points_awarded` set to zero while its `finish_position` is left unchanged — no other competitor is moved up to fill the gap — and the entry's `event_points` is recomputed, which for a disqualified entry comes to zero. The season standings reflect the change on their next read.

When every kart is weighed and every fee settled, the `RaceDirector` locks the grid on an event that is `IN_PROGRESS`. The call is all-or-nothing across the event: every `TECH_PASSED` entry advances to `GRID_LOCKED` in one stroke, but if any non-`WITHDRAWN` entry is not in `TECH_PASSED` the whole call fails with `ERR_TECH_NOT_PASSED`, and if any non-`WITHDRAWN` entry's `fee_status` is not `PAID` the whole call fails with `ERR_ENTRY_FEE_UNPAID` (HTTP 402).

### 3.5. Sessions, Result Batches, and Scoring

Once the event is `IN_PROGRESS`, the `RaceDirector` builds its running order as sessions, each with a `session_type` of `PRACTICE`, `QUALIFYING`, `HEAT`, or `MAIN` and a `sequence` ordinal that is a positive integer unique within the event. Because the running order is a property of the event, session creation carries the OCC field `expected_event_version` per §2.6 and advances the event's `version` by one. A session is born `SCHEDULED`; the `RaceDirector` opens it (`SCHEDULED → OPEN`, which requires the parent event still `IN_PROGRESS`) and closes it (`OPEN → CLOSED`) when running ends. Each session echoes its parent `event_id`.

Results are submitted only against a `CLOSED` session, as one full batch: the `results` array carries one row per finisher with the `entry_id` — which must be a `GRID_LOCKED` entry of the session's event — the recorded `finish_position` (a positive integer), and `best_lap_ms` and `total_time_ms` (both positive integer milliseconds). Two rows for the same entry in one submission are refused with `ERR_DUPLICATE_RESULT`. A batch submitted while an earlier batch exists supersedes it: the previous rows are discarded and the new rows are recorded `PROVISIONAL`. The submission carries `expected_session_version` (§2.6) and advances the session's `version` by one; submitting against a session that is not `CLOSED` fails with `ERR_INVALID_STATE`.

Scoring — `CLOSED → SCORED` — is the reckoning. Attempting it from any state other than `CLOSED` fails with `ERR_SESSION_NOT_CLOSED`, and it is refused with `ERR_RESULTS_INCOMPLETE` until every `GRID_LOCKED` entry of the parent event holds a result row in the session. Scoring assigns each result's points. Results in `PRACTICE` and `QUALIFYING` sessions never earn points. In `HEAT` and `MAIN` sessions, each result's base points come from the season's `points_scheme` by finishing position — first place takes the array's first element, second place the second, and positions past the array's end take zero. The session's fastest lap goes to the result with the lowest `best_lap_ms`, a tie broken in favor of the better `finish_position`, and that result's `is_fastest_lap` flag is set; when the fastest finisher also placed tenth or better (`FASTEST_LAP_MAX_POSITION`), the season's `fastest_lap_bonus_points` are added to that result's base as a bonus. A result's `points_awarded` is base plus bonus — or zero if the entry has been `DISQUALIFIED`. Each entry's `event_points` is then recomputed as the sum of its `points_awarded` across the event's `HEAT` and `MAIN` sessions, and scoring advances the session's `version` by one. After `SCORED`, the session's results are immutable: any further batch submission fails with `ERR_INVALID_STATE`.

Results moved by a later penalty are the one exception, handled by the incident cascade of §3.6: a result whose finishing position changes passes from `PROVISIONAL` to `AMENDED`, further penalty applications or reversals keep an already-`AMENDED` result in `AMENDED`, and event finalization settles every `PROVISIONAL` or `AMENDED` result into `FINAL`.

### 3.6. Incident Reports, Adjudication, and Appeals

Any on-track official — a `RaceDirector` or a `Steward` — may report an incident against an entry in a session of the event, supplying the `entry_id`, the `session_id`, and a free-text `description`; the server records the caller's identifier as `reporter_user_id`, and the report opens in `REPORTED` status. A `Steward` opens review, moving the incident `REPORTED → UNDER_REVIEW`; the same open-review action also returns an `APPEALED` incident to `UNDER_REVIEW` for a second look. Each incident carries its parent `event_id`.

Adjudication is the steward's exclusive province and carries the segregation-of-duties rule of §2.1: the ruling steward's `X-User-ID` must differ from the incident's `reporter_user_id`, on pain of `ERR_SELF_ADJUDICATION`. The ruling itself is a `decision` of `UPHELD` or `DISMISSED`, recorded along with the steward's identifier as `adjudicator_user_id`. An upheld ruling also records a `penalty_kind` — `NONE`, `TIME_SECONDS`, or `DISQUALIFICATION` — with `penalty_seconds` required and positive exactly when the kind is `TIME_SECONDS` and null for any other kind (`ERR_INVALID_REQUEST`). Two state gates guard upheld rulings: a `TIME_SECONDS` penalty requires the incident's session to be `SCORED` and the parent event to be `IN_PROGRESS` or `COMPLETED`, and a `DISQUALIFICATION` requires the reported entry to be in `TECH_CHECK`, `TECH_PASSED`, or `GRID_LOCKED`; breaching either gate is `ERR_INVALID_STATE`.

An upheld ruling with `penalty_kind` `TIME_SECONDS` triggers the penalty cascade. First, the result of the reported entry in the reported session has the `penalty_seconds` added to its `penalty_seconds_applied`. Second, every result in that session is re-ranked by effective total time — the recorded `total_time_ms` plus one thousand milliseconds for each second of `penalty_seconds_applied` — ascending, with ties broken in favor of the result that held the better `finish_position` before the re-rank; the `finish_position` values are then rewritten to the new order, and every result whose position changed moves from `PROVISIONAL` to `AMENDED` with its `points_awarded` recomputed after the re-rank. Third, `points_awarded` is recomputed for every result of the session under the session-points rule of §3.5, each affected entry's `event_points` is recomputed, and the standings reflect the change on their next read. An upheld ruling with `penalty_kind` `DISQUALIFICATION` instead moves the entry to `DISQUALIFIED`, with all of the disqualification consequences of §3.4. An upheld ruling with `penalty_kind` `NONE` applies no sporting penalty at all.

The driver of the reported entry — and only that driver, else `ERR_NOT_ENTRY_DRIVER` — may appeal an upheld ruling, moving the incident `UPHELD → APPEALED`. Each incident allows at most one appeal: the attempt is refused with `ERR_APPEAL_LIMIT` once the incident's `appeal_count` has reached one, and a successful appeal adds one to that count. When a previously upheld incident is, after its appeal, re-adjudicated as `DISMISSED`, the penalty is reversed as compensation: the `penalty_seconds` are subtracted from the affected result's `penalty_seconds_applied`, and the session is re-ranked and recomputed exactly as in the upheld cascade, restoring the pre-penalty positions and points.

Open incidents block the close of an event's business: finalization is refused with `ERR_OPEN_INCIDENTS` while any incident of the event remains in `REPORTED`, `UNDER_REVIEW`, or `APPEALED`. `UPHELD` and `DISMISSED` are the incident's terminal states.

### 3.7. Season Standings, Drop Rounds, and the Championship Tiebreak

Standings are computed on read, per class: a standings request names the `class_id`, and the response carries the `season_id`, the `class_id`, and an array of `rows`, one per driver holding an entry in that class. Only counted events feed the totals — child events in `COMPLETED` or `FINALIZED` status; `CANCELLED` events are excluded — and the season's `rounds_completed` is exactly the count of those counted events. Because each driver holds at most one entry per event, a driver's per-event score is unambiguous: the `event_points` of that driver's entry in the event.

Each row reports two totals. The `provisional_points` are the plain sum of the driver's per-event scores over all counted events — nothing dropped. The `final_points` apply the season's drop-rounds rule: order the driver's per-event scores ascending and discard the first `drop_rounds` of them — when scores tie at the drop boundary, the event with the lower `round_number` is discarded first — then sum what remains. The discarded rounds are reported as `dropped_round_numbers`. If the season's `drop_rounds` meets or exceeds the number of counted events the driver scored in, the driver's `final_points` are zero and every one of their round numbers appears in `dropped_round_numbers`. Both totals are always computed, so identical data yields different totals whenever a driver's lowest round score is nonzero.

The rank basis is pinned by the season's status. Before the season reaches `FINALIZED`, rows rank by `provisional_points` descending, ties broken in favor of the driver who registered earlier (the lower `created_at`). Once the season is `FINALIZED`, rows rank by `final_points` descending, and ties run the championship tiebreak, which considers only each tied driver's counted — non-dropped — events and only their `MAIN`-session finish positions: first, the driver with more first-place `MAIN` finishes ranks higher; if still level, second-place `MAIN` finishes are compared, then third, and so on down the finishing order. If the countback fails to separate them, the driver whose best counted `MAIN` finish was achieved at the higher `round_number` — the more recent best result — ranks higher. Any tie still standing is broken in favor of the driver who registered earlier. Finalization is what makes these final standings authoritative; concluding the awards then crowns the rank-1 row of each class as its champion.

### 3.8. Practice Bookings and Track-Time Billing

Outside race events, a `Driver` books practice track time with a rental kart, supplying the `driver_id`, the `kart_id`, the window's `start_time` and `end_time`, and a `pricing_mode` of `FLAT` or `METERED`. The window must be well formed — `end_time` strictly after `start_time`, else `ERR_INVALID_REQUEST` — the driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), the kart must be `AVAILABLE` (`ERR_KART_UNAVAILABLE`), and the overlap and capacity checks of §2.10 apply. A created booking holds status `RESERVED`, with `minutes_used` and `fee_cents` null until the visit is complete.

The visit itself is two driver-scoped steps. Check-in moves `RESERVED → CHECKED_IN`; check-out moves `CHECKED_IN → COMPLETED` and settles the bill. At check-out, `minutes_used` is set to the whole-minute length of the booked window, and `fee_cents` is computed by the variant the booking's `pricing_mode` selected: a `FLAT` booking is charged a fixed $40.00 (4000 cents) regardless of the minutes used, while a `METERED` booking is charged by multiplying the minutes used by the $1.50-per-minute rate (150 cents) and then applying 8.25% tax on top, with the result rounded half-up to whole cents. Tax and rounding are pinned to the per-booking level at check-out — never applied across a sum of bookings — so any per-driver or per-day total is the plain sum of the already-rounded per-booking `fee_cents` values.

Cancellation releases the kart: the booking's owning driver, or a `LeagueAdmin`, moves `RESERVED → CANCELLED`, after which the window no longer counts against kart overlap or track capacity and subsequent overlapping bookings for the same kart are accepted. Each booking transition advances the booking's `version` by one, and each booking echoes its `booking_id`-addressable identifiers `driver_id` and `kart_id` for filtered listing.

## 4. Endpoint Definitions

Operations that create a new resource — a season, class, driver, kart, event, entry, inspection, session, result batch, incident, or practice booking — return `201 Created`. Operations that modify an existing resource, including every state transition, payment, withdrawal, scoring call, adjudication, appeal, and check-in/check-out/cancel, return `200 OK`. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/karting/seasons` | Create a season (starts `SCHEDULED`, counters zero) | LeagueAdmin |
| GET | `/karting/seasons/{season_id}` | Get a season, including computed `rounds_completed` and `collected_fees_cents` | Any |
| POST | `/karting/seasons/{id}/activate` | Activate a season (requires at least one class) | LeagueAdmin |
| POST | `/karting/seasons/{id}/finalize` | Finalize a season; final standings become the rank basis | LeagueAdmin |
| POST | `/karting/seasons/{id}/conclude-awards` | Conclude the awards banquet; crown champions; lock the season | LeagueAdmin |
| GET | `/karting/seasons/{id}/standings` | Computed standings rows per driver for a class (query: `class_id`) | Any |
| POST | `/karting/seasons/{id}/classes` | Create a race class for the season | LeagueAdmin |
| GET | `/karting/seasons/{id}/classes` | List the classes of a season | Any |
| GET | `/karting/classes/{class_id}` | Get one class | Any |
| POST | `/karting/drivers` | Register a driver (starts `PENDING`) | LeagueAdmin, Driver |
| GET | `/karting/drivers/{driver_id}` | Get a driver | Any |
| PATCH | `/karting/drivers/{driver_id}` | Transition driver status (`PENDING`/`ACTIVE`/`SUSPENDED`) | LeagueAdmin |
| POST | `/karting/karts` | Add a rental kart (starts `AVAILABLE`) | LeagueAdmin |
| GET | `/karting/karts/{kart_id}` | Get a kart | Any |
| GET | `/karting/karts` | List karts; optional `status` filter; paginated | Any |
| PATCH | `/karting/karts/{kart_id}` | Transition kart status (`AVAILABLE`/`IN_MAINTENANCE`/`RETIRED`) | LeagueAdmin |
| POST | `/karting/seasons/{id}/events` | Create a race event (round) in the season | LeagueAdmin |
| GET | `/karting/seasons/{id}/events` | List the events of a season | Any |
| GET | `/karting/events/{event_id}` | Get an event | Any |
| POST | `/karting/events/{id}/open-registration` | Open registration for the event | LeagueAdmin |
| POST | `/karting/events/{id}/start` | Start the event; closes entry creation | RaceDirector |
| POST | `/karting/events/{id}/complete` | Complete the event (requires all sessions scored) | RaceDirector |
| POST | `/karting/events/{id}/finalize` | Finalize the event (requires no open incidents); results become `FINAL` | RaceDirector |
| POST | `/karting/events/{id}/cancel` | Cancel the event; entries withdrawn, paid fees refunded | LeagueAdmin |
| POST | `/karting/events/{id}/lock-grid` | Lock the grid: all `TECH_PASSED` entries advance together | RaceDirector |
| POST | `/karting/events/{id}/entries` | Enter a driver into the event (fee snapshotted from the class) | LeagueAdmin, Driver |
| GET | `/karting/events/{id}/entries` | List entries of an event; paginated | Any |
| GET | `/karting/entries/{entry_id}` | Get one entry, including computed `event_points` and `tech_fail_count` | Any |
| GET | `/karting/entries` | Filtered list of entries across events (`driver_id`, `class_id`, `kart_id`); paginated | Any |
| POST | `/karting/entries/{id}/pay` | Mark the entry fee `PAID` | LeagueAdmin, Driver |
| POST | `/karting/entries/{id}/withdraw` | Withdraw an entry; paid fee refunded | LeagueAdmin, Driver |
| POST | `/karting/entries/{id}/inspections` | Record a weigh-in; computes `outcome` and drives the entry's tech state | RaceDirector |
| GET | `/karting/entries/{id}/inspections` | List the inspections of an entry (append-only) | Any |
| POST | `/karting/events/{id}/sessions` | Create a session (OCC via `expected_event_version`) | RaceDirector |
| GET | `/karting/events/{id}/sessions` | List sessions of an event | Any |
| GET | `/karting/sessions/{session_id}` | Get a session | Any |
| PATCH | `/karting/sessions/{session_id}` | Transition session status (`OPEN`/`CLOSED`) | RaceDirector |
| POST | `/karting/sessions/{id}/results` | Submit the full result batch (supersedes any prior batch; OCC via `expected_session_version`) | RaceDirector |
| POST | `/karting/sessions/{id}/score` | Score the session: fastest lap and points awarded | RaceDirector |
| GET | `/karting/sessions/{id}/results` | List results of a session | Any |
| GET | `/karting/entries/{id}/results` | List results of an entry across sessions | Any |
| POST | `/karting/events/{id}/incidents` | Report an incident against an entry in a session | RaceDirector, Steward |
| GET | `/karting/events/{id}/incidents` | List incidents of an event | Any |
| GET | `/karting/incidents/{incident_id}` | Get an incident | Any |
| GET | `/karting/incidents` | Filtered list of incidents (`entry_id`, `session_id`); paginated | Any |
| POST | `/karting/incidents/{incident_id}/open-review` | Open steward review of an incident | Steward |
| POST | `/karting/incidents/{incident_id}/adjudicate` | Adjudicate an incident under review (`decision`, optional penalty fields) | Steward |
| POST | `/karting/incidents/{incident_id}/appeal` | Appeal an upheld incident (the entry's driver only; at most one) | Driver |
| POST | `/karting/practice-bookings` | Book track time with a rental kart (half-open window; overlap and capacity checks) | Driver |
| GET | `/karting/practice-bookings` | Filtered list of practice bookings (`driver_id`, `kart_id`); paginated | Any |
| GET | `/karting/practice-bookings/{booking_id}` | Get a booking | Any |
| POST | `/karting/practice-bookings/{booking_id}/check-in` | Check in to a booking (owning driver) | Driver |
| POST | `/karting/practice-bookings/{booking_id}/check-out` | Check out; sets `minutes_used` and `fee_cents` per `pricing_mode` | Driver |
| POST | `/karting/practice-bookings/{booking_id}/cancel` | Cancel a booking; releases the kart window | LeagueAdmin, Driver |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_ADJUDICATION` | 403 Forbidden |
| `ERR_NOT_ENTRY_DRIVER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEASON_NOT_ACTIVE` | 409 Conflict |
| `ERR_EVENT_REGISTRATION_CLOSED` | 409 Conflict |
| `ERR_DRIVER_NOT_ACTIVE` | 409 Conflict |
| `ERR_KART_UNAVAILABLE` | 409 Conflict |
| `ERR_CLASS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RENTAL_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_KART_CLASS_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENTRY` | 409 Conflict |
| `ERR_DUPLICATE_ROUND` | 409 Conflict |
| `ERR_DUPLICATE_CLASS_CODE` | 409 Conflict |
| `ERR_DUPLICATE_RESULT` | 409 Conflict |
| `ERR_TECH_NOT_PASSED` | 409 Conflict |
| `ERR_ENTRY_FEE_UNPAID` | 402 Payment Required |
| `ERR_SESSION_NOT_CLOSED` | 409 Conflict |
| `ERR_RESULTS_INCOMPLETE` | 409 Conflict |
| `ERR_OPEN_INCIDENTS` | 409 Conflict |
| `ERR_APPEAL_LIMIT` | 409 Conflict |
| `ERR_BOOKING_OVERLAP` | 409 Conflict |
| `ERR_TRACK_CAPACITY_EXCEEDED` | 409 Conflict |
