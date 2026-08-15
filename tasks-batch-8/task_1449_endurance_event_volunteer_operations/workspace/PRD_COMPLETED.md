# Endurance Event Volunteer Operations API — Product Requirements Document

## 1. Introduction

Organizing an endurance event — a city marathon, a trail ultra, a charity ride — means staffing dozens of posts spread across miles of course with a workforce that is unpaid, lightly vetted, and prone to drifting away on race morning. The organizing committee must publish a catalog of volunteer roles with enforceable minimum ages, skills, and training gates; fill shift seats per course segment; survive the race-day churn of no-shows by drawing on a pool of floating volunteers; and then convert verified hours into fundraising credit for affiliated groups and recognition for the volunteers themselves. When any of this is tracked in spreadsheets, seats go unfilled, under-age or untrained volunteers slip onto the course, and credit disputes linger for weeks.

This document specifies the Endurance Event Volunteer Operations API, the committee's single system of record for that entire arc: role catalog and shift creation by course segment, volunteer registration with minimum-age and skill requirements, training records and captain assignment, race-day check-in with credential and supply distribution, no-show backfill from the floating pool, hour tracking feeding group fundraising credit, an appreciation and retention program, and post-event debriefs that drive adjustments to next year's roles. All endpoints are mounted under the `/volunteer-ops` prefix. Every temporal rule in this document — signup windows, check-in windows, confirmation deadlines, training validity — is evaluated against a server-maintained logical clock (see §2.4), never against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: identity and authorization, the response envelope, pagination, the logical clock, resource invariants, precision, concurrency control, and the order in which validations run.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or whose role value does not name a declared role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The API declares six roles, spelled exactly as follows: `Anonymous`, `Volunteer`, `Captain`, `GroupLeader`, `VolunteerCoordinator`, and `EventDirector`. Each endpoint admits a fixed set of roles (enumerated in §4); a caller whose role is not in the endpoint's set is rejected with `ERR_FORBIDDEN_ROLE`.

Role identity determines what `X-User-ID` means and which resources a caller owns:

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the anonymous caller may self-register as a volunteer and read public resources, and the server never compares the identifier to any entity's `id`.
- When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer — a signup's `volunteer_id`, or the volunteer standing behind an hour log's signup — compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Captain`, `X-User-ID` is likewise the `id` of a Volunteer — specifically one who holds a captain signup (`is_captain` true) on the shift being acted upon; captain-scoped ownership checks compare both the volunteer identity and membership of that captain signup in the relevant shift.
- When `X-User-Role` is `GroupLeader`, `X-User-ID` is the `id` of the acting FundraisingGroup; ownership checks on group-scoped resources compare the resource's group reference to `X-User-ID`.
- When `X-User-Role` is `VolunteerCoordinator` or `EventDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record the acting capacity (for example, as `verified_by_role` on an hour log at verification time) but does not compare the identifier to any entity's `id`.

Entity-backed callers that touch a resource they do not own are rejected with `ERR_NOT_RESOURCE_OWNER`. The specific ownership rule for each operation is stated alongside its workflow in §3.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, list endpoints accept resource-specific filters as query parameters: events, course segments, role catalog entries, fundraising groups, and supply inventories filter by `event_id`; shifts filter by `event_id`, `role_entry_id`, or `segment_id`; volunteers filter by `event_id` or `group_id`; training records filter by `event_id` or `volunteer_id`; signups filter by `event_id`, `volunteer_id`, `shift_id`, `status`, or `replaces_signup_id`; distribution records filter by `event_id`, `signup_id`, `inventory_id`, or `kind`; hour logs filter by `event_id` or `signup_id`; debrief reports filter by `event_id`, `shift_id`, or `author_volunteer_id`; and role adjustments filter by `event_id`, `role_entry_id`, or `debrief_report_id`.

### 2.4. The Logical Clock

The server maintains a logical clock, and every temporal rule in this document — signup windows, the check-in window, confirmation deadlines, the no-show grace period, the backfill window, training validity, event start and end gates — is evaluated against that clock. The logical clock never falls back to wall-clock time. At server startup the clock reads exactly 2026-08-01T00:00:00Z. An `EventDirector`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `now_iso8601`. The same clock drives the ops-run epoch sweep described in §3.9.

### 2.5. The Event as Operational Backbone

Every resource in the system belongs to exactly one Event: course segments, role catalog entries, shifts, fundraising groups, volunteers, training records, signups, supply inventories, distribution records, hour logs, debrief reports, and role adjustments all carry an `event_id` binding them to their owning event. The event's lifecycle therefore anchors everything beneath it. When the event locks its signup window, its shifts lock with it; when race day starts, locked shifts move into progress; when the event is cancelled, the cancellation cascades downward through shifts and signups to outstanding distribution records (the full cascade appears in §3.1). These cascade and reconciliation transitions may fire without an explicit client request on the affected child resource — the server transitions children automatically whenever the parent's rules require it.

The same backbone principle runs in the other direction: computed counters on a shift (its filled and on-course headcounts) are derived continuously from the statuses of its signups, so child mutations realign the parent without any explicit shift-level write. Any mutation — client-driven or system-driven — refreshes the affected resource's `updated_at` timestamp and increments its `version`.

### 2.6. Common Resource Properties

Every resource in this API — events, course segments, role catalog entries, shifts, fundraising groups, volunteers, training records, signups, supply inventories, distribution records, hour logs, debrief reports, and role adjustments — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation of the resource, including system-initiated transitions and cascade-driven changes. This field backs the optimistic concurrency rules of §2.9.

### 2.7. Reference Validation and Existence Checks

When an endpoint path contains resource identifiers, the server validates them sequentially, left to right, and rejects the request with the not-found error of the first identifier that does not resolve to an existing resource. The mapping is fixed: `eventId` to `ERR_EVENT_NOT_FOUND`, `segmentId` to `ERR_SEGMENT_NOT_FOUND`, `roleEntryId` to `ERR_ROLE_ENTRY_NOT_FOUND`, `shiftId` to `ERR_SHIFT_NOT_FOUND`, `groupId` to `ERR_GROUP_NOT_FOUND`, `volunteerId` to `ERR_VOLUNTEER_NOT_FOUND`, `trainingRecordId` to `ERR_TRAINING_RECORD_NOT_FOUND`, `signupId` to `ERR_SIGNUP_NOT_FOUND`, `inventoryId` to `ERR_INVENTORY_NOT_FOUND`, `distributionId` to `ERR_DISTRIBUTION_NOT_FOUND`, `hourLogId` to `ERR_HOUR_LOG_NOT_FOUND`, `debriefId` to `ERR_DEBRIEF_NOT_FOUND`, and `adjustmentId` to `ERR_ADJUSTMENT_NOT_FOUND`. All of these carry HTTP status 404.

Foreign-key references supplied in request bodies — `event_id`, `volunteer_id`, `shift_id`, `group_id`, `role_entry_id`, `segment_id`, `inventory_id`, `signup_id`, and `debrief_report_id` — must likewise reference existing resources and draw from the same not-found family. Existence is verified before any state or business rule is consulted (see §2.10), so a request naming a missing shift is answered with `ERR_SHIFT_NOT_FOUND` rather than with a shift-state error.

### 2.8. Hours, Money, and Rounding Discipline

Three families of numbers recur throughout the API, each with a pinned precision discipline. Claimed volunteer hours are decimal values rounded half up to exactly two decimal places. Credited volunteer hours are exact quarter-hour multiples: the quarter-hour count is rounded half up to a whole number of quarters per individual hour-log entry before any summation takes place — group and volunteer totals are sums of per-entry rounded values, never the rounding of a sum. Fundraising credit and sponsor-match amounts are integer numbers of cents, with each tier slice and the match itself rounded half up to a whole cent at the moment it is computed. Recognition points are integers. The full formulas live in §3.7 and §3.8; the invariant here is that no calculation anywhere in the system uses approximate or floating arithmetic, and the rounding point of each quantity is fixed by these rules rather than left to the caller.

