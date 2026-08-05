# Diabetes Education & CGM Program (DSMES) API — Product Requirements Document

## 1. Introduction

Diabetes Self-Management Education and Support (DSMES) programs sit at the intersection of clinical education, medical-device logistics, and third-party billing. A patient arrives through a physician referral, is evaluated in an accreditation-required assessment, and — once enrolled — works through a structured curriculum of face-to-face education hours delivered either one-on-one or in a group classroom, frequently supplemented by a loaner continuous-glucose-monitor (CGM) or insulin pump. Every education hour a patient consumes draws down a finite annual Diabetes Self-Management Training (DSMT) benefit, and every completed encounter becomes a billable claim adjudicated by a payer. The program is only allowed to operate while its accrediting body keeps it in good standing.

This document specifies the REST API that backs such a program. The API must faithfully model four interlocking concerns: the **referral-to-enrollment pipeline** gated by accreditation and assessment; the **benefit-hour economy**, in which scheduled and completed education time competes for a capped pool of covered hours; the **scheduling fabric**, where dietitian calendars, classroom rooms, and group-class seats must not collide; and the **clinical-outcome loop**, where care-plan goals project an expected A1c reduction from education hours and later reconcile against a measured lab value. Because sessions carry two independent lifecycles — an encounter axis (was the patient seen?) and a billing axis (was the claim paid?) — and because no-shows, withdrawals, and suspensions cascade across many rows at once, the system's correctness depends on precise, deterministic bookkeeping rather than best-effort estimation.

The reader should treat this document as the single authoritative contract. Section 2 defines the system-wide invariants — authentication, response shape, pagination, identity and versioning, concurrency, validation ordering, and the accounting rules that govern hours and money. Section 3 narrates the business workflows in the order a real program would live them. Sections 4 and 5 enumerate the endpoint surface and the machine-readable error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly three roles, spelled precisely as follows:

- **`ProgramCoordinator`** — the operations role. Coordinators create programs, curricula, patients, dietitians, referrals, enrollments, group classes, and device enrollments; they drive enrollment lifecycle actions (activate, reinstate, withdraw) and referral rejection; and they alone advance the server's logical clock. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for an actor stamp, but it never compares it to any entity's `id`.

- **`Dietitian`** — the clinical educator. Dietitians perform the accreditation-required assessment, schedule and run both individual and group sessions, manage device activation, return, and reading ingest, and author, revise, reopen, and close care plans. When `X-User-Role` is `Dietitian`, `X-User-ID` is the `id` of the acting `Dietitian` entity; any workflow that records the acting educator (for example, stamping `assessed_by_dietitian_id` on a referral at assessment time) writes `X-User-ID`, and any ownership check on a resource that references a `Dietitian` compares that resource's dietitian foreign key to `X-User-ID`.

- **`BillingSpecialist`** — the revenue role. A specialist adjudicates submitted DSMT claims and otherwise has read access to all resources for reconciliation. When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

All three roles may call every `GET` (read) endpoint. Write endpoints are restricted as described above and enumerated in Section 4.

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

All list (collection `GET`) endpoints are paginated through two query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Requests supplying a `limit` or `offset` outside these bounds are rejected as malformed input with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` in ascending order (oldest first). Each paginated response reports `limit`, `offset`, `total_count` (the total number of matching records across all pages), and `has_more` (true when records remain beyond the current page) inside `meta`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id`, formatted as a UUID with no type prefix. Clients never supply an `id`; foreign-key references in request bodies always use these server-minted values.

Most resources also carry three common bookkeeping fields. `created_at` records the moment of creation and `updated_at` records the moment of the most recent mutation, both as ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that starts at 1 on creation and increments by 1 on every mutation of that resource. These common fields are present on `Program`, `Curriculum`, `Patient`, `Dietitian`, `Referral`, `Enrollment`, `Session`, `GroupClass`, `DeviceEnrollment`, and `CarePlan`.

`DeviceReading` is the sole exception. It is an append-only, immutable record: once a reading is accepted it is never updated. A `DeviceReading` therefore carries only `id` and `created_at` — it has neither `updated_at` nor `version`.

### 2.5. The Logical Clock and Temporal Semantics

The server maintains a **logical clock** that is the single source of "now" for every deadline, expiry, and windowing rule in the system. On startup the clock reads exactly `2026-05-01T00:00:00Z`; until a coordinator explicitly sets it, the clock stays at this default and never falls back to the machine's wall-clock time. A coordinator advances the clock by supplying a target instant in the `to_iso8601` field.

