# Kids Coding & STEM Camp API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the backend API that powers a chain of children's coding and STEM enrichment centers, in the spirit of programs such as Code Ninjas or iD Tech. The platform must reconcile two pressures that pull in opposite directions: families want flexible ways to enroll their children — drop-in single sessions, recurring memberships, multi-week summer camps — while centers must respect hard physical limits on lab devices and the number of children a single instructor may safely supervise. Every seat sold is constrained simultaneously by hardware inventory and by staffing ratio, and the system must never let an enrollment over-subscribe either one.

Beyond capacity, the platform tracks each child's curriculum journey. Members progress through belt levels within a program track, earning badges as they master concepts, and they may compete in showcases once they reach an eligible rank. Guardians manage their own children's enrollments, memberships, and competition entries through a parent portal, while instructors record attendance and award badges, and center administrators configure the catalogue and run the operational sweeps. The pricing engine layers multi-week camp discounts, sibling discounts, and an account wallet credit on top of base fees, and a billing-cycle sweep returns the value of unused membership sessions back to families. The remainder of this document defines the global contracts that all endpoints share, the business workflows that govern each entity's lifecycle, the full endpoint catalogue, and the canonical error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as follows: `CenterAdmin`, `Instructor`, and `Guardian`. When an authenticated caller attempts an operation that its role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

A `CenterAdmin` is operations staff: this role configures centers, programs, belt levels, and badges, runs the session and showcase lifecycles, adjusts guardian wallets, and drives the billing-cycle and logical-clock sweeps. `CenterAdmin` is a superset only for configuration and lifecycle operations; it is not a blanket override of the billing decisions that belong to a guardian. An `Instructor` is teaching staff: this role records attendance through check-ins, awards and revokes badges, and promotes members, in addition to read access across the catalogue and roster. A `Guardian` is a parent who owns their members, memberships, enrollments, and showcase entries, and manages the enrollment and membership lifecycle for their own children.

When `X-User-Role` is `CenterAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. When `X-User-Role` is `Instructor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; ownership checks on any resource that references a guardian compare the resource's owning guardian to `X-User-ID`. For guardian-owned resources, the owning guardian is established directly on a `Guardian`, or transitively: a `Member` is owned through its `guardian_id`, a `Membership` through its member's `guardian_id`, and an `Enrollment` or `ShowcaseEntry` through its member's `guardian_id`. When a guardian acts on a resource it does not own under any of these chains, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check guards the following guardian-scoped operations specifically: creating an enrollment, cancelling an enrollment, creating a membership, activating, pausing, resuming, or cancelling a membership, creating a member, reading a member's progress, creating a showcase entry, and withdrawing a showcase entry.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every persisted resource in the system — centers, programs, belt levels, badges, guardians, members, memberships, sessions, enrollments, badge awards, showcases, and showcase entries — carries a standard set of system-managed fields:

- **`id`** (string): A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): An ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- **`updated_at`** (string): An ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- **`version`** (integer): A system-managed integer that begins at its initial value and increments by one with every mutation of the resource. It is the basis for optimistic concurrency control.

All entities in this system carry the full set of common fields, including `updated_at` and `version`. Whenever a derived or computed field on a resource changes — for example a session's `confirmed_seat_count`, a guardian's `wallet_credit_cents`, a member's `active_badge_count`, or a membership's `sessions_used_this_cycle` — that change counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented by one.

### 2.5. The Logical Clock

The system operates against a server-controlled logical clock rather than real wall-clock time, so that age computations, refund windows, entry deadlines, and session-end checks are fully deterministic. At server startup the clock is fixed at exactly `2026-04-01T00:00:00Z`; before any clock-setting call is made, every read of "now" returns precisely this default instant and never the real wall-clock. An administrative test-driving capability advances the logical clock to a supplied `to_iso8601` instant, after which all subsequent reads of "now" return that instant. All stored timestamps are UTC; a center's `timezone` is an IANA timezone string used only for display and defaults to `UTC`.

### 2.6. Capacity Posture and the Seat Constraint

A session's available capacity is bounded simultaneously by two independent physical resources: the lab devices at its center and the supervision ceiling implied by the instructor-to-student ratio. The system computes a single **effective capacity** for each session and re-evaluates it whenever the confirmed seat count changes. The device-bound seat count is the center's `device_count` divided by the session's `device_seats_requested`, rounded down to a whole number of seats, because each seat consumes `device_seats_requested` devices. The instructor-bound seat count is the session's `assigned_instructor_count` multiplied by the center's `min_student_instructor_ratio` (the maximum number of students one instructor may supervise). The effective capacity is the smaller of these two: the device-bound seat count and the instructor-bound seat count. When the device-bound seat count is the smaller of the two, capacity is limited by devices and adding instructors does not raise it; when the instructor-bound seat count is the smaller, capacity is limited by staffing and adding devices does not raise it.

From the effective capacity the system derives a session's posture, using a restricted threshold equal to the effective capacity multiplied by 0.8 and rounded up to a whole number. When the confirmed seat count is below that rounded-up restricted threshold, the session's posture is `OPEN`. When the confirmed seat count is at least the rounded-up restricted threshold but still strictly below the effective capacity, the posture is `RESTRICTED`. When the confirmed seat count equals the effective capacity exactly, the posture is `FULL`. For a small effective capacity the restricted band can be empty — for instance, when the effective capacity is 2, its restricted threshold rounds up to 2, which equals capacity, so no `RESTRICTED` band exists. The confirmed seat count is the number of enrollments on a session whose attendance is in `RESERVED`, `CHECKED_IN`, or `ATTENDED`, and it is recomputed on every enrollment create, cancel, and check-in.

### 2.7. Monetary Values and Rounding

