# Early Childhood Enrichment API — Product Requirements Document

## 1. Introduction

This document specifies the Early Childhood Enrichment API, the system of record for a chain of developmental movement and play studios in the tradition of The Little Gym and Gymboree. Families enroll young children into age-banded movement programs, hold recurring memberships that bill on a monthly cycle, and rely on makeup credits when a class they paid for cannot be held. Behind the front desk, the studio juggles a finite set of rooms and a roster of instructors who are each certified for a specific subset of program levels, so every scheduled class is a small constraint-satisfaction problem: the right room, an available and qualified instructor, and a clean gap before and after the instructor's other classes.

The API exists to make the studio's day-to-day operations safe, fair, and financially exact. It governs the full arc of a child's participation — from a one-off paid trial class, through recurring enrollment in a level-appropriate program, to graduation up the level ladder as the child grows — while protecting capacity limits, parent-participation safety ratios, and the integrity of the credit and billing ledgers. It also accommodates the revenue add-ons that keep a studio viable: private birthday parties that take over a whole room, and shared open-gym sessions that pack children in against a room's physical capacity. Because front-desk staff, parents acting on their own accounts, and studio administrators all touch overlapping data, the system enforces precise role boundaries and uses optimistic concurrency to keep two well-meaning operators from overbooking the same last seat or double-booking the same room.

All time-dependent behavior — a child's age at the moment a class starts, the expiry of a makeup credit, the boundaries of a billing cycle, and the overlap of intervals — is evaluated against a single server-managed logical clock rather than wall-clock time, so the studio's operational state is fully deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API. The API is mounted under the `/enrichment` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `StudioAdmin`, `FrontDeskStaff`, and `Parent`.

A `StudioAdmin` is the studio operator. The `X-User-ID` of a `StudioAdmin` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. A `StudioAdmin` exclusively manages configuration and time: creating programs, creating rooms, creating instructors, deactivating instructors, and setting the logical clock. Beyond that, a `StudioAdmin` may perform essentially any operational action in the system.

A `FrontDeskStaff` is the front-desk operator. The `X-User-ID` of a `FrontDeskStaff` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. Front-desk staff own scheduling, attendance, and billing actions — scheduling class sessions, holding and cancelling sessions, renewing memberships, activating a pending membership, and advancing a child up a level — but cannot create or modify program, room, or instructor configuration.

