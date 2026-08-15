# Study Abroad Program Administration API — Product Requirements Document

## 1. Introduction

Running a study abroad office means reconciling academic, financial, and safety obligations that no single campus system was designed to hold together. A partner agreement in Lyon or Tokyo defines how credits convert; a catalog program carries its own capacity, deadline, and billing model; each applicant must clear GPA and conduct review, win approval from a second coordinator, pre-clear courses with faculty, arrange emergency insurance that spans the entire program, and — once home — have a transcript converted into posted home credits. Threaded through all of this is a travel-warning policy that can block an approval in an instant or suspend an entire program overnight, with refunds and insurance cancellations following automatically.

This document specifies an API that gives the study abroad office a single system of record for that entire lifecycle, from catalog curation through credit posting. It defines five operator roles with strict segregation of duties, a deterministic logical clock so that deadline and advisory-window decisions are reproducible, dual billing models with portable financial aid, and a set of cascading reconciliation rules that keep programs, applications, billing statements, and insurance enrollments mutually consistent. All endpoints are mounted under the `/api/v1` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `Student`, `ProgramCoordinator`, `FacultyApprover`, `SafetyOfficer`, and `BursarOffice`. A request missing either header, or presenting an `X-User-Role` value outside this list, is rejected with `ERR_UNAUTHENTICATED`. Once authenticated, the caller's role must appear in the endpoint's authorized-role list; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN`.

Identity semantics differ by role. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` record; ownership checks on any resource that references a student compare the resource's student foreign-key field to `X-User-ID`. This governs every student-scoped interaction — application actions, course pre-approval creation and revision, insurance enrollment creation and cancellation, incident reporting, and reading one's own student record: whenever the linked `student_id` does not equal the caller's `X-User-ID`, the request is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `ProgramCoordinator`, `FacultyApprover`, `SafetyOfficer`, or `BursarOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for an actor stamp — for example as `clearance_recorded_by` or `approved_by` on an application, `reviewed_by` on a course pre-approval, `reported_by` on an incident, or `posted_by` on a credit posting — but it does not compare it to any entity's `id`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, consisting of the `req_` prefix followed by 24 lowercase hexadecimal characters.
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

Requests to undefined paths, and requests using an unsupported method on a defined path, surface the standard error envelope with `ERR_NOT_FOUND` and HTTP 404. A request body that is absent or not valid JSON is treated as an empty object, so the first missing required field surfaces `ERR_INVALID_REQUEST`.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order. Filters are exact-match equality on the named field; a filter value that matches no resource simply yields an empty page, and unrecognized query parameters are ignored.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts all matching resources regardless of pagination, and `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the API — partner agreements, programs, students, applications, course pre-approvals, travel advisories, insurance enrollments, billing statements, incidents, and credit postings — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (e.g., `2027-01-15T09:30:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer starting at 1 when the resource is created and incrementing with every modification to the resource, including modifications produced by cascades originating on other resources.

At creation, `created_at` and `updated_at` coincide. Fields that record later workflow stamps are null at creation: `clearance_recorded_by`, `approved_by`, and `withdraw_reason` on applications; `reviewed_by` and `review_notes` on course pre-approvals; `resolution_notes` on incidents; and `posted_by` on credit postings. Applications are born with `transfer_credits_posted` at 0, and billing statements are born with `credit_memo_cents` at 0.

### 2.5. The Logical Clock and Temporal Semantics

