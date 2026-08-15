# Cycling & Triathlon Event Operations API — Product Requirements Document

## 1. Introduction

Staging a USA Triathlon–sanctioned cycling or triathlon event is an exercise in coordinated constraint management. Road closures must be permitted by public authorities before the course can be published; start waves must be built, athletes licensed, and aid stations staffed and stocked before racing can begin; and a single water-temperature reading on race morning can convert the entire event from a triathlon into a duathlon. This document specifies the Cycling & Triathlon Event Operations API, the operational backbone a race organization uses to run one sanctioned event end to end: course permitting and road-closure coordination, transition-area bike check-in and check-out security, wave and start-order assignment with drafting rules, aid-station supply and volunteer staffing, swim-safety and weather cancellation decisions, chip timing across multiple disciplines and transitions, results, penalties, and appeals.

Two governing ideas shape every rule in this specification. First, the event carries a `posture` — a coarse lifecycle position that gates every forward-progress operation, so that nothing can be published before permits are in place, nothing can start before the swim decision is made, and nothing can be finalized while a penalty or an appeal remains unresolved. Second, the server runs on a logical clock rather than wall-clock time; every deadline, timestamp, refund tier, and appeal window in this document is evaluated against that clock. Because results are derived by replaying an ordered stream of chip reads, and because entry-fee refunds and competition integrity are at stake, thresholds, rounding order, and transition preconditions are pinned down exactly wherever they apply.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly six roles: `RaceDirector`, `PermitCoordinator`, `Referee`, `Timer`, `VolunteerCoordinator`, and `Athlete`. A request whose headers are missing or whose role is not one of these six is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to call the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403); the full role-to-endpoint mapping is given in §4.

The six roles partition the operating staff of a race. A `RaceDirector` owns the event lifecycle: event creation, posture advancement, start, finalization, cancellation, waves, athletes, aid stations, water allocation, the ops checkpoint, and the logical clock. A `PermitCoordinator` handles course permitting and road-closure coordination with public authorities. A `Referee` is the head official, responsible for penalty assessment and amendment, appeal review and decision, shared authority over safety assessments, and marking did-not-finish athletes. A `Timer` runs chip timing: recording reads, validating or invalidating them, and correcting official results. A `VolunteerCoordinator` staffs the aid stations. An `Athlete` is a registered participant acting on their own records.

For five of the six roles — `RaceDirector`, `PermitCoordinator`, `Referee`, `Timer`, and `VolunteerCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `assessed_by_user_id` on a Penalty when a `Referee` assesses the penalty, or as `decided_by_user_id` on an Appeal when a `Referee` decides one) but does not compare it to any entity's `id`. When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting `Athlete`; ownership checks on any resource that references an `Athlete` compare the resource's foreign-key field to `X-User-ID`.

Concretely, an `Athlete`-role caller may only act on their own records: registering themselves (the payload's `athlete_id` must equal `X-User-ID`), and paying, withdrawing, checking a bike in or out, or filing an appeal only where the registration's `athlete_id` — for an appeal, the penalized registration's `athlete_id` — equals `X-User-ID`. Any mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403). The duty-separation comparison on appeal decisions also keys on `X-User-ID`, but it is evaluated as its own later rule (§2.10), not as part of this ownership check. Every read endpoint in §4 is callable by all six roles.

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

List endpoints are paginated through two query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100 — an unparseable `limit` falls back to 10, and a value below 1 or above 100 is clamped to that bound. `offset` specifies how many items to skip and defaults to 0 — an unparseable `offset` falls back to 0 and a negative value is clamped to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties retaining creation order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in this API — Event, RoadSegment, CoursePermit, Wave, Athlete, Registration, BikeCheck, AidStation, VolunteerAssignment, TimingRecord, Result, Penalty, Appeal, and SafetyAssessment — carries the same four system-managed fields:

- **`id`** (string): a unique, server-minted UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- **`version`** (integer): a system-managed integer that starts at 1 when the resource is created, increments by one on every mutation of the resource, and forms the basis of optimistic concurrency control (§2.8).

### 2.5. The Logical Clock and Race Time

The server maintains a logical clock that governs every temporal rule in this document: confirm and check-in deadlines, appeal windows, refund tiers, the ops checkpoint, and every field described as stamped from the clock (`checked_in_at`, `checked_out_at`, `assessed_at`, `withdrawn_at`, `actual_start_time`). Before any operator intervention the clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `RaceDirector`-only test-driving capability, `POST /_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The supplied value must parse as an ISO 8601 datetime (`ERR_VALIDATION` otherwise) but is otherwise accepted verbatim — the clock may be set to any instant, earlier or later, with no monotonicity check. The clock retains the supplied string verbatim: every field stamped from the clock carries that exact string, and an instant computed arithmetically from a clock reading — `appeal_window_expires_at` (§3.7) — is rendered in the clock string's own lexical precision, carrying a three-digit fractional second exactly when the clock string itself carries a fractional part and whole seconds otherwise.

### 2.6. Race Posture and the Swim-Decision Dimension

An Event's `posture` walks a one-way course — `DRAFT`, then `PERMITTED`, then `PUBLISHED`, then `LIVE`, and finally one of the terminal states `FINALIZED` or `CANCELLED` — and gates every forward-progress operation in the system: segments and permits are assembled while `DRAFT`; registrations confirm and bikes rack only while `PUBLISHED`; timing flows while `LIVE`. Cancellation is reachable from `PERMITTED`, `PUBLISHED`, or `LIVE` — never from `DRAFT`, and never after finalization.