A `Parent` is an account holder acting on their own family. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`; ownership checks on any resource that references a `Family` compare the resource's family foreign key to `X-User-ID`. Concretely, a `Parent` may act only on resources that trace back to their own `Family` — their own children, their own memberships, their own enrollments, their own facility bookings, and their own makeup credits and invoices. A `Parent` attempting to act on a family that is not their own is rejected with `ERR_UNAUTHORIZED`. For resources reached indirectly (an enrollment, a membership, a child), the ownership check resolves the chain back to the owning `Family.id` and compares it to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a standard set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation. Mutable resources additionally carry an `updated_at` (an ISO 8601 UTC timestamp refreshed on every change) and a `version` (an integer that begins at its initial value and increments by one on every mutation, used for optimistic concurrency control). The entities `Family`, `Child`, `Membership`, `Program`, `Room`, `Instructor`, `ClassSession`, `Enrollment`, `FacilityBooking`, and `Invoice` all carry the full set: `id`, `created_at`, `updated_at`, and `version`.

Two entities are deliberately leaner. An `AttendanceRecord` and a `MakeupCredit` each carry only an `id` and a `created_at`; they have no `updated_at` and no `version`. These rows are minted by cascades and, once written, are not independently versioned.

All age, expiry, billing-cycle, and interval-overlap reasoning is performed against a single logical clock maintained by the server. On startup the clock reads exactly `2026-04-01T00:00:00Z`; before any clock-setting call it holds this default and never falls back to real wall-clock time. An administrative test-driving capability moves the clock to a supplied UTC instant carried in the `to_iso8601` field, and every downstream rule that mentions "now," "the current instant," or "today" reads this clock.

### 2.5. Nested Resource Retrieval and Reverse Reachability

The entity model is flat: there is no nested ownership tree in the URL space. Cross-references between entities are foreign keys validated on write, and they are discovered through reverse-reachability list endpoints — for example, the children of a family, the memberships of a family, the enrollments of a child, the makeup credits of a membership, the invoices of a membership, the sessions in a room, the facility bookings in a room, the sessions assigned to an instructor, the enrollments of a session, and the attendance records of a session or enrollment.

When a path contains a resource identifier, the system validates referenced resources left to right and rejects the first missing one with `ERR_NOT_FOUND` (HTTP 404). This applies equally to identifiers supplied in a request body: every referenced `Family`, `Child`, `Membership`, `Program`, `Room`, `Instructor`, `ClassSession`, `Enrollment`, `MakeupCredit`, `FacilityBooking`, and `Invoice` must exist, checked in that order, before any business rule runs.

### 2.6. Hierarchical Consistency and Cascades

Many operations in this system touch more than one entity. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one (for the versioned entities listed in §2.4). When an operation cascades into other entities — cancelling enrollments, minting credits, voiding an invoice, promoting a waitlisted child — each affected versioned entity independently has its `version` bumped and `updated_at` refreshed. The detailed cascade rules live in the workflow narratives of §3; the governing principle here is that derived and computed fields are reconciled immediately and synchronously as part of the triggering request, never deferred. In particular, the computed fields `Family.child_count`, `Membership.makeup_credit_balance`, and `ClassSession.enrolled_count` always reflect the live state the instant a request completes.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer counts of cents — there are no fractional-cent or floating-point money values anywhere in the API. Where a calculation can produce a non-integer intermediate (proration, percentage discounts), the result is rounded using the round-half-up method to a whole number of cents. A rule that matters throughout billing: when several per-child tuition lines are combined, each individual line is rounded to whole cents first and only then summed — the system computes a sum of rounded lines, never a rounded sum. Where this ordering is load-bearing it is restated in the relevant workflow.

### 2.8. Optimistic Concurrency Control

Two write operations guard a shared parent resource with optimistic concurrency, and for those two operations the version field is a required, non-optional part of the request.

Creating an enrollment targets a `ClassSession` as its parent. The create request must carry `expected_session_version`, the `version` of the target `ClassSession` the client last observed. If that value does not equal the session's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason this matters: the last open seat may already have been claimed by an enrollment that advanced the session's `version`, so a client holding an older version is working from a stale view of `enrolled_count` and must be turned away rather than allowed to overbook.

Booking a facility targets a `Room` as its parent. The booking request must carry `expected_room_version`, the `version` of the target `Room` the client last observed. If that value does not equal the room's current `version`, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). A prior booking that occupies the requested window legitimately advances the room's `version`; a client holding an older room version is rejected before its potentially overlapping booking is committed.

These are the only two endpoints that take a version field. Every other mutation — activating, freezing, cancelling, holding, paying, advancing, and so on — does not accept or require an expected-version input.

### 2.9. Membership, Billing, and the Credit Ledger

A `Membership` is the recurring billing and entitlement relationship between a family and the studio. Its `tier` is one of `CORE`, `PLUS`, or `UNLIMITED`, and the tier fixes the monthly base fee that is snapshotted onto `monthly_base_fee_cents` at activation: 3000 cents for `CORE`, 5000 cents for `PLUS`, and 9000 cents for `UNLIMITED`. The base fee is snapshotted precisely so that a later change to studio pricing configuration never retroactively reprices an existing membership.

Each membership also tracks a credit ledger. `makeup_credit_balance` is the live count of that membership's `MakeupCredit` rows whose `status` is `AVAILABLE`, reconciled every time a credit is issued, redeemed, or expired. A credit's `status` is one of `AVAILABLE`, `REDEEMED`, or `EXPIRED`. A makeup credit carries an `expires_at` instant computed as its issuance time plus 60 days; once the logical clock passes that instant the credit is treated as expired for redemption purposes. A makeup credit is born only as a side effect of a cancelled session (see §3); it can never be created directly.

### 2.10. Capacity, Rooms, and Scheduling Integrity

A `Room` has a `physical_capacity` — the maximum number of children it can hold at once for any single session or booking — and a `ClassSession.capacity` may never exceed the room's `physical_capacity`. Class sessions and facility bookings compete for room time, and the system enforces non-overlap with half-open interval semantics: an interval runs from its `start_at` (inclusive) to its `end_at` (exclusive). Adjacency is therefore allowed — one event's `end_at` equal to another's `start_at` does not overlap.

For room scheduling, a session or a `BIRTHDAY_PARTY` booking holds the room exclusively: it must not strictly overlap any other non-`CANCELLED` session or any other non-`CANCELLED` `BIRTHDAY_PARTY` booking on the same room, and a violation is rejected with `ERR_ROOM_SCHEDULE_CONFLICT` (HTTP 409). `OPEN_GYM` bookings are shared: several may coexist in an overlapping window provided that the sum of `head_count` across all overlapping `CONFIRMED` `OPEN_GYM` bookings does not exceed the room's `physical_capacity`; exceeding it is the same `ERR_ROOM_SCHEDULE_CONFLICT`. Cancelling a session or a booking releases its interval so that later events may reuse the freed window.

### 2.11. Instructor Eligibility and Buffered Scheduling

An `Instructor` is certified for a set of program levels recorded in `certified_level_indices` and has a `status` of either `ACTIVE` or `INACTIVE`. An instructor also carries a `buffer_minutes` value, the required clear gap between any two of that instructor's classes. For overlap detection, the instructor's occupied interval for a session is the session's `[start_at, end_at)` expanded by `buffer_minutes` on each side; the expanded interval must not overlap any other non-`CANCELLED` session of the same instructor, or the new session is rejected with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` (HTTP 409). Certification and buffer rules are detailed alongside scheduling in §3.

