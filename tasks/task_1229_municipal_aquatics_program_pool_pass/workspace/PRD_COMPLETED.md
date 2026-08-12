# Municipal Aquatics Program & Pool Pass API — Product Requirements Document

## 1. Introduction

The Municipal Aquatics Program & Pool Pass API supports a city parks and recreation aquatics division in operating its public pools through a full summer season. The system covers the entire patron-facing surface — season-pass sales, daily gate admissions, swim-lesson registration, facility rental bookings — and pairs it with the operational surface that keeps a pool legal and safe: water chemistry logging, lifeguard certification tracking, shift coverage against a bather-load staffing rule, weather and chemistry closures with rain-check refunds, and incident reporting with escalating patron consequences.

Three features of the domain shape the design. First, the facility itself is a stateful resource whose posture (`OPEN`, `RESTRICTED`, or one of several `CLOSED_*` variants) gates nearly every write operation, and whose posture can change as a side effect of a single chemistry reading or a single lifeguard no-show. Second, several finite resources — bather capacity, lap lanes, session seats, lesson waitlist positions — must be tracked with exact arithmetic so that gate staff and lesson coordinators see the same numbers the safety rules use. Third, money moves in integer cents with residency-tiered pricing, age-tiered discounts, an early-bird window, rental overtime billed in quarter-hour blocks, and a cancellation fee that depends on how far out the renter cancels; the rounding rules for each of these are contractual, not advisory.

The API is intended for four operator populations — division managers, gate attendants, lifeguards, and registered patrons — and all time-dependent behavior is evaluated against a logical clock that the test harness can advance explicitly. This document specifies the public contract in full; the implementer should be able to build the service from this document alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names the operational capacity in which they act. The system recognizes exactly four roles: `AquaticsManager`, `GateAttendant`, `Lifeguard`, and `PassHolder`. A request missing either header, presenting an empty value for either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The interpretation of `X-User-ID` differs by role. When `X-User-Role` is `AquaticsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to an entity `id`. The same opaque-identifier rule applies when `X-User-Role` is `GateAttendant`. When `X-User-Role` is `Lifeguard`, `X-User-ID` is the `id` of the acting `Lifeguard` entity; identity checks such as the one on shift check-in compare the shift's `lifeguard_id` against `X-User-ID`, and the same rule applies to incident-report submission against `reporting_lifeguard_id`. When `X-User-Role` is `PassHolder`, `X-User-ID` is the `id` of the acting `PassHolder` entity; ownership checks on enrollments and rentals compare the resource's `pass_holder_id` foreign key to `X-User-ID`. Ownership is not enforced at creation time: a `PassHolder` may create an enrollment or a rental naming any existing `pass_holder_id`, with the identity check applying only to subsequent reads, drops, and cancellations.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside the 1–100 range, and an `offset` that is not an integer or is negative, are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise stated, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by insertion order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` inside the `meta` block of the envelope. One exception to the default sort: the chemistry-log listing for a facility returns entries newest-first by `recorded_at` (ties broken by reverse insertion order), because operators care most about the most recent reading. List endpoints additionally accept exact-match query filters: `GET /seasons` by `facility_id` and `status`; `GET /admissions` by `facility_id`, `pass_holder_id`, and `status`; `GET /lesson-levels` by `prerequisite_level_id`; `GET /lesson-sessions` by `facility_id`, `level_id`, `season_id`, and `status`; `GET /lifeguards` by `cert_status`; `GET /shifts` by `facility_id`, `lifeguard_id`, and `status`; `GET /lane-allocations` by `facility_id`, `purpose`, and `status`; `GET /rentals` by `facility_id`, `pass_holder_id`, and `status`; and `GET /incident-reports` by `facility_id`, `involved_pass_holder_id`, and `status`.

### 2.4. Common Resource Properties

Almost every primary resource in this API — `Facility`, `MembershipSeason`, `PassHolder`, `SeasonPass`, `DailyAdmission`, `SwimLessonLevel`, `LessonSession`, `LessonEnrollment`, `Lifeguard`, `LifeguardShift`, `LaneAllocation`, `FacilityRental`, `IncidentReport`, `PoolClosureEvent` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments by 1 on every mutation of the resource, including mutations driven by derived-field recomputation or cascading side effects.

The single exception is `ChemistryLog`, which is an immutable water-chemistry record: it carries only `id` and `created_at`; both `updated_at` and `version` are absent. Recording a new `ChemistryLog` does not mutate prior logs.

When an operation changes a `Facility`'s derived counters (for example, admitting a patron, checking in a rental party, or posting a chemistry reading that flips the operational posture), the change counts as a mutation of the `Facility` and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Money, Precision, and Rounding

All monetary amounts are integer cents. Endpoints never accept or return fractional-cent values, and all arithmetic is performed in integer cents after the rounding steps named below. Two rounding modes appear in this system, and each rule states which one it uses:

- "Rounded half-up to the nearest cent" means a fraction of exactly one-half rounds up.
- "Rounded up to the next whole cent (ceiling)" means any positive fractional remainder rounds up to the next integer cent.

Wherever a percentage or multiplier is applied, the multiplier is applied to the integer-cent base and then rounded per the named mode before any subsequent addition. Partial hours and partial quarter-hour blocks in the rental rules always round up to a whole unit. Age in years is always a floor — a patron is treated as the age of their most recent birthday, not their upcoming one.

### 2.6. The Logical Clock and Time-Dependent Transitions

All "now" semantics in this API refer to a server-side logical clock, not wall-clock time. The clock's default value before any test-driving call is `2026-05-01T00:00:00Z`. An `AquaticsManager` may advance the clock via a dedicated test-driving capability that accepts a `to_iso8601` timestamp and re-evaluates every time-dependent system transition — lifeguard certification expiry, shift no-show detection, lesson session start and end, season close, season-end facility closure, ban expiry, and so on — against the new clock value. The call accepts any parseable ISO 8601 timestamp (there is no forward-only constraint) and returns `200 OK` with a data object of the form `{"current_utc": <the new clock value>}`. State changes triggered by the clock are reported by the same response envelope as client-initiated changes.

Several transitions compare the clock against stored ISO dates or datetimes. `start_date` and `end_date` on a `MembershipSeason` are inclusive calendar days. `shift_start` and `shift_end` on a `LifeguardShift` are datetimes; the no-show grace is exactly 15 minutes after `shift_start`. Ban windows compare `banned_until` against the clock with strict inequality: a ban whose `banned_until` equals the current clock is no longer in effect.