Independently of posture, the same Event carries a `swim_status` dimension with values `PENDING_DECISION`, `SWIM_ON`, `SWIM_CANCELLED`, and `NO_SWIM`. At creation, an event whose `has_swim` flag is true starts at `PENDING_DECISION`; an event without a swim leg starts at `NO_SWIM`, which has no transitions. The two dimensions evolve in parallel: publishing the course says nothing about the swim, and a swim cancellation may arrive before or after racing begins — with one exception, covered in §3.5, that a cancelled swim cannot be reinstated while the event's posture is `LIVE`.

### 2.7. Precision, Units, and Rounding

All durations in this API — splits, totals, and penalty seconds — are integer numbers of seconds; no fractional seconds appear anywhere. All money is handled as integer cents, and refund arithmetic uses a pinned rounding order: the refundable base is rounded down to a whole cent first, the processing fee is then computed on that rounded base and rounded up to a whole cent, and the fee is subtracted from the base. The two rounding steps are never combined into a single sum-then-round. Water temperatures are recorded as supplied (conventionally with one decimal place), and the interval-conflict checks used for permit windows and volunteer shifts compare the parsed datetimes at their full supplied precision.

### 2.8. Optimistic Concurrency Control

Two write endpoints in this API are guarded by optimistic concurrency control, and they are the only endpoints that accept a version field. Amending an assessed penalty (the `POST /penalties/{id}/amend` capability) requires `expected_penalty_version` in the request body, carrying the version of the Penalty the client last observed; if it does not match the Penalty's current `version`, the request is rejected with `ERR_STALE_PENALTY_VERSION` (HTTP 412). Correcting an official result (the `POST /results/{id}/corrections` capability) requires `expected_result_version`, carrying the version of the Result the client last observed; a mismatch with the Result's current `version` is rejected with `ERR_STALE_RESULT_VERSION` (HTTP 412). Because both amendments and corrections legitimately supersede earlier values, the version check is the only thing distinguishing a current view from a stale one. No other endpoint takes a version field; all other mutations proceed without an OCC check. On both guarded endpoints the stale-version check is evaluated immediately after the operation's from-state check, so a request that fails the from-state requirement is rejected with `ERR_INVALID_STATE` even when its expected version is also stale.

### 2.9. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers left to right — event first, then the child within that event, then any grandchild — and reject the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. A request targeting a wave under a non-existent event therefore fails on the event id before the wave id is ever examined. The same ordering applies to creation and modification operations addressed under a parent. Requests addressed to unknown paths, or to known paths with an unsupported method, are likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.10. Validation Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed order and surfaces the first failure. Authentication comes first (missing or unrecognized headers, `ERR_UNAUTHENTICATED`), followed by role authorization (`ERR_FORBIDDEN`), then left-to-right path existence (`ERR_NOT_FOUND`), then — for `Athlete`-role callers — the self-ownership comparison (on registration creation, where the comparison needs the payload's `athlete_id`, it is evaluated immediately after the required-field check that extracts that field), and then request-body validation: required fields, enum membership, field formats, datetime ordering where an end must be strictly later than its start, and the `reduced_seconds` range on appeal decisions, all under `ERR_VALIDATION` (HTTP 400). After body validation come the integrity-of-competition guards (an open appeal blocking withdrawal, `ERR_APPEAL_PENDING`; an appeal decider who assessed the penalty, `ERR_SEGREGATION_OF_DUTIES`), then state-machine from-state validity (`ERR_INVALID_STATE`), then the requirement that an appealed penalty still be `ASSESSED` (`ERR_PENALTY_NOT_ASSESSED`). Event-posture gates are evaluated next (`ERR_EVENT_POSTURE` and the advance, start, and finalize gate errors), followed by logical-clock windows (confirm, check-in, and appeal-filing deadlines), then athlete-license standing (`ERR_ATHLETE_SUSPENDED`), and finally the operation-specific business constraints: bib-code match, duplicate bike check-in, permit-window conflict, volunteer-shift overlap, the draft-legal-wave restriction, the refund-destination requirement, and the water-deallocation precondition.

## 3. Business Logic & Workflows

### 3.1. Course Permitting and Road-Closure Coordination

An event begins in `DRAFT` posture, created by a `RaceDirector` with a `name`, a `start_date` marking the scheduled first-wave start, a `has_swim` flag distinguishing triathlons from bike/run-only formats, a `water_pool_units` budget of total event water, and an optional `appeal_window_minutes` that defaults to 60 minutes when omitted or supplied as null. At creation the event's `water_pool_remaining` equals `water_pool_units` and its `ops_run_index` checkpoint counter starts at 0.

With the event on file, a `PermitCoordinator` maps the course as a set of road segments, each created with a `name` (for example, "Main St mile 2-8"), a `length_km`, and a planned closure window from `closure_start` to `closure_end`, where the end must be strictly later than the start. Each segment belongs to its event through `event_id`. Against each segment the coordinator files one or more course permits, each naming an `authority_name` (city, county, or state police) and a requested window from `requested_start` to `requested_end`, again with the end strictly later than the start; the permit carries its segment's `road_segment_id` and enters as `DRAFT`.

A permit's lifecycle is cyclic. Submitting moves `DRAFT` to `SUBMITTED`; the same submit action resubmits a `REJECTED` permit, clearing its `rejection_reason` back to null, and this reject–resubmit loop may repeat without bound. Rejection records the request body's `reason` onto `rejection_reason`. Approval is guarded by a corridor-conflict rule: within the same `road_segment_id`, no two `APPROVED` permits may sit within a 30-minute buffer of one another. A conflict exists when the candidate's `requested_start` falls strictly earlier than the other permit's `requested_end` plus 30 minutes and, symmetrically, the other permit's `requested_start` falls strictly earlier than the candidate's `requested_end` plus 30 minutes; touching at exactly 30 minutes of separation is allowed because both comparisons are strict. A conflicting approval is rejected with `ERR_PERMIT_WINDOW_CONFLICT`.