### 2.12. Validation Ordering

When a single endpoint can fail several ways, the checks are evaluated in a fixed priority order so that the reported error is deterministic. The order, highest priority first, is: (1) authentication of the headers; (2) authorization of the role (and, for a `Parent`, that `X-User-ID` matches the owning `Family.id`); (3) existence of every referenced resource, validated left to right; (4) request-body well-formedness — required fields present and field types and enums valid; (5) that the target resource is in a state from which the requested transition is defined; (6) instructor certification and active status; (7) instructor schedule conflict; (8) room schedule conflict; (9) child age-band eligibility; (10) level match; (11) membership-active fiscal check; (12) session capacity; (13) parent-participation ratio; (14) availability of a makeup credit to redeem; and (15) the optimistic-concurrency stale-version check. A lower-numbered check always surfaces before a higher-numbered one when both would fail. Each check and its error code is described in context within §3; this ordering is the tie-breaker among them.

## 3. Business Logic & Workflows

### 3.1. Families, Children, and the Level Ladder

A family account is registered by front-desk or admin staff with an `account_email` (which must be non-empty and unique across all families) and a `primary_contact_name`. Each family exposes a computed `child_count`: the number of that family's `Child` rows whose `status` is `ENROLLED_ELIGIBLE`. Children whose `status` has become `WITHDRAWN` are excluded from this count. This count is what drives the sibling-discount tier described in §3.6.

A child is added under a family by supplying that family's identifier in the `family_id` field, along with the child's `full_name` and `birth_date` (an ISO 8601 calendar date, `YYYY-MM-DD`, which must be a valid date and must not be in the future relative to the logical clock; a future birth date is a malformed request, `ERR_INVALID_REQUEST`). A new child begins with `status` `ENROLLED_ELIGIBLE` and `current_level` 0, and the owning family's `child_count` is reconciled at creation.

A child's `current_level` is the `level_index` of the program the child is currently placed at. Programs form a self-referential ladder: each `Program` has a `next_program_id` pointing at the program a child advances into from it (null at the top of the ladder). When staff advance a child, they supply the `target_program_id` of the destination program; the child's `current_level` is set to that program's `level_index`. Advancement is not merely a label change — it triggers the advancement-transfer cascade. Every `ENROLLED` `RECURRING` enrollment of that child sitting on a session whose program `level_index` no longer equals the child's new `current_level` is demoted from `ENROLLED` to `WAITLISTED`: the child has moved up and out of that level's standing seat. Each such demotion assigns the row a `waitlist_seq` equal to one more than the current maximum `waitlist_seq` on that session (ties broken by `created_at` ascending), decrements that session's `enrolled_count` by one, and bumps the session's `version`. Freeing that seat in turn triggers promotion of the next waitlisted row on that session, exactly as an ordinary cancellation would.

Withdrawing a child sets the child's `status` to `WITHDRAWN`, which is terminal and only permitted from `ENROLLED_ELIGIBLE`; attempting to withdraw an already-withdrawn child is rejected with `ERR_INVALID_STATE` (HTTP 409). The withdrawal cascades over every `ENROLLED` or `WAITLISTED` enrollment of that child, transitioning each to `CANCELLED`. For each formerly `ENROLLED` enrollment, the host session's `enrolled_count` is decremented by one and that session's next waitlisted row is promoted; `WAITLISTED` enrollments simply terminate without touching any seat count. Finally the family's `child_count` is reconciled so the withdrawn child no longer counts toward sibling discounting.

### 3.2. Membership Lifecycle: Activation, Freeze, Reactivation, Cancellation

