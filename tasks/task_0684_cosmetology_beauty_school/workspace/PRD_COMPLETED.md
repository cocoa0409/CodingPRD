# Cosmetology & Beauty School API — Product Requirements Document

## 1. Introduction

Cosmetology and beauty schools operate at the intersection of three regulated worlds at once: a clock-hour academic ledger that state licensing boards audit, a federal Title IV financial-aid ledger that the U.S. Department of Education audits, and a working salon floor where paying clients are served by students under instructor supervision. The same student record must simultaneously satisfy a Satisfactory Academic Progress (SAP) pace requirement, earn financial-aid disbursements only after the hours and weeks they fund have actually been completed, accumulate billable clinic-floor service hours under a licensed instructor's sign-off, and — should the student leave — drive both a federal Return of Title IV (R2T4) calculation and a separate institutional pro-rata tuition refund that use deliberately different bases.

This API is the institution's system of record for that lifecycle. It governs programs of study and the students enrolled in them, the instructors and physical floor stations that staff the clinic, the attendance and make-up sessions that accrue scheduled and actual clock hours, the clinic tickets that bill walk-in clients and credit service hours, the Title IV disbursements that fund tuition, the state-board exam-readiness and application workflow, and the withdrawal/refund process that unwinds an enrollment. Every figure that an auditor might later question — a student's pace, a posted disbursement's net amount, a ledger balance at graduation, a refund owed on withdrawal, a program's placement rate — is a derived value the server computes deterministically from primary records, never a number a client may assert directly. The remainder of this document specifies the entities, their state machines, the calculations, and the validation order that together make those derived figures reproducible and defensible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint in the API. All resource paths are mounted under the `/school` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `Registrar`, `FinancialAidOfficer`, `Instructor`, and `Student`. The `Registrar` owns the enrollment lifecycle, program/student/instructor/station setup, attendance voiding, SAP evaluation, clinic payment and voiding, exam-application adjudication, and placement reporting. The `FinancialAidOfficer` owns Title IV disbursements, their posting and return, and refund/withdrawal processing. The `Instructor` records and approves attendance, opens and signs off clinic tickets, and reserves and releases stations. The `Student` acts only on exam applications belonging to their own enrollment.

Two of these roles are tied to a persisted entity, and two are not. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; any ownership check on a resource that references an instructor compares the resource's instructor foreign key to `X-User-ID`. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on exam applications compare the `student_id` of the enrollment behind the application to `X-User-ID`, and a student acting on an exam application whose enrollment they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. By contrast, when `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. Likewise, when `X-User-Role` is `FinancialAidOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. Unless an endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and Versioning

Every entity in this system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All of the entities defined here — programs, students, instructors, stations, enrollments, attendance records, clinic tickets, station assignments, disbursements, exam applications, and withdrawals — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and an integer `version` that begins at its initial value on creation and increments by one on every mutation of that resource. There are no version-less or immutable entities in this domain; every resource participates in the `updated_at`/`version` convention.

The `version` field is the basis for optimistic concurrency control described in §2.7. Whenever the specification says an operation "bumps the version" of a resource, it means the integer `version` increments by one and `updated_at` is refreshed to the current logical clock instant.

### 2.5. Derived Fields, Hierarchical Consistency, and Cascades

A large fraction of the fields on an `Enrollment` are derived, not supplied: `actual_hours`, `pace_pct`, `total_charges_cents`, `total_credits_cents`, `ledger_balance_cents`, and `projected_balance_cents` are all computed by the server from child records and program charges, while `sap_warning_count`, `last_attendance_iso`, and `placement_status` are system-maintained counters and outcomes. Clients never write these directly. Each time a child event changes one of these bases — an attendance approval, a clinic sign-off, a disbursement post or return — the owning enrollment is recomputed, its `updated_at` refreshed, and its `version` incremented as part of the same operation.

Several operations cascade across more than one entity. When an enrollment terminates by withdrawal, the server propagates that change down to the enrollment's children (described in §3.6). When an enrollment graduates, any still-reserved station holdings are released. The single guiding rule is that derived enrollment figures and child states are always brought back into agreement within the same request that triggered the change; the system never leaves a posted-but-uncredited disbursement or a graduated enrollment still holding a reserved station. Each such reconciliation independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`.

The full recomputation of `actual_hours` and the ledger balances is always performed from scratch over the qualifying child records, never adjusted incrementally. This guarantees that compensating events — voiding a previously approved attendance record, or returning a previously posted disbursement — leave the derived totals exactly where a from-scratch recount would put them, with no accumulated drift.

### 2.6. Nested Resource Retrieval and Existence Ordering

When a request references resources, the server validates their existence from left to right. Any identifier embedded in the URL path is checked first, in path order, and the first one that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or body field is examined. After path identifiers, foreign keys carried in the request body are validated: a body foreign key that names a non-existent entity is rejected with `ERR_FK_NOT_FOUND`. Only once every referenced resource is known to exist does the server proceed to field-shape validation, state checks, and business rules.

