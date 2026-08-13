# School Immunization Compliance & Exclusion API — Product Requirements Document

## 1. Introduction

District health services carries a legal obligation that recurs every academic year: every enrolled student must either present verified evidence of the immunizations required for their grade, hold an approved exemption, or — after due notice — be excluded from attendance. Today that obligation is met with binders, spreadsheets, and phone calls to the state registry, and the cost of a missed deadline is measured in audit findings and, in the worst case, an outbreak spreading through a school whose exempt students were never identified in time.

This document specifies the School Immunization Compliance & Exclusion API, the system of record for that obligation. The API covers the full arc of the compliance calendar: intake of student enrollment with a provisional window for families to produce records, configuration of grade-scoped vaccine requirements per school year, entry and verification of dose records, adjudication of medical and religious exemption requests under segregation of duties, issuance of non-compliance notices with a fixed grace period before exclusion, outbreak-triggered suspension of exemptions and immediate exclusion of exempt students, reconciliation against the state immunization registry, coordination of catch-up clinic sessions, and the annual compliance-rate reporting the district files with the state.

Two design commitments shape everything that follows. First, the system runs on a **logical clock** rather than wall-clock time, so that provisional deadlines, exclusion dates, and academic-year boundaries are deterministic and testable. Second, compliance is always evaluated through two lenses — what the district's own verified records show, and what those records show once the state registry has been reconciled in — because official enforcement decisions and official annual reports deliberately use different lenses.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `HealthClerk`, `SchoolNurse`, `DistrictHealthOfficer`, and `RegistryCoordinator`. A request missing either header, or presenting an `X-User-Role` value that is not one of these four declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

All four roles use an opaque identity model. When `X-User-Role` is `HealthClerk`, `SchoolNurse`, `DistrictHealthOfficer`, or `RegistryCoordinator`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution — for example, as `verified_by_user_id` on an `ImmunizationRecord` when a `SchoolNurse` verifies a dose, as `submitted_by_user_id` on an `ExemptionRequest` at submission, and as `reviewed_by_user_id` when a `DistrictHealthOfficer` takes a request under review — but it never compares `X-User-ID` to any entity's `id`. The one place identity comparison matters is segregation of duties on exemption adjudication, described in §3.4, where the reviewer's `X-User-ID` is compared to the request's recorded `submitted_by_user_id`.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Academic Year

The system does not consult wall-clock time for any business decision. A logical clock governs every timestamp the server writes (`issue_date`, `declared_at`, `resolved_at`, and the like) and every deadline comparison the system performs. At server startup, before any operator action, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `DistrictHealthOfficer` advances the clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and responds with the resulting `current_utc`. All datetime comparisons in this document are evaluated at second precision against this logical clock.

The **academic year** is derived from the logical clock. The academic year runs from August 1 of one calendar year through July 31 of the next; any clock date within that span is labeled with the starting year and the following year joined by a hyphen. For example, any clock reading from 2026-08-01 through 2027-07-31 inclusive belongs to the school year `2026-2027`. Vaccine requirements and compliance snapshots are keyed by this label.

### 2.5. Common Resource Properties

Every primary resource in the system — Student, VaccineRequirement, ImmunizationRecord, ExemptionRequest, ComplianceNotice, OutbreakEvent, ClinicSession, ClinicAppointment, RegistrySyncRun, and ComplianceSnapshot — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource. Cascading recomputation of derived fields (for example, a student's recomputed `deficiency_vaccine_codes` after a dose is verified, or a session's recomputed `booked_count` after an appointment is booked) counts as a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.6. Optimistic Concurrency Control

Two write endpoints in the system are guarded by optimistic concurrency control, and only those two.

Recording a dose against a student requires the request to carry `expected_student_version`, holding the `version` of the Student the client last observed. Dose creation legitimately mutates the student — every creation recomputes the student's derived compliance fields and increments `version` — so if the supplied value does not equal the student's current `version`, the request is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412): the client is writing against a superseded view of the student's record.

Booking an appointment into a clinic session requires the request to carry `expected_clinic_session_version`, holding the `version` of the ClinicSession the client last observed. Every booking, cancellation, completion, or no-show sweep legitimately recomputes `booked_count` and increments the session's `version`, so a mismatch between the supplied value and the session's current `version` is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412): the client is booking against a superseded view of the session's remaining capacity.

No other endpoint accepts a version field; mutations not listed above are processed without an OCC check.

### 2.7. Validation Pipeline and Evaluation Order