Before the event can leave `DRAFT`, the permitting gate must pass: advancing the posture from `DRAFT` to `PERMITTED` requires at least one road segment to exist, and every segment must hold at least one `APPROVED` permit whose requested window covers the segment's planned closure — the permit's `requested_start` no later than the segment's `closure_start` and its `requested_end` no earlier than the segment's `closure_end`. A failure on either count is rejected with `ERR_SEGMENT_NOT_COVERED`. Each successful posture advance increments the event's `version` by one.

### 3.2. Waves, Divisions, and the Athlete Roster

Start waves slice the field into manageable groups. A `RaceDirector` creates each wave with a `label` (such as "M18-39 AG"), a `division` of either `AGE_GROUP` or `ELITE`, a `scheduled_start_time`, a `capacity` cap on assigned athletes, a `draft_legal` flag recording whether drafting is permitted (typical of `ELITE` racing), and an inclusive age window from `age_band_min` to `age_band_max` (`age_band_max` must be greater than or equal to `age_band_min`, else `ERR_VALIDATION`). Age for band purposes is computed calendar-year-wise: an athlete's `age_at_event` is the year of the event's `start_date` minus the year of the athlete's `birth_date`. A new wave opens in `OPEN` status with `assigned_count` at 0 and belongs to its event via `event_id`.

A wave's occupancy is derived, not declared: `assigned_count` counts the registrations whose `wave_id` points at the wave and whose status is one of `CONFIRMED`, `RACKED`, `RACING`, `FINISHED`, or `DSQ`. When the count reaches `capacity` the wave flips automatically from `OPEN` to `FULL`; when the count later drops below `capacity` it flips back to `OPEN` and immediately runs a waitlist-promotion sweep for that wave (§3.4). A `RaceDirector` may also close an `OPEN` wave manually, moving it to `CLOSED`, and later reopen it — reopening requires `assigned_count` below `capacity` and is rejected with `ERR_INVALID_STATE` otherwise, and a successful reopen likewise triggers a promotion sweep.

The athlete roster lives in the event's scope: a `RaceDirector` creates each athlete record with a `full_name`, a `birth_date` as an ISO `YYYY-MM-DD` date, and the athlete's USA Triathlon `license_number`; the record carries the event's `event_id` and starts with `license_status` `ACTIVE`. Suspension is the heavy hammer. Moving an athlete to `SUSPENDED` cascades through every registration of theirs in `ENTERED`, `PAID`, `CONFIRMED`, `WAITLISTED`, or `RACKED`, forcing each to `WITHDRAWN` with a tiered provisional refund computed per the withdrawal rule in §3.4 — the cascade applies neither the open-appeal guard nor the refund-destination requirement of §3.4, and re-asserting `SUSPENDED` on an already-suspended athlete runs no cascade; every freed wave slot recomputes its wave's `assigned_count` and status and triggers waitlist promotion. Reinstatement back to `ACTIVE` is permitted freely but deliberately does not undo any prior withdrawal cascade.

### 3.3. Aid Stations, Water Logistics, and Volunteer Staffing

Aid stations keep athletes fueled and the permit authorities satisfied. A `RaceDirector` creates each station with a `name` (for example, "AS-1 Bike km 10"), a `location_km` fixing its position on the course, a `required_volunteers` minimum staffing level, and a `required_water_units` minimum supply level. A new station holds `allocated_water_units` 0 and `confirmed_volunteer_count` 0, and therefore reports `readiness_status` `UNDERSTAFFED`. Each station carries its event's `event_id`.

Readiness is a two-test derivation, recomputed whenever staffing or water changes — on station creation, on volunteer confirmation or no-show, and on water allocation or deallocation. If `confirmed_volunteer_count` is below `required_volunteers`, the station is `UNDERSTAFFED`. Otherwise, if `allocated_water_units` is below `required_water_units`, the station is `WATER_SHORT`. Otherwise it is `READY`. The boundaries are inclusive on the satisfied side: a count exactly equal to its requirement passes that test. The `confirmed_volunteer_count` itself counts only assignments in `CONFIRMED` status.

Water moves out of the event pool through a waterfall allocation run by the `RaceDirector`. Stations are visited in `location_km` ascending order, with `created_at` ascending breaking ties; each station receives the smaller of its remaining deficit (`required_water_units` minus its current `allocated_water_units`) and the water still remaining in the pool, floored at zero so a station already at or over its requirement neither gains nor loses water. The grant is added to the station's `allocated_water_units` and subtracted from the pool, and every station visited has its `version` incremented whether or not its allocation changed; when the walk ends, the event's `water_pool_remaining` — always `water_pool_units` minus the total allocated across all of the event's stations — is refreshed, readiness is re-derived at every station, and the event's `version` increments by one. A station's water can also be returned to the pool: deallocation requires `allocated_water_units` above zero (`ERR_WATER_NOT_ALLOCATED` otherwise), zeroes the station's allocation, adds the prior allocation back to `water_pool_remaining`, re-derives readiness, and increments the event's `version` by one.