### 2.7. Optimistic Concurrency Control on the Enrollment

Two write operations are guarded by optimistic concurrency control against the parent `Enrollment`, because both consume the enrollment's earned-hours and ledger snapshot and would corrupt it if applied to a stale view. Each requires a non-optional `expected_enrollment_version` field in its request body, carrying the client's last observed `version` of the target enrollment.

Posting a disbursement requires `expected_enrollment_version` to equal the live `version` of the disbursement's owning enrollment. If a prior mutation — another disbursement post, an attendance approval that changed `actual_hours`, or a SAP evaluation — has advanced the enrollment's `version` since the client last read it, the post is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), preventing a credit against the wrong ledger snapshot. Finalizing a withdrawal likewise requires `expected_enrollment_version` to equal the live `version` of the owning enrollment; if a disbursement post or attendance approval has advanced that `version` between the moment the withdrawal was calculated and the finalize call, the finalize is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), because the R2T4 and refund figures were computed against an enrollment view that no longer holds. This is purely a stale-version comparison against the enrollment's current `version`, not a timing or ordering rule. No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.8. Monetary and Hour Precision

All monetary amounts are stored and returned as integer cents; there are no fractional cents anywhere in the system. Where a calculation produces a sub-cent intermediate, the result is rounded to whole cents using the round-half-up convention at the point the relevant rule specifies, and several rules pin the exact order of rounding versus summation — those orders are stated with each calculation in §3 and must be followed exactly, because the alternative order diverges on half-cent boundaries.

Clock-hour and clinic-hour quantities are decimal numbers carried to two decimal places, rounded half up. Percentages such as a student's pace, an exam readiness score, and a placement rate are likewise carried to two decimal places, rounded half up, except where a rule explicitly floors or truncates (credit-hour conversion truncates toward zero to an integer). The exact rounding behavior of each derived figure is restated alongside its formula in §3.

### 2.9. The Logical Clock

The server maintains a single logical clock that stands in for "now" everywhere a current-time comparison is needed — instructor license-expiry checks at sign-off and attendance approval, and the elapsed-weeks gate on disbursement posting. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it remains at that default; it never falls back to wall-clock time. An administrative capability lets an operator set the clock to a supplied instant, after which all current-time comparisons use the new value. The supplied instant is provided as `to_iso8601`, and the capability returns the resulting `current_utc`.

### 2.10. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the same bad request always fails with the same error. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`), then existence of every path-referenced resource left to right (`ERR_NOT_FOUND`), then existence of every body foreign key (`ERR_FK_NOT_FOUND`), then request-shape validation — required fields present, correct types, valid enum values, and numeric fields within their declared ranges (`ERR_INVALID_REQUEST`). Only after a request is structurally sound does the server apply the domain-specific constraints: uniqueness checks, the per-endpoint business rules described throughout §3, the state-machine precondition that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), resource-ownership checks for student-scoped actions (`ERR_NOT_RESOURCE_OWNER`), and finally the optimistic-concurrency version check (`ERR_STALE_ENROLLMENT_VERSION`). Where a single endpoint layers several domain rules, the relative ordering among them is stated in the workflow narrative that defines them in §3.

## 3. Business Logic & Workflows

### 3.1. Programs, Students, Instructors, and Stations

A `Registrar` seeds the institution's reference data. A **Program** of study is created with a human-readable `name` (for example, "Cosmetology 1500"), the `total_clock_hours` required to graduate (at least 1), the full `tuition_cents` charged at enrollment, the `kit_fee_cents` for the student's kit, and the `lab_fee_cents` registration charge — each of these three charges being a non-negative cents amount. The program also fixes the `clinic_phase_start_hour`, the cumulative actual clock-hour at which a student becomes eligible to perform clinic-floor work (a non-negative integer), and may supply `clock_hours_per_credit`, the divisor that converts clock hours to academic credits; when omitted it defaults to 37.5 and must be strictly greater than zero. A program may also supply `admin_fee_cap_cents`, the maximum institutional administrative fee the school is allowed to retain when a student withdraws; when omitted it defaults to 15000 cents (that is, $150.00) and must be non-negative.

On program creation the server derives `credit_hours` once: it divides `total_clock_hours` by `clock_hours_per_credit` and takes the floor, truncating any fraction toward zero to yield an integer. For a 1500-hour program at the default divisor of 37.5 clock hours per credit, this yields 40 credits.

A **Student** is registered with a `full_name`, a contact `email` that must be unique across all students, and `ssn_last4`, the last four digits of the Social Security number used for Title IV and state-board identity. A new student begins with `status` of `PROSPECT`; over their lifecycle the `status` moves to `ENROLLED` when they are first enrolled in a program, and may eventually be `ARCHIVED`. Attempting to register a student whose `email` already belongs to another student is rejected with `ERR_DUPLICATE_KEY`.

