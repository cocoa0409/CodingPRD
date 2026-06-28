# Cdl Truck Driving School API — Product Requirements Document

## 1. Introduction

Commercial driver licensing in the United States sits at the intersection of federal compliance and hands-on operational scheduling. Under the FMCSA Entry-Level Driver Training (ELDT) mandate, a school cannot graduate a candidate until that candidate has accumulated documented theory, yard, and public-road clock-hours, passed a skills examination administered by an independent examiner, and had the result transmitted to the federal registry. This API is the system of record for a CDL truck-driving school that must reconcile all of those obligations at once: it tracks each student's enrollment from application through completion, enforces the medical and permit prerequisites that gate training, schedules scarce tractors and instructors against overlapping demand, computes the weighted skills score that decides pass or fail, and manages the financing and carrier-sponsorship arrangements that pay for tuition.

The system is built around a single hub — the **Enrollment** — with peer resources (programs, tractors, instructors, carriers) referenced across aggregate boundaries as sessions are booked and tests are scheduled. Because the domain is fundamentally a compliance audit, the API treats logged clock-hours as a conserved, reconcilable quantity: hours are credited only when sessions actually complete, reserved truck and instructor minutes are released the instant a session is cancelled, and a lapsed medical certificate pulls a student back out of training and cancels their booked sessions. The sections that follow define the global contract (authentication, response envelope, pagination, precision, and concurrency control) and then the business workflows that govern every enrollment from the first prerequisite document to the final FMCSA transmission.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation per the access rules described throughout this document, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `SchoolAdmin`, `Registrar`, `Instructor`, and `ThirdPartyExaminer`.

A `SchoolAdmin` is the school operator. The role configures programs, tractors, instructors, and carriers; voids scheduled tests; forfeits accepted sponsorships; drafts and transmits FMCSA completion reports; and drives the logical test-clock. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

A `Registrar` owns the enrollment lifecycle: creating enrollments, managing prerequisite documents, booking sessions, scheduling tests, accepting or declining sponsorships, creating finance plans, and withdrawing students. When `X-User-Role` is `Registrar`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

An `Instructor` delivers classroom, range, and road sessions, and may book, complete, and cancel booked sessions. A `ThirdPartyExaminer` is a state-authorized examiner who grades skills tests and is subject to segregation-of-duties constraints. For both of these roles, `X-User-ID` is the `id` of the acting `Instructor` entity (examiners are backed by the same `Instructor` records, distinguished by their `examiner_certified` flag); any ownership or conflict check on a resource that references an instructor compares that resource's instructor foreign-key field to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Out-of-range numeric values are clamped rather than rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; when two resources share the same `created_at`, they are further ordered by their server-assigned creation sequence, so that the earlier-created resource sorts first.

List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a system-managed `id`: a server-minted UUID with no type prefix. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, set when the resource is first created.

All entities in this system — `Program`, `Truck`, `Instructor`, `Enrollment`, `PrereqDocument`, `ClockSession`, `SkillsTest`, `Carrier`, `SponsorshipOffer`, `FinancePlan`, and `CompletionReport` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, and `version` is an integer that begins at its initial value of 1 on creation and increments by one with every mutation. These two fields are present on all resource types here; there are no create-only resources in this domain that omit them.

### 2.5. Precision, Rounding, and Conserved Quantities

Two precision regimes apply. Clock-hour totals (the logged and projected hour fields on an enrollment, and the hour snapshots on a completion report) are expressed in hours to 2 decimal places, rounded half-up. Monetary amounts are stored and returned as integer cents; wherever a monetary computation requires rounding, the half-up method is used, except where a calculation explicitly pins a floor operation (see the finance schedule in §3.7).

Reserved minutes on a truck and on an instructor are tracked as exact integer minutes and are never rounded. They form a conserved-quantity ledger: the `reserved_minutes` of a `Truck` is the sum of `duration_minutes` over that truck's `BOOKED` sessions, and the `reserved_minutes` of an `Instructor` is the sum of `duration_minutes` over that instructor's `BOOKED` sessions. The governing invariant is that booking a session and then cancelling the same session leaves `reserved_minutes` exactly equal to its pre-booking value. A `COMPLETED` or `CANCELLED` session contributes nothing to reserved minutes.

### 2.6. Hierarchical Consistency and Automatic Reconciliation