Staffing is offered shift by shift. A `VolunteerCoordinator` creates an assignment against a station — the record carries the station's `aid_station_id` — with an opaque `volunteer_id` (not tied to any persisted entity), a `shift_start`, and a `shift_end` strictly later than the start; the assignment enters as `OFFERED`. Confirming a shift checks for double-booking across all of that volunteer's `CONFIRMED` assignments using half-open interval semantics: a conflict exists when the candidate's `shift_start` is strictly earlier than the other shift's `shift_end` and the other shift's `shift_start` is strictly earlier than the candidate's `shift_end`, and a conflicting confirmation is rejected with `ERR_SHIFT_OVERLAP`. Purely touching windows — one shift starting exactly when another ends — are allowed, and unlike the permit-corridor rule there is no buffer. Confirmation moves the assignment to `CONFIRMED` and recomputes the station's count and readiness. Declining moves `OFFERED` to `DECLINED`, which is terminal. Marking a no-show moves `CONFIRMED` to `NO_SHOW`, also terminal, decrementing the station's `confirmed_volunteer_count` by one and re-deriving readiness.

Publishing the event — advancing posture from `PERMITTED` to `PUBLISHED` — is where these logistics harden into a gate: at least one wave must be `OPEN` (`ERR_NO_OPEN_WAVE`), and every aid station of the event must be `READY` (`ERR_AID_STATION_NOT_READY`).

### 3.4. Registration, Wave Assignment, and Withdrawal Refunds

A registration binds an athlete to the event. It is created — by a `RaceDirector`, or by an `Athlete`-role caller registering themselves — with an `athlete_id`, a `division` of `AGE_GROUP` or `ELITE`, and an `entry_fee_cents` amount paid — a non-negative integer (`ERR_VALIDATION` otherwise) — and it enters in `ENTERED` status carrying the event's `event_id`. The athlete's license must be `ACTIVE` at creation (`ERR_ATHLETE_SUSPENDED`). The event's registration list can be filtered by `athlete_id`, `wave_id`, or `status`.

Payment moves `ENTERED` to `PAID`, again gated on an `ACTIVE` license; the athlete or a `RaceDirector` may record it. Confirmation is where the wave selector runs, and it is a `RaceDirector`-only action guarded by three preconditions evaluated in order: the event posture must be `PUBLISHED` (`ERR_EVENT_POSTURE`), the logical clock must be strictly earlier than 24 hours before the event's `start_date` (`ERR_CONFIRM_WINDOW_CLOSED`), and the athlete's license must still be `ACTIVE` (`ERR_ATHLETE_SUSPENDED`).

The selector is fully deterministic. A wave is eligible when it is `OPEN`, its `assigned_count` is below `capacity`, its `division` equals the registration's `division`, and the athlete's `age_at_event` falls within the wave's `age_band_min` to `age_band_max` inclusive. Eligible waves are ranked by `scheduled_start_time` ascending, with ties broken by the wave's `created_at` ascending — never by id. When the eligible pool is empty the registration moves from `PAID` to `WAITLISTED` with no `wave_id`. Otherwise the first-ranked wave is assigned: the registration moves to `CONFIRMED`, its `wave_id` is set, its `age_at_event` is stamped, the wave's `assigned_count` increases by one, and a wave that thereby reaches `capacity` flips to `FULL`.

Waitlisted athletes are not forgotten. Whenever a slot frees — a `CONFIRMED` or `RACKED` withdrawal, an athlete suspension, a wave reopening, or the ops-checkpoint sweep (§3.7) — the oldest eligible `WAITLISTED` registration, ordered by the registration's `created_at` ascending, is promoted into the wave through exactly the same eligibility predicate: its status becomes `CONFIRMED`, its `wave_id` is set, its `age_at_event` is stamped, the wave's count is incremented, and `FULL` is re-derived at capacity.

Withdrawal is available from `ENTERED`, `PAID`, `CONFIRMED`, `WAITLISTED`, or `RACKED`, to the athlete themselves or a `RaceDirector`. Two guards apply: no penalty of the registration may have an appeal in `FILED` or `UNDER_REVIEW` (`ERR_APPEAL_PENDING`), and when the computed provisional refund is above zero a `refund_destination` payout destination must be supplied (`ERR_REFUND_DESTINATION_REQUIRED`, HTTP 400). A supplied `refund_destination` is recorded on the registration, and a withdrawal never clears the registration's `wave_id`. The provisional refund is tiered on how far out the withdrawal lands: let the days until the event be the whole number of days between `withdrawn_at` and the event's `start_date`. Sixty or more days out, the refundable base is 75 percent of `entry_fee_cents`; from 30 up to and including 59 days out, 50 percent; fewer than 30 days out, zero. The base is rounded down to whole cents, a processing fee of 10 percent of that rounded base is rounded up to whole cents, and `refund_estimate_cents` is the base minus the fee. The estimate is stored immediately, `refund_final_cents` stays null pending settlement, and `withdrawn_at` is stamped from the clock. A withdrawal from `CONFIRMED` or `RACKED` additionally frees the wave slot — `assigned_count` drops by one and a `FULL` wave reopens to `OPEN` — and immediately promotes the oldest eligible waitlisted registration into the freed slot; a `WAITLISTED` withdrawal simply leaves the queue. `WITHDRAWN` is terminal, as are `EXPIRED` and `DSQ`.

### 3.5. Swim Safety, Transition Security, and Starting the Race