An **Instructor** is created with a `full_name`, a state `license_number` that must be unique across all instructors, the `license_expires_on` date after which the license is no longer valid, and an `active` flag indicating whether the instructor is currently on staff (defaulting to true when omitted). Creating an instructor whose `license_number` duplicates an existing one is rejected with `ERR_DUPLICATE_KEY`. An instructor's licensure governs whether they may sign off student work, as detailed in §3.3.

A **Station** is a physical position on the clinic floor, created with a `label` such as "Styling-12" and a `station_type` that is one of `HAIR`, `NAIL`, `SKIN`, or `MAKEUP`. A station's `status` begins as `AVAILABLE` and moves to `OCCUPIED` while a service or reservation holds it, or to `OUT_OF_SERVICE` when it is withdrawn from use. Stations are released back to `AVAILABLE` automatically when the work holding them concludes, as described in §3.3.

### 3.2. Enrolling a Student and the SAP Pace Discipline

A `Registrar` creates an **Enrollment** by naming the `student_id` and the `program_id` and supplying `enrolled_on_iso`, the ISO date the enrollment begins, which becomes the basis for counting elapsed payment-period weeks. The Registrar may also supply `scheduled_hours_to_date`, the number of scheduled clock hours the student should have attended as of now; it defaults to 0 and must be non-negative. As the term progresses the Registrar updates `scheduled_hours_to_date` to reflect the curriculum calendar, and each such update recomputes the enrollment's pace. A new enrollment begins in `ACTIVE` status, and creating it transitions the named student's `status` to `ENROLLED`.

At enrollment, the server snapshots the program's charges into the ledger: `total_charges_cents` is the sum of the program's `tuition_cents`, `kit_fee_cents`, and `lab_fee_cents`, fixed at this moment and not re-read if the program is later edited. A fresh enrollment has `total_credits_cents` of 0, so its `ledger_balance_cents` (charges minus credits) initially equals the full charges, a positive number meaning the student owes that amount. The complete ledger rules are in §3.5.

The school monitors **Satisfactory Academic Progress (SAP)** through the enrollment's `pace_pct`. Pace is the student's `actual_hours` divided by `scheduled_hours_to_date`, multiplied by 100 and rounded half up to two decimal places. As a guard against division by zero, when `scheduled_hours_to_date` is 0 the pace is fixed at 100.00. A student is meeting SAP when pace is at least 67.00; a pace strictly below 67.00 fails SAP. The boundary is inclusive on the passing side — a pace of exactly 67.00 passes and is not a warning.

A `Registrar` runs a SAP evaluation on an enrollment, which compares the current pace against the 67.00 threshold and may move the enrollment between `ACTIVE` and `SAP_WARNING`. From `ACTIVE`, if pace is strictly below 67.00, the enrollment transitions to `SAP_WARNING`, its `sap_warning_count` is incremented by one, and its `version` is bumped. From `SAP_WARNING`, if pace has recovered to at least 67.00, the enrollment returns to `ACTIVE` and its `version` is bumped. Each evaluation requires the enrollment to be in the corresponding originating state for its transition to be defined; an evaluation requested from a state with no matching transition is rejected with `ERR_INVALID_STATE`. The two recovery/warning transitions above are the only ones defined, so an evaluation that would be a no-op is likewise rejected with `ERR_INVALID_STATE`: from `ACTIVE` when pace is at least 67.00 (no `ACTIVE`-to-`ACTIVE` transition exists), and from `SAP_WARNING` when pace is still strictly below 67.00 (no `SAP_WARNING`-to-`SAP_WARNING` transition exists). An evaluation requested from any other status (such as `EXAM_PENDING`, `GRADUATED`, or `WITHDRAWN`) is also rejected with `ERR_INVALID_STATE`.

### 3.3. Attendance, Make-Up Sessions, and the Clinic Floor

Hours reach the ledger through two channels: classroom/lab attendance and clinic-floor service. Both flow through an `Instructor`.

**Attendance.** An `Instructor` records an **Attendance Record** against an enrollment by supplying the `enrollment_id`, the recording `instructor_id`, the `session_date_iso`, the `scheduled_hours` for the session (which must be greater than 0), and the `hours` actually attended (which must be non-negative, and is 0 for an absence). A record may be marked as a make-up via `record_type`, which is one of `REGULAR` or `MAKEUP` and defaults to `REGULAR`. The recorded `hours` may not exceed the session's `scheduled_hours`; a record whose `hours` is greater than its `scheduled_hours` is rejected with `ERR_HOURS_EXCEED_SCHEDULED`. A new record begins in `PENDING` status and contributes nothing to the ledger until approved.

An `Instructor` approves a `PENDING` attendance record, moving it to `APPROVED`. Approval is only permitted when the recording instructor is currently on staff (their `active` flag is true) and the instructor's `license_expires_on` is strictly later than the current logical-clock time; an inactive or expired-license instructor is rejected with `ERR_INSTRUCTOR_LICENSE_INVALID`. Approval further requires the owning enrollment to be in either `ACTIVE` or `SAP_WARNING` status. On approval the enrollment's `actual_hours` is recomputed, its `pace_pct` is recomputed from the new hours, its `last_attendance_iso` is advanced to the later of its current value and the record's `session_date_iso`, and the enrollment's `version` is bumped.

