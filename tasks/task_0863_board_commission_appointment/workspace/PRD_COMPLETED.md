# Board & Commission Appointment Management API — Product Requirements Document

## 1. Introduction

Local and state governments seat hundreds of residents on boards, commissions, and authorities, and every one of those appointments carries a paper trail: who applied, whether they meet residency and eligibility rules, who nominated them, who cast the confirming vote, how long they may serve, whether they filed their financial disclosures, and whether the body met the open-meetings (sunshine) requirements along the way. This API is the system of record for that entire lifecycle. It manages the creation of governing bodies and their seats, the intake and review of citizen applications, the segregation-of-duties workflow that separates nomination from confirmation, the terms that result, and the ongoing compliance obligations — attendance, disclosure filing, and term limits — that determine when a member becomes removal-eligible or a seat rotates.

The system is built for administrative clerks, appointing authorities, confirming bodies, ethics officers, applicants, and the transparency-minded public, each of whom sees a different slice of the same regulated process. Because appointments are legally consequential, the platform treats correctness of state, timing, and authority as first-class concerns: deadlines are evaluated against a controllable logical clock, votes are checked against quorum, nominations are guarded against stale reads of a contested seat, and a single removal can cascade through a member's term, their seat's occupancy, and a freshly opened vacancy. This document specifies the complete contract an implementer must satisfy.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request (with the two exceptions noted below) must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes six roles, spelled exactly: `BoardClerk`, `AppointingAuthority`, `ConfirmingMember`, `EthicsOfficer`, `Applicant`, and `PublicAuditor`.

- A `BoardClerk` is the administrative operator: they create boards, seats, and vacancies, drive application review, expire terms, schedule meetings and post notices, record attendance, and produce reports. The clerk also drives the server's logical clock.
- An `AppointingAuthority` nominates candidates, initiates and executes removals, and requests reappointments.
- A `ConfirmingMember` records confirming or rejecting votes on nominations and decides reappointment requests.
- An `EthicsOfficer` independently reviews financial-disclosure and ethics filings and may initiate removals on ethics grounds.
- An `Applicant` is a member of the public who registers, applies to vacancies, resubmits returned applications, and — once seated — files their own disclosures.
- A `PublicAuditor` is a read-only oversight role for transparency listings, rosters, and compliance reports.

Two identity conventions apply. For `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an applicant compare the resource's applicant foreign key to `X-User-ID`. For the other five roles — `BoardClerk`, `AppointingAuthority`, `ConfirmingMember`, `EthicsOfficer`, and `PublicAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `nominated_by_user_id` or `confirmed_by_user_id` on an `Appointment`, or `initiated_by_user_id` on a `RemovalAction`, where a transition writes it) but does not compare it to any entity's `id`.

Two endpoints are exempt from the authentication check: applicant self-registration (creating an `Applicant`) accepts requests with no user context, and the logical-clock setter is a test-driving capability that is exempt from both the authentication and the role-authorization checks — it accepts any request regardless of the `X-User-ID`/`X-User-Role` headers (the `BoardClerk` role shown for it in the endpoint table below is nominal and is not enforced), and it never returns `ERR_UNAUTHENTICATED` or `ERR_UNAUTHORIZED`. All other endpoints require valid headers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0. A `limit` or `offset` that cannot be parsed as an integer falls back to its default (10 and 0 respectively).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the number of matching records before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. The Logical Clock and Common Resource Properties

All deadline, window, spacing, expiry, and disclosure-due evaluations are made against a server logical clock, never against wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-set call it stays at that default rather than drifting to real time. A `BoardClerk` may advance the clock by supplying a `to_iso8601` instant; this becomes the "current" time for every subsequent rule evaluation.