For an event with `has_swim`, the swim leg lives under a recorded safety decision. A `RaceDirector` or `Referee` records a safety assessment with the measured `water_temp_celsius` and a `lightning_within_10km` flag; each assessment carries the event's `event_id` and enters as `RECORDED`. The derived `outcome` is `SWIM_CANCEL` when the water is colder than 12.0 degrees, warmer than 31.0 degrees, or lightning is present within ten kilometers, and `SWIM_OK` otherwise — the boundaries are inclusive on the proceed side, so exactly 12.0 degrees and exactly 31.0 degrees both proceed. Recording a new assessment supersedes the event's previous `RECORDED` assessment, moving it to `SUPERSEDED` (terminal), and flips the event's `swim_status` to match the new outcome. An assessment may also be recorded on an event without a swim leg: it enters as `RECORDED` and supersedes as usual but never changes the `NO_SWIM` swim_status.

The swim dimension interacts with racing in both directions. From `PENDING_DECISION`, an assessment moves the event to `SWIM_ON` or `SWIM_CANCELLED` according to its outcome; from `SWIM_ON`, a later cancellation moves it to `SWIM_CANCELLED`. Any transition into `SWIM_CANCELLED` recomputes every existing result of the event under the duathlon variant described in §3.6 — `swim_seconds` and `t1_seconds` become zero and the bike split is measured from the wave's `actual_start_time` — and recomputes division ranks. The reverse, reinstating a cancelled swim from `SWIM_CANCELLED` back to `SWIM_ON`, recomputes results under the standard triathlon variant but is forbidden while the event's posture is exactly `LIVE` (`ERR_INVALID_STATE`): the swim cannot be reinstated while racing is underway.

Transition-area security runs on bib codes. Bike check-in — by the athlete or a `RaceDirector` — requires the event to be `PUBLISHED` (`ERR_EVENT_POSTURE`), the logical clock strictly earlier than the event's `start_date` (`ERR_CHECKIN_WINDOW_CLOSED`), and no other `CHECKED_IN` bike check on the same registration (`ERR_DUPLICATE_BIKE_CHECKIN`). Under the §2.10 ordering, the from-state requirement — the registration must be `CONFIRMED` — is evaluated before that duplicate guard, so a repeat check-in against a registration an earlier check-in has already moved to `RACKED` is rejected with `ERR_INVALID_STATE`. A successful check-in presents a `bib_code`, creates the BikeCheck record (carrying the registration's `registration_id`) in `CHECKED_IN` status with `checked_in_at` stamped from the clock, moves the registration from `CONFIRMED` to `RACKED`, and creates the athlete's Result one-for-one with the registration: `PROVISIONAL`, all five splits null, `penalty_seconds_total` zero. Check-out first requires an open `CHECKED_IN` record on the registration — when none exists, including on a repeated check-out, the request is rejected with `ERR_INVALID_STATE`, and this requirement is evaluated before the registration-state check — and is then permitted only once the registration is `FINISHED` or `DNF` (`ERR_INVALID_STATE`) and only when the presented `bib_code` equals the open check-in's `bib_code` (`ERR_BIB_MISMATCH`); it moves the record to `CHECKED_OUT`, terminal, and stamps `checked_out_at`.

Starting the race moves the posture from `PUBLISHED` to `LIVE`. For a `has_swim` event the swim decision must already be made — `swim_status` `SWIM_ON` or `SWIM_CANCELLED` — otherwise the start is rejected with `ERR_SWIM_DECISION_PENDING`. A successful start stamps every wave's `actual_start_time` from the logical clock, and this instant — not `scheduled_start_time` — becomes the basis of every split computation; all `RACKED` registrations move to `RACING`, and the event's `version` increments by one.

### 3.6. Timing, Results, and Rankings

Chip timing is an append-then-curate stream. A `Timer` records each read against a registration — the record carries its `registration_id` — with a `discipline` of `SWIM`, `T1`, `BIKE`, `T2`, or `FINISH` (the finish-line read marks run completion) and the chip's `recorded_at` timestamp; the record enters as `RECORDED`. The registration's timing list can be filtered by `discipline`.

Curation happens read by read. Validating a `RECORDED` record requires the registration to be `RACING` or `FINISHED` (`ERR_INVALID_STATE`) and moves the record to `VALIDATED`; invalidating moves a `RECORDED` or `VALIDATED` record to `INVALIDATED`, which is terminal. Every validation or invalidation replays the athlete's result from scratch: the projection walks the registration's `VALIDATED` records in `recorded_at` ascending order — `RECORDED` and `INVALIDATED` records never enter the computation, and when several `VALIDATED` records share a discipline the one with the latest `recorded_at` governs — and measures each split against the wave's `actual_start_time`. Under the standard variant (swim not cancelled), `swim_seconds` runs from the wave's actual start to the `SWIM` read, `t1_seconds` from `SWIM` to `T1`, `bike_seconds` from `T1` to `BIKE`, `t2_seconds` from `BIKE` to `T2`, and `run_seconds` from `T2` to `FINISH`. Under the duathlon variant (swim cancelled), `swim_seconds` and `t1_seconds` are zero, `bike_seconds` runs from the wave's `actual_start_time` to the `BIKE` read, and `t2_seconds` and `run_seconds` are measured as in the standard variant. Splits are computed as a strict chain from the wave's actual start: each split is computed only when its own bounding reads and every upstream split are present, so the first missing read nulls its split and every later split (under the duathlon variant `swim_seconds` and `t1_seconds` are fixed at zero and the chain begins at the bike leg). `provisional_total_seconds` — the sum of the five splits, excluding all penalties, even confirmed ones — remains null until the chain completes through a validated `FINISH` record.