A membership is created for a family by supplying the `family_id`, the desired `tier`, and a `cycle_anchor_day` — the day of the month, an integer from 1 through 28 inclusive, on which the monthly billing cycle renews. A `cycle_anchor_day` outside that range is `ERR_INVALID_REQUEST`. A new membership opens in `PENDING_PAYMENT` with a `makeup_credit_balance` of 0; it holds no active billing relationship yet.

Activation moves a membership from `PENDING_PAYMENT` to `ACTIVE`. This is only valid from `PENDING_PAYMENT` (or, for reactivation, from `FROZEN`); calling it from any other state is `ERR_INVALID_STATE`. On the `PENDING_PAYMENT → ACTIVE` transition the system resolves and snapshots `monthly_base_fee_cents` from the tier (the 3000 / 5000 / 9000 mapping of §2.9), sets `current_cycle_start` to the current logical-clock instant, and increments the membership's `version`.

A `Parent` may freeze their own `ACTIVE` membership, moving it to `FROZEN`. Freezing is only valid from `ACTIVE`; otherwise `ERR_INVALID_STATE`. A frozen membership suspends billing — any renew attempt while `FROZEN` is rejected — but preserves all of its makeup credits across the freeze. Freezing increments the membership's `version`.

Reactivating a `FROZEN` membership runs the same activate operation and returns it to `ACTIVE`, valid only from `FROZEN` in that path. Reactivation sets `current_cycle_start` to the current logical-clock instant and increments the `version`; because reactivation can land partway through what would have been a billing cycle, the next renewal of a reactivated membership uses the prorated billing variant described in §3.6.

Cancellation moves a membership to the terminal `CANCELLED` state and is permitted from either `ACTIVE` or `FROZEN`. Cancelling is a multi-entity cascade. Every `AVAILABLE` makeup credit on the membership transitions to `EXPIRED` and the membership's `makeup_credit_balance` is reconciled to 0. From an `ACTIVE` membership, every `ENROLLED` or `WAITLISTED` enrollment billed to that membership is transitioned to `CANCELLED`; each formerly `ENROLLED` enrollment decrements its session's `enrolled_count` and frees a seat for waitlist promotion, exactly as an individual cancellation would. The membership's current `OPEN` invoice, if any, is voided to `VOID`. The membership's `version` is incremented. (A `FROZEN` membership has already suspended new enrollment activity, so its cancellation expires credits and bumps the version without the enrollment cascade.)

### 3.3. Scheduling Class Sessions

A class session is scheduled by front-desk or admin staff against a specific program, room, and instructor, supplied as `program_id`, `room_id`, and `instructor_id`, together with the session interval `start_at` (inclusive) and `end_at` (exclusive, and strictly after `start_at`, else `ERR_INVALID_REQUEST`) and a `capacity`. The session opens in `SCHEDULED` with an `enrolled_count` of 0.