Most resources — `Board`, `Seat`, `Vacancy`, `Applicant`, `Application`, `Appointment`, `Term`, `Meeting`, `DisclosureFiling`, `RemovalAction`, and `ReappointmentRequest` — carry a common set of system-managed fields:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version`: an integer that begins at 1 and increments on every mutation; it supports optimistic concurrency control (§2.5).

The `AttendanceRecord` resource is the single exception: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because an attendance record is immutable once written.

Whenever a resource's state or a derived field changes, its `updated_at` is refreshed and its `version` is incremented. This applies equally to cascade-driven mutations — for example, when confirming an appointment flips a seat's `occupancy_status`, the affected seat's `updated_at` and `version` both advance.

### 2.5. Optimistic Concurrency on Seat Nominations

Only one live `NOMINATED` appointment may exist for a seat at a time; a fresh nomination legitimately supersedes the prior one (§3.3). Because two appointing authorities may both be looking at the same vacant seat, nomination is guarded by optimistic concurrency on the `Seat`. A nomination request must carry `expected_seat_version` equal to the target seat's current `version`. Each accepted nomination increments the seat's `version` by 1. If another writer has already nominated against that seat since the client last read it — advancing the seat's `version` — then the client's `expected_seat_version` is stale, and the nomination is rejected with `ERR_STALE_SEAT_VERSION` (HTTP 412). This prevents an authority from overwriting a nomination it never observed. Nomination is the only endpoint that takes a seat version field; no other endpoint accepts or checks one.

### 2.6. Cascading State Propagation and Occupancy Reconciliation

A seat's `occupancy_status` is a derived reflection of the terms attached to it: `VACANT` when no live term occupies it, `FILLED` when an `ACTIVE` term occupies it, and `HOLDOVER` when a `HOLDOVER` term occupies it. Operations that create or end terms must keep this derivation consistent, and several operations cascade across two or three resources in a single call.

Confirming an appointment creates an `ACTIVE` term, sets that seat to `FILLED`, mints two disclosure obligations, and closes the linked open vacancy. Executing a removal runs a three-step cascade: the member's term becomes `VACATED`, the seat it occupied returns to `VACANT`, and a new `Vacancy` is opened against that seat with reason `REMOVAL`; the term's still-open disclosure filings are closed at the same time. Expiring a term either extends its window into holdover (setting the seat to `HOLDOVER`) or ends it cleanly, and may return the seat to `VACANT`. Every entity touched in a cascade has its `updated_at` and `version` advanced independently. These cascades are described in full in the relevant §3 workflows.

### 2.7. Path Resolution and Validation Ordering

For any request, checks are applied in a fixed priority order, and the first failure determines the response. The global order is: authentication of the headers first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then field-level input validation (`ERR_INVALID_REQUEST` — required fields present, enum values in range, and numeric constraints such as vote counts being non-negative and `seat_number` being at least 1), then existence of every referenced resource (`ERR_NOT_FOUND`), and only then the business rules specific to the endpoint.

Existence is resolved left to right: every identifier in the URL path is validated before any foreign key in the request body, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND`. Business rules that follow existence run in their own documented order per endpoint; where multiple business rules apply to one endpoint, the specific ordering is stated alongside that endpoint's workflow in §3.

### 2.8. Precision, Rounding, and the Dual Attendance Rate

All rate calculations round half up. Attendance rates are expressed as a percentage to one decimal place. Cumulative years of service are rounded to two decimal places, half up. Vote counts are integers, and term windows are whole-day ISO 8601 instants that preserve the time-of-day of the term's start.

Attendance is computed two ways from the same underlying records, and the difference is deliberate. Each term accumulates `present_count`, `absent_count`, and `excused_count` from its attendance records. The **provisional** rate — surfaced live whenever a term is read and on the live roster — divides present appearances by the sum of present and absent appearances only, excluding excused absences from the denominator, so it reads higher; when that denominator is zero the provisional rate is `0.0`. The **final** rate — used for the compliance report, for attendance-based removal eligibility, and persisted when a term expires or completes — divides present appearances by the sum of present, absent, and excused appearances, counting excused absences against the member, so it reads lower; when that denominator is zero the final rate is `null`. Both are the count of present appearances divided by the applicable denominator, multiplied by 100 and rounded half up to one decimal place. The provisional value is exposed as `provisional_attendance_rate` and the final value as `final_attendance_rate`.

## 3. Business Logic & Workflows

### 3.1. Establishing Boards, Seats, and Vacancies

A `BoardClerk` stands up a governing body by creating a `Board` with a `name`, a `jurisdiction`, and a `board_type` that is one of `BOARD`, `COMMISSION`, or `AUTHORITY`. The board also fixes its governance parameters: `authorized_seat_count` (at least 1), `quorum_count` (the minimum YES votes needed to confirm, at least 1), `term_length_months` (a whole number of months, at least 1), `max_consecutive_terms` (at least 1), `max_cumulative_years` (greater than 0), `attendance_threshold_pct` (greater than 0 and at most 100), and `sunshine_notice_days` (zero or more days of advance notice). Two fields are optional at creation: `max_holdover_days`, the maximum number of days a member may hold over past a scheduled term end awaiting a successor, defaults to 90; and `is_sunshine_subject`, whether the board is subject to open-meetings law, defaults to true. A board's `status` is system-managed and is always `ACTIVE`.