All monetary amounts in the system — drop-in fees, membership fees, enrollment prices, wallet credit, and cycle refunds — are stored and exchanged as whole integer numbers of cents. Wherever a calculation requires rounding, the system uses the round-half-up method, rounding to the nearest whole cent with ties going up. The pricing rules specify exactly where each rounding step occurs; rounding is applied at those pinned points and not arbitrarily redistributed. The member progress score is likewise an integer in the range 0 through 100, obtained by rounding half up after the weighting step.

### 2.8. Hierarchical Consistency and Cascades

Many operations in this system mutate more than one entity. When a single action drives a state change, the system applies every downstream effect described in the relevant workflow narrative, and each affected resource independently refreshes its `updated_at` and increments its `version`. For example, cancelling a session does not merely change the session: it drives every non-terminal enrollment on that session to a cancelled attendance state, which in turn returns money to each affected guardian's wallet or restores a membership seat, and the restored wallet credit is subsequently observable when that guardian's next drop-in enrollment is priced. These chains are applied immediately and synchronously; the system maintains an immediate consistency model in which derived fields and dependent states are reconciled within the same operation that triggered them. Where the server itself re-derives a session's posture or recomputes a member's badge count without an explicit client request on that specific resource, it does so as part of the triggering operation.

### 2.9. Nested Resource Validation Order

Resources in this system are flat collections linked by foreign-key references carried in request paths and bodies rather than nested ownership URLs. For any request, the system validates the existence of every referenced resource left-to-right in the canonical order — `Center`, `Program`, `BeltLevel`, `Badge`, `Guardian`, `Member`, `Membership`, `Session`, `Enrollment`, `Showcase`, `ShowcaseEntry` — and rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier, whether in the path or the body, that does not correspond to an existing resource.

### 2.10. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the earliest failing check determines the error returned. The order is: first, authentication of the request headers (`ERR_UNAUTHENTICATED`); second, whether the acting role is permitted for the operation (`ERR_FORBIDDEN_ROLE`); third, for guardian-owned resources, whether the acting guardian owns the target (`ERR_NOT_RESOURCE_OWNER`); fourth, existence of every referenced resource (`ERR_RESOURCE_NOT_FOUND`); and fifth, whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after these gates pass does the system evaluate the operation's domain-specific business rules. Within the enrollment-create operation specifically, those domain rules are themselves ordered, as described in the enrollment workflow: program match, then age, then duplicate enrollment, then schedule conflict, then sibling-index, then membership coverage, then seat capacity, then the optimistic-concurrency version check, and finally field-shape validation. The relative ordering ensures, for example, that a program mismatch surfaces as `ERR_PROGRAM_MISMATCH` before a capacity check could mask it.

### 2.11. Optimistic Concurrency Control

Two write operations in the system guard a finite shared pool against a stale view of remaining capacity by means of optimistic concurrency control, and each requires the caller to supply the parent's last-observed version as a non-optional field.

The enrollment-create operation requires `expected_session_version`, carrying the client's last observed `version` of the target session. A seat is a finite resource: when an earlier enrollment consumed the last seat, the session's `version` advanced (its `confirmed_seat_count` was bumped and its posture re-derived toward `FULL`). If `expected_session_version` does not match the session's current `version`, the create is operating on a stale view of remaining capacity and is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412) rather than silently over-subscribing the lab.

The showcase-entry accept operation requires `expected_showcase_version`, carrying the client's last observed `version` of the parent showcase. Showcase capacity is likewise a finite pool: when a prior accept consumed the final slot, the showcase's `version` advanced (its `accepted_entry_count` was bumped). If `expected_showcase_version` does not match the showcase's current `version`, the accept is rejected with `ERR_STALE_SHOWCASE_VERSION` (HTTP 412). Operations other than these two do not take a version field and are not subject to a concurrency-version check.

### 2.12. Status Codes

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions, wallet adjustments, promotions, and the sweeps — return `200 OK`. Read operations return `200 OK`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalogue: Centers, Programs, Belts, and Badges

A `CenterAdmin` establishes the operational catalogue. A **Center** is created with a display `name`, a `device_count` giving the number of lab devices (laptops or robots) physically present (which must be at least 1), a `min_student_instructor_ratio` giving the maximum number of students one instructor may supervise (at least 1), and an optional `timezone` IANA string that defaults to `UTC` and is used for display only.

A **Program** (a track such as "JR Robotics" or "CREATE Coding") is created with a `name`, a short unique `code`, a `min_age`, a `max_age`, and a `drop_in_fee_cents`. The `code` must be unique across all programs and consist of 2 to 8 uppercase characters drawn from A–Z and 0–9. The `min_age` is the minimum member age in whole years allowed to enroll in any session of this program and must be at least 4; the `max_age` is the inclusive maximum age and must be greater than or equal to `min_age`. The `drop_in_fee_cents` is the base per-seat drop-in fee in cents for a single session of this program before any discount, and must be at least 0.

Each program is structured into a ladder of **belt levels**. A `BeltLevel` is created with its owning `program_id`, a `name` (such as "White", "Yellow", or "Black"), a 1-based `rank` giving its ordinal within the program, an optional `prereq_belt_level_id`, and a `required_badge_count`. The `rank` must be at least 1 and must be unique among belts of the same program. The `prereq_belt_level_id` references the belt a member must hold before promoting into this one, and is null only for the entry belt of rank 1. The `required_badge_count` is the number of distinct active badges of this belt a member must have been awarded before promotion into the next belt is permitted, and must be at least 0. Belt levels may be listed and filtered by `program_id` or by `prereq_belt_level_id`.

