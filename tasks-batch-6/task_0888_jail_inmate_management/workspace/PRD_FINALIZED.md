# Jail & Inmate Management API — Product Requirements Document

## 1. Introduction

Correctional facilities juggle a person's entire custody episode through a chain of loosely coupled desks: intake books an arrestee and safeguards their property, a classification desk scores custody risk and finds a compatible bed, schedulers arrange court appearances and family visits, medical and grievance staff triage inmate requests, and supervisors sign off on releases, disciplinary findings, and money movements. Today these functions live in disconnected spreadsheets and paper logs, so a bed can be double-booked, an inmate can be released before their earned date, or commissary money can drift out of balance without anyone noticing until an audit.

This document specifies a single REST API that unifies the whole lifecycle behind one custody record. The system treats a **booking** as the spine of a custody episode: everything — classification, housing, court dates, commissary, visits, medical requests, discipline, and property — hangs off that booking, and the person (**inmate**) may accumulate several bookings over time. Two families of numeric discipline run through the platform: a **ledger** discipline that keeps commissary money conserved across deposits, orders, fulfillments, and refunds; and a **temporal** discipline that projects release dates from good-time credit and gates release on the current date. Because several desks may touch the same booking or account concurrently, the platform layers optimistic concurrency control, cascading side effects, dual-variant calculations, and threshold triggers over the base workflow. The sections below define the global contract first, then scatter the concrete business rules across the workflow narratives that own them.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows: `IntakeOfficer`, `ClassificationOfficer`, `Scheduler`, `HealthGrievanceOfficer`, `Supervisor`, and `Visitor`.

- An `IntakeOfficer` books inmates, logs and returns property, and manages commissary deposits, orders, and fulfillment.
- A `ClassificationOfficer` runs classification assessments and manages housing units, beds, and housing assignments.
- A `Scheduler` schedules and reschedules court events and manages visitor registration and visits.
- A `HealthGrievanceOfficer` handles the full lifecycle of medical and grievance requests.
- A `Supervisor` releases inmates, upholds disciplinary infractions, refunds commissary orders, and sets the logical clock; a `Supervisor` may also perform any read.
- A `Visitor` is an approved external visitor who may request, read, and cancel only their own visits.

Any of the five staff roles may report a disciplinary infraction. Reads are broadly available to staff roles within their scope, and the `Supervisor` may read across all scopes.

For the five staff roles — `IntakeOfficer`, `ClassificationOfficer`, `Scheduler`, `HealthGrievanceOfficer`, and `Supervisor` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow calls for it — for example, it stores the reporting officer's `X-User-ID` as `reported_by_user_id` on a `DisciplinaryInfraction` — but it never compares that value to any entity's `id`. When `X-User-Role` is `Visitor`, by contrast, `X-User-ID` is the `id` of the acting `Visitor` entity; ownership checks on any resource that references a `Visitor` compare the resource's `visitor_id` to `X-User-ID`.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a requested `limit` above 100 is capped at 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` in ascending order (oldest first) unless a subsection states otherwise. Every list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page) inside `meta`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — a UUID with no type prefix — at creation time, and carries a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on every mutation. These common properties apply to `Inmate`, `Booking`, `HousingUnit`, `Bed`, `HousingAssignment`, `CourtEvent`, `CommissaryAccount`, `CommissaryOrder`, `Visitor`, `Visit`, `Request`, `DisciplinaryInfraction`, and `PropertyItem`.

One entity is deliberately lightweight: a `ClassificationAssessment` is an immutable record of a scoring event and therefore carries only `id` and `created_at`. It has no `updated_at` and no `version`; a re-classification does not mutate a prior assessment but creates a new one that supersedes it.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC) against a parent entity's `version`, because several desks may act on the same booking or account between a client's read and its write.

When a `ClassificationOfficer` runs a classification assessment on a booking, the request must include `expected_booking_version` carrying the `version` of the target `Booking` that the client last observed. If that value does not equal the booking's current `version` — for example because an earlier assessment or an upheld infraction has already advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), rather than silently producing a second superseding assessment off a stale view.

When an `IntakeOfficer` places a commissary order, the request must include `expected_commissaryaccount_version` carrying the `version` of the target `CommissaryAccount` that the client last observed. Deposits, fulfillments, and refunds all advance the account's `version`; if the supplied value does not equal the account's current `version`, the order is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client re-reads the current balance before committing. No other endpoint takes a version field.

