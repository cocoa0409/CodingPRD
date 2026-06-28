# Learning-Center Franchise API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Learning-Center Franchise platform, a back-office system modeled on supplemental-education franchises such as Kumon, Mathnasium, and Sylvan. The platform coordinates four overlapping concerns that operators struggle to keep consistent by hand: the diagnostic placement of a student onto an individualized curriculum track, the day-to-day scheduling of tutoring sessions under strict instructor-to-student ratios, the recurring billing of tuition and one-time enrollment fees with multi-subject and sibling discounts, and the royalty accounting a franchisee owes the franchisor on collected tuition.

The system serves a franchise hierarchy. A franchisor administrator stands up centers, signs the franchise agreement that governs each one, and defines the subjects and curriculum levels students progress through. A center director runs a single location — enrolling families, placing students by diagnostic score, scheduling sessions, and producing the monthly invoices. Instructors grade worksheets and record attendance for the sessions they staff. Parents read their children's progress and pay invoices. The platform's central promise is that every derived figure — a student's current level, a family's discounted monthly rate, an invoice's amount due, the royalty owed on a payment — is computed deterministically from the events that produced it, so that any two operators reading the same data reach the same conclusion.

Because tuition pricing, mastery-driven curriculum advancement, attendance capacity, and royalty settlement are deeply interdependent, the bulk of this specification concerns how a change in one place ripples correctly through the others. A student pausing one enrollment can change a sibling's discount; mastering a worksheet set can advance a level or complete an enrollment; suspending a center can cascade through its sessions down to individual bookings.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation — or the caller is acting on a resource outside the center or family they are scoped to — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `FranchiseAdmin`, `CenterDirector`, `Instructor`, and `Parent`.

A `FranchiseAdmin` is a franchisor-side operator who configures centers, franchise agreements, subjects, and curriculum levels, and who drives the test clock. When `X-User-Role` is `FranchiseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A `CenterDirector` runs the operations of a single center — the enrollment, session, and invoice lifecycles. When `X-User-Role` is `CenterDirector`, `X-User-ID` is likewise an opaque operator identifier; the director is scoped to the center(s) they operate, which the server enforces by comparing the target resource's `center_id` to the director's scope rather than to `X-User-ID` itself. An `Instructor` grades worksheets and records attendance. When `X-User-Role` is `Instructor`, `X-User-ID` is an opaque instructor identifier; the server may record it (for example, as `instructor_user_id` on a `Session` when a session is scheduled) but does not compare it to any entity's `id`. A `Parent` is a family account holder: when `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`, and ownership checks on any resource that references a `Family` compare the resource's `family_id` (directly, or by following the chain through `Student` and `Enrollment`) to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; it defaults to 10 when omitted, and is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter counts how many items to skip from the front of the result and defaults to 0. A `limit` that is non-integer or outside 1 through 100, or an `offset` that is non-integer or negative, is rejected with `ERR_INVALID_REQUEST` (422).

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order; when two items share a `created_at`, their relative order is their insertion (creation) order, which is stable and deterministic.

List endpoints additionally accept optional exact-match filter query parameters, each narrowing the result to items whose named field equals the supplied value; supplying several filters intersects (ANDs) them, and an unrecognized or empty filter parameter is ignored. The filterable fields per list endpoint are: centers by `status`; franchise-agreements by `center_id`; subjects by `center_id`; curriculum-levels by `subject_id` and `prereq_level_id`; families by `center_id`; students by `family_id`; enrollments by `center_id`, `student_id`, `subject_id`, `placement_level_id`, `current_level_id`, and `status`; worksheets by `enrollment_id`, `level_id`, and `status`; sessions by `center_id` and `status`; attendance-records by `session_id`, `enrollment_id`, and `status`; and invoices by `family_id`, `center_id`, and `status`.

Every list response carries the pagination bookkeeping inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in the system — `Center`, `FranchiseAgreement`, `Subject`, `CurriculumLevel`, `Family`, `Student`, `Enrollment`, `Worksheet`, `Session`, `AttendanceRecord`, and `Invoice` — carries a server-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment the resource is first created.

Each of these resources additionally carries an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current time on any mutation of the resource, including mutations of computed fields. The `version` starts at its initial value when the resource is created and increments by exactly one on every mutation. This versioning is the substrate for both the audit trail and the optimistic-concurrency mechanism described in §2.7. When a state-machine transition or a recompute touches a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this holds equally for derived fields, so recomputing a `Family`'s `sibling_count`, an `Enrollment`'s `monthly_rate_cents`, or a `Session`'s `booked_seat_count` is itself a versioned mutation of the entity that owns the field.

### 2.5. Hierarchical Consistency and Cascading State

The platform keeps parent and child state aligned automatically. When a parent transition makes downstream work untenable, the server resolves the affected children in the same operation rather than leaving them dangling, and when a child event changes the basis for a derived parent value, the server recomputes that value immediately.

The clearest example is center suspension. When a `Center` moves from `OPERATING` to `SUSPENDED`, every `Session` at that center whose status is `SCHEDULED` or `OPEN` is driven to `CANCELLED` (a first-level cascade). For each session so cancelled, every `AttendanceRecord` on it whose status is `BOOKED` or `PRESENT` is in turn driven to `CANCELLED`, and that session's `booked_seat_count` is recomputed accordingly (a second-level cascade). Each entity touched along this chain has its `version` incremented and `updated_at` refreshed.

A symmetric pattern governs enrollment changes and family discounts: whenever an enrollment becomes active, pauses, resumes, completes, or withdraws, the owning `Family`'s `sibling_count` is recomputed and the per-enrollment `monthly_rate_cents` is recomputed for the still-active enrollments across that family. Sessions closing and bookings cancelling likewise feed back into the parent session's seat count. These propagation rules are detailed alongside the workflows that trigger them in §3.

### 2.6. Tuition, Discounts, and Royalty Accounting Principles

All monetary amounts in this system are integer counts of cents; the field names carry the `_cents` suffix to make this explicit. There are no fractional cents and no floating-point money values in responses. Discount and royalty math is governed by precise rounding rules stated with each calculation in §3, but two principles hold throughout. First, when a percentage discount is applied to tuition, the result is floored to a whole cent after each discount step rather than once at the end. Second, when a basis-point royalty or marketing fee is applied to collected tuition, each term is floored to a whole cent before the terms are summed.

Royalty and marketing rates are expressed in basis points (`royalty_rate_bps`, `marketing_fee_bps`), where one basis point is one ten-thousandth: ten thousand basis points equal the whole amount. Discount tiers are expressed as percentages of the base tuition. The interplay of multi-subject discounts, sibling discounts, royalty floors, and wallet credits is the heart of the pricing engine and is specified workflow-by-workflow in §3.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's last-observed `version`. These are the only two endpoints that take a version field; no other endpoint accepts one.

Creating a draft invoice for a family requires the request to carry `expected_family_version`, holding the client's last-observed `version` of the target `Family`. Drafting an invoice bills tuition and enrollment fees that supersede the family's prior unbilled state, so the create is rejected when `expected_family_version` no longer matches the family's current `version`: another draft-invoice creation has already advanced the family's `version` (recomputing or consuming the billable enrollments), which means the present writer's view of the family is stale. The rejection carries `ERR_STALE_VERSION` (HTTP 412).

Booking a seat requires the request to carry `expected_session_version`, holding the client's last-observed `version` of the target `Session`. A booking is rejected when `expected_session_version` no longer matches the session's current `version`: another writer has already booked a seat (advancing the session's `version` and its `booked_seat_count`), so the present writer's view of remaining capacity is stale. This rejection also carries `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Resource Existence and Validation Ordering