Many state changes in this system cascade. When a parent enrollment changes state, dependent child resources are resolved automatically without a separate client request against each child, and when a child resource changes in a way that affects the parent's gating criteria, the parent is re-evaluated and may transition on its own. Each such automatic transition independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`. The specific cascades — prerequisite verification unlocking training, an expiring document reverting a student out of training, completed hours promoting an enrollment to test-ready, withdrawal cancelling sessions and finance plans and forfeiting sponsorships — are described in their workflow context in §3.

The denormalized totals on parents are kept reconciled with their children at all times: an enrollment's logged and projected hour fields, and a truck's and instructor's reserved minutes, are recomputed from the underlying sessions whenever a session is booked, completed, or cancelled, rather than being independently mutated.

### 2.7. Nested Resource Retrieval and Left-to-Right Validation

Several endpoints address a child resource through its parent — for example, the prerequisite documents, clock sessions, skills tests, sponsorship offers, finance plans, and completion reports that hang under an enrollment. For any request whose path carries more than one identifier, the system validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource. A request for a sub-resource under a non-existent enrollment therefore fails on the enrollment identifier before the child is ever consulted. The same left-to-right rule applies to foreign keys carried in a request body: any referenced resource that does not exist yields `ERR_NOT_FOUND`.

### 2.8. Validation Ordering

When a single request is subject to several checks, the system applies them in a fixed priority order so that the reported error is deterministic. Authentication is evaluated first: a missing or malformed `X-User-ID` / `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN`. Existence is third: any missing path or foreign-key resource yields `ERR_NOT_FOUND`. Request well-formedness is fourth: a body missing a required field, carrying an invalid enum value, a `duration_minutes` that is not greater than zero, or a component score outside the inclusive 0 to 100 range yields `ERR_INVALID_REQUEST`. State validity is fifth: if the target resource is not in a state from which the requested transition is defined, the request yields `ERR_INVALID_STATE`. The optimistic-concurrency check (§2.9) is sixth. Only after all of these pass does the system evaluate the domain-specific business-safety, referential, and temporal rules described in §3, each of which carries its own error identifier. In every case the earliest failing check in this ordering is the one reported.

### 2.9. Optimistic Concurrency Control

Creating a finance plan for an enrollment is guarded by optimistic concurrency control on the parent enrollment. The create request must carry `expected_enrollment_version`, a non-optional field whose value is the `version` of the target enrollment as the client last observed it. If `expected_enrollment_version` does not equal the enrollment's current `version` at the time the create is processed, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412. Because a newly created active plan supersedes the prior active plan for the same enrollment, this guard ensures the writer's view of the enrollment — and therefore which plan it is about to supersede — is current before the supersession takes effect; a client that has not observed the enrollment's latest version cannot blindly overwrite a plan it never saw. No other endpoint in this API takes a version field; finance-plan creation is the sole OCC-guarded write.

## 3. Business Logic & Workflows

### 3.1. Programs, Tractors, Instructors, and Carriers — the Configuration Layer

Before any student is enrolled, a `SchoolAdmin` stands up the reference data the rest of the system schedules against.

A **Program** captures the ELDT requirements and pricing for one credential. It is created with a `name`, a `cdl_class` that is either `CLASS_A` or `CLASS_B`, and three required-hour figures: `classroom_required_hours` for theory, `range_required_hours` for yard (behind-the-wheel range) work, and `road_required_hours` for public-road driving, each of which must be zero or greater. It also carries a `tuition_cents` sticker price in integer cents (zero or greater) and an optional `skills_pass_threshold`, the minimum weighted skills score required to pass, which lies on the inclusive 0 to 100 scale and defaults to 80 when omitted. On creation, a program's `active` flag is set to true, meaning new enrollments may reference it.

A **Truck** is a training tractor, registered with a `unit_number` fleet identifier and a `cdl_class` (`CLASS_A` or `CLASS_B`) describing the class it is rated for. It also accepts an optional `turnaround_buffer_minutes` — the post-session unavailable buffer appended after each session for cleaning and inspection — which defaults to 30 and must be zero or greater. At registration the truck's `status` is set to `AVAILABLE` (the only status a truck holds in this benchmark) and its `reserved_minutes` ledger starts at 0.

An **Instructor** is registered with a `full_name` and a `cdl_class` denoting the highest CDL class they are certified to teach, where a `CLASS_A` instructor covers `CLASS_B` work as well. The optional `examiner_certified` flag marks whether this person is also a state-authorized third-party skills examiner; it defaults to false. At registration the instructor's `status` is `ACTIVE` (the only status in this benchmark) and `reserved_minutes` starts at 0.