### 2.6. Validation Ordering and Error Precedence

When more than one condition could fail on a single request, checks are evaluated in a fixed priority order and the first failure determines the response. The ordering is: (1) authentication of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the operation (`ERR_UNAUTHORIZED`); (3) existence of every path-referenced resource, validated left-to-right along the URL so that a parent named earlier in the path is checked before a child named later (`ERR_NOT_FOUND`); (4) presence and correct typing of required body fields (`ERR_VALIDATION`); (5) enum-valued fields carrying a declared member (`ERR_INVALID_ENUM`); (6) interval end strictly after start where an interval is supplied (`ERR_INVALID_TIME_RANGE`); (7) the optimistic-concurrency version check (`ERR_STALE_VERSION`); then the domain-state and business rules described in §3 in ascending order of their guard — booking-not-released, booking-classified-before-housing, source-state validity, visitor-approval, segregation of duties, security-level match, gender match, bed double-booking, visit overlap, housing-unit capacity, sufficient funds, and finally release eligibility. Within §3 narratives each rule is stated next to the workflow it guards; this subsection fixes only their relative precedence.

### 2.7. Custody-Status Propagation and Cascades

Mutations frequently ripple across entities, and every such ripple must complete atomically within the request. When a booking is released, its person's `Inmate.status` is set to `RELEASED`; more generally, an inmate's `status` is `IN_CUSTODY` by default and becomes `RELEASED` when that person's latest booking is `RELEASED`. Ending a housing assignment frees its bed. Releasing a housed booking cascades all the way down: it ends the active housing assignment, which frees the bed and reduces the owning unit's occupied-bed count, and it returns every stored property item. Upholding a disciplinary infraction feeds forfeited good-time days back into the booking's release projection. Each of these cascades refreshes `updated_at` and increments the `version` of every entity it mutates. The concrete side effects are specified in the §3 subsection that owns each workflow.

### 2.8. Temporal Foundations and the Logical Clock

All timestamps are ISO 8601 UTC. Date-only fields (`date_of_birth`, `sentence_start_date`, `statutory_release_date`, `projected_release_date`) use the `YYYY-MM-DD` calendar-day form, and any arithmetic on release dates is calendar-day arithmetic with day counts floored to whole integers. "Current date" for release decisions is derived from the server's logical clock rather than wall-clock time. The clock starts at `2026-05-01T00:00:00Z`; before it is ever set it reads exactly this default and never falls back to real wall-clock time. A `Supervisor` may advance it by supplying a `to_iso8601` instant, after which reads return the supplied `current_utc`.

### 2.9. Monetary Precision and Ledger Conservation

All commissary money is held in whole cents as integers. Where a fractional cent arises during order pricing, the value is rounded half-up to the nearest whole cent, and — importantly — rounding happens per line before the lines are summed, never after. The commissary ledger is conservative: the sum of an account's funds plus the value tied up in fulfilled-but-not-refunded orders is preserved across every legal transition, which is why refunding a fulfilled order credits back exactly the amount that was debited when it was fulfilled. Deposits raise both the spendable balance and the lifetime deposit total.

## 3. Business Logic & Workflows

### 3.1. Intake, Booking, and Property

Intake begins when an `IntakeOfficer` registers a person, supplying `full_name`, `date_of_birth`, and `sex`. The `sex` value is one of `MALE` or `FEMALE` and later drives housing gender segregation. A newly registered inmate starts with `status` `IN_CUSTODY`.

Opening a custody episode is a separate step: an `IntakeOfficer` books an inmate by supplying the `inmate_id`, the `arrest_datetime`, the most serious `charge_severity` (one of `FELONY`, `MISDEMEANOR`, or `INFRACTION`), the `prior_bookings_count` (which must be zero or greater), the `sentence_days` (which must be strictly greater than zero), and the `sentence_start_date`. A new booking enters `booking_status` `BOOKED` and its `classification_level` is `null` until the first classification lands. At booking time the system immediately computes the statutory good-time credit and the resulting `statutory_release_date` (see §3.8), and it auto-creates a `CommissaryAccount` for the booking with a zero balance. A booking's `release_reason` is `null` until release.