### 2.7. Optimistic Concurrency Control on Facility-Mutating Writes

Two write endpoints carry a mandatory optimistic-concurrency guard because both depend on a fresh view of the parent `Facility`:

- Approving a facility rental requires the request body to include `expected_facility_version`, carrying the client's last observed `version` of the `Facility` the rental belongs to. If the facility's current `version` has advanced past that value — for example because a chemistry reading pushed the facility into `CLOSED_CHEMISTRY`, or a recent gate entry bumped `required_lifeguard_count` — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Scheduling a lesson session requires the same field, `expected_facility_version`, carrying the client's last observed `version` of the parent `Facility`. A lane-allocation release or a bather-count change may have invalidated the lane availability the scheduler relied on, so a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Endpoints not listed here do not perform OCC. On both guarded endpoints the field is mandatory: a missing or non-integer `expected_facility_version` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and this shape check is evaluated only after every other rule (state, OCC staleness, facility posture, capacity, and window checks) has passed.

### 2.8. Hierarchical Consistency and Cascading Side Effects

The `Facility` is the operational root. Its `operational_status` gates gate entries, lesson starts, rental check-ins, rental approvals, and session scheduling, and its posture can be changed by events originating elsewhere in the system: a single `OUT_OF_RANGE` chemistry reading pushes it to `CLOSED_CHEMISTRY`; a `WARNING` reading pushes it to `RESTRICTED`; a staffing shortage pushes it to `CLOSED_STAFFING`; and the end of the last published season pushes it to `CLOSED_SEASON`. Each such transition has a defined cascade that touches lane allocations, rentals, daily admissions, and the derived `current_bather_count` — these cascades are described alongside each workflow in §3.

Child resources also drive the parent. Every gate entry, rental check-in, gate exit, and rental check-out adjusts the facility's `current_bather_count` and recomputes its `required_lifeguard_count`. Every chemistry log re-derives `chemistry_state` and, on transitions into or out of `OUT_OF_RANGE`, updates `chemistry_out_of_range_since`. Every mutation of a parent resource increments that parent's `version` and refreshes its `updated_at`, which is what makes the OCC guard in §2.7 meaningful.

### 2.9. Nested Resource Retrieval

Endpoints that address a resource nested under another — for example, an enrollment under a lesson session, or a chemistry log under a facility — validate path identifiers from left to right. The first path identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404) and stops further evaluation. A request naming a non-existent facility therefore returns `ERR_NOT_FOUND` before any enrollment- or chemistry-specific check runs. The same left-to-right rule applies to foreign keys inside request bodies: an unresolvable `pass_holder_id`, `season_id`, `level_id`, `lifeguard_id`, `lesson_session_id`, `owning_lesson_session_id`, `placement_evidence_level_id`, `involved_pass_holder_id`, or `reporting_lifeguard_id` produces `ERR_NOT_FOUND`.

### 2.10. Validation Order

When several rules could reject the same request, they are evaluated in a fixed priority order so the rejection a client sees is stable:

1. Presence and well-formedness of `X-User-Role` (`ERR_UNAUTHENTICATED`).
2. Presence and well-formedness of `X-User-ID` (`ERR_UNAUTHENTICATED`).
3. Role permitted for the endpoint (`ERR_FORBIDDEN`).
4. Path-templated identifiers resolve, left-to-right (`ERR_NOT_FOUND`).
5. Request-body foreign-key references resolve (`ERR_NOT_FOUND`).
6. Target resource's current state permits the requested transition (`ERR_INVALID_STATE`).
7. OCC stale-version check on the two guarded endpoints (`ERR_STALE_VERSION`).
8. Facility not in a `CLOSED_*` posture for operations that admit, check in, schedule, or approve (`ERR_FACILITY_CLOSED`).
9. Patron not currently banned (`ERR_HOLDER_BANNED`).
10. Lifeguard certification is `ACTIVE` at the moment of submission or check-in (`ERR_GUARD_NOT_CERTIFIED`).
11. Rental does not overlap another approved or checked-in rental at the same facility (`ERR_RENTAL_OVERLAP`).
12. Lane capacity sufficient for a new lesson or lane allocation (`ERR_LANE_CAPACITY_EXCEEDED`).
13. Lesson session window lies inside its season (`ERR_SESSION_OUTSIDE_SEASON`).
14. Admission date is today and the season is `PUBLISHED` on that date (`ERR_ADMISSION_DATE_INVALID`).
15. Shift window is well-formed and within the allowed booking horizon (`ERR_SHIFT_WINDOW_INVALID`).
16. Enrollment prerequisites satisfied (`ERR_PREREQUISITE_NOT_MET`).
17. Season publish passes pricing and overlap checks (`ERR_SEASON_OVERLAP`).
18. Chemistry log readings inside plausible instrument bounds (`ERR_CHEMISTRY_INPUT_INVALID`).
19. Rental capacity and lane exclusivity (`ERR_RENTAL_CAPACITY`).
20. Gate entry respects bather capacity (`ERR_FACILITY_AT_CAPACITY`).
21. Rental check-in respects bather capacity (`ERR_FACILITY_AT_CAPACITY`).
22. Field shape — required fields present, enum values match declared members case-sensitively, numeric inputs within their declared bounds (`ERR_INVALID_REQUEST`).

The ordering matters. For example, a rental approval attempted against a banned patron whose facility is also closed surfaces `ERR_FACILITY_CLOSED` (rule 8), not `ERR_HOLDER_BANNED` (rule 9), because the facility check fires first.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Facility and a Season

An `AquaticsManager` onboards a new pool by creating a `Facility` with a display `name`, a street `address`, a `max_bather_capacity` (the hard cap on simultaneous bathers, at least 1), and a `lap_lane_count` (the number of lanes available for allocation, which may be zero for a leisure-only pool). The new facility starts with `current_bather_count` at 0, `required_lifeguard_count` at 0, `operational_status` of `OPEN`, `chemistry_state` of `IN_RANGE`, and `chemistry_out_of_range_since` null.