All time-dependent rules in this system — application deadlines, advisory windows, insurance coverage windows — are evaluated against a server-side **logical clock**, never against wall-clock time. Before any call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time at any point. A staff-only test-driving capability, available to `ProgramCoordinator`, `SafetyOfficer`, `FacultyApprover`, and `BursarOffice` (but not `Student`), sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` value. Setting the clock validates that `to_iso8601` is a parseable ISO 8601 instant (`ERR_INVALID_REQUEST` otherwise), stores the supplied string verbatim, and echoes that same string as `current_utc`.

ISO 8601 inputs without an explicit offset are interpreted as UTC, and date-time fields on resources (such as `effective_from`, `start_date`, or `coverage_start_date`) are stored and returned exactly as supplied, without normalization. Resource `created_at`/`updated_at` values and the envelope's `api_request_timestamp` are generated from the server's wall clock in UTC; the logical clock governs rule evaluation only.

Travel advisory windows are half-open intervals: `effective_from` is inclusive and `effective_to` is exclusive, so an advisory is in effect at exactly those instants greater than or equal to `effective_from` and strictly before `effective_to`. Deadline comparisons ask whether the logical clock has passed a stored instant; a clock reading exactly equal to `application_deadline` has not passed it.

### 2.6. Money and Credit Precision

All monetary amounts are represented as integer cents; no floating-point arithmetic is permitted anywhere in billing. Exactly one rounding operation exists in the billing pipeline: a floor applied to the aid-cap product (see §3.4). Every other billing figure — bases, premiums, fees, portable aid, charges, payments, credit memos, outstanding balances — is exact integer arithmetic.

Academic credit conversion follows a different, equally strict rule. Each course's converted home-credit value is rounded individually to the nearest half credit (a step of 0.5), using round half up with ties away from zero, **before** any summation takes place; the resulting per-course values are then summed exactly. Summing raw unrounded values and rounding the total produces different numbers and is not the contract.

### 2.7. Hierarchical Consistency and Cascading Reconciliation

A program's catalog status, its applications, and each application's financial and insurance records form a consistency web. When a parent-level event invalidates dependent records — a travel advisory suspending a program, a withdrawal voiding a billing statement — the server reconciles every dependent record automatically within the same operation, without requiring explicit client requests against those dependents. Each reconciled resource is itself mutated: its `version` increments and its `updated_at` refreshes. The same holds for the program's seat counter, which moves up and down as applications commit, withdraw, and return (§3.4), and for the application's own `version`, which advances when a course pre-approval is created beneath it (§3.3).

### 2.8. Nested Resource Retrieval

Several resources are addressed beneath a parent application — course pre-approvals and credit postings live under the application they belong to. For any request whose path contains multiple resource identifiers, the server validates identifiers sequentially, left to right: the parent application's id is resolved before any child id is examined. The request is rejected immediately with `ERR_NOT_FOUND` for the *first* identifier that does not resolve to an existing resource, and no further validation or processing occurs.

### 2.9. Optimistic Concurrency Control

Exactly one write operation participates in optimistic concurrency control: creating a course pre-approval under an application. That request must carry `expected_application_version`, a non-optional integer field holding the parent application's `version` as last observed by the client; a missing, null, or non-integer value fails request-body integrity with `ERR_INVALID_REQUEST`. If the application's current `version` does not match — because another writer has advanced it in the meantime, for instance by creating a pre-approval that superseded a prior record for the same course — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the application. The version comparison is evaluated after request-body integrity passes and before any record is created or superseded. No other endpoint accepts or requires a version field.

### 2.10. Validation Ordering

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic:

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is recognized — otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The caller's role is permitted on the endpoint; additionally, for `Student`-role calls on student-scoped resources, the linked `student_id` must equal `X-User-ID` — otherwise `ERR_FORBIDDEN`.
3. **Existence.** Path identifiers resolve to existing resources, validated left to right — otherwise `ERR_NOT_FOUND`.
4. **Request-body integrity.** Required fields are present, types are valid, enum members are valid, and ranges hold: `capacity` at least 1, `gpa` between 0.0 and 4.0 inclusive, `effective_from` strictly before `effective_to`, `start_date` strictly before `end_date`, `coverage_start_date` strictly before `coverage_end_date`, `host_credits` greater than 0, `credit_conversion_factor` greater than 0. The conditional fee rule is evaluated at this tier as well: a program whose `billing_model` is `PROGRAM_FEE` requires a positive `program_fee_cents` (`ERR_PROGRAM_FEE_REQUIRED`), while a `HOME_TUITION` program must omit `program_fee_cents` or set it to 0 (`ERR_INVALID_REQUEST`). Other schema failures also surface as `ERR_INVALID_REQUEST`. Fields beyond those defined for an endpoint are ignored rather than rejected.
5. **State-machine preconditions and cross-entity state gates.** The target resource must be in a valid from-state for the requested transition, and cross-entity gates must hold: approval and commitment require the program to be `OPEN`, departure requires the application to be `COMMITTED`, credit-posting creation and posting require the application to be `RETURNED_HOME`, and incident reporting requires the application to be `ABROAD` — otherwise `ERR_INVALID_STATE`.
6. **Segregation of duties on approval.** A record-dependent authorization, evaluated only after the state checks pass — otherwise `ERR_SEGREGATION_OF_DUTIES`.
7. **Safety gates.** The travel-warning gate on application approval and insurance enrollment creation, and the insurance-cancel safety lock — surfacing as `ERR_TRAVEL_ADVISORY_BLOCK` or `ERR_CANNOT_CANCEL_WHILE_ABROAD` respectively.
8. **Referential integrity beyond path ids.** Transcript lines must reference valid approved pre-approvals, departure requires covering insurance, and publishing requires a partner agreement that exists and is `ACTIVE` — surfacing as `ERR_PREAPPROVAL_INVALID`, `ERR_INSURANCE_COVERAGE_MISSING`, or `ERR_AGREEMENT_NOT_ACTIVE`. At this tier, a body-referenced program or agreement that does not exist at all surfaces as `ERR_NOT_FOUND`, while a program that exists but is not `OPEN` surfaces as `ERR_INVALID_STATE`.
9. **Temporal rules.** Application deadline, advisory window overlap, the host-institution schedule buffer, and insurance coverage containment — surfacing as `ERR_APPLICATION_DEADLINE_PASSED`, `ERR_ADVISORY_WINDOW_OVERLAP`, `ERR_PROGRAM_SCHEDULE_BUFFER`, or `ERR_COVERAGE_WINDOW_INSUFFICIENT`.
10. **Domain constraints.** GPA minimum, conduct hold, duplicate active applications, duplicate active enrollments, duplicate credit postings, and transcript grade range — surfacing as `ERR_GPA_BELOW_MINIMUM`, `ERR_CONDUCT_HOLD`, `ERR_DUPLICATE_APPLICATION`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_CREDIT_POSTING`, or `ERR_GRADE_OUT_OF_RANGE`.
11. **Money and capacity checks last.** Seat availability on commitment and payment amount rules on billing statements — surfacing as `ERR_PROGRAM_FULL`, `ERR_PAYMENT_NOT_POSITIVE`, or `ERR_OVERPAYMENT`.