Fields whose `source` is a logical-clock reading — a referral's `assessment_completed_at`, an enrollment's `benefit_year_start`, a device's `activated_at` — are stamped from this clock at the moment their triggering action occurs. Derived temporal fields (`benefit_year_end`, `expires_on`) are computed from those stamps as described in Section 3.

### 2.6. Optimistic Concurrency Control

Two write operations mutate a shared, capacity-bearing parent and therefore require optimistic concurrency control (OCC). In each case the client must echo the `version` of the parent it last observed, and the server rejects the write if that value no longer matches the parent's current `version`.

- **Scheduling an individual session** requires `expected_enrollment_version` in the request body, carrying the client's last observed `version` of the target `Enrollment`. Each scheduled session debits the enrollment's finite benefit-hour pool and advances the enrollment's `version`, so a create still carrying a pre-debit version describes a pool the client has not actually seen. If `expected_enrollment_version` does not equal the enrollment's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and the pool is left untouched.

- **Reserving a group-class seat** requires `expected_group_class_version` in the request body, carrying the client's last observed `version` of the target `GroupClass`. Each reservation consumes finite seat capacity and advances the class's `version`. If `expected_group_class_version` does not equal the class's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no seat is consumed.

No other endpoint takes a version field. The OCC check is evaluated ahead of the business rules on these two endpoints so that a stale write can never mutate the benefit pool or seat count before being rejected.

### 2.7. Validation Ordering and Error Precedence

When more than one failure condition could apply to a single request, checks are evaluated in a fixed priority order, and the first failure encountered determines the response. The order is:

1. **Authentication** — headers present and valid, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform this operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named in the path and in the body exists, validated left-to-right in path order and then body order, else the corresponding `ERR_{RESOURCE}_NOT_FOUND` (404).
4. **Optimistic concurrency** — on the two OCC endpoints, a supplied `expected_<parent>_version` matches the parent's current `version`, else `ERR_STALE_VERSION` (412). This runs before any business rule so a stale write never mutates the pool.
5. **Body well-formedness** — required fields present, enum members valid, numeric values in range, else `ERR_VALIDATION` (400).
6. **Time-range sanity** — `scheduled_end` strictly after `scheduled_start`, else `ERR_INVALID_TIME_RANGE` (400).
7. **Enrollment-active gate** — the governing enrollment is `ACTIVE` where scheduling or device activation requires it, else `ERR_ENROLLMENT_NOT_ACTIVE` (409).
8. **Session encounter state** — the session is in a valid `encounter_status` for the requested encounter transition, else `ERR_SESSION_INVALID_STATE` (409).
9. **Referral assessed** — a referral is `ASSESSED` before an enrollment is created from it, else `ERR_REFERRAL_NOT_ASSESSED` (409).
10. **Program accredited** — the program is `ACCREDITED` before an enrollment activates, else `ERR_PROGRAM_NOT_ACCREDITED` (403).
11. **Curriculum type match** — the curriculum targets the patient's diabetes type, else `ERR_CURRICULUM_TYPE_MISMATCH` (409).
12. **Dietitian availability** — no double-booking of an individual session, else `ERR_DIETITIAN_DOUBLE_BOOKED` (409).
13. **Patient availability** — no patient time conflict for a group reservation, else `ERR_PATIENT_TIME_CONFLICT` (409).
14. **Seat capacity** — the class has a free seat, else `ERR_GROUP_CLASS_FULL` (409).
15. **Room availability** — a new group class clears the room buffer, else `ERR_ROOM_CONFLICT` (409).
16. **Benefit budget** — the schedule fits within the benefit cap, else `ERR_BENEFIT_HOURS_EXCEEDED` (402).
17. **Device window** — a device is active and within its loan window for reading ingest, else `ERR_DEVICE_EXPIRED` (409).
18. **Billing state** — the claim is `SUBMITTED` before adjudication, else `ERR_BILLING_INVALID_STATE` (409).

Not every check applies to every endpoint; each rule is scoped to the operations named in Section 3. Where several of these checks co-apply to one endpoint, their relative order above is authoritative. The numbered list is authoritative for the multi-check create and scheduling flows (individual-session scheduling and group-seat reservation), where body well-formedness (item 5) is validated before the enrollment-active, availability, capacity, and budget gates. On the single-transition action endpoints — referral assess/reject, session check-in/complete/no-show/cancel/adjudicate, enrollment activate/reinstate/withdraw, device activate/return/reading-ingest, and care-plan revise/reopen/close — the guard on the target resource's own current lifecycle state is instead evaluated before body well-formedness, so a request against a resource in the wrong state is rejected with that state error (including `ERR_DEVICE_EXPIRED` / `ERR_DEVICE_INVALID_STATE` on reading ingest) even when the body is independently malformed.