### 2.9. Optimistic Concurrency Control

Three write operations carry a mandatory optimistic-concurrency field, and no other endpoint accepts one:

- Updating an event's configuration requires the request to carry `expected_event_version`, holding the client's last observed `version` of the event. If the event's current `version` has advanced beyond that observed value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the event before retrying.
- Updating a volunteer's mutable profile fields requires `expected_volunteer_version`, holding the client's last observed `version` of the volunteer. A mismatch with the volunteer's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — for example, when a coordinator edits skills after the volunteer's record has already been advanced by another write.
- Applying an approved role adjustment requires `expected_role_version`, holding the client's last observed `version` of the target role catalog entry. A mismatch with the entry's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); since two approved adjustments on the same role could both legitimately apply, the later one must re-read the role before re-applying.

Each successful write increments the parent entity's `version`, so any stored expectation immediately becomes stale.

### 2.10. Validation Priority Order

A request that would fail several checks is answered with exactly one error, and which error is not arbitrary. The server evaluates checks in the following fixed order, returning the first failure and never evaluating later gates for that request:

1. Authentication context: both headers present and the role declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization: the caller's role admitted by the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Existence: path identifiers validated left to right, then body foreign-key references (the not-found family of §2.7).
4. State preconditions: the state-machine gates of the target resources — event status gates, signup status gates, and the training, role-entry, group, hour-log, distribution, debrief, and adjustment state checks (their respective 409 errors, including `ERR_INVALID_EVENT_STATE`, `ERR_EVENT_NOT_PUBLISHED`, `ERR_SHIFT_NOT_OPEN`, the `ERR_SIGNUP_NOT_*` family, `ERR_VOLUNTEER_NOT_ELIGIBLE`, `ERR_VOLUNTEER_NOT_SCREENABLE`, `ERR_VOLUNTEER_NOT_SUSPENDED`, `ERR_TRAINING_INVALID_STATE`, `ERR_ROLE_ENTRY_INVALID_STATE`, `ERR_ROLE_ENTRY_NOT_ACTIVE`, `ERR_GROUP_INVALID_STATE`, `ERR_HOUR_LOG_INVALID_STATE`, `ERR_DISTRIBUTION_INVALID_STATE`, `ERR_DEBRIEF_INVALID_STATE`, `ERR_ADJUSTMENT_INVALID_STATE`, `ERR_EVENT_READINESS_INCOMPLETE`, `ERR_EVENT_NOT_YET_STARTED`, `ERR_EVENT_NOT_YET_ENDED`, `ERR_SIGNUPS_STILL_ON_COURSE`, `ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS`, `ERR_EVENT_CLOSE_BLOCKED`, and `ERR_DEBRIEF_NOT_ACKNOWLEDGED`).
5. Minimum age (`ERR_MIN_AGE_NOT_MET`).
6. Required skill (`ERR_REQUIRED_SKILL_MISSING`).
7. Training currency (`ERR_TRAINING_NOT_CURRENT`).
8. Temporal windows: the signup window (`ERR_SIGNUP_WINDOW_CLOSED`, `ERR_EARLY_ACCESS_RESTRICTED`), the check-in window (`ERR_CHECKIN_WINDOW_INVALID`), the confirmation deadline (`ERR_CONFIRM_DEADLINE_PASSED`), and the no-show grace period (`ERR_NO_SHOW_GRACE_NOT_PASSED`).
9. Constraint satisfaction: volunteer shift-time overlap (`ERR_SHIFT_TIME_OVERLAP`), segment mile overlap (`ERR_SEGMENT_MILE_OVERLAP`), per-event code uniqueness, one active signup per volunteer per shift (`ERR_DUPLICATE_SIGNUP`), one training record per volunteer per module (`ERR_DUPLICATE_TRAINING_RECORD`), one captain per shift (`ERR_CAPTAIN_SLOT_TAKEN`), one issued credential per signup (`ERR_CREDENTIAL_ALREADY_ISSUED`), the `inventory_id`-versus-`kind` requirement, and datetime ordering (all remaining cases as `ERR_INVALID_REQUEST`).
10. Capacity: headcount room at approval (`ERR_SHIFT_CAPACITY_REACHED`) and zero non-terminal signups at role retirement (`ERR_ROLE_IN_USE`).
11. Group affiliation: the referenced fundraising group must be `ACTIVE` (`ERR_GROUP_SUSPENDED`).
12. Supply stock: units remain to issue (`ERR_OUT_OF_STOCK`).
13. Ownership: entity-backed callers act only on their own resources (`ERR_NOT_RESOURCE_OWNER`).

Because ownership is evaluated last, a request that fails an earlier gate surfaces that gate's error rather than an ownership error; conversely, `ERR_NOT_RESOURCE_OWNER` implies the request passed every other check.

## 3. Business Logic & Workflows

This section walks the operational life of an event in the order a committee lives it: standing up the event and its course, defining roles and shifts, registering and screening volunteers, training them, filling seats, running race day, absorbing no-shows, settling hours and credit, and closing out with debriefs and role adjustments. State names appear as exact uppercase strings; error identifiers appear inline where their trigger lives.

### 3.1. The Event Lifecycle: From Draft to Cancellation

An `EventDirector` opens a new event by supplying a human-readable `name` and five instants: `event_start_at`, `event_end_at`, `early_access_opens_at`, `signup_opens_at`, and `signup_closes_at`. The ordering invariants among them are strict, and any violation is rejected with `ERR_INVALID_REQUEST`: `event_end_at` must fall strictly after `event_start_at`; `signup_opens_at` must fall on or after `early_access_opens_at` and strictly before `signup_closes_at`; and `signup_closes_at` must fall strictly after `signup_opens_at` and on or before `event_start_at`. A new event is born in `DRAFT` status with `version` 1. Its full status vocabulary is `DRAFT`, `PUBLISHED`, `LOCKED`, `RACE_DAY`, `COMPLETED`, `DEBRIEF_OPEN`, `CLOSED`, and `CANCELLED`, the last two being terminal.

While the event remains `DRAFT`, the director may revise its `name` and any of the five instants through a configuration update that must carry `expected_event_version` under the concurrency rule of §2.9; each successful write increments the event's `version` by one. Once the event has left `DRAFT`, configuration updates are rejected with `ERR_INVALID_EVENT_STATE`.

Publishing moves the event from `DRAFT` to `PUBLISHED` and gates on a readiness invariant: at least one role catalog entry in `ACTIVE` status, at least one course segment, and at least one shift must exist for the event. Any shortfall is rejected with `ERR_EVENT_READINESS_INCOMPLETE`.

The signup window closes in either of two ways: the director locks signups deliberately, or the epoch sweep of §3.9 auto-locks the event once the logical clock reaches `signup_closes_at`. Either way the event moves from `PUBLISHED` to `LOCKED`, and every shift of the event in `OPEN` or `FULL` status cascades to `LOCKED`.

Starting race day moves the event from `LOCKED` to `RACE_DAY` and requires the logical clock to have reached `event_start_at`; an early attempt is rejected with `ERR_EVENT_NOT_YET_STARTED`. The transition cascades every `LOCKED` shift of the event to `IN_PROGRESS`. Completing the event moves it from `RACE_DAY` to `COMPLETED` and carries two gates: the clock must be at or past `event_end_at` (`ERR_EVENT_NOT_YET_ENDED`), and zero signups of the event may remain in `CHECKED_IN` status — no one may still be on the course — (`ERR_SIGNUPS_STILL_ON_COURSE`). From `COMPLETED`, the director opens the debrief window, moving the event to `DEBRIEF_OPEN`; the workflows of that phase and the final close-out to `CLOSED` are covered in §3.9.