## 3. Business Logic & Workflows

### 3.1. Curating the Catalog: Partner Agreements and Programs

Before any program can exist, a `ProgramCoordinator` registers the **partner agreement** that governs a host institution. The record captures the `host_institution` name, the ISO 3166-1 alpha-2 `country_code` (for example `FR` or `JP`; codes are stored as supplied, with no format enforcement), the `effective_from` and `effective_to` instants bounding the agreement's validity — the latter strictly after the former — and a `credit_conversion_factor`, a positive multiplier (such as 0.75) that converts host-institution credits into home credits. An optional `insurance_required` flag, defaulting to `false` and required to be a boolean when supplied, declares whether programs under this agreement demand emergency insurance enrollment. Agreements are born in `DRAFT` status; activation by a `ProgramCoordinator` moves an agreement from `DRAFT` to `ACTIVE`, incrementing its `version`. Only `ACTIVE` agreements can underpin a published program.

With an agreement in place, the coordinator creates a catalog **program**, referencing its governing agreement via `partner_agreement_id`. The program carries a display `name` (for example, "Lyon Spring 2027 Exchange"), the destination `country_code`, the `host_institution` name, an academic `term` of `SPRING`, `SUMMER`, `FALL`, or `ACADEMIC_YEAR`, the `start_date` and `end_date` (end strictly after start), the `application_deadline` after which new applications are refused, a `capacity` of at least 1 committed seat, and a `min_gpa` between 0.0 and 4.0 inclusive that applicants must meet or exceed. The `billing_model` declares how enrolled students are charged — `HOME_TUITION` or `PROGRAM_FEE` — and obeys the conditional fee rule of §2.10: `PROGRAM_FEE` programs carry a positive integer `program_fee_cents` (a missing, non-integer, or non-positive value surfaces `ERR_PROGRAM_FEE_REQUIRED`), while `HOME_TUITION` programs carry none — the field is stored and returned as 0. New programs are born in `DRAFT` with `seats_taken` at 0.

Creation also enforces a scheduling courtesy between programs sharing a host institution. If another program at the same `host_institution` exists in `DRAFT` or `OPEN` status whose dates are separated from the new program's dates by fewer than seven days in either direction, the create is rejected with `ERR_PROGRAM_SCHEDULE_BUFFER`; a separation of exactly seven days is permitted, and `SUSPENDED` programs do not participate in the check. Separation is measured between the exact parsed instants, seven days meaning precisely 168 hours. Publishing moves a program from `DRAFT` to `OPEN` and is gated on the partner agreement: the referenced agreement must exist (`ERR_NOT_FOUND`) and be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`). Once `OPEN`, a program accepts applications. Catalog browsing supports filters on `country_code`, `status`, `host_institution`, and `partner_agreement_id`, and reading a single program always includes the computed `seats_taken` described in §3.4.

### 3.2. Students, Applications, and the Clearance Pipeline

Student records arrive through registrar import: a `ProgramCoordinator` registers each student with a `full_name`, university `email`, cumulative `gpa` between 0.0 and 4.0 inclusive, a `conduct_standing` of `GOOD_STANDING`, `CONDUCT_REVIEW`, or `CONDUCT_HOLD`, and an optional `aid_award_cents` — the total financial aid award in cents considered for portability — defaulting to 0 and never negative. A `Student` caller may read only its own record; coordinators read any.