### 2.8. DSMT Benefit-Hour Accounting and Rounding

Education time is measured in **DSMT units** of 30 minutes each; each whole unit is worth exactly half an hour (0.5). The number of units in a span of minutes is that span divided by 30 and rounded **down** to a whole number — partial units never count. A single session's forward-looking **provisional hours** equal the whole units in its planned duration times 0.5, and its realized **final hours** equal the whole units in its actual face-to-face duration times 0.5.

Rounding order is strict and must not be shortcut: **each session is rounded to whole 30-minute units first, and only then are per-session hours summed at the enrollment level.** The system never sums raw minutes across sessions and divides once at the end — doing so would yield different totals and is incorrect.

An enrollment's benefit pool is capped by `benefit_hours_cap`. For an initial benefit year (`benefit_year_index` of 0) the cap is 10.0 hours; for any follow-up year (`benefit_year_index` of 1 or greater) the cap is 2.0 hours. Two running totals track consumption. `provisional_hours_used` is the sum of per-session provisional hours over every session of the enrollment whose `encounter_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; sessions in `NO_SHOW` or `CANCELLED` are excluded from this sum. `final_hours_used` is the sum of per-session final hours over only the sessions in `COMPLETED`. `hours_remaining` is `benefit_hours_cap` minus `provisional_hours_used`. All hour figures are multiples of 0.5.

### 2.9. Money, A1c, and Statistical Precision

Charges are always expressed in whole integer cents. Care-plan A1c deltas and device glucose averages are computed to **one decimal place using round-half-up**. Seat counts, no-show counts, unit counts, and module counts are integers. These precision rules are fixed contract: a value specified to one decimal is stored and returned at one decimal, and a value specified in cents is never expressed as a fractional currency amount.

### 2.10. Nested Resource Resolution and State Consistency

Where an endpoint path nests one resource under another — for example a device's readings under a device enrollment — path parameters are resolved strictly left to right, and the first missing ancestor yields its own `ERR_{RESOURCE}_NOT_FOUND` before any deeper resource is consulted.

Many operations mutate more than one resource in a single call. Whenever a mutation changes a resource, that resource's `updated_at` is refreshed and its `version` increments by 1. Cascades — a no-show that suspends an enrollment and cancels its remaining sessions, a withdrawal that cancels sessions and releases seats, a completion that advances an enrollment to `COMPLETED` and recomputes care-plan projections — are part of the same logical operation and are described in full in Section 3. Every downstream row a cascade touches is a real mutation and follows the same `updated_at`/`version` rules.

## 3. Business Logic & Workflows

### 3.1. Program, Curriculum, Patient, and Educator Setup

Before any patient can be served, a coordinator stands up the reference data. A **program** is created with a `name` and an `accreditation_body`, which is either `ADA` or `ADCES`. Its `accreditation_status` is one of `ACCREDITED`, `PROBATION`, or `LAPSED` and defaults to `ACCREDITED` when omitted; an optional `accreditation_expires_on` date may be recorded for information only. Only a program in `ACCREDITED` posture may host an activating enrollment, as described in 3.3.

A **curriculum** template is created with a `name`, a `diabetes_type_focus` (one of `TYPE_1`, `TYPE_2`, `GESTATIONAL`, `PREDIABETES`, or `ANY`), a `required_hours` figure (the completed education hours a patient must accumulate to finish the program, for example 10.0), and a `module_count` of curriculum modules. A **patient** is registered with an `mrn` (medical record number), a `full_name`, a `date_of_birth`, a `diabetes_type` (one of `TYPE_1`, `TYPE_2`, `GESTATIONAL`, or `PREDIABETES`), a `payer` (one of `MEDICARE`, `MEDICAID`, `COMMERCIAL`, or `SELF_PAY`), and a `baseline_a1c` percent recorded at intake (for example 8.0).

An **educator** — modeled as a dietitian — is registered with a `full_name`, an `npi` (National Provider Identifier), a `credential` (one of `RD`, `RN`, `CDCES`, or `PHARMD`), and an `active` flag that defaults to true when omitted. All four setup entities are coordinator-created and readable by every role.

### 3.2. Referral Intake and the Accreditation-Required Assessment

A patient enters the program through a **referral**, created by a coordinator with a `program_id`, a `patient_id`, the `referring_provider_npi` of the ordering clinician, and a `referral_reason` (one of `NEWLY_DIAGNOSED`, `POOR_CONTROL`, `MEDICATION_CHANGE`, or `ANNUAL_FOLLOWUP`). A newly created referral begins life in `RECEIVED`. Referrals may be listed with optional filters on `program_id`, `patient_id`, and `status`.