A `Registrar` may void an attendance record. Voiding an `APPROVED` record moves it to `VOIDED` and recomputes the enrollment's `actual_hours` downward by exactly that record's contribution — because the recompute is performed from scratch over the remaining approved records, the void leaves no residue — and the enrollment's `pace_pct` and `version` are updated accordingly. Voiding a record that is still `PENDING` also moves it to `VOIDED`, but since a pending record never contributed any hours, no enrollment recompute occurs. A void requested on a record in any other state is rejected with `ERR_INVALID_STATE`.

**Clinic floor.** Once a student has accumulated enough hours, they perform supervised services on paying walk-in clients. An `Instructor` opens a **Clinic Ticket** by supplying the `enrollment_id` of the performing student, the `station_id` occupied, the supervising `instructor_id`, the walk-in `client_name`, the `start_iso` and `end_iso` of the service slot (the end being exclusive), and a `line_items` array in which each entry names a `service_code` and the corresponding `salon_price_cents`. The ticket may carry a `clinic_discount_pct`, the fractional discount off salon price, which must be between 0 and 1 inclusive and defaults to 0.50 (a 50% clinic discount). Opening a ticket sets the chosen station to `OCCUPIED` and computes the ticket's `clinic_hours` from the slot window. A new ticket begins in `OPEN` status.

Opening a ticket is subject to three placement rules. First, the ticket's `start_iso`-to-`end_iso` slot, extended by a 15-minute turnover buffer, must not collide with any non-`VOIDED` ticket on the same station; two tickets on one station that fall within 15 minutes of each other are rejected with `ERR_CLINIC_SLOT_CONFLICT` even when their raw time windows do not actually overlap. Second, the chosen station's `station_type` must match the service category and the station must not be `OUT_OF_SERVICE`; a mismatched or out-of-service station is rejected with `ERR_STATION_UNAVAILABLE`. Because no `service_code`-to-`station_type` taxonomy is defined, the station_type/service-category match imposes no constraint in practice, so this rule reduces to the single check that the station's `status` is not `OUT_OF_SERVICE`: only an `OUT_OF_SERVICE` station triggers `ERR_STATION_UNAVAILABLE`, and a station of any `station_type` in `AVAILABLE` or `OCCUPIED` status passes. The ticket's `clinic_hours` is the difference between `end_iso` and `start_iso` expressed in hours, rounded half up to two decimal places.

An `Instructor` signs off an `OPEN` clinic ticket once the service is complete, moving it to `SIGNED_OFF`. Sign-off requires the supervising instructor to be on staff (`active` true) with a `license_expires_on` strictly later than the current logical clock — otherwise `ERR_INSTRUCTOR_LICENSE_INVALID` — and requires the owning enrollment to be in `ACTIVE` or `SAP_WARNING` status. Critically, sign-off is only allowed once the student has reached the clinic phase: the owning enrollment's `actual_hours` must be at least the program's `clinic_phase_start_hour`. A sign-off attempted before that threshold is rejected with `ERR_CLINIC_PHASE_NOT_REACHED`. On sign-off the ticket's `clinic_hours` is credited into the enrollment's `actual_hours`, the enrollment's `pace_pct` is recomputed, the enrollment's `version` is bumped, and the occupied station is released from `OCCUPIED` back to `AVAILABLE`.

A `Registrar` takes the client's payment on a `SIGNED_OFF` ticket, moving it to `PAID` and computing the ticket's `ticket_total_cents` at that moment (the POS total rule is in §3.5); paying bumps the ticket's `version`. A `Registrar` may also void an `OPEN` ticket, moving it to `VOIDED` and releasing the occupied station back to `AVAILABLE`; because the ticket was never signed off, voiding it credits no clinic hours. A pay or void requested against a ticket not in the required originating state is rejected with `ERR_INVALID_STATE`.

**Station reservations.** Independently of tickets, an `Instructor` may reserve a station for a student over a window by creating a **Station Assignment** with the `station_id`, the `enrollment_id` of the student holding the station, the supervising `instructor_id`, and the `start_iso` and `end_iso` of the reservation window (end exclusive). A reservation begins in `RESERVED` status and sets the station to `OCCUPIED`. The reserved window, treated as the half-open interval from `start_iso` up to but not including `end_iso`, must not overlap any existing `RESERVED` assignment on the same station; an overlapping reservation is rejected with `ERR_STATION_DOUBLE_BOOKED`. Adjacency is permitted — a reservation whose start equals another's end does not overlap. As with clinic tickets, the reserved station's `station_type` must match and it must not be `OUT_OF_SERVICE`, else `ERR_STATION_UNAVAILABLE`; here too the station_type match imposes no constraint in practice and the rule reduces to rejecting only an `OUT_OF_SERVICE` station, with a station of any `station_type` in `AVAILABLE` or `OCCUPIED` status passing. An `Instructor` releases a `RESERVED` assignment, moving it to `RELEASED`, bumping its `version`, and returning the station to `AVAILABLE`.