Two transitions ride on this replay. When a `FINISH` record becomes `VALIDATED`, the registration moves from `RACING` to `FINISHED` regardless of chain completeness, while the result's `finish_timestamp` takes the record's `recorded_at` and the provisional total is computed only when the split chain completes; division ranks are recomputed. Conversely, invalidating a `FINISH` record while the registration is `FINISHED` reverts it to `RACING` and returns the provisional totals to null. A `Referee` or `RaceDirector` may instead mark a racing athlete did-not-finish, moving `RACING` to `DNF`; the result then stays `PROVISIONAL` with null totals and a null rank.

The headline totals layer on top of the splits. `penalty_seconds_total` sums the `seconds` of the registration's penalties in `CONFIRMED` status only — assessed and overturned penalties contribute nothing. `official_total_seconds`, populated only while the result is `OFFICIAL`, is the provisional total plus `penalty_seconds_total`; for identical split data the two totals differ whenever a confirmed penalty exists. `effective_total_seconds` is the official total when `OFFICIAL` and the provisional total otherwise, and it is the ranking key: within each `division`, `division_rank` is the 1-based position by `effective_total_seconds` ascending over results whose registrations are not `DSQ` and whose effective totals are non-null, with ties broken by `finish_timestamp` ascending and then by the registration's `created_at` ascending. Disqualified and unfinished results carry a null `division_rank`. The event's results list can be filtered by `registration_id` or `division`, and reading a registration's own result returns a zero- or one-element array.

After finalization, official results can still be amended, carefully and under optimistic concurrency. A `Timer` submits a correction naming the `discipline` (`SWIM`, `T1`, `BIKE`, `T2`, or `RUN`), the `corrected_seconds` replacement value, and `expected_result_version` carrying the version of the result last observed; a stale version is rejected with `ERR_STALE_RESULT_VERSION` (HTTP 412, §2.8). The correction applies only to an `OFFICIAL` result — attempting it against a result in any other state is rejected with `ERR_INVALID_STATE` — and provisional results are corrected implicitly through timing-record validation and invalidation rather than through this capability. A successful correction replaces the named split, recomputes both the provisional and official totals and the division ranks, leaves the result `OFFICIAL`, and increments the result's `version` by one.

### 3.7. Penalties, Appeals, Finalization, and Event-Wide Operations

Officiating starts with assessment. A `Referee` assesses a penalty against a registration with a `kind` of `DRAFTING`, `COURSE_VIOLATION`, or `EQUIPMENT` and optional free-text `notes`; the penalty carries the registration's `registration_id` and enters as `ASSESSED`, with `assessed_by_user_id` recording the referee's `X-User-ID`, `assessed_at` stamped from the clock, and `appeal_window_expires_at` computed as `assessed_at` plus the event's `appeal_window_minutes`. Drafting is policed per wave: assessing a `DRAFTING` penalty against a registration whose wave is `draft_legal` is rejected outright with `ERR_DRAFT_LEGAL_WAVE` (HTTP 400).

Penalty severity is computed, not entered. For `DRAFTING`, the system counts the registration's prior drafting penalties — those in `ASSESSED` or `CONFIRMED` status, excluding the penalty being created or amended. With no priors the penalty is 120 seconds; with one prior, 300 seconds; with two or more priors the penalty carries zero seconds and instead sets `triggers_dsq`, the disqualification flag. The fixed kinds are simpler: `COURSE_VIOLATION` is always 300 seconds and `EQUIPMENT` always 60 seconds, and neither sets `triggers_dsq`.

While a penalty is `ASSESSED`, a `Referee` may amend it — replacing `kind`, `notes`, or both — through an OCC-guarded amendment that requires `expected_penalty_version` matching the penalty's current `version` and is rejected with `ERR_STALE_PENALTY_VERSION` (HTTP 412, §2.8) on mismatch; the amendment recomputes `seconds` and `triggers_dsq` from the current prior-penalty counts and increments the penalty's `version` by one, leaving it `ASSESSED`; the draft-legal-wave guard applies equally here, so an amendment that changes the kind to `DRAFTING` against a registration on a draft-legal wave is rejected with `ERR_DRAFT_LEGAL_WAVE`. A penalty leaves `ASSESSED` in only three ways: the ops checkpoint auto-confirms it once `appeal_window_expires_at` is at or before the clock and no appeal of it is `FILED` or `UNDER_REVIEW`; an appeal decision of `UPHELD` or `REDUCED` confirms it; or an appeal decision of `OVERTURNED` overturns it. Confirmation recomputes the result's `penalty_seconds_total`; when the confirmed penalty's `triggers_dsq` is set, the registration — whether `RACING` or `FINISHED` — moves to `DSQ`, its `division_rank` is nulled, and it is excluded from ranking; and when the result is already `OFFICIAL`, its official total is recomputed as well. Overturning recomputes `penalty_seconds_total` so the overturned penalty stops contributing. `CONFIRMED` and `OVERTURNED` are both terminal.

The athlete (or a `RaceDirector` on their behalf) may appeal an `ASSESSED` penalty by filing `grounds` against it — filing against a penalty in any other status is rejected with `ERR_INVALID_STATE`, evaluated before the window check — provided the logical clock is at or before the penalty's `appeal_window_expires_at`; filing after that instant is rejected with `ERR_APPEAL_WINDOW_EXPIRED`. The new appeal, carrying the penalty's `penalty_id`, enters as `FILED` and blocks the auto-confirmation described above while it remains open. A `Referee` moves the appeal to `UNDER_REVIEW` to begin deliberation and decides it from there. Decision carries three guards: the penalty must still be `ASSESSED` (`ERR_PENALTY_NOT_ASSESSED`); the deciding referee's `X-User-ID` must differ from the penalty's `assessed_by_user_id` — segregation of duties, rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); and a `decision` of `REDUCED` must supply `reduced_seconds` that is at least zero and strictly less than the penalty's current `seconds` (`ERR_VALIDATION`). The decision stamps `decision` and `decided_by_user_id` and resolves the penalty: `UPHELD` confirms it at its original seconds, `REDUCED` confirms it at `reduced_seconds` (the `triggers_dsq` flag is left as computed, so a reduced penalty whose flag is set still applies the disqualification cascade on confirmation), and `OVERTURNED` overturns it — with totals, ranks, and any disqualification cascade recomputed accordingly. `DECIDED` is terminal.