With a facility in place, the manager drafts a `MembershipSeason` scoped to that facility via `facility_id`. A season carries a `season_name` (for example, "Summer 2026"), an inclusive `start_date` and `end_date`, and four prices in integer cents: `resident_pass_price_cents`, `non_resident_pass_price_cents`, `resident_daily_price_cents`, and `non_resident_daily_price_cents`. Creation requires `end_date` to be strictly after `start_date` and all four prices to be non-negative integers; violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). New seasons begin in `DRAFT`. Publishing the season moves it to `PUBLISHED`, but only if resident prices do not exceed the corresponding non-resident prices — that is, `resident_pass_price_cents` is at most `non_resident_pass_price_cents` and `resident_daily_price_cents` is at most `non_resident_daily_price_cents` — and only if no other `PUBLISHED` season for the same facility overlaps the requested window. Overlap is evaluated on the half-open interval from `start_date` up to but not including the day after `end_date`, so two seasons that touch end-to-start do not conflict. A violation of either condition is rejected with `ERR_SEASON_OVERLAP` (HTTP 409). Once `PUBLISHED`, season-pass purchases open. A season is closed either manually by the manager or automatically when the clock advances past `end_date`; closure moves it to `CLOSED`, blocks further pass purchases, and — if no future `PUBLISHED` season exists for the facility — cascades the facility to `CLOSED_SEASON`, which also cancels every future `LessonSession` and renders existing `ACTIVE` season passes unusable for new admissions. Here a "future `PUBLISHED` season" means another `PUBLISHED` season for the same facility whose `end_date` is on or after the current date; the facility cascade fires only while the facility is `OPEN` or `RESTRICTED`, and — unlike chemistry, weather, and staffing closures — the season-end transition creates no `PoolClosureEvent`.

### 3.2. Patrons, Passes, and Daily Gate Admissions

A `GateAttendant` or `AquaticsManager` registers a `PassHolder` with `full_name`, `date_of_birth`, `residency_status`, and `email`. Residency is one of `RESIDENT` or `NON_RESIDENT`; the division's residency-proof process happens at the counter and is outside the API. The holder's age tier is derived from `date_of_birth` against the current clock: under 18 is `CHILD`, 18 through 61 is `ADULT`, and 62 or older is `SENIOR`. Each holder also carries two disciplinary fields, `strike_count` (initially 0) and `banned_until` (initially null), populated by the incident workflow described in §3.8.

A season pass is purchased against a specific `PUBLISHED` season by posting `pass_holder_id` and `season_id`; purchasing against a season in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). No uniqueness is enforced: a holder may own multiple passes against the same season, and may hold multiple daily admissions for the same day. The system snapshots `purchase_price_cents` from the season's price book at the moment of purchase: `resident_pass_price_cents` if the holder is a `RESIDENT`, otherwise `non_resident_pass_price_cents`. The pass begins in `ACTIVE` with `refunded_cents` at 0. A manager may refund an `ACTIVE` pass while the clock is still within the season window — that is, any time before the start of the day after `end_date`, so refunds remain possible through `end_date` itself; the refund transition moves the pass to `REFUNDED`, sets `refunded_cents` to the full `purchase_price_cents`, and rejects any future daily admissions that reference it. Mid-season partial refunds are out of scope. If the holder is subsequently banned (see §3.8), every `ACTIVE` pass for that holder moves to `REVOKED`, and any admission still in `ISSUED` for that holder transitions to `VOID` with a full refund of its `charge_cents`.

Daily admission is issued by a `GateAttendant` for a specific `facility_id`, `pass_holder_id`, and `admission_date`, optionally referencing a `season_pass_id`. Issue-time checks reject the request when the holder is currently banned (`ERR_HOLDER_BANNED`, HTTP 409), when `admission_date` is not today's date per the logical clock, or when the season covering that date is not `PUBLISHED`, with `ERR_ADMISSION_DATE_INVALID` (HTTP 422). For admission purposes the early-bird window counts as covered by the upcoming `PUBLISHED` season, so an admission dated within the seven days before `start_date` is issuable. When a `season_pass_id` is supplied, the pass must be `ACTIVE`, must belong to the season covering the admission date, and must belong to the same `pass_holder_id`; otherwise the request fails with `ERR_PASS_NOT_VALID` (HTTP 409), a check evaluated after the admission-date rule and before field-shape validation. A valid pass covers the day in full, so `charge_cents` is 0 and no pricing math runs.

When no pass is supplied, `charge_cents` is computed from the season's daily price book and the holder's profile. The base is `resident_daily_price_cents` for a `RESIDENT` holder or `non_resident_daily_price_cents` for a `NON_RESIDENT` holder. If `admission_date` falls inside the early-bird window — the seven calendar days immediately before `start_date` — an early-bird discount of 10 percent is applied to the residency base before any age multiplier. The age multiplier is then applied to the discounted integer base: `CHILD` patrons pay 60 percent of the base, `SENIOR` patrons pay 75 percent, and `ADULT` patrons pay the base unchanged. The final amount is rounded up to the next whole cent. The order of operations is contractual: residency base first, then early-bird discount (when applicable), then age multiplier, then ceiling-to-cent.

An issued admission begins in `ISSUED`. Entry at the gate transitions it to `ENTERED` and stamps `entered_at` with the current clock; entry requires the facility to be `OPEN` or `RESTRICTED` (rejecting with `ERR_FACILITY_CLOSED`), the patron not to be currently banned (`ERR_HOLDER_BANNED`), the `admission_date` to equal today, and the facility's `current_bather_count` to be strictly below `max_bather_capacity` (`ERR_FACILITY_AT_CAPACITY` when the cap has been reached). A successful entry increments the facility's `current_bather_count` by 1 and recomputes `required_lifeguard_count`. Exit transitions the admission from `ENTERED` to `EXITED`, stamps `exited_at`, decrements `current_bather_count` by 1, and recomputes the lifeguard requirement. A second entry attempt on an already-`ENTERED` admission, or a second check-in on any already-active record elsewhere in the system, is rejected with `ERR_ALREADY_CHECKED_IN` (HTTP 409).

### 3.3. Water Chemistry, Facility Posture, and Reopening

A `Lifeguard` (or an `AquaticsManager`) records a water sample by posting `recorded_at`, `free_chlorine_ppm`, `ph`, `combined_chlorine_ppm`, and `recorded_by_lifeguard_id` to the facility's chemistry log. Readings must sit inside plausible instrument bounds — free chlorine between 0 and 10 ppm, pH between 6.0 and 9.0, combined chlorine between 0 and 5 ppm — otherwise the request is rejected as malformed with `ERR_CHEMISTRY_INPUT_INVALID` (HTTP 422); these are not chemistry judgments, they are sanity limits on the instrument.