Capacity is constrained by the room: `capacity` must be at least 1 and must not exceed the chosen room's `physical_capacity`; a capacity larger than the room is a malformed request, `ERR_INVALID_REQUEST`. The instructor must be certified for the session's level: the program's `level_index` must appear in the instructor's `certified_level_indices`, or the create is rejected with `ERR_INSTRUCTOR_NOT_CERTIFIED` (HTTP 422). The instructor's schedule must also be clear under the buffered-interval rule of §2.11 — the session's interval expanded by the instructor's `buffer_minutes` on each side must not overlap any of that instructor's other non-`CANCELLED` sessions — or the create is rejected with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`. Finally the room must be free under the half-open overlap rule of §2.10, or the create is rejected with `ERR_ROOM_SCHEDULE_CONFLICT`. Per the ordering in §2.12, certification is checked before the instructor schedule conflict, which is checked before the room conflict.

A session has two terminal outcomes that fork from `SCHEDULED` with deliberately divergent effects: it can be held or it can be cancelled.

Holding a session, valid only from `SCHEDULED`, advances it to `HELD`. Two further preconditions apply: the assigned instructor's `status` must be `ACTIVE` at hold time (an `INACTIVE` instructor blocks the hold with `ERR_INSTRUCTOR_NOT_CERTIFIED`), and the logical clock must have reached the session's `start_at` (the clock instant must be at or after `start_at`); a too-early hold is rejected as an invalid state, `ERR_INVALID_STATE`. The hold request carries an `attendance` map keyed per enrolled child. For each `ENROLLED` enrollment in the session the system creates an `AttendanceRecord` whose `outcome` is the value supplied in that map — `PRESENT` or `ABSENT` — and any enrolled child omitted from the map defaults to `ABSENT`. Holding mints no makeup credits whatsoever. The session's `version` is incremented.

Cancelling a session, valid only from `SCHEDULED`, advances it to `CANCELLED` and runs a three-depth cascade. At depth one, for each `ENROLLED` `RECURRING` enrollment in the session the system creates an `AttendanceRecord` with `outcome` `EXCUSED`. At depth two, each `EXCUSED` record mints exactly one `MakeupCredit` on that enrollment's membership, with `issued_tuition_cents` snapshotted to this cancelled session's program `tuition_cents` and `status` `AVAILABLE`. At depth three, each minted credit increments its membership's `makeup_credit_balance` by one and bumps that membership's `version`. `TRIAL` enrollments are pointedly excluded — a trial never earns a makeup credit. Independently of the credit cascade, every `ENROLLED` or `WAITLISTED` enrollment in the session is transitioned to `CANCELLED` and the session's `enrolled_count` is set to 0. The session's `version` is incremented. The contrast with the held branch is the whole point: holding records attendance and mints nothing, while cancelling mints credits for excused recurring children and voids the roster.

### 3.4. Enrollment: Trials, Recurring Seats, and the Waitlist

A child is enrolled in a session by supplying the `child_id`, the target `session_id`, and the billing `membership_id`, an optional `kind` (one of `TRIAL` or `RECURRING`, defaulting to `RECURRING`), an optional `accompanying_adult`, and the required `expected_session_version` for the concurrency check of §2.8. A `TRIAL` is a one-off paid trial that never grants makeup credits; a `RECURRING` enrollment is a standing seat. A new enrollment opens in `ENROLLED` unless capacity rules push it to `WAITLISTED`.

Enrolling is gated by a sequence of checks (ordered per §2.12). The target session must be `SCHEDULED`; enrolling into a `HELD` or `CANCELLED` session is `ERR_INVALID_STATE`. The child must be age-eligible: the child's whole-month age at the session's `start_at` must fall within the program's half-open band, at least `min_age_months` and strictly less than `max_age_months`. A child exactly at `max_age_months` is ineligible. A violation is `ERR_AGE_BAND_MISMATCH` (HTTP 422). For a `RECURRING` enrollment the child must be on-level: the child's `current_level` must equal the session's program `level_index`, or the request is rejected with `ERR_LEVEL_MISMATCH` (HTTP 422); `TRIAL` enrollments are exempt from the level match. The billing membership must be `ACTIVE`; a `RECURRING` enrollment against a `PENDING_PAYMENT`, `FROZEN`, or `CANCELLED` membership is rejected with `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP 422).

Capacity is where the two kinds diverge. A seat is available when the session's `enrolled_count` is below its `capacity`. A `RECURRING` request that arrives when the session is at capacity is not rejected — it is placed `WAITLISTED` instead. A `TRIAL` request that arrives at capacity is rejected outright with `ERR_SESSION_FULL` (HTTP 409), because a trial cannot occupy a waitlist seat. The parent-participation rule of §3.5 is also checked here. Finally the stale-version check of §2.8 applies: `expected_session_version` must match the session's live `version`, else `ERR_STALE_VERSION` (HTTP 412).

Every successful create increments the session's `version`, whether the new row landed `ENROLLED` or `WAITLISTED`, which is exactly what makes the next stale create fail. When a row is created `ENROLLED`, the session's `enrolled_count` is incremented by one. When a row is created `WAITLISTED`, it is assigned a `waitlist_seq` equal to one more than the maximum existing `waitlist_seq` on that session (and holds no seat, so `enrolled_count` is untouched).

The waitlist is a cyclic relationship between `ENROLLED` and `WAITLISTED`. Promotion happens automatically whenever a seat frees on a session that still has a waitlisted row and `enrolled_count` is below `capacity`: the system promotes the row with the lowest `waitlist_seq` first (ties broken by `created_at` ascending), clears that row's `waitlist_seq` to null, and increments the session's `enrolled_count` by one. Demotion is the reverse edge, used by the advancement-transfer cascade of §3.1: an `ENROLLED` row whose child's `current_level` has moved off this session's level is sent back to `WAITLISTED`. A `waitlist_seq` is null while a row is `ENROLLED`.