The accreditation-required **assessment** is a clinical step performed by a dietitian on a referral that is still in `RECEIVED`; attempting it from any other state fails with `ERR_REFERRAL_INVALID_STATE`. Completing the assessment advances the referral from `RECEIVED` to `ASSESSED`, stamps `assessment_completed_at` from the logical clock, records the supplied `assessed_a1c`, and denormalizes the acting educator's identity into `assessed_by_dietitian_id` (the `X-User-ID` of the calling dietitian, retained as an actor stamp rather than a navigable reference).

A coordinator may **reject** a referral while it is in either `RECEIVED` or `ASSESSED`; from any other state the rejection fails with `ERR_REFERRAL_INVALID_STATE`. Rejection moves the referral to the terminal `REJECTED` state and stores the optional free-text `rejection_reason`. The full set of referral states is `RECEIVED`, `ASSESSED`, `ENROLLED`, and `REJECTED`, of which `ENROLLED` and `REJECTED` are terminal. A referral reaches `ENROLLED` only as a bubble-up side effect of enrollment creation, never through a direct action.

### 3.3. Enrollment Creation, Activation, and Benefit-Year Anchoring

An **enrollment** is created by a coordinator from an assessed referral by supplying a `referral_id` and a `curriculum_id`. The referral must be in `ASSESSED`; a create against a referral in any other state is rejected with `ERR_REFERRAL_NOT_ASSESSED`. The chosen curriculum must fit the patient: its `diabetes_type_focus` must be `ANY` or must equal the patient's `diabetes_type`, otherwise the create is rejected with `ERR_CURRICULUM_TYPE_MISMATCH`. On success the new enrollment starts in `PENDING`; the system copies `patient_id` and `program_id` from the referral, copies the curriculum's `required_hours` into `required_curriculum_hours`, and — as a bubble-up side effect — transitions the source referral to its terminal `ENROLLED` state. Enrollments may be listed with optional filters on `referral_id`, `patient_id`, `curriculum_id`, `program_id`, and `status`.

An enrollment's `benefit_year_index` is fixed at 0 on creation and is not read from the request body, marking the initial DSMT benefit year; a value of 1 or greater would denote a follow-up year, but because re-anchoring across years is out of scope here the index never leaves 0 in practice. The `benefit_hours_cap` is derived from this index as described in 2.8 — 10.0 hours for the initial year and 2.0 hours for any follow-up year.

**Activation** is a coordinator action valid only from `PENDING`; from any other state it fails with `ERR_ENROLLMENT_INVALID_STATE`. Activation additionally requires the governing program to be `ACCREDITED`; if the program's `accreditation_status` is `PROBATION` or `LAPSED`, activation is refused with `ERR_PROGRAM_NOT_ACCREDITED`. On success the enrollment moves to `ACTIVE`, `benefit_year_start` is stamped from the logical clock's current instant (the full clock timestamp verbatim, not a date-only value), `benefit_year_end` is set to `benefit_year_start` plus 365 days, and the enrollment's `version` increments by 1.

Two further coordinator actions close out an enrollment's life. **Reinstatement** returns a `SUSPENDED` enrollment to `ACTIVE`; it is valid only from `SUSPENDED` (else `ERR_ENROLLMENT_INVALID_STATE`), increments `version` by 1, and deliberately does **not** reset `no_show_count` — historical no-show strikes persist across a suspension so a reinstated patient remains one strike from re-suspension if already at the threshold. **Withdrawal** takes an enrollment from either `ACTIVE` or `SUSPENDED` (else `ERR_ENROLLMENT_INVALID_STATE`) to the terminal `WITHDRAWN` state, accepting an optional `withdraw_reason`; as a cascade, every session of the enrollment still in `SCHEDULED` or `CHECKED_IN` is transitioned to `CANCELLED`, each such cancel reversing that session's provisional hours from `provisional_hours_used` and, for a group session, releasing its class seat. The complete enrollment state set is `PENDING`, `ACTIVE`, `SUSPENDED`, `COMPLETED`, and `WITHDRAWN`, with `COMPLETED` and `WITHDRAWN` terminal. Reaching `COMPLETED` happens only automatically, as described in 3.6.

### 3.4. Scheduling Individual Sessions

A dietitian schedules an **individual session** against an active enrollment. The request supplies the `enrollment_id`, the `dietitian_id` who will deliver it, the `modality` (`INDIVIDUAL` for this path), the `scheduled_start` and `scheduled_end` instants, an optional `is_telehealth` flag (defaulting to false, a place-of-service modifier that does not change any unit math), and `expected_enrollment_version` for the concurrency check. On creation the session's `encounter_status` is set to `SCHEDULED` and its `billing_status` to `UNBILLED`; `planned_minutes` is computed as the whole number of minutes between `scheduled_start` and `scheduled_end`; and `provisional_hours` is computed from `planned_minutes` per the unit rounding in 2.8.