An applicant submits an **application** with a payload containing the `student_id` and the target `program_id`; the caller's `X-User-ID` must equal the `student_id`. Submission runs the gauntlet of §2.10: the referenced program must exist (`ERR_NOT_FOUND`), then the referenced student must exist (`ERR_NOT_FOUND`), then the program must be `OPEN` (`ERR_INVALID_STATE`), checked in that order; the logical clock must not have passed the program's `application_deadline` (`ERR_APPLICATION_DEADLINE_PASSED`); the student's `gpa` must be at least the program's `min_gpa` (`ERR_GPA_BELOW_MINIMUM`); a `conduct_standing` of `CONDUCT_HOLD` is an absolute bar (`ERR_CONDUCT_HOLD`), though `CONDUCT_REVIEW` is not; and the student may hold at most one active application per program — an existing application for the same `(student_id, program_id)` pair in any of `SUBMITTED`, `RETURNED_FOR_REVISION`, `CLEARED`, `APPROVED`, `COMMITTED`, `ABROAD`, or `RETURNED_HOME` triggers `ERR_DUPLICATE_APPLICATION`. On acceptance the application is born `SUBMITTED`, and the student's `aid_award_cents` is frozen into `aid_award_cents_snapshot`; all billing computations use the snapshot, never the live student field.

Clearance is recorded by a `ProgramCoordinator` against a `SUBMITTED` application. The `decision` is one of `CLEARED`, `RETURNED_FOR_REVISION`, or `REJECTED`; whichever decision is recorded, the application takes that status and `clearance_recorded_by` is stamped with the caller's `X-User-ID`. `REJECTED` is terminal. A `RETURNED_FOR_REVISION` application can be resubmitted by its owning student, looping back to `SUBMITTED`; resubmission resets `clearance_recorded_by` to null so that a fresh clearance review is required before any approval, and re-runs none of the submission gates — deadline, GPA, conduct, and duplicate checks are not re-evaluated.

Approval is deliberately separated from clearance. A `ProgramCoordinator` approves a `CLEARED` application only when the program is still `OPEN` (otherwise `ERR_INVALID_STATE`), when the caller's `X-User-ID` differs from the application's `clearance_recorded_by` — the segregation-of-duties rule, rejecting with `ERR_SEGREGATION_OF_DUTIES` — and when the travel-warning gate of §3.6 is clear (`ERR_TRAVEL_ADVISORY_BLOCK`). A successful approval stamps `approved_by` with the approver's identity and moves the application to `APPROVED`.

Withdrawal is available from `SUBMITTED`, `RETURNED_FOR_REVISION`, `CLEARED`, `APPROVED`, and `COMMITTED`, and may be initiated by the owning student or by a `ProgramCoordinator`. The application records a `withdraw_reason` of `STUDENT_INITIATED` when the student acts and `STAFF_INITIATED` when a coordinator acts; a third reason, `SYSTEM_SUSPENSION`, is reserved for the advisory cascade of §3.6 and is never set by a manual call. Withdrawing from `COMMITTED` carries financial consequences described fully in §3.4 and §3.5: the seat is released, the billing statement is voided with a refund credit memo, and any `ACTIVE` insurance enrollment is cancelled. `WITHDRAWN` is terminal, as are `REJECTED` and the end-of-journey `CREDIT_POSTED`.

### 3.3. Course Pre-Approvals and Faculty Review

Academic planning begins once a student has an application on file. The owning student creates a **course pre-approval** under the application, supplying the host institution's `course_code` and `course_title`, the `host_credits` value (strictly greater than 0), and — per §2.9 — the `expected_application_version` guarding against stale views; a mismatch with the application's current `version` is rejected with `ERR_STALE_VERSION`. Creation advances the parent application's `version` and is not gated on the application's status. At most one record per `(application_id, course_code)` pair may be live: if an existing record with the same `course_code` for the same application is in `PENDING` or `APPROVED`, the new create supersedes it, moving the older record to `SUPERSEDED` whether it was `PENDING` or `APPROVED`.

Every new record is born `PENDING` and immediately carries a computed `home_credits_est`: the `host_credits` multiplied by the governing agreement's `credit_conversion_factor`, with the product rounded to the nearest half credit, ties rounding away from zero. This per-course rounding rule is pinned system-wide and resurfaces verbatim in transcript conversion (§3.8).

A `FacultyApprover` then reviews each `PENDING` record, recording a `decision` of `APPROVED`, `NEEDS_REVISION`, or `REJECTED`. All three decisions stamp `reviewed_by` with the reviewer's `X-User-ID` and store the payload's `review_notes` (which may be omitted or null). `REJECTED` is terminal; `APPROVED` records become the currency of credit posting on return. A student whose plan comes back `NEEDS_REVISION` revises it — supplying a new `host_credits` and optionally a new `course_title` — which loops the record back to `PENDING` and recomputes `home_credits_est` under the same per-course rounding; an omitted `course_title` leaves the prior title unchanged, and the prior `reviewed_by` and `review_notes` are retained until the next review overwrites them. Neither review nor revision is gated on the parent application's status. Pre-approval listings under an application are visible to `ProgramCoordinator`, `FacultyApprover`, and the owning student.

