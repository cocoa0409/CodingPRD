# Crossfit Box API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Crossfit Box API, a back-office and member-facing platform for a functional-fitness gym (a "box"). The platform manages the full commercial and operational life of the box: the catalogue of membership plans members buy into, the individual memberships those members hold, the daily workout-of-the-day (WOD) class sessions coaches run, and the seat reservations that fill those sessions. Because a class has a finite number of seats, the central engineering challenge is allocation under contention — seats are reserved, committed, and released as members come and go, and an ordered waitlist promotes the next athlete whenever a committed seat frees up.

Layered on top of seat allocation are the box's commercial rules. Memberships follow a billing lifecycle from pending payment through active use, optional freezes, and eventual cancellation, with early-termination fees keyed to contract commitments and a periodic billing batch that settles the books. Athletes accrue no-show strikes that can suspend their booking privileges, punch-pass holders draw down a finite punch balance, and visiting drop-in athletes pay per session rather than holding a membership. The platform also tracks athletic performance: benchmark and personal-record (PR) results that certified coaches verify and that feed per-track leaderboards, plus competition teams whose rosters form, lock, and disband. Throughout, time matters — reservation cut-offs, late-cancel windows, freeze durations, and coach scheduling buffers are all evaluated against a controllable server clock so that time-gated behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API carries its caller identity in two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's operational capacity. The system recognizes exactly four roles, spelled precisely as `BoxManager`, `Coach`, `Member`, and `Anonymous`. A request that omits the required headers or presents them malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the sole exception is member self-registration, which is reachable without an authenticated identity. A well-formed but insufficiently privileged caller — one whose role is not permitted to perform the requested operation — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles map to system identity in two distinct ways. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's member foreign key to `X-User-ID`. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; ownership checks on any resource that references a `Coach` compare the resource's coach foreign key to `X-User-ID`. Both `BoxManager` and `Anonymous` are opaque roles: when `X-User-Role` is `BoxManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server may record it but does not compare it to any entity's `id`; likewise, when `X-User-Role` is `Anonymous`, `X-User-ID` (when present at all) is an opaque visitor identifier not tied to any persisted entity and is never compared to an entity's `id`.

Ownership is enforced beyond mere role membership. When an entity-backed `Member` attempts to act on a `Membership`, `Reservation`, `BenchmarkResult`, or competition team resource that is not their own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies to member-owned mutation endpoints and is distinct from the coarser role check above.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response surfaces four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — `MembershipPlan`, `Member`, `Membership`, `ProgramTrack`, `Coach`, `ClassSession`, `Reservation`, `BenchmarkResult`, `CompetitionTeam`, and `TeamMember` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp that is refreshed on every mutation of the resource. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation; it is the basis for the optimistic-concurrency mechanism described in §2.6. All ten entities in this system carry the full complement of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Denormalized Counters

Several resources hold denormalized counters that the system keeps reconciled with the underlying rows they summarize. A `ClassSession` exposes `seats_reserved`, the live count of its reservations in `RESERVED` status, and `waitlist_count`, the live count of its reservations in `WAITLISTED` status; both are recomputed on every reservation create, cancel, no-show, completion, and waitlist promotion that touches the session. A `CompetitionTeam` exposes `roster_size`, the count of its team-member rows in `ACCEPTED` status (the captain included). When an operation causes a counter to change, that mutation is applied to the owning resource atomically within the same request, refreshing its `updated_at` and incrementing its `version`. Cascades that span entities — a freeze or cancellation that releases seats, a session cancellation that releases an entire roster of reservations, a team lock that expires invitations — all complete inside the single triggering request; the system never leaves a counter drifted from the rows it counts.

### 2.6. Optimistic Concurrency Control on Seat Reservation

Reserving a seat is the one operation in this system guarded by optimistic concurrency control, because seat availability on a `ClassSession` is contended. A reservation-create request must carry `expected_session_version`, a non-optional field holding the `version` of the target `ClassSession` that the client last observed. The server compares this value to the session's current `version`. If another writer has advanced the session's version since the client read it — for example, because a reservation that landed on the last open seat legitimately superseded the client's earlier view of seat availability by bumping the session version — the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412), and the client must re-read the session's current seat state before retrying. No other endpoint takes a version field; only reservation creation participates in this stale-version check.

### 2.7. Time, the Logical Clock, and Temporal Windows

All time-based rules evaluate against a server-controlled logical clock rather than wall-clock time. The clock defaults to `2026-01-01T00:00:00Z` at startup and never falls back to wall-clock time before it has been explicitly set. An administrative test-driving capability sets the clock to an arbitrary UTC instant supplied as `to_iso8601`. Reservation cut-offs, late-cancel windows, freeze-day accrual, session-completion eligibility, and contract-commitment comparisons all read "now" from this clock. The system stores all timestamps — `starts_at`, `recorded_at`, `contract_start_date`, `commitment_end_date`, `freeze_started_at` — in UTC.

### 2.8. Monetary and Counting Precision

All monetary amounts in the system are integer cents and are never rounded — the relevant fees are flat values (`monthly_fee_cents`, `early_termination_fee_cents`, `drop_in_fee_cents`) and the computed totals are exact integer sums of those values. Cancellation fees (`cancellation_fee_cents`), per-reservation drop-in charges (`drop_in_fee_charged_cents`), and the cycle-close billing total are all integer-cent quantities carried with no fractional component. Punch counts (`punch_count`, `punches_remaining`) and strike counts (`no_show_strikes`) are non-negative integers. Benchmark values (`value`) are compared as plain numbers, with strict comparisons only — equal values never count as a record (see §3.6).

### 2.9. Left-to-Right Existence Validation

Endpoints reference resources both through path identifiers and through foreign-key fields in the request body. Before any business rule runs, the system confirms that every referenced resource exists — members, plans, memberships, sessions, reservations, tracks, coaches, benchmark results, teams, and team-member slots — validating them left to right in the order they appear, and rejecting the first missing reference with `ERR_NOT_FOUND` (HTTP 404).

### 2.10. Validation Ordering

When several checks guard a single endpoint, they run in a fixed priority order so that the rejection a caller receives is deterministic. Authentication is evaluated first: a missing or malformed identity yields `ERR_UNAUTHENTICATED`. Role authorization is evaluated next, yielding `ERR_FORBIDDEN_ROLE` for a disallowed role. Resource ownership follows, yielding `ERR_NOT_RESOURCE_OWNER` when an entity-backed `Member` reaches for something they do not own. Existence of all referenced resources is checked next, yielding `ERR_NOT_FOUND`. Only then are request-body shape and type checks applied, yielding `ERR_INVALID_REQUEST` for missing required fields, wrong types, out-of-range numbers, or out-of-set enum values; plan-shape and reservation-shape consistency, yielding `ERR_PLAN_SHAPE_INVALID`, is evaluated within this same body-validation stage. State-machine legality is checked after structural validity, yielding `ERR_INVALID_STATE` when the target is not in a state from which the requested transition is defined. Domain-specific business rules — membership ownership of a reservation, reservation suspension, foundations prerequisites, reservation windows, drop-in eligibility, duplicate and time-conflict checks, coach double-booking, punch availability, roster capacity, coach certification — are evaluated after that. The optimistic-concurrency stale-version check on reservation creation is evaluated last among the reservation checks. The per-endpoint orderings that matter most are spelled out in the workflow narratives of §3.

## 3. Business Logic & Workflows

### 3.1. The Plan Catalogue and Member Registry

The commercial catalogue begins with the **membership plan**, a `BoxManager`-authored template that members buy into. A plan carries a display `name` (for example, "Unlimited Monthly") and a `plan_type` that is one of `UNLIMITED` or `PUNCH`, fixing its usage model. Its `monthly_fee_cents` is the recurring monthly charge in cents, levied at activation and on each subsequent billing cycle, and must be zero or greater. The shape of a plan depends on its type: a `PUNCH` plan must supply `punch_count`, the number of class punches granted on activation, as an integer of at least 1, while an `UNLIMITED` plan must leave `punch_count` null. A request that violates this pairing — a `PUNCH` plan omitting `punch_count` or an `UNLIMITED` plan supplying it — is rejected with `ERR_PLAN_SHAPE_INVALID`. A plan also declares its contract terms: `commitment_months` is the contract commitment length in months (defaulting to 0, meaning no commitment, and never negative), and `early_termination_fee_cents` is the flat fee charged for cancelling while still inside that commitment window (defaulting to 0, never negative). The `requires_foundations` flag (defaulting to true) governs whether a member on the plan must clear their on-ramp before reserving regular-track classes. Every plan is born with `active` set to true; archiving a plan flips `active` to false so it can no longer back new memberships, and bumps the plan's `version`.

A **member** is the athlete record. Registration — the one anonymous-reachable write — supplies a login `email`, a `full_name`, and optionally `home_box_member`. The `email` is stored lowercased and must be unique across all members on a case-insensitive basis. The `home_box_member` flag (defaulting to true) distinguishes home-box athletes, who hold memberships, from visiting and drop-in athletes, who book only via paid drop-in passes. Every new member starts with `no_show_strikes` at 0 and is not reservation-suspended. The `no_show_strikes` field is a rolling count of missed reserved sessions; it climbs by one each time a coach marks the member a no-show and is reset to 0 only by a `BoxManager` strike-clear action. The computed `reservation_suspended` flag is true exactly when `no_show_strikes` is at least 3 — the suspension threshold — and false otherwise; while it is true, the member may create no new reservations. A `BoxManager` strike-clear sets `no_show_strikes` back to 0, recomputes `reservation_suspended` to false, and increments the member's `version`, lifting any suspension.

### 3.2. Memberships: Activation, Freezing, and the Contract Clock

A **membership** binds a member to a plan and is created — by a `BoxManager` or by a `Member` for themselves — with only `member_id` and `plan_id` supplied. It is born in `PENDING_PAYMENT` status with `punches_remaining` null and its contract dates unset; `foundations_completed` starts false. The `status` ranges over `PENDING_PAYMENT`, `ACTIVE`, `FROZEN`, `CANCEL_PENDING`, and `CANCELLED`.

A `BoxManager` confirms initial payment to activate a membership; this is permitted only when the membership is in `PENDING_PAYMENT`, otherwise `ERR_INVALID_STATE` is returned. Activation moves the membership from `PENDING_PAYMENT` to `ACTIVE`, sets `contract_start_date` to the current clock time, and sets `commitment_end_date` to the contract start plus the plan's `commitment_months` months. For a `PUNCH` plan, activation sets `punches_remaining` to the plan's `punch_count`; for an `UNLIMITED` plan, `punches_remaining` stays null. The membership's `version` increments.

A `Member` may freeze their own membership, but only while it is `ACTIVE`; a freeze is always permitted in the `ACTIVE` state regardless of any reservation suspension, and an attempt from any other status yields `ERR_INVALID_STATE`. Freezing moves the membership from `ACTIVE` to `FROZEN`, records `freeze_started_at` at the current clock time, and increments `version`. Critically, a freeze cascades into reservations: every reservation this membership holds on a future, still-`SCHEDULED` session in `RESERVED` status is transitioned from `RESERVED` to `CANCELLED`, and each such cancellation decrements that session's `seats_reserved` and promotes the head of that session's waitlist (the cancel-and-promote mechanics are detailed in §3.4).

Unfreezing reverses the freeze and is permitted only from `FROZEN` (otherwise `ERR_INVALID_STATE`). On unfreeze, the membership returns from `FROZEN` to `ACTIVE`. The system computes the elapsed freeze duration as the difference between the current clock time and `freeze_started_at`, expressed in days and rounded up to the next whole day; this whole-day figure is added to `total_frozen_days`, and `commitment_end_date` is pushed forward by that same number of days so frozen time does not count against the contract. The `freeze_started_at` field is then cleared to null and `version` increments. `total_frozen_days` accumulates across every freeze episode.

### 3.3. Membership Cancellation and the Billing Cycle Close

A `Member` may request cancellation of a membership that is either `ACTIVE` or `FROZEN`; from any other status the request is rejected with `ERR_INVALID_STATE`. Cancellation does not delete the membership immediately — it moves the membership into `CANCEL_PENDING`, where it remains until the billing batch finalizes it at the close of the cycle. At cancellation-request time the system computes and stores `cancellation_fee_cents`. The fee turns on whether the contract commitment is still in force, evaluated against `commitment_end_date`, which already includes any frozen-day extensions applied at unfreeze: if the plan's `commitment_months` is 0 the fee is 0; otherwise, if the current clock time is strictly before `commitment_end_date` the membership is still inside its commitment window and the fee equals the plan's `early_termination_fee_cents`; and if the current clock time is at or after `commitment_end_date` the commitment is satisfied and the fee is 0. The fee is a flat integer-cent amount with no rounding.

When the cancellation request is made on an `ACTIVE` membership, it also cascades into reservations exactly as a freeze does: every future `RESERVED` reservation of the membership is transitioned from `RESERVED` to `CANCELLED`, decrementing each affected session's `seats_reserved` and promoting that session's waitlist head. When the cancellation request is made on a `FROZEN` membership, `freeze_started_at` is cleared to null and no reservation cascade fires — a frozen membership has no future `RESERVED` reservations, because the freeze that put it into `FROZEN` already cancelled them. In both cases the membership transitions to `CANCEL_PENDING` and its `version` increments.

The cancellation is finalized by the **billing cycle-close batch**, a `BoxManager` capability. The batch finalizes every `CANCEL_PENDING` membership to `CANCELLED` and computes the total charged for the cycle. It processes memberships in two passes, each ordered by `created_at` ascending with no other tiebreak. In the first pass, every membership currently in `CANCEL_PENDING` is taken in `created_at` order; its stored `cancellation_fee_cents` is added to the running cycle total, and it transitions from `CANCEL_PENDING` to `CANCELLED`, with `version` incremented (a `PUNCH` plan's `punches_remaining` is set to 0 at this finalization). In the second pass, every membership currently in `ACTIVE` is taken in `created_at` order and its plan's `monthly_fee_cents` is added to the running total; these memberships stay `ACTIVE`. Memberships in `FROZEN` are charged no monthly fee for the cycle and are skipped by both passes. The batch returns the resulting integer-cent total as `total_charged_cents`, together with the list of finalized membership identifiers in `finalized_membership_ids`. A `CANCEL_PENDING` membership may be finalized only from that status.

The on-ramp prerequisite is signed off through a separate coach capability: a `Coach` completes a membership's foundations by referencing its `membership_id`, which sets the membership's `foundations_completed` to true and increments its `version`.

### 3.4. Class Sessions, Reservations, and the Waitlist

A **program track** organizes the box's offerings. A `BoxManager` creates one by supplying a `name`, a `track_type` (one of `FOUNDATIONS`, `REGULAR`, or `COMPETITION`, which fixes the track's prerequisite and eligibility semantics), and the `head_coach_id` of the coach who owns the track and may create its sessions. Track type drives two downstream rules described below: foundations is required on `REGULAR` tracks, and drop-in athletes are barred from `COMPETITION` tracks.

A **class session** is a single scheduled WOD. A `BoxManager` or `Coach` schedules one by supplying the `track_id` of the program track it belongs to, the `coach_id` of the leading coach, its `starts_at` UTC start time, its `duration_minutes` (at least 1), its `capacity` of committed seats (at least 1), and optionally a `drop_in_fee_cents` per-seat charge for visiting athletes (defaulting to 0, never negative). A new session is born `SCHEDULED` with `seats_reserved` and `waitlist_count` both 0. The `status` ranges over `SCHEDULED`, `CANCELLED`, and `COMPLETED`. A coach may not be double-booked: when scheduling a session, the system treats each of that coach's `SCHEDULED` sessions as occupying a busy interval that runs from its `starts_at` to its `starts_at` plus `duration_minutes` plus a 15-minute trailing turnaround buffer, and the new session's busy interval (computed the same way) must not overlap any of them — intervals that merely touch at their endpoints are allowed, but any genuine overlap is rejected with `ERR_COACH_DOUBLE_BOOKED`. This buffer-inclusive geometry is deliberately wider than the member time-conflict rule described below, which uses the bare class window with no buffer.

A **reservation** holds one athlete's seat on one session. Booking supplies the `session_id`, the `member_id` of the booking athlete, the `reservation_kind` (one of `MEMBERSHIP` or `DROP_IN`), the `expected_session_version` discussed in §2.6, and — for a `MEMBERSHIP` reservation only — the `membership_id` of the membership consuming the seat. A `DROP_IN` reservation must omit `membership_id`, and a `MEMBERSHIP` reservation must supply it; violating this pairing is rejected with `ERR_PLAN_SHAPE_INVALID`. A reservation's `status` ranges over `RESERVED`, `WAITLISTED`, `CANCELLED`, `NO_SHOW`, and `ATTENDED`, and it tracks `waitlist_position`, `drop_in_fee_charged_cents`, and `punch_consumed`.

Several conditions are checked before a seat is granted, and a `Member` who is reservation-suspended is turned away outright. The order in which these reservation checks resolve is fixed. After the resource-existence check, the membership-ownership rule fires: for a `MEMBERSHIP` reservation, the supplied `membership_id` must belong to a membership whose `member_id` equals the reserving `member_id`, or the request is rejected with `ERR_MEMBERSHIP_NOT_OWNED`. Next, the booking member must not be reservation-suspended — a member whose `no_show_strikes` is at least 3 is blocked with `ERR_RESERVATION_SUSPENDED`. Next comes the foundations prerequisite: when the session's track is of type `REGULAR` and the consuming membership's plan has `requires_foundations` set, the membership's `foundations_completed` must be true, or the booking is rejected with `ERR_FOUNDATIONS_NOT_COMPLETED`. Next the reservation window is enforced: the session must be `SCHEDULED` and the current clock time must be at or before the session's `starts_at` minus 60 minutes — the cut-off is 60 minutes before the session begins, so a request exactly at `starts_at` minus 60 minutes is still open while any later moment is closed — and a violation yields `ERR_RESERVATION_WINDOW_CLOSED`. Next, a visiting or drop-in athlete — a member with `home_box_member` false booking a `DROP_IN` seat — may book only sessions whose track is not of type `COMPETITION`; an attempt on a competition-track session is rejected with `ERR_DROP_IN_NOT_ALLOWED`. Next, a member may hold at most one non-terminal (`RESERVED` or `WAITLISTED`) reservation on a given session; a second is rejected with `ERR_DUPLICATE_RESERVATION`. Next, the new reservation must not overlap in time with another non-terminal reservation the same member already holds: treating each reservation's session as occupying the half-open interval from its `starts_at` to its `starts_at` plus duration, these intervals must be disjoint, with intervals that merely touch at their endpoints allowed, and a genuine overlap yields `ERR_SESSION_TIME_CONFLICT`. For a `PUNCH`-plan `MEMBERSHIP` reservation, the consuming membership must have `punches_remaining` of at least 1 at commit time (that is, when the seat is actually granted as `RESERVED`, not when it is merely waitlisted), or the booking is rejected with `ERR_NO_PUNCHES_REMAINING`. Finally, the optimistic-concurrency check described in §2.6 compares `expected_session_version` against the session's current `version` and rejects a mismatch with `ERR_STALE_SESSION_VERSION`.

Whether a booking becomes a held seat or a waitlist entry is decided at commit time by current occupancy. If the session is full — its `seats_reserved` equals its `capacity` — and the session is `SCHEDULED`, the reservation is created directly into `WAITLISTED` rather than `RESERVED`: it is assigned a `waitlist_position` equal to the session's current `waitlist_count` plus one, the session's `waitlist_count` increments, and crucially no punch is consumed and no drop-in fee is charged while waitlisted. Otherwise the reservation is created `RESERVED`: the session's `seats_reserved` increments, and for a `PUNCH`-plan `MEMBERSHIP` reservation the membership's `punches_remaining` is decremented by one and `punch_consumed` is set true, while for a `DROP_IN` reservation the session's `drop_in_fee_cents` is charged and recorded on the reservation as `drop_in_fee_charged_cents`. Every successful reservation create increments the session's `version`.

A waitlisted reservation is promoted automatically whenever a `RESERVED` seat on its session is freed. The candidate for promotion is the `WAITLISTED` reservation with the lowest `waitlist_position` (ties broken by earliest `created_at`), and promotion proceeds only while the session's `seats_reserved` is below `capacity` after the freeing event. Promotion sets that reservation's `status` to `RESERVED` and clears its `waitlist_position` to null, increments the session's `seats_reserved` by one and decrements its `waitlist_count` by one, and applies the seat cost that was deferred at waitlist time: a `PUNCH`-plan `MEMBERSHIP` reservation has its membership's `punches_remaining` decremented by one and `punch_consumed` set true, and a `DROP_IN` reservation is charged the session's `drop_in_fee_cents`, recorded as `drop_in_fee_charged_cents`. The remaining waitlisted reservations are renumbered so their `waitlist_position` values stay contiguous from 1. This promotion is the closing step of the freeze-and-cancel cascade: a membership freeze or cancel cancels a reservation, which frees a seat, which promotes the waitlist head.

### 3.5. Cancelling Reservations, Marking Attendance, and Cancelling Sessions

A `Member` may cancel their own reservation while the session is still `SCHEDULED`. Cancelling a `RESERVED` reservation transitions it from `RESERVED` to `CANCELLED`, decrements the session's `seats_reserved` by one, and — if any waitlisted reservations remain — promotes the head of the session's waitlist as described in §3.4. Whether the seat cost is returned depends on the late-cancel window: the system measures the hours before start as the gap between the session's `starts_at` and the current clock time. The late-cancel window is 12 hours. If that gap is strictly less than 12 hours the cancel is late and the athlete forfeits — the punch stays consumed and the drop-in fee is not refunded. If the gap is at least 12 hours the cancel is timely — the punch is restored (the membership's `punches_remaining` is increased by one when `punch_consumed` was true) and the drop-in fee is fully refunded (the recorded `drop_in_fee_charged_cents` is returned). The boundary is inclusive on the timely side: a cancel exactly 12 hours before start is treated as timely and earns the refund. Cancelling a reservation that is merely `WAITLISTED` transitions it from `WAITLISTED` to `CANCELLED`, decrements the session's `waitlist_count` by one, and renumbers the remaining waitlisted reservations contiguous from 1; because no seat was held, there is no punch or fee adjustment and no promotion. Cancellation is permitted only while the reservation is `RESERVED` or `WAITLISTED` and the session is `SCHEDULED`; otherwise `ERR_INVALID_STATE` applies.

A `Coach` (or a `BoxManager`) completes a session once the current clock time is at or after the session's `starts_at` and the session is `SCHEDULED`; an attempt before the start time or from a non-`SCHEDULED` session yields `ERR_INVALID_STATE`. Completion supplies an `attendance` map marking each attendee. The session moves from `SCHEDULED` to `COMPLETED` and its `version` increments. For each still-`RESERVED` reservation, the attendance map decides its fate: a reservation marked attended transitions from `RESERVED` to `ATTENDED` with no strike change, while a reservation marked a no-show — and any still-`RESERVED` reservation not explicitly marked, which defaults to a no-show — transitions from `RESERVED` to `NO_SHOW`, increments that member's `no_show_strikes` by one, and recomputes that member's `reservation_suspended` to reflect whether `no_show_strikes` has reached 3. In both attendance outcomes the punch stays consumed and any drop-in fee stays charged; no-shows are never refunded. Every `WAITLISTED` reservation on the session is transitioned from `WAITLISTED` to `CANCELLED`, since the class has run.

A `Coach` (or a `BoxManager`) may also cancel a scheduled session outright, permitted only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`). A box-initiated session cancellation moves the session from `SCHEDULED` to `CANCELLED` and always refunds, regardless of the late-cancel window: every `RESERVED` reservation on the session is transitioned from `RESERVED` to `CANCELLED` with full punch-restore and drop-in-fee refund, and every `WAITLISTED` reservation is transitioned from `WAITLISTED` to `CANCELLED`. The session's `seats_reserved` and `waitlist_count` are both set to 0 and its `version` increments.