A parent (or staff) may cancel an enrollment. Cancelling an `ENROLLED` row requires its session still be `SCHEDULED`; cancelling against a session no longer `SCHEDULED` is `ERR_INVALID_STATE`. The row transitions to the terminal `CANCELLED` state, the session's `enrolled_count` is decremented by one to free the seat, the next waitlisted row (lowest `waitlist_seq`) is promoted as above, and the session's `version` is incremented. Cancelling a `WAITLISTED` row is also permitted: the row terminates, no seat count changes because a waitlisted row holds no seat, and the session's `version` is still incremented. An already-`CANCELLED` enrollment cannot be cancelled again (`ERR_INVALID_STATE`).

### 3.5. Parent Participation

Some programs require an accompanying adult to participate alongside the child, expressed by the program's `participation_required` flag, which defaults to true. When a session's program has `participation_required` true, each enrolling child must declare its accompanying adult through the `accompanying_adult` field on the enroll request. Omitting `accompanying_adult` for a participation-required program is rejected with `ERR_PARTICIPATION_REQUIRED` (HTTP 422). When the program does not require participation, the field may be omitted. This participation ratio is effectively one accompanying adult per enrolled child for the programs that require it.

### 3.6. Billing Cycles, Tuition, and the Sibling Discount

A membership's monthly invoice is produced by renewing the membership, an operation reserved for front-desk and admin staff. Renewal advances `current_cycle_start` forward by one cycle to the next `cycle_anchor_day` and emits a new `OPEN` invoice. An invoice carries the `membership_id` it bills, the `cycle_start` it covers, and the computed `subtotal_cents`, `sibling_discount_cents`, and `total_cents`; its `status` is one of `OPEN`, `PAID`, or `VOID`. Renewal requires the membership to be `ACTIVE` — a `FROZEN` membership's renewal is refused.

The invoice is built from the membership's billable roster: one tuition line per distinct child holding an `ENROLLED` `RECURRING` enrollment on this membership. `WAITLISTED`, `TRIAL`, and `CANCELLED` enrollments contribute nothing. Each child's line draws on that session's program `tuition_cents`, the per-cycle tuition charged per enrolled child. Two variants determine the line amount:

- **Full-cycle billing** applies when the membership was `ACTIVE` for the entire billing cycle. Each child's line is simply that program's `tuition_cents`, with no proration.
- **Mid-cycle prorated billing** applies when the membership was reactivated from `FROZEN` partway through the cycle — that is, `current_cycle_start` was reset to the reactivation instant, which is later than the cycle's nominal anchor. Here each child's line is the program's `tuition_cents` multiplied by the number of active days and divided by the fixed cycle length of 30 days, then rounded half-up to whole cents. The active-day count is the whole-day count from `current_cycle_start` to the renewal instant — the floor of the elapsed time measured in whole days — clamped to between 0 and 30 inclusive. For illustration: a membership reactivated 20 days before its renewal yields 10 active days, so a line whose program tuition is 2500 cents prorates to round-half-up of (2500 × 10 ÷ 30), which is 833 cents.

In both variants the rounding is applied to each child line before the lines are summed — sum-of-rounded, never round-of-sum. The `subtotal_cents` is the membership's `monthly_base_fee_cents` plus the sum of these rounded per-child tuition lines.

The sibling discount is then computed and applies only to the tuition portion of the bill, never to the base fee. Let the tuition-only amount be the subtotal minus `monthly_base_fee_cents`, and let the sibling count for billing be the family's `child_count` — that is, the number of `ENROLLED_ELIGIBLE` children with at least one `ENROLLED` `RECURRING` enrollment on this membership. The discount rate steps with that count: a count of one or fewer earns no discount (rate 0.00); exactly two earns 0.10; exactly three earns 0.15; and four or more earns 0.20. The raw discount is the tuition-only amount multiplied by that rate. This raw discount is rounded half-up to whole cents, and then capped: the final `sibling_discount_cents` is the smaller of the rounded raw discount and the largest single rounded child tuition line among the billed children — the discount may never exceed one full child's tuition line. Finally `total_cents` is `subtotal_cents` minus `sibling_discount_cents`, floored at 0 so the total is never negative.