### 3.4. Commitment, Seats, and the Billing Statement

Commitment is the student's own act: the owner of an `APPROVED` application commits, provided the program is still `OPEN` (`ERR_INVALID_STATE`) and still has room — the program's `seats_taken` must be strictly less than its `capacity`, else `ERR_PROGRAM_FULL`. A successful commit moves the application to `COMMITTED`, increments the program's `seats_taken` by one, and bumps the program's `version`. In the same operation the server creates the application's **billing statement** in `ISSUED` status. Statements are never created directly; commit is their only origin. The statement freezes the program's `billing_model` into `billing_model_snapshot` at commit time and computes its money fields from the snapshot of the student's aid. The commit response returns the updated application object.

Two billing models produce different charges from the same student data. Under the home-tuition model, `base_cents` is the university-wide home tuition constant of 2400000 cents ($24,000 per term); under the program-fee model, `base_cents` is the program's own `program_fee_cents`. When the program's partner agreement has `insurance_required` set, an `insurance_premium_cents` of 35000 cents ($350) is added; otherwise the premium is 0. An `application_fee_cents` of 5000 cents ($50) always applies. Aid portability is capped: `aid_portable_cents` is the lesser of the application's `aid_award_cents_snapshot` and the floor of the cap percentage times `base_cents` — the cap is 100% of base under `HOME_TUITION` and 60% of base under `PROGRAM_FEE`. The resulting `charge_cents` is the base plus the premium plus the fee minus the portable aid, and `outstanding_cents` is the charge minus `amount_paid_cents`, which starts at 0. All figures are integer cents; the floor on the aid-cap product is the only rounding in the pipeline.

The `BursarOffice` records payments against a statement by submitting an `amount_cents`. Payments are accepted only while the statement is `ISSUED` or `PARTIALLY_PAID`; against any other status the attempt fails with `ERR_INVALID_STATE`. The amount must be positive (`ERR_PAYMENT_NOT_POSITIVE`) and no greater than the current `outstanding_cents` (`ERR_OVERPAYMENT`). A payment strictly below the outstanding balance moves an `ISSUED` statement to `PARTIALLY_PAID`, and further partial payments keep it in `PARTIALLY_PAID`; a payment exactly equal to the outstanding balance moves the statement — from either `ISSUED` or `PARTIALLY_PAID` — to `PAID`, forcing `outstanding_cents` to 0. Every accepted payment adds to `amount_paid_cents`, recomputes `outstanding_cents`, and bumps the statement's `version`.

The `seats_taken` counter on a program is a derived figure with an exact definition: it counts precisely the program's applications in `COMMITTED` or `ABROAD` status — applications holding a seat. `SUBMITTED`, `RETURNED_FOR_REVISION`, `CLEARED`, `APPROVED`, `RETURNED_HOME`, and all terminal statuses are excluded. The counter rises by one at commit and falls by one when a committed application withdraws and again when an abroad student's return is recorded (§3.8).

Voiding is the statement's compensating path. When an application withdraws from `COMMITTED` — manually per §3.2 or via the suspension cascade per §3.6 — its statement, whether `ISSUED`, `PARTIALLY_PAID`, or `PAID`, transitions to `VOID`: `credit_memo_cents` is set to the full `amount_paid_cents` (a complete refund of monies actually paid) and `outstanding_cents` is forced to 0. `VOID` is terminal. Statements are listed and read by `BursarOffice` and `ProgramCoordinator`, with list filters on `application_id` and `status`.

### 3.5. Insurance Enrollment and Departure Clearance

A committed student traveling under an agreement that requires insurance must enroll before departure — and may enroll regardless, subject to the rules here. The owning student creates an **insurance enrollment** for a `COMMITTED` application, supplying the `application_id`, the `provider` name, and the coverage window: `coverage_start_date` must fall at or before the program's `start_date`, and `coverage_end_date` must fall at or after the program's `end_date` while remaining strictly after the coverage start. A window that fails to fully contain the program dates is rejected with `ERR_COVERAGE_WINDOW_INSUFFICIENT`. Enrollment creation is also subject to the travel-warning gate of §3.6, rejecting with `ERR_TRAVEL_ADVISORY_BLOCK` when a blocking advisory is in force. At most one `ACTIVE` enrollment may exist per application (`ERR_DUPLICATE_ENROLLMENT`). Enrollments are born `ACTIVE`.

Cancellation moves an `ACTIVE` enrollment to `CANCELLED`, terminally. The owning student or a `ProgramCoordinator` may cancel, but never while the linked application is `ABROAD` — the safety lock rejects that attempt with `ERR_CANNOT_CANCEL_WHILE_ABROAD`, since a student on site must not lose coverage mid-program. The withdrawal cascades of §3.2 and §3.6 cancel enrollments automatically and are not subject to that lock.