Within each belt's curriculum, a `CenterAdmin` defines **badges**. A `Badge` is created with the `belt_level_id` of the belt whose curriculum it belongs to and a `name` (such as "Loops" or "Variables"). A badge's `status` begins at `ACTIVE` when created. A retire action moves the `status` to `RETIRED`; once retired, the badge no longer counts toward promotion requirements computed after the retirement, but BadgeAward rows already issued for it are preserved. Retiring a badge also recomputes `active_badge_count` for every member who holds an active award of that badge on their current belt — the cascade reaches each such member — and increments the badge's `version` by one. Badges may be listed and filtered by `belt_level_id`. The two valid badge status values are `ACTIVE` and `RETIRED`.

### 3.2. Guardians, Wallets, and Members

A **Guardian** record (a parent) is registered with a `full_name` and an `email`. The `email` is the login and contact address and must be unique across all guardians, compared case-insensitively. Each guardian holds an account credit balance, `wallet_credit_cents`, denominated in cents and never permitted to fall below zero; it begins at 0. This balance is increased by enrollment-cancellation refunds and membership cycle credits, and decreased when applied to a drop-in enrollment. A guardian record may be fetched, and the fetch includes the current `wallet_credit_cents`.

A `CenterAdmin` may directly correct a guardian's wallet through a wallet-adjustment action, supplying an `amount_cents` and a `reason`. A positive `amount_cents` credits the wallet; a negative `amount_cents` debits it. The adjustment adds `amount_cents` to `wallet_credit_cents`, but the balance is clamped so it never goes below zero, and it increments the guardian's `version` by one. If a negative adjustment would drive the wallet below zero — that is, the magnitude of the debit exceeds the current balance — the request is rejected with `ERR_WALLET_INSUFFICIENT` (HTTP 409).

A **Member** (a child) is created with the owning `guardian_id`, the `program_id` of the track the child is on, a `full_name`, and a `birth_date` (an ISO 8601 value whose date portion is authoritative). The child's age is computed as whole completed years against the logical clock. On creation, the member's `current_belt_level_id` is automatically set to the rank-1 belt of the member's program, and the member's `active_badge_count` is initialized to 0. The `active_badge_count` is the count of distinct active BadgeAward rows for the member whose underlying badge is `ACTIVE` and whose badge belongs to the member's current belt; it is recomputed on every badge award, badge revoke, and badge retire. Members may be listed and filtered by `guardian_id`, `program_id`, or `current_belt_level_id`.

### 3.3. Membership Lifecycle and the Billing Cycle

A guardian (or a `CenterAdmin` acting on their behalf) creates a **Membership** for a member by supplying the `member_id`, a recurring `monthly_fee_cents` (at least 0), and an `included_sessions_per_cycle` (at least 0) giving the number of membership-covered, zero-marginal-cost session enrollments granted each billing cycle. A membership's `status` begins at `PENDING`. It also tracks `sessions_used_this_cycle`, the number of membership-covered enrollments consumed in the current cycle (starting at 0), and `cycle_index`, a 0-based count of completed billing cycles (starting at 0). The four valid membership statuses are `PENDING`, `ACTIVE`, `PAUSED`, and `CANCELLED`.

Activating a `PENDING` membership transitions it `PENDING → ACTIVE`; this is permitted only when the membership is currently `PENDING`, and on activation `sessions_used_this_cycle` is set to 0 and `cycle_index` is set to 0, and the membership's `version` is incremented by one. An active membership may be paused, transitioning `ACTIVE → PAUSED`; this is permitted only from `ACTIVE`, after which the membership stops covering new enrollments while paused, and its `version` is incremented. A paused membership may be resumed, transitioning `PAUSED → ACTIVE`; this is permitted only from `PAUSED`, and the membership resumes covering enrollments with `sessions_used_this_cycle` left unchanged across the pause, with its `version` incremented. The `ACTIVE → PAUSED → ACTIVE` cycle may repeat any number of times. A membership may be cancelled from either `ACTIVE` or `PAUSED`, transitioning to `CANCELLED`; once cancelled, all future enrollments for that member default to drop-in coverage, and the membership's `version` is incremented. Any state-transition action attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409). Memberships may be listed and filtered by `member_id`.

A billing-cycle sweep — an administrative test-driving and real-world operation — advances the cycle for active memberships, optionally narrowed to a single `member_id`. For each `ACTIVE` membership the sweep computes an unused-session credit; memberships that are `PAUSED` or `CANCELLED` are skipped entirely, receiving no credit and no reset. The number of unused sessions is the membership's `included_sessions_per_cycle` minus its `sessions_used_this_cycle`, floored at zero so it is never negative. The per-session value is the `monthly_fee_cents` divided by the `included_sessions_per_cycle` (using 1 as the divisor if `included_sessions_per_cycle` is 0, to avoid division by zero), left unrounded at this stage. The credit is the number of unused sessions multiplied by the per-session value, rounded half up to whole cents once after the multiplication. This prorated credit — proportional to the unused sessions only — is authoritative; the system does not refund the entire monthly fee whenever any session is unused. The computed credit is added to the member's guardian's `wallet_credit_cents`, after which `sessions_used_this_cycle` is reset to 0 and `cycle_index` is incremented by one.

### 3.4. Sessions: Creation, Opening, and Capacity Posture

A `CenterAdmin` creates a **Session** by supplying the `center_id` where it runs, the `program_id` of the track it teaches (members must be on this program to enroll), a `format`, a `week_count`, a `starts_at`, an `ends_at`, a `device_seats_requested`, and an `assigned_instructor_count`. The `format` is one of `AFTER_SCHOOL`, `WEEKLY`, or `CAMP`. A `CAMP` session runs a multi-week block with a `week_count` greater than 1, whereas `AFTER_SCHOOL` and `WEEKLY` sessions are single-week and must have a `week_count` of exactly 1; the `week_count` must be at least 1 and must equal 1 unless the format is `CAMP`. The `starts_at` and `ends_at` are ISO 8601 UTC instants, and `ends_at` must be strictly after `starts_at`. The `device_seats_requested` is the number of devices each seat-holder needs and must be at least 1; the `assigned_instructor_count` is the number of instructors staffed on the session and must be at least 1. A session's `status` begins at `DRAFT`. The six valid session statuses are `DRAFT`, `OPEN`, `RESTRICTED`, `FULL`, `CANCELLED`, and `COMPLETED`. The session also carries a computed `confirmed_seat_count`, starting at 0. Sessions may be listed and filtered by `center_id`, `program_id`, or `status`.