A **Carrier** is a sponsoring motor carrier, registered with a `name`, a `commitment_months` figure stating how many months a sponsored graduate must drive for the carrier (which must be greater than zero), and a `reimbursement_cents` amount in integer cents (zero or greater) that the carrier funds when its sponsorship offer is accepted.

### 3.2. Enrollment Intake and the Prerequisite Gate

A `Registrar` opens the student lifecycle by creating an **Enrollment** against a program, supplying the `program_id` and the `student_name`. A fresh enrollment begins in `APPLIED` status with both verification flags — `dot_medical_verified` and `permit_verified` — false, its `sponsoring_carrier_id` unset, and `fmcsa_reported` false. Reading an enrollment exposes its computed hour totals (`logged_classroom_hours`, `logged_range_hours`, `logged_road_hours`, `projected_road_hours`) and its `status`. Enrollments may be listed and filtered by `program_id` or by `sponsoring_carrier_id`.

Before training can begin, two prerequisite documents must be approved: a DOT-medical certificate and a commercial learner permit (CLP). The `Registrar` submits each as a **PrereqDocument** against the enrollment, supplying the `kind` (`DOT_MEDICAL` or `CLP_PERMIT`), a `reference_code` (the document or permit reference number on file), and an `expires_on` expiry instant in UTC. A submitted document enters `SUBMITTED` status. Submitting the first prerequisite document while the enrollment is `APPLIED` advances the enrollment to `PREREQ_PENDING`, where it awaits approval of both prerequisites. Documents can be retrieved individually, listed under their enrollment, or listed across the system filtered by `enrollment_id`.

When the `Registrar` approves a document, the system first confirms it is still `SUBMITTED` and that its `expires_on` is strictly after the current clock time; approving a document whose `expires_on` is at or before the current clock time is forbidden and rejected with `ERR_DOCUMENT_EXPIRED`. On approval the document moves to `APPROVED`, and the matching verification flag is set on the enrollment: a `DOT_MEDICAL` approval sets `dot_medical_verified` true, and a `CLP_PERMIT` approval sets `permit_verified` true. The moment both `dot_medical_verified` and `permit_verified` are true, the enrollment automatically advances from `PREREQ_PENDING` to `TRAINING`, which is the cascade that unlocks clock-session booking for the student. Alternatively the `Registrar` may reject a `SUBMITTED` document, moving it to `REJECTED` with no side effects on the enrollment.

An approved document does not stay valid forever. A `Registrar` or `SchoolAdmin` may manually expire an approved document, and the test-clock may expire it automatically (see §3.8). The two paths differ on their time gate: the manual expire endpoint moves any `APPROVED` document straight to `EXPIRED` immediately, with no comparison against the clock — its only precondition is that the document is currently `APPROVED` (otherwise `ERR_INVALID_STATE`) — whereas the automatic, clock-driven path expires a document only when the current clock time is at or after its `expires_on`. Expiry clears the corresponding flag — a `DOT_MEDICAL` expiry clears `dot_medical_verified`, a `CLP_PERMIT` expiry clears `permit_verified`. If clearing a flag leaves either `dot_medical_verified` false or `permit_verified` false while the enrollment is in `TRAINING`, the enrollment automatically reverts from `TRAINING` to `PREREQ_PENDING`; this revert cancels all of the enrollment's `BOOKED` clock sessions and releases the reserved minutes those sessions held on their trucks and instructors. Documents are terminal once `REJECTED` or `EXPIRED`.

### 3.3. Scheduling Clock-Hour Sessions Against Trucks and Instructors

Once an enrollment reaches `TRAINING`, instruction is delivered through **ClockSession** bookings, which a `Registrar` or an `Instructor` may create against the enrollment. A booking supplies the `phase` (`CLASSROOM`, `RANGE`, or `ROAD`), the `instructor_id` of the delivering instructor, an optional `truck_id`, the `starts_at` session-start instant in UTC, and the `duration_minutes` scheduled length (a positive integer number of minutes — a value that is not an integer, or not greater than zero, is rejected with `ERR_INVALID_REQUEST`). A `RANGE` or `ROAD` session requires a tractor and therefore a `truck_id`, and omitting the `truck_id` on a `RANGE` or `ROAD` booking is rejected with `ERR_TRUCK_CLASS_MISMATCH`; a `CLASSROOM` session must not supply a `truck_id`, and supplying one is rejected with `ERR_TRUCK_CLASS_MISMATCH`. For range and road sessions the chosen tractor's `cdl_class` must match the program's `cdl_class`; a mismatch is also rejected with `ERR_TRUCK_CLASS_MISMATCH`.