Cancellation is available from `DRAFT`, `PUBLISHED`, `LOCKED`, `RACE_DAY`, and `COMPLETED`, always landing in terminal `CANCELLED`, and always running the same three-link cascade. Link one: every shift of the event in `OPEN`, `FULL`, `LOCKED`, or `IN_PROGRESS` status becomes `CANCELLED`. Link two: every signup on those shifts in `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status becomes `CANCELLED` — the `CHECKED_IN` case arises when a mid-race cancellation strands volunteers already on the course, and their credentials must be pulled. Link three: every distribution record on a cancelled signup still in `ISSUED` status becomes `REVOKED`, and revoked records of `kind` `SUPPLY_ITEM` decrement the owning inventory's `quantity_issued`, returning those units to stock.

### 3.2. Course Segments, the Role Catalog, and Shifts

A `VolunteerCoordinator` lays out the course as segments. Each segment carries its `event_id`, a `segment_code` unique within that event (for example, `MILE-05-WATER`), a half-open mile range from `mile_start` (inclusive) to `mile_end` (exclusive), and a `terrain_type` of `ROAD`, `TRAIL`, `BRIDGE`, or `TRACK`. `mile_end` must be strictly greater than `mile_start`, and duplicate segment codes within an event are rejected; both violations surface as `ERR_INVALID_REQUEST`. A new segment conflicts with an existing segment of the same event when the new `mile_start` is less than the existing segment's `mile_end` and the existing segment's `mile_start` is less than the new `mile_end`; the conflict is rejected with `ERR_SEGMENT_MILE_OVERLAP`. The ranges are half-open, so exact adjacency — one segment's `mile_end` equal to another's `mile_start` — is legal.

The role catalog defines who may staff what. A coordinator creates each entry with `event_id`, a `role_code` unique within the event, a display `title`, a `min_age_years` in whole years measured against the event date, and optionally `required_skill`, `required_training_module`, and `credit_weight`. The `required_skill` is one of `NONE`, `MEDICAL`, `BIKE_MARSHAL`, `TIMING_TECH`, or `COURSE_MARSHAL`, defaulting to `NONE`. The `required_training_module` is one of `NONE`, `SAFETY_BRIEFING`, `MEDICAL_RESPONSE`, or `CAPTAIN_COURSE`, defaulting to `NONE`, which means the role carries no training gate. The `credit_weight` is the fundraising-credit hour multiplier for the role: greater than zero, at most three, and defaulting to 1.0. Duplicate role codes within an event are rejected with `ERR_INVALID_REQUEST`. A new entry starts `ACTIVE`; its possible statuses are `ACTIVE`, `SUSPENDED`, and terminal `RETIRED`.

An `ACTIVE` entry can be suspended, and a `SUSPENDED` entry reactivated; attempting either transition from the wrong state is rejected with `ERR_ROLE_ENTRY_INVALID_STATE`. New signups against shifts of a suspended role are rejected with `ERR_ROLE_ENTRY_NOT_ACTIVE`. Retirement — invoked directly by a coordinator, or indirectly when an applied role adjustment carries `proposed_retire` (§3.9) — is permitted from `ACTIVE` or `SUSPENDED` and requires zero signups in `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status across all shifts of that role (`ERR_ROLE_IN_USE`). A retired role bars future shift creation, likewise with `ERR_ROLE_ENTRY_NOT_ACTIVE`.

A shift staffs one role on one segment. The coordinator supplies `event_id`, `role_entry_id`, `segment_id`, `start_at`, `end_at`, and `required_headcount` (at least one seat). All three references must belong to the same event, and the shift's window must sit inside the event's bounds: `start_at` no earlier than `event_start_at`, `end_at` no later than `event_end_at`, and `end_at` strictly after `start_at`. Violations are rejected with `ERR_INVALID_REQUEST`, and a referenced role that is not `ACTIVE` rejects the creation with `ERR_ROLE_ENTRY_NOT_ACTIVE`. A new shift opens in `OPEN` status with `understaffed_alert` false; its full status vocabulary is `OPEN`, `FULL`, `LOCKED`, `IN_PROGRESS`, `RECONCILED`, and `CANCELLED`, the last two terminal.