Seats belong to boards. Creating a `Seat` requires the owning `board_id`, a `seat_number` (at least 1), a `seat_category` of `AT_LARGE`, `DISTRICT`, or `EX_OFFICIO`, and a `residency_requirement` of `IN_JURISDICTION`, `DISTRICT_SPECIFIC`, or `NONE`. When and only when the residency requirement is `DISTRICT_SPECIFIC`, the `required_district` field must be supplied as a non-null value; a district-specific seat created without it is rejected with `ERR_DISTRICT_REQUIRED`. A seat's `occupancy_status` starts at `VACANT`. Two seat rules run in order after the seat's inputs and board existence are validated: the district-required check first, then the capacity check. Creating a seat may not push the board's total seat count above its `authorized_seat_count`; a seat that would exceed the authorization is rejected with `ERR_SEAT_LIMIT_REACHED`. A seat read exposes the seat's `version`, which nominators need for concurrency control.

A vacancy makes a seat open for applications. A `BoardClerk` opens a `Vacancy` against a seat by supplying the `seat_id`, a `reason` of `NEW_SEAT`, `RESIGNATION`, `TERM_EXPIRY`, or `REMOVAL`, and an `application_deadline` instant. The seat need only exist — its current `occupancy_status` is not checked, so a vacancy may be opened against a seat in any occupancy state. A new vacancy's `status` defaults to `OPEN`. A clerk may close an open vacancy without filling it, moving its `status` from `OPEN` to `CLOSED`. When an appointment is later confirmed for the seat, an `OPEN` vacancy on that seat is instead moved to `FILLED` automatically.

### 3.2. Applicant Intake and the Eligibility Review Loop

Anyone may register as an `Applicant` without authentication, supplying `full_name`, `email`, `residence_district`, the boolean `resides_in_jurisdiction`, the boolean `is_registered_voter`, and an optional `employer` (used later for conflict screening in disclosures). An applicant's `status` is system-managed and is always `ACTIVE`.

An applicant applies to a vacancy by submitting an `Application` referencing their `applicant_id` and the target `vacancy_id`, together with `residency_attested` (a sworn attestation that they meet the seat's residency rule) and an optional `statement` of interest. On submission, after both foreign keys are confirmed to exist, the target vacancy must be `OPEN`; a submission against a vacancy in any other status is rejected with `ERR_INVALID_STATE`. Then two business checks run in order: the residency check first, then the application-window check. Residency is satisfied when the applicant's attestation is true and their residence matches the seat's rule — for `IN_JURISDICTION`, `resides_in_jurisdiction` must be true; for `DISTRICT_SPECIFIC`, the applicant's `residence_district` must equal the seat's `required_district`; for `NONE`, the residence is always acceptable. A submission that fails residency, or whose `residency_attested` is false, is rejected with `ERR_RESIDENCY_REQUIREMENT_NOT_MET`. The application window is honored only when the current clock is at or before the vacancy's `application_deadline` (the deadline instant itself is still open); a submission after the deadline is rejected with `ERR_APPLICATION_WINDOW_CLOSED`. A new application starts in `SUBMITTED` with `return_count` at 0.

Review is a cycle driven mostly by the clerk. A `BoardClerk` starts review, moving a `SUBMITTED` application to `UNDER_REVIEW`. From `UNDER_REVIEW`, the clerk may return the application for more information — optionally attaching `notes` — which moves it to `RETURNED_FOR_INFO` and increments `return_count` by 1. The owning applicant then resubmits, optionally revising their `statement`, which moves the application from `RETURNED_FOR_INFO` back to `UNDER_REVIEW`; because this closes the revision loop, the applicant may only resubmit their own application, and an applicant acting on an application they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. The application may bounce between `UNDER_REVIEW` and `RETURNED_FOR_INFO` any number of times. Finally, the clerk decides eligibility on an `UNDER_REVIEW` application by supplying the boolean `eligible`: a true decision requires the applicant to satisfy the seat residency requirement — the same attestation-plus-residence test applied at submission, re-evaluated live and rejected with `ERR_RESIDENCY_REQUIREMENT_NOT_MET` when it fails — and moves the application to the terminal `ELIGIBLE`, while a false decision moves it to the terminal `INELIGIBLE`. Each transition requires the application to be in the state the transition starts from; otherwise the request is rejected with `ERR_INVALID_STATE`.

### 3.3. Nomination, Confirmation, and the Appointment Fork

An `AppointingAuthority` nominates by creating an `Appointment` from an `ELIGIBLE` application. The nomination payload supplies the `application_id`, the target `seat_id`, the proposed `term_start_date`, and the `expected_seat_version` for the concurrency guard (§2.5). The system copies the nominated application's applicant into `applicant_id`, records the acting authority's `X-User-ID` in `nominated_by_user_id`, and computes two values: `term_end_date`, obtained by adding the board's `term_length_months` whole calendar months to `term_start_date` (the day-of-month is preserved and clamped to the last valid day of the target month when necessary, with the start's time-of-day carried through); and `term_sequence_number`, set to one more than the count of the applicant's prior consecutive terms on this board. A nomination may only be created from an `ELIGIBLE` application — nominating a non-eligible application is rejected with `ERR_INVALID_STATE`. Creating a new nomination for a seat that already has a live `NOMINATED` appointment supersedes the earlier one, setting that prior appointment's status from `NOMINATED` to `SUPERSEDED`; each accepted nomination advances the seat's `version` by 1. A new appointment starts in `NOMINATED` with `yes_votes`, `no_votes`, and `confirmed_by_user_id` unset.