Departure itself is recorded by a `ProgramCoordinator` through the application's lifecycle bookkeeping with `action` set to `DEPART`, moving a `COMMITTED` application to `ABROAD`. The gate is insurance: an `ACTIVE` enrollment for the application must exist whose coverage fully contains the program dates — `coverage_start_date` at or before `start_date` and `coverage_end_date` at or after `end_date` — otherwise the transition fails with `ERR_INSURANCE_COVERAGE_MISSING`. `ABROAD` applications continue to hold their seat, so recording departure changes neither `seats_taken` nor the program's `version`. Enrollment listings and reads are shared by `ProgramCoordinator`, `BursarOffice`, and the owning student, filterable by `application_id` and `status`; a `Student` caller's list results are scoped to enrollments of that student's own applications.

### 3.6. Travel Advisories and Emergency Suspension

Health and safety oversight rests with the `SafetyOfficer`, who publishes **travel advisories** scoped to a `country_code` with a severity `level` of `CAUTION`, `WARNING`, or `DO_NOT_TRAVEL`, bounded by `effective_from` (inclusive) and `effective_to` (exclusive, strictly later). Advisories are born `ACTIVE`. One country's advisories must not contradict one another: a new advisory is rejected with `ERR_ADVISORY_WINDOW_OVERLAP` if its half-open window intersects that of another `ACTIVE` advisory for the same `country_code` — though pure adjacency, where one advisory's `effective_to` equals the other's `effective_from`, is not an overlap and is permitted.

The advisory machinery gates two distinct operations. Application approval (§3.2) and insurance enrollment creation (§3.5) are both blocked with `ERR_TRAVEL_ADVISORY_BLOCK` whenever an `ACTIVE` advisory exists with `level` `DO_NOT_TRAVEL` whose `country_code` matches the program's, whose window is in effect at the logical clock — `effective_from` at or before the clock and `effective_to` strictly after it — and whose window overlaps the program's `[start_date, end_date]` span. Overlap here is evaluated with inclusive boundaries: the gate fires when the advisory's `effective_from` is at or before the program's `end_date` and its `effective_to` is at or after the program's `start_date`, so an advisory whose `effective_to` exactly equals the program's `start_date` still blocks.

Creating a `DO_NOT_TRAVEL` advisory can do far more than gate. When its window **fully contains** an `OPEN` program's dates — `effective_from` at or before the program's `start_date` and `effective_to` at or after its `end_date` — for a matching `country_code`, the program is suspended: it transitions from `OPEN` to `SUSPENDED`, terminally, with its `version` incremented. The cascade continues to the program's applications: every application in `APPROVED` or `COMMITTED` is withdrawn with `withdraw_reason` set to `SYSTEM_SUSPENSION`, while `CLEARED` applications are deliberately left untouched. Each of those withdrawals fires the withdrawal side effects of §3.2 — and for withdrawn `COMMITTED` applications that means the seat is released (`seats_taken` decremented, program `version` bumped again per §2.7), the billing statement is voided with the full refund credit memo of §3.4, and any `ACTIVE` insurance enrollment is cancelled.

Lifting an advisory — `ACTIVE` to `LIFTED`, a `SafetyOfficer` action — closes the window going forward but is deliberately not retroactive: previously suspended programs remain `SUSPENDED`, and withdrawn applications remain `WITHDRAWN`.

### 3.7. On-Site Incident Management

While students are abroad, incidents are reported against applications in `ABROAD` status; reporting against any other application status fails with `ERR_INVALID_STATE`. The reporter is either the owning student or a `ProgramCoordinator`, supplying the `application_id`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and a free-text `description`. The incident is born `REPORTED` with `reported_by` stamped from the caller's `X-User-ID`.

Triage belongs to the `SafetyOfficer`, who advances the incident by naming a `to_state`. The ladder runs `REPORTED` → `TRIAGED` → `ESCALATED` → `RESOLVED`, with one shortcut: a `TRIAGED` incident may move directly to `RESOLVED`. Both resolution paths — from `TRIAGED` and from `ESCALATED` — capture the payload's `resolution_notes` onto the incident, and those notes may be omitted or null. `RESOLVED` is terminal. Incident lists and reads are shared by `SafetyOfficer` and `ProgramCoordinator`, filterable by `application_id` and `status`.

### 3.8. Return, Transcripts, and Credit Posting

When a student comes home, a `ProgramCoordinator` records the return through lifecycle bookkeeping with `action` set to `RECORD_RETURN`, moving the application from `ABROAD` to `RETURNED_HOME`. Because `RETURNED_HOME` sits outside the seat-holding set, the program's `seats_taken` falls by one and the program's `version` increments.