Two computed counters track each shift's staffing posture. `confirmed_count` counts the shift's signups in `APPROVED`, `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status — those are the seats occupied, while `REQUESTED`, `WAITLISTED`, `NO_SHOW`, and `CANCELLED` signups never occupy a seat. `checked_in_count` counts those in `CHECKED_IN` or `COMPLETED`. While the event is `PUBLISHED` and the shift is `OPEN` or `FULL`, the shift's status shadows its headcount: when `confirmed_count` reaches `required_headcount` the shift flips from `OPEN` to `FULL`, and when it drops back below, the shift returns from `FULL` to `OPEN` and the seat-open handling of §3.7 fires. These flips are automatic; no client writes the shift's status directly. The counters recompute on every signup approval, promotion, backfill, cancellation, no-show, sweep timeout, check-in, and check-out.

A coordinator may decommission an `OPEN` or `FULL` shift while its event is `DRAFT` or `PUBLISHED`; from any other event state the manual cancellation is rejected with `ERR_INVALID_EVENT_STATE`. The shift becomes `CANCELLED`, and every signup on it in `REQUESTED`, `WAITLISTED`, `APPROVED`, or `CONFIRMED` status is cancelled with it. `LOCKED` and `IN_PROGRESS` shifts are cancelled only through the event-level cascade of §3.1; the race-day form of that cascade additionally revokes the `ISSUED` distribution records of `CHECKED_IN` signups.

### 3.3. Volunteer Registration, Screening, and Fundraising Groups

Registration is per-event and self-service. An `Anonymous` caller — or a `VolunteerCoordinator` acting on someone's behalf — registers by supplying `event_id`, `full_name`, `date_of_birth` as an ISO `YYYY-MM-DD` date, and optionally `skill_tags`, `group_id`, `float_opt_in`, and `is_returning`. The `skill_tags` array draws from `MEDICAL`, `BIKE_MARSHAL`, `TIMING_TECH`, and `COURSE_MARSHAL` and defaults to empty. The `float_opt_in` flag enters the volunteer into the floating backfill pool of §3.7 and defaults to false. The `is_returning` flag marks a returning volunteer under the retention program — it gates the early-access signup window of §3.5 and the waitlist ranking — and defaults to false. A new volunteer starts `REGISTERED` with `no_show_strikes` at zero; the status vocabulary is `REGISTERED`, `ELIGIBLE`, and `SUSPENDED`.

At registration the system derives `age_years_on_event`, and it reuses that derivation at screening, signup creation, and approval: the whole years between `date_of_birth` and the calendar date of the event's `event_start_at` in UTC — the event year minus the birth year, reduced by one when the event date's month-and-day falls earlier in the calendar year than the birthday's month-and-day. A birthday falling exactly on the event date counts as reached.

Screening is the committee's gate. A coordinator screens a `REGISTERED` volunteer — from any other status the request is rejected with `ERR_VOLUNTEER_NOT_SCREENABLE` — enforcing the global floor: `age_years_on_event` of at least fourteen, otherwise `ERR_MIN_AGE_NOT_MET`. A passed screen moves the volunteer from `REGISTERED` to `ELIGIBLE`, the only status from which signups may be created or approved.

Fundraising groups exist so that teams — a school track club, a rotary chapter — can earn credit for their members' hours. The `EventDirector` creates each group with `event_id`, a display `name`, and a `charity_code` unique within the event (a duplicate is `ERR_INVALID_REQUEST`); the group starts `ACTIVE`, and its other status is `SUSPENDED`. Affiliation is optional: a volunteer's `group_id` is null when unaffiliated. A volunteer may affiliate only with an `ACTIVE` group, both at registration and on later profile updates; referencing a suspended group is rejected with `ERR_GROUP_SUSPENDED`. Suspending a group (`ACTIVE` to `SUSPENDED`; from any other state, `ERR_GROUP_INVALID_STATE`) blocks new affiliations while existing members keep their affiliation — and, per §3.8, their already-affiliated hours keep accruing credit. Reinstatement returns a `SUSPENDED` group to `ACTIVE` under the same state gate.

After registration, the mutable profile fields — `skill_tags`, `group_id`, `float_opt_in`, and `is_returning` — are revised through a profile update that must carry `expected_volunteer_version` under the rule of §2.9; a `Volunteer` caller may update only their own record (`ERR_NOT_RESOURCE_OWNER`), a coordinator may update anyone's, and every successful write increments the volunteer's `version` by one. A group change into a `SUSPENDED` group fails with `ERR_GROUP_SUSPENDED`. Each `NO_SHOW` signup adds one strike to `no_show_strikes` (§3.7); when the count reaches two, an `ELIGIBLE` volunteer is suspended automatically. A coordinator can reinstate a `SUSPENDED` volunteer — from any other status the request is rejected with `ERR_VOLUNTEER_NOT_SUSPENDED` — which returns the volunteer to `ELIGIBLE` and resets `no_show_strikes` to zero.

### 3.4. Training Records and Credential Currency

Certain roles require proof of preparation, which the committee tracks as training records. A coordinator enrolls a volunteer in a module by supplying `event_id`, `volunteer_id`, and `module_code` — one of `SAFETY_BRIEFING`, `MEDICAL_RESPONSE`, or `CAPTAIN_COURSE`. One record exists per volunteer per module: a second enrollment for the same pair is rejected with `ERR_DUPLICATE_TRAINING_RECORD`, and the remedy is re-enrollment of the existing record, not a new one. A fresh record starts `ENROLLED` with `attempt_count` at one; the status vocabulary is `ENROLLED`, `PASSED`, `FAILED`, and `EXPIRED`, none of them terminal.

A coordinator records the outcome. Passing — allowed only from `ENROLLED`, otherwise `ERR_TRAINING_INVALID_STATE` — moves the record to `PASSED`, stamps `passed_at` with the current instant, and sets `valid_until` by adding the module's validity window: thirty days for `SAFETY_BRIEFING`, three hundred sixty-five days for `CAPTAIN_COURSE`, and seven hundred thirty days for `MEDICAL_RESPONSE`. Failing — likewise only from `ENROLLED`, otherwise `ERR_TRAINING_INVALID_STATE` — moves the record to `FAILED` and stamps neither field. Re-enrollment is permitted from `FAILED` or `EXPIRED` only (`ERR_TRAINING_INVALID_STATE` otherwise); it returns the record to `ENROLLED`, increments `attempt_count` by one, and clears `passed_at` and `valid_until` back to null.

A role's training requirement counts as current only when the volunteer holds a record for that exact module in `PASSED` status whose `valid_until` has not yet passed relative to the logical clock; `ENROLLED`, `FAILED`, and `EXPIRED` records never satisfy a gate, and a role whose `required_training_module` is `NONE` is always satisfied. Training currency is checked at signup creation, again at approval, and at captain assignment, each time surfacing `ERR_TRAINING_NOT_CURRENT` on failure.

Validity can lapse mid-campaign. The epoch sweep of §3.9 moves every `PASSED` record whose `valid_until` has passed into `EXPIRED`, and the expiry cascades: every signup of that volunteer in `APPROVED` or `CONFIRMED` status whose shift's role requires exactly the expired module is cancelled, each freed seat running the seat-open handling of §3.7.

### 3.5. The Signup Pipeline: Windows, Requests, and Approvals

Once an event is `PUBLISHED`, volunteers request seats. A signup is created by supplying the `volunteer_id` and the `shift_id`; a `Volunteer` caller may submit only their own `volunteer_id` — it must equal `X-User-ID`, otherwise `ERR_NOT_RESOURCE_OWNER` — while a coordinator may file on anyone's behalf. The new record stamps `requested_at` with the creation instant and lands in `REQUESTED` status when the shift still has a free seat, or in `WAITLISTED` when the shift's `confirmed_count` has already reached its `required_headcount`; either way its `origin` begins as `DIRECT`, and its `is_captain` flag starts false. The full status vocabulary of a signup is `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, and `CANCELLED`, with `COMPLETED`, `NO_SHOW`, and `CANCELLED` terminal.

The signup window is three-phased. Before `early_access_opens_at`, and from `signup_closes_at` onward, creation is rejected with `ERR_SIGNUP_WINDOW_CLOSED`. During the early-access window — from `early_access_opens_at` inclusive to `signup_opens_at` exclusive — only returning volunteers, those with `is_returning` true, may create signups; anyone else is rejected with `ERR_EARLY_ACCESS_RESTRICTED`. From `signup_opens_at` until `signup_closes_at` the window is open to all.

Creation and approval both run the same safety gauntlet, and approval re-runs it in full because any fact may have changed since the request was filed. The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`); the volunteer must be `ELIGIBLE` (`ERR_VOLUNTEER_NOT_ELIGIBLE`); the shift must be `OPEN` or `FULL` — a `LOCKED`, `IN_PROGRESS`, `RECONCILED`, or `CANCELLED` shift rejects with `ERR_SHIFT_NOT_OPEN`; the shift's role entry must be `ACTIVE` (`ERR_ROLE_ENTRY_NOT_ACTIVE`); the volunteer's `age_years_on_event` must be at least the role's `min_age_years` (`ERR_MIN_AGE_NOT_MET`); the role's `required_skill`, when not `NONE`, must appear in the volunteer's `skill_tags` (`ERR_REQUIRED_SKILL_MISSING`); and the role's training gate must be current per §3.4 (`ERR_TRAINING_NOT_CURRENT`). The per-gate order in which these checks surface relative to one another follows §2.10.

Two scheduling constraints guard against double-booking and duplication. First, the overlap rule: the candidate shift is compared against every shift on which the volunteer already holds an `APPROVED` or `CONFIRMED` signup — signups in `REQUESTED`, `WAITLISTED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, or `CANCELLED` status are ignored. When the two shifts cover different segments, a thirty-minute transition buffer applies; on the same segment the buffer is zero. An overlap exists when the candidate's `start_at` falls before the existing shift's `end_at` plus the buffer and, symmetrically, the existing shift's `start_at` falls before the candidate's `end_at` plus the buffer; a violation is rejected with `ERR_SHIFT_TIME_OVERLAP`. Back-to-back shifts on the same segment are allowed — an existing shift ending exactly when the candidate begins is not an overlap — while changing segments always demands a strict thirty-minute gap. Second, the duplicate rule: a volunteer may hold at most one signup in `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status on the same shift; a second active signup is rejected with `ERR_DUPLICATE_SIGNUP`.

Approval is a coordinator action on a `REQUESTED` signup; from any other status the request fails with `ERR_SIGNUP_NOT_APPROVABLE`. Beyond the re-run gauntlet, approval requires spare capacity — the shift's `confirmed_count` still below its `required_headcount`, otherwise `ERR_SHIFT_CAPACITY_REACHED`. A successful approval moves the signup to `APPROVED`, stamps `approved_at`, and computes `confirm_by_at` as the earlier of two instants: forty-eight hours after `approved_at`, or one hour before the shift's `start_at`. The shift's `confirmed_count` is then recomputed, and if it has reached `required_headcount` the shift moves from `OPEN` to `FULL` per §3.2.

While the event remains `PUBLISHED`, a seat that opens on a shift is offered to its waitlist. Eligible candidates are the `WAITLISTED` signups on that shift whose volunteer is `ELIGIBLE` and who still pass the age, skill, training, and overlap checks at promotion time. The ranking is a deterministic total order: returning volunteers (`is_returning` true) first, then earliest `requested_at`, then earliest `created_at` of the volunteer record; resource `id` values never participate in tie-breaking. The single top candidate is promoted to `APPROVED` with `origin` set to `WAITLIST_PROMOTION`, `approved_at` stamped, and `confirm_by_at` recomputed exactly as at a manual approval; the shift's counts and `FULL` posture recompute the same way. If no candidate qualifies, the seat simply stays open.

Confirmation is personal: only the volunteer themselves may confirm, so `X-User-ID` must equal the signup's `volunteer_id` (`ERR_NOT_RESOURCE_OWNER`), the signup must be `APPROVED` (`ERR_SIGNUP_NOT_CONFIRMABLE`), and the logical clock must not have passed `confirm_by_at` (`ERR_CONFIRM_DEADLINE_PASSED`). Confirmation moves the signup to `CONFIRMED` and stamps `confirmed_at`. An `APPROVED` signup left unconfirmed past its deadline is cancelled by the epoch sweep (§3.9), freeing the seat.

Cancellation keeps the pipeline honest. A volunteer may cancel their own signup, and a coordinator may cancel any signup, while it is in `REQUESTED`, `WAITLISTED`, `APPROVED`, or `CONFIRMED` status; cancellation from `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, or `CANCELLED` is rejected with `ERR_SIGNUP_NOT_CANCELLABLE`, as is a volunteer's self-cancellation of a `CONFIRMED` signup once the event has reached `RACE_DAY` — from that point, pulling out of a confirmed seat requires a coordinator. Freeing an `APPROVED` or `CONFIRMED` seat recomputes the shift's `confirmed_count`, drops a `FULL` shift back to `OPEN` when the count falls below `required_headcount`, and fires seat-open handling per §3.7. If the cancelled signup carried the shift's captain flag, the captain slot is released. Cancelling a `CONFIRMED` signup also revokes each of its distribution records still in `ISSUED` status, and revoked supply items decrement their inventory's `quantity_issued`. The cancellation path never cancels a `CHECKED_IN` signup — only the event-level cascade of §3.1 can do that.