A `ConfirmingMember` resolves a `NOMINATED` appointment along one of two explicit branches, and the branches carry deliberately different consequences.

**Confirming** (`NOMINATED → CONFIRMED`) records the vote and seats the member. The confirming member supplies `yes_votes` and `no_votes`. Several checks apply, evaluated in order after the appointment is confirmed to be in `NOMINATED` state: segregation of duties first — the confirming member's `X-User-ID` must differ from the appointment's `nominated_by_user_id`, and a self-confirmation is rejected with `ERR_SEGREGATION_OF_DUTIES`; then the seat must currently be `VACANT`, and a seat in any other occupancy state is rejected with `ERR_INVALID_STATE`; then quorum — the confirmation succeeds only when `yes_votes` is at least the board's `quorum_count` and `yes_votes` is strictly greater than `no_votes` (the quorum boundary is inclusive: exactly meeting quorum passes), and a vote that fails either condition is rejected with `ERR_QUORUM_NOT_MET`; and finally term overlap — the proposed term window must not overlap any `ACTIVE` or `HOLDOVER` term on the seat. Term windows are treated as half-open intervals `[term_start_date, term_end_date)`, so a new term starting exactly when an existing term ends is adjacent, not overlapping, and is allowed; a genuine overlap is rejected with `ERR_TERM_OVERLAP`. On success, the system records `yes_votes`, `no_votes`, and the confirming member's `X-User-ID` in `confirmed_by_user_id`; creates a new `Term` in `ACTIVE` status for the seat and applicant with its `term_sequence_number` and computed `term_end_date`; sets the seat's `occupancy_status` to `FILLED`; mints two `DisclosureFiling` rows (one `FINANCIAL_DISCLOSURE` and one `ETHICS_PLEDGE`) in `PENDING` with a computed `due_date`; and, if a vacancy for the seat is `OPEN`, moves that vacancy to `FILLED`.

**Rejecting** (`NOMINATED → REJECTED`) is the sibling branch. The confirming member may supply an optional `reason`. Segregation of duties applies here too: the rejecting member's `X-User-ID` must differ from `nominated_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A rejection records the rejecting voter in `confirmed_by_user_id` along with the reason, but creates no term; the seat's `occupancy_status` is left unchanged and any open vacancy stays `OPEN`. Both branches require the appointment to be `NOMINATED`; acting on an appointment in any other state is rejected with `ERR_INVALID_STATE`. The third terminal state, `SUPERSEDED`, is reached only by the automatic supersede described above, never by a direct vote.

### 3.4. Term Lifecycle, Expiry, and Holdover

A `Term` records who serves which seat on which board, carrying the originating `appointment_id`, the `seat_id`, the `applicant_id`, the `board_id`, the actual `term_start_date` copied from the appointment, the scheduled `term_end_date`, the `term_sequence_number`, and the `is_holdover` flag (false until the term passes its scheduled end without a seated successor). A term begins `ACTIVE` and can reach `HOLDOVER`, `EXPIRED`, `VACATED`, or `COMPLETED`.