### 3.6. Benchmarks, Verification, Personal Records, and Leaderboards

A `Member` records a **benchmark result** for an athlete by supplying the `member_id`, the `benchmark_name` (one of `FRAN`, `GRACE`, `MURPH`, `BACK_SQUAT_1RM`, or `DEADLIFT_1RM`), the `metric_kind` (one of `TIME_SECONDS` or `LOAD_KG`, fixing the comparison direction), the `value` (interpreted as seconds for `TIME_SECONDS` benchmarks and kilograms for `LOAD_KG` benchmarks, and required to be strictly greater than 0), and the `recorded_at` UTC timestamp at which the result was achieved. A new result is born with `verified` false and `is_pr` false.

Only a certified coach may verify a result: when a `Coach` whose `certified` flag is not set attempts verification, the request is rejected with `ERR_COACH_NOT_CERTIFIED`. Verification sets the result's `verified` flag to true, recomputes its `is_pr` flag, and increments the result's `version`. Personal-record determination considers only the member's other verified results for the same `benchmark_name`, excluding the result being verified. If there is no such prior verified result, this result is a personal record. Otherwise the comparison direction follows `metric_kind`: for a `TIME_SECONDS` benchmark (lower is better) the result is a personal record exactly when its `value` is strictly less than the best — that is, the smallest — prior verified value; for a `LOAD_KG` benchmark (higher is better) it is a personal record exactly when its `value` is strictly greater than the best — that is, the largest — prior verified value. Equal values are never a personal record.