Opening a draft session transitions it `DRAFT → OPEN` and is restricted to a `CenterAdmin`. It is permitted only when the session is currently `DRAFT`, the `ends_at` is strictly after the `starts_at`, and the `assigned_instructor_count` is at least 1. On opening, the `confirmed_seat_count` is set to 0, the effective capacity is computed as described in §2.6, the session begins accepting enrollments in the `OPEN` posture, and the session's `version` is incremented by one. As enrollments are created and cancelled, the system automatically re-derives the posture among `OPEN`, `RESTRICTED`, and `FULL` according to the thresholds in §2.6: an enrollment create may carry the session from `OPEN` into `RESTRICTED` (when the new confirmed seat count reaches at least the rounded-up restricted threshold but stays below effective capacity) or into `FULL` (when the new confirmed seat count equals effective capacity exactly), and an enrollment cancel may revert it from `FULL` to `RESTRICTED` (when the post-cancel count lands at or above the rounded-up restricted threshold but below capacity), from `RESTRICTED` to `OPEN` (when the post-cancel count falls below the rounded-up restricted threshold), or directly from `FULL` to `OPEN` (when the post-cancel count falls below the rounded-up restricted threshold, which happens for small capacities whose restricted band is empty). These posture shifts are system-driven and require no explicit client action on the session.

A session may be completed once its end instant is reached. Completing a session transitions it from `OPEN`, `RESTRICTED`, or `FULL` to `COMPLETED`, and is restricted to a `CenterAdmin`; it is permitted only when the session's status is one of `OPEN`, `RESTRICTED`, or `FULL`, and only when the logical clock's "now" is at or after the session's `ends_at`. If completion is attempted before the clock reaches `ends_at`, it is rejected with `ERR_SESSION_NOT_ENDED` (HTTP 409). On completion, every enrollment whose attendance is `CHECKED_IN` transitions to `ATTENDED`, and every enrollment still `RESERVED` transitions to `NO_SHOW` with no refund — and if such an enrollment's billing was `CHARGED`, its billing becomes `FORFEITED`, while if its billing was `COVERED` the membership seat is not returned. Completion increments the session's `version` by one.

A `CenterAdmin` may cancel a session from `DRAFT`, `OPEN`, `RESTRICTED`, or `FULL`, transitioning it to `CANCELLED`. A center-initiated cancel always refunds in full regardless of any refund window, in contrast to a guardian-initiated enrollment cancel. The cancellation cascades in hops: the session moving to `CANCELLED` drives every non-terminal enrollment on it — those whose attendance is `RESERVED` or `CHECKED_IN` — to a `CANCELLED` attendance state; each such enrollment then settles its billing as `REFUNDED`, and for a drop-in enrollment the guardian's `wallet_credit_cents` is increased by the sum of that enrollment's `price_cents` and `wallet_applied_cents` (restoring both the cash paid and the wallet credit originally consumed, so money is conserved), while for a membership enrollment the covering membership's `sessions_used_this_cycle` is decremented by one. The restored wallet credit then becomes observable on the guardian's next drop-in enrollment, where it is applied during pricing. Each hop is caused by the prior hop rather than directly by the cancel action. Cancelling the session increments its `version` by one.

### 3.5. Enrollment: Pricing, Coverage, and the Two Status Axes

Enrolling a member into a session is performed by a guardian (or a `CenterAdmin`) and is the most heavily guarded operation in the system. The request supplies the `session_id`, the `member_id`, a `coverage`, an optional `sibling_index`, and the mandatory `expected_session_version` for the optimistic-concurrency check described in §2.11. The `coverage` is either `DROP_IN`, meaning the seat is paid per session, or `MEMBERSHIP`, meaning it consumes one included session from the member's active membership. An `Enrollment` carries two independent status axes. The attendance axis, `attendance_status`, begins at `RESERVED` and may be `RESERVED`, `CHECKED_IN`, `ATTENDED`, `NO_SHOW`, or `CANCELLED`. The billing axis, `billing_status`, begins at `UNBILLED` and may be `UNBILLED`, `CHARGED`, `COVERED`, `REFUNDED`, or `FORFEITED`. These axes move independently; for instance, a check-in changes only the attendance axis and leaves the billing axis untouched. Enrollments may be listed and filtered by `session_id` or `member_id`.

Before an enrollment is admitted, the operation runs its domain checks in the following order. First, the member's `program_id` must equal the session's `program_id`, or the request is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 409). Next, the member's age in whole completed years at the logical clock must fall within the session program's `min_age` and `max_age`, inclusive of both ends, or the request is rejected with `ERR_AGE_OUT_OF_RANGE` (HTTP 409). Next, the member must not already hold a non-terminal enrollment in this session — that is, no existing enrollment for this member on this session whose attendance is `RESERVED` or `CHECKED_IN` — or the request is rejected with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409). Next comes the member's self-scheduling check: the target session's half-open time interval, from its `starts_at` inclusive to its `ends_at` exclusive, must not overlap the half-open interval of any other session in which this member holds a non-terminal enrollment (`RESERVED` or `CHECKED_IN`); adjacency is allowed, so two sessions where one's `ends_at` equals the other's `starts_at` do not conflict because the interval is end-exclusive. An overlap is rejected with `ERR_MEMBER_SCHEDULE_CONFLICT` (HTTP 409).