A `BoardClerk` expires a term whose scheduled end has arrived — the operation requires the current clock to be at or after the term's `term_end_date`, and the term must be `ACTIVE` or `HOLDOVER`; otherwise it is rejected with `ERR_INVALID_STATE`. The resolution examines successors. The scheduled end is the term's existing `term_end_date`. A successor is the earliest `ACTIVE` term on the same seat whose `term_start_date` is at or after the scheduled end (earliest by `term_start_date` ascending, breaking ties by `created_at` ascending), if any exists. If a successor exists and its `term_start_date` is at or before the current clock — meaning the successor is already seated — the term ends cleanly: its `term_end_date` stays at the scheduled end, it moves to `EXPIRED`, and its `final_attendance_rate` is computed and persisted. Otherwise the term holds over: a holdover ceiling is computed as the scheduled end plus the board's `max_holdover_days` days, the resolved end is the smaller of the successor's `term_start_date` (when a successor exists, otherwise the holdover ceiling) and the holdover ceiling, and the resolved end is never allowed to fall before the scheduled end. In the holdover case the term's `term_end_date` is set to that resolved end, `is_holdover` is set to true, the term moves to `HOLDOVER`, and the seat's `occupancy_status` becomes `HOLDOVER`.

A `HOLDOVER` term is itself expired once the clock reaches its holdover-extended `term_end_date`: it moves to `EXPIRED`, its `final_attendance_rate` is computed and persisted, and if the seat is still `HOLDOVER` with no `ACTIVE` successor, the seat returns to `VACANT`. A term also leaves the active roster through removal (moving to `VACATED`, §3.7) or through reappointment of a holdover incumbent (moving to `COMPLETED`, §3.8). Reading a term computes its `provisional_attendance_rate` live; the `present_count`, `absent_count`, and `excused_count` used by both rates come straight from the term's attendance records.

### 3.5. Meetings, Public Notice, and Attendance

A `BoardClerk` schedules a `Meeting` for a board by supplying the `board_id` and a `scheduled_date`. To honor open-meetings spacing, a new meeting must be at least 24 hours from every other meeting of the same board; the buffer is closed around the scheduled instant, so a new meeting is rejected with `ERR_MEETING_TOO_CLOSE` whenever the absolute gap between its `scheduled_date` and any existing board meeting's `scheduled_date` is less than 24 hours. A new meeting starts in `SCHEDULED`.

Posting the public notice moves the meeting from `SCHEDULED` to `NOTICED`, stamping `notice_posted_at` with the current clock and computing `notice_compliant`. The notice is compliant when it is posted early enough: taking the required-by instant as the meeting's `scheduled_date` minus the board's `sunshine_notice_days` days, the notice is compliant exactly when `notice_posted_at` is at or before that required-by instant, and the boundary is inclusive so a notice posted exactly the required number of days ahead is compliant. Holding the meeting moves it from `NOTICED` to `HELD`, but only once the clock has reached the `scheduled_date`; an attempt to hold a meeting before its scheduled instant is rejected with `ERR_MEETING_NOT_YET_DUE`, and an attempt to hold a meeting that is not `NOTICED` is rejected with `ERR_INVALID_STATE`.

Attendance is recorded by a `BoardClerk` against a held meeting. An `AttendanceRecord` supplies the `term_id`, the `meeting_id`, and a `presence` of `PRESENT`, `ABSENT`, or `EXCUSED`. Recording is allowed only when the meeting is `HELD`, the term is `ACTIVE` or `HOLDOVER`, and the meeting's board matches the term's board; any of these failing is rejected with `ERR_MEETING_NOT_HELD`. Each new record refreshes the owning term's `present_count`, `absent_count`, and `excused_count` so the two attendance rates stay current.

### 3.6. Financial Disclosure and Ethics Filings

When a term is created, the system mints two `DisclosureFiling` obligations for it — one of `filing_type` `FINANCIAL_DISCLOSURE` and one `ETHICS_PLEDGE` — each attached to the term via `term_id` and to the board via `board_id`, each starting in `PENDING`. A filing's `due_date` is computed as the term's `term_start_date` plus 30 days. Its `filed_at` and `content` are unset until filed.

The seated member files a disclosure by supplying its `content`, moving the filing from `PENDING` to `FILED` and stamping `filed_at` with the current clock. Because a member may only file their own obligations, the acting applicant's `X-User-ID` must equal the term's `applicant_id`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. An `EthicsOfficer` then reviews a `FILED` disclosure by supplying the boolean `accept`: accepting moves it to the terminal `ACCEPTED`, while declining moves it to `DEFICIENT`. A `DEFICIENT` filing can be cured — the member re-files it, again supplying `content` and re-stamping `filed_at`, which returns it to `FILED` for another review; the review may accept a filing that is `FILED` or was previously `DEFICIENT`. This cure loop between `FILED` and `DEFICIENT` may repeat. Filings that are still open when their term is vacated by removal — those in `PENDING` or `DEFICIENT` — are closed automatically to `CLOSED`; filings already `FILED` or `ACCEPTED` are left untouched. Any filing action attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.7. Removal and the Vacate Cascade