The **leaderboard** for a program track ranks members by their best verified result for a requested `benchmark_name`, supplied as a query parameter. The candidate set is the verified benchmark results for that `benchmark_name` belonging to members who hold an `ACTIVE` membership on a plan attached to a session of the requested track, reduced to one best row per member. Each member's best is the smallest `value` for a `TIME_SECONDS` benchmark and the largest `value` for a `LOAD_KG` benchmark. The ranking then orders these bests: ascending for `TIME_SECONDS`, so the fastest time ranks first, and descending for `LOAD_KG`, so the heaviest load ranks first. When two members' bests tie, the earlier `recorded_at` of the best-defining result ranks higher; if `recorded_at` also ties, the earlier `created_at` of that result ranks higher. Ranks are 1-based.

### 3.7. Competition Teams and Roster Management

A `Member` forms a **competition team** by supplying a `name`, the `captain_member_id`, and a `max_roster_size` (at least 1, the maximum number of members on the roster including the captain). The team is created in `FORMING` status with `roster_size` 1, and the captain is simultaneously enrolled as a team-member row in `ACCEPTED` status. A team's `name` must be unique among teams that are not `DISBANDED`. The team `status` ranges over `FORMING`, `LOCKED`, and `DISBANDED`.

The captain grows the roster by inviting members. Inviting supplies the `team_id` and the `member_id` of the athlete being invited, creating a **team-member** row in `INVITED` status. A team-member row's `status` ranges over `INVITED`, `ACCEPTED`, `DECLINED`, and `REMOVED`. The invited athlete acts on their own slot: accepting it is permitted only while the slot is `INVITED`, the parent team is `FORMING`, the acting member is the slot's own `member_id`, and the team has room — its `roster_size` must be strictly below `max_roster_size`, otherwise the acceptance is rejected with `ERR_ROSTER_FULL`. Acceptance transitions the slot from `INVITED` to `ACCEPTED` and bubbles up an increment of one to the parent team's `roster_size`. Declining is permitted only while the slot is `INVITED` and the acting member is the slot's own `member_id`; it transitions the slot from `INVITED` to `DECLINED` and changes no roster count, since the invitee was never counted.