### 3.4. Title IV Disbursements

A `FinancialAidOfficer` schedules a **Disbursement** of federal aid against an enrollment by naming the `enrollment_id`, the `payment_period` ordinal (which must be 1 or 2), the `period_hours` (the scheduled clock hours that must be completed to earn this period, at least 1), the `period_weeks` (the instructional weeks that must elapse to earn it, at least 1), the `gross_amount_cents` awarded for the period (non-negative), and the `origination_fee_cents` withheld (non-negative, defaulting to 0). Each enrollment may carry at most one non-`RETURNED` disbursement per payment period: scheduling a disbursement whose `payment_period` is not 1 or 2, or that duplicates a payment period already held by another non-`RETURNED` disbursement on the same enrollment, is rejected with `ERR_INVALID_PERIOD`. A new disbursement begins in `SCHEDULED` status.

Posting a `SCHEDULED` disbursement moves it to `POSTED` and is the moment aid actually credits the ledger, so it is gated on the period genuinely having been earned along two dimensions. The clock-hour gate requires the owning enrollment's `actual_hours` to be at least the disbursement's `period_hours`; if not, the post is rejected with `ERR_PERIOD_HOURS_NOT_EARNED`. The time gate requires that the whole number of weeks elapsed since the enrollment's `enrolled_on_iso`, measured against the current logical clock, be at least the disbursement's `period_weeks`; if not, the post is rejected with `ERR_PERIOD_WEEKS_NOT_ELAPSED`. Both gates must clear — the period is earned only at the later of the two. Posting also requires the owning enrollment to be in `ACTIVE` or `SAP_WARNING` status, and it is one of the two optimistic-concurrency-guarded writes: the request must carry `expected_enrollment_version` matching the enrollment's live `version`, failing with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) on a mismatch, as described in §2.7. On a successful post the disbursement's `net_amount_cents` is computed as its `gross_amount_cents` minus its `origination_fee_cents` (an exact integer-cent subtraction), that net amount is added to the enrollment's `total_credits_cents`, the enrollment's `ledger_balance_cents` is recomputed, and the enrollment's `version` is bumped.

A `FinancialAidOfficer` returns a `POSTED` disbursement, moving it to `RETURNED`. A return reverses exactly the previously credited `net_amount_cents`: that amount is subtracted from the enrollment's `total_credits_cents`, the `ledger_balance_cents` is recomputed from scratch, and the enrollment's `version` is bumped. Because the ledger is always recomputed over the set of `POSTED` disbursements rather than adjusted incrementally, a post followed by a return leaves the ledger exactly where it began. A disbursement that is still `SCHEDULED` may also reach `RETURNED` — but only as a side effect of withdrawal finalization (§3.6), and such a never-posted return carries no ledger impact since the scheduled award was never credited. A return requested against a disbursement not in a valid originating state is rejected with `ERR_INVALID_STATE`.

### 3.5. The Ledger, the Clinic POS Total, and the Projected Balance

Three monetary calculations live on the enrollment-and-ticket boundary, and each pins its own rounding discipline.

**The posted ledger.** An enrollment's `total_charges_cents` is the fixed sum of the program's `tuition_cents`, `kit_fee_cents`, and `lab_fee_cents` captured at enrollment. Its `total_credits_cents` is the sum of `net_amount_cents` over only those disbursements on the enrollment whose status is `POSTED` — `SCHEDULED` and `RETURNED` disbursements are excluded. The `ledger_balance_cents` is `total_charges_cents` minus `total_credits_cents`; a positive value means the student still owes that amount, and a value of zero or below means the student owes nothing. All three are exact integer cents, and `total_credits_cents` and `ledger_balance_cents` are recomputed in full whenever a disbursement posts or returns, so that a return compensates exactly.

**The projected balance.** Alongside the posted ledger, the enrollment exposes a provisional, forward-looking view in `projected_balance_cents` for what-if planning before aid posts. The projected credits are the sum of `net_amount_cents` over disbursements whose status is either `POSTED` or `SCHEDULED` (only `RETURNED` is excluded); for a still-`SCHEDULED` disbursement its net is projected as its `gross_amount_cents` minus its `origination_fee_cents` as though it will post. The `projected_balance_cents` is `total_charges_cents` minus those projected credits, in exact integer cents. This figure deliberately diverges from `ledger_balance_cents` whenever an undisbursed `SCHEDULED` award exists, because the projected view counts that award as if it had already arrived while the posted ledger does not.

**The clinic POS total.** When a clinic ticket is paid, its `ticket_total_cents` is computed from the ticket's `line_items` and its `clinic_discount_pct` in a pinned order: for each line item, multiply its `salon_price_cents` by one minus the `clinic_discount_pct`, round that single line to whole cents using round-half-up, and only then sum the rounded line amounts. The discount-and-round is applied per line item before summing, never by summing first and rounding once at the end — the two orders diverge on half-cent line totals, and only the round-per-line-then-sum order is correct here.