Several guards apply to scheduling, in the precedence given in 2.7. The enrollment must be `ACTIVE`, or the request is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The `scheduled_end` must be strictly after `scheduled_start`, or the request is rejected with `ERR_INVALID_TIME_RANGE`. The `expected_enrollment_version` must match the enrollment's current `version`, or the request is rejected with `ERR_STALE_VERSION`, and this concurrency check runs before the hour-budget arithmetic so a stale request never touches the pool. The named dietitian must be free: if the dietitian already has another non-terminal individual session whose time window overlaps the requested `[scheduled_start, scheduled_end)` window, the request is rejected with `ERR_DIETITIAN_DOUBLE_BOOKED`. Overlap is evaluated on a half-open basis, so two sessions that merely touch at an endpoint (one ends exactly when the next begins) do not conflict. Finally, the schedule must fit the benefit: if `provisional_hours_used` plus this session's `provisional_hours` would exceed `benefit_hours_cap`, the request is rejected with `ERR_BENEFIT_HOURS_EXCEEDED`.

On success the enrollment's `provisional_hours_used` and `hours_remaining` are recomputed to include the new session, and the enrollment's `version` increments by 1 — which is precisely why a subsequent create must present a fresh `expected_enrollment_version`. Sessions may be listed with optional filters on `enrollment_id`, `dietitian_id`, `group_class_id`, `encounter_status`, and `billing_status`.

### 3.5. Group Classes and Seat Reservation

A coordinator schedules a **group class** by supplying a `curriculum_id`, the leading `dietitian_id`, a `room_id` used for room-conflict detection, the `scheduled_start` and `scheduled_end`, a seat `capacity`, and a `topic`. The class end must be strictly after its start, else `ERR_INVALID_TIME_RANGE`. Rooms are protected by a buffer: a new class in the same `room_id` must keep at least a 15-minute gap from every other class already booked in that room, where the comparison treats each class's time span as a closed interval and additionally requires the 15-minute cushion between them; a class that falls within that buffered window of another is rejected with `ERR_ROOM_CONFLICT`. A new class is created with `seats_taken` of 0. Group classes may be listed with optional filters on `curriculum_id` and `dietitian_id`.

A dietitian **reserves a seat** for a patient by creating a group session under a class, supplying the `enrollment_id`, an optional `is_telehealth` flag, and `expected_group_class_version`. The server synthesizes the session: `modality` is `GROUP`, `group_class_id` is set to the class, the `dietitian_id` is copied from the class's leader, and the session's times are copied from the class's `scheduled_start` and `scheduled_end`. As with individual scheduling, the enrollment must be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`) and the reservation must fit the benefit (else `ERR_BENEFIT_HOURS_EXCEEDED`). The `expected_group_class_version` must match the class's current `version`, else `ERR_STALE_VERSION`, checked before capacity is consumed. The reserving patient must have no other non-terminal session that overlaps the class's time window, else `ERR_PATIENT_TIME_CONFLICT`. And the class must have a free seat: if `seats_taken` (measured before this reservation) has already reached `capacity`, the reservation is rejected with `ERR_GROUP_CLASS_FULL`.

On success the new group session enters `SCHEDULED`, its provisional hours are debited to the enrollment exactly as for an individual session, `seats_taken` is incremented by 1, and the class's `version` increments by 1. A class's `seats_taken` is defined as the count of group sessions referencing that class whose `encounter_status` is `SCHEDULED`, `CHECKED_IN`, `COMPLETED`, or `NO_SHOW`; a `CANCELLED` group session releases its seat and drops out of this count.

### 3.6. Session Encounter Lifecycle, No-Shows, Completion, and Cascades