An invoice can be fetched on demand and shows these computed line totals. Paying an invoice, an action available to staff or the owning parent, moves it from `OPEN` to `PAID` and increments its `version`; paying requires the invoice be `OPEN` (a non-`OPEN` invoice yields `ERR_INVALID_STATE`) and the billing membership be `ACTIVE` (otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`). Separately, an `OPEN` invoice is automatically voided to `VOID` by the membership-cancellation cascade of §3.2.

### 3.7. Redeeming Makeup Credits

When a recurring class is cancelled, the affected children earn makeup credits (§3.3). Redeeming a credit enrolls the child into a replacement session. The redeem request names the `target_session_id` and carries the required `expected_session_version` for the concurrency check against that target session. The system automatically selects a single `AVAILABLE` credit for the redeeming membership, choosing the credit with the earliest `expires_at` first, breaking ties by `created_at` ascending. The chosen credit's `source_attendance_id` records which `EXCUSED` attendance row minted it; this provenance pointer is not a queryable foreign key — credits are discovered through the membership's makeup-credits listing.

Redemption is gated as follows. There must be a usable credit at all: if `makeup_credit_balance` is 0, or every credit is expired, the redeem is rejected with `ERR_NO_CREDIT_AVAILABLE` (HTTP 409). The target session must be `SCHEDULED` with a free seat; a target session at or above capacity is rejected with `ERR_SESSION_FULL`. The child must be age-eligible for the target session's program band exactly as in ordinary enrollment, or `ERR_AGE_BAND_MISMATCH`. Crucially, makeup redemption is exempt from the level-match rule: a credit may be applied to a target session of any level the child is age-eligible for, even one off the child's `current_level`. The billing membership must be `ACTIVE`, else `ERR_MEMBERSHIP_NOT_ACTIVE`. The stale-version check of §2.8 applies via `expected_session_version`.

On a successful redemption the selected credit transitions from `AVAILABLE` to `REDEEMED`, the membership's `makeup_credit_balance` is decremented by one, and that membership's `version` is incremented. A new `RECURRING` enrollment is created `ENROLLED` on the target session, the target session's `enrolled_count` is incremented by one, and the target session's `version` is incremented. The new enrollment records the spent credit's identifier in `redeemed_credit_id` — a system field, not a queryable foreign key; the spent credit is discovered through the membership's own credit listing.

The credit's value is governed by two valuation variants over the program tuition. The **issuance value** is the snapshot taken when the credit was minted by a session-cancel cascade: `issued_tuition_cents` equals the cancelled session's program `tuition_cents`. The **redemption value** is computed live when the credit is spent against a target session that may sit at a different level. The redemption coverage is the smaller of the credit's `issued_tuition_cents` and the target program's `tuition_cents` — a credit covers at most the target level's tuition. When the target program's tuition exceeds the credit's snapshotted issuance value, the uncovered remainder is owed: the enrollment's `residual_owed_cents` is the larger of 0 and (the target program's `tuition_cents` minus the credit's `issued_tuition_cents`). For an ordinary, non-redemption enrollment `residual_owed_cents` is 0.

### 3.8. Facility Bookings: Birthday Parties and Open Gym

A facility booking reserves a room for an add-on event. It is created by supplying the `room_id`, the `family_id` of the booking family, a `booking_type`, the booking interval `start_at` (inclusive) and `end_at` (exclusive, strictly after start, else `ERR_INVALID_REQUEST`), an optional `head_count` (default 1, minimum 1), and the required `expected_room_version` for the room concurrency check of §2.8. The booking opens in `CONFIRMED`.

The `booking_type` is one of `BIRTHDAY_PARTY` or `OPEN_GYM`. A `BIRTHDAY_PARTY` is private and occupies the whole room exclusively for its interval regardless of `head_count` (the `head_count` is informational for a party). An `OPEN_GYM` is shared and counts its `head_count` against the room's `physical_capacity`. Both are subject to the room overlap rules of §2.10: a `BIRTHDAY_PARTY` cannot strictly overlap any other non-`CANCELLED` session or `BIRTHDAY_PARTY` on that room, while overlapping `OPEN_GYM` bookings coexist only while the summed `head_count` of overlapping `CONFIRMED` `OPEN_GYM` bookings stays within `physical_capacity`; either violation is `ERR_ROOM_SCHEDULE_CONFLICT`. Every successful booking increments the room's `version`. Cancelling a booking, valid only from `CONFIRMED`, moves it to the terminal `CANCELLED` state, releases the room interval for later use, and increments the room's `version`.

### 3.9. Instructors, Rooms, and Programs as Configuration

Studio administrators define the catalog the rest of the system schedules against. A program is created with a `name`, a unique ordinal `level_index` (an integer of at least 0, unique among programs), the inclusive lower age bound `min_age_months` and the exclusive upper age bound `max_age_months` (which must be strictly greater than `min_age_months`), the per-cycle `tuition_cents` (at least 0), and the optional `participation_required` (default true) and `next_program_id` (default null, the link up the ladder). A room is created with a `name` and a `physical_capacity` of at least 1. An instructor is created with a `full_name`, a non-empty `certified_level_indices` array, and an optional `buffer_minutes` (default 15). A newly created instructor opens with `status` `ACTIVE`. Deactivating an instructor sets `status` to `INACTIVE`, which blocks holding any of that instructor's sessions, as covered in §3.3.

A child's whole-month age at a session's start is the floor of the calendar-month difference between the session's `start_at` and the child's `birth_date`, measured in whole calendar months; this same age computation underlies both the enrollment age-band check and any advancement reasoning, and it always reads the session's `start_at` against the logical clock semantics of §2.4.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify or transition an existing resource, list resources, fetch a single resource, or advance the logical clock return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/enrichment/_clock/set_current_utc` | Set the logical clock to a UTC instant | StudioAdmin |
| POST | `/enrichment/families` | Register a family account | StudioAdmin, FrontDeskStaff |
| GET | `/enrichment/families/{id}` | Fetch a family including computed child count | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/families/{id}/children` | List a family's children | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/families/{id}/memberships` | List a family's memberships | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/children` | Add a child to a family | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/children/{id}` | Fetch a child | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/children/{id}/enrollments` | List a child's enrollments | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/children/{id}/advance` | Advance a child to the next program level | StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/children/{id}/withdraw` | Withdraw a child from the studio | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/memberships` | Create a recurring membership | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/memberships/{id}` | Fetch a membership including credit balance and version | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/memberships/{id}/makeup-credits` | List a membership's makeup credits | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/memberships/{id}/invoices` | List a membership's invoices | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/memberships/{id}/activate` | Activate or reactivate a membership | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/memberships/{id}/freeze` | Freeze an active membership | Parent, StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/memberships/{id}/cancel` | Cancel a membership (cascades) | Parent, StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/memberships/{id}/renew` | Advance to the next cycle and emit an invoice | StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/programs` | Create a program/level | StudioAdmin |
| GET | `/enrichment/programs/{id}` | Fetch a program | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/programs` | List programs, optionally filtered by `next_program_id` | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/rooms` | Create a room | StudioAdmin |
| GET | `/enrichment/rooms/{id}` | Fetch a room (includes version for OCC) | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/rooms/{id}/sessions` | List sessions in a room | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/rooms/{id}/facility-bookings` | List facility bookings in a room | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/instructors` | Create an instructor | StudioAdmin |
| GET | `/enrichment/instructors/{id}` | Fetch an instructor | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/instructors/{id}/sessions` | List an instructor's sessions | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/instructors/{id}/deactivate` | Set an instructor inactive | StudioAdmin |
| POST | `/enrichment/sessions` | Schedule a class session | StudioAdmin, FrontDeskStaff |
| GET | `/enrichment/sessions` | List sessions, optionally filtered by `program_id` | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/sessions/{id}` | Fetch a session including enrolled count and version | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/sessions/{id}/enrollments` | List a session's enrollments | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/sessions/{id}/attendance` | List a session's attendance records | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/attendance-records` | List attendance records, optionally filtered by `enrollment_id` or `session_id` | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/sessions/{id}/hold` | Hold a session (records attendance) | FrontDeskStaff, StudioAdmin |
| POST | `/enrichment/sessions/{id}/cancel` | Cancel a session (mints credits, voids enrollments) | FrontDeskStaff, StudioAdmin |
| POST | `/enrichment/enrollments` | Enroll a child in a session | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/enrollments/{id}` | Fetch an enrollment | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/enrollments/{id}/attendance` | List an enrollment's attendance records | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/enrollments` | List enrollments filtered by `membership_id` | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/enrollments/{id}/cancel` | Cancel an enrollment (frees a seat, promotes waitlist) | Parent, StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/enrollments/{id}/redeem-makeup` | Redeem a makeup credit into a target session | Parent, StudioAdmin, FrontDeskStaff |
| POST | `/enrichment/facility-bookings` | Book a room for a party or open gym | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/facility-bookings` | List facility bookings, optionally filtered by `family_id` | StudioAdmin, FrontDeskStaff, Parent |
| GET | `/enrichment/facility-bookings/{id}` | Fetch a facility booking | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/facility-bookings/{id}/cancel` | Cancel a facility booking | Parent, StudioAdmin, FrontDeskStaff |
| GET | `/enrichment/invoices/{id}` | Fetch an invoice with computed line totals | StudioAdmin, FrontDeskStaff, Parent |
| POST | `/enrichment/invoices/{id}/pay` | Mark an open invoice paid | FrontDeskStaff, StudioAdmin, Parent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ROOM_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_AGE_BAND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_PARTICIPATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_CREDIT_AVAILABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