Booking is gated on the enrollment's training status: a session may only be booked when the enrollment is in `TRAINING` (which means both DOT-medical and permit are verified). Attempting to book while the enrollment is in any other status is rejected with `ERR_PREREQ_NOT_MET`. A new session is created in `BOOKED` status; the booking adds its `duration_minutes` to the instructor's `reserved_minutes` and, when a truck is set, to the truck's `reserved_minutes`, and it triggers a recompute of the enrollment's `projected_road_hours`.

Two temporal conflict rules protect the shared tractors and instructors, and they are deliberately asymmetric. A truck's busy interval is the half-open span beginning at a session's `starts_at` and running through `starts_at` plus `duration_minutes` plus the truck's `turnaround_buffer_minutes`; the upper bound is exclusive. A new booking whose own half-open interval — from its `starts_at` through `starts_at` plus `duration_minutes`, upper bound exclusive — overlaps any existing buffered busy interval on the same truck is rejected with `ERR_TRUCK_DOUBLE_BOOKED`. An instructor's busy interval is the half-open span from `starts_at` through `starts_at` plus `duration_minutes` with no turnaround buffer; a new session overlapping the instructor's existing `BOOKED` interval is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`, but because the intervals are half-open, a back-to-back session that begins exactly when the prior one ends is permitted.

A session is delivered and then closed out by an `Instructor`, who marks it complete. Completion requires that the session still be `BOOKED`, that the owning enrollment be in `TRAINING` (otherwise `ERR_ENROLLMENT_NOT_TRAINING`), and that enough time has elapsed on the clock — specifically that `starts_at` plus `duration_minutes` is at or before the current clock time (otherwise `ERR_SESSION_NOT_ELAPSED`). On completion the session moves to `COMPLETED` and the enrollment's logged hours for that phase are recomputed.

A booked session can instead be cancelled by an `Instructor` or a `SchoolAdmin` (both roles are authorized on the cancel operation, and either may cancel a session that is still `BOOKED`). Cancelling a `BOOKED` session moves it to `CANCELLED`, subtracts its `duration_minutes` from the instructor's `reserved_minutes` and, when a truck is set, from the truck's `reserved_minutes`, and recomputes the enrollment's projected road hours. Separately, a `SchoolAdmin` may administratively void a session that has already been `COMPLETED` — a compensating action that reverses the logging; the void of a `COMPLETED` session is reserved to a `SchoolAdmin`, so an `Instructor` who targets a `COMPLETED` session through the same cancel operation is rejected with `ERR_FORBIDDEN`. This void is permitted only when the session is `COMPLETED` and the enrollment is neither `PASSED` nor `COMPLETED`; once the enrollment has reached either of those, the void is rejected with `ERR_SESSION_LOCKED`. When the cancel operation targets a session that is already `CANCELLED`, it is rejected with `ERR_INVALID_STATE`. A void moves the session to `CANCELLED`, recomputes the enrollment's logged hours downward, and may revert the enrollment from `TEST_READY` back to `TRAINING` if a logged total falls below its requirement. A session is terminal once `COMPLETED` or `CANCELLED`. Sessions may be listed under their enrollment or across the system filtered by `truck_id`, `instructor_id`, or `enrollment_id`.

### 3.4. Logged Hours, Projected Hours, and the Test-Ready Gate

The school distinguishes two views of accumulated clock-hours. The **logged** totals are the verified, reportable, chronological view that counts only sessions that have actually been completed. The logged classroom hours equal the sum, over the enrollment's `COMPLETED` `CLASSROOM` sessions, of each session's `duration_minutes` divided by 60; the logged range hours are the same sum over `COMPLETED` `RANGE` sessions; and the logged road hours are the same sum over `COMPLETED` `ROAD` sessions. Booked and cancelled sessions contribute nothing to these totals. Each total is rounded half-up to two decimal places. These totals are recomputed whenever a session completes or a completed session is administratively voided.

The **projected** road view is forward-looking and is used to judge whether the booked plan will reach the road requirement before any session has been delivered. The projected road hours equal the sum, over the enrollment's `ROAD` sessions whose status is either `BOOKED` or `COMPLETED`, of each session's `duration_minutes` divided by 60, rounded half-up to two decimal places. Because it counts booked-but-not-yet-completed sessions in addition to completed ones, for the same set of road sessions the projected total meets or exceeds the logged total until each of those sessions is actually completed. Projected road hours are recomputed whenever a road session is booked or cancelled.