Each session carries two independent axes: an **encounter** axis and a **billing** axis (covered in 3.7). The encounter axis has states `SCHEDULED`, `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, and `CANCELLED`, of which the last three are terminal. Every encounter transition is a dietitian action and requires the session to be in the correct originating state; any mismatch is rejected with `ERR_SESSION_INVALID_STATE`.

**Check-in** advances a session from `SCHEDULED` to `CHECKED_IN` and has no accounting side effects. **Completion** advances a session from `CHECKED_IN` to `COMPLETED` and is the system's most consequential encounter step: the caller supplies `actual_minutes` (the face-to-face minutes actually delivered); `final_hours` is computed from `actual_minutes` per the 30-minute unit rounding; `billable_units` and `charge_cents` are computed per the billing rules in 3.7 using the benefit units remaining *before* this completion; the session's `billing_status` moves from `UNBILLED` to `SUBMITTED`; and the enrollment's `final_hours_used` is recomputed to include this session. If, after that recomputation, `final_hours_used` is at least `required_curriculum_hours`, the enrollment automatically transitions from `ACTIVE` to the terminal `COMPLETED` state, and that transition in turn recomputes `projected_a1c_delta` on each `OPEN` care plan of the enrollment from the new `final_hours_used`.

**No-show** advances a session from `SCHEDULED` to `NO_SHOW`. Because a no-show session leaves the provisional set, the enrollment's `provisional_hours_used` is recomputed to exclude it, and the enrollment's `no_show_count` (the count of that enrollment's sessions in `NO_SHOW`) increases by 1. A no-show on a group session keeps its class seat consumed. When `no_show_count` reaches the suspension threshold of 3 while the enrollment is `ACTIVE`, the enrollment automatically transitions from `ACTIVE` to `SUSPENDED`; that suspension cascades by cancelling every remaining session of the enrollment still in `SCHEDULED` or `CHECKED_IN`, and each cascaded cancel reverses that session's provisional hours from `provisional_hours_used` and, for a group session, releases its class seat. After the cascade, `provisional_hours_used` and `hours_remaining` are recomputed.

**Cancellation** takes a session from either `SCHEDULED` or `CHECKED_IN` to `CANCELLED`, accepting an optional `cancel_reason`. Cancelling reverses the session's `provisional_hours` from the enrollment's `provisional_hours_used` (and recomputes `hours_remaining`), and if the session is a group session it decrements the class's `seats_taken` by 1, freeing the seat for another patient.

### 3.7. Claim Billing and Adjudication

The **billing** axis is independent of the encounter axis and advances only after an encounter completes. Its states are `UNBILLED`, `SUBMITTED`, `PAID`, and `DENIED`, with `PAID` and `DENIED` terminal. A session is created `UNBILLED`; on encounter completion it automatically becomes `SUBMITTED`, at which point `billable_units` and `charge_cents` are pinned.

Billing is computed as follows at completion. First, the benefit units still available before this completion are determined: take `benefit_hours_cap` minus the enrollment's `final_hours_used` as measured *before* this session's completion, divide by the half-hour unit value to express it in whole 30-minute units. The session's raw units are the whole 30-minute units in its `actual_minutes` (its `actual_minutes` divided by 30, rounded down). The `billable_units` are the smaller of those raw units and the remaining benefit units, where the remaining benefit units are floored at 0 so the program never bills below zero — in other words a session can never bill more units than the benefit still permits. The per-unit rate depends on modality: an `INDIVIDUAL` session bills at 5000 cents per unit and a `GROUP` session at 1500 cents per unit. The `charge_cents` is `billable_units` multiplied by that per-unit rate, expressed as whole integer cents.

A **BillingSpecialist** adjudicates a submitted claim by supplying a `billing_decision`. The session's `billing_status` must be `SUBMITTED`, or the request is rejected with `ERR_BILLING_INVALID_STATE`. A decision of `PAID` moves the billing status to `PAID`; a decision of `DENIED` moves it to `DENIED`. Both are terminal on the billing axis, and neither alters the encounter axis — a session that already reached `COMPLETED` continues to evolve only on the billing axis.

### 3.8. Device Enrollment, Loans, and CGM Readings

A coordinator requests a **device enrollment** for an education enrollment by supplying the `enrollment_id`, a `device_type` (one of `CGM`, `INSULIN_PUMP`, or `SMART_PEN`), and a `serial_number`. The device begins in `REQUESTED`. The device lifecycle states are `REQUESTED`, `ACTIVE`, `RETURNED`, and `EXPIRED`, with `RETURNED` and `EXPIRED` terminal. Device enrollments may be listed with optional filters on `enrollment_id` and `status`.

**Activation** is a dietitian action valid only from `REQUESTED` (else `ERR_DEVICE_INVALID_STATE`) and additionally requires the governing education enrollment to be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`). On activation the device moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `expires_on` is set to `activated_at` plus 90 days — the device loan window. A dietitian may **return** an `ACTIVE` device (else `ERR_DEVICE_INVALID_STATE`), moving it to the terminal `RETURNED` state.