When multiple validations could fire on one request, they are evaluated in a fixed priority order so that the same input always yields the same error. Authentication is checked first: a request with missing or unknown headers fails with `ERR_UNAUTHENTICATED` (401) before anything else. Authorization is checked second: a caller whose role is not permitted to invoke the operation at all fails immediately with `ERR_FORBIDDEN` (403), before existence is examined. Existence is checked third: every resource referenced by the request — first the identifiers embedded in the URL path, validated left to right, then the foreign keys named in the body — must exist, or the request fails with `ERR_NOT_FOUND` (404), reporting the first missing reference encountered. The narrower resource-scope ownership check — whether a `Parent` (or center-scoped role) actually owns the targeted resource — is necessarily evaluated only after that resource is confirmed to exist, since ownership is determined by following the resource's family or center chain; a present-but-unauthorized scope still yields `ERR_FORBIDDEN` (403), but a reference to a resource that does not exist yields `ERR_NOT_FOUND` (404) rather than `ERR_FORBIDDEN`. Request well-formedness is checked fourth: required fields must be present, enum values must be legal, and numeric values must lie in their declared standalone ranges (for example, `diagnostic_raw_score` within 0 through 100, and `seat_cap` being an integer of at least 1); a violation yields `ERR_INVALID_REQUEST` (422), except that an out-of-range worksheet grade is reported specifically as `ERR_SCORE_OUT_OF_RANGE` (422). The cross-entity upper bound on `seat_cap` — that it not exceed the center's `instructor_ratio_cap` — is not a well-formedness check but a later business rule reported as `ERR_RATIO_EXCEEDED` (see §3.5).

Only after those four gates does the request reach state and business rules. The optimistic-concurrency check (priority five) runs next where it applies, yielding `ERR_STALE_VERSION` (412). The state-machine guard (priority six) runs after that: a resource that is not in a valid originating state for the requested transition fails with `ERR_INVALID_STATE` (409). The remaining business rules then apply in this order: instructor-ratio and seat-capacity enforcement (`ERR_RATIO_EXCEEDED`, 409), then per-enrollment session-overlap (`ERR_SESSION_OVERLAP`, 409), then per-instructor session double-booking (`ERR_INSTRUCTOR_DOUBLE_BOOKED`, 409), then curriculum prerequisite integrity (`ERR_PREREQ_CYCLE`, 409), then level-to-subject coherence (`ERR_LEVEL_SUBJECT_MISMATCH`, 409), then territory uniqueness (`ERR_TERRITORY_CONFLICT`, 409), and finally invoice payment exactness (`ERR_PAYMENT_AMOUNT_MISMATCH`, 409). This ordering matters when an input could trip more than one rule: the earlier rule in the list is the one reported.