The `sibling_index` is a 1-based ordinal of this child among the guardian's children enrolled in this same session at create time, defaulting to 1; the client supplies it and the server validates it. The supplied `sibling_index` must equal one plus the count of the same guardian's other children who already hold a non-terminal enrollment in this session — leaving no gaps and no duplicates — or the request is rejected with `ERR_INVALID_SIBLING_INDEX` (HTTP 409). For `MEMBERSHIP` coverage, the member must have an `ACTIVE` membership whose `sessions_used_this_cycle` is strictly less than its `included_sessions_per_cycle` (so an included seat remains), or the request is rejected with `ERR_NO_INCLUDED_SESSIONS` (HTTP 409). The enrollment must not push the session's `confirmed_seat_count` above the session's effective capacity; a create that would exceed effective capacity is rejected with `ERR_SESSION_AT_CAPACITY` (HTTP 409). Finally the optimistic-concurrency check on `expected_session_version` is applied (yielding `ERR_STALE_SESSION_VERSION`, HTTP 412, on a mismatch), and field-shape validation guards required fields, valid enums, and in-range numbers (yielding `ERR_INVALID_FIELD`, HTTP 422).

When coverage is `MEMBERSHIP`, the enrollment's `price_cents` is set to 0 and its `billing_status` becomes `COVERED`, the covering membership's `sessions_used_this_cycle` is incremented by one. When coverage is `DROP_IN`, the system computes the charged price and wallet application as described in §3.6, sets `billing_status` to `CHARGED`, and debits the guardian's wallet. In both cases the session's `confirmed_seat_count` is incremented by one, the session posture is re-derived per §2.6, and the session's `version` is incremented by one.

A reserved enrollment may be checked in by an `Instructor` (or `CenterAdmin`), transitioning the attendance axis `RESERVED → CHECKED_IN`. Check-in is permitted only when the enrollment's attendance is `RESERVED`, the session's status is one of `OPEN`, `RESTRICTED`, or `FULL`, and the logical clock's "now" is at or after the session's `starts_at`. Check-in changes only `attendance_status` and leaves `billing_status` unchanged, and it increments the enrollment's `version` by one.

A guardian (or `CenterAdmin`) may cancel an enrollment while the session is not `COMPLETED`. From a `RESERVED` attendance state the cancel sets `attendance_status` to `CANCELLED`, and the billing outcome depends on coverage and the refund window. For a drop-in enrollment, if the time from "now" until the session's `starts_at` is at least 24 hours, the cancel is refundable: `billing_status` becomes `REFUNDED` and the guardian's `wallet_credit_cents` is increased by the sum of the enrollment's `price_cents` and `wallet_applied_cents`, restoring both the cash paid and the wallet credit originally consumed so that total money is conserved. For a drop-in enrollment cancelled when the time until `starts_at` is less than 24 hours, the cancel is non-refundable: `billing_status` becomes `FORFEITED` and no wallet credit is returned, neither `price_cents` nor `wallet_applied_cents`. For a membership enrollment, the cancel sets `billing_status` to `REFUNDED` and decrements the covering membership's `sessions_used_this_cycle` by one, returning the seat regardless of the window. From a `CHECKED_IN` attendance state the cancel sets `attendance_status` to `CANCELLED` and `billing_status` to `FORFEITED` with no refund, because the child has already been checked in. In all cancel cases the session's `confirmed_seat_count` is decremented by one and the posture is re-derived (reverting from `FULL` toward `RESTRICTED` or `OPEN` as applicable), and the enrollment's `version` is incremented by one. A cancel from `RESERVED` requires the attendance to be `RESERVED`, and a cancel from `CHECKED_IN` requires the attendance to be `CHECKED_IN`; both require that the session is not `COMPLETED`.

### 3.6. The Drop-In Pricing Engine

When a drop-in enrollment is created, the system computes its `price_cents` and `wallet_applied_cents` through a pinned four-step sequence that must be followed exactly. The single enrollment's pricing draws on the program's `drop_in_fee_cents`, the session's `format` and `week_count`, the enrollment's `sibling_index`, and the guardian's `wallet_credit_cents`.

The first step takes the base price as the program's `drop_in_fee_cents`. The second step applies the multi-week multiplier, which is relevant only for camps: if the session's format is `CAMP` and its `week_count` is at least 2, the week factor is the `week_count` multiplied by the quantity one minus 0.10 (the multi-week discount of ten percent); otherwise the week factor is simply the `week_count`, which for a single-week session is a factor of 1. The gross amount is the base multiplied by the week factor, rounded half up to whole cents at this point — this rounding happens here, per line, before any sibling discount. The third step applies the sibling discount to the rounded gross: if the enrollment's `sibling_index` is at least 2, the discounted amount is the gross multiplied by the quantity one minus 0.15 (the sibling discount of fifteen percent), rounded half up to whole cents; otherwise the discounted amount equals the gross unchanged. The fourth step applies wallet credit: the amount of wallet credit applied, `wallet_applied_cents`, is the smaller of the guardian's current `wallet_credit_cents` and the discounted amount, the final `price_cents` is the discounted amount minus `wallet_applied_cents`, and the guardian's `wallet_credit_cents` is then reduced by `wallet_applied_cents` (the debit happens only after the price has been pinned). Performing the steps in this order — compute the discounted amount, derive the wallet application from it, then debit — makes the otherwise circular dependency between price and wallet well-defined. When the guardian's wallet credit is 0, `wallet_applied_cents` is 0 and `price_cents` equals the discounted amount; when the wallet credit is positive, `wallet_applied_cents` is the smaller of the credit and the discounted amount, the price is reduced accordingly, and the wallet is debited.