The compound test-ready gate is evaluated upward after a session completes: when the enrollment's logged classroom hours are at least the program's `classroom_required_hours`, its logged range hours are at least the program's `range_required_hours`, and its logged road hours are at least the program's `road_required_hours` — all three simultaneously — the enrollment automatically advances from `TRAINING` to `TEST_READY` and becomes eligible to schedule a skills test. The gate is also re-evaluated downward: if an administrative void drops any one of the three logged totals below its corresponding requirement while the enrollment is `TEST_READY`, the enrollment automatically reverts from `TEST_READY` to `TRAINING` and loses test eligibility.

### 3.5. The Skills Test, the Examiner, and the Retake Cycle

A `Registrar` schedules a **SkillsTest** against an enrollment, which is permitted only when the enrollment is in `TEST_READY` status — scheduling while the enrollment is not `TEST_READY` is rejected with `ERR_ENROLLMENT_NOT_TEST_READY`. The schedule request supplies the `examiner_id` of the third-party examiner and, for a retake, an optional `supersedes_test_id` pointing at the prior failed test this attempt replaces (null for a first attempt). When `supersedes_test_id` is supplied it must resolve to an existing skills test (otherwise `ERR_NOT_FOUND`), but the system does not otherwise constrain the superseded test's status or outcome at schedule time. A scheduled test begins in `SCHEDULED` status.

Two examiner constraints apply when scheduling. First, segregation of duties: the named examiner — identified by `examiner_id` — must not have personally instructed any `COMPLETED` `ROAD` session of this same enrollment. An examiner who logged the student's road hours as the delivering instructor may not then examine that student, and a scheduling attempt that violates this is rejected with `ERR_EXAMINER_CONFLICT`. Second, the examiner must be qualified: the instructor referenced by `examiner_id` must have `examiner_certified` set true and must be certified for the program's `cdl_class`, where certification follows the same covering rule as instruction — a `CLASS_A` examiner is certified for both `CLASS_A` and `CLASS_B` programs, while a `CLASS_B` examiner covers only `CLASS_B`; otherwise the schedule is rejected with `ERR_EXAMINER_NOT_CERTIFIED`.

Grading is performed by a `ThirdPartyExaminer`, who enters three component scores — `pre_trip_score` for the pre-trip inspection, `basic_control_score` for the basic-control (range) component, and `road_score` for the on-road component — each on the inclusive 0 to 100 scale. Grading is permitted only when the test is still `SCHEDULED` and the enrollment is still in `TEST_READY` (otherwise `ERR_ENROLLMENT_NOT_TEST_READY`). On grading, the system computes the `weighted_score` as three-tenths of the pre-trip score plus three-tenths of the basic-control score plus four-tenths of the road score, rounded half-up to two decimal places. The `outcome` is `PASS` when the weighted score is at least the program's `skills_pass_threshold`, and `FAIL` otherwise — the comparison is inclusive at the threshold, so a weighted score exactly equal to the threshold passes. The test then moves to `GRADED`. When the outcome is `PASS`, the enrollment automatically advances from `TEST_READY` to `PASSED`, making it eligible for FMCSA completion reporting.

A `SchoolAdmin` may instead void a `SCHEDULED` test, moving it to `VOIDED` with no side effects; `VOIDED` is terminal. After a graded failure, the `Registrar` schedules a fresh retake whose `supersedes_test_id` is set to the prior graded-fail test, forming the retake loop. Skills tests can be retrieved individually, listed under their enrollment, or listed across the system filtered by `enrollment_id`, `examiner_id`, or `supersedes_test_id`.

### 3.6. Carrier Sponsorship, Service, and Clawback

A `SchoolAdmin` or `Registrar` extends a **SponsorshipOffer** to a student by supplying the `carrier_id` of the offering carrier; the offer is created in `OFFERED` status. Offers may be retrieved individually, listed under their enrollment, or listed across the system filtered by `enrollment_id` or `carrier_id`.

A `Registrar` accepts an `OFFERED` offer, provided the enrollment has no other `ACCEPTED` sponsorship offer — a second acceptance is rejected with `ERR_SPONSORSHIP_CONFLICT`. Acceptance moves the offer to `ACCEPTED` and sets the enrollment's `sponsoring_carrier_id` to the offer's carrier. A `Registrar` may instead decline an `OFFERED` offer, moving it to `DECLINED` with no side effects.

Once accepted, the offer accrues service. The offer's `months_served` counter starts at 0 and is advanced as the graduate drives for the carrier (mechanically, via the service-tick capability in §3.8). When `months_served` reaches at least the carrier's `commitment_months`, the offer automatically transitions from `ACCEPTED` to `FULFILLED`, its `clawback_cents` is set to 0, and the service obligation is discharged.