Either an `EthicsOfficer` or an `AppointingAuthority` initiates removal of a seated term by creating a `RemovalAction` referencing the `term_id`, a `reason` of `RESIGNATION`, `TERM_LIMIT`, `ATTENDANCE`, `ETHICS_VIOLATION`, or `FOR_CAUSE`, and an `effective_date`. The initiating role's `X-User-ID` is recorded in `initiated_by_user_id`, and the action starts in `INITIATED`. The referenced term must be `ACTIVE` or `HOLDOVER`, checked before the reason-specific gate below; initiating removal against a term in any other state is rejected with `ERR_INVALID_STATE`. One reason carries an extra gate: for an `ATTENDANCE` removal, the term's final-variant attendance rate — computed live over the term's attendance records with the denominator counting present, absent, and excused appearances — must be strictly below the board's `attendance_threshold_pct`. If the term has no attendance records at all, its rate is treated as 100.0 (and therefore not below any threshold). A removal whose live final rate is at or above the threshold is rejected with `ERR_ATTENDANCE_ABOVE_THRESHOLD`.

An `AppointingAuthority` executes an `INITIATED` removal, moving it to `EXECUTED` and running the three-link cascade. Link one: the member's term (which must be `ACTIVE` or `HOLDOVER`) moves to `VACATED`. Link two: the seat that term occupied returns to `VACANT`. Link three: a new `Vacancy` is opened against that now-vacant seat with `status` `OPEN`, `reason` `REMOVAL`, and a null `application_deadline`. At the same time, the term's still-open disclosure filings are closed to `CLOSED`. Each resource touched has its `updated_at` and `version` advanced.

### 3.8. Reappointment, Rotation, and Term Limits

When an incumbent's term is winding down, an `AppointingAuthority` may request reappointment by creating a `ReappointmentRequest` naming the expiring or holdover `term_id`, the `seat_id` to be re-filled, the incumbent's `applicant_id`, and a `requested_term_start`. The request starts in `REQUESTED`. A `ConfirmingMember` decides it by supplying the boolean `approve`. Either terminal decision — a successful approval or a denial — snapshots the incumbent's tenure at decision time into `consecutive_terms_at_request` and `cumulative_years_at_request`; an approval that is rejected for failing a precondition writes no snapshot (see below).

Two tenure measures govern the decision, both computed over the incumbent's served terms on the board — the terms whose status is `ACTIVE`, `HOLDOVER`, `EXPIRED`, or `COMPLETED`, excluding `VACATED` and any future terms — ordered by `term_start_date` ascending with `created_at` ascending as the tie-break. The **consecutive-term count** walks those served terms from newest to oldest and counts the length of the unbroken run ending at the newest served term: a term joins the run only when its predecessor's `term_end_date` plus one day is at or after that term's `term_start_date`; a gap larger than one day resets the run so that only the terms after the gap are counted. The **cumulative years** sums, across all served terms regardless of gaps, each term's nominal length — the number of days between the term's `term_start_date` and the date obtained by adding the board's `term_length_months` months to that start (deliberately using the nominal length, never any holdover-extended end, so the measure is holdover-independent) — then divides the total days by 365.0 and rounds to two decimal places, half up; this measure never resets.

Approval requires that the expiring term be `EXPIRED` or `HOLDOVER`, that the consecutive-term count be strictly less than the board's `max_consecutive_terms`, and that the cumulative years be strictly less than the board's `max_cumulative_years`. If either term-limit ceiling would be reached or exceeded, approval is rejected with `ERR_TERM_LIMIT_EXCEEDED`. The proposed new term window is also subject to the same half-open overlap check as a confirmation, rejected with `ERR_TERM_OVERLAP` on a genuine overlap. On approval the request moves to `APPROVED`: the system mints a fresh `CONFIRMED` `Appointment` — with `application_id` and `nominated_by_user_id` both null, `yes_votes` and `no_votes` null, and `confirmed_by_user_id` set to the deciding `ConfirmingMember`'s `X-User-ID` — and a new `ACTIVE` `Term` for the seat (reusing the full confirmation cascade — the seat becomes `FILLED`, two `PENDING` disclosures are minted, and any `OPEN` vacancy on the seat is moved to `FILLED`), records the new appointment's id in `resulting_appointment_id`, and if the expiring term was in `HOLDOVER` completes it by moving it to `COMPLETED`. A denied decision (`approve` false) moves the request to `DENIED`, again snapshotting the two tenure values but minting nothing. An approval that fails a precondition — the expiring term not being `EXPIRED` or `HOLDOVER` (`ERR_INVALID_STATE`), a term-limit ceiling being reached or exceeded (`ERR_TERM_LIMIT_EXCEEDED`), or a genuine overlap (`ERR_TERM_OVERLAP`) — is rejected and leaves the request in `REQUESTED` with nothing written, rather than moving it to `DENIED`.