Every shift may designate at most one captain. A coordinator marks a `CONFIRMED` signup as the shift's captain: the volunteer must hold a current `CAPTAIN_COURSE` training record (`ERR_TRAINING_NOT_CURRENT`), and the shift must not already have a captain — if another signup on the shift already has `is_captain` true, the assignment is rejected with `ERR_CAPTAIN_SLOT_TAKEN`. The designation sets `is_captain` true on the signup, and a coordinator may later clear the flag, releasing the slot. Captain status confers the race-day and debrief powers of §3.7 and §3.9.

### 3.6. Race Day: Check-in, Credentials, and Supplies

Race day begins when the event reaches `RACE_DAY`. A coordinator checks in a `CONFIRMED` signup — from any other status, `ERR_SIGNUP_NOT_CHECKINABLE` — and only while the event is `RACE_DAY` (`ERR_INVALID_EVENT_STATE`). Check-in is accepted within a fixed window: from sixty minutes before the shift's `start_at` through the shift's `end_at`, inclusive; outside that window the request fails with `ERR_CHECKIN_WINDOW_INVALID`. A successful check-in moves the signup to `CHECKED_IN`, stamps `checked_in_at`, recomputes the shift's `checked_in_count`, and automatically issues the volunteer's credential: a new distribution record of `kind` `CREDENTIAL` in `ISSUED` status, bound to that signup.

Beyond the automatic credential, a coordinator issues items from the supply tent by submitting the `signup_id`, the `kind` — `CREDENTIAL` or `SUPPLY_ITEM` — and, for supplies, the `inventory_id`. The recipient signup must be `CHECKED_IN` (`ERR_SIGNUP_NOT_CHECKED_IN`). The two kinds have opposite inventory rules: a `CREDENTIAL` record must carry a null `inventory_id`, a `SUPPLY_ITEM` record must carry a live one, and any mismatch is rejected with `ERR_INVALID_REQUEST`. A signup may hold at most one credential in `ISSUED` status; a second issuance is rejected with `ERR_CREDENTIAL_ALREADY_ISSUED`. Issuing a supply item consumes stock: the inventory's `quantity_issued` must still be below its `quantity_total`, which means issuing the final unit succeeds and the attempt after it fails with `ERR_OUT_OF_STOCK`. Every issuance lands in `ISSUED` status, stamps `issued_at`, and recomputes the inventory's `quantity_issued` upward. A distribution record's terminal statuses are `RETURNED` and `REVOKED`.

Supply inventories themselves are provisioned per event by coordinators: each item carries `event_id`, an `item_code` unique within the event (for example, `SAFETY_VEST`), an optional free-text `description`, and a `quantity_total` of zero or more units. The computed `quantity_issued` starts at zero and always equals the number of distribution records referencing that inventory with `kind` `SUPPLY_ITEM` in `ISSUED` status.

Items come back, and issuances get undone. Returning — allowed only for a `SUPPLY_ITEM` record in `ISSUED` status; credentials cannot be returned, and any record not currently `ISSUED` rejects with `ERR_DISTRIBUTION_INVALID_STATE` — moves the record to `RETURNED`, stamps `returned_at`, and decrements the inventory's `quantity_issued`. Revoking moves an `ISSUED` record of either kind to `REVOKED` (again, `ERR_DISTRIBUTION_INVALID_STATE` from any other status) and decrements `quantity_issued` when the record is a supply item. The cancellation cascades of §3.1 and §3.5 use the same revocation path.

Check-out closes the loop. A coordinator checks out a `CHECKED_IN` signup — from any other status, `ERR_SIGNUP_NOT_CHECKED_OUTABLE` — optionally supplying `break_minutes` for unpaid break time. The signup moves to `COMPLETED`, stamps `checked_out_at`, and spawns an hour log in `PENDING_VERIFICATION` status, with `event_id` denormalized from the signup at creation and its duration fields computed as §3.8 defines.

### 3.7. No-Shows, Strikes, and the Floating Backfill Pool

A `CONFIRMED` volunteer who never checks in can be marked as a no-show. The mark requires the signup to be `CONFIRMED` (`ERR_SIGNUP_NOT_NO_SHOWABLE`), the event to be `RACE_DAY` or `COMPLETED` (`ERR_INVALID_EVENT_STATE`), and the logical clock to have reached at least thirty minutes past the shift's `start_at` (`ERR_NO_SHOW_GRACE_NOT_PASSED`). The actor is a `VolunteerCoordinator`, or a `Captain` whose own captain signup sits on the same shift as the absent volunteer; anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`. The signup lands in terminal `NO_SHOW`.

Marking a no-show fires a five-link cascade. Link one: the volunteer's `no_show_strikes` increments by one. Link two: when the strike count reaches two, an `ELIGIBLE` volunteer flips automatically to `SUSPENDED`. Link three: every other signup of that volunteer in `APPROVED` or `CONFIRMED` status is cancelled, with each signup's `origin` preserved on the cancelled record. Link four: each affected shift recomputes its `confirmed_count` and falls from `FULL` to `OPEN` wherever the count dropped below `required_headcount`. Link five: every freed seat fires seat-open handling. Reinstatement per §3.3 is the only way back, and it zeroes the strike count.

Seat-open handling — fired by cancellations, no-shows, and sweep timeouts alike — chooses its mechanism by event phase. While the event is `PUBLISHED`, the seat is offered to the waitlist under the promotion ranking of §3.5. During `RACE_DAY`, the seat goes to the floating pool, but only while the logical clock is no later than ninety minutes after the shift's `start_at`; past that backfill window, and in every other event phase, no refill is attempted.