Credit conversion on return begins when a `FacultyApprover` uploads the return transcript as a **credit posting** under a `RETURNED_HOME` application — any other application status yields `ERR_INVALID_STATE`. The payload's `lines` array carries one object per course, each pairing a `course_preapproval_id` with the earned `grade_points`. `lines` must be present and be an array (`ERR_INVALID_REQUEST` otherwise), a check evaluated before the `RETURNED_HOME` state gate; the contents of individual line objects are validated only after that gate passes. An empty `lines` array is accepted, producing zero totals. Every `grade_points` must lie between 0.0 and 4.0 inclusive (`ERR_GRADE_OUT_OF_RANGE`), and every `course_preapproval_id` must reference a pre-approval that belongs to this same application and is in `APPROVED` status (`ERR_PREAPPROVAL_INVALID`). An application carries at most one credit posting in `PENDING` or `POSTED` (`ERR_DUPLICATE_CREDIT_POSTING`).

The posting is born `PENDING` with two computed totals. Both reuse the pinned per-course rule of §3.3: each line's `host_credits` — read from the referenced pre-approval — is multiplied by the agreement's `credit_conversion_factor` and rounded to the nearest half credit, ties away from zero, before any summation. `provisional_credits` sums those per-course values over **all** transcript lines regardless of grade, giving the planning view; `final_credits` sums only lines whose `grade_points` are at least 2.0, with weaker lines contributing nothing. Summing raw products and rounding once at the end is expressly not the contract. Totals that land on a whole number are serialized as integers (for example, `3` rather than `3.0`).