If an accepted sponsorship is broken before the commitment is served, a clawback is owed. A `SchoolAdmin` may forfeit an `ACCEPTED` offer directly, and a withdrawal of the owning enrollment forfeits it automatically (see §3.9); either path moves the offer from `ACCEPTED` to `FORFEITED`, computes `clawback_cents`, and clears the enrollment's `sponsoring_carrier_id`. The clawback decays linearly with service rendered. First compute the remaining months as the carrier's `commitment_months` minus the offer's `months_served`. If the remaining months are zero or fewer, `clawback_cents` is 0. Otherwise `clawback_cents` is the carrier's `reimbursement_cents` multiplied by the remaining months and divided by the carrier's `commitment_months`, rounded half-up to an integer number of cents. As a consequence, when a graduate forfeits with `months_served` equal to 0, the remaining months equal the full commitment and the clawback equals the entire `reimbursement_cents`. Offers are terminal once `DECLINED`, `FULFILLED`, or `FORFEITED`.

### 3.7. Tuition Financing

A `Registrar` may create a **FinancePlan** for an enrollment, supplying the `term_months` count of monthly installments (an integer from 1 to 36 inclusive) and the `expected_enrollment_version` required by the optimistic-concurrency guard of §2.9. A new plan is created in `ACTIVE` status. Creating a plan increments the enrollment's `version` by one, and any prior `ACTIVE` finance plan for the same enrollment is moved to `SUPERSEDED`, leaving exactly one active plan governing tuition. A finance plan is also moved to `CANCELLED` automatically when its owning enrollment is withdrawn. Plans may be retrieved individually, listed under their enrollment, or listed across the system filtered by `enrollment_id`.

The plan's full schedule is computed at creation time, all in integer cents. The plan snapshots `tuition_cents` from the program's `tuition_cents` at the moment of creation. The down-payment percentage is tiered on that snapshot: when the snapshotted tuition is at least 600000 cents (that is, six thousand dollars), the down payment is twenty percent of tuition; otherwise it is ten percent. The `down_payment_cents` is that percentage of the snapshotted tuition, rounded half-up. The `financed_cents` is the snapshotted tuition minus the down payment. Interest is simple interest accrued at one percent of the financed principal per month: the `total_interest_cents` is the financed amount multiplied by one percent and by the number of `term_months`, rounded half-up. The total amount to repay is the financed amount plus the total interest.

The installment split is order-sensitive and must be performed exactly as follows. The `installment_cents` — the amount of each of the first `term_months` minus one installments — is the total repayment amount divided by `term_months`, taking the floor (rounding down to a whole number of cents). The `final_installment_cents` is then the total repayment amount minus `installment_cents` multiplied by `term_months` minus one, so that the last installment absorbs the entire leftover-cents remainder. The equal installment is floored first and the remainder lands only on the final line; the alternative of rounding each installment independently and summing is not used.

### 3.8. Logical Clock and Post-Graduation Service Ticks

The server runs a logical clock rather than reading wall-clock time. At startup the clock is set to `2026-04-01T00:00:00Z`, and it never falls back to wall-clock. A `SchoolAdmin` may move the clock to a supplied UTC instant, provided through the `to_iso8601` field, with no constraint requiring the new instant to be later than the current one (the clock may be set backward as well as forward); this set operation returns `200 OK` whose `data` is a small status object carrying a single `current_utc` field holding the new clock instant as an ISO 8601 UTC timestamp, rather than any persisted resource. Advancing the clock past an approved prerequisite document's `expires_on` automatically expires that document — moving it from `APPROVED` to `EXPIRED`, clearing the corresponding verification flag, and, where that leaves a verification flag false on an enrollment in `TRAINING`, reverting the enrollment to `PREREQ_PENDING` with the attendant session cancellations described in §3.2.

A `SchoolAdmin` also drives post-graduation service accrual through a capability that advances an accepted sponsorship offer's service counter, supplying the `offer_id` of the offer (which must resolve to an existing offer, otherwise `ERR_NOT_FOUND`) and the required integer `months` to add. The targeted offer must currently be `ACCEPTED`; otherwise the request is rejected with `ERR_INVALID_STATE`. The supplied months are added to that offer's `months_served`, and if the counter thereby reaches at least the carrier's `commitment_months`, the offer auto-transitions from `ACCEPTED` to `FULFILLED` as described in §3.6. The operation returns `200 OK` with the updated sponsorship offer as its `data`.

### 3.9. Withdrawal and the FMCSA Completion Report