During intake, an `IntakeOfficer` also logs each item of personal property held for safekeeping, supplying a `description` and a `category` (one of `CLOTHING`, `ELECTRONICS`, `CASH`, `DOCUMENTS`, or `OTHER`). A logged `PropertyItem` starts in `property_status` `STORED`. An `IntakeOfficer` may later return a single stored item to its owner, moving it from `STORED` to `RETURNED`; a return is permitted only when the item is currently `STORED`, otherwise `ERR_INVALID_STATE`. Stored items are also returned automatically as part of a release cascade (see §3.8).

### 3.2. Classification and Custody Scoring

A `ClassificationOfficer` classifies a booking by running an assessment whose `assessment_type` is either `INITIAL` or `REASSESSMENT`. The very first assessment must be `INITIAL` and drives the booking from `BOOKED` to `CLASSIFIED`. A `REASSESSMENT` may be run while the booking is `CLASSIFIED` or `HOUSED`; it leaves the booking in its current state (a `CLASSIFIED` booking stays `CLASSIFIED`, a `HOUSED` booking stays `HOUSED`) while producing a fresh assessment that supersedes the prior one. Every assessment request must also carry `expected_booking_version` for the OCC check described in §2.5, and every successful assessment increments the booking's `version` by 1.

Each assessment records its scoring breakdown as `severity_points`, `history_points`, `behavior_points`, `total_score`, and the `resulting_level`. Scoring works as follows. The `severity_points` come from the booking's `charge_severity`: a `FELONY` scores 30 points, a `MISDEMEANOR` scores 10 points, and an `INFRACTION` scores 5 points. The `history_points` are the booking's `prior_bookings_count` multiplied by 6 points per prior booking, capped at a maximum of 30 points. The `behavior_points` depend on the assessment type: for an `INITIAL` assessment they are forced to 0, while for a `REASSESSMENT` they add 15 points for each infraction on the booking that has been upheld. The `total_score` is the sum of severity, history, and behavior points. The `resulting_level` is derived from the total using inclusive thresholds: a total of at least 55 yields `MAX`, otherwise a total of at least 25 yields `MED`, and anything below 25 yields `MIN`. Because a `REASSESSMENT` adds behavior points that an `INITIAL` ignores, the same charge severity and history can produce a higher level after infractions accumulate. On every successful assessment the booking's `classification_level` is set to the `resulting_level`, and the booking's earned good-time credit and projected release date are recomputed now that the accrual rate implied by the level is known.

### 3.3. Housing Units, Beds, and Assignments

A `ClassificationOfficer` provisions housing by creating a `HousingUnit` with a `name`, a `security_level` (one of `MIN`, `MED`, or `MAX`), a `gender` the unit accepts (one of `MALE`, `FEMALE`, or `COED`), and a `capacity` that must be strictly greater than zero and caps the number of concurrently occupied beds. Beds are added to a unit one at a time with a `bed_label` unique within the unit; each `Bed` records the `housing_unit_id` of its containing unit and starts with `status` `AVAILABLE`. A unit's beds can be listed by that owning unit.