Finalization is the race's accounting close: moving `LIVE` to `FINALIZED` requires that no penalty remain `ASSESSED` (`ERR_PENALTIES_UNRESOLVED`) and that no appeal remain `FILED` or `UNDER_REVIEW` (`ERR_APPEALS_OUTSTANDING`). The penalties gate is evaluated before the appeals gate, so when both conditions fail at once the rejection is `ERR_PENALTIES_UNRESOLVED`. It moves every result to `OFFICIAL`, sets each `official_total_seconds` to the provisional total plus `penalty_seconds_total`, recomputes division ranks over `effective_total_seconds`, and increments the event's `version` by one.

Cancellation is the emergency exit, available from `PERMITTED`, `PUBLISHED`, or `LIVE` with a free-text `reason` (accepted but not persisted). Every registration in `ENTERED`, `PAID`, `CONFIRMED`, `WAITLISTED`, or `RACKED` is moved to `WITHDRAWN` at a full refund — the tier ladder and the processing fee are bypassed, and both `refund_estimate_cents` and `refund_final_cents` are set to the full `entry_fee_cents` — while freed wave slots recompute their waves' counts and statuses. Cancelling from `LIVE` additionally moves every `RACING` registration to `DNF`, with no refund recomputation for those athletes. The event's `version` increments by one.

Between race morning and the final accounting, a `RaceDirector` runs the ops checkpoint to push time-driven bookkeeping forward; the checkpoint is not posture-gated and may be run in any posture. Each run increments the event's `ops_run_index` by one and performs four sweeps: registrations still `PAID` once the logical clock has moved strictly past the instant 24 hours before `start_date` lapse to `EXPIRED`; withdrawals whose refunds have not settled receive `refund_final_cents`, recomputed by the same tier rule as §3.4 but keyed to the processing date — so when processing lands in a lower tier than the withdrawal date did, the final amount differs from the provisional estimate; `ASSESSED` penalties whose appeal window has passed with no open appeal are confirmed, recomputing totals and triggering any disqualification cascade; and a waitlist-promotion sweep runs across waves. The event's `version` increments by one with each run.

## 4. Endpoint Definitions