### 2.9. The Test-Driving Logical Clock

All deadline, age, and interval comparisons in the system read a single logical clock rather than wall-clock time. On server startup the logical clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it never falls back to wall-clock time. A `FranchiseAdmin` may set the clock to an absolute UTC instant by supplying that instant as `to_iso8601`; the clock is set to exactly the supplied instant with no requirement that it move strictly forward (it may be set to an earlier instant), and a `to_iso8601` that is missing or not a parseable ISO 8601 instant is rejected with `ERR_INVALID_REQUEST` (422). The endpoint returns `200 OK` with an empty `data` object. From that point on, every check that asks "is it now after this moment?" — session start gating, future-attendance cancellation on withdrawal, session-overlap windows, certification-style age checks — reads the value just set.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Center and Its Franchise Agreement

A `FranchiseAdmin` brings a location online in stages. Creating a center records its `name`, a `territory_code`, and three pricing knobs that default if omitted: the `instructor_ratio_cap` (the most students one instructor may staff in a single session, defaulting to 6 and never less than 1), the one-time `enrollment_fee_cents` charged the first time a student enrolls (defaulting to 5000 and never negative), and the base `monthly_tuition_cents` per subject-enrollment before discounts (defaulting to 15000 and never negative). A freshly created center begins in `PROVISIONING` status with its `active_enrollment_count` at 0, where `active_enrollment_count` reflects the number of enrollments at the center whose status is either `ACTIVE` or `PAUSED`. This count is a read-time projection: it is recomputed and reflected when the center is fetched or listed rather than being eagerly updated as enrollments change, and recomputing it does not by itself increment the center's `version` or refresh its `updated_at` (it is exempt from the versioned-derived-field rule of §2.4). The `territory_code` is stored as an uppercase string and must be unique across all centers; an attempt to create a center with a `territory_code` another center already uses is rejected with `ERR_TERRITORY_CONFLICT`.