A dietitian **ingests a reading** by posting a `glucose_mgdl` sensor value and the `measured_at` instant at which it was captured. Ingest requires the device to be `ACTIVE` and the logical clock to be at or before `expires_on`. A device that is not `ACTIVE` because it is still `REQUESTED` or already `RETURNED` rejects the ingest with `ERR_DEVICE_INVALID_STATE`, and a device already in `EXPIRED` rejects it with `ERR_DEVICE_EXPIRED`; this device state-and-window check runs before the body is validated for `glucose_mgdl` and `measured_at`. If the device is `ACTIVE` but the current clock is past `expires_on`, the reading is rejected with `ERR_DEVICE_EXPIRED`, no reading is persisted, and the device transitions to the terminal `EXPIRED` state. An accepted reading is stored as an immutable `DeviceReading` referencing its `device_enrollment_id`, and the owning device's rollups are recomputed: `readings_count` is the number of accepted readings; `avg_glucose_mgdl` is the mean of `glucose_mgdl` across accepted readings, to one decimal with round-half-up; and `latest_glucose_mgdl` is the `glucose_mgdl` of the reading with the greatest `measured_at`, breaking ties by the earlier `created_at`. A device's readings can be listed in a reverse-navigable collection under the device.

### 3.9. Care Plans, Goal Revision, and A1c Outcomes

A dietitian authors a **care plan** for an enrollment by supplying the `enrollment_id`, a `goal_description` narrative, and a `target_a1c`. On creation the plan is `OPEN`, its `baseline_a1c` is copied from the enrollment's patient, its `revision_count` starts at 0, and its `projected_a1c_delta` is computed. The projection estimates the A1c reduction the patient can expect from completed education: it is the enrollment's `final_hours_used` multiplied by 0.1 percentage points of reduction per completed hour, but never more than the room between the patient's `baseline_a1c` and a clinical floor of 6.5 — that is, it is capped at `baseline_a1c` minus 6.5 (and never below 0 when the baseline is already at or under the floor). The projection is carried to one decimal place with round-half-up. Care plans may be listed with optional filters on `enrollment_id` and `status`.

The plan states are `OPEN`, `REVISED`, `MET`, and `NOT_MET`, with `MET` and `NOT_MET` terminal. **Revising** a plan is valid only from `OPEN` (else `ERR_CARE_PLAN_INVALID_STATE`); it moves the plan to `REVISED`, overwrites `target_a1c` with the supplied value, and increments `revision_count` by 1. **Reopening** is valid only from `REVISED` (else `ERR_CARE_PLAN_INVALID_STATE`); it returns the plan to `OPEN` and recomputes `projected_a1c_delta` from the current `final_hours_used`. This same recomputation is what the enrollment's automatic completion performs against every `OPEN` plan, so a plan's projection always reflects the latest realized education hours.

**Closing** a plan records the outcome. The caller supplies an `outcome` and a `measured_a1c`; closing is valid only from `OPEN` (else `ERR_CARE_PLAN_INVALID_STATE`). An `outcome` of `MET` moves the plan to `MET` and a `NOT_MET` outcome moves it to `NOT_MET`; in both cases `measured_a1c` is recorded and `final_a1c_delta` is set to the patient's `baseline_a1c` minus the `measured_a1c`, carried to one decimal with round-half-up. The final delta is the realized reduction from a measured lab value and, unlike the projection, does not depend on education hours.

## 4. Endpoint Definitions