The floating pool is assembled from the event's volunteers who opted in with `float_opt_in` true. A backfill candidate must be `ELIGIBLE`, must meet the shift role's `min_age_years` against their `age_years_on_event`, must hold the role's `required_skill` in their `skill_tags` unless the role requires `NONE`, must satisfy the role's `required_training_module` with a `PASSED`, unexpired training record unless the module is `NONE` (which is always satisfied), and must hold no `APPROVED` or `CONFIRMED` signup overlapping the freed shift under the buffer semantics of §3.5. Candidates are ranked by fewest hours already worked at this event — the sum of `credited_hours` across that volunteer's hour logs in every status except `REJECTED` — and then by earliest volunteer `created_at`; the order is deterministic and total, and resource `id` values never participate. A volunteer whose only logs are `REJECTED` ranks with a zero-hour sum but remains eligible.

The top-ranked candidate receives a brand-new signup placed directly in `CONFIRMED` status — no approval or confirmation step — with `origin` set to `FLOAT_POOL_BACKFILL`, `replaces_signup_id` pointing at the freed `NO_SHOW` or `CANCELLED` signup it replaces (the field is null on all non-backfill signups), and `confirmed_at` stamped at creation. When the eligible pool is empty, the attempt raises no error; instead the shift's `understaffed_alert` flag is set to true, and it remains set until `confirmed_count` again reaches `required_headcount`, at which point the alert clears.

### 3.8. Hour Logs, Verification, and Fundraising Credit

Every completed shift stint produces one hour log, created at check-out in `PENDING_VERIFICATION` status with the `signup_id` it records and an `event_id` denormalized from that signup. The log carries an adjustable `break_minutes` input (zero or more, defaulting to zero) and three derived quantities. `raw_minutes` is the elapsed time from `checked_in_at` to `checked_out_at` minus `break_minutes`, floored at zero so a long break can never produce a negative duration. `claimed_hours` is `raw_minutes` divided by sixty, rounded half up to two decimal places. `credited_hours` is `raw_minutes` divided by fifteen, that quotient rounded half up to a whole number of quarter-hours, and the result multiplied by one quarter hour. The rounding order is pinned: quarter-hour rounding applies per individual log entry before any summation, and group or volunteer totals are sums of per-entry `credited_hours`. The opposite order — summing raw minutes first and rounding the total — is forbidden: two separate six-minute logs credit zero quarters each and contribute zero point zero zero hours in total, never a quarter-hour between them. While a log remains `PENDING_VERIFICATION`, a coordinator may adjust its `break_minutes`, and the adjustment recomputes `raw_minutes`, `claimed_hours`, and `credited_hours`; adjusting in any other status is rejected with `ERR_HOUR_LOG_INVALID_STATE`. The log's status vocabulary is `PENDING_VERIFICATION`, `VERIFIED`, `DISPUTED`, and terminal `REJECTED`.

Verification converts a log into credit. A coordinator may verify any log; a `Captain` may verify only logs belonging to their own shift — the shift behind the log's `signup_id` — with anyone else rejected as `ERR_NOT_RESOURCE_OWNER`. Verification is allowed from `PENDING_VERIFICATION` or `DISPUTED` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), moves the log to `VERIFIED`, and records who acted in `verified_by_role` as `CAPTAIN` or `COORDINATOR`. Disputing runs the other way, from `PENDING_VERIFICATION` or `VERIFIED` into `DISPUTED` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), and is open to the log's own volunteer (`X-User-ID` equal to the signup's `volunteer_id`), to the `GroupLeader` of that volunteer's fundraising group (`X-User-ID` equal to the group's `id`), or to a coordinator — anyone else draws `ERR_NOT_RESOURCE_OWNER`. A disputed log leaves the settled credit pool until it is re-verified, and a dispute followed by re-verification leaves the settled credit exactly as it stood. Rejection is coordinator-only, allowed only from `PENDING_VERIFICATION` (otherwise `ERR_HOUR_LOG_INVALID_STATE`), lands in terminal `REJECTED`, and excludes the log from both credit variants forever.

The fundraising credit summary of a group is a computed read, open to the `EventDirector` and to the `GroupLeader` of that group — whose `X-User-ID` must equal the group's `id`, otherwise `ERR_NOT_RESOURCE_OWNER`. Per log, the system derives two weighted figures: effective hours, the log's `credited_hours` multiplied by the `credit_weight` of the role catalog entry behind the log's signup's shift and rounded half up to two decimal places; and effective claimed hours, the same multiplication applied to `claimed_hours` with the same rounding. Two variants are then computed. The provisional variant pools the group's logs in `PENDING_VERIFICATION`, `VERIFIED`, or `DISPUTED` status: `provisional_effective_hours` is the sum of their effective claimed hours, and `provisional_credit_cents` prices that sum. The settled variant admits `VERIFIED` logs only: `settled_effective_hours` is the sum of their effective hours, and `settled_credit_cents` prices it. Pool membership is decided by log status alone: logs of volunteers whose group has since been `SUSPENDED` continue to accrue, because suspension blocks new affiliations rather than accrual on existing ones, while `REJECTED` logs fall outside both pools. With identical data the provisional figure is never smaller than the settled one — it counts a larger pool at unrounded claimed hours.

Pricing is marginal across three slices, each slice rounded half up to a whole cent before the slices are summed: the first one hundred hours earn five hundred cents per hour; hours beyond the first hundred, up to a cumulative five hundred, earn eight hundred cents per hour; and all hours beyond five hundred earn twelve hundred cents per hour. When an audit view needs to attribute specific hours to specific tiers, logs are allocated in order of their shift's `start_at`, ties broken by the hour log's `created_at`.

A sponsor match layers on top of the settled credit in a pinned four-step order that removes any circular reading. Step one takes `settled_credit_cents` as the base. Step two selects the match percentage from the base alone: twenty-five percent when the base reaches 250,000 cents, fifteen percent when it reaches 50,000 cents, and five percent otherwise; the tier is never re-evaluated against the final total. Step three sets `sponsor_match_cents` to the base multiplied by the selected percentage, rounded half up to a whole cent. Step four sets `total_settled_credit_cents` to the base plus the match. The summary response carries all six figures: `provisional_effective_hours`, `settled_effective_hours`, `provisional_credit_cents`, `settled_credit_cents`, `sponsor_match_cents`, and `total_settled_credit_cents`.

### 3.9. Recognition, Debriefs, Role Adjustments, and Closing the Event

The appreciation program scores each volunteer per event, and its summary read reports two point totals, a tier, and two tallies — `captain_shift_count` and `no_show_count`. Per signup, hour points are the relevant hours multiplied by ten: `credited_hours` from `VERIFIED` logs for the official figure, and `claimed_hours` from `PENDING_VERIFICATION` or `DISPUTED` logs for the projected figure. A captain signup — `is_captain` true on a signup that is not `CANCELLED` — adds twenty-five points; a `NO_SHOW` signup subtracts fifteen; and a returning volunteer with `is_returning` true adds fifty points once per event. Signups in `CANCELLED` status are excluded entirely, and `REJECTED` hour logs contribute nothing. The projected total, `projected_points`, sums hour points (claimed hours for unverified logs), bonuses, and penalties across all non-cancelled signups, plus the returning bonus; the official total, `official_points`, counts `VERIFIED` credited hours only under the same bonuses and penalties. The `recognition_tier` keys on the official total: `PLATINUM` at six hundred points or more, `GOLD` at three hundred or more, `SILVER` at one hundred fifty or more, `BRONZE` at fifty or more, and `NONE` below that. Points may go negative — there is no floor.

After the event moves from `COMPLETED` to `DEBRIEF_OPEN`, captains file post-event reports. A `Captain` creates a debrief for their own shift, supplying `event_id`, `shift_id`, `author_volunteer_id`, `headcount_actual` (zero or more), a `role_effectiveness_rating` from one to five, an optional `supply_shortage_flag` defaulting to false, and free-text `notes`. The `author_volunteer_id` must equal `X-User-ID`, and the author must hold the captain signup on that shift; otherwise the creation is rejected with `ERR_NOT_RESOURCE_OWNER`. The report starts in `DRAFT` status. The author then submits it — `DRAFT` to `SUBMITTED`, requiring the event to be `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`), the caller to be the author (`ERR_NOT_RESOURCE_OWNER`), and the report to be in `DRAFT` (`ERR_DEBRIEF_INVALID_STATE`). A coordinator acknowledges a submitted report — `SUBMITTED` to terminal `ACKNOWLEDGED`, otherwise `ERR_DEBRIEF_INVALID_STATE`.

Debriefs feed the following year's planning through role adjustments. While the event is `DEBRIEF_OPEN`, a coordinator proposes an adjustment naming `event_id`, the target `role_entry_id`, and a motivating `debrief_report_id` whose report is at least `SUBMITTED` — a still-`DRAFT` report cannot anchor an adjustment — plus any combination of the optional replacements `proposed_min_age_years`, `proposed_required_skill` (one of `NONE`, `MEDICAL`, `BIKE_MARSHAL`, `TIMING_TECH`, `COURSE_MARSHAL`), `proposed_credit_weight`, and `proposed_retire` (defaulting to false). The proposal starts `PROPOSED`; its statuses are `PROPOSED`, `APPROVED`, and terminal `REJECTED` or `APPLIED`. The `EventDirector` approves or rejects it — both only from `PROPOSED` (`ERR_ADJUSTMENT_INVALID_STATE`) and only while the event remains `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`) — and approval additionally requires the cited debrief to be `ACKNOWLEDGED` (`ERR_DEBRIEF_NOT_ACKNOWLEDGED`).

Application is a coordinator action on an `APPROVED` adjustment, again gated on the event being `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE`) and on the adjustment's state (`ERR_ADJUSTMENT_INVALID_STATE`). The request must carry `expected_role_version` matching the role catalog entry's current `version`, per §2.9; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the role before re-applying. When `proposed_retire` is true, the role must have zero non-terminal signups across its shifts (`ERR_ROLE_IN_USE`). Applying writes every provided `proposed_*` value onto the role catalog entry — a true `proposed_retire` moves the entry to `RETIRED` — increments the entry's `version` by one, stamps `applied_at`, and is strictly forward-looking: existing signups are not re-validated against the new requirements.

