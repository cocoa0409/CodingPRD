# Language School ESL API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Language School ESL API, the operational backbone of a multi-track English-as-a-Second-Language institution that serves both self-paying learners and internationally sponsored students. The platform must reconcile three traditionally siloed concerns into a single coherent system: the academic journey (placement testing, level assignment, cohort scheduling, attendance, progress assessment, and certification), the financial relationship (tuition invoicing, volume discounts for corporate sponsors, supplementary product fees, and withdrawal refunds), and the regulatory burden that attaches to international students who study on an F-1 visa under an issued I-20.

The defining tension the API resolves is compliance. For an international student, enrollment is not merely a commercial transaction; it is a representation to immigration authorities that the student is pursuing a full course of study. The institution's Designated School Official (DSO) is accountable for that representation, and the system must therefore treat visa posture as a first-class, audited dimension that gates academic actions, cascades automatically when a student's enrollment footprint changes, and leaves an append-only trail of every compliance action taken. Simultaneously, cohort seats and corporate-contract seats are finite, contended resources: the system must allocate them under concurrency, reserve them on enrollment, and release them on every departure path so that waitlisted students bubble up fairly.

A product manager reading this document should understand that almost every interesting rule here lives at the intersection of two entities — a withdrawal touches the enrollment, the cohort's seat count, the waitlist, the corporate contract, and possibly the student's visa standing, all within one atomic request. The sections below describe those interactions in business terms; the engineering contract (envelopes, status codes, concurrency tokens) is fixed in §2 and must be honored exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to an authenticated endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request that is missing either header, or that supplies a malformed value, on an endpoint that requires authentication is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Registrar`, `DSO`, `Instructor`, `Student`, `CorporateSponsor`, and `Anonymous`.

The `Registrar` owns the cohort and enrollment lifecycle: creating cohorts and enrollments, confirming placements, withdrawing and completing enrollments, voiding placement tests, and creating and closing corporate contracts. The `DSO` (Designated School Official) owns the I-20 and F-1 visa lifecycle: issuing the I-20, activating, placing on probation, clearing probation, and terminating visa status, as well as terminating an individual enrollment. The `Instructor` owns instructional records: scoring placement tests, recording attendance, and recording progress assessments. The `Anonymous` role represents unauthenticated public callers and is permitted only to self-register a student and to register a placement test.

For the `Registrar`, `DSO`, `Instructor`, and `Anonymous` roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in a free-text justification field where a transition writes one (for example, the `reason` captured on a compliance action), but it does not compare it against any entity's `id`.

The `Student` and `CorporateSponsor` roles are ownership-bound. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a `Student` compare that resource's student foreign key to `X-User-ID`. A `Student` may register and cancel their own add-on subscriptions, register their own placement tests, and read their own student record, enrollments, add-ons, placement tests, attendance, and progress reports. When `X-User-Role` is `CorporateSponsor`, `X-User-ID` is the `id` of the acting `CorporateContract`; ownership checks on any resource that references a contract compare that resource's contract foreign key to `X-User-ID`. A `CorporateSponsor` may read only its own contract and the students that contract sponsors. When an ownership-bound role acts on a resource it does not own, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A request whose `limit` falls outside 1 through 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit Fields

Most resources in the system carry a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it underpins optimistic concurrency control as described in §2.7.

Two entities are deliberate exceptions to this convention: the `AttendanceRecord` and the `ComplianceEvent`. These are append-only records that are never modified after creation. Each therefore carries only an `id` (UUID) and a `created_at` timestamp; both `updated_at` and `version` are absent on these two entities. The `ComplianceEvent` in particular forms an immutable audit log of every visa action taken against a student.

It is important to distinguish the wall-clock audit fields above from the system's **logical clock**. Several timestamps that drive business calculations — `enrolled_at`, `recorded_at`, `assessed_at`, the refund-week computation, and the completion time-gate — are read from a logical clock, not from real time. The logical clock starts at exactly `2026-04-01T00:00:00Z` and reads that default on every access until it is explicitly set; before any set call it never falls back to wall-clock time. An administrative capability allows an operator to advance the logical clock to a supplied UTC instant — provided as `to_iso8601` in the request body — for deterministic, time-gated workflows, after which every subsequent logical-clock read uses that instant.

### 2.5. Precision, Rounding, and Monetary Representation

All monetary amounts in the system are expressed as integer counts of cents (for example `base_tuition_cents`, `tuition_invoice_cents`, `refund_cents`, `fee_cents`). Wherever a calculation introduces a fractional cent — a percentage discount, a percentage surcharge, or a fractional refund tier — the result is rounded using the **round half up** method to a whole number of cents. Each calculation section below specifies the exact point at which rounding is applied, because the rounding point is load-bearing: rounding a component versus rounding the final total can differ by a cent. Scores that are rounded (the placement band is a pure integer comparison; the completion and certification scores round half up) follow the same round-half-up convention at the points named in §3.

### 2.6. Seat Allocation, Cascades, and State Consistency

Cohort seats and corporate-contract seats are finite resources tracked by computed counters. A `Cohort` exposes `seats_taken`, the count of enrollments currently in `ENROLLED` state, and a derived `status` of `OPEN` while `seats_taken` is below `capacity` or `FULL` once `seats_taken` equals `capacity`. A `CorporateContract` exposes `seats_consumed`, the count of currently `ENROLLED` enrollments whose student it sponsors, and a derived `status` that is `ACTIVE` while seats remain, `EXHAUSTED` once `seats_consumed` equals `contracted_seats`, or `CLOSED` once the contract is closed.

Whenever an enrollment enters or leaves the `ENROLLED` state, the system updates these counters and any dependent derived state atomically within the same request. Because counters live on the cohort, the contract, and the student's visa dimension, a single enrollment transition can cascade across all three. Every entity touched by such a cascade has its `updated_at` refreshed and its `version` incremented as part of the same atomic operation. The system performs these reconciliations automatically; a client never issues a separate request to release a seat or to flip a cohort from `FULL` back to `OPEN`. The specific cascades — seat release, waitlist promotion, visa probation, visa termination, and certification voiding — are described in the workflow narratives of §3.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control keyed on a parent entity's `version`. These are the only two endpoints that accept a version token; every other write operation ignores versioning entirely and takes no version field.

The first guarded operation is confirming a placement-pending enrollment. The confirm request must carry `expected_cohort_version` carrying the client's last observed `version` of the target `Cohort`. If the cohort's `version` has advanced since the client last read it — for instance because another confirm has already consumed the last remaining seat and thereby legitimately superseded this client's stale view of remaining capacity — the request is rejected with `ERR_STALE_COHORT_VERSION` (HTTP 412). This is a stale-version check on the cohort, not a timing artifact: the rejection fires purely because the supplied `expected_cohort_version` no longer matches the live cohort `version`, preventing the client from acting on capacity it never observed.

The second guarded operation is closing a corporate contract. The close request must carry `expected_contract_version` carrying the client's last observed `version` of the target `CorporateContract`. If the contract's `version` has advanced since the client last observed it — for instance because another writer enrolled a sponsored student, drawing down a seat and bumping the contract version — then the closer's view of which enrollments the close cascade will revoke is stale, and the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).

### 2.8. Nested Resource Retrieval and Validation Ordering

Many read endpoints address a resource by walking a path that names a parent and then a collection, such as a student's enrollments or a cohort's enrollments. For any request that names one or more resource identifiers, the system validates existence left to right, in path order first and then for any foreign keys named in the body. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in that order that does not correspond to an existing resource.

The complete validation pipeline that guards mutating endpoints is strictly ordered, and the order is observable because an earlier failure masks a later one. The system evaluates checks in this sequence: first, authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`, 401); second, role permission for the endpoint per the access-control matrix (`ERR_FORBIDDEN`, 403); third, ownership for an ownership-bound role acting on its own resource, where `X-User-ID` must match the owning foreign key (`ERR_FORBIDDEN`, 403); fourth, existence of every referenced resource, validated left to right through the path and then the body (`ERR_NOT_FOUND`, 404); fifth, that the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`, 409). Only after these five gates pass does the system evaluate the endpoint-specific business rules described in §3, and finally field-level input validation. The relative ordering among the business rules that share the confirm endpoint is given explicitly in §3.4.

## 3. Business Logic & Workflows

### 3.1. Students, Sponsorship, and the Placement Journey

A student record is the anchor of the system. Registration captures the student's legal `full_name` and a contact `email`, and may declare whether the student `is_international` (defaulting to false), which program `track` they study in (one of `GENERAL`, `ACADEMIC`, `BUSINESS`, or `EXAM_PREP`, defaulting to `GENERAL`), and an optional `corporate_contract_id` linking the student to a sponsoring contract (null by default, meaning self-pay). Registration is open to the public, so it may be performed anonymously or by a `Registrar`. Email addresses must be unique across all students when compared case-insensitively; a registration whose email collides with an existing student is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). When a `corporate_contract_id` is supplied, it must reference an existing contract; if it does not, the registration is rejected with `ERR_CONTRACT_REQUIRED_FOR_SPONSOR` (HTTP 404). When a contract is set, that student's tuition is billed to the contract and benefits from its discount.

Several student fields are computed by the system rather than supplied. The `placement_level` holds the CEFR level assigned by the student's most recent scored placement test and is one of `A1`, `A2`, `B1`, `B2`, `C1`, or `C2`, remaining null until a test is scored. The `visa_status` (one of `NONE`, `INITIAL`, `ACTIVE`, `PROBATION`, or `TERMINATED`, defaulting to `NONE` and only meaningful for international students) tracks F-1 posture. The `i20_required_weekly_hours` is a system field holding the minimum weekly instructional hours for a full course of study; it defaults to 0 and is set to 18 when the I-20 is issued. The `certification_status` (one of `NONE`, `PROVISIONAL`, `CERTIFIED`, or `VOIDED`, defaulting to `NONE`) and the `final_progress_score` (a number from 0 to 100, null until certified) capture program certification, derived as described in §3.7.

The placement journey begins with a **placement test**. Anyone permitted — the public, the student themselves, or a `Registrar` — registers a test by supplying the `student_id` of the test-taker, which must reference an existing student. A freshly registered test carries `status` `REGISTERED`, a null `raw_score`, and a null `assigned_level`. An `Instructor` later scores the test by supplying a `raw_score`. Scoring requires that the test currently be in `REGISTERED` state; scoring a test in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). The `raw_score` must be an integer present and within 0 through 100 inclusive; otherwise the request is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Scoring transitions the test `REGISTERED → SCORED`, derives the `assigned_level` from the raw score via the placement bands described in §3.2, and writes that level onto the student's `placement_level`. When a student has more than one scored test, the level from the latest scored test wins, where "latest" means the greatest `recorded_at` logical-clock timestamp, with ties broken by the earlier `created_at` (ascending). Scoring is the only path that ever populates a student's `placement_level`.

Alternatively, a `Registrar` may void a test, transitioning it `REGISTERED → VOIDED`. Voiding also requires the test to be in `REGISTERED` state, and a void makes no change to the student's `placement_level`. Both `SCORED` and `VOIDED` are terminal.

### 3.2. Placement Banding and Cohort Structure

When a placement test is scored, the examiner's integer `raw_score` is mapped to a CEFR band by inclusive lower-bound thresholds. A raw score of at least 90 yields `C2`. A score below 90 but at least 75 yields `C1`. A score below 75 but at least 60 yields `B2`. A score below 60 but at least 45 yields `B1`. A score below 45 but at least 25 yields `A2`. Any score below 25 yields `A1`. The thresholds are inclusive on the lower bound, so a raw score of exactly 60 lands in `B2` while a raw score of 59 lands in `B1`. This banding is the value written to the test's `assigned_level` and propagated to the student's `placement_level`.

A `Registrar` organizes instruction into **cohorts**. A cohort is created with a `name` label, a `level` (the CEFR level it teaches, one of `A1` through `C2`), a `track` (one of `GENERAL`, `ACADEMIC`, `BUSINESS`, `EXAM_PREP`), a `capacity` (the maximum number of simultaneously `ENROLLED` enrollments, an integer of at least 1), a `weekly_hours` figure (instructional hours delivered per week, an integer of at least 1), a `term_start` and a `term_end` (inclusive first and last session dates, where `term_end` must be strictly after `term_start`), a `total_sessions` count (planned class sessions across the term, an integer of at least 1), a `base_tuition_cents` amount (full-term tuition before add-ons and discounts, an integer of at least 0), and a `schedule_block` naming the time-of-day block the cohort meets in (one of `MORNING`, `AFTERNOON`, or `EVENING`). Any cohort field that violates its range or enum, or a `term_end` not strictly after `term_start`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

A cohort's `seats_taken` and `status` are computed, never supplied: `seats_taken` counts current `ENROLLED` enrollments, and `status` reads `OPEN` while `seats_taken` is below `capacity` and `FULL` once they are equal. The `schedule_block` matters beyond display: it is the dimension along which the system detects a student double-booking, as described in §3.4.

### 3.3. Creating and Confirming Enrollments

An **enrollment** is the junction that places one student into one cohort. A `Registrar` first creates the enrollment by supplying the `student_id` and `cohort_id`, both of which must reference existing entities. A new enrollment begins in `PLACEMENT_PENDING` state with a null `enrolled_at`, zero `sessions_attended` and `sessions_elapsed`, an `attendance_rate` of 1.0, a `tuition_invoice_cents` of 0, a `refund_cents` of 0, a null `completion_score`, and a null `termination_reason`.

Confirmation is the pivotal transition, and it forks. A `Registrar` confirms a `PLACEMENT_PENDING` enrollment by supplying `expected_cohort_version` and an optional `require_seat` flag. The confirm always demands that the student's `placement_level` exactly equal the cohort's `level` and the student's `track` exactly equal the cohort's `track`; a mismatch on either is rejected with `ERR_PLACEMENT_MISMATCH` (HTTP 409). The confirm also always demands that the supplied `expected_cohort_version` match the live cohort `version`, failing with `ERR_STALE_COHORT_VERSION` (HTTP 412) as described in §2.7. Every confirm increments the cohort's `version` by one as part of its side effects, whichever branch it takes.

Where the confirm forks is on capacity. When the cohort has a free seat — that is, its `status` is `OPEN` and `seats_taken` is below `capacity` — the enrollment advances `PLACEMENT_PENDING → ENROLLED`. When the cohort is `FULL`, or equivalently when `seats_taken` is at or above `capacity`, the enrollment instead advances `PLACEMENT_PENDING → WAITLISTED`, consuming no seat and parking behind any enrollments already waitlisted on that cohort, ordered first-in-first-out by `created_at` ascending. The `WAITLISTED` branch performs no placement-independent safety checks beyond placement and the version match; it simply parks the student.

The `ENROLLED` branch additionally enforces the compliance and capacity guards. If the student `is_international`, their `visa_status` must be either `INITIAL` or `ACTIVE`; a student whose status is `NONE`, `PROBATION`, or `TERMINATED` cannot be confirmed into an `ENROLLED` seat and the confirm is rejected with `ERR_VISA_NONCOMPLIANT` (HTTP 409). The `ENROLLED` branch also enforces the schedule-conflict guard described in §3.4 and, for sponsored students, the contract-seat guard described in §3.6. Upon a successful `ENROLLED` confirm, the system stamps `enrolled_at` with the current logical clock, computes and pins `tuition_invoice_cents` per §3.6, increments the cohort's `seats_taken` by one (flipping the cohort's `status` to `FULL` if `seats_taken` thereby reaches `capacity`), and, if the student is sponsored, increments the contract's `seats_consumed` by one (flipping the contract's `status` to `EXHAUSTED` if it thereby reaches `contracted_seats`).

When a caller wants to force the `ENROLLED` outcome rather than accept a silent waitlist, they set `require_seat` to true. With `require_seat` set, a confirm against a cohort whose `seats_taken` is at or above `capacity` is treated as an error rather than a waitlist, and is rejected with `ERR_COHORT_FULL` (HTTP 409).

### 3.4. Confirm-Time Check Ordering and Schedule Conflicts

The `ENROLLED` confirm path is guarded by several checks, and the order in which they are evaluated is observable and fixed because an earlier failure preempts a later one. After the universal pipeline of §2.8 (authentication, role permission, ownership, existence, then state — a non-`PLACEMENT_PENDING` target yields `ERR_INVALID_STATE`), the confirm-specific checks are evaluated in this order: first the placement gate (`ERR_PLACEMENT_MISMATCH`), then the F-1 visa gate for international students (`ERR_VISA_NONCOMPLIANT`), then the schedule-conflict check (`ERR_SCHEDULE_CONFLICT`), then the corporate-contract seat check for sponsored students (`ERR_CONTRACT_SEATS_EXHAUSTED`), then the cohort-capacity check that applies when `require_seat` is true (`ERR_COHORT_FULL`), and finally the optimistic-concurrency version check (`ERR_STALE_COHORT_VERSION`). Field-level input validation (`ERR_INVALID_REQUEST`) is the last gate of all.

The **schedule-conflict** rule prevents a student from being double-booked. A confirm into the `ENROLLED` state is rejected with `ERR_SCHEDULE_CONFLICT` (HTTP 409) when the student already holds another `ENROLLED` enrollment whose cohort shares the same `schedule_block` as the target cohort and whose term overlaps the target cohort's term. Overlap is evaluated as a closed-interval test on the two `[term_start, term_end]` ranges: the two terms conflict whenever the earlier term's `term_end` is on or after the later term's `term_start`, so that even terms that merely touch at a shared boundary date are treated as overlapping. Only `ENROLLED` enrollments sharing the same `schedule_block` can conflict; differing blocks never collide.

### 3.5. Attendance, Progress, and the Attendance Rate

Throughout a term, an `Instructor` records attendance one session at a time. Each **attendance record** names the `enrollment_id` it belongs to, a 1-based `session_index` identifying which session of the term it marks, and a `status` of `PRESENT`, `ABSENT`, or `EXCUSED`. The system stamps a `recorded_at` logical-clock timestamp on the record. The `session_index` must be unique within a given enrollment and must fall within 1 through the cohort's `total_sessions`; a record whose index repeats an already-recorded session for that enrollment, or whose index falls outside that range, is rejected with `ERR_DUPLICATE_SESSION` (HTTP 409).

Recording attendance recomputes three derived enrollment fields. The `sessions_attended` is the count of attendance records for the enrollment whose `status` is `PRESENT`. The `sessions_elapsed` is the count of all attendance records for the enrollment, regardless of status. The `attendance_rate` is `sessions_attended` divided by `sessions_elapsed`, expressed as a fraction between 0 and 1; by definition it is exactly 1.0 when no sessions have yet elapsed.

An `Instructor` also records **progress reports** for an enrollment. Each report names its `enrollment_id` and four sub-scores — `speaking`, `listening`, `reading`, and `writing` — each an integer from 0 through 100 inclusive. The system stamps an `assessed_at` logical-clock timestamp on each report. When more than one report exists for an enrollment, the "latest" report is the one with the greatest `assessed_at`, with ties broken by the earlier `created_at` (ascending); that latest report is the one used in the completion scoring of §3.7.

### 3.6. Tuition, Discounts, and Add-On Fees

A student may bundle supplementary products onto an enrollment as **add-on subscriptions**. An add-on names the subscribing `student_id`, the `enrollment_id` it is bundled onto, an `add_on_type` (one of `CONVERSATION_CLUB`, `PRIVATE_TUTORING`, or `IMMERSION_ABROAD`), and a `units` quantity (an integer of at least 1, representing tutoring hours, club weeks, or immersion weeks abroad). A `Student` may create their own add-ons, or a `Registrar` may create them on a student's behalf; the named enrollment must belong to the named student, and if it does not the request is rejected with `ERR_ADDON_ENROLLMENT_MISMATCH` (HTTP 409). A new add-on begins with `status` `ACTIVE`.

The add-on's `fee_cents` is computed at creation from a per-unit rate keyed on the type: a `CONVERSATION_CLUB` unit costs 1,500 cents, a `PRIVATE_TUTORING` unit costs 6,000 cents, and an `IMMERSION_ABROAD` unit costs 40,000 cents. The base fee is the unit rate multiplied by `units`. For `CONVERSATION_CLUB` and `PRIVATE_TUTORING` the fee is exactly that base. For `IMMERSION_ABROAD`, a tiered surcharge applies: the first 2 weeks carry no surcharge, and each additional week beyond the first 2 adds a surcharge of 15 percent of that week's base rate. Concretely, when `units` exceeds 2, the surcharge is the unit rate multiplied by the number of units above 2, multiplied by 0.15, rounded half up to a whole number of cents; when `units` is 2 or fewer, the surcharge is 0. The immersion `fee_cents` is the base plus that surcharge. Rounding is applied once, to the surcharge term.

When an enrollment is confirmed into the `ENROLLED` state, the system computes and pins its `tuition_invoice_cents` in a fixed evaluation order whose steps must be performed exactly as written, because the order is load-bearing to the last cent. First, the system sums the `fee_cents` of every `ACTIVE` add-on bundled onto this enrollment to obtain an add-on total; because each add-on's `fee_cents` was already rounded at creation, this step is a sum of already-rounded integers. Second, it forms a gross amount equal to the cohort's `base_tuition_cents` plus that add-on total. Third, it selects a discount percentage from the student's sponsoring contract's `discount_tier` if the student is sponsored: `BRONZE` yields 0 percent, `SILVER` yields 10 percent, and `GOLD` yields 20 percent; a self-pay student (no `corporate_contract_id`) uses 0 percent. Fourth — and this is the pinned subtlety — the discount in cents is computed by multiplying the cohort's `base_tuition_cents` alone by the discount percentage and rounding that product half up to a whole number of cents; the discount is computed off the base tuition only and never off the add-ons. Fifth, the pinned `tuition_invoice_cents` is the gross amount minus that discount in cents. For a self-pay student this reduces to `base_tuition_cents` plus the add-on total with no discount. The single rounding in this calculation occurs at the fourth step, on the discount alone.

The same tuition computation runs whenever an enrollment enters `ENROLLED`, including when a waitlisted enrollment is later promoted. For **sponsored** confirmations there is an additional gate: a sponsored student can only take an `ENROLLED` seat while the contract has capacity, meaning `seats_consumed` is strictly below `contracted_seats` and the contract is neither `EXHAUSTED` nor `CLOSED`. A sponsored `ENROLLED` confirm against a contract with no remaining seats is rejected with `ERR_CONTRACT_SEATS_EXHAUSTED` (HTTP 409).

### 3.7. Completion, Withdrawal, Termination, and Their Cascades

An enrollment in `ENROLLED` state has three exits, each with a divergent set of side effects.

**Completion.** A `Registrar` completes an enrollment, transitioning `ENROLLED → COMPLETED`. Completion is gated: the current logical clock must be on or after the cohort's `term_end`, the enrollment's `attendance_rate` must be at least 0.70 (the minimum passing attendance), and at least one progress report must exist for the enrollment. If any of these three conditions fails — completing before the term ends, an attendance rate below 0.70, or no progress report on file — the request is rejected with `ERR_COMPLETION_REQUIREMENTS_UNMET` (HTTP 409). On success, the system computes the enrollment's `completion_score`, decrements the cohort's `seats_taken` by one (freeing the seat for waitlist promotion), decrements the sponsoring contract's `seats_consumed` by one if the student is sponsored, and recomputes the student's `certification_status`.

The `completion_score` is a weighted blend of skill and attendance, computed with rounding pinned at three independent steps. First, the system takes the latest progress report (greatest `assessed_at`, ties broken by earlier `created_at`) and computes a skill average as the sum of its `speaking`, `listening`, `reading`, and `writing` sub-scores divided by 4, rounded half up to a whole number. Second, it computes an attendance-points figure as the enrollment's `attendance_rate` multiplied by 100, rounded half up to a whole number. Third, it combines them as 0.7 times the rounded skill average plus 0.3 times the rounded attendance points, and rounds that result half up to a whole number — this is the `completion_score`. The skill average and the attendance points must each be rounded independently before the weighted combine; the system does not combine raw values and round only once at the end, because the two orderings can differ in the last point.

After each completion the student's certification posture is rolled up. The system collects every enrollment of the student that is in `COMPLETED` state and computes `final_progress_score` as the mean of their `completion_score` values, rounded half up to a whole number; this aggregate is order-independent. If the student has completed fewer than 2 enrollments, the `certification_status` is `PROVISIONAL` and `final_progress_score` is the current running mean, which may still move as further enrollments complete. If the student has completed at least 2 enrollments and the rounded mean is at least 70, the `certification_status` is `CERTIFIED` and the `final_progress_score` is frozen at that value. If the student has at least 2 completions but the rounded mean is below 70, the status remains `PROVISIONAL`. The certified and provisional outcomes are computed from the same per-enrollment data; the distinction is purely whether the second completion has crossed both the count-of-2 and the score-of-70 thresholds.

**Withdrawal.** A `Registrar` withdraws an enrolled student, transitioning `ENROLLED → WITHDRAWN`. Withdrawal requires only that the enrollment be in `ENROLLED` state. On withdrawal the system computes `refund_cents`, decrements the cohort's `seats_taken` by one and flips the cohort's `status` from `FULL` back to `OPEN` if it was full, decrements the sponsoring contract's `seats_consumed` by one and flips the contract's `status` from `EXHAUSTED` back to `ACTIVE` if it was exhausted, and promotes the earliest waitlisted enrollment on that cohort if any exists. If the student `is_international` and, after this withdrawal, the student has zero remaining `ENROLLED` enrollments, the system sets the student's `visa_status` to `PROBATION` and appends a `ComplianceEvent` of type `PROBATION_PLACED`; this is the visa-dimension cascade of a withdrawal that empties a student's course load.

The `refund_cents` is the authoritative chronological tiered-schedule refund, computed off the already-pinned net `tuition_invoice_cents` (which already includes add-ons and the discount). First the system computes the whole number of weeks elapsed since the term began: it takes the current logical clock minus the cohort's `term_start`, divides by 7 days, and floors the result to a whole number (so the value is 0 during the first week, 1 during the second, and so on). It then selects a refund fraction from a tiered schedule on that elapsed-week count: 0 weeks elapsed refunds the full amount (fraction 1.00, the withdrawal lands before the first week completes); 1 week elapsed refunds 0.75; 2 or 3 weeks elapsed refunds 0.50; 4 or 5 weeks elapsed refunds 0.25; and 6 or more weeks elapsed refunds nothing (fraction 0.00). The `refund_cents` is the enrollment's pinned `tuition_invoice_cents` multiplied by that fraction, rounded half up to a whole number of cents. The refund is driven entirely by calendar weeks elapsed since `term_start`, independent of how many class sessions actually took place; an alternative reading that would prorate by remaining sessions is explicitly not used and would produce a different value.

**Termination.** A `DSO` terminates an enrollment, transitioning `ENROLLED → TERMINATED`. Termination requires the enrollment to be in `ENROLLED` state and a supplied `termination_reason` that is one of `VISA_NONCOMPLIANCE`, `ATTENDANCE_FAILURE`, or `CONTRACT_REVOKED`; a termination with a missing or out-of-set reason is rejected with `ERR_INVALID_TERMINATION_REASON` (HTTP 422). On termination the system records the `termination_reason`, sets `refund_cents` to 0 (no refund is ever paid on a termination), decrements the cohort's `seats_taken` by one and flips a `FULL` cohort back to `OPEN`, decrements the sponsoring contract's `seats_consumed` by one if sponsored, and promotes the earliest waitlisted enrollment on that cohort if any exists. When and only when the reason is `VISA_NONCOMPLIANCE`, the termination additionally sets the student's `visa_status` to `TERMINATED`, appends a `ComplianceEvent` of type `I20_TERMINATED`, and voids the student's certification by setting `certification_status` to `VOIDED` if it was previously `PROVISIONAL` or `CERTIFIED`.

**Waitlist promotion** is the shared tail of withdrawal, termination, and completion. Whenever a seat frees on a cohort, the system promotes the earliest `WAITLISTED` enrollment on that cohort — the one with the smallest `created_at` — by transitioning it `WAITLISTED → ENROLLED`. Promotion stamps the promoted enrollment's `enrolled_at` with the current logical clock, computes and pins its `tuition_invoice_cents` exactly as a fresh `ENROLLED` confirm would, increments the cohort's `seats_taken` by one, and increments the sponsoring contract's `seats_consumed` by one if the promoted student is sponsored. If the promoted student `is_international`, promotion proceeds only while their `visa_status` is `INITIAL` or `ACTIVE`.

### 3.8. F-1 Visa Lifecycle and the I-20

International students carry a separate visa dimension that the `DSO` administers, and every transition appends an immutable `ComplianceEvent`. Each compliance event records the subject `student_id`, an `event_type` (one of `I20_ISSUED`, `STATUS_ACTIVATED`, `PROBATION_PLACED`, `PROBATION_CLEARED`, or `I20_TERMINATED`), the `prior_status` and `new_status` of the student's `visa_status` bracketing the event, an optional free-text `reason` (the DSO's note, which may be supplied on the action), and a `recorded_at` logical-clock timestamp.

Issuing the I-20 is the entry point: a `DSO` issues the I-20 for an international student, transitioning the student's `visa_status` `NONE → INITIAL`. Issuance requires that the student `is_international` be true and that the current `visa_status` be `NONE`. The issuance sets `i20_required_weekly_hours` to 18 and appends a `ComplianceEvent` of type `I20_ISSUED` (prior `NONE`, new `INITIAL`).

Activating F-1 status transitions the student `INITIAL → ACTIVE`. A `DSO` may activate only when the current `visa_status` is `INITIAL` and the student is meeting a **full course of study** — that is, the sum of `weekly_hours` over the cohorts of the student's currently `ENROLLED` enrollments is at least the student's `i20_required_weekly_hours`. Only enrollments in `ENROLLED` state count toward this sum; enrollments in `PLACEMENT_PENDING`, `WAITLISTED`, or any terminal state are excluded. The boundary is inclusive: a student whose enrolled weekly hours sum to exactly 18 satisfies the full course of study. When the full-course-of-study sum falls short of `i20_required_weekly_hours`, activation is rejected with `ERR_NOT_FULL_COURSE_OF_STUDY` (HTTP 409). Activation appends a `ComplianceEvent` of type `STATUS_ACTIVATED` (prior `INITIAL`, new `ACTIVE`).

The visa status then runs a revision cycle between `ACTIVE` and `PROBATION`. A student is placed on probation, transitioning `ACTIVE → PROBATION`, either automatically when a withdrawal empties the student's course load (as described in §3.7) or explicitly when a `DSO` places them on probation; the explicit placement requires the current status to be `ACTIVE` and appends a `ComplianceEvent` of type `PROBATION_PLACED` (prior `ACTIVE`, new `PROBATION`). A student in `PROBATION` cannot confirm a new `ENROLLED` enrollment until cleared, which is the same gate enforced by `ERR_VISA_NONCOMPLIANT`. A `DSO` clears probation, transitioning `PROBATION → ACTIVE`, but only when the current status is `PROBATION` and the student is once again meeting a full course of study by the same enrolled-weekly-hours rule; a clear attempt that does not meet the full course of study is rejected with `ERR_NOT_FULL_COURSE_OF_STUDY` (HTTP 409). Clearing appends a `ComplianceEvent` of type `PROBATION_CLEARED` (prior `PROBATION`, new `ACTIVE`).

Terminating F-1 status is the terminal exit: a `DSO` terminates a probationary student, transitioning `PROBATION → TERMINATED`, which requires the current status to be `PROBATION`. Termination appends a `ComplianceEvent` of type `I20_TERMINATED` (prior `PROBATION`, new `TERMINATED`), then cascades: every currently `ENROLLED` enrollment of the student is terminated with `termination_reason` `VISA_NONCOMPLIANCE` (releasing each cohort seat and each contract seat and promoting waitlists as in §3.7), and the student's `certification_status` is set to `VOIDED` if it was previously `PROVISIONAL` or `CERTIFIED`. `TERMINATED` is the terminal visa state.

### 3.9. Corporate Contracts and Add-On Cancellation

A `Registrar` creates a **corporate contract** to sponsor a group of students. A contract names the `company_name`, a `contracted_seats` count (the total prepaid seats it may sponsor across all cohorts, an integer of at least 1), and an optional `discount_tier` (one of `BRONZE`, `SILVER`, or `GOLD`, defaulting to `BRONZE`). The contract begins with `status` `ACTIVE` and `seats_consumed` of 0. As sponsored students take and leave `ENROLLED` seats, `seats_consumed` rises and falls; the contract automatically becomes `EXHAUSTED` when `seats_consumed` reaches `contracted_seats` (blocking further sponsored `ENROLLED` confirmations) and automatically returns to `ACTIVE` when a sponsored enrollment leaves `ENROLLED` and frees a seat.

A `Registrar` closes a contract, transitioning it `ACTIVE → CLOSED` or `EXHAUSTED → CLOSED`. The close requires the contract to currently be `ACTIVE` or `EXHAUSTED` and that the supplied `expected_contract_version` match the live contract `version`, failing otherwise with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) as described in §2.7. Closing cascades: every currently `ENROLLED` enrollment sponsored by the contract is terminated with `termination_reason` `CONTRACT_REVOKED` (releasing each cohort seat and each contract seat and promoting waitlists exactly as a termination does), and the contract's `version` is incremented by one. `CLOSED` is terminal.

Finally, an add-on subscription may be cancelled. A `Student` cancels their own add-on, transitioning it `ACTIVE → CANCELLED`, which requires the add-on to currently be `ACTIVE` and its parent enrollment to be in one of `PLACEMENT_PENDING`, `ENROLLED`, or `WAITLISTED` state — an add-on cannot be cancelled once its enrollment has reached a terminal state. Cancellation triggers no tuition reversal: the add-on's `fee_cents` was already baked into the enrollment's `tuition_invoice_cents` at the moment of `ENROLLED`, so cancelling only stops future delivery and does not adjust any invoice or refund.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource — including every state-machine action and the logical-clock control — return a `200 OK` status code. Request and response bodies, side effects, and trigger conditions for each endpoint are described in the §3 narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/students` | Register a student (self-pay or sponsored) | Anonymous, Registrar |
| GET | `/students/{id}` | Fetch a student with computed posture fields | Registrar, DSO, Instructor, Student |
| GET | `/students` | List students; filter by `corporate_contract_id`, `visa_status` | Registrar, DSO |
| GET | `/students/{id}/enrollments` | List all enrollments of a student | Registrar, DSO, Instructor, Student |
| GET | `/students/{id}/compliance-events` | List the append-only compliance audit log of a student | Registrar, DSO |
| GET | `/students/{id}/add-ons` | List all add-on subscriptions of a student | Registrar, Student |
| GET | `/students/{id}/placement-tests` | List all placement tests of a student | Registrar, Instructor, Student |
| POST | `/students/{id}/issue-i20` | Issue the I-20: visa status `NONE → INITIAL` | DSO |
| POST | `/students/{id}/activate-status` | Activate F-1 status: `INITIAL → ACTIVE` | DSO |
| POST | `/students/{id}/place-probation` | Place on probation: `ACTIVE → PROBATION` | DSO |
| POST | `/students/{id}/clear-probation` | Clear probation: `PROBATION → ACTIVE` | DSO |
| POST | `/students/{id}/terminate-status` | Terminate F-1 status: `PROBATION → TERMINATED` (cascades) | DSO |
| POST | `/placement-tests` | Register a placement test for a student | Anonymous, Registrar, Student |
| GET | `/placement-tests/{id}` | Fetch a placement test | Registrar, Instructor, Student |
| POST | `/placement-tests/{id}/score` | Score a test: `REGISTERED → SCORED`; sets levels | Instructor |
| POST | `/placement-tests/{id}/void` | Void a test: `REGISTERED → VOIDED` | Registrar |
| POST | `/cohorts` | Create a cohort | Registrar |
| GET | `/cohorts/{id}` | Fetch a cohort with computed seats and status | Registrar, DSO, Instructor, Student |
| GET | `/cohorts` | List cohorts; filter by `level`, `track`, `status` | Registrar, DSO, Instructor, Student |
| GET | `/cohorts/{id}/enrollments` | List all enrollments on a cohort | Registrar, DSO, Instructor |
| POST | `/enrollments` | Create a `PLACEMENT_PENDING` enrollment | Registrar |
| GET | `/enrollments/{id}` | Fetch an enrollment with computed fields | Registrar, DSO, Instructor, Student |
| POST | `/enrollments/{id}/confirm` | Confirm placement: forks `ENROLLED` vs `WAITLISTED` | Registrar |
| POST | `/enrollments/{id}/withdraw` | Withdraw: `ENROLLED → WITHDRAWN` (refund, cascades) | Registrar |
| POST | `/enrollments/{id}/terminate` | Terminate: `ENROLLED → TERMINATED` with reason (cascades) | DSO |
| POST | `/enrollments/{id}/complete` | Complete: `ENROLLED → COMPLETED` (score, rollup) | Registrar |
| POST | `/attendance` | Record a session attendance mark | Instructor |
| GET | `/enrollments/{id}/attendance` | List all attendance records for an enrollment | Registrar, DSO, Instructor, Student |
| POST | `/progress-reports` | Record a progress assessment | Instructor |
| GET | `/enrollments/{id}/progress-reports` | List all progress reports for an enrollment | Registrar, DSO, Instructor, Student |
| POST | `/add-ons` | Subscribe to an add-on bundled onto an enrollment | Registrar, Student |
| GET | `/add-ons/{id}` | Fetch an add-on subscription | Registrar, Student |
| GET | `/enrollments/{id}/add-ons` | List all add-ons bundled onto an enrollment | Registrar, DSO, Student |
| POST | `/add-ons/{id}/cancel` | Cancel an add-on: `ACTIVE → CANCELLED` | Student |
| POST | `/corporate-contracts` | Create a corporate/group contract | Registrar |
| GET | `/corporate-contracts/{id}` | Fetch a contract with computed seats and status | Registrar, CorporateSponsor |
| GET | `/corporate-contracts/{id}/students` | List all students sponsored by a contract | Registrar, CorporateSponsor |
| POST | `/corporate-contracts/{id}/close` | Close a contract: `ACTIVE/EXHAUSTED → CLOSED` (cascades) | Registrar |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied UTC instant | Registrar, DSO |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLACEMENT_MISMATCH` | 409 |
| `ERR_VISA_NONCOMPLIANT` | 409 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_DUPLICATE_SESSION` | 409 |
| `ERR_CONTRACT_SEATS_EXHAUSTED` | 409 |
| `ERR_COHORT_FULL` | 409 |
| `ERR_STALE_COHORT_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_COMPLETION_REQUIREMENTS_UNMET` | 409 |
| `ERR_NOT_FULL_COURSE_OF_STUDY` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_CONTRACT_REQUIRED_FOR_SPONSOR` | 404 |
| `ERR_INVALID_TERMINATION_REASON` | 422 |
| `ERR_ADDON_ENROLLMENT_MISMATCH` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