A `Registrar` may withdraw an enrollment from any non-terminal status — that is, whenever the enrollment is not already `COMPLETED` — moving it to `WITHDRAWN`. Withdrawal is a cascading event. All of the enrollment's `BOOKED` clock sessions are auto-cancelled, and the reserved minutes they held are released back to their trucks and instructors. Any `ACTIVE` finance plan for the enrollment is moved to `CANCELLED`. If the enrollment has an `ACCEPTED` sponsorship offer, that offer is moved to `FORFEITED` with its `clawback_cents` computed per §3.6, which debits the sponsoring carrier's reimbursement obligation, and the enrollment's `sponsoring_carrier_id` is cleared. `WITHDRAWN` and `COMPLETED` are the two terminal enrollment states.

The lifecycle finishes with FMCSA reporting. Once an enrollment is `PASSED`, a `SchoolAdmin` drafts a **CompletionReport** against it, supplying the `passing_test_id` that identifies the graded passing skills test that qualified the graduate; the `passing_test_id` must resolve to an existing skills test (otherwise `ERR_NOT_FOUND`), but drafting itself does not gate on the enrollment's status or on the referenced test's outcome — those preconditions are enforced only at transmission time, so a draft may be created against an enrollment that has not yet reached `PASSED`. A drafted report begins in `DRAFT` status and snapshots the candidate's hour totals at draft time: `reported_classroom_hours`, `reported_range_hours`, and `reported_road_hours` are taken from the enrollment's logged classroom, range, and road hours respectively. Reports may be retrieved individually, listed under their enrollment, or listed across the system filtered by `enrollment_id` or `passing_test_id`.