Before a center can operate, it needs a franchise agreement. Creating a `FranchiseAgreement` names the `center_id` it governs (one agreement per center is the intended model, but the create endpoint does not itself reject a second agreement for the same center — the center-activation and royalty rules simply key on the center's `ACTIVE` agreement) and records the royalty terms: a `royalty_rate_bps` applied to collected tuition (defaulting to 1000 basis points, constrained to the inclusive range 0 through 10000), a `marketing_fee_bps` national marketing fee on collected tuition (defaulting to 200 basis points, same range), a `minimum_monthly_royalty_cents` floor (defaulting to 50000, never negative), and a `royalty_basis` selector that chooses how the floor interacts with the fees. The `royalty_basis` is either `ROYALTY_FLOOR` (the default) or `COMBINED_FLOOR`; its effect on the royalty calculation is described in §3.7. A new agreement begins in `PENDING` status.

Activating a pending agreement moves it from `PENDING` to `ACTIVE`, but only when the sum of `royalty_rate_bps` and `marketing_fee_bps` is at most 10000 basis points; if the two rates together exceed 10000, activation is rejected with `ERR_ROYALTY_RATE_INVALID`. Activation increments the agreement's `version`.

Bringing a center online transitions it from `PROVISIONING` to `OPERATING`; the same operation also returns a `SUSPENDED` center to `OPERATING`. Either way, the center may enter `OPERATING` only when a franchise agreement naming that center exists and is in `ACTIVE` status — otherwise the activation is rejected with `ERR_AGREEMENT_NOT_ACTIVE` — and the transition increments the center's `version`. Suspending an operating center moves it from `OPERATING` to `SUSPENDED` and triggers the session-and-attendance cascade described in §2.5, incrementing the center's `version`. An agreement may be wound down from `ACTIVE` to `TERMINATED`, but only when the center it backs is not currently `OPERATING`; terminating the agreement of an operating center is rejected with `ERR_CENTER_OPERATING`, since a terminated agreement may not back an operating center. Termination is terminal and increments the agreement's `version`.

### 3.2. Subjects and the Curriculum-Level DAG

A `FranchiseAdmin` defines what a center teaches. Creating a `Subject` records its `center_id`, a human `name` (such as MATH or READING), and a short `code` that must be unique among the subjects of that same center; an attempt to reuse a `code` already taken by another subject of the same center is rejected as a well-formedness violation with `ERR_INVALID_REQUEST` (422). Subjects are created `ACTIVE` and remain `ACTIVE` in this version of the system.

Within a subject, the admin lays out an ordered ladder of curriculum levels. Creating a `CurriculumLevel` records its `subject_id`, an integer `rank` (1 is the lowest; ranks are at least 1 and unique within a subject — reusing a `rank` already held by another level of the same subject is rejected as a well-formedness violation with `ERR_INVALID_REQUEST`, 422), a human `label` (such as "A", "B", or "3A"), the `worksheets_to_master` count of distinct worksheet sets that must reach mastery to advance past the level (defaulting to 10, at least 1), and the `mastery_score_threshold` — the minimum worksheet score, between 0 and 100 inclusive, that counts as a pass toward mastery (defaulting to 80). Each level may also name a `prereq_level_id`, the immediately-lower prerequisite level; the entry level has no prerequisite and leaves `prereq_level_id` null. These links form a self-referential directed acyclic graph of prerequisites. A `prereq_level_id` must reference a level in the same subject whose `rank` is strictly lower than the new level's `rank`, and it must not introduce a cycle into the prerequisite graph; a violation of either condition is rejected with `ERR_PREREQ_CYCLE`. Levels can be listed and filtered by `subject_id`, or filtered by `prereq_level_id` to find the levels that name a given level as their prerequisite.

### 3.3. Families, Students, and Diagnostic Placement

A family account anchors billing. Creating a `Family` records its home `center_id` for billing, a `contact_email` used as the parent login, and the guardian's `contact_name`. A new family opens with `wallet_credit_cents` at 0 and `sibling_count` at 0. The `wallet_credit_cents` is an account credit accumulated from refunds and voids and later applied against invoices; the `sibling_count` is the number of students in the family with at least one active enrollment, which drives the sibling discount. An operator may adjust a family's wallet directly through a goodwill credit, supplying an `amount_cents` delta and a `reason`; the adjustment adds `amount_cents` to `wallet_credit_cents` (the amount may be negative, but the resulting balance is floored at 0) and increments the family's `version`.

Each child is a `Student` under a family, created with a `family_id`, a `full_name`, and a `birthdate` recorded as an ISO 8601 datetime. A new student carries `enrollment_fee_charged` set to false; this flag flips to true the first time the student is placed (its enrollment activated through placement), which is when the one-time enrollment fee is staged for billing, and once true it is never set back to false. The flag marks that the fee has been staged; whether the fee actually lands on a given invoice is governed separately by the per-invoice billing rule of §3.7.

Enrolling a student in a subject creates an `Enrollment` referencing the `center_id`, the `student_id`, and the `subject_id`, optionally carrying an initial `diagnostic_raw_score`. A new enrollment begins in `PLACEMENT_PENDING` status with its computed `monthly_rate_cents` at 0; its `placement_level_id` and `current_level_id` are not yet set. Placement is the act of running the diagnostic and activating the enrollment, transitioning it from `PLACEMENT_PENDING` to `ACTIVE`. The placement request may carry a `diagnostic_raw_score` and a `placement_policy` selecting the placement variant; `placement_policy` defaults to `STRICT` when omitted, and any value other than `STRICT` or `SUPPORTIVE` is rejected with `ERR_INVALID_REQUEST` (422). When a `diagnostic_raw_score` is supplied in the placement body it is used and persisted onto the enrollment even if the enrollment already carried a score (the body value takes precedence); when the body omits it, the enrollment's existing `diagnostic_raw_score` is used. A score supplied in the body is range-checked to 0 through 100 as a well-formedness rule (`ERR_INVALID_REQUEST`, 422) before the state and business gates run. Placement may proceed only when the enrollment's center is `OPERATING` (otherwise `ERR_CENTER_NOT_OPERATING`), a `diagnostic_raw_score` between 0 and 100 is present (otherwise `ERR_DIAGNOSTIC_MISSING`), and the level chosen by the diagnostic belongs to the enrollment's `subject_id` (otherwise `ERR_LEVEL_SUBJECT_MISMATCH`); the state-machine guard requiring the enrollment to be in `PLACEMENT_PENDING` (else `ERR_INVALID_STATE`) is evaluated before these three cross-entity checks.

The diagnostic determines the starting level from the score. Take the curriculum levels belonging to the enrollment's `subject_id`, sorted by `rank` ascending and breaking any tie by `created_at` ascending, and let N be how many such levels there are. Compute a band width as 100 divided by N, rounded up to the next whole number. Compute a target index as the score divided by that band width, rounded down to a whole number, then capped so it is no greater than N minus 1; this index is zero-based into the rank-sorted list. Under the default `STRICT` policy, the placement level is exactly the level at the target index. Under the `SUPPORTIVE` policy, the placement level is the level one position below the target index — that is, at the index obtained by subtracting 1 from the target index but never going below 0 — so that for the same `diagnostic_raw_score`, `SUPPORTIVE` lands a student a level lower than `STRICT` whenever the target index is greater than 0, and on the same entry level otherwise. The chosen level fills both `placement_level_id` and the working `current_level_id`.

Activating an enrollment through placement also runs the fee-and-discount machinery: the student's `enrollment_fee_charged` is examined and, if still false, set true and the enrollment fee staged for the next invoice; the family's `sibling_count` is recomputed; and the sibling discount is re-run across every active enrollment of every student in the family, so each affected enrollment's `monthly_rate_cents` is recomputed by the tuition calculation of §3.6. The enrollment's `version` is incremented. A center director may later pause an active enrollment (`ACTIVE` to `PAUSED`), resume a paused one (`PAUSED` to `ACTIVE`, which again requires the center to be `OPERATING`, else `ERR_CENTER_NOT_OPERATING`), or withdraw an enrollment from `ACTIVE`, `PAUSED`, or `PLACEMENT_PENDING` to the terminal `WITHDRAWN`. Pausing, resuming, and withdrawing each recompute the family's `sibling_count` and re-derive `monthly_rate_cents` for the still-active enrollments in the family, and each increments the enrollment's `version`. A paused enrollment no longer counts toward the sibling discount. When an enrollment is withdrawn, its worksheets in `ASSIGNED`, `GRADED`, or `RETRY` status are not advanced to any new state — their status is left unchanged but no further grading is permitted on them — while every future booking of that enrollment (an `AttendanceRecord` in `BOOKED` status on a session whose `start_at` is after the current logical clock) is driven to `CANCELLED`, each such cancellation recomputing the affected session's `booked_seat_count`.

The progress report for an enrollment surfaces its current level, its `mastered_sets_in_level`, and the per-level mastered counts, all derived from the worksheet history described next. Concretely, the report's `data` is the full enrollment resource object (its `current_level_id`, `mastered_sets_in_level`, and every other enrollment field) augmented with a `per_level_mastered_counts` field: an object keyed by `level_id`, whose value for each level is the number of distinct `set_number` values among the enrollment's worksheets in `MASTERED` status that target that level. Levels with no mastered sets do not appear as keys.

### 3.4. Worksheet Progression, Mastery, and Advancement

A worksheet set is the unit of practice. Assigning one creates a `Worksheet` referencing the `enrollment_id` it belongs to, the `level_id` it targets, and a `set_number` (a sequential index within the level, at least 1). The set begins with `status` of `ASSIGNED`, a null `score`, and an `attempt_count` of 0. The targeted `level_id` must belong to the enrollment's subject; a mismatch is rejected with `ERR_LEVEL_SUBJECT_MISMATCH`. Worksheets can be listed and filtered by `enrollment_id` or `level_id`.

Grading is the engine of progression and follows a cycle. An instructor grades an assigned set by supplying a `score`; this is allowed only when the parent enrollment is `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`) and the `score` lies between 0 and 100 inclusive (otherwise `ERR_SCORE_OUT_OF_RANGE`). Grading records the `score`, increments `attempt_count` by one, moves the set from `ASSIGNED` to `GRADED`, and increments the worksheet's `version`. Immediately after grading, the system resolves the graded set: if the `score` is greater than or equal to the targeted level's `mastery_score_threshold`, the set advances from `GRADED` to `MASTERED`; otherwise it moves from `GRADED` to `RETRY`. A set that reaches `RETRY` can be reassigned by an instructor — again requiring the parent enrollment to be `ACTIVE`, else `ERR_ENROLLMENT_NOT_ACTIVE` — which returns it from `RETRY` to `ASSIGNED`, resets its `score` to null so the next grade re-attempts the same `set_number`, and increments its `version`.