All endpoints are mounted under the `/dsmes` prefix (the logical-clock utility excepted). Resource-creating operations return HTTP 201 with the created resource; state-changing action and clock operations return HTTP 200 with the affected resource (or an empty object for the clock); reads return HTTP 200. Authentication and authorization are enforced on every endpoint as described in Section 2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramCoordinator |
| POST | `/dsmes/programs` | Create a DSMES program | ProgramCoordinator |
| GET | `/dsmes/programs/{id}` | Get a program | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/curricula` | Create a curriculum template | ProgramCoordinator |
| GET | `/dsmes/curricula/{id}` | Get a curriculum | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/patients` | Register a patient | ProgramCoordinator |
| GET | `/dsmes/patients/{id}` | Get a patient | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/dietitians` | Register a dietitian / educator | ProgramCoordinator |
| GET | `/dsmes/dietitians/{id}` | Get a dietitian | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/referrals` | Create a referral (RECEIVED) | ProgramCoordinator |
| GET | `/dsmes/referrals/{id}` | Get a referral | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/referrals` | List referrals (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/referrals/{id}/assess` | Complete the accreditation-required assessment (RECEIVED → ASSESSED) | Dietitian |
| POST | `/dsmes/referrals/{id}/reject` | Reject a referral | ProgramCoordinator |
| POST | `/dsmes/enrollments` | Create an enrollment from an ASSESSED referral (PENDING) | ProgramCoordinator |
| GET | `/dsmes/enrollments/{id}` | Get an enrollment (with computed hours) | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/enrollments` | List enrollments (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/enrollments/{id}/activate` | Activate an enrollment (PENDING → ACTIVE) | ProgramCoordinator |
| POST | `/dsmes/enrollments/{id}/reinstate` | Reinstate a suspended enrollment (SUSPENDED → ACTIVE) | ProgramCoordinator |
| POST | `/dsmes/enrollments/{id}/withdraw` | Withdraw an enrollment (ACTIVE\|SUSPENDED → WITHDRAWN) | ProgramCoordinator |
| POST | `/dsmes/sessions` | Schedule an INDIVIDUAL session | Dietitian |
| GET | `/dsmes/sessions/{id}` | Get a session | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/sessions` | List sessions (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/sessions/{id}/check-in` | Check in a session (SCHEDULED → CHECKED_IN) | Dietitian |
| POST | `/dsmes/sessions/{id}/complete` | Complete a session (CHECKED_IN → COMPLETED); computes final hours and billing | Dietitian |
| POST | `/dsmes/sessions/{id}/no-show` | Mark a session NO_SHOW (SCHEDULED → NO_SHOW) | Dietitian |
| POST | `/dsmes/sessions/{id}/cancel` | Cancel a session (SCHEDULED\|CHECKED_IN → CANCELLED) | Dietitian |
| POST | `/dsmes/sessions/{id}/adjudicate` | Adjudicate a submitted claim (SUBMITTED → PAID\|DENIED) | BillingSpecialist |
| POST | `/dsmes/group-classes` | Create a group class (room-conflict checked) | ProgramCoordinator |
| GET | `/dsmes/group-classes/{id}` | Get a group class | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/group-classes` | List group classes (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/group-classes/{id}/sessions` | Reserve a seat: create a GROUP session for an enrollment | Dietitian |
| POST | `/dsmes/device-enrollments` | Enroll a CGM/pump device (REQUESTED) | ProgramCoordinator |
| GET | `/dsmes/device-enrollments/{id}` | Get a device enrollment | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/device-enrollments` | List device enrollments (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/device-enrollments/{id}/activate` | Activate a device (REQUESTED → ACTIVE); requires enrollment ACTIVE | Dietitian |
| POST | `/dsmes/device-enrollments/{id}/return` | Return a device (ACTIVE → RETURNED) | Dietitian |
| POST | `/dsmes/device-enrollments/{id}/readings` | Ingest a CGM reading; rejected (and device → EXPIRED) if past expires_on | Dietitian |
| GET | `/dsmes/device-enrollments/{id}/readings` | List a device's readings | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/care-plans` | Create a care plan / goal (OPEN) | Dietitian |
| GET | `/dsmes/care-plans/{id}` | Get a care plan | ProgramCoordinator, Dietitian, BillingSpecialist |
| GET | `/dsmes/care-plans` | List care plans (filterable) | ProgramCoordinator, Dietitian, BillingSpecialist |
| POST | `/dsmes/care-plans/{id}/revise` | Revise the target (OPEN → REVISED) | Dietitian |
| POST | `/dsmes/care-plans/{id}/reopen` | Reopen a revised plan (REVISED → OPEN) | Dietitian |
| POST | `/dsmes/care-plans/{id}/close` | Close the plan with an outcome (OPEN → MET\|NOT_MET) | Dietitian |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_TIME_RANGE | 400 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_CURRICULUM_NOT_FOUND | 404 |
| ERR_PATIENT_NOT_FOUND | 404 |
| ERR_DIETITIAN_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_GROUP_CLASS_NOT_FOUND | 404 |
| ERR_DEVICE_ENROLLMENT_NOT_FOUND | 404 |
| ERR_CARE_PLAN_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_REFERRAL_INVALID_STATE | 409 |
| ERR_REFERRAL_NOT_ASSESSED | 409 |
| ERR_ENROLLMENT_INVALID_STATE | 409 |
| ERR_ENROLLMENT_NOT_ACTIVE | 409 |
| ERR_SESSION_INVALID_STATE | 409 |
| ERR_BILLING_INVALID_STATE | 409 |
| ERR_DEVICE_INVALID_STATE | 409 |
| ERR_CARE_PLAN_INVALID_STATE | 409 |
| ERR_PROGRAM_NOT_ACCREDITED | 403 |
| ERR_CURRICULUM_TYPE_MISMATCH | 409 |
| ERR_DIETITIAN_DOUBLE_BOOKED | 409 |
| ERR_PATIENT_TIME_CONFLICT | 409 |
| ERR_ROOM_CONFLICT | 409 |
| ERR_GROUP_CLASS_FULL | 409 |
| ERR_BENEFIT_HOURS_EXCEEDED | 402 |
| ERR_DEVICE_EXPIRED | 409 |