### 3.9. Roster and Compliance Reporting

Two computed views summarize a board's health, both open to a `BoardClerk` and a `PublicAuditor`. The **roster** returns the board's seats with their current occupant and term, along with `board_id`, an array of `seats`, and four tallies: `filled_seat_count` (seats whose occupancy is `FILLED`), `vacant_seat_count` (seats whose occupancy is `VACANT`), `holdover_count` (seats whose occupancy is `HOLDOVER`), and `active_member_count` (the number of `ACTIVE` terms on the board). Attendance figures shown on the roster use the provisional variant.

The **compliance report** returns `board_id`, the `board_attendance_index`, and three counts: `sunshine_meeting_count`, `sunshine_violation_count`, and `delinquent_disclosure_count`. The `sunshine_meeting_count` is the number of the board's meetings that have posted their public notice (those whose `notice_compliant` has been evaluated), and `sunshine_violation_count` is how many of those had a non-compliant notice. The `delinquent_disclosure_count` is the number of the board's disclosure filings that remain unmet past their due date — those still `PENDING` or `DEFICIENT` whose `due_date` is at or before the current clock. The `board_attendance_index` averages the board's members' attendance with a pinned rounding order: take each member term whose status is `ACTIVE`, `HOLDOVER`, `EXPIRED`, or `COMPLETED`, skip any whose final-variant denominator (present plus absent plus excused) is zero, compute each remaining member's exact unrounded final rate as present divided by that denominator times 100, sum those exact rates, divide by the number of members counted, and round the single result to one decimal place, half up. The per-member rates are never rounded before averaging. When the board has no qualifying member terms, the `board_attendance_index` is `null`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. State-transition and modification operations, list reads, and single-resource reads return `200 OK`. The logical-clock setter returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | BoardClerk |
| POST | `/civic/boards` | Create a board or commission | BoardClerk |
| GET | `/civic/boards` | List boards | BoardClerk, PublicAuditor |
| GET | `/civic/boards/{id}` | Fetch a board | BoardClerk, PublicAuditor |
| GET | `/civic/boards/{id}/roster` | Computed roster of seats and occupancy | BoardClerk, PublicAuditor |
| GET | `/civic/boards/{id}/compliance-report` | Computed attendance, sunshine, and disclosure compliance | BoardClerk, PublicAuditor |
| POST | `/civic/seats` | Create a seat on a board | BoardClerk |
| GET | `/civic/seats` | List seats, optionally by board or occupancy | BoardClerk, PublicAuditor |
| GET | `/civic/seats/{id}` | Fetch a seat (includes version for OCC) | BoardClerk, PublicAuditor, AppointingAuthority |
| POST | `/civic/vacancies` | Open a vacancy against a seat (occupancy not checked) | BoardClerk |
| GET | `/civic/vacancies` | List vacancies, optionally by seat or status | BoardClerk, PublicAuditor, Applicant |
| GET | `/civic/vacancies/{id}` | Fetch a vacancy | BoardClerk, PublicAuditor, Applicant |
| POST | `/civic/vacancies/{id}/close` | Close an OPEN vacancy without filling it | BoardClerk |
| POST | `/civic/applicants` | Self-register an applicant (no auth required) | Applicant, BoardClerk |
| GET | `/civic/applicants/{id}` | Fetch an applicant | Applicant, BoardClerk, PublicAuditor |
| POST | `/civic/applications` | Submit an application to an OPEN vacancy | Applicant |
| GET | `/civic/applications` | List applications by applicant, vacancy, or status | BoardClerk, Applicant |
| GET | `/civic/applications/{id}` | Fetch an application | BoardClerk, Applicant |
| POST | `/civic/applications/{id}/start-review` | Move a SUBMITTED application into review | BoardClerk |
| POST | `/civic/applications/{id}/return-for-info` | Return an UNDER_REVIEW application for more info | BoardClerk |
| POST | `/civic/applications/{id}/resubmit` | Applicant resubmits a RETURNED_FOR_INFO application | Applicant |
| POST | `/civic/applications/{id}/decide-eligibility` | Decide eligibility of an UNDER_REVIEW application | BoardClerk |
| POST | `/civic/appointments` | Nominate an ELIGIBLE application to a seat (OCC-guarded) | AppointingAuthority |
| GET | `/civic/appointments` | List appointments by application, seat, applicant, or status | BoardClerk, AppointingAuthority, ConfirmingMember |
| GET | `/civic/appointments/{id}` | Fetch an appointment | BoardClerk, AppointingAuthority, ConfirmingMember |
| POST | `/civic/appointments/{id}/confirm` | Record the confirming vote and seat the member | ConfirmingMember |
| POST | `/civic/appointments/{id}/reject` | Reject a NOMINATED appointment | ConfirmingMember |
| GET | `/civic/terms` | List terms by seat, applicant, board, appointment, or status | BoardClerk, PublicAuditor |
| GET | `/civic/terms/{id}` | Fetch a term (provisional attendance computed on read) | BoardClerk, PublicAuditor |
| POST | `/civic/terms/{id}/expire` | Expire a term; resolves to EXPIRED or HOLDOVER | BoardClerk |
| POST | `/civic/meetings` | Schedule a meeting (24h spacing enforced) | BoardClerk |
| GET | `/civic/meetings` | List meetings by board or status | BoardClerk, PublicAuditor |
| GET | `/civic/meetings/{id}` | Fetch a meeting | BoardClerk, PublicAuditor |
| POST | `/civic/meetings/{id}/post-notice` | Post the public notice; compute compliance | BoardClerk |
| POST | `/civic/meetings/{id}/hold` | Mark a NOTICED meeting HELD | BoardClerk |
| POST | `/civic/attendance` | Record attendance at a HELD meeting | BoardClerk |
| GET | `/civic/attendance` | List attendance records by term or meeting | BoardClerk, PublicAuditor |
| GET | `/civic/attendance/{id}` | Fetch an attendance record | BoardClerk, PublicAuditor |
| GET | `/civic/disclosures` | List disclosure filings by term, board, or status | BoardClerk, EthicsOfficer, Applicant |
| GET | `/civic/disclosures/{id}` | Fetch a disclosure filing | BoardClerk, EthicsOfficer, Applicant |
| POST | `/civic/disclosures/{id}/file` | File or re-file a disclosure | Applicant |
| POST | `/civic/disclosures/{id}/review` | Accept or mark a FILED disclosure deficient | EthicsOfficer |
| POST | `/civic/removals` | Initiate removal of a seated term | EthicsOfficer, AppointingAuthority |
| GET | `/civic/removals` | List removal actions by term or status | BoardClerk, EthicsOfficer, AppointingAuthority |
| GET | `/civic/removals/{id}` | Fetch a removal action | BoardClerk, EthicsOfficer, AppointingAuthority |
| POST | `/civic/removals/{id}/execute` | Execute a removal; run the vacate cascade | AppointingAuthority |
| POST | `/civic/reappointments` | Request reappointment of an EXPIRED or HOLDOVER incumbent | AppointingAuthority |
| GET | `/civic/reappointments` | List reappointment requests by term, seat, applicant, or status | BoardClerk, AppointingAuthority, ConfirmingMember |
| GET | `/civic/reappointments/{id}` | Fetch a reappointment request | BoardClerk, AppointingAuthority, ConfirmingMember |
| POST | `/civic/reappointments/{id}/decide` | Approve or deny reappointment; enforce term limits | ConfirmingMember |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DISTRICT_REQUIRED` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_STALE_SEAT_VERSION` | 412 |
| `ERR_RESIDENCY_REQUIREMENT_NOT_MET` | 422 |
| `ERR_SEAT_LIMIT_REACHED` | 409 |
| `ERR_APPLICATION_WINDOW_CLOSED` | 422 |
| `ERR_TERM_OVERLAP` | 409 |
| `ERR_MEETING_TOO_CLOSE` | 409 |
| `ERR_MEETING_NOT_YET_DUE` | 409 |
| `ERR_MEETING_NOT_HELD` | 409 |
| `ERR_QUORUM_NOT_MET` | 422 |
| `ERR_TERM_LIMIT_EXCEEDED` | 422 |
| `ERR_ATTENDANCE_ABOVE_THRESHOLD` | 422 |