When a set reaches `MASTERED`, the advancement evaluation runs in a pinned order. First, recompute `mastered_sets_in_level` as the count of distinct `set_number` values among the enrollment's worksheets whose status is `MASTERED` and whose `level_id` equals the enrollment's `current_level_id`. Second, take the current level and read its `worksheets_to_master` and `rank`. Third, only if `mastered_sets_in_level` is greater than or equal to the current level's `worksheets_to_master`, look for the next level — the level in the same subject with the smallest `rank` strictly greater than the current level's `rank`, breaking ties by `created_at` ascending. If such a next level exists, set `current_level_id` to it and then re-run the first step against the new level, so `mastered_sets_in_level` becomes the count of distinct mastered sets already sitting in the new level. If no higher level exists and the mastery target has been met, the enrollment moves from `ACTIVE` to the terminal `COMPLETED`. The evaluation order is strict: count mastery, compare to the threshold, and only then advance and recompute against the new level. Each MASTERED resolution increments the worksheet's `version`, and a level advancement or completion is itself a versioned mutation of the enrollment with `mastered_sets_in_level` and, where applicable, `current_level_id` and `status` updated.

Completion may also be reached directly: when an active enrollment's `current_level_id` is already the highest-rank level for its subject (no level of greater rank exists) and `mastered_sets_in_level` is at least that level's `worksheets_to_master`, the enrollment transitions from `ACTIVE` to `COMPLETED`. As with every enrollment status change, completion recomputes the family's `sibling_count` and the `monthly_rate_cents` of the still-active enrollments across the family, and increments the enrollment's `version`.

### 3.5. Sessions, Attendance, and Capacity

A center director schedules tutoring time by creating a `Session` at a `center_id` for a named instructor. The session records the `instructor_user_id` staffing it (the opaque identifier of the acting instructor, retained for audit), a `start_at` and an `end_at` (ISO 8601 UTC instants, with `end_at` required to be strictly after `start_at`), and a `seat_cap`. The `seat_cap` is the maximum number of seats and must be between 1 and the center's `instructor_ratio_cap` inclusive; a `seat_cap` exceeding the center's `instructor_ratio_cap` is rejected with `ERR_RATIO_EXCEEDED`. A new session begins `SCHEDULED` with `booked_seat_count` at 0, where `booked_seat_count` is the number of attendance records on the session whose status is `BOOKED` or `PRESENT`.