A guardian (or `CenterAdmin`) may preview the price of enrolling several siblings into a single camp session through a read-only quote, supplying the `member_ids` to be priced (all of whom must be on the session's program). The quote prices each child exactly as the drop-in engine above would, assigning `sibling_index` values 1 through N in the order the `member_ids` are listed (the first child receives index 1), so that the second and later children receive the sibling discount. The order of rounding versus summing is pinned to round-per-seat-then-sum: each per-seat price is computed and rounded by its own pinned steps first, and the block total is the sum of those already-rounded per-seat prices. The sum is exact integer cents and is not re-rounded; the system deliberately does not sum the raw pre-round amounts and round once at the end, because that would yield a different cent total. Wallet credit is not applied in the quote because the quote is a preview only and persists nothing; it returns the block total in cents along with the per-seat breakdown. The quote response is the session resource object (the same fields a session fetch returns) extended with two additional fields: `block_total_cents`, the integer-cents sum of the already-rounded per-seat prices, and `per_seat`, an array holding one object per priced member in the same order the `member_ids` were supplied, where each element is an object carrying that member's `member_id`, its assigned `sibling_index` (1 through N in supply order), and its `price_cents`.

### 3.7. Curriculum Progression: Badge Awards and Promotion

An `Instructor` (or `CenterAdmin`) records mastery by awarding a badge to a member through a **BadgeAward**, supplying the `enrollment_id` during which the badge was earned (which pins the member and session) and the `badge_id` of the badge awarded. A badge award's `status` begins at `ACTIVE`; only active awards count toward `active_badge_count` and toward promotion. Creating an award recomputes the member's `active_badge_count` — the cascade runs from the new award to the member's count, which may in turn unblock a promotion — and increments the member's `version` by one. The two valid award statuses are `ACTIVE` and `REVOKED`. An award may be revoked by an `Instructor` (or `CenterAdmin`), transitioning its `status` from `ACTIVE` to `REVOKED` and recomputing the member's `active_badge_count` (cascading to the member), and incrementing the badge award's `version` by one. Badge awards may be listed and filtered by `enrollment_id` or `badge_id`.

Promoting a member to the next belt is performed by an `Instructor` (or `CenterAdmin`). The promotion target is the belt one rank above the member's current belt within the member's program. Promotion is permitted only when the member's `active_badge_count` for the current belt is at least the current belt's `required_badge_count`, and the member currently holds the prerequisite belt in rank order; if these requirements are not met — including the case where no next belt exists — the request is rejected with `ERR_PROMOTION_REQUIREMENTS_NOT_MET` (HTTP 409). On a successful promotion, the member's `current_belt_level_id` advances to the rank-plus-one belt of the program, the member's `active_badge_count` is recomputed for the new current belt (effectively resetting relative to the new belt), and the member's `version` is incremented by one.

A guardian reads a child's progress through the parent portal, which returns the member's progress score together with the belt, badge, and attendance breakdown. The read returns the member resource object extended with a single nested `progress` object; the progress score and the breakdown live inside that `progress` object rather than at the top level of `data`. The `progress` object carries `progress_score` (the computed score described below), `belt_rank` (the rank of the member's current belt), `total_belts` (the number of belts in the member's program), `active_badge_count`, `required_badge_count` (the current belt's `required_badge_count`), `attended_sessions` (the count of the member's `ATTENDED` enrollments), and `no_show_sessions` (the count of the member's `NO_SHOW` enrollments). The progress score blends three factors. The belt factor is the rank of the member's current belt divided by the total number of belts in the member's program, yielding a value between 0 and 1. The badge factor is the member's `active_badge_count` divided by the current belt's `required_badge_count` (using 1 as the divisor if that requirement is 0), capped at a maximum of 1.0. The attendance factor is the number of the member's attended sessions divided by the sum of the member's attended and no-show sessions, where attended sessions are the enrollments with attendance `ATTENDED` and no-show sessions are the enrollments with attendance `NO_SHOW`; when the member has no attended or no-show sessions at all, the attendance factor is defined as 0 rather than an undefined division. The raw blend weights the belt factor by 0.5, the badge factor by 0.3, and the attendance factor by 0.2; the final progress score is the raw blend multiplied by 100, rounded half up to a whole integer in the range 0 through 100. This read also persists a reconciliation of `active_badge_count` if it was found stale.

### 3.8. Showcases and Competition Entries

A `CenterAdmin` runs **showcases** (competitions). A `Showcase` is created with the host `center_id`, the `program_id` whose members may enter, a `min_belt_rank` (the minimum belt rank an entrant's current belt must meet or exceed, at least 1), a `capacity` (the maximum number of accepted entries, at least 1), a `starts_at`, and an `entry_deadline_at`. The `entry_deadline_at` is the inclusive instant at or before which entries may be submitted and must be strictly before `starts_at`. A showcase's `status` begins at `DRAFT`; the five valid statuses are `DRAFT`, `OPEN`, `JUDGING`, `COMPLETED`, and `CANCELLED`. The showcase also tracks a computed `accepted_entry_count`, starting at 0, which is recomputed on entry accept and entry withdraw. Showcases may be listed and filtered by `center_id`, `program_id`, or `status`.

Opening a showcase transitions it `DRAFT → OPEN` and is permitted only when it is currently `DRAFT` and its `entry_deadline_at` is strictly before its `starts_at`, after which it accepts entries; opening increments the showcase's `version` by one. After the deadline has passed, a `CenterAdmin` closes entries, transitioning the showcase `OPEN → JUDGING`; this is permitted only from `OPEN` and only when the logical clock's "now" is strictly after the `entry_deadline_at` (otherwise it is rejected with `ERR_DEADLINE_NOT_REACHED`, HTTP 409). Closing entries sweeps every entry still in `SUBMITTED` to `REJECTED` and increments the showcase's `version` by one. Posting results transitions the showcase `JUDGING → COMPLETED`; it is permitted only from `JUDGING` and only when every accepted entry has reached `SCORED` (if any accepted entry remains un-scored it is rejected with `ERR_UNSCORED_ENTRIES_REMAIN`, HTTP 409). Posting results assigns each scored entry a final placement `rank`, ordered by `score` descending and then by `created_at` ascending, numbering 1 through N, and increments the showcase's `version` by one. A `CenterAdmin` may cancel a showcase from `DRAFT`, `OPEN`, or `JUDGING`, transitioning it to `CANCELLED`; cancellation drives every non-terminal entry — those in `SUBMITTED`, `ACCEPTED`, or `SCORED` — to `WITHDRAWN`, sets the `accepted_entry_count` to 0, and increments the showcase's `version` by one.

A guardian (or `CenterAdmin`) submits a member into a showcase by supplying the `showcase_id` and the `member_id`. A **ShowcaseEntry**'s `status` begins at `SUBMITTED`; the five valid statuses are `SUBMITTED`, `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `SCORED`. The entry carries an optional judge `score` (a number between 0 and 100 inclusive when present, otherwise null) supplied during scoring, and a computed final `rank` (null until the showcase reaches judging or completion). At submit time the member's `program_id` must equal the showcase's `program_id` or the request is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 409). The entry must be submitted at or before the showcase's `entry_deadline_at` (the boundary instant is inclusive); after that instant the request is rejected with `ERR_ENTRY_DEADLINE_PASSED` (HTTP 409). The submission is also subject to a showcase-session clash check: the symmetric closed window spanning 120 minutes before to 120 minutes after the showcase's `starts_at` must not contain the `starts_at` of any session in which the member holds a non-terminal enrollment; unlike the half-open member-schedule rule for sessions, this clash is evaluated as a closed buffered window around the single showcase-start instant, and a violation is rejected with `ERR_SHOWCASE_SESSION_CLASH` (HTTP 409). Showcase entries may be listed and filtered by `showcase_id` or `member_id`.

From `SUBMITTED` an entry may fork into one of two outcomes. A `CenterAdmin` accepts an entry, transitioning it `SUBMITTED → ACCEPTED`; acceptance requires that the entry is `SUBMITTED`, the showcase is `OPEN`, the showcase's `accepted_entry_count` is below its `capacity`, and the member's current belt rank meets or exceeds the showcase's `min_belt_rank`. An accept whose member's belt rank is below `min_belt_rank` is rejected with `ERR_BELT_TOO_LOW` (HTTP 409); an accept that would push `accepted_entry_count` above `capacity` is rejected with `ERR_SHOWCASE_AT_CAPACITY` (HTTP 409). The accept also requires the `expected_showcase_version` field for the optimistic-concurrency check of §2.11, rejected on mismatch with `ERR_STALE_SHOWCASE_VERSION` (HTTP 412). A successful accept sets the entry to `ACCEPTED`, increments the showcase's `accepted_entry_count` by one, and increments the showcase's `version` by one. Alternatively a `CenterAdmin` rejects an entry, transitioning it `SUBMITTED → REJECTED`; rejection is permitted while the showcase is `OPEN` or `JUDGING`, has no effect on capacity, and increments the entry's `version` by one. The two branches carry divergent effects: accept is capacity-consuming and belt-gated, while reject changes no capacity.

A guardian (or `CenterAdmin`) may withdraw an accepted entry, transitioning it `ACCEPTED → WITHDRAWN`; withdrawal is permitted while the showcase is `OPEN` or `JUDGING`, frees a slot by decrementing the showcase's `accepted_entry_count` by one, and increments the entry's `version` by one. During judging, a `CenterAdmin` scores an accepted entry, transitioning it `ACCEPTED → SCORED`; scoring is permitted only when the entry is `ACCEPTED`, the showcase is `JUDGING`, and the supplied `score` is between 0 and 100 inclusive, after which the entry's `score` is set and its `version` is incremented by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions, wallet adjustments, promotions, the quote preview, and the administrative sweeps — return a `200 OK` status code, as do all read operations.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/centers` | Create a center with device inventory and instructor ratio | CenterAdmin |
| GET | `/centers/{id}` | Fetch a center | CenterAdmin, Instructor, Guardian |
| POST | `/programs` | Create a program/track with age range and base drop-in fee | CenterAdmin |
| GET | `/programs/{id}` | Fetch a program | CenterAdmin, Instructor, Guardian |
| POST | `/belt-levels` | Create a belt level within a program | CenterAdmin |
| GET | `/belt-levels/{id}` | Fetch a belt level | CenterAdmin, Instructor, Guardian |
| GET | `/belt-levels` | List belt levels; filter by program or prerequisite | CenterAdmin, Instructor, Guardian |
| POST | `/badges` | Create a curriculum badge tied to a belt level | CenterAdmin |
| GET | `/badges/{id}` | Fetch a badge | CenterAdmin, Instructor, Guardian |
| GET | `/badges` | List badges; filter by belt level | CenterAdmin, Instructor, Guardian |
| POST | `/badges/{id}/retire` | Retire a badge; recompute affected members' badge counts | CenterAdmin |
| POST | `/guardians` | Register a guardian (parent) | CenterAdmin, Guardian |
| GET | `/guardians/{id}` | Fetch a guardian (includes wallet credit) | CenterAdmin, Guardian |
| POST | `/guardians/{id}/wallet/adjustments` | Admin credit/debit of a guardian wallet | CenterAdmin |
| POST | `/members` | Create a child member | CenterAdmin, Guardian |
| GET | `/members/{id}` | Fetch a member | CenterAdmin, Instructor, Guardian |
| GET | `/members` | List members; filter by guardian, program, or belt | CenterAdmin, Instructor, Guardian |
| GET | `/members/{id}/progress` | Parent-portal progress read | CenterAdmin, Instructor, Guardian |
| POST | `/members/{id}/promote` | Promote a member to the next belt | CenterAdmin, Instructor |
| POST | `/memberships` | Create a PENDING membership for a member | CenterAdmin, Guardian |
| GET | `/memberships/{id}` | Fetch a membership | CenterAdmin, Guardian |
| GET | `/memberships` | List memberships; filter by member | CenterAdmin, Guardian |
| POST | `/memberships/{id}/activate` | Activate a PENDING membership | CenterAdmin, Guardian |
| POST | `/memberships/{id}/pause` | Pause an ACTIVE membership | CenterAdmin, Guardian |
| POST | `/memberships/{id}/resume` | Resume a PAUSED membership | CenterAdmin, Guardian |
| POST | `/memberships/{id}/cancel` | Cancel an ACTIVE or PAUSED membership | CenterAdmin, Guardian |
| POST | `/sessions` | Create a DRAFT session at a center for a program | CenterAdmin |
| GET | `/sessions/{id}` | Fetch a session (includes seat count and posture) | CenterAdmin, Instructor, Guardian |
| GET | `/sessions` | List sessions; filter by center, program, or status | CenterAdmin, Instructor, Guardian |
| GET | `/sessions/{id}/quote` | Read-only multi-child CAMP price preview | CenterAdmin, Guardian |
| POST | `/sessions/{id}/open` | Open a DRAFT session for enrollment | CenterAdmin |
| POST | `/sessions/{id}/complete` | Complete a session after its end instant | CenterAdmin |
| POST | `/sessions/{id}/cancel` | Cancel a session; full-refund non-terminal enrollments | CenterAdmin |
| POST | `/enrollments` | Enroll a member in a session (drop-in or membership) | CenterAdmin, Guardian |
| GET | `/enrollments/{id}` | Fetch an enrollment | CenterAdmin, Instructor, Guardian |
| GET | `/enrollments` | List enrollments; filter by session or member | CenterAdmin, Instructor, Guardian |
| POST | `/enrollments/{id}/check-in` | Instructor checks a reserved enrollment in | Instructor, CenterAdmin |
| POST | `/enrollments/{id}/cancel` | Guardian cancels an enrollment | Guardian, CenterAdmin |
| POST | `/badge-awards` | Award a badge to a member via an enrollment | Instructor, CenterAdmin |
| GET | `/badge-awards/{id}` | Fetch a badge award | CenterAdmin, Instructor, Guardian |
| GET | `/badge-awards` | List badge awards; filter by enrollment or badge | CenterAdmin, Instructor, Guardian |
| POST | `/badge-awards/{id}/revoke` | Revoke a badge award | Instructor, CenterAdmin |
| POST | `/showcases` | Create a DRAFT showcase/competition | CenterAdmin |
| GET | `/showcases/{id}` | Fetch a showcase | CenterAdmin, Instructor, Guardian |
| GET | `/showcases` | List showcases; filter by center, program, or status | CenterAdmin, Instructor, Guardian |
| POST | `/showcases/{id}/open` | Open a showcase for entries | CenterAdmin |
| POST | `/showcases/{id}/close-entries` | Close entries after the deadline; move to judging | CenterAdmin |
| POST | `/showcases/{id}/post-results` | Post results: assign ranks; complete | CenterAdmin |
| POST | `/showcases/{id}/cancel` | Cancel a showcase; withdraw all non-terminal entries | CenterAdmin |
| POST | `/showcase-entries` | Submit a member into a showcase | CenterAdmin, Guardian |
| GET | `/showcase-entries/{id}` | Fetch a showcase entry | CenterAdmin, Instructor, Guardian |
| GET | `/showcase-entries` | List entries; filter by showcase or member | CenterAdmin, Instructor, Guardian |
| POST | `/showcase-entries/{id}/accept` | Accept a SUBMITTED entry (belt + capacity gated) | CenterAdmin |
| POST | `/showcase-entries/{id}/reject` | Reject a SUBMITTED entry | CenterAdmin |
| POST | `/showcase-entries/{id}/score` | Score an ACCEPTED entry during judging | CenterAdmin |
| POST | `/showcase-entries/{id}/withdraw` | Withdraw an ACCEPTED entry | Guardian, CenterAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CenterAdmin |
| POST | `/_billing/advance-cycle` | Advance the billing cycle for ACTIVE memberships | CenterAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROGRAM_MISMATCH` | 409 |
| `ERR_AGE_OUT_OF_RANGE` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_MEMBER_SCHEDULE_CONFLICT` | 409 |
| `ERR_SHOWCASE_SESSION_CLASH` | 409 |
| `ERR_ENTRY_DEADLINE_PASSED` | 409 |
| `ERR_BELT_TOO_LOW` | 409 |
| `ERR_PROMOTION_REQUIREMENTS_NOT_MET` | 409 |
| `ERR_INVALID_SIBLING_INDEX` | 409 |
| `ERR_NO_INCLUDED_SESSIONS` | 409 |
| `ERR_SESSION_AT_CAPACITY` | 409 |
| `ERR_SHOWCASE_AT_CAPACITY` | 409 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_SHOWCASE_VERSION` | 412 |
| `ERR_INVALID_FIELD` | 422 |
| `ERR_WALLET_INSUFFICIENT` | 409 |
| `ERR_SESSION_NOT_ENDED` | 409 |
| `ERR_DEADLINE_NOT_REACHED` | 409 |
| `ERR_UNSCORED_ENTRIES_REMAIN` | 409 |