Operations that create a new resource — an event, road segment, permit, wave, athlete, registration, aid station, volunteer assignment offer, safety assessment, timing record, penalty, appeal, or a bike check-in record — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | RaceDirector |
| POST | `/events` | Create an event | RaceDirector |
| GET | `/events/{id}` | Get an event | All roles |
| POST | `/events/{id}/advance` | Advance posture DRAFT→PERMITTED→PUBLISHED with gate preconditions | RaceDirector |
| POST | `/events/{id}/start` | Start the race (PUBLISHED→LIVE); stamps wave actual start times | RaceDirector |
| POST | `/events/{id}/finalize` | Finalize results (LIVE→FINALIZED) | RaceDirector |
| POST | `/events/{id}/cancel` | Cancel the event (PERMITTED/PUBLISHED/LIVE→CANCELLED) | RaceDirector |
| POST | `/events/{id}/run-ops` | Ops checkpoint: expiry, refund settlement, penalty auto-confirm, waitlist sweep | RaceDirector |
| POST | `/events/{id}/road-segments` | Add a road segment with its closure window | PermitCoordinator |
| GET | `/events/{id}/road-segments` | List road segments of an event | All roles |
| GET | `/road-segments/{id}` | Get a road segment | All roles |
| POST | `/road-segments/{id}/permits` | Create a course permit request against a segment | PermitCoordinator |
| GET | `/road-segments/{id}/permits` | List permits of a segment | All roles |
| GET | `/permits/{id}` | Get a permit | All roles |
| POST | `/permits/{id}/submit` | Submit (or resubmit from REJECTED) a permit | PermitCoordinator |
| POST | `/permits/{id}/approve` | Approve a permit with 30-minute-buffer conflict check | PermitCoordinator |
| POST | `/permits/{id}/reject` | Reject a permit | PermitCoordinator |
| POST | `/events/{id}/waves` | Create a start wave | RaceDirector |
| GET | `/events/{id}/waves` | List waves of an event | All roles |
| GET | `/waves/{id}` | Get a wave | All roles |
| POST | `/waves/{id}/close` | Manually close a wave (OPEN→CLOSED) | RaceDirector |
| POST | `/waves/{id}/reopen` | Reopen a closed wave (requires assigned_count below capacity) | RaceDirector |
| GET | `/waves/{id}/registrations` | List registrations assigned to a wave | All roles |
| POST | `/events/{id}/athletes` | Create an athlete record in the event scope | RaceDirector |
| GET | `/events/{id}/athletes` | List athletes of an event | All roles |
| GET | `/athletes/{id}` | Get an athlete | All roles |
| PATCH | `/athletes/{id}` | Update athlete license status with withdrawal cascade | RaceDirector |
| GET | `/athletes/{id}/registrations` | List registrations of an athlete | All roles |
| POST | `/events/{id}/registrations` | Register an athlete (Athlete role registers self) | RaceDirector, Athlete |
| GET | `/events/{id}/registrations` | List registrations of an event with optional filters | All roles |
| GET | `/registrations/{id}` | Get a registration | All roles |
| POST | `/registrations/{id}/pay` | Mark entry fee paid (ENTERED→PAID) | RaceDirector, Athlete |
| POST | `/registrations/{id}/confirm` | Run the wave selector; CONFIRMED with assignment or WAITLISTED | RaceDirector |
| POST | `/registrations/{id}/withdraw` | Withdraw with tiered provisional refund and promotion cascade | RaceDirector, Athlete |
| POST | `/registrations/{id}/mark-dnf` | Mark a racing registration DNF | RaceDirector, Referee |
| POST | `/registrations/{id}/check-in-bike` | Transition-area bike check-in (CONFIRMED→RACKED); creates BikeCheck and Result | RaceDirector, Athlete |
| POST | `/registrations/{id}/check-out-bike` | Bike check-out with bib match; registration must be FINISHED or DNF | RaceDirector, Athlete |
| GET | `/registrations/{id}/bike-checks` | List bike checks of a registration | All roles |
| POST | `/events/{id}/aid-stations` | Create an aid station | RaceDirector |
| GET | `/events/{id}/aid-stations` | List aid stations of an event | All roles |
| GET | `/aid-stations/{id}` | Get an aid station | All roles |
| POST | `/events/{id}/allocate-water` | Run the water-allocation waterfall across all aid stations | RaceDirector |
| POST | `/aid-stations/{id}/deallocate-water` | Return this station's allocated water to the event pool | RaceDirector |
| POST | `/aid-stations/{id}/assignments` | Offer a volunteer shift at this station | VolunteerCoordinator |
| GET | `/aid-stations/{id}/assignments` | List volunteer assignments of a station | All roles |
| GET | `/volunteer-assignments/{id}` | Get a volunteer assignment | All roles |
| POST | `/volunteer-assignments/{id}/confirm` | Confirm an offered shift with half-open overlap check | VolunteerCoordinator |
| POST | `/volunteer-assignments/{id}/decline` | Decline an offered shift | VolunteerCoordinator |
| POST | `/volunteer-assignments/{id}/no-show` | Mark a confirmed volunteer as no-show | VolunteerCoordinator |
| POST | `/events/{id}/safety-assessments` | Record a water/weather safety assessment; may flip swim_status | RaceDirector, Referee |
| GET | `/events/{id}/safety-assessments` | List safety assessments of an event | All roles |
| GET | `/safety-assessments/{id}` | Get a safety assessment | All roles |
| POST | `/registrations/{id}/timing-records` | Record a chip read for a discipline | Timer |
| GET | `/registrations/{id}/timing-records` | List timing records of a registration | All roles |
| GET | `/timing-records/{id}` | Get a timing record | All roles |
| POST | `/timing-records/{id}/validate` | Validate a chip read; FINISH validation completes the race | Timer |
| POST | `/timing-records/{id}/invalidate` | Invalidate a chip read; a FINISH invalidate reverts FINISHED→RACING | Timer |
| GET | `/events/{id}/results` | List results of an event with optional filters | All roles |
| GET | `/registrations/{id}/results` | Get the (single) result of a registration as a 0- or 1-element array | All roles |
| GET | `/results/{id}` | Get a result | All roles |
| POST | `/results/{id}/corrections` | OCC-guarded correction of one split of an OFFICIAL result | Timer |
| POST | `/registrations/{id}/penalties` | Assess a penalty (seconds computed per kind/tier) | Referee |
| GET | `/registrations/{id}/penalties` | List penalties of a registration | All roles |
| GET | `/penalties/{id}` | Get a penalty | All roles |
| POST | `/penalties/{id}/amend` | OCC-guarded amendment of an ASSESSED penalty | Referee |
| POST | `/penalties/{id}/appeals` | File an appeal against an ASSESSED penalty within its appeal window | Athlete, RaceDirector |
| GET | `/penalties/{id}/appeals` | List appeals of a penalty | All roles |
| GET | `/appeals/{id}` | Get an appeal | All roles |
| POST | `/appeals/{id}/begin-review` | Move an appeal FILED→UNDER_REVIEW | Referee |
| POST | `/appeals/{id}/decide` | Decide an appeal (UPHELD/OVERTURNED/REDUCED); decider must differ from assessor | Referee |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EVENT_POSTURE` | 409 Conflict |
| `ERR_SEGMENT_NOT_COVERED` | 409 Conflict |
| `ERR_NO_OPEN_WAVE` | 409 Conflict |
| `ERR_AID_STATION_NOT_READY` | 409 Conflict |
| `ERR_SWIM_DECISION_PENDING` | 409 Conflict |
| `ERR_PENALTIES_UNRESOLVED` | 409 Conflict |
| `ERR_APPEALS_OUTSTANDING` | 409 Conflict |
| `ERR_PERMIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CONFIRM_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_ATHLETE_SUSPENDED` | 409 Conflict |
| `ERR_APPEAL_PENDING` | 409 Conflict |
| `ERR_REFUND_DESTINATION_REQUIRED` | 400 Bad Request |
| `ERR_BIB_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_BIKE_CHECKIN` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_WATER_NOT_ALLOCATED` | 409 Conflict |
| `ERR_DRAFT_LEGAL_WAVE` | 400 Bad Request |
| `ERR_PENALTY_NOT_ASSESSED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_RESULT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PENALTY_VERSION` | 412 Precondition Failed |