### 3.6. Withdrawal, R2T4, and Institutional Refund

When a student leaves, a `FinancialAidOfficer` creates a **Withdrawal** against the enrollment, naming the `enrollment_id`, the `withdrawal_type` (either `OFFICIAL` for a student-initiated withdrawal or `UNOFFICIAL` for an administrative determination), and the `last_date_of_attendance_iso` that serves as the withdrawal date. Creating the withdrawal immediately computes three figures and leaves the record in `CALCULATED` status.

The first computed figure is `pct_completed`, the R2T4 completion percentage: the enrollment's `scheduled_hours_to_date` divided by the program's `total_clock_hours`, multiplied by 100, rounded half up to two decimal places. Note the basis — R2T4 uses *scheduled* hours as of the withdrawal date, not hours actually attended.

The second figure is `title_iv_return_cents`, the federal funds to return. Let the total posted net be the sum of `net_amount_cents` over the enrollment's `POSTED` disbursements only. If `pct_completed` is strictly greater than 60.00, the student is treated as having earned 100% of their aid and `title_iv_return_cents` is 0. Otherwise the earned aid is `pct_completed` divided by 100, multiplied by the total posted net, rounded half up to whole cents; and `title_iv_return_cents` is the total posted net minus that earned amount. The 60.00 boundary is strict — exactly 60.00 does not earn 100% and falls into the return-some branch.

The third figure is `institutional_refund_cents`, the tuition refund the school owes the student, and it deliberately uses a *different* basis than R2T4 — it is driven by hours *actually attended*. Compute the fraction used as the enrollment's `actual_hours` divided by the program's `total_clock_hours`. The refund before the administrative fee is the program's `tuition_cents` multiplied by one minus that used fraction, rounded half up to whole cents. From that, subtract the program's `admin_fee_cap_cents` (the capped institutional administrative fee), and floor the result at 0 so the refund is never negative: `institutional_refund_cents` is the greater of 0 and the refund-before-fee minus the admin-fee cap. Because R2T4 uses scheduled hours while the institutional refund uses actual hours, the two figures will generally differ for the same withdrawal.

A `FinancialAidOfficer` finalizes a `CALCULATED` withdrawal, which is the head of a depth-three cascade. Finalization requires the owning enrollment to be in `ACTIVE` or `SAP_WARNING` status, and it is the second optimistic-concurrency-guarded write: the request must carry `expected_enrollment_version` equal to the enrollment's live `version`, failing with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) on a mismatch as described in §2.7, because a disbursement post or attendance approval occurring after the withdrawal was calculated would have changed the very hours and ledger the R2T4 figures rest on. A finalize requested against a withdrawal not in `CALCULATED` status is rejected with `ERR_INVALID_STATE`.

On a successful finalize the withdrawal moves to `FINALIZED` and the owning enrollment transitions to `WITHDRAWN`, which then drives three cascades on the enrollment's children, all within the same operation: every `SCHEDULED` disbursement on the enrollment is moved to `RETURNED` (and because each such return is processed through the ledger sync, a disbursement that had been posted is debited back out of `total_credits_cents` and the `ledger_balance_cents` recomputed, while a never-posted scheduled disbursement returns with no ledger impact); every `OPEN` clinic ticket on the enrollment is moved to `VOIDED`, releasing its station; and every `RESERVED` station assignment on the enrollment is moved to `RELEASED`, releasing its station. The enrollment's `version` is bumped as part of the finalization. The withdrawal path is available from either `ACTIVE` or `SAP_WARNING`; the originating-state set and the cascade are identical in both cases.

### 3.7. State-Board Exam Readiness, Application, and Graduation

A `Student` drives their own state-board **Exam Application**, and may act only on applications belonging to an enrollment they own — a student touching another enrollment's application is rejected with `ERR_NOT_RESOURCE_OWNER`. The student creates an application naming the `enrollment_id`, the `exam_type` (either `WRITTEN` or `PRACTICAL`), the `mock_exam_avg` (the average of mock-exam scores, between 0 and 100 inclusive), and the `competency_signoff_pct` (the percent of required competencies signed off, between 0 and 100 inclusive). A new application begins in `DRAFT` status.

The student submits the application, moving it from `DRAFT` to `SUBMITTED`; the same submit action also moves an application from `RETURNED_FOR_REVISION` back to `SUBMITTED`, forming a revision cycle. Either submission requires the owning enrollment to be in `ACTIVE` or `SAP_WARNING` status, and recomputes the application's `readiness_score` and bumps the application's `version`. The `readiness_score` is a weighted blend with a pinned rounding order. First compute the hours percentage as the enrollment's `actual_hours` divided by the program's `total_clock_hours`, multiplied by 100, rounded to two decimal places, and cap it at 100 (the hours factor is the lesser of 100 and that percentage). Then form three weighted terms, each rounded half up to two decimal places on its own: the first is 0.40 times the capped hours factor; the second is 0.35 times the `mock_exam_avg`; the third is 0.25 times the `competency_signoff_pct`. The `readiness_score` is the sum of those three already-rounded terms — each term is rounded before summing, not after. A score of 80 or above is the readiness bar.