Transmitting the report is the final act, performed by a `SchoolAdmin`. Transmission requires that the report still be `DRAFT`, that the enrollment be in `PASSED` status (otherwise `ERR_ENROLLMENT_NOT_PASSED`), and that the `passing_test_id` reference a `GRADED` test whose outcome is `PASS` (otherwise — when the referenced test is not in `GRADED` status or its outcome is not `PASS` — the transmission is rejected with `ERR_INVALID_STATE`). On transmission the report's `reported_classroom_hours`, `reported_range_hours`, and `reported_road_hours` are re-snapshotted from the enrollment's current logged classroom, range, and road hours (replacing the draft-time snapshot), the report moves to `TRANSMITTED`, the enrollment's `fmcsa_reported` flag is set true, and the enrollment automatically advances from `PASSED` to `COMPLETED`. If the enrollment carries an `ACCEPTED` sponsorship offer at this point, that offer's service clock begins. A completion report is terminal once `TRANSMITTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or read an existing resource return `200 OK`. The complete request body, response payload, and side effects for each operation are described in the §3 narratives above; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a training program | SchoolAdmin |
| GET | `/programs/{id}` | Get a program | SchoolAdmin, Registrar, Instructor, ThirdPartyExaminer |
| POST | `/trucks` | Register a training tractor | SchoolAdmin |
| GET | `/trucks/{id}` | Get a truck (includes reserved-minutes ledger) | SchoolAdmin, Registrar, Instructor |
| POST | `/instructors` | Register an instructor | SchoolAdmin |
| GET | `/instructors/{id}` | Get an instructor (includes reserved-minutes ledger) | SchoolAdmin, Registrar, Instructor, ThirdPartyExaminer |
| POST | `/carriers` | Register a sponsoring carrier | SchoolAdmin |
| GET | `/carriers/{id}` | Get a carrier | SchoolAdmin, Registrar |
| POST | `/enrollments` | Create an enrollment against a program | Registrar |
| GET | `/enrollments` | List enrollments (filter by program_id or sponsoring_carrier_id) | SchoolAdmin, Registrar |
| GET | `/enrollments/{id}` | Get an enrollment | SchoolAdmin, Registrar, Instructor, ThirdPartyExaminer |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment | Registrar |
| POST | `/enrollments/{id}/prereq-documents` | Submit a DOT-medical or CLP permit document | Registrar |
| GET | `/enrollments/{id}/prereq-documents` | List prerequisite documents for an enrollment | SchoolAdmin, Registrar |
| GET | `/prereq-documents` | List prerequisite documents (filter by enrollment_id) | SchoolAdmin, Registrar |
| GET | `/prereq-documents/{id}` | Get a prerequisite document | SchoolAdmin, Registrar |
| POST | `/prereq-documents/{id}/approve` | Approve a prerequisite document | Registrar |
| POST | `/prereq-documents/{id}/reject` | Reject a prerequisite document | Registrar |
| POST | `/prereq-documents/{id}/expire` | Manually expire an approved prerequisite document | Registrar, SchoolAdmin |
| POST | `/enrollments/{id}/clock-sessions` | Book a clock-hour session | Registrar, Instructor |
| GET | `/enrollments/{id}/clock-sessions` | List clock sessions for an enrollment | SchoolAdmin, Registrar, Instructor |
| GET | `/clock-sessions` | List clock sessions (filter by truck_id, instructor_id, or enrollment_id) | SchoolAdmin, Registrar, Instructor |
| GET | `/clock-sessions/{id}` | Get a clock session | SchoolAdmin, Registrar, Instructor |
| POST | `/clock-sessions/{id}/complete` | Mark a clock session completed | Instructor |
| POST | `/clock-sessions/{id}/cancel` | Cancel a booked session or void a completed one | Instructor, SchoolAdmin |
| POST | `/enrollments/{id}/skills-tests` | Schedule a third-party skills test | Registrar |
| GET | `/enrollments/{id}/skills-tests` | List skills tests for an enrollment | SchoolAdmin, Registrar, ThirdPartyExaminer |
| GET | `/skills-tests` | List skills tests (filter by enrollment_id, examiner_id, or supersedes_test_id) | SchoolAdmin, Registrar, ThirdPartyExaminer |
| GET | `/skills-tests/{id}` | Get a skills test | SchoolAdmin, Registrar, ThirdPartyExaminer |
| POST | `/skills-tests/{id}/grade` | Grade a skills test | ThirdPartyExaminer |
| POST | `/skills-tests/{id}/void` | Void a scheduled skills test | SchoolAdmin |
| POST | `/enrollments/{id}/sponsorship-offers` | Extend a carrier sponsorship offer | SchoolAdmin, Registrar |
| GET | `/enrollments/{id}/sponsorship-offers` | List sponsorship offers for an enrollment | SchoolAdmin, Registrar |
| GET | `/sponsorship-offers` | List sponsorship offers (filter by enrollment_id or carrier_id) | SchoolAdmin, Registrar |
| GET | `/sponsorship-offers/{id}` | Get a sponsorship offer | SchoolAdmin, Registrar |
| POST | `/sponsorship-offers/{id}/accept` | Accept a sponsorship offer | Registrar |
| POST | `/sponsorship-offers/{id}/decline` | Decline a sponsorship offer | Registrar |
| POST | `/sponsorship-offers/{id}/forfeit` | Forfeit an accepted sponsorship | SchoolAdmin |
| POST | `/enrollments/{id}/finance-plans` | Create a tuition finance plan (OCC-guarded) | Registrar |
| GET | `/enrollments/{id}/finance-plans` | List finance plans for an enrollment | SchoolAdmin, Registrar |
| GET | `/finance-plans` | List finance plans (filter by enrollment_id) | SchoolAdmin, Registrar |
| GET | `/finance-plans/{id}` | Get a finance plan | SchoolAdmin, Registrar |
| POST | `/enrollments/{id}/completion-reports` | Draft an FMCSA completion report | SchoolAdmin |
| GET | `/enrollments/{id}/completion-reports` | List completion reports for an enrollment | SchoolAdmin, Registrar |
| GET | `/completion-reports` | List completion reports (filter by enrollment_id or passing_test_id) | SchoolAdmin, Registrar |
| GET | `/completion-reports/{id}` | Get a completion report | SchoolAdmin, Registrar |
| POST | `/completion-reports/{id}/transmit` | Transmit the completion report to FMCSA | SchoolAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a UTC instant | SchoolAdmin |
| POST | `/_clock/advance_service_months` | Advance an accepted sponsorship's service months | SchoolAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DOCUMENT_EXPIRED` | 409 |
| `ERR_PREREQ_NOT_MET` | 409 |
| `ERR_EXAMINER_CONFLICT` | 409 |
| `ERR_EXAMINER_NOT_CERTIFIED` | 409 |
| `ERR_TRUCK_CLASS_MISMATCH` | 409 |
| `ERR_TRUCK_DOUBLE_BOOKED` | 409 |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_ENROLLMENT_NOT_TRAINING` | 409 |
| `ERR_SESSION_NOT_ELAPSED` | 409 |
| `ERR_SESSION_LOCKED` | 409 |
| `ERR_ENROLLMENT_NOT_TEST_READY` | 409 |
| `ERR_SPONSORSHIP_CONFLICT` | 409 |
| `ERR_ENROLLMENT_NOT_PASSED` | 409 |