Assigning a booking to a bed is the act that houses an inmate. The `ClassificationOfficer` supplies the `booking_id`, the `bed_id`, a `start_datetime` marking the inclusive start of occupation, and optionally an `end_datetime` marking the exclusive end of occupation; when `end_datetime` is omitted the assignment is open-ended. A new `HousingAssignment` begins in `assignment_status` `ACTIVE`, sets its bed to `OCCUPIED` (incrementing the bed's `version`), and drives the booking from `CLASSIFIED` to `HOUSED`. Several guards apply, and they are evaluated in the precedence fixed in §2.6. The booking must already be `CLASSIFIED`; a booking that has never been classified is rejected with `ERR_BOOKING_NOT_CLASSIFIED`. If an `end_datetime` is supplied it must be strictly after the `start_datetime`, otherwise `ERR_INVALID_TIME_RANGE`. The bed's unit `security_level` must equal the booking's `classification_level`, otherwise `ERR_SECURITY_LEVEL_MISMATCH`. The unit's `gender` must accept the inmate's `sex`, where a `COED` unit accepts both a `MALE` and a `FEMALE` inmate, otherwise `ERR_GENDER_MISMATCH`. The requested interval must not overlap any existing `ACTIVE` assignment on that same bed, where overlap is judged on the half-open interval running from the inclusive `start_datetime` up to but not including the `end_datetime`; a clash is rejected with `ERR_BED_DOUBLE_BOOKED`. Finally, the unit must have room: counting the beds in the unit whose `status` is `OCCUPIED`, if that count is already at or above the unit's `capacity` the assignment is rejected with `ERR_HOUSING_UNIT_FULL`.

Ending an assignment un-houses the inmate. It is permitted only when an `ACTIVE` assignment exists for the booking; ending moves the `assignment_status` from `ACTIVE` to `ENDED`, frees the bed back to `AVAILABLE` (incrementing the bed's `version`), and returns the booking from `HOUSED` to `CLASSIFIED`. Housing assignments can be read individually or listed, and a list may be filtered by `booking_id`, by `bed_id`, or by both.

### 3.4. Commissary Accounts, Deposits, and Orders

Each booking owns exactly one `CommissaryAccount`, created automatically at booking time with `balance_cents` and `total_deposited_cents` both at zero. An `IntakeOfficer` deposits funds by supplying an `amount_cents`; a deposit adds that amount to `balance_cents`, adds the same amount to the lifetime `total_deposited_cents`, and increments the account's `version`.

An `IntakeOfficer` places an order against an account by supplying the order `lines` and the `expected_commissaryaccount_version` for the OCC check in §2.5. Each entry in `lines` names an `item_name`, a `quantity`, a `unit_price_cents`, and a boolean `taxable` flag. An order with an empty `lines` array or a non-positive `quantity` is rejected with `ERR_VALIDATION`. The `order_total_cents` is computed per line and then summed: for each line, the raw amount is the `quantity` multiplied by the `unit_price_cents`, and when the line is `taxable` that raw amount is further multiplied by 1 plus the tax rate of 0.0725; each line's raw amount is then rounded half-up to whole cents to yield the line total. The `order_total_cents` is the sum of the per-line totals plus a flat service fee of 25 cents. This per-line-then-sum ordering is mandatory; summing raw amounts before rounding is incorrect. The system also verifies at create time that the account's `balance_cents` covers the computed `order_total_cents`; if it does not, the order is rejected with `ERR_INSUFFICIENT_FUNDS`. A newly created `CommissaryOrder` records its `commissary_account_id`, enters `order_status` `PENDING`, and increments the account's `version` by 1.

Fulfilling a pending order is where money actually moves. An `IntakeOfficer` fulfills an order that is currently `PENDING`; fulfillment re-checks that `balance_cents` still covers `order_total_cents` (again `ERR_INSUFFICIENT_FUNDS` if not), then moves the order from `PENDING` to `FULFILLED`, debits the account's `balance_cents` by the `order_total_cents`, and increments the account's `version`. A `Supervisor` may refund an order that is currently `FULFILLED`; refunding moves it from `FULFILLED` to `REFUNDED`, credits the account's `balance_cents` back by exactly the `order_total_cents`, and increments the account's `version` — restoring the ledger-conservation invariant of §2.9. Orders may be listed for an account and read back individually.

### 3.5. Court Scheduling and Transport

A `Scheduler` schedules a court date on a booking by supplying the `event_datetime`, the `event_type` (one of `ARRAIGNMENT`, `HEARING`, `TRIAL`, or `SENTENCING`), and optionally whether `transport_required` — which defaults to true when omitted and indicates that custodial transport must be arranged. A new `CourtEvent` enters `court_event_status` `SCHEDULED` with a `continuance_count` of 0.

Court events follow a cyclic rescheduling pattern that momentarily passes through a `CONTINUED` state. When an event that is currently `SCHEDULED` is continued, the `Scheduler` supplies a `new_event_datetime`; within that single request the event moves `SCHEDULED → CONTINUED` — recording the prior time and incrementing the `continuance_count` by 1 — and then completes by re-scheduling to the `new_event_datetime`, returning `CONTINUED → SCHEDULED` with `event_datetime` set to the new value. The event therefore settles back in `SCHEDULED` and may be continued again later, growing `continuance_count` each time. A continue is allowed only from `SCHEDULED`. Separately, a `Scheduler` may mark a `SCHEDULED` event as attended, moving it from `SCHEDULED` to the terminal `ATTENDED`. Acting on an event that is not in a valid source state for the requested transition is rejected with `ERR_INVALID_STATE`. Court events may be listed per booking.

### 3.6. Visitation

Before anyone may visit, a `Scheduler` registers a visitor against an inmate by supplying the `visitor_name` and the `relationship` (one of `FAMILY`, `ATTORNEY`, `FRIEND`, or `CLERGY`); the resulting `Visitor` records its `inmate_id` and starts in `visitor_status` `PENDING`. A `Scheduler` approves a pending visitor, moving `visitor_status` from `PENDING` to `APPROVED`. Registered visitors for an inmate can be listed.

A visit joins a booking and a visitor. A `Scheduler` — or a `Visitor` acting on their own behalf — requests a visit by supplying the `booking_id`, the `visitor_id`, a `start_datetime` (inclusive), and an `end_datetime` (inclusive). The requested visit's `end_datetime` must be strictly after its `start_datetime`, otherwise `ERR_INVALID_TIME_RANGE`. The referenced visitor must already be `APPROVED`; a visit that names a still-`PENDING` visitor is rejected with `ERR_VISITOR_NOT_APPROVED`. The visit must not crowd another visit on the same booking: treating each visit as a closed interval and extending it by a 30-minute buffer on each side, a requested visit that falls within that buffered window of any other non-cancelled visit on the same booking is rejected with `ERR_VISIT_OVERLAP`. The requested visit is itself treated as a closed interval, and "falls within" is decided by closed-interval intersection: the request is rejected whenever the requested visit's closed interval and the buffered window overlap at all — including when they meet at exactly one boundary instant. Thus a requested visit whose `start_datetime` equals the prior visit's `end_datetime` plus 30 minutes (touching the buffered window's right edge), or whose `end_datetime` equals the prior visit's `start_datetime` minus 30 minutes (touching its left edge), is rejected. A new `Visit` enters `visit_status` `REQUESTED`.

A `Scheduler` approves a requested visit, moving it from `REQUESTED` to `APPROVED`. Either a `Scheduler` or the owning `Visitor` may cancel a visit that is currently `REQUESTED` or `APPROVED`, moving it to the terminal `CANCELLED`. Visits may be read individually or listed, and a list may be filtered by `booking_id`, by `visitor_id`, or by both. A `Visitor` may act only on their own visits, as fixed in §2.1.

### 3.7. Medical and Grievance Requests

A `HealthGrievanceOfficer` files a request against a booking by supplying the `request_type` (one of `MEDICAL` or `GRIEVANCE`) and a free-text `description`. A new `Request` enters `request_status` `SUBMITTED` with an `appeal_count` of 0. The same officer role drives the request through its lifecycle: a `SUBMITTED` request is moved into review, becoming `UNDER_REVIEW`; a request `UNDER_REVIEW` may then be resolved (terminal `RESOLVED`) or denied (`DENIED`).

Denial is not necessarily final. A `DENIED` request may be appealed back into review, which returns it from `DENIED` to `UNDER_REVIEW` and increments its `appeal_count` by 1; from there it may again be resolved or denied, so the review–deny–appeal cycle can repeat. Each of these transitions requires the request to be in the correct source state — submitted for review, under review for resolve or deny, denied for appeal — and a request that is not in the expected state is rejected with `ERR_INVALID_STATE`. Requests may be listed per booking.

### 3.8. Discipline, Good-Time Credit, and Release

Any staff role may report a disciplinary infraction on a booking, supplying the `infraction_type` (one of `CONTRABAND`, `ASSAULT`, `DISOBEDIENCE`, or `PROPERTY_DAMAGE`) and the `good_time_forfeit_days` to forfeit if the infraction is upheld (which must be zero or greater). The system records the reporting officer's `X-User-ID` as `reported_by_user_id` on the new `DisciplinaryInfraction`, which starts in `infraction_status` `REPORTED`. Only a `Supervisor` may uphold an infraction, and only while it is `REPORTED`. Upholding enforces segregation of duties: the upholder's `X-User-ID` must not equal the `reported_by_user_id` of the officer who reported it, and an attempt to uphold one's own report is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful uphold moves the infraction from `REPORTED` to `UPHELD`, adds its `good_time_forfeit_days` to the booking's `total_forfeited_days`, recomputes the booking's earned good-time credit and projected release date, and increments the booking's `version`. Infractions may be listed per booking.

Two independent good-time figures govern a booking's release outlook, and both can be read together. The **statutory** figure is fixed: `statutory_good_time_days` is the `sentence_days` multiplied by the statutory rate of 0.10, floored to a whole number of days, and `statutory_release_date` is the `sentence_start_date` advanced by the `sentence_days` minus the `statutory_good_time_days`. This figure ignores classification and behavior and is computed at booking time. The **earned** figure reflects behavior and custody level. Its accrual rate depends on the booking's `classification_level` — a `MIN` booking accrues at 0.25, a `MED` booking at 0.15, and a `MAX` booking at 0.05 — and an unclassified booking accrues at a rate of 0, so its earned credit is 0. The earned credit is computed by taking the `sentence_days` multiplied by that accrual rate and floored to whole days, subtracting the booking's `total_forfeited_days`, and then clamping the result to lie between 0 and a cap; the cap is the `sentence_days` multiplied by 0.20 and floored to whole days. In other words, `earned_good_time_days` is the accrued-minus-forfeited amount but never below 0 and never above the cap. The `projected_release_date` is the `sentence_start_date` advanced by the `sentence_days` minus the `earned_good_time_days`. Because the earned figure uses a class-specific rate and subtracts forfeitures while the statutory figure does not, the two release dates diverge for identical `sentence_days`; the earned projection is the one that governs release eligibility. These figures are recomputed whenever a classification lands and whenever an infraction is upheld, and a computed read exposes the `classification_level`, `total_forfeited_days`, `statutory_good_time_days`, `earned_good_time_days`, `statutory_release_date`, and `projected_release_date` together.

Release is reserved to a `Supervisor`, who supplies the `release_reason` (one of `TIME_SERVED`, `COURT_ORDER`, `BOND`, or `BAIL`). Eligibility depends on the reason. A discretionary reason — `COURT_ORDER`, `BOND`, or `BAIL` — is always eligible, with no date gate. A `TIME_SERVED` release is eligible only when the current date drawn from the logical clock has reached or passed the booking's `projected_release_date` (the comparison is at day granularity and inclusive of the projected date itself); a `TIME_SERVED` request before that date is rejected with `ERR_NOT_RELEASE_ELIGIBLE`. A booking may be released from `BOOKED`, `CLASSIFIED`, or `HOUSED`. Release drives the booking to the terminal `RELEASED`, sets the person's `Inmate.status` to `RELEASED`, and returns every `STORED` property item on the booking to `RETURNED`. When the booking was `HOUSED`, release additionally cascades: it ends the `ACTIVE` housing assignment (moving it to `ENDED`), which frees the bed to `AVAILABLE` and increments the bed's `version`, and the freed bed reduces its unit's occupied-bed count.

A booking that has reached `RELEASED` is closed to further activity. Attempting to place a commissary order, schedule a court event, create a housing assignment, request a visit, or file a request against a `RELEASED` booking is rejected with `ERR_BOOKING_RELEASED`.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; reads and state-changing actions that modify an existing resource return HTTP 200. Request and response payloads are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/inmates` | Register a person | IntakeOfficer |
| GET | `/inmates/{id}` | Read an inmate | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| GET | `/inmates/{id}/bookings` | List an inmate's bookings | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| GET | `/inmates/{id}/visitors` | List an inmate's registered visitors | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| POST | `/inmates/{id}/visitors` | Register a visitor for an inmate | Scheduler |
| POST | `/bookings` | Book an inmate (open a custody episode) | IntakeOfficer |
| GET | `/bookings/{id}` | Read a booking | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| GET | `/bookings/{id}/release-projection` | Read statutory vs. earned good-time and release dates | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| POST | `/bookings/{id}/classifications` | Run a classification assessment | ClassificationOfficer |
| GET | `/bookings/{id}/classifications` | List classification assessments | ClassificationOfficer, Supervisor |
| POST | `/bookings/{id}/release` | Release a booking | Supervisor |
| POST | `/housing-units` | Create a housing unit | ClassificationOfficer |
| GET | `/housing-units/{id}` | Read a housing unit | ClassificationOfficer, Supervisor |
| POST | `/housing-units/{id}/beds` | Add a bed to a unit | ClassificationOfficer |
| GET | `/housing-units/{id}/beds` | List beds in a unit | ClassificationOfficer, Supervisor |
| POST | `/housing-assignments` | Assign a booking to a bed | ClassificationOfficer |
| GET | `/housing-assignments/{id}` | Read a housing assignment | ClassificationOfficer, Supervisor |
| GET | `/housing-assignments` | List housing assignments (filter by `booking_id` / `bed_id`) | ClassificationOfficer, Supervisor |
| POST | `/housing-assignments/{id}/end` | End an active assignment (un-house) | ClassificationOfficer |
| GET | `/bookings/{id}/commissary-account` | Read the booking's commissary account | IntakeOfficer, Supervisor |
| GET | `/commissary-accounts/{id}` | Read a commissary account | IntakeOfficer, Supervisor |
| POST | `/commissary-accounts/{id}/deposits` | Deposit funds into an account | IntakeOfficer |
| POST | `/commissary-accounts/{id}/orders` | Place a commissary order | IntakeOfficer |
| GET | `/commissary-accounts/{id}/orders` | List orders on an account | IntakeOfficer, Supervisor |
| POST | `/commissary-orders/{id}/fulfill` | Fulfill a pending order | IntakeOfficer |
| POST | `/commissary-orders/{id}/refund` | Refund a fulfilled order | Supervisor |
| POST | `/bookings/{id}/court-events` | Schedule a court date | Scheduler |
| GET | `/bookings/{id}/court-events` | List court events for a booking | Scheduler, Supervisor |
| POST | `/court-events/{id}/continue` | Continue (reschedule) a court event | Scheduler |
| POST | `/court-events/{id}/attend` | Mark a court event attended | Scheduler |
| POST | `/visitors/{id}/approve` | Approve a visitor | Scheduler |
| POST | `/visits` | Request a visit | Scheduler, Visitor |
| GET | `/visits/{id}` | Read a visit | Scheduler, Supervisor, Visitor |
| GET | `/visits` | List visits (filter by `booking_id` / `visitor_id`) | Scheduler, Supervisor |
| POST | `/visits/{id}/approve` | Approve a requested visit | Scheduler |
| POST | `/visits/{id}/cancel` | Cancel a requested or approved visit | Scheduler, Visitor |
| POST | `/bookings/{id}/requests` | File a medical or grievance request | HealthGrievanceOfficer |
| GET | `/bookings/{id}/requests` | List requests for a booking | HealthGrievanceOfficer, Supervisor |
| POST | `/requests/{id}/review` | Move a request into review | HealthGrievanceOfficer |
| POST | `/requests/{id}/deny` | Deny a request under review | HealthGrievanceOfficer |
| POST | `/requests/{id}/appeal` | Appeal a denied request back into review | HealthGrievanceOfficer |
| POST | `/requests/{id}/resolve` | Resolve a request under review | HealthGrievanceOfficer |
| POST | `/bookings/{id}/infractions` | Report a disciplinary infraction | IntakeOfficer, ClassificationOfficer, Scheduler, HealthGrievanceOfficer, Supervisor |
| GET | `/bookings/{id}/infractions` | List infractions for a booking | ClassificationOfficer, Supervisor |
| POST | `/infractions/{id}/uphold` | Uphold an infraction (forfeits good-time) | Supervisor |
| POST | `/bookings/{id}/property` | Log a property item held at intake | IntakeOfficer |
| GET | `/bookings/{id}/property` | List property items for a booking | IntakeOfficer, Supervisor |
| POST | `/property-items/{id}/release` | Return a stored property item | IntakeOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Supervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOOKING_RELEASED` | 409 |
| `ERR_BOOKING_NOT_CLASSIFIED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VISITOR_NOT_APPROVED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SECURITY_LEVEL_MISMATCH` | 409 |
| `ERR_GENDER_MISMATCH` | 409 |
| `ERR_BED_DOUBLE_BOOKED` | 409 |
| `ERR_VISIT_OVERLAP` | 409 |
| `ERR_HOUSING_UNIT_FULL` | 409 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_NOT_RELEASE_ELIGIBLE` | 409 |
</content>
</invoke>