A `Registrar` adjudicates a `SUBMITTED` application. The Registrar may return it for revision, moving it to `RETURNED_FOR_REVISION`; a return is the appropriate outcome when the application is not yet ready — that is, when the `readiness_score` is below 80, or the `competency_signoff_pct` is below 100, or the enrollment's `actual_hours` is below 90% of the program's `total_clock_hours`. Alternatively the Registrar approves the application, but approval is gated: it requires the `readiness_score` to be at least 80, the `competency_signoff_pct` to equal exactly 100, the enrollment's `actual_hours` to be at least 90% (that is, 0.90 times) the program's `total_clock_hours`, and the owning enrollment to currently be `ACTIVE`. If any of those readiness conditions is unmet, approval is rejected with `ERR_EXAM_NOT_READY`. On approval the application moves to `APPROVED` and, as a cross-entity bubble-up, the owning enrollment transitions from `ACTIVE` to `EXAM_PENDING`, bumping the enrollment's `version`.

From `APPROVED` the Registrar schedules the exam, moving the application to `SCHEDULED`. The Registrar then records the result, supplying `result`. A result of `PASSED` moves a `SCHEDULED` application to `PASSED`; a result of `FAILED` moves it to `FAILED`. Recording a result against an application not in `SCHEDULED` status is rejected with `ERR_INVALID_STATE`.

Recording `PASSED` is the graduation gate. It transitions the owning enrollment from `EXAM_PENDING` to `GRADUATED`, but only when two enrollment-level conditions hold: the enrollment's `actual_hours` must be at least the program's `total_clock_hours`, and the enrollment's `ledger_balance_cents` must be zero or below (no outstanding balance). The balance condition is evaluated before the hours condition: an outstanding balance — a `ledger_balance_cents` greater than 0 — blocks graduation and the result recording is rejected with `ERR_OUTSTANDING_BALANCE` first; only once the balance is zero or below is the hours condition checked, and an `actual_hours` short of the program's `total_clock_hours` blocks graduation and the result recording is rejected with `ERR_INVALID_STATE`. On graduation, all `RESERVED` station assignments for the enrollment are released to `RELEASED`, and the enrollment's `version` is bumped. Recording `FAILED` instead reverts the owning enrollment from `EXAM_PENDING` back to `ACTIVE` so a retake may be pursued, bumping the enrollment's `version`. Both terminal results bump the application's `version`.

### 3.8. Placement Reporting

After a student graduates, a `Registrar` records the post-graduation employment outcome on the enrollment by supplying `placement_status`, set to `PLACED`, `UNPLACED`, or `EXCLUDED`. The enrollment's `placement_status` defaults to `UNREPORTED` until this is recorded. Placement may only be recorded on an enrollment whose status is `GRADUATED`; an attempt to record placement on a non-graduated enrollment is rejected with `ERR_INVALID_STATE`.