Posting is the final act. A `FacultyApprover` posts a `PENDING` credit posting; the linked application must be `RETURNED_HOME` at that moment (`ERR_INVALID_STATE`). Posting stamps `posted_by` with the caller's `X-User-ID`, moves the posting to `POSTED` (terminal), and cascades to the application: `RETURNED_HOME` → `CREDIT_POSTED`, with the application's `transfer_credits_posted` set to the posting's `final_credits`. Credit posting listings under an application are visible to `FacultyApprover`, `ProgramCoordinator`, and the owning student.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new resources to a collection return a `201 Created` status code. Operations that modify an existing resource — state transitions, payments, reviews, and similar actions — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/partner-agreements` | Create a partner agreement in `DRAFT` | ProgramCoordinator |
| POST | `/api/v1/partner-agreements/{id}/activate` | Activate a `DRAFT` agreement (`DRAFT` → `ACTIVE`) | ProgramCoordinator |
| POST | `/api/v1/programs` | Create a catalog program in `DRAFT`; runs the 7-day host-institution schedule-buffer check | ProgramCoordinator |
| GET | `/api/v1/programs` | List programs with filters and pagination | ProgramCoordinator, Student, FacultyApprover, SafetyOfficer, BursarOffice |
| GET | `/api/v1/programs/{id}` | Read one program including computed `seats_taken` | ProgramCoordinator, Student, FacultyApprover, SafetyOfficer, BursarOffice |
| POST | `/api/v1/programs/{id}/publish` | Publish a `DRAFT` program (`DRAFT` → `OPEN`); requires an `ACTIVE` partner agreement | ProgramCoordinator |
| POST | `/api/v1/students` | Register a student record (registrar import) | ProgramCoordinator |
| GET | `/api/v1/students/{id}` | Read a student; `Student` role may read only its own record | ProgramCoordinator, Student |
| POST | `/api/v1/applications` | Submit an application to an `OPEN` program; runs deadline, GPA, conduct, and duplicate checks; snapshots aid | Student |
| GET | `/api/v1/applications` | List applications with filters (`student_id` / `program_id` / `status`) and pagination | ProgramCoordinator |
| GET | `/api/v1/applications/{id}` | Read one application; `Student` role may read only its own | ProgramCoordinator, Student |
| POST | `/api/v1/applications/{id}/clearance` | Record clearance decision on a `SUBMITTED` application: `CLEARED`, `RETURNED_FOR_REVISION`, or `REJECTED` | ProgramCoordinator |
| POST | `/api/v1/applications/{id}/resubmit` | Resubmit a `RETURNED_FOR_REVISION` application back to `SUBMITTED` | Student |
| POST | `/api/v1/applications/{id}/approve` | Approve a `CLEARED` application; program `OPEN`, travel gate clear, approver different from clearance recorder | ProgramCoordinator |
| POST | `/api/v1/applications/{id}/commit` | Owning student commits; consumes a seat and issues the billing statement | Student |
| POST | `/api/v1/applications/{id}/withdraw` | Withdraw from `SUBMITTED`, `RETURNED_FOR_REVISION`, `CLEARED`, `APPROVED`, or `COMMITTED`; voids billing and cancels insurance when committed | Student, ProgramCoordinator |
| POST | `/api/v1/applications/{id}/lifecycle` | Departure/return bookkeeping: `DEPART` (`COMMITTED` → `ABROAD`) or `RECORD_RETURN` (`ABROAD` → `RETURNED_HOME`) | ProgramCoordinator |
| POST | `/api/v1/applications/{id}/course-preapprovals` | Create a course pre-approval; supersedes a live same-`course_code` record; OCC-guarded by `expected_application_version` | Student |
| GET | `/api/v1/applications/{id}/course-preapprovals` | List course pre-approvals of an application | ProgramCoordinator, FacultyApprover, Student |
| POST | `/api/v1/course-preapprovals/{id}/review` | Faculty review of a `PENDING` pre-approval: `APPROVED`, `NEEDS_REVISION`, or `REJECTED` | FacultyApprover |
| POST | `/api/v1/course-preapprovals/{id}/revise` | Student revises a `NEEDS_REVISION` pre-approval back to `PENDING` | Student |
| POST | `/api/v1/travel-advisories` | Create an advisory (`ACTIVE`); rejects window overlap; a containing `DO_NOT_TRAVEL` advisory suspends matching `OPEN` programs | SafetyOfficer |
| POST | `/api/v1/travel-advisories/{id}/lift` | Lift an `ACTIVE` advisory (`ACTIVE` → `LIFTED`); does not un-suspend programs | SafetyOfficer |
| POST | `/api/v1/insurance-enrollments` | Enroll a `COMMITTED` application in emergency insurance; coverage must contain program dates; travel gate applies | Student |
| GET | `/api/v1/insurance-enrollments` | List insurance enrollments, filterable by `application_id` / `status` | ProgramCoordinator, BursarOffice, Student |
| GET | `/api/v1/insurance-enrollments/{id}` | Read one enrollment; `Student` role only for own application's enrollment | ProgramCoordinator, BursarOffice, Student |
| POST | `/api/v1/insurance-enrollments/{id}/cancel` | Cancel an `ACTIVE` enrollment; forbidden while the linked application is `ABROAD` | Student, ProgramCoordinator |
| GET | `/api/v1/billing-statements` | List billing statements, filterable by `application_id` / `status` | BursarOffice, ProgramCoordinator |
| GET | `/api/v1/billing-statements/{id}` | Read one billing statement including computed `outstanding_cents` | BursarOffice, ProgramCoordinator |
| POST | `/api/v1/billing-statements/{id}/payments` | Record a payment against an `ISSUED`/`PARTIALLY_PAID` statement; exact outstanding amount transitions to `PAID` | BursarOffice |
| POST | `/api/v1/incidents` | Report an on-site incident for an `ABROAD` application | Student, ProgramCoordinator |
| GET | `/api/v1/incidents` | List incidents, filterable by `application_id` / `status` | SafetyOfficer, ProgramCoordinator |
| GET | `/api/v1/incidents/{id}` | Read one incident | SafetyOfficer, ProgramCoordinator |
| POST | `/api/v1/incidents/{id}/transition` | Advance triage: `REPORTED` → `TRIAGED` → `ESCALATED` → `RESOLVED`, or `TRIAGED` → `RESOLVED` | SafetyOfficer |
| POST | `/api/v1/applications/{id}/credit-postings` | Upload a return transcript as a `PENDING` credit posting; computes `provisional_credits` and `final_credits` | FacultyApprover |
| GET | `/api/v1/applications/{id}/credit-postings` | List credit postings of an application | FacultyApprover, ProgramCoordinator, Student |
| POST | `/api/v1/credit-postings/{id}/post` | Post a `PENDING` posting; flips the application to `CREDIT_POSTED` with `transfer_credits_posted` set to `final_credits` | FacultyApprover |
| POST | `/api/v1/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock; initially 2026-08-01T00:00:00Z, never wall-clock | ProgramCoordinator, SafetyOfficer, FacultyApprover, BursarOffice |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_FEE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_GPA_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CONDUCT_HOLD` | 422 Unprocessable Entity |
| `ERR_APPLICATION_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_PROGRAM_FULL` | 409 Conflict |
| `ERR_TRAVEL_ADVISORY_BLOCK` | 422 Unprocessable Entity |
| `ERR_PROGRAM_SCHEDULE_BUFFER` | 409 Conflict |
| `ERR_ADVISORY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COVERAGE_WINDOW_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_INSURANCE_COVERAGE_MISSING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_CANNOT_CANCEL_WHILE_ABROAD` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_POSITIVE` | 422 Unprocessable Entity |
| `ERR_PREAPPROVAL_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CREDIT_POSTING` | 409 Conflict |
| `ERR_GRADE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