Classification is computed from the three readings and written to `classification`. The reading is `OUT_OF_RANGE` when free chlorine is strictly below 1.0 ppm or strictly above 5.0 ppm, or when pH is strictly below 7.2 or strictly above 7.8. A value sitting exactly on a boundary — free chlorine of exactly 1.0 or exactly 5.0, pH of exactly 7.2 or exactly 7.8 — is inside range. If none of those out-of-range conditions hold and combined chlorine is strictly above 0.4 ppm, the reading is `WARNING`. Otherwise it is `IN_RANGE`.

A new `OUT_OF_RANGE` reading on an `OPEN` or `RESTRICTED` facility transitions the facility to `CLOSED_CHEMISTRY` and creates a `PoolClosureEvent` with `closure_reason` of `CHEMISTRY` whose `started_at` is the current clock (not the reading's `recorded_at`). The cascade that follows cancels every `RESERVED` `LaneAllocation` overlapping the closure window, force-completes every `CHECKED_IN` `FacilityRental` with `final_price_cents` set to the locked `quoted_price_cents` (overtime is waived for a chemistry-forced exit), transitions every `ENTERED` `DailyAdmission` to `EXITED` with `exited_at` stamped now and no refund, and resets `current_bather_count` to 0. The first `OUT_OF_RANGE` reading also stamps `chemistry_out_of_range_since` with that reading's `recorded_at`; if a second consecutive `OUT_OF_RANGE` reading arrives, the timestamp remains anchored to the first reading of the streak, and a `WARNING` or `IN_RANGE` reading clears `chemistry_out_of_range_since` to null. Posting a chemistry log always mutates the facility — refreshing `updated_at` and incrementing `version` — even when the posture does not change, and a reading posted while the facility is already in a `CLOSED_*` posture updates `chemistry_state` and the streak bookkeeping without creating another closure event.

A `WARNING` reading on an `OPEN` facility transitions it to `RESTRICTED` and sets `chemistry_state` to `WARNING`; new lesson sessions cannot be started while restricted, but gate admissions continue. A subsequent `IN_RANGE` reading on a `RESTRICTED` facility returns it to `OPEN`. For a chemistry-closed facility, reopening is stricter: the most recent chemistry log must be `IN_RANGE`, and if the closure streak contained two or more consecutive `OUT_OF_RANGE` readings, the facility requires two consecutive `IN_RANGE` readings — not one — before the reopen criteria are met. The streak considered is the longest run of consecutive `OUT_OF_RANGE` readings recorded since the facility last returned to `OPEN`, and the count of consecutive `IN_RANGE` readings resets whenever a `WARNING` or `OUT_OF_RANGE` reading intervenes.

An `AquaticsManager` may reopen a closed facility, which resolves every `ACTIVE` `PoolClosureEvent` for the facility (stamping `ended_at` with the current clock), returns the facility to `OPEN`, and increments the facility's `version`. Reopen is defined only for `CLOSED_CHEMISTRY`, `CLOSED_WEATHER`, and `CLOSED_STAFFING`; calling it on a facility in any other posture — including `CLOSED_SEASON` — is rejected with `ERR_INVALID_STATE` (HTTP 409), and a successful reopen always lands on `OPEN`, regardless of the current `chemistry_state`. Reopening is rejected with `ERR_REOPEN_CRITERIA_NOT_MET` (HTTP 409) when the chemistry-driven closure still has a most-recent `OUT_OF_RANGE` log or when the staffing shortage that triggered the closure is still present.

### 3.4. Weather Closures and Rain Checks

An `AquaticsManager` may declare a weather closure at any time by posting `closure_reason` of `WEATHER` and a `started_at` timestamp for the closure window. The facility must not already be in a `CLOSED_*` posture; if it is, the declaration is rejected with `ERR_INVALID_STATE` (HTTP 409). The manual closure endpoint in fact accepts any of the four `closure_reason` values — `WEATHER`, `CHEMISTRY`, `STAFFING_SHORTAGE`, or `SEASON_END` — and applies the corresponding cascade; unlike the automatic season rollover, a manually declared `SEASON_END` closure does create a `PoolClosureEvent`. The weather transition moves the facility to `CLOSED_WEATHER`, creates a `PoolClosureEvent` with `closure_reason` of `WEATHER`, cancels every `RESERVED` `LaneAllocation` overlapping the window, force-completes every `CHECKED_IN` rental with overtime waived, cancels every `APPROVED` rental whose `start_datetime` falls inside the closure window with a full refund, transitions every `ENTERED` admission to `RAIN_CHECKED`, and resets `current_bather_count` to 0.

Rain-check compensation for each rain-checked admission is derived from how long the patron had been inside when the closure began, and the outcome is recorded on the closure event as `rain_check_issuance` with one of three values: `FULL_REFUND`, `PRO_RATA_CREDIT`, or `NONE`. Elapsed minutes are computed from `entered_at` to the closure's `started_at`, floored to a whole minute. If elapsed time is at most 60 minutes, the issuance is `FULL_REFUND` and the patron is refunded their full `charge_cents`. If elapsed time is greater than 60 minutes, the issuance is `PRO_RATA_CREDIT` and the patron is refunded 50 percent of `charge_cents`, rounded half-up to the nearest cent. The single `rain_check_issuance` recorded on the closure event is `PRO_RATA_CREDIT` when any rain-checked admission had elapsed more than 60 minutes and `FULL_REFUND` otherwise — including the degenerate case in which no admission was `ENTERED` at closure time. Rain-check refund amounts are not persisted on the admission or any other resource. For closures not caused by weather — chemistry or staffing — the issuance is `NONE` and no refund is owed. Because a season-pass admission always carries `charge_cents` of 0, the same arithmetic yields a 0 refund and `SeasonPass.refunded_cents` is never incremented by rain checks; the pass itself is not double-refunded.

A closure event may be resolved individually by a manager, which stamps `ended_at` and recomputes the facility's posture, or implicitly through the facility-wide reopen call described in §3.3.

### 3.5. Lifeguards, Certifications, and Shift Staffing

An `AquaticsManager` registers a `Lifeguard` with `full_name`, `certification_id`, `cert_expires_on`, and `hired_on`. Certification status is derived: a guard whose `cert_expires_on` has passed moves from `ACTIVE` to `EXPIRED`, which also cancels every future `SCHEDULED` shift for that guard. `cert_expires_on` is an inclusive calendar day — the guard remains `ACTIVE` through the end of that day and becomes `EXPIRED` only once the clock passes midnight at the day's end — and the same derivation applies when the guard is first registered. A manager may also suspend a guard (the request must include a `reason`, such as a failed audit); only an `ACTIVE` guard can be suspended — other statuses are rejected with `ERR_INVALID_STATE` (HTTP 409) — and suspension moves the guard to `SUSPENDED` and likewise cancels future `SCHEDULED` shifts. Throughout these transitions a shift counts as "future" when its `shift_start` is strictly after the current clock. A suspended guard may be reinstated, returning to `ACTIVE`, but only when `cert_expires_on` is still in the future (under the same inclusive-day semantics).

A shift is created against a `facility_id` and `lifeguard_id` with a `shift_start` and `shift_end`. The shift window must be well-formed — `shift_start` strictly before `shift_end` — and both endpoints must lie within the allowed booking horizon of one hour in the past to 60 days in the future; otherwise the creation fails with `ERR_SHIFT_WINDOW_INVALID` (HTTP 422). Creation performs no certification check: a shift may be created for a guard of any `cert_status`. Shifts begin in `SCHEDULED`.

The assigned lifeguard checks in personally: the request is only valid when `X-User-ID` equals the shift's `lifeguard_id`, when the guard's `cert_status` is `ACTIVE` at that moment (otherwise `ERR_GUARD_NOT_CERTIFIED`, HTTP 409), and when the clock is no more than 15 minutes past `shift_start` (a later check-in is rejected with `ERR_INVALID_STATE`, HTTP 409). A successful check-in moves the shift to `COVERED` and increments the facility's scheduled-guard count for the shift window. If the clock advances past `shift_start` plus 15 minutes with no check-in, the system marks the shift `NO_SHOW` and decrements the scheduled-guard count. A manager may also cancel a `SCHEDULED` shift, which decrements the same count. Scheduled-guard coverage is not a stored counter: it is derived on demand as the number of shifts in `SCHEDULED` or `COVERED` whose windows overlap the evaluation window, which is the one-hour window starting at the current clock for closure detection.

The staffing requirement is recomputed every time `current_bather_count` changes. When the count is 0, the requirement is 0 guards. When the count is between 1 and 50 inclusive, the requirement is 2 guards. Above 50, the requirement is 2 plus the ceiling of the excess over 50 divided by 25 — so 51 bathers requires 3 guards, 75 requires 3, 76 requires 4, and so on. When the facility is in `RESTRICTED` posture, the requirement is raised by 1 additional guard (a chemistry-warning margin) before being compared against scheduled coverage. If a shift no-show or cancellation causes the scheduled-guard count for the current hour to fall below the requirement while bathers are present, the facility transitions to `CLOSED_STAFFING`, creates a `PoolClosureEvent` with `closure_reason` of `STAFFING_SHORTAGE`, transitions every `ENTERED` admission to `EXITED` with no refund, and cancels overlapping `RESERVED` lane allocations. A staffing closure does not force-complete `CHECKED_IN` rentals: they remain checked in, and `current_bather_count` is reset to the sum of their party sizes rather than to zero.

### 3.6. Swim Lesson Levels, Sessions, and Enrollment

An `AquaticsManager` authors the curriculum as a set of `SwimLessonLevel` records. Each level has a unique `level_code` (for example, `L1`; a duplicate `level_code` is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `display_name` (for example, "Water Acclimation"), a `min_age_years` floor (zero or greater), an optional `prerequisite_level_id` that is null for the entry level, and a `capacity_per_session` of at least 1.

A `LessonSession` is created in `DRAFT` against a `facility_id`, `level_id`, and `season_id`, with a `start_datetime`, an `end_datetime` strictly after it, and a `lanes_required` of at least 1. The session window must lie entirely inside its season — `start_datetime` on or after `start_date`, and `end_datetime` no later than the day after `end_date` — otherwise creation (and later scheduling) is rejected with `ERR_SESSION_OUTSIDE_SEASON` (HTTP 422). Scheduling the session moves it to `SCHEDULED` and is the OCC-guarded operation described in §2.7; it also requires the facility to be `OPEN` (`ERR_FACILITY_CLOSED` otherwise) and requires lane availability: at every instant of the session window, the sum of `lane_count` over overlapping `RESERVED` lane allocations plus the session's `lanes_required` must not exceed the facility's `lap_lane_count`, with overlap evaluated on half-open intervals (`ERR_LANE_CAPACITY_EXCEEDED` when insufficient). A successful schedule creates a `LaneAllocation` with `purpose` of `LESSON` and `owning_lesson_session_id` pointing at the new session, reserving `lanes_required` lanes for the session window, and increments the parent facility's `version`. Sessions whose start time is reached while the facility is `OPEN` or `RESTRICTED` transition from `SCHEDULED` to `IN_PROGRESS`; a `SCHEDULED` session whose start passed while the facility was closed latches to `IN_PROGRESS` at the next clock evaluation in which the facility is `OPEN` or `RESTRICTED` (and may complete in the same evaluation if its end time has also passed). When the end time is reached the session transitions to `COMPLETED`, releasing its owned lane allocation and moving every `ENROLLED` enrollment to `COMPLETED`; `WAITLISTED` enrollments are left untouched by completion. A manager may cancel a `DRAFT` or `SCHEDULED` session, which moves it to `CANCELLED`, cancels its owned lane allocation, and drops every enrollment. The session's `enrolled_count` always counts `ENROLLED` enrollments only and is recomputed after these cascades, so it falls to 0 when a session completes or is cancelled.

Enrollment is open to a `GateAttendant`, an `AquaticsManager`, or the patron themselves. The payload names `lesson_session_id`, `pass_holder_id`, and optionally `placement_evidence_level_id` — the level the student has already passed. Enrollment is permitted into `DRAFT` and `SCHEDULED` sessions; enrolling into a `CANCELLED` or `COMPLETED` session is rejected with `ERR_INVALID_STATE` (HTTP 409). The prerequisite check compares this evidence against the level's `prerequisite_level_id`: enrollment is allowed when the level has no prerequisite, or when the evidence level matches the declared prerequisite exactly; the patron's age on the session's start date must also be at least `min_age_years`. Violations are rejected with `ERR_PREREQUISITE_NOT_MET` (HTTP 422). The patron must not be currently banned (`ERR_HOLDER_BANNED`).

When an enrollment is created against a session whose `enrolled_count` has not yet reached the level's `capacity_per_session`, the enrollment is created in `ENROLLED` and the session's `enrolled_count` increments by 1. When the session is full, the enrollment is created in `WAITLISTED` and assigned the next `waitlist_position` — one more than the count of existing `WAITLISTED` enrollments for that session, so the first waitlisted patron is position 1.

Dropping an enrollment is permitted for the patron themselves (when `X-User-ID` equals the enrollment's `pass_holder_id`) or for a manager. Only an `ENROLLED` or `WAITLISTED` enrollment can be dropped; any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Dropping a `WAITLISTED` enrollment simply moves it to `DROPPED`. Dropping an `ENROLLED` enrollment decrements the session's `enrolled_count`, promotes the waitlist head — the `WAITLISTED` enrollment with the lowest `waitlist_position`, ties broken by earliest `created_at` — to `ENROLLED`, sets that promoted enrollment's `waitlist_position` to null, increments `enrolled_count` back by 1, and re-numbers the remaining waitlist so positions shift up by 1. The drop records no refund: enrollments carry no payment fields, no refund computation runs, and the response contains only the updated enrollment.

### 3.7. Lane Allocation and Facility Rentals

Beyond the allocations automatically created for lessons, an `AquaticsManager` may reserve lanes directly for `LAP_SWIM` or `SWIM_TEAM` use by posting `facility_id`, `purpose`, `start_datetime`, `end_datetime`, and `lane_count`. Posting a `purpose` of `LESSON`, or any `owning_lesson_session_id`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — lesson allocations are created only by session scheduling — and lane reservation performs no facility-posture check. The same capacity rule applies — overlapping `RESERVED` allocations plus the new `lane_count` must not exceed `lap_lane_count`, on half-open intervals (`ERR_LANE_CAPACITY_EXCEEDED`). A `RESERVED` allocation may be manually released (moving it to `RELEASED`) or may be cancelled by the system when its owning session is cancelled or when the facility closes.

A facility rental begins life as a `REQUESTED` `FacilityRental` created by a `PassHolder`, `GateAttendant`, or `AquaticsManager` with `facility_id`, `pass_holder_id`, `party_size` (at least 1), `start_datetime`, and `end_datetime` strictly later. The patron must not be currently banned. At creation the system computes `quoted_price_cents`. The quote first derives whole hours by rounding the rental duration up to the next hour. The base rate is 15000 cents per hour. A residency multiplier is then applied — 1.0 for `RESIDENT` holders, 1.5 for `NON_RESIDENT` holders — and the result is rounded half-up to the cent. A party fee is then added: the first 25 attendees are included, and every attendee beyond 25 adds 300 cents. The sum of the residency-adjusted base and the party fee is the quote. The rounding sequence is contractual: residency multiplier first, round half-up to cent, then add the party fee.

Approval is the OCC-guarded operation described in §2.7. Beyond the version check, approval requires the facility to be `OPEN` or `RESTRICTED`, the `party_size` not to exceed `max_bather_capacity`, and the rental window not to overlap any other `APPROVED` or `CHECKED_IN` rental at the same facility — rentals are whole-facility exclusive (`ERR_RENTAL_OVERLAP`). Approval also requires exclusive lane use: no `RESERVED` lane allocation may overlap the rental window, so the sum of overlapping reserved lanes must be zero (`ERR_RENTAL_CAPACITY`). Approval locks `quoted_price_cents`, moves the rental to `APPROVED`, and increments the parent facility's `version`. A manager may instead reject the request, moving it to `REJECTED`.

Check-in is performed by a `GateAttendant` and moves the rental from `APPROVED` to `CHECKED_IN`. Pre-conditions are that the facility is `OPEN` or `RESTRICTED`, that `current_bather_count` plus `party_size` does not exceed `max_bather_capacity` (`ERR_FACILITY_AT_CAPACITY`), and that the clock lies within the rental window inclusively — at or after `start_datetime` and at or before `end_datetime` — with a clock outside the window rejected as `ERR_INVALID_STATE` (HTTP 409). Check-in adds `party_size` to `current_bather_count` and recomputes `required_lifeguard_count`. Check-out moves the rental to `COMPLETED`, subtracts `party_size` from `current_bather_count`, and computes `final_price_cents` as the locked `quoted_price_cents` plus overtime. Overtime is zero when the actual exit is at or before `end_datetime`; otherwise the overage is divided into 15-minute blocks with any partial block rounded up, and each block adds 5000 cents. When the exit was forced by a weather closure, overtime is waived even if the actual exit is past `end_datetime`.

Either the patron or a manager may cancel a `REQUESTED` or `APPROVED` rental. Cancelling a `REQUESTED` rental is free. Cancelling an `APPROVED` rental is free when the cancellation is at least 72 hours before `start_datetime`; inside that window — strictly less than 72 hours — a 25 percent cancellation fee on `quoted_price_cents`, rounded half-up to the cent, is withheld. A cancellation at exactly 72.0 hours before start incurs no fee. The fee amount is computed at cancellation time but is not persisted on the rental or any other resource; the response carries only the updated rental.

### 3.8. Incident Reports and Patron Discipline

A `Lifeguard` or `AquaticsManager` drafts an `IncidentReport` against a `facility_id`, naming the `reporting_lifeguard_id`, the `involved_pass_holder_id`, an `incident_type` of `RESCUE`, `FIRST_AID`, `RULE_VIOLATION`, or `EQUIPMENT_FAILURE`, an `occurred_at` timestamp, a `severity` of `MINOR`, `MODERATE`, or `MAJOR`, and a free-text `narrative`. The report begins in `DRAFT`.

Submission is performed by the reporting lifeguard personally: `X-User-ID` must equal the report's `reporting_lifeguard_id`, and the guard's `cert_status` must be `ACTIVE` at submission time (otherwise `ERR_GUARD_NOT_CERTIFIED`). Submission moves the report to `SUBMITTED`. A manager then either dismisses the report (moving it to `DISMISSED` with no further effect) or confirms it.

Confirmation moves the report to `CONFIRMED` and increments the involved holder's `strike_count` by 1. Two escalation paths then apply independently: if the report's `severity` is `MAJOR`, or if the holder's `strike_count` has reached at least 3, the holder's `banned_until` is set to 30 days from the current clock. Activating a ban also revokes every `ACTIVE` `SeasonPass` the holder owns (moving each to `REVOKED`) and voids every `ISSUED` daily admission tied to the holder, refunding each admission's `charge_cents` in full.

### 3.9. Closure Resolution and Season Rollover

A `PoolClosureEvent` in `ACTIVE` status can be resolved directly by a manager, transitioning the closure to `RESOLVED`, stamping `ended_at` with the current clock, and recomputing the facility's posture. Resolving one closure while another `ACTIVE` closure exists for the same facility is rejected with `ERR_REOPEN_CRITERIA_NOT_MET`. Alternatively the facility-wide reopen call resolves every active closure at once, moving each from `ACTIVE` to `RESOLVED`. In both cases the reopen is gated: all active closures for the facility must be ended (or be ended by this call), a chemistry-triggered closure requires the most recent chemistry log to be `IN_RANGE` (with the two-consecutive-`IN_RANGE` rule applied after a streak of two or more `OUT_OF_RANGE` readings), and a staffing-triggered closure requires the scheduled lifeguard coverage for the next two hours to meet or exceed the current `required_lifeguard_count`. Failure of any criterion is rejected with `ERR_REOPEN_CRITERIA_NOT_MET`. Once met, the facility's `version` increments; the facility-wide reopen always returns the facility to `OPEN`, while individual resolution returns the facility to `OPEN` — or to `RESTRICTED` when its `chemistry_state` is `WARNING` — and in either path a facility in `CLOSED_SEASON` is left untouched.

Season rollover is a system transition: when the clock advances past a `PUBLISHED` season's `end_date`, the season moves to `CLOSED`. If no future `PUBLISHED` season exists for the facility, the facility transitions to `CLOSED_SEASON`, every future `LessonSession` is cancelled, and `ACTIVE` season passes tied to the closed season become unusable for new admissions (their `status` is not rewritten — they remain `ACTIVE` records, but admission validation rejects them).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a facility, season, pass holder, season pass, daily admission, lesson level, lesson session, enrollment, lifeguard, shift, lane allocation, rental, incident report, chemistry log, or closure event) return `201 Created`. Operations that modify an existing resource — state transitions such as publish, refund, enter, exit, schedule, cancel, drop, check-in, check-out, approve, reject, submit, confirm, dismiss, resolve, reopen, suspend, reinstate, release, and the clock-driving call — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and re-evaluate time-dependent transitions | AquaticsManager |
| POST | `/facilities` | Create a Facility | AquaticsManager |
| GET | `/facilities/{id}` | Read a Facility including computed posture | AquaticsManager, GateAttendant, Lifeguard, PassHolder |
| GET | `/facilities` | List Facilities | AquaticsManager, GateAttendant, Lifeguard, PassHolder |
| GET | `/facilities/{id}/chemistry-logs` | List ChemistryLogs for a Facility (newest first) | AquaticsManager, Lifeguard, GateAttendant |
| GET | `/facilities/{id}/closures` | List PoolClosureEvents for a Facility | AquaticsManager, Lifeguard, GateAttendant, PassHolder |
| POST | `/facilities/{id}/chemistry-logs` | Record a ChemistryLog; classification computed; may trigger closure cascade | Lifeguard, AquaticsManager |
| POST | `/facilities/{id}/closures` | Manually declare a closure (typically WEATHER) | AquaticsManager |
| POST | `/facilities/{id}/reopen` | Resolve active closures and return Facility to OPEN | AquaticsManager |
| POST | `/seasons` | Create a MembershipSeason in DRAFT | AquaticsManager |
| GET | `/seasons/{id}` | Read a MembershipSeason | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/seasons` | List MembershipSeasons (filterable by facility_id) | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/seasons/{id}/passes` | List SeasonPasses purchased against a MembershipSeason | AquaticsManager, GateAttendant |
| POST | `/seasons/{id}/publish` | Publish a season (validates pricing and overlap) | AquaticsManager |
| POST | `/seasons/{id}/close` | Manually close a PUBLISHED season | AquaticsManager |
| POST | `/pass-holders` | Register a PassHolder | GateAttendant, AquaticsManager |
| GET | `/pass-holders/{id}` | Read a PassHolder | GateAttendant, AquaticsManager, PassHolder |
| GET | `/pass-holders/{id}/passes` | List SeasonPasses for a PassHolder | GateAttendant, AquaticsManager, PassHolder |
| GET | `/pass-holders/{id}/admissions` | List DailyAdmissions for a PassHolder | GateAttendant, AquaticsManager, PassHolder |
| GET | `/pass-holders/{id}/rentals` | List FacilityRentals for a PassHolder | GateAttendant, AquaticsManager, PassHolder |
| GET | `/pass-holders/{id}/enrollments` | List LessonEnrollments for a PassHolder | GateAttendant, AquaticsManager, PassHolder |
| POST | `/passes` | Purchase a SeasonPass (price snapshotted by residency) | GateAttendant, AquaticsManager |
| GET | `/passes/{id}` | Read a SeasonPass | GateAttendant, AquaticsManager, PassHolder |
| POST | `/passes/{id}/refund` | Refund a SeasonPass (ACTIVE → REFUNDED) | AquaticsManager |
| GET | `/passes/{id}/admissions` | List DailyAdmissions tied to a given SeasonPass | GateAttendant, AquaticsManager |
| POST | `/admissions` | Issue a DailyAdmission for a PassHolder | GateAttendant |
| GET | `/admissions/{id}` | Read a DailyAdmission | GateAttendant, AquaticsManager, PassHolder |
| GET | `/admissions` | List DailyAdmissions | GateAttendant, AquaticsManager |
| POST | `/admissions/{id}/enter` | Mark admission entered; bather count incremented | GateAttendant |
| POST | `/admissions/{id}/exit` | Mark admission exited; bather count decremented | GateAttendant |
| POST | `/lesson-levels` | Create a SwimLessonLevel | AquaticsManager |
| GET | `/lesson-levels/{id}` | Read a SwimLessonLevel | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/lesson-levels` | List SwimLessonLevels | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/lesson-levels/{id}/enrollments-as-evidence` | List LessonEnrollments that cite this level as placement evidence | AquaticsManager, GateAttendant |
| POST | `/lesson-sessions` | Create a LessonSession in DRAFT | AquaticsManager |
| GET | `/lesson-sessions/{id}` | Read a LessonSession | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/lesson-sessions` | List LessonSessions | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/lesson-sessions/{id}/enrollments` | List LessonEnrollments for a LessonSession | AquaticsManager, GateAttendant, PassHolder, Lifeguard |
| GET | `/lesson-sessions/{id}/lane-allocations` | List LaneAllocations owned by a LessonSession | AquaticsManager, GateAttendant |
| POST | `/lesson-sessions/{id}/schedule` | Transition DRAFT → SCHEDULED; reserves lanes via a LaneAllocation | AquaticsManager |
| POST | `/lesson-sessions/{id}/cancel` | Cancel a LessonSession; cascades to enrollments and lane allocation | AquaticsManager |
| POST | `/enrollments` | Enroll a PassHolder in a LessonSession | GateAttendant, AquaticsManager, PassHolder |
| GET | `/enrollments/{id}` | Read a LessonEnrollment | AquaticsManager, GateAttendant, PassHolder |
| POST | `/enrollments/{id}/drop` | Drop an enrollment; may promote waitlist head | AquaticsManager, PassHolder |
| POST | `/lifeguards` | Register a Lifeguard | AquaticsManager |
| GET | `/lifeguards/{id}` | Read a Lifeguard | AquaticsManager, Lifeguard, GateAttendant |
| GET | `/lifeguards` | List Lifeguards | AquaticsManager, GateAttendant |
| GET | `/lifeguards/{id}/shifts` | List LifeguardShifts for a Lifeguard | AquaticsManager, Lifeguard, GateAttendant |
| POST | `/lifeguards/{id}/suspend` | Suspend a lifeguard (cancels future shifts) | AquaticsManager |
| POST | `/lifeguards/{id}/reinstate` | Reinstate a suspended lifeguard | AquaticsManager |
| GET | `/lifeguards/{id}/chemistry-logs` | List ChemistryLogs recorded by a Lifeguard | AquaticsManager, GateAttendant |
| GET | `/lifeguards/{id}/incident-reports` | List IncidentReports filed by a Lifeguard | AquaticsManager, GateAttendant |
| POST | `/shifts` | Create a LifeguardShift | AquaticsManager |
| GET | `/shifts/{id}` | Read a LifeguardShift | AquaticsManager, Lifeguard, GateAttendant |
| GET | `/shifts` | List LifeguardShifts | AquaticsManager, GateAttendant |
| POST | `/shifts/{id}/check-in` | Lifeguard checks in for their shift | Lifeguard |
| POST | `/shifts/{id}/cancel` | Cancel a shift | AquaticsManager |
| POST | `/lane-allocations` | Reserve lanes for LAP_SWIM or SWIM_TEAM | AquaticsManager |
| GET | `/lane-allocations/{id}` | Read a LaneAllocation | AquaticsManager, Lifeguard, GateAttendant |
| GET | `/lane-allocations` | List LaneAllocations | AquaticsManager, Lifeguard, GateAttendant |
| POST | `/lane-allocations/{id}/release` | Manually release a RESERVED LaneAllocation | AquaticsManager |
| POST | `/rentals` | Create a FacilityRental REQUEST | PassHolder, GateAttendant, AquaticsManager |
| GET | `/rentals/{id}` | Read a FacilityRental | PassHolder, GateAttendant, AquaticsManager |
| GET | `/rentals` | List FacilityRentals | GateAttendant, AquaticsManager |
| POST | `/rentals/{id}/approve` | Approve a FacilityRental (validates exclusive use and OCC) | AquaticsManager |
| POST | `/rentals/{id}/reject` | Reject a FacilityRental | AquaticsManager |
| POST | `/rentals/{id}/check-in` | Check in a rental party; bather count incremented by party size | GateAttendant |
| POST | `/rentals/{id}/check-out` | Check out a rental party; final price computed with overtime | GateAttendant |
| POST | `/rentals/{id}/cancel` | Cancel a REQUESTED or APPROVED rental (cancellation fee may apply) | PassHolder, AquaticsManager |
| POST | `/incident-reports` | Create an IncidentReport in DRAFT | Lifeguard, AquaticsManager |
| GET | `/incident-reports/{id}` | Read an IncidentReport | Lifeguard, AquaticsManager, GateAttendant |
| GET | `/incident-reports` | List IncidentReports | AquaticsManager, GateAttendant |
| POST | `/incident-reports/{id}/submit` | Submit a DRAFT IncidentReport | Lifeguard |
| POST | `/incident-reports/{id}/confirm` | Confirm a SUBMITTED IncidentReport (may trigger ban) | AquaticsManager |
| POST | `/incident-reports/{id}/dismiss` | Dismiss a SUBMITTED IncidentReport | AquaticsManager |
| GET | `/closures/{id}` | Read a PoolClosureEvent | AquaticsManager, Lifeguard, GateAttendant, PassHolder |
| POST | `/closures/{id}/resolve` | Resolve a specific PoolClosureEvent | AquaticsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FACILITY_CLOSED` | 409 |
| `ERR_FACILITY_AT_CAPACITY` | 409 |
| `ERR_HOLDER_BANNED` | 409 |
| `ERR_GUARD_NOT_CERTIFIED` | 409 |
| `ERR_RENTAL_OVERLAP` | 409 |
| `ERR_RENTAL_CAPACITY` | 409 |
| `ERR_LANE_CAPACITY_EXCEEDED` | 409 |
| `ERR_SESSION_OUTSIDE_SEASON` | 422 |
| `ERR_ADMISSION_DATE_INVALID` | 422 |
| `ERR_SHIFT_WINDOW_INVALID` | 422 |
| `ERR_PREREQUISITE_NOT_MET` | 422 |
| `ERR_SEASON_OVERLAP` | 409 |
| `ERR_CHEMISTRY_INPUT_INVALID` | 422 |
| `ERR_REOPEN_CRITERIA_NOT_MET` | 409 |
| `ERR_PASS_NOT_VALID` | 409 |
| `ERR_ALREADY_CHECKED_IN` | 409 |