The captain may lock or disband the team while it is `FORMING`. Locking is permitted only when the team is `FORMING`, its `roster_size` is at least 1, and the acting member is the team's `captain_member_id`; it transitions the team from `FORMING` to `LOCKED`, finalizing the roster by cascading every still-`INVITED` team-member slot from `INVITED` to `DECLINED` (locking expires the outstanding invitations), and increments the team's `version`. Disbanding is permitted only when the team is `FORMING` and the acting member is the team's `captain_member_id`; it transitions the team from `FORMING` to `DISBANDED`, cascades every `ACCEPTED` or `INVITED` team-member slot to `REMOVED`, sets the team's `roster_size` to 0, and increments the team's `version`. A lock or disband from a non-`FORMING` team is rejected with `ERR_INVALID_STATE`. Both the lock and disband requests carry `expected_team_version`; the value is the client's last observed team `version`, recorded for the operation.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. To reconstruct the full request and response shape and side effects for any endpoint below, refer to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/box/membership-plans` | Create a membership plan (UNLIMITED or PUNCH) | BoxManager |
| GET | `/box/membership-plans` | List membership plans (filter by active or plan_type) | BoxManager, Member, Coach, Anonymous |
| GET | `/box/membership-plans/{id}` | Fetch one plan | BoxManager, Member, Coach, Anonymous |
| POST | `/box/membership-plans/{id}/archive` | Archive a plan (active=false) | BoxManager |
| POST | `/box/members/register` | Register a new member or visiting athlete | Anonymous |
| GET | `/box/members/{id}` | Fetch a member | BoxManager, Member, Coach |
| GET | `/box/members` | List members (filter by home_box_member) | BoxManager, Coach |
| POST | `/box/members/{id}/clear-strikes` | Reset a member's no-show strikes to 0 | BoxManager |
| POST | `/box/memberships` | Create a membership for a member on a plan | BoxManager, Member |
| GET | `/box/memberships/{id}` | Fetch a membership | BoxManager, Member, Coach |
| GET | `/box/memberships` | List memberships (filter by member_id, plan_id, status) | BoxManager, Member, Coach |
| POST | `/box/memberships/{id}/confirm-payment` | Confirm payment, activating the membership | BoxManager |
| POST | `/box/memberships/{id}/freeze` | Freeze an active membership | Member |
| POST | `/box/memberships/{id}/unfreeze` | Unfreeze a frozen membership and extend commitment | Member |
| POST | `/box/memberships/{id}/cancel` | Request cancellation; computes fee and cascades reservations | Member |
| POST | `/box/coaches` | Create a coach | BoxManager |
| GET | `/box/coaches/{id}` | Fetch a coach | BoxManager, Member, Coach |
| GET | `/box/coaches` | List coaches (filter by certified) | BoxManager, Member, Coach |
| POST | `/box/program-tracks` | Create a program track owned by a head coach | BoxManager |
| GET | `/box/program-tracks/{id}` | Fetch a program track | BoxManager, Member, Coach |
| GET | `/box/program-tracks` | List program tracks (filter by track_type, head_coach_id) | BoxManager, Member, Coach |
| GET | `/box/program-tracks/{id}/leaderboard` | Ranked leaderboard of best verified results for a benchmark | BoxManager, Member, Coach |
| POST | `/box/sessions` | Schedule a WOD class session | BoxManager, Coach |
| GET | `/box/sessions/{id}` | Fetch a session | BoxManager, Member, Coach |
| GET | `/box/sessions` | List sessions (filter by track_id, coach_id, status) | BoxManager, Member, Coach |
| POST | `/box/sessions/{id}/cancel` | Cancel a session; refunds and releases all reservations | BoxManager, Coach |
| POST | `/box/sessions/{id}/complete` | Complete a session, marking attendance/no-shows | BoxManager, Coach |
| POST | `/box/reservations` | Reserve a seat (or waitlist) on a session | Member |
| GET | `/box/reservations/{id}` | Fetch a reservation | BoxManager, Member, Coach |
| GET | `/box/reservations` | List reservations (filter by session_id, member_id, membership_id, status) | BoxManager, Member, Coach |
| POST | `/box/reservations/{id}/cancel` | Cancel a reservation; refund per window; promote waitlist | Member |
| POST | `/box/benchmark-results` | Record a benchmark/PR result (unverified) | Member |
| GET | `/box/benchmark-results/{id}` | Fetch a benchmark result | BoxManager, Member, Coach |
| GET | `/box/benchmark-results` | List benchmark results (filter by member_id, benchmark_name, verified) | BoxManager, Member, Coach |
| POST | `/box/benchmark-results/{id}/verify` | Certified coach verifies a result; recomputes is_pr | Coach |
| POST | `/box/teams` | Create a competition team | Member |
| GET | `/box/teams/{id}` | Fetch a competition team | BoxManager, Member, Coach |
| GET | `/box/teams` | List competition teams (filter by status, captain_member_id) | BoxManager, Member, Coach |
| POST | `/box/teams/{id}/lock` | Lock the roster; expires outstanding invites | Member |
| POST | `/box/teams/{id}/disband` | Disband a forming team | Member |
| POST | `/box/team-members` | Invite a member to a competition team | Member |
| GET | `/box/team-members/{id}` | Fetch a team-member roster slot | BoxManager, Member, Coach |
| GET | `/box/team-members` | List team-member roster slots (filter by team_id, member_id, status) | BoxManager, Member, Coach |
| POST | `/box/team-members/{id}/accept` | Accept an invite; bumps team roster_size | Member |
| POST | `/box/team-members/{id}/decline` | Decline an invite | Member |
| POST | `/box/_clock/set_current_utc` | Set the server logical clock to a UTC instant | BoxManager |
| POST | `/box/_membership/complete-foundations` | Sign off a membership's foundations prerequisite | Coach |
| POST | `/box/_billing/run-cycle-close` | Run the billing cycle-close batch; returns the cycle total | BoxManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_PLAN_SHAPE_INVALID` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBERSHIP_NOT_OWNED` | 409 |
| `ERR_RESERVATION_SUSPENDED` | 409 |
| `ERR_FOUNDATIONS_NOT_COMPLETED` | 409 |
| `ERR_RESERVATION_WINDOW_CLOSED` | 409 |
| `ERR_DROP_IN_NOT_ALLOWED` | 409 |
| `ERR_DUPLICATE_RESERVATION` | 409 |
| `ERR_SESSION_TIME_CONFLICT` | 409 |
| `ERR_COACH_DOUBLE_BOOKED` | 409 |
| `ERR_NO_PUNCHES_REMAINING` | 409 |
| `ERR_ROSTER_FULL` | 409 |
| `ERR_COACH_NOT_CERTIFIED` | 409 |
| `ERR_STALE_SESSION_VERSION` | 412 |