Scheduling also guards against double-booking an instructor. A new session may not be created for the same `instructor_user_id` at the same center when the new session's interval, expanded by a thirty-minute buffer on each side — that is, the closed window running from thirty minutes before its `start_at` to thirty minutes after its `end_at` — overlaps the unexpanded interval of any existing session staffed by that instructor whose status is `SCHEDULED`, `OPEN`, or `CLOSED` (cancelled sessions are ignored). Because the buffer is thirty minutes, two of an instructor's sessions falling within thirty minutes of each other count as a conflict; such a collision is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`.

A session opens for booking when a director moves it from `SCHEDULED` to `OPEN`, which is permitted only while the center is `OPERATING` (otherwise `ERR_CENTER_NOT_OPERATING`) and increments the session's `version`. A director closes a session from `OPEN` to `CLOSED`, permitted only once the logical clock has reached or passed the session's `start_at` (otherwise `ERR_SESSION_NOT_STARTED`); on close, every attendance record still in `BOOKED` status is driven to `ABSENT` with its `marked_at` set to the current clock, and the session's `version` is incremented. A director may cancel a session from either `SCHEDULED` or `OPEN` to `CANCELLED` (the system performs the same cancellation when a center is suspended); cancelling drives every attendance record in `BOOKED` or `PRESENT` status to `CANCELLED`, resets `booked_seat_count` to 0, and increments the session's `version`.

Booking a seat creates an `AttendanceRecord` referencing the `session_id` and the `enrollment_id` taking the seat, and carrying `expected_session_version` for the concurrency check of §2.7. A booking is permitted only while the target session is in `SCHEDULED` or `OPEN` status; a booking against a session in any other status (for example `CLOSED` or `CANCELLED`) is rejected by the state-machine guard with `ERR_INVALID_STATE`, which runs at priority six — after the optimistic-concurrency check and before the seat-capacity and overlap rules. A booking begins in `BOOKED` status, increments the session's `booked_seat_count`, and increments the session's `version`. A booking is refused when it would push `booked_seat_count` above the session's `seat_cap`, in which case it is rejected with `ERR_RATIO_EXCEEDED`. A booking is also refused when the same enrollment already holds a `BOOKED` or `PRESENT` record at the same center on a session whose time overlaps the new one: intervals are half-open `[start_at, end_at)`, so two sessions that merely touch (one's `end_at` equal to the other's `start_at`) do not overlap, but any true overlap is rejected with `ERR_SESSION_OVERLAP`. An attendance record also carries a `marked_at` timestamp that is null until presence or absence is recorded.

An instructor resolves a booked seat at the session. Each of these record transitions first applies the state-machine guard against the record itself: the record must be in `BOOKED` status, and a record in any other status is rejected with `ERR_INVALID_STATE`. Checking in moves a record from `BOOKED` to `PRESENT` and sets `marked_at` to the current clock, permitted only while the parent session is `OPEN` (otherwise `ERR_SESSION_NOT_OPEN`); it increments the record's `version`. Marking absent moves a record from `BOOKED` to `ABSENT`, sets `marked_at`, recomputes the session's `booked_seat_count` (an absent seat no longer counts), and increments the record's `version`; this is permitted while the parent session is `OPEN` or `CLOSED`, with a parent session in any other status rejected as `ERR_INVALID_STATE`, and is also what the system applies to leftover booked seats when a session closes. A booking may be cancelled from `BOOKED` to `CANCELLED` by a director or the booking parent; cancelling recomputes the session's `booked_seat_count` to free the seat and increments the record's `version`. Attendance records can be listed and filtered by `session_id` or `enrollment_id`.

### 3.6. Tuition Rate: Multi-Subject and Sibling Discounts

The per-enrollment `monthly_rate_cents` is recomputed whenever a family's active-enrollment picture changes — on placement, pause, resume, withdrawal, or completion — and is also relied upon when an invoice is drafted. It begins from the center's base `monthly_tuition_cents` and is reduced by two discounts applied multiplicatively in a pinned order: the multi-subject discount first, then the sibling discount.

The multi-subject discount keys on this enrollment's position among the same student's active enrollments. Order that student's active enrollments by `created_at` ascending — ties are broken by `created_at` alone and never by `id` — and let the subject index be this enrollment's one-based position in that ordering. The first such enrollment receives no multi-subject discount; the second receives a 10 percent discount; the third and any beyond receive a 15 percent discount.

The sibling discount keys on the family's `sibling_count`, the number of students in the family with at least one active enrollment. A `sibling_count` of one or fewer earns no sibling discount; a `sibling_count` of exactly two earns a 5 percent discount; a `sibling_count` of three or more earns a 10 percent discount.

The two discounts are applied in sequence with flooring after each step. First, take the base `monthly_tuition_cents`, multiply by one minus the multi-subject discount fraction, and floor to a whole cent. Then take that intermediate amount, multiply by one minus the sibling discount fraction, and floor again to a whole cent; the result is the enrollment's `monthly_rate_cents`. The flooring happens after the multi-subject step and again after the sibling step — never as a single rounding at the end — and the multi-subject step always precedes the sibling step.

### 3.7. Billing: Invoices, Wallet, Payment, and Royalty

A center director drafts a monthly bill by creating an `Invoice` for a family. The create names the billed `family_id`, the `center_id` whose tuition is billed, the `period_month` the invoice covers (formatted "YYYY-MM"), and `expected_family_version` for the concurrency guard of §2.7. A new invoice opens in `DRAFT` status. On creation the system computes the two billable components over the active enrollments whose `center_id` matches the invoice's `center_id` and whose student belongs to the invoice's `family_id` (an enrollment counts toward the components only while its status is exactly `ACTIVE`; `PAUSED` enrollments are excluded): the `enrollment_fee_component_cents` is the sum, over the students newly charged on this invoice, of the center's `enrollment_fee_cents`, and the `tuition_component_cents` is the sum of those enrollments' `monthly_rate_cents`. A distinct student is "newly charged" on this invoice when that student has at least one such active enrollment, the student's `enrollment_fee_charged` flag is true (so the fee was staged at placement), and the student's fee has not already been placed on any prior non-`VOID` invoice of this family; the fee contributes the center's `enrollment_fee_cents` exactly once per such student. The student identifiers whose fee this invoice charges are recorded on the invoice, so a subsequent invoice for the same family will not re-charge them — unless this invoice is later voided, which releases the charges it had recorded and lets them recur on a future invoice. Drafting the invoice advances the family's `version` as the optimistic-concurrency parent. A draft invoice's `wallet_applied_cents`, `total_due_cents`, and `royalty_owed_cents` remain at 0 until later stages pin them.

Issuing an invoice moves it from `DRAFT` to `ISSUED` and pins the wallet and total. It may be issued only when there is something to bill — the sum of `tuition_component_cents` and `enrollment_fee_component_cents` is greater than 0 — otherwise it is rejected with `ERR_EMPTY_INVOICE`. The invoice total is computed by summing the integer per-line components first and only then applying the wallet: let the gross be `enrollment_fee_component_cents` plus `tuition_component_cents`; the `wallet_applied_cents` is the smaller of the family's `wallet_credit_cents` and that gross; and the `total_due_cents` is the gross minus `wallet_applied_cents`, which is never negative. Issuing is also the moment the wallet credit is reserved: the pinned `wallet_applied_cents` is deducted from the family's `wallet_credit_cents` at issue time (the balance is floored at 0), which is the conserved balance that a later void of the issued invoice refunds. Issuing increments the invoice's `version`, and when the wallet deduction is non-zero it also increments the family's `version`.

Paying an issued invoice moves it from `ISSUED` to `PAID`. The payment request supplies an `amount_cents`, which must be present and a non-negative integer (otherwise the well-formedness gate rejects it with `ERR_INVALID_REQUEST`, 422) and must equal the invoice's pinned `total_due_cents` exactly; any other non-negative amount is rejected by the business rule with `ERR_PAYMENT_AMOUNT_MISMATCH`. The wallet was already deducted from the family's `wallet_credit_cents` when the invoice was issued, so payment does not deduct the wallet again and does not mutate the family. On payment, the royalty owed on the invoice is computed and stored in `royalty_owed_cents` (using the center's `ACTIVE` agreement; if no such agreement exists, `royalty_owed_cents` is left at 0), and the invoice's `version` is incremented.

The royalty calculation runs over the invoice's `tuition_component_cents` only — the enrollment-fee portion is not royalty-bearing — using the single franchise agreement whose `center_id` matches the invoice's `center_id` and whose status is `ACTIVE`. Compute a percentage royalty as `tuition_component_cents` multiplied by `royalty_rate_bps`, divided by 10000, floored to a whole cent. Compute a marketing amount as `tuition_component_cents` multiplied by `marketing_fee_bps`, divided by 10000, floored to a whole cent. The agreement's `royalty_basis` then selects how the `minimum_monthly_royalty_cents` floor applies. Under `ROYALTY_FLOOR`, the floor applies to the percentage royalty alone: `royalty_owed_cents` is the greater of the percentage royalty and `minimum_monthly_royalty_cents`, plus the marketing amount. Under `COMBINED_FLOOR`, the floor applies to the percentage royalty and marketing combined: `royalty_owed_cents` is the greater of (the percentage royalty plus the marketing amount) and `minimum_monthly_royalty_cents`. For identical tuition the two variants diverge whenever the percentage royalty is below the minimum and the marketing amount is above zero.

An invoice may be voided from either `DRAFT` or `ISSUED` to the terminal `VOID`. If the invoice had already been issued, voiding refunds its `wallet_applied_cents` back to the family's `wallet_credit_cents`, restoring the conserved wallet balance the issue had reserved; a void from `DRAFT` makes no wallet change because nothing was reserved. Voiding increments the invoice's `version`. Invoices can be listed and filtered by `family_id` or `center_id`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions, wallet adjustments, and the clock control — return `200 OK`. All read operations return `200 OK`. Every endpoint requires the authentication headers of §2.1, and access is further constrained to the authorized roles below; reads by a `CenterDirector`, `Instructor`, or `Parent` are additionally scoped to their own center or family.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an absolute UTC instant | FranchiseAdmin |
| POST | `/centers` | Create a center | FranchiseAdmin |
| GET | `/centers/{center_id}` | Get center details | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/centers` | List centers | FranchiseAdmin |
| POST | `/centers/{center_id}/activate` | Activate a center (to OPERATING) | FranchiseAdmin |
| POST | `/centers/{center_id}/suspend` | Suspend a center | FranchiseAdmin |
| POST | `/franchise-agreements` | Create a franchise agreement | FranchiseAdmin |
| GET | `/franchise-agreements/{agreement_id}` | Get an agreement | FranchiseAdmin, CenterDirector |
| GET | `/franchise-agreements` | List/filter agreements | FranchiseAdmin, CenterDirector |
| POST | `/franchise-agreements/{agreement_id}/activate` | Activate an agreement | FranchiseAdmin |
| POST | `/franchise-agreements/{agreement_id}/terminate` | Terminate an agreement | FranchiseAdmin |
| POST | `/subjects` | Create a subject | FranchiseAdmin |
| GET | `/subjects/{subject_id}` | Get a subject | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/subjects` | List/filter subjects | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/curriculum-levels` | Create a curriculum level | FranchiseAdmin |
| GET | `/curriculum-levels/{level_id}` | Get a curriculum level | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/curriculum-levels` | List/filter curriculum levels | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/families` | Create a family | FranchiseAdmin, CenterDirector |
| GET | `/families/{family_id}` | Get a family | FranchiseAdmin, CenterDirector, Parent |
| GET | `/families` | List/filter families | FranchiseAdmin, CenterDirector |
| POST | `/families/{family_id}/wallet-adjustments` | Adjust a family wallet | FranchiseAdmin, CenterDirector |
| POST | `/students` | Create a student | FranchiseAdmin, CenterDirector, Parent |
| GET | `/students/{student_id}` | Get a student | FranchiseAdmin, CenterDirector, Parent, Instructor |
| GET | `/students` | List/filter students | FranchiseAdmin, CenterDirector, Parent, Instructor |
| POST | `/enrollments` | Create an enrollment | FranchiseAdmin, CenterDirector |
| GET | `/enrollments/{enrollment_id}` | Get an enrollment | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/enrollments` | List/filter enrollments | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/enrollments/{enrollment_id}/place` | Run diagnostic placement and activate | CenterDirector |
| POST | `/enrollments/{enrollment_id}/pause` | Pause an enrollment | CenterDirector |
| POST | `/enrollments/{enrollment_id}/resume` | Resume an enrollment | CenterDirector |
| POST | `/enrollments/{enrollment_id}/withdraw` | Withdraw an enrollment | CenterDirector |
| GET | `/enrollments/{enrollment_id}/report` | Get a mastery/advancement report | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/worksheets` | Assign a worksheet set | CenterDirector, Instructor |
| GET | `/worksheets/{worksheet_id}` | Get a worksheet set | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/worksheets` | List/filter worksheets | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/worksheets/{worksheet_id}/grade` | Grade a worksheet set | Instructor |
| POST | `/worksheets/{worksheet_id}/reassign` | Reassign a failed worksheet set | Instructor |
| POST | `/sessions` | Schedule a session | CenterDirector |
| GET | `/sessions/{session_id}` | Get a session | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/sessions` | List/filter sessions | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/sessions/{session_id}/open` | Open a session for booking | CenterDirector |
| POST | `/sessions/{session_id}/close` | Close a session | CenterDirector |
| POST | `/sessions/{session_id}/cancel` | Cancel a session | CenterDirector |
| POST | `/attendance-records` | Book a seat | CenterDirector, Parent |
| GET | `/attendance-records/{record_id}` | Get an attendance record | FranchiseAdmin, CenterDirector, Instructor, Parent |
| GET | `/attendance-records` | List/filter attendance records | FranchiseAdmin, CenterDirector, Instructor, Parent |
| POST | `/attendance-records/{record_id}/check-in` | Mark present | Instructor |
| POST | `/attendance-records/{record_id}/mark-absent` | Mark absent | Instructor |
| POST | `/attendance-records/{record_id}/cancel` | Cancel a booking | CenterDirector, Parent |
| POST | `/invoices` | Create a draft invoice | CenterDirector |
| GET | `/invoices/{invoice_id}` | Get an invoice | FranchiseAdmin, CenterDirector, Parent |
| GET | `/invoices` | List/filter invoices | FranchiseAdmin, CenterDirector, Parent |
| POST | `/invoices/{invoice_id}/issue` | Issue an invoice | CenterDirector |
| POST | `/invoices/{invoice_id}/pay` | Pay an invoice | Parent, CenterDirector |
| POST | `/invoices/{invoice_id}/void` | Void an invoice | CenterDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_SCORE_OUT_OF_RANGE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_CENTER_OPERATING` | 409 |
| `ERR_CENTER_NOT_OPERATING` | 409 |
| `ERR_ROYALTY_RATE_INVALID` | 409 |
| `ERR_TERRITORY_CONFLICT` | 409 |
| `ERR_DIAGNOSTIC_MISSING` | 409 |
| `ERR_LEVEL_SUBJECT_MISMATCH` | 409 |
| `ERR_PREREQ_CYCLE` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_RATIO_EXCEEDED` | 409 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_SESSION_NOT_STARTED` | 409 |
| `ERR_EMPTY_INVOICE` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 |