When multiple checks could reject the same request, the system evaluates them in a fixed priority order and surfaces the first failure encountered. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; failure yields `ERR_UNAUTHENTICATED`. This applies to all endpoints.
2. **Authorization** — the caller's role is in the endpoint's allowed-roles list; failure yields `ERR_FORBIDDEN`. This applies to all endpoints.
3. **Existence** — path-template identifiers are resolved left to right, and then body foreign-key identifiers (such as `student_id`) are resolved; an unresolvable identifier yields the corresponding not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_SNAPSHOT_NOT_FOUND`.
4. **Optimistic concurrency** — on the two OCC-guarded writes, the supplied expected version must equal the parent's current `version`; failures yield `ERR_STALE_STUDENT_VERSION` or `ERR_STALE_SESSION_VERSION`.
5. **State admissibility** — the target resource's current state must permit the operation: dose entry, exemption submission, and appointment booking require a student whose `status` is not `WITHDRAWN` (`ERR_STUDENT_NOT_ACTIVE`); start-review requires an exemption request in `SUBMITTED`, approve and deny require `UNDER_REVIEW` (`ERR_EXEMPTION_NOT_REVIEWABLE`); resubmit requires `DENIED` (`ERR_EXEMPTION_NOT_RESUBMITTABLE`); opening a session requires `SCHEDULED` (`ERR_SESSION_NOT_OPENABLE`), closing requires `OPEN` (`ERR_SESSION_NOT_CLOSABLE`), cancelling requires `SCHEDULED` or `OPEN` (`ERR_SESSION_NOT_CANCELLABLE`), and booking requires `OPEN` (`ERR_SESSION_NOT_OPEN`); appointment cancel and complete require `BOOKED` (`ERR_APPOINTMENT_NOT_BOOKED`); rescinding a notice requires `ISSUED` (`ERR_NOTICE_NOT_OPEN`); lifting an outbreak requires `ACTIVE` (`ERR_OUTBREAK_ALREADY_LIFTED`); finalizing a snapshot requires `DRAFT` (`ERR_SNAPSHOT_FINALIZED`).
6. **Dose clinical safety** — evaluated only on manual dose entry, in this order: (6a) the administered date must not precede the minimum-age boundary for the applicable requirement, else `ERR_MIN_AGE_VIOLATION`; then (6b) the administered date must respect the minimum interval after the latest prior dose of the same vaccine, else `ERR_MIN_INTERVAL_VIOLATION`.
7. **Temporal placement** — in this order: (7a) session spacing for the school, else `ERR_SESSION_GAP_VIOLATION`; (7b) the appointment must lie within the session window, else `ERR_APPOINTMENT_OUTSIDE_SESSION`; (7c) the appointment must not overlap another booked appointment of the same student, else `ERR_APPOINTMENT_TIME_CONFLICT`.
8. **Uniqueness, segregation, and allowability** — in this order: (8a) no duplicate dose ordinal, else `ERR_DUPLICATE_DOSE`; (8b) segregation of duties on exemption review actions, else `ERR_SEGREGATION_OF_DUTIES`; (8c) no duplicate requirement for the same vaccine and school year, else `ERR_DUPLICATE_REQUIREMENT`; (8d) no duplicate active outbreak for the same school and vaccine, else `ERR_OUTBREAK_ALREADY_ACTIVE`; (8e) a manual initial-noncompliance notice is allowed only against a student already in `NON_COMPLIANT`, else `ERR_NOTICE_NOT_ALLOWED`; (8f) no regeneration once a finalized snapshot exists for the same cell, else `ERR_SNAPSHOT_EXISTS`.
9. **Capacity** — booking requires a free seat in the session, else `ERR_SESSION_FULL`.
10. **Request-body schema** — required fields present, enum members valid, types well-formed; failure yields `ERR_VALIDATION`. Schema validation is deliberately last: a request that fails both a business rule and a schema check surfaces the business-rule error first.

### 2.8. Nested Path Resolution

Endpoints that address a resource nested under another — a student's dose records, a session's appointments — validate path identifiers strictly left to right. The request is rejected with the 404 error corresponding to the first path identifier that does not resolve to an existing resource, before later identifiers or any body content are examined. Only after every path identifier resolves does the system consider body-supplied foreign keys such as `student_id`, and only after all existence checks does it proceed to the state, safety, and business rules of §2.7.

### 2.9. Two Lenses on Compliance

Compliance is always computed in two variants, and the two differ in exactly one respect: whether doses imported from the state registry count.

The **`LOCAL_RECORDS`** variant counts only verified dose records whose `source` is `MANUAL` or `CLINIC`; registry-imported doses are invisible to it. This variant alone drives official student status transitions, the student's `deficiency_vaccine_codes`, sweep decisions, and exclusion decisions.

The **`REGISTRY_RECONCILED`** variant additionally counts verified dose records whose `source` is `REGISTRY_IMPORT`. It feeds the reconciled fields of the per-student compliance view and the `compliant_count` of annual compliance snapshots. A student can therefore be fully satisfied under REGISTRY_RECONCILED while still deficient under LOCAL_RECORDS — the registry knows about doses the district has not yet verified locally — and such a student is never excluded on the strength of that discrepancy, but is reported as compliant in the annual filing.

In both variants, only records in `VERIFIED` status count (records in `PENDING_VERIFICATION` or `VOIDED` never do), and an exemption request counts toward satisfaction only while its status is `APPROVED`; an exemption suspended by an outbreak (`SUSPENDED_OUTBREAK`) does not satisfy the requirement for as long as the suspension lasts.

### 2.10. Numeric Precision and Rounding

Dose counts, appointment counts, and sync-run counters are integers and are compared exactly; a requirement calling for a given `doses_required` is met only when the qualifying count is at least that number. Compliance rates are rounded to exactly 1 decimal place using the round-half-up method, and — as detailed in §3.9 — district-level aggregation rounds each school's rate first and only then computes the enrollment-weighted district figure, rounding the final result half-up to 1 decimal place again. Calendar arithmetic for minimum ages uses whole calendar months; deadline and interval arithmetic uses whole days.

## 3. Business Logic & Workflows

### 3.1. Student Intake and the Provisional Enrollment Window

A `HealthClerk` registers a student by supplying the student's `legal_name`, `date_of_birth` (normalized to midnight UTC), current `grade`, the `school_code` of the enrolling school, and the `enrollment_date`. Grade values are drawn from the fixed set `PK`, `K`, `G1`, `G2`, `G3`, `G4`, `G5`, `G6`, `G7`, `G8`, `G9`, `G10`, `G11`, `G12`. Registration returns the new student resource.

Every student begins life in the `ENROLLED_PROVISIONAL` status: state rules grant families a provisional window of 30 days from enrollment to produce complete records. At creation the system computes the student's `provisional_deadline` as the `enrollment_date` plus 30 days, and immediately runs its first requirement evaluation, populating the student's `deficiency_vaccine_codes` with the vaccine codes of every applicable requirement that is not currently satisfied under LOCAL_RECORDS. At any point, the student's full compliance posture can be read through the computed per-requirement compliance view, which returns the student's `student_status` together with a `requirements` array — one row per applicable requirement showing both evaluation variants and the next-dose due date.

Withdrawal is a terminal act performed by a `HealthClerk`. A student may be withdrawn from `ENROLLED_PROVISIONAL`, `ENROLLED_COMPLIANT`, `NON_COMPLIANT`, or `EXCLUDED`; in every case the student's `status` becomes `WITHDRAWN` and the student's `version` is incremented. Withdrawal also cascades to the clinic calendar: every appointment of that student still in `BOOKED` status transitions to `CANCELLED`, and for each affected session the `booked_count` is recomputed and the session's `version` incremented. Once a student is `WITHDRAWN`, dose entry, exemption submission, and appointment booking against that student are all rejected with `ERR_STUDENT_NOT_ACTIVE`.

### 3.2. Configuring Vaccine Requirements

Before any student can be evaluated, a `DistrictHealthOfficer` configures the immunization schedule for the school year. Each VaccineRequirement names a `vaccine_code` — one of `DTAP`, `IPV`, `MMR`, `HEPB`, `VAR`, `HIB`, `PCV`, `HEPA` — together with the `applies_to_grades` it covers (a list drawn from the student grade enum), the `doses_required` for compliance (at least 1), the `min_interval_days` that must separate consecutive doses (at least 0), the `min_age_months` below which no dose of that vaccine is valid (at least 0), and the `school_year` label in the `YYYY-YYYY` format, such as `2026-2027`. The combination of `vaccine_code` and `school_year` is unique: configuring a second requirement for a pair that already exists is rejected with `ERR_DUPLICATE_REQUIREMENT`.

Which requirements apply to a given student is a function of grade and time. A requirement applies when the student's `grade` is among its `applies_to_grades` and its `school_year` equals the academic-year label of the current logical clock (August through July, per §2.4). Because the applicable set is time-dependent, the same student can face different requirements after the clock crosses an August 1 boundary.

### 3.3. Recording Doses: Entry, Verification, and Correction

A `HealthClerk` records a dose against a student by supplying the `vaccine_code`, the ordinal `dose_number` (starting at 1), the `administered_date`, and — because this write is OCC-guarded — the `expected_student_version` (§2.6). The new ImmunizationRecord is born with `source` set to `MANUAL`, its `status` set to `PENDING_VERIFICATION`, `clinic_appointment_id` null, and `verified_by_user_id` null. A pending record does not count toward compliance in either evaluation variant.

Manual entry is guarded by two clinical safety checks, evaluated in this order. First, the `administered_date` must not fall before the student's `date_of_birth` plus the applicable requirement's `min_age_months` whole calendar months; a dose administered too early is rejected with `ERR_MIN_AGE_VIOLATION` (HTTP 422). Second, the `administered_date` must be at least the requirement's `min_interval_days` days after the most recent `administered_date` among the student's existing non-`VOIDED` records for the same vaccine; a dose that arrives too soon after its predecessor is rejected with `ERR_MIN_INTERVAL_VIOLATION` (HTTP 422). Independently of timing, the dose ordinal must be unique: among records that are not `VOIDED`, no two records for the same student and vaccine may share a `dose_number`, and a colliding entry is rejected with `ERR_DUPLICATE_DOSE`.

Verification belongs to the `SchoolNurse`. Verifying a record in `PENDING_VERIFICATION` moves it to `VERIFIED`, stamps `verified_by_user_id` with the caller's `X-User-ID`, and triggers a full re-evaluation of the student: the LOCAL_RECORDS lens is recomputed, `deficiency_vaccine_codes` is refreshed, the student's `version` is incremented, and the student status transitions prescribed by §3.5 fire — including the cure of outstanding notices when the student reaches full satisfaction.

A `SchoolNurse` may also void a record, supplying a `reason`, from either `PENDING_VERIFICATION` or `VERIFIED`; the record lands in the terminal `VOIDED` status. Voiding a pending record merely recomputes the student's evaluation. Voiding a previously verified record can cost the student their standing: if at least one applicable requirement is no longer satisfied after the void, a student in `ENROLLED_COMPLIANT` falls back to `ENROLLED_PROVISIONAL` when the current logical clock is at or before the student's `provisional_deadline`, and falls to `NON_COMPLIANT` when the clock is strictly past that deadline. In both cases `deficiency_vaccine_codes` is recomputed and the student's `version` incremented.

### 3.4. Exemption Requests and Adjudication

Families claim medical or religious exemptions through school staff. A `SchoolNurse` or `DistrictHealthOfficer` submits an ExemptionRequest against a student, naming the `vaccine_code` the exemption covers, the `exemption_type` — `MEDICAL` or `RELIGIOUS` — and a `document_ref` pointing at supporting documentation uploaded out of band. The request is born in `SUBMITTED` status, and the system captures the caller's `X-User-ID` as `submitted_by_user_id`, anchoring segregation of duties for everything that follows.

Adjudication is reserved for a `DistrictHealthOfficer`, with a hard segregation rule: the reviewing officer must not be the person who submitted the request. Starting review moves a request from `SUBMITTED` to `UNDER_REVIEW` and stamps `reviewed_by_user_id` with the caller's `X-User-ID`; the action is rejected with `ERR_EXEMPTION_NOT_REVIEWABLE` from any other state, and with `ERR_SEGREGATION_OF_DUTIES` when the caller's `X-User-ID` equals the request's `submitted_by_user_id`.

From `UNDER_REVIEW`, the officer either approves or denies. Approval moves the request to `APPROVED` and immediately re-evaluates the student, since an `APPROVED` exemption satisfies its requirement under both lenses; if the approval completes the student's schedule, the student transitions toward `ENROLLED_COMPLIANT` as described in §3.5. Approval is not permitted while an outbreak is active for the same school and vaccine — the combination of the student's `school_code` and the request's `vaccine_code` — and such an attempt is rejected with `ERR_OUTBREAK_ACTIVE`. Denial moves the request to `DENIED` and stores the officer's `denial_reason` from the request payload. Both approval and denial enforce the same segregation-of-duties check as start-review, and both are rejected with `ERR_EXEMPTION_NOT_REVIEWABLE` when attempted from a state other than `UNDER_REVIEW`.

A denied request is not the end of the road. A `SchoolNurse` or `DistrictHealthOfficer` may resubmit a request that is in `DENIED`, supplying a fresh `document_ref`; resubmission from any other state is rejected with `ERR_EXEMPTION_NOT_RESUBMITTABLE`. Resubmission returns the request to `SUBMITTED`, replaces `document_ref` with the new value, clears `reviewed_by_user_id` and `denial_reason` back to null, and — crucially for segregation of duties — re-anchors `submitted_by_user_id` to the resubmitting caller's `X-User-ID`.

### 3.5. Notices, Sweeps, and the Path to Exclusion

The ComplianceNotice is the legal instrument that starts the exclusion clock. A notice carries a `notice_type` — `INITIAL_NONCOMPLIANCE` or `OUTBREAK_EXCLUSION` — a `status` that begins at `ISSUED`, an `issue_date` stamped from the logical clock at issuance, an `exclusion_date`, and a `resolved_at` that stays null until the notice resolves. For an `INITIAL_NONCOMPLIANCE` notice the exclusion date is the issue date plus 14 days — the grace period for the family to cure. For an `OUTBREAK_EXCLUSION` notice the exclusion date equals the issue date: exclusion is immediate, and such notices are created by the system alone during an outbreak cascade, never by hand.

A `DistrictHealthOfficer` may also issue an `INITIAL_NONCOMPLIANCE` notice manually against a student, but only while that student's `status` is `NON_COMPLIANT`; the attempt against a student in any other status — or any attempt to hand-create an `OUTBREAK_EXCLUSION` notice — is rejected with `ERR_NOTICE_NOT_ALLOWED` (HTTP 422). An officer may rescind a notice still in `ISSUED` (for example, a clerical error), supplying a `reason`; the notice moves to `RESCINDED` with `resolved_at` set to the current clock. Rescinding a notice that has already been cured, rescinded, or made effective is rejected with `ERR_NOTICE_NOT_OPEN`.

Most status movement, however, flows through the district's compliance sweep — an ops-run checkpoint a `DistrictHealthOfficer` triggers, which walks four kinds of work and reports back the counts `provisional_expired_count`, `notices_escalated_count`, `students_excluded_count`, `students_marked_compliant_count`, and `appointments_no_show_count`. The four passes:

- Every student still in `ENROLLED_PROVISIONAL` whose `provisional_deadline` is **strictly** in the past — the current clock is later than the deadline; sitting exactly at the deadline leaves the student provisional — and who has at least one applicable requirement unsatisfied under LOCAL_RECORDS, transitions to `NON_COMPLIANT`. The sweep issues that student an `INITIAL_NONCOMPLIANCE` notice in `ISSUED` status with `issue_date` set to the current clock and `exclusion_date` 14 days out, recomputes `deficiency_vaccine_codes`, and increments the student's `version`.
- Every `ISSUED` notice whose `exclusion_date` has been reached or passed — the comparison here is inclusive: sitting exactly at the exclusion date escalates — while the student is still deficient under LOCAL_RECORDS, transitions to `EXCLUSION_EFFECTIVE`, and the student transitions from `NON_COMPLIANT` to `EXCLUDED` with a `version` increment.
- Every appointment still `BOOKED` whose `end_time` is earlier than the current clock transitions to `NO_SHOW`, with the host session's `booked_count` recomputed and its `version` incremented (§3.7).
- Every student in `ENROLLED_PROVISIONAL` whose evaluation shows zero deficiencies transitions to `ENROLLED_COMPLIANT`, with `deficiency_vaccine_codes` cleared and `version` incremented.

Cure flows the other way. Whenever a student in `NON_COMPLIANT` reaches full satisfaction under LOCAL_RECORDS — through a dose verification, a completed clinic appointment, or an exemption approval — the student transitions to `ENROLLED_COMPLIANT`, all of that student's notices still in `ISSUED` move to `CURED` with `resolved_at` set to the current clock, `deficiency_vaccine_codes` is cleared, and the student's `version` is incremented. A student in `ENROLLED_PROVISIONAL` who reaches full satisfaction through the same events transitions directly to `ENROLLED_COMPLIANT` with the deficiency list cleared. Even a student in `EXCLUDED` can be readmitted the same way: a dose verification or clinic completion that brings the record to full satisfaction moves the student from `EXCLUDED` back to `ENROLLED_COMPLIANT`, curing every notice in `ISSUED` or `EXCLUSION_EFFECTIVE` with `resolved_at` stamped, clearing the deficiency list, and incrementing `version`.

### 3.6. Outbreak Response

When a vaccine-preventable disease appears in a school, a `DistrictHealthOfficer` declares an OutbreakEvent for the affected `school_code` and `vaccine_code`. The event is born `ACTIVE` with `declared_at` stamped from the logical clock and `lifted_at` null. Only one active outbreak may exist per school-and-vaccine pair; declaring a duplicate while one is still `ACTIVE` is rejected with `ERR_OUTBREAK_ALREADY_ACTIVE`.

Declaration triggers an immediate protective cascade. Every ExemptionRequest in `APPROVED` status whose student's `school_code` and whose `vaccine_code` match the event transitions to `SUSPENDED_OUTBREAK` — a suspended exemption no longer satisfies its requirement under either lens. Each affected student is then re-evaluated, and because the requirement is now unsatisfied, the student transitions to `EXCLUDED` regardless of whether they were previously `ENROLLED_PROVISIONAL`, `ENROLLED_COMPLIANT`, or `NON_COMPLIANT`. For each excluded student the system creates an `OUTBREAK_EXCLUSION` notice already in `EXCLUSION_EFFECTIVE` status, with `issue_date` and `exclusion_date` both set to the current clock, and increments the student's `version`.

Lifting the outbreak — again a `DistrictHealthOfficer` action, permitted only while the event is `ACTIVE` and otherwise rejected with `ERR_OUTBREAK_ALREADY_LIFTED` — moves the event to its terminal `LIFTED` status, stamps `lifted_at`, and runs the cascade in reverse. Every matching exemption in `SUSPENDED_OUTBREAK` returns to `APPROVED`. Each affected student is re-evaluated: a student whose requirements are now all satisfied (typically because the reinstated exemption satisfies the outstanding requirement) transitions from `EXCLUDED` to `ENROLLED_COMPLIANT` with the deficiency list cleared; a student still deficient under LOCAL_RECORDS after reinstatement transitions from `EXCLUDED` to `NON_COMPLIANT` with `deficiency_vaccine_codes` recomputed. In both cases the student's `OUTBREAK_EXCLUSION` notice in `EXCLUSION_EFFECTIVE` moves to `CURED` with `resolved_at` stamped, and the student's `version` is incremented.

### 3.7. Catch-Up Clinics: Sessions and Appointments

To help deficient families catch up, a `SchoolNurse` schedules a ClinicSession for a host `school_code`, giving the `session_date` start, a `duration_minutes` length (greater than 0), and a `capacity` of at least 1. The session occupies the half-open window from its `session_date` up to but not including `session_date` plus `duration_minutes` minutes. Sessions of the same school must be spaced out: no new session may begin less than 7 days from an existing session of that school in `SCHEDULED`, `OPEN`, or `CLOSED` status — a gap of exactly 7 days is allowed, and `CANCELLED` sessions are ignored by this check. A too-close session is rejected with `ERR_SESSION_GAP_VIOLATION`. A session is born `SCHEDULED` with `booked_count` 0; the nurse then opens it (`SCHEDULED` → `OPEN`) to accept bookings, closes it (`OPEN` → `CLOSED`) when done, or cancels it from either `SCHEDULED` or `OPEN`. Cancelling a session cascades: every appointment still `BOOKED` transitions to `CANCELLED` and the session's `booked_count` is recomputed.

A `HealthClerk` books an appointment into an `OPEN` session by naming the `student_id`, the `vaccine_code` to administer, and the half-open interval from `start_time` to `end_time` (end strictly after start), together with the OCC token `expected_clinic_session_version` (§2.6). The appointment is recorded against the session as its `clinic_session_id` and begins in `BOOKED`. Three placement rules guard booking, in the order of §2.7: the interval must lie entirely within the session window, else `ERR_APPOINTMENT_OUTSIDE_SESSION` (HTTP 422); the interval must not overlap any other `BOOKED` appointment of the same student — two appointments that merely touch, one's `end_time` equal to the other's `start_time`, do not conflict — else `ERR_APPOINTMENT_TIME_CONFLICT`; and the session must still have a free seat. Capacity is judged on `booked_count` against `capacity`: a session whose `booked_count` already equals its `capacity` rejects the booking with `ERR_SESSION_FULL`, while one short of capacity accepts it.

The `booked_count` on a session is always the live count of its appointments in `BOOKED` status — completed, cancelled, and no-show appointments do not count. It is recomputed after every appointment mutation affecting the session: booking increments it by 1, while cancellation, completion, and the no-show sweep each decrement it by 1, and every such recompute increments the session's `version`.

A booked appointment meets one of three ends. The clerk may cancel it, freeing the seat (`BOOKED` → `CANCELLED`). The sweep may find it stale and mark it `NO_SHOW`. Or a `SchoolNurse` marks it completed, which is the productive path: completion creates an ImmunizationRecord for the appointment's student and vaccine with `source` set to `CLINIC`, `status` born `VERIFIED`, `clinic_appointment_id` pointing back at the appointment, `administered_date` taken from the appointment's `start_time`, and `dose_number` assigned as one more than the highest `dose_number` among the student's existing non-`VOIDED` records for that vaccine — 1 if none exist. Completion then re-evaluates the student exactly as a verification does, including the notice-cure cascade of §3.5. Cancel or complete attempted on an appointment no longer in `BOOKED` is rejected with `ERR_APPOINTMENT_NOT_BOOKED`. The dose record a completion produced remains traceable: the records linked to an appointment can be listed (zero or one entries), and a student's appointments can be listed across sessions.

### 3.8. State Registry Reconciliation

The state maintains its own immunization registry, and the district reconciles against it. For testing and simulation, a `RegistryCoordinator` can plant a dose in the external registry — supplying `student_id`, `vaccine_code`, `dose_number`, and `administered_date` — receiving back a `seed_id`; these seeded doses are what a later sync run inspects.

Reconciliation itself is a synchronous act: the `RegistryCoordinator` starts a RegistrySyncRun for a `school_code`, and the run executes inside the request, beginning in `RUNNING` and returning already `COMPLETED`. The run examines every seeded registry dose belonging to students of that school and tallies four counters. `registry_doses_seen` counts the seeded doses inspected. `imported_count` counts seeded doses with no local record for the same student, vaccine, and dose number: each is imported as an ImmunizationRecord with `source` set to `REGISTRY_IMPORT` and `status` born `VERIFIED`. `matched_count` counts seeded doses that agree with an existing non-`VOIDED` local record on student, vaccine, dose number, and `administered_date`. `discrepancy_count` counts seeded doses that match a non-`VOIDED` local record on student, vaccine, and dose number but disagree on `administered_date`.

Imported doses change what the district can see but not what the district enforces. Because LOCAL_RECORDS counts only `MANUAL` and `CLINIC` sources, a registry import never moves a student's official status by itself; it is the REGISTRY_RECONCILED lens — the per-student compliance view's reconciled fields and the annual snapshot's `compliant_count` — that absorbs imported doses. Each affected student's evaluation is nonetheless recomputed after the run.

### 3.9. Annual Compliance Reporting

Once a year the district files compliance rates, cell by cell, with the state. A `RegistryCoordinator` generates a ComplianceSnapshot for a `school_year`, `school_code`, `grade`, `census_date`, and `rate_variant`. Membership in the cell is decided by the variant: under `CENSUS_DATE` — the official report — the denominator counts students of that school and grade whose `enrollment_date` is on or before the `census_date` and whose status is not `WITHDRAWN`; under `EVER_ENROLLED` — the auxiliary accountability view — withdrawn students remain in the denominator, so identical data yields an equal or lower rate.

Three counts and a rate are computed at generation time. `enrolled_count` is the size of the membership set. `compliant_count` counts members whose REGISTRY_RECONCILED evaluation is fully satisfied at that moment — this is where registry reconciliation pays off (§3.8). `exempt_count` counts members holding at least one ExemptionRequest in `APPROVED` status. `compliance_rate` is one hundred times `compliant_count` divided by `enrolled_count`, rounded half-up to 1 decimal place; when `enrolled_count` is zero the rate is null rather than zero.

A snapshot is born `DRAFT`. Regenerating the same cell — the same `school_year`, `school_code`, `grade`, and `rate_variant` — supersedes an existing draft, but once a `DistrictHealthOfficer` finalizes the snapshot (`DRAFT` → `FINALIZED`) its numbers are locked: further mutation of the snapshot is rejected with `ERR_SNAPSHOT_FINALIZED`, and regeneration of that cell is rejected with `ERR_SNAPSHOT_EXISTS`.

Above the per-cell snapshots sits the district rollup. A `DistrictHealthOfficer` requests the district-wide rate for a `school_year` and `grade`; the rollup is computed live, using the current logical clock as the census date and CENSUS_DATE membership, over every school that has at least one member. The rounding order is pinned and non-negotiable: first, each school's rate is computed and rounded half-up to 1 decimal place on its own; second, the district rate is the enrollment-weighted average of those already-rounded school rates — the sum over schools of each rounded rate multiplied by that school's enrolled count, divided by the sum of enrolled counts — itself rounded half-up to 1 decimal place. Aggregating the raw counts first and rounding once is explicitly not the rule; the per-school rounded rate is the weighted term. The response carries the `district_rate`, the `schools_included` count, and the `enrolled_total`; when no school has any members, `district_rate` is null.

## 4. Endpoint Definitions

Operations that create a new resource — registering a student, configuring a requirement, recording a dose, submitting an exemption request, issuing a notice, declaring an outbreak, scheduling a session, booking an appointment, running a registry sync, generating a snapshot, seeding a registry dose — return `201 Created`. Operations that act on an existing resource without creating a new one — withdrawals, verifications, voids, reviews, approvals, denials, resubmissions, rescinds, lifts, opens, closes, cancels, completions, finalizations, rollups, sweeps, and the clock advance — return `200 OK`. All endpoints are mounted under `/api` except the two test-driving endpoints, which are mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/students` | Register a student (born `ENROLLED_PROVISIONAL`) | HealthClerk |
| GET | `/api/students` | List students with optional filters and pagination | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| GET | `/api/students/{id}` | Fetch one student including computed fields | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/students/{id}/withdraw` | Withdraw a student (terminal); cancels booked appointments | HealthClerk |
| GET | `/api/students/{id}/compliance` | Per-requirement compliance view with both evaluation variants and next-dose due dates | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/vaccine-requirements` | Configure a grade-scoped vaccine requirement for a school year | DistrictHealthOfficer |
| GET | `/api/vaccine-requirements` | List vaccine requirements with optional filters | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/students/{id}/immunization-records` | Record a dose (`MANUAL`, `PENDING_VERIFICATION`); OCC-guarded on the student | HealthClerk |
| GET | `/api/students/{id}/immunization-records` | List a student's dose records | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/immunization-records/{id}/verify` | Verify a pending dose record; re-evaluates the student | SchoolNurse |
| POST | `/api/immunization-records/{id}/void` | Void a dose record; re-evaluates the student | SchoolNurse |
| POST | `/api/students/{id}/exemption-requests` | Submit a medical/religious exemption request | SchoolNurse, DistrictHealthOfficer |
| GET | `/api/students/{id}/exemption-requests` | List a student's exemption requests | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/exemption-requests/{id}/start-review` | Move a submitted request under review | DistrictHealthOfficer |
| POST | `/api/exemption-requests/{id}/approve` | Approve a request under review; re-evaluates the student | DistrictHealthOfficer |
| POST | `/api/exemption-requests/{id}/deny` | Deny a request under review with a reason | DistrictHealthOfficer |
| POST | `/api/exemption-requests/{id}/resubmit` | Resubmit a denied request with new documentation | SchoolNurse, DistrictHealthOfficer |
| POST | `/api/students/{id}/compliance-notices` | Manually issue an `INITIAL_NONCOMPLIANCE` notice | DistrictHealthOfficer |
| GET | `/api/students/{id}/compliance-notices` | List a student's compliance notices | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/compliance-notices/{id}/rescind` | Rescind an issued notice | DistrictHealthOfficer |
| POST | `/api/outbreak-events` | Declare an outbreak; suspends matching exemptions and excludes affected students | DistrictHealthOfficer |
| POST | `/api/outbreak-events/{id}/lift` | Lift an active outbreak; reinstates exemptions and re-evaluates students | DistrictHealthOfficer |
| POST | `/api/clinic-sessions` | Schedule a catch-up clinic session | SchoolNurse |
| GET | `/api/clinic-sessions/{id}` | Fetch one clinic session including `booked_count` and `version` | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/clinic-sessions/{id}/open` | Open a scheduled session for booking | SchoolNurse |
| POST | `/api/clinic-sessions/{id}/close` | Close an open session | SchoolNurse |
| POST | `/api/clinic-sessions/{id}/cancel` | Cancel a scheduled or open session; cancels booked appointments | SchoolNurse |
| POST | `/api/clinic-sessions/{id}/appointments` | Book an appointment into an open session; OCC-guarded on the session | HealthClerk |
| GET | `/api/clinic-sessions/{id}/appointments` | List a session's appointments | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| GET | `/api/clinic-appointments/{id}` | Fetch one appointment | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| GET | `/api/students/{id}/clinic-appointments` | List a student's appointments across sessions | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/clinic-appointments/{id}/cancel` | Cancel a booked appointment; frees the seat | HealthClerk |
| POST | `/api/clinic-appointments/{id}/complete` | Complete a booked appointment; creates a verified clinic-source dose record | SchoolNurse |
| GET | `/api/clinic-appointments/{id}/immunization-records` | List dose records produced by this appointment | HealthClerk, SchoolNurse, DistrictHealthOfficer, RegistryCoordinator |
| POST | `/api/registry-sync-runs` | Reconcile the school's students against seeded state-registry doses (synchronous) | RegistryCoordinator |
| POST | `/api/compliance-snapshots/generate` | Generate a draft compliance snapshot for a cell | RegistryCoordinator |
| POST | `/api/compliance-snapshots/{id}/finalize` | Finalize a draft snapshot, locking its numbers | DistrictHealthOfficer |
| POST | `/api/compliance-snapshots/district-rollup` | Compute the district-wide rate for a school year and grade | DistrictHealthOfficer |
| POST | `/api/ops/compliance-sweep` | Run the compliance sweep checkpoint | DistrictHealthOfficer |
| POST | `/_clock/set_current_utc` | Advance the logical clock | DistrictHealthOfficer |
| POST | `/_registry/seed-doses` | Plant a dose in the external state registry | RegistryCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_RECORD_NOT_FOUND` | 404 |
| `ERR_EXEMPTION_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_OUTBREAK_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_STALE_STUDENT_VERSION` | 412 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STUDENT_NOT_ACTIVE` | 409 |
| `ERR_EXEMPTION_NOT_REVIEWABLE` | 409 |
| `ERR_EXEMPTION_NOT_RESUBMITTABLE` | 409 |
| `ERR_SESSION_NOT_OPENABLE` | 409 |
| `ERR_SESSION_NOT_CLOSABLE` | 409 |
| `ERR_SESSION_NOT_CANCELLABLE` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 |
| `ERR_NOTICE_NOT_OPEN` | 409 |
| `ERR_OUTBREAK_ALREADY_LIFTED` | 409 |
| `ERR_SNAPSHOT_FINALIZED` | 409 |
| `ERR_MIN_AGE_VIOLATION` | 422 |
| `ERR_MIN_INTERVAL_VIOLATION` | 422 |
| `ERR_SESSION_GAP_VIOLATION` | 409 |
| `ERR_APPOINTMENT_OUTSIDE_SESSION` | 422 |
| `ERR_APPOINTMENT_TIME_CONFLICT` | 409 |
| `ERR_DUPLICATE_DOSE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_OUTBREAK_ACTIVE` | 409 |
| `ERR_DUPLICATE_REQUIREMENT` | 409 |
| `ERR_OUTBREAK_ALREADY_ACTIVE` | 409 |
| `ERR_NOTICE_NOT_ALLOWED` | 422 |
| `ERR_SNAPSHOT_EXISTS` | 409 |
| `ERR_SESSION_FULL` | 409 |