Before the books close, each shift must be reconciled. A coordinator reconciles an `IN_PROGRESS` shift once the event is `COMPLETED` or `DEBRIEF_OPEN` (`ERR_INVALID_EVENT_STATE` otherwise), and only while no signup on the shift remains in `CONFIRMED` or `CHECKED_IN` status — unresolved seats reject with `ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS`. Reconciliation lands the shift in terminal `RECONCILED`. Closing the event — `DEBRIEF_OPEN` to terminal `CLOSED` — then demands four conditions, each enforced as `ERR_EVENT_CLOSE_BLOCKED`: zero hour logs of the event in `PENDING_VERIFICATION` or `DISPUTED` status; zero debrief reports still `SUBMITTED`; zero role adjustments in `PROPOSED` or `APPROVED` status; and every shift of the event in `RECONCILED` or `CANCELLED` status. Once the event closes, settled fundraising credit and recognition tiers become final, and no further hour-log or debrief mutations are accepted.

Two system duties remain, both driven by the `EventDirector` through the ops-run epoch sweep of a single event, which reports back `expired_training_record_ids`, `auto_locked`, and `timed_out_signup_ids`. First, the sweep expires credentials: every `PASSED` training record of the event whose `valid_until` has passed moves to `EXPIRED`, firing the cancellation cascade of §3.4. Second, if the event is still `PUBLISHED` and the clock has reached `signup_closes_at`, the sweep auto-locks it exactly as a manual lock would, cascading the event's `OPEN` and `FULL` shifts to `LOCKED`. Third, the sweep cancels every `APPROVED` signup of the event whose `confirm_by_at` deadline has passed, each freed seat running the seat-open handling of §3.7.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that read or modify an existing resource — including every state transition and computed read — return `200 OK`. Request bodies and side effects are intentionally not repeated here; §3 carries the workflow each endpoint participates in. In the role column, "Any" means the endpoint is open to all six declared roles, including `Anonymous`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/volunteer-ops/_clock/set_current_utc` | Set the server logical clock | EventDirector |
| POST | `/volunteer-ops/events` | Create an event in `DRAFT` | EventDirector |
| GET | `/volunteer-ops/events` | List events | Any |
| GET | `/volunteer-ops/events/{eventId}` | Get one event | Any |
| PATCH | `/volunteer-ops/events/{eventId}` | Update event configuration while `DRAFT` (OCC) | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/publish` | Publish the event after the readiness check | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/lock-signups` | Lock the signup window, locking open shifts | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/start-race-day` | Move the event to `RACE_DAY`, shifts to `IN_PROGRESS` | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/complete` | Complete the event once the course is clear | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/open-debrief` | Open the debrief window | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/close` | Close the event after all resolution gates pass | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/cancel` | Cancel the event with the full downward cascade | EventDirector |
| POST | `/volunteer-ops/events/{eventId}/run-epoch-sweep` | Run the ops checkpoint: training expiry, auto-lock, confirm timeouts | EventDirector |
| POST | `/volunteer-ops/course-segments` | Create a course segment | VolunteerCoordinator |
| GET | `/volunteer-ops/course-segments` | List course segments | Any |
| GET | `/volunteer-ops/course-segments/{segmentId}` | Get one course segment | Any |
| POST | `/volunteer-ops/role-catalog-entries` | Create a role catalog entry | VolunteerCoordinator |
| GET | `/volunteer-ops/role-catalog-entries` | List role catalog entries | Any |
| GET | `/volunteer-ops/role-catalog-entries/{roleEntryId}` | Get one role catalog entry | Any |
| POST | `/volunteer-ops/role-catalog-entries/{roleEntryId}/suspend` | Suspend an active role entry | VolunteerCoordinator |
| POST | `/volunteer-ops/role-catalog-entries/{roleEntryId}/reactivate` | Reactivate a suspended role entry | VolunteerCoordinator |
| POST | `/volunteer-ops/role-catalog-entries/{roleEntryId}/retire` | Retire a role entry with no non-terminal signups | VolunteerCoordinator |
| POST | `/volunteer-ops/shifts` | Create a shift staffing one role on one segment | VolunteerCoordinator |
| GET | `/volunteer-ops/shifts` | List shifts | Any |
| GET | `/volunteer-ops/shifts/{shiftId}` | Get one shift, including computed counters | Any |
| POST | `/volunteer-ops/shifts/{shiftId}/cancel` | Decommission an `OPEN` or `FULL` shift before lock | VolunteerCoordinator |
| POST | `/volunteer-ops/shifts/{shiftId}/reconcile` | Reconcile an `IN_PROGRESS` shift after the event | VolunteerCoordinator |
| POST | `/volunteer-ops/fundraising-groups` | Create a fundraising group | EventDirector |
| GET | `/volunteer-ops/fundraising-groups` | List fundraising groups | Any |
| GET | `/volunteer-ops/fundraising-groups/{groupId}` | Get one fundraising group | Any |
| GET | `/volunteer-ops/fundraising-groups/{groupId}/credit-summary` | Computed provisional/settled credit and sponsor match | GroupLeader, EventDirector |
| POST | `/volunteer-ops/fundraising-groups/{groupId}/suspend` | Suspend a group, blocking new affiliations | EventDirector |
| POST | `/volunteer-ops/fundraising-groups/{groupId}/reinstate` | Reinstate a suspended group | EventDirector |
| POST | `/volunteer-ops/volunteers` | Register a volunteer for an event | Anonymous, VolunteerCoordinator |
| GET | `/volunteer-ops/volunteers` | List volunteers | Any |
| GET | `/volunteer-ops/volunteers/{volunteerId}` | Get one volunteer | Any |
| PATCH | `/volunteer-ops/volunteers/{volunteerId}` | Update mutable profile fields (OCC) | Volunteer, VolunteerCoordinator |
| POST | `/volunteer-ops/volunteers/{volunteerId}/screen` | Screen a `REGISTERED` volunteer into `ELIGIBLE` | VolunteerCoordinator |
| POST | `/volunteer-ops/volunteers/{volunteerId}/reinstate` | Reinstate a suspended volunteer, resetting strikes | VolunteerCoordinator |
| GET | `/volunteer-ops/volunteers/{volunteerId}/recognition-summary` | Computed recognition points and tier | Any |
| POST | `/volunteer-ops/training-records` | Enroll a volunteer in a training module | VolunteerCoordinator |
| GET | `/volunteer-ops/training-records` | List training records | Any |
| GET | `/volunteer-ops/training-records/{trainingRecordId}` | Get one training record | Any |
| POST | `/volunteer-ops/training-records/{trainingRecordId}/pass` | Mark an enrolled record passed, starting its validity window | VolunteerCoordinator |
| POST | `/volunteer-ops/training-records/{trainingRecordId}/fail` | Mark an enrolled record failed | VolunteerCoordinator |
| POST | `/volunteer-ops/training-records/{trainingRecordId}/re-enroll` | Re-enroll a failed or expired record | VolunteerCoordinator |
| POST | `/volunteer-ops/signups` | Create a signup, routing to `REQUESTED` or `WAITLISTED` | Volunteer, VolunteerCoordinator |
| GET | `/volunteer-ops/signups` | List signups | Any |
| GET | `/volunteer-ops/signups/{signupId}` | Get one signup | Any |
| POST | `/volunteer-ops/signups/{signupId}/approve` | Approve a `REQUESTED` signup after the re-run gauntlet | VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/confirm` | Confirm an approved signup, volunteer self only | Volunteer |
| POST | `/volunteer-ops/signups/{signupId}/cancel` | Cancel a non-terminal signup, freeing its seat | Volunteer, VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/check-in` | Check in a confirmed signup on race day, issuing its credential | VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/check-out` | Check out a checked-in signup, spawning its hour log | VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/mark-no-show` | Mark a confirmed signup `NO_SHOW`, firing the strike cascade | Captain, VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/assign-captain` | Designate the signup as its shift's captain | VolunteerCoordinator |
| POST | `/volunteer-ops/signups/{signupId}/remove-captain` | Clear the captain flag on a signup | VolunteerCoordinator |
| POST | `/volunteer-ops/supply-inventories` | Create a supply inventory item | VolunteerCoordinator |
| GET | `/volunteer-ops/supply-inventories` | List supply inventories | Any |
| GET | `/volunteer-ops/supply-inventories/{inventoryId}` | Get one inventory item, including issued count | Any |
| POST | `/volunteer-ops/distribution-records` | Issue a credential or supply item to a checked-in signup | VolunteerCoordinator |
| GET | `/volunteer-ops/distribution-records` | List distribution records | Any |
| GET | `/volunteer-ops/distribution-records/{distributionId}` | Get one distribution record | Any |
| POST | `/volunteer-ops/distribution-records/{distributionId}/return` | Return an issued supply item to stock | VolunteerCoordinator |
| POST | `/volunteer-ops/distribution-records/{distributionId}/revoke` | Revoke an issued credential or supply item | VolunteerCoordinator |
| GET | `/volunteer-ops/hour-logs` | List hour logs | Any |
| GET | `/volunteer-ops/hour-logs/{hourLogId}` | Get one hour log | Any |
| POST | `/volunteer-ops/hour-logs/{hourLogId}/verify` | Verify a pending or disputed hour log | Captain, VolunteerCoordinator |
| POST | `/volunteer-ops/hour-logs/{hourLogId}/dispute` | Dispute a pending or verified hour log | Volunteer, GroupLeader, VolunteerCoordinator |
| POST | `/volunteer-ops/hour-logs/{hourLogId}/reject` | Reject a pending hour log, excluding it from credit | VolunteerCoordinator |
| POST | `/volunteer-ops/hour-logs/{hourLogId}/adjust` | Adjust break minutes on a pending log, recomputing hours | VolunteerCoordinator |
| POST | `/volunteer-ops/debrief-reports` | Create a draft debrief for a shift, captain-authored | Captain |
| GET | `/volunteer-ops/debrief-reports` | List debrief reports | Any |
| GET | `/volunteer-ops/debrief-reports/{debriefId}` | Get one debrief report | Any |
| POST | `/volunteer-ops/debrief-reports/{debriefId}/submit` | Submit a draft debrief during the debrief window | Captain |
| POST | `/volunteer-ops/debrief-reports/{debriefId}/acknowledge` | Acknowledge a submitted debrief | VolunteerCoordinator |
| POST | `/volunteer-ops/role-adjustments` | Propose a role adjustment citing a debrief | VolunteerCoordinator |
| GET | `/volunteer-ops/role-adjustments` | List role adjustments | Any |
| GET | `/volunteer-ops/role-adjustments/{adjustmentId}` | Get one role adjustment | Any |
| POST | `/volunteer-ops/role-adjustments/{adjustmentId}/approve` | Approve a proposed adjustment once its debrief is acknowledged | EventDirector |
| POST | `/volunteer-ops/role-adjustments/{adjustmentId}/reject` | Reject a proposed adjustment | EventDirector |
| POST | `/volunteer-ops/role-adjustments/{adjustmentId}/apply` | Apply an approved adjustment to the role (OCC) | VolunteerCoordinator |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ROLE_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_VOLUNTEER_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNUP_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_NOT_FOUND` | 404 Not Found |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 Not Found |
| `ERR_HOUR_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_DEBRIEF_NOT_FOUND` | 404 Not Found |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_EVENT_STATE` | 409 Conflict |
| `ERR_EVENT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_EVENT_READINESS_INCOMPLETE` | 409 Conflict |
| `ERR_EVENT_NOT_YET_STARTED` | 409 Conflict |
| `ERR_EVENT_NOT_YET_ENDED` | 409 Conflict |
| `ERR_SIGNUPS_STILL_ON_COURSE` | 409 Conflict |
| `ERR_EVENT_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_CAPACITY_REACHED` | 409 Conflict |
| `ERR_SHIFT_HAS_UNRESOLVED_SIGNUPS` | 409 Conflict |
| `ERR_SHIFT_TIME_OVERLAP` | 409 Conflict |
| `ERR_SEGMENT_MILE_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_SIGNUP` | 409 Conflict |
| `ERR_DUPLICATE_TRAINING_RECORD` | 409 Conflict |
| `ERR_CAPTAIN_SLOT_TAKEN` | 409 Conflict |
| `ERR_CREDENTIAL_ALREADY_ISSUED` | 409 Conflict |
| `ERR_SIGNUP_NOT_APPROVABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_CHECKINABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_CHECKED_OUTABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_NO_SHOWABLE` | 409 Conflict |
| `ERR_SIGNUP_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_SCREENABLE` | 409 Conflict |
| `ERR_VOLUNTEER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_TRAINING_INVALID_STATE` | 409 Conflict |
| `ERR_ROLE_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_ROLE_ENTRY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROLE_IN_USE` | 409 Conflict |
| `ERR_GROUP_INVALID_STATE` | 409 Conflict |
| `ERR_GROUP_SUSPENDED` | 409 Conflict |
| `ERR_HOUR_LOG_INVALID_STATE` | 409 Conflict |
| `ERR_DISTRIBUTION_INVALID_STATE` | 409 Conflict |
| `ERR_DEBRIEF_INVALID_STATE` | 409 Conflict |
| `ERR_DEBRIEF_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_ADJUSTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_MIN_AGE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_REQUIRED_SKILL_MISSING` | 422 Unprocessable Entity |
| `ERR_TRAINING_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_SIGNUP_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_EARLY_ACCESS_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_CHECKIN_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CONFIRM_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_GRACE_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_OUT_OF_STOCK` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