A `Registrar` pulls a program's placement report, which aggregates the program's graduates into a placement rate. Across the program's `GRADUATED` enrollments, count the `total_graduates`; count the `excluded_count` of those whose `placement_status` is `EXCLUDED`; and count the `placed_count` of those whose `placement_status` is `PLACED`. The denominator is `total_graduates` minus `excluded_count` — excluded graduates are removed from the denominator entirely, while `UNPLACED` graduates remain in it. If that denominator is zero or below, the `placement_rate_pct` is reported as 0 (there is no division by zero). Otherwise the `placement_rate_pct` is `placed_count` divided by the denominator, multiplied by 100, rounded half up to two decimal places. The report returns the `program_id` together with `total_graduates`, `excluded_count`, `placed_count`, and `placement_rate_pct`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the action/transition endpoints and the test-driving clock — return a `200 OK` status code. Read endpoints return `200 OK`. The complete request bodies, side effects, and computed outputs for each operation are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/school/programs` | Create a program of study; computes credit hours | Registrar |
| GET | `/school/programs/{id}` | Fetch a program | Registrar, FinancialAidOfficer, Instructor, Student |
| GET | `/school/programs` | List programs (paginated) | Registrar, FinancialAidOfficer, Instructor, Student |
| POST | `/school/students` | Register a prospective student | Registrar |
| GET | `/school/students/{id}` | Fetch a student | Registrar, FinancialAidOfficer, Student |
| POST | `/school/instructors` | Create an instructor | Registrar |
| GET | `/school/instructors/{id}` | Fetch an instructor | Registrar, FinancialAidOfficer, Instructor, Student |
| POST | `/school/stations` | Create a floor station | Registrar |
| GET | `/school/stations/{id}` | Fetch a station | Registrar, FinancialAidOfficer, Instructor, Student |
| GET | `/school/stations` | List stations (paginated) | Registrar, FinancialAidOfficer, Instructor, Student |
| POST | `/school/enrollments` | Enroll a student in a program | Registrar |
| GET | `/school/enrollments/{id}` | Fetch an enrollment with computed hours and ledger | Registrar, FinancialAidOfficer, Instructor, Student |
| GET | `/school/enrollments` | List enrollments; filter by student and program | Registrar, FinancialAidOfficer |
| PATCH | `/school/enrollments/{id}` | Update scheduled hours to date | Registrar |
| POST | `/school/enrollments/{id}/evaluate-sap` | Run a SAP evaluation | Registrar |
| POST | `/school/attendance` | Record an attendance/make-up session | Instructor |
| GET | `/school/attendance/{id}` | Fetch a single attendance record | Registrar, Instructor, Student |
| GET | `/school/attendance` | List attendance records; filter by enrollment and instructor | Registrar, Instructor, Student |
| POST | `/school/attendance/{id}/approve` | Approve a pending attendance record | Instructor |
| POST | `/school/attendance/{id}/void` | Void an attendance record | Registrar |
| POST | `/school/clinic-tickets` | Open a clinic-floor service ticket | Instructor |
| GET | `/school/clinic-tickets/{id}` | Fetch a single clinic ticket | Registrar, FinancialAidOfficer, Instructor, Student |
| GET | `/school/clinic-tickets` | List clinic tickets; filter by enrollment, station, instructor | Registrar, FinancialAidOfficer, Instructor, Student |
| POST | `/school/clinic-tickets/{id}/sign-off` | Sign off a clinic service; credit hours, release station | Instructor |
| POST | `/school/clinic-tickets/{id}/pay` | Take client payment; compute POS total | Registrar |
| POST | `/school/clinic-tickets/{id}/void` | Void an open clinic ticket; release station | Registrar |
| POST | `/school/station-assignments` | Reserve a station over a time window | Instructor |
| GET | `/school/station-assignments/{id}` | Fetch a single station assignment | Registrar, Instructor |
| GET | `/school/station-assignments` | List station assignments; filter by station, enrollment, instructor | Registrar, Instructor |
| POST | `/school/station-assignments/{id}/release` | Release a reserved station | Instructor |
| POST | `/school/disbursements` | Schedule a Title IV disbursement for a payment period | FinancialAidOfficer |
| GET | `/school/disbursements/{id}` | Fetch a single disbursement | Registrar, FinancialAidOfficer |
| GET | `/school/disbursements` | List disbursements; filter by enrollment | Registrar, FinancialAidOfficer |
| POST | `/school/disbursements/{id}/post` | Post a scheduled disbursement; OCC-guarded | FinancialAidOfficer |
| POST | `/school/disbursements/{id}/return` | Return a posted disbursement; reverse ledger credit | FinancialAidOfficer |
| POST | `/school/exam-applications` | Create a state-board exam application in DRAFT | Student |
| GET | `/school/exam-applications/{id}` | Fetch a single exam application | Registrar, Student |
| GET | `/school/exam-applications` | List exam applications; filter by enrollment | Registrar, Student |
| POST | `/school/exam-applications/{id}/submit` | Submit or resubmit an exam application | Student |
| POST | `/school/exam-applications/{id}/return` | Return a submitted application for revision | Registrar |
| POST | `/school/exam-applications/{id}/approve` | Approve a ready application; bubble enrollment to EXAM_PENDING | Registrar |
| POST | `/school/exam-applications/{id}/schedule` | Schedule the approved exam | Registrar |
| POST | `/school/exam-applications/{id}/record-result` | Record exam result; graduate or revert the enrollment | Registrar |
| POST | `/school/withdrawals` | Create a withdrawal; compute R2T4 and institutional refund | FinancialAidOfficer |
| GET | `/school/withdrawals/{id}` | Fetch a single withdrawal | Registrar, FinancialAidOfficer |
| GET | `/school/withdrawals` | List withdrawals; filter by enrollment | Registrar, FinancialAidOfficer |
| POST | `/school/withdrawals/{id}/finalize` | Finalize a withdrawal; cascade returns, voids, releases; OCC-guarded | FinancialAidOfficer |
| POST | `/school/enrollments/{id}/placement` | Record post-graduation placement outcome | Registrar |
| GET | `/school/programs/{id}/placement-report` | Aggregate placement-rate report for a program | Registrar |
| POST | `/school/_clock/set_current_utc` | Set the server logical clock | Registrar, FinancialAidOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INSTRUCTOR_LICENSE_INVALID` | 409 |
| `ERR_CLINIC_PHASE_NOT_REACHED` | 409 |
| `ERR_STATION_DOUBLE_BOOKED` | 409 |
| `ERR_CLINIC_SLOT_CONFLICT` | 409 |
| `ERR_STATION_UNAVAILABLE` | 409 |
| `ERR_PERIOD_HOURS_NOT_EARNED` | 409 |
| `ERR_PERIOD_WEEKS_NOT_ELAPSED` | 409 |
| `ERR_EXAM_NOT_READY` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 409 |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 |
| `ERR_INVALID_PERIOD` | 409 |
| `ERR_HOURS_EXCEED_SCHEDULED` | 422 |
