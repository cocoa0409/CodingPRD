# Hospital Surgery Scheduling API — Product Requirements Document

## 1. Introduction

A modern operating-theatre suite is a tightly coupled system: each surgical case binds together a specialty-restricted operating room, a small team of qualified anesthesiologists and nurses, a sterile instrument set whose cleanliness expires on a clock, and a billing record that must reconcile estimates with actuals across multiple payers. The Hospital Surgery Scheduling API is the system-of-record that orchestrates this binding from the moment a surgeon's coordinator drafts a case request through department-head approval, scheduler-driven resource allocation, intra-operative state changes, and post-operative multi-payer settlement.

The API is mounted under the path prefix `/surgical-cases` for case-related capabilities and exposes parallel branches for operating rooms, staff rostering, instrument sterilization, settlement, and audit retrieval. It is built around two cross-cutting tensions that drive most of its rules. The first is **temporal**: rooms have turnover buffers, staff have shift windows and rolling 24-hour workload caps, and sterilized instrument trays expire 72 hours after they leave the autoclave. The second is **fiscal**: every scheduled case carries a forward-looking provisional estimate that must be reconciled — at the line-item level — against a chronological actual once the surgery completes, and the resulting total must be split across one or more insurance payers with a half-up rounding remainder absorbed by the primary payer.

A small number of design decisions deserve early framing. Pre-operative assessment and informed-consent verification are gating preconditions, not advisory checks; an EMERGENCY priority case may preempt non-emergency scheduled cases but is itself protected from preemption; sterilization expiry is enforced lazily on read and eagerly via a sweep capability so that no test of the 72-hour boundary depends on real wall-clock time. Time itself is represented as integer minutes against a logical clock that the test harness can advance directly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must include the headers `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP status 400. The system recognises five roles, each spelled exactly as shown: `SurgicalCoordinator`, `DepartmentHead`, `Scheduler`, `BillingAdmin`, and `Any`. The `Any` role denotes the read-only baseline that all authenticated users share.

When `X-User-Role` is `SurgicalCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records the actor on the `AuditEntry.actor_user_id` written by the coordinator's request but does not compare it to any entity's `id`. The same opaque-identity treatment applies when `X-User-Role` is `DepartmentHead`, when it is `Scheduler`, when it is `BillingAdmin`, and when it is `Any`: in all five cases `X-User-ID` is a free-form operator label, recorded in audit metadata but never used as a foreign-key match against an entity. Resource ownership in this system is therefore established by entity references in request bodies and path parameters (a case's `scheduled_room_id`, an assignment's `staff_id`, a booking's `instrument_set_id`, a settlement's `case_id`) rather than by `X-User-ID`.

If the role-bearing headers are present but the role is not on the authorized list for the requested operation, the server rejects the call with `ERR_INSUFFICIENT_PERMISSIONS` and HTTP status 403. The detailed authorized-roles mapping appears alongside the endpoint summary in §4.

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

List endpoints accept the optional query parameters `limit` and `offset`. The default for `limit` is 10, the minimum is 1, and the maximum is 100; the default for `offset` is 0. List endpoints sort by `created_at` ascending. The `meta` object on a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the standard `api_request_id` and `api_request_timestamp` fields.

### 2.4. Common Resource Properties, Identity, and Optimistic Concurrency

Every entity except `AuditEntry` carries four common properties: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no entity-type prefix. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation time and `updated_at` advances on every mutation, including cascade mutations triggered by operations on related entities. The `version` field is an integer that begins at 1 on creation and increments by 1 on every successful mutation, again including cascades.

`AuditEntry` is immutable: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

Mutation endpoints accept an optional `version` field in the request body to opt into optimistic concurrency control. When the client supplies `version` and it does not match the entity's current `version`, the server rejects the request with `ERR_STALE_DATA` and HTTP status 409. Omitting `version` from the request body skips the check.

### 2.5. Time, the Logical Clock, and Test-Driving Capabilities

All temporal fields in this API are integer minute offsets against a single server-maintained logical clock — referred to throughout as `current_minute` — rather than wall-clock timestamps. Cases are scheduled, started, completed, and preempted against `current_minute`; sterilization expiry, working-hour windows, and turnover buffers are likewise computed in minutes.

Two admin-only test-driving capabilities exist to make these temporal rules deterministically observable. The first advances the logical clock: the request body supplies a `delta_minutes` integer (which must be greater than 0; otherwise the request is rejected with `ERR_INVALID_TIME_PARAMETERS`), and on success the server reports the new `current_minute` value in the response body. The second forces a sterilization-expiration sweep across all currently-clean instrument sets and reports an `expired_count` on the response. Both capabilities are restricted to the `Scheduler` role.

### 2.6. Validation Priority and Error Surfacing

Validation in this system is **strictly priority-ordered**, and the order matters whenever a single request would fail more than one check. The server evaluates checks in the following sequence and surfaces only the first failure encountered:

1. The presence of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. The role's permission for this operation (`ERR_INSUFFICIENT_PERMISSIONS`).
3. The existence of every resource named by a path parameter, validated left-to-right — `caseId` is resolved before `assignmentId`, and so on for `roomId`, `staffId`, `instrumentSetId`, and `settlementId`. The first miss returns the specific not-found error for that resource: `ERR_CASE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_INSTRUMENT_SET_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND` (each at HTTP status 404). An assignment that exists but does not belong to the case named by `caseId` is treated as `ERR_ASSIGNMENT_NOT_FOUND`.
4. The existence of every entity id supplied in the request body (the `scheduled_room_id`, every `staff_id`, the `instrument_set_id`), evaluated in the order they appear in the request payload — first miss returns the same specific not-found error.
5. The state of the target entity for state-transition operations (`ERR_CASE_NOT_REQUESTED`, `ERR_CASE_NOT_APPROVED`, `ERR_CASE_NOT_SCHEDULED`, `ERR_CASE_NOT_IN_PROGRESS`, `ERR_CASE_NOT_COMPLETED`, `ERR_CASE_NOT_CANCELLABLE`, `ERR_INSTRUMENT_NOT_STERILIZED`, `ERR_INSTRUMENT_EXPIRED`, or `ERR_INVALID_STATE` — all at HTTP 409).
6. The all-assignments-confirmed precondition for surgery start (`ERR_ASSIGNMENT_NOT_CONFIRMED`).
7. Business safety preconditions in this internal sequence: pre-operative assessment attachment (`ERR_PRE_OP_ASSESSMENT_MISSING`), informed consent verification (`ERR_INFORMED_CONSENT_MISSING`), staff qualifications (`ERR_QUALIFICATION_MISMATCH`), staff shift windows (`ERR_STAFF_OUT_OF_SHIFT`), and staff role compatibility (`ERR_STAFF_ROLE_MISMATCH`).
8. Business referential preconditions on resource specialty: the room (`ERR_ROOM_SPECIALTY_RESTRICTED`) and the instrument set (`ERR_INSTRUMENT_SPECIALTY_MISMATCH`).
9. Temporal conflicts in this internal sequence: room turnover-buffer overlap (`ERR_ROOM_TIME_CONFLICT`), staff time conflict (`ERR_STAFF_TIME_CONFLICT`), and instrument booking conflict (`ERR_INSTRUMENT_TIME_CONFLICT`).
10. Capacity constraints: the rolling staff working-hours window (`ERR_STAFF_WORKING_HOURS_EXCEEDED`, HTTP 422).
11. Emergency-insertion's preempt-emergency guard (`ERR_CANNOT_PREEMPT_EMERGENCY`).
12. Fiscal preconditions on settlement: insurance-split summation (`ERR_INVALID_INSURANCE_SPLIT`) and pre-auth requirement at settle (`ERR_INSURANCE_PRE_AUTH_REQUIRED`, HTTP 402).
13. Optimistic concurrency (`ERR_STALE_DATA`).
14. Schema and value-range checks on the request body (`ERR_INVALID_REQUEST`, or `ERR_INVALID_TIME_PARAMETERS` for time-invariant violations such as `planned_end_minute` not being strictly greater than `planned_start_minute`, `shift_end_minute` not being strictly greater than `shift_start_minute`, or `delta_minutes` not being strictly greater than zero).

The above is the full priority ladder. When two checks are at the same level and could both fail (for example, the existence of two distinct path-parameter resources), the order specified within that level — left-to-right for path parameters, request-payload order for body ids — applies.

### 2.7. Currency Precision and Per-Component Rounding

Every monetary amount in the system carries two decimal places and is rounded **half-up**. When a calculation aggregates several components (room hours, staff hours, instrument fee, implant fee), each component is rounded to two decimal places **before** the components are summed; the system never sums first and rounds the total. The half-up convention applies equally to per-payer split allocations, where any rounding remainder produced by per-payer half-up rounding is then absorbed by the primary payer to make the per-payer amounts sum to the settlement total exactly.

### 2.8. Cascade Discipline, the Audit Trail, and Concurrency Resolution

Every successful state transition that mutates a related entity bumps both `updated_at` and `version` on every affected entity, including the cascading children — a case being scheduled bumps the `version` on the case, on each new `CaseAssignment`, on the `InstrumentBooking`, on the `InstrumentSet`, and on the `Settlement` whose `estimated_total_amount` has just been computed. Every such transition also appends an `AuditEntry`. Each audit row carries `actor_role` (the request's `X-User-Role`), `actor_user_id` (the request's `X-User-ID`), `entity_type` (the affected entity, for example `'SurgicalCase'`), `entity_id` (the affected entity's `id`), `action` (a logical action label such as `'CASE_REQUESTED'`, `'CASE_APPROVED'`, `'CASE_REJECTED'`, `'CASE_SCHEDULED'`, `'CASE_STARTED'`, `'CASE_COMPLETED'`, `'CASE_CANCELLED'`, `'EMERGENCY_INSERTED'`, `'EMERGENCY_PREEMPT'`, `'ASSIGNMENT_CONFIRMED'`, `'STERILIZATION_STARTED'`, `'STERILIZATION_COMPLETED'`, `'STERILIZATION_EXPIRED'`, `'SETTLEMENT_PRE_AUTHORIZED'`, `'SETTLEMENT_ITEMIZED'`, `'SETTLEMENT_SETTLED'`, or `'SETTLEMENT_REFUNDED'`), `payload` (a JSON snapshot of action-specific information at the moment of the event), and `occurred_at_minute` (the value of `current_minute` when the event occurred). Audit entries are append-only and immutable; clients can list them with `entity_type`, `entity_id`, and `action` filters to reconstruct any case or settlement's history.

The system is internally consistent — every cascade lands within the same logical transaction as the originating operation. When two operations race against the same shared resource, the contest resolves first-writer-wins on the entity field that the operation is gated by, and the loser receives a deterministic error: two simultaneous schedules competing for the same operating room and overlapping window resolve so that exactly one schedule succeeds and the other is rejected with `ERR_ROOM_TIME_CONFLICT` (HTTP 409); two simultaneous schedules competing for the same instrument set resolve so that exactly one succeeds and the other is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE` (HTTP 409) when the loser observes the instrument's `current_case_id` set but its `sterilization_status` not yet flipped to `CHECKED_OUT`; once the flip lands, a still-later schedule against the same set sees `CHECKED_OUT` and is rejected with `ERR_INSTRUMENT_NOT_STERILIZED`. A simultaneous approval and rejection on the same `REQUESTED` case resolves so that exactly one transition wins and the loser receives `ERR_INVALID_STATE` because the case is no longer in `REQUESTED`. Two simultaneous emergency-insertion attempts that would each preempt the same `SCHEDULED` case resolve so that exactly one preemption lands; the second observes the case already in `PREEMPTED` and is rejected with `ERR_INVALID_STATE`. A schedule attempt that races a sterilization-completion on the same instrument set resolves first-writer-wins on `sterilization_status`: when the completion runs first, the schedule sees `CLEAN_STERILIZED` and may proceed; when the schedule runs first against an `IN_STERILIZATION` set it is rejected with `ERR_INSTRUMENT_NOT_STERILIZED`.

## 3. Business Logic & Workflows

### 3.1. The Resource Pool: Operating Rooms, Staff Roster, and Instrument Sets

Before any case can be scheduled, three resource pools must be populated.

**Operating rooms.** A `Scheduler` registers a new operating room by supplying its hospital-internal label `room_number` (which must be unique within the hospital), its `room_type` (one of `GENERAL_OR`, `CARDIAC_OR`, `NEURO_OR`, or `OBSTETRIC_OR`), an `equipment_list` of equipment identifiers present in the room (for example `['HEART_LUNG_BYPASS','C_ARM_FLUOROSCOPE']`), the `specialty_required` it serves (one of `GENERAL`, `CARDIAC`, `NEURO`, or `OBSTETRIC`), and the `hourly_rate` charged in currency units per hour (a non-negative number with two decimal places). The room also carries a `turnover_buffer_minutes` value: this is the number of minutes that must elapse after one case ends before another may begin in the same room, and it defaults to 30 when not supplied at creation.

**Staff roster.** A `Scheduler` registers a clinician by supplying `staff_name`, `staff_role` (one of `ANESTHESIOLOGIST`, `SCRUB_NURSE`, or `CIRCULATING_NURSE`), `qualifications` (a list whose values are drawn from the set `GENERAL`, `CARDIAC`, `NEURO`, `OBSTETRIC`, and `PEDIATRIC`), `hourly_rate`, and the inclusive shift-window start `shift_start_minute` and the exclusive end `shift_end_minute` (which must be strictly greater than `shift_start_minute`). The optional `on_call` flag is `false` when omitted; it indicates whether the staff member is currently the on-call holder for their `staff_role`, and at most one on-call holder per role is permitted at any moment. A staff member's read response also includes two computed workload totals, `planned_workload_minutes` and `actual_workload_minutes`, defined in §3.6.

**Instrument sets.** A `Scheduler` registers a sterile instrument tray by supplying `set_name` (its operational label, e.g., `'GENERAL_LAPAROTOMY_TRAY'`) and `specialty` (one of `GENERAL`, `CARDIAC`, `NEURO`, or `OBSTETRIC`). On creation the tray's `sterilization_status` is set to `SOILED`, its `last_sterilized_at_minute` is `null` until the first sterilization completes, its `current_case_id` is `null`, and its `cycle_count` is 0. The full sterilization lifecycle is described in §3.5.

Each pool exposes a list capability and a get-by-id capability, both available to any authenticated role; lists support `limit` and `offset` pagination and filter by domain-specific attributes — staff lists filter by `staff_role`, instrument-set lists by `sterilization_status`, and case lists by `status`.

### 3.2. Case Application and Departmental Approval

A surgical case begins life as a request authored by a `SurgicalCoordinator`. The coordinator supplies the external `patient_id` (an opaque string supplied by the hospital identity system), the free-text `surgery_type` (such as `'CABG'` or `'Appendectomy'`), and the `specialty_required` (one of `GENERAL`, `CARDIAC`, `NEURO`, or `OBSTETRIC`). Three optional fields shape downstream behaviour: `priority` defaults to `ROUTINE` when omitted and otherwise must be `URGENT` or `EMERGENCY` (only routine cases follow the standard request-then-schedule path; emergency cases follow the dedicated insertion flow described in §3.8); `pre_op_assessment_attached` defaults to `false`, indicating whether the pre-operative assessment document has been attached; `informed_consent_verified` defaults to `false`, indicating whether informed consent has been verified. An optional `implant_cost_estimate` carries the projected implant component of the eventual bill — it defaults to `0.0` when omitted, must be a non-negative number with two decimal places, and is later compared against `implant_cost_actual` at completion.

A successful creation initialises the case's `status` to `REQUESTED`, leaves `scheduled_room_id`, `actual_start_minute`, `actual_end_minute`, `implant_cost_actual`, `rejected_reason`, `preempted_at_minute`, and `preempted_by_case_id` as `null`, and writes an `AuditEntry` whose `action` is `'CASE_REQUESTED'`. The case is created with a 201 response.

Once requested, a case is sent to the department head for clinical review. Approval by a `DepartmentHead` advances the case from `REQUESTED` to `APPROVED`, but only when both safety preconditions are met: the request must already have `pre_op_assessment_attached` set to `true` (otherwise the call is rejected with `ERR_PRE_OP_ASSESSMENT_MISSING`), and `informed_consent_verified` must already be `true` (otherwise rejected with `ERR_INFORMED_CONSENT_MISSING`). Note that the priority ladder of §2.6 evaluates assessment attachment before consent verification — when both flags are missing, the system surfaces the assessment error first, not the consent error. On approval, the system creates a `Settlement` for the case (`status` set to `DRAFT`, `case_id` set to the case's id, `estimated_total_amount` left as `null` until the case is scheduled, `final_total_amount` `null`, `line_items` an empty array, `insurance_split` an empty array, `per_payer_amounts` an empty array, `implant_cost` `0.0`, `refund_amount` `0.0`, and `insurance_pre_auth_reference` `null`), and writes an `AuditEntry` with `action` `'CASE_APPROVED'`.

Rejection by a `DepartmentHead` advances the case from `REQUESTED` to `REJECTED`. Rejection has no preconditions beyond the case being in `REQUESTED`. The optional `rejected_reason` from the request body is persisted (it remains `null` when not supplied), and an `AuditEntry` with `action` `'CASE_REJECTED'` is appended. `REJECTED` is terminal: a rejected case cannot be approved, scheduled, or otherwise advanced.

A request to approve or reject a case that is no longer in `REQUESTED` is rejected with `ERR_CASE_NOT_REQUESTED`.

### 3.3. Scheduling, Part 1 — Specialty, Shift, and Workload Gates

Scheduling an `APPROVED` case is the workflow's most demanding step and is performed by a `Scheduler`. The scheduler supplies a target `scheduled_room_id`, an integer `planned_start_minute`, an integer `planned_end_minute` (which must be strictly greater than `planned_start_minute`; otherwise `ERR_INVALID_TIME_PARAMETERS`), a `staff_assignments` list of records each carrying a `staff_id` and a `role_in_case` (one of `LEAD_ANESTHESIOLOGIST`, `SCRUB_NURSE`, or `CIRCULATING_NURSE`), and a single `instrument_set_id` for the case. The case must currently be in `APPROVED` (otherwise `ERR_CASE_NOT_APPROVED`).

Several gates must clear before the case advances from `APPROVED` to `SCHEDULED`. The room must serve the case's specialty: the room's `specialty_required` must equal the case's `specialty_required`, and a mismatch is rejected with `ERR_ROOM_SPECIALTY_RESTRICTED`. Every requested staff member must list the case's `specialty_required` among their `qualifications`; any staff member who does not is rejected with `ERR_QUALIFICATION_MISMATCH`. Every requested staff member's shift window must fully cover the planned interval — the staff member's `shift_start_minute` must be less than or equal to `planned_start_minute` and their `shift_end_minute` must be greater than or equal to `planned_end_minute`; a violation is rejected with `ERR_STAFF_OUT_OF_SHIFT`. Every staff member's `role_in_case` must be compatible with their `staff_role`: a `LEAD_ANESTHESIOLOGIST` requires the staff member to be an `ANESTHESIOLOGIST`, a `SCRUB_NURSE` requires the staff member to be a `SCRUB_NURSE`, and a `CIRCULATING_NURSE` requires the staff member to be a `CIRCULATING_NURSE`; any other pairing is rejected with `ERR_STAFF_ROLE_MISMATCH`.

The scheduler must also keep clinicians within the regulatory **rolling working-hour cap** of 12 hours per day. For each requested staff member, the system computes a 1440-minute window centred at the candidate `planned_start_minute` — that is, the window begins 720 minutes before the candidate start and ends 720 minutes after. Within that window, the system sums the duration in minutes (`assigned_end_minute` minus `assigned_start_minute`) of every existing `CaseAssignment` for that staff member whose `status` is one of `RESERVED`, `CONFIRMED`, or `COMPLETED` and whose half-open interval `[assigned_start_minute, assigned_end_minute)` intersects the 1440-minute window. The duration of the new schedule (`planned_end_minute` minus `planned_start_minute`) is added to that running total. If the resulting sum exceeds 720 minutes, the request is rejected with `ERR_STAFF_WORKING_HOURS_EXCEEDED` (HTTP 422); if the resulting sum is less than or equal to 720 minutes, the cap is satisfied. The boundary is therefore strict on the upper side — exactly 720 minutes including the new schedule passes; 721 minutes does not. `RELEASED` and `PREEMPTED` historical assignments are deliberately excluded from this sum because they no longer represent committed clinician time.

### 3.4. Scheduling, Part 2 — Temporal Conflict Gates and Resource Reservation

Once the specialty, shift, role, and workload gates have cleared, three temporal-conflict gates apply.

The **room turnover-buffer** check is enforced against every existing case in the same room whose `status` is `SCHEDULED` or `IN_PROGRESS`. For each such existing case, the system constructs an extended window `[planned_start_minute, planned_end_minute + turnover_buffer_minutes)` for the existing case and the same shape for the new schedule. If those two windows intersect in any way, the request is rejected with `ERR_ROOM_TIME_CONFLICT`. Boundary semantics are closed-gap: the test that **passes** is when the existing case's `planned_end_minute` plus the room's `turnover_buffer_minutes` is less than or equal to the new case's `planned_start_minute`. If exactly that boundary holds, the schedule succeeds; if the existing case's end-plus-buffer crosses the new case's start by even one minute, the schedule fails.

The **staff-time conflict** check rejects the schedule when any requested staff member already has a `CaseAssignment` whose `status` is `RESERVED` or `CONFIRMED` and whose half-open interval `[assigned_start_minute, assigned_end_minute)` overlaps the new case's planned half-open interval `[planned_start_minute, planned_end_minute)`. The error returned is `ERR_STAFF_TIME_CONFLICT`. The **instrument-time conflict** check rejects the schedule when the requested instrument set already has an `InstrumentBooking` whose `status` is `RESERVED` or `CHECKED_OUT` and whose owning case's planned half-open interval overlaps the new case's planned half-open interval; the error returned is `ERR_INSTRUMENT_TIME_CONFLICT`. (Specialty matching of the instrument set against the case's `specialty_required` is a referential check and is enforced before these temporal checks; see §3.5.)

When all gates clear, the system advances the case from `APPROVED` to `SCHEDULED` and pins the resources as a single atomic transaction. It persists the new `scheduled_room_id`, `planned_start_minute`, and `planned_end_minute` on the `SurgicalCase`. It creates one `CaseAssignment` per requested staff entry: the assignment carries the parent `case_id`, the supplied `staff_id`, the supplied `role_in_case`, an `assigned_start_minute` equal to the case's `planned_start_minute`, an `assigned_end_minute` equal to the case's `planned_end_minute`, and an initial `status` of `RESERVED`. It creates one `InstrumentBooking` carrying the parent `case_id`, the supplied `instrument_set_id`, and an initial `status` of `RESERVED`. It flips the instrument set's `sterilization_status` from `CLEAN_STERILIZED` to `CHECKED_OUT` and pins the instrument set's `current_case_id` to the case's id. It computes the case's provisional cost — described in §3.9 — and writes it to the settlement's `estimated_total_amount`. Finally, it writes an `AuditEntry` with `action` `'CASE_SCHEDULED'`. A request to schedule a case whose `status` is not `APPROVED` is rejected with `ERR_CASE_NOT_APPROVED`.

### 3.5. The Sterilization Cycle and the 72-Hour Expiry

An instrument set moves through a strict five-state cycle: `SOILED` → `IN_STERILIZATION` → `CLEAN_STERILIZED` → `CHECKED_OUT` → `SOILED`, with `CLEAN_STERILIZED` → `EXPIRED` as a side branch when the sterile shelf-life elapses, and `EXPIRED` → `IN_STERILIZATION` as the path back. There are no terminal states.

A `Scheduler` initiates sterilization on a `SOILED` or `EXPIRED` set, advancing its `sterilization_status` to `IN_STERILIZATION` and writing an `AuditEntry` with `action` `'STERILIZATION_STARTED'`. A request to begin sterilization on a set in any other state is rejected with `ERR_INVALID_STATE`. Completion of sterilization advances the set from `IN_STERILIZATION` to `CLEAN_STERILIZED`, sets `last_sterilized_at_minute` equal to the value of `current_minute` at the moment of completion, increments `cycle_count` by one, and writes an `AuditEntry` with `action` `'STERILIZATION_COMPLETED'`. The transition from `CLEAN_STERILIZED` to `CHECKED_OUT` is system-initiated as part of the scheduling cascade described in §3.4; the reverse transition from `CHECKED_OUT` back to `SOILED` is system-initiated as part of completion, cancellation, or preemption, and clears `current_case_id` to `null`.

A `CLEAN_STERILIZED` set has a sterile shelf-life of 72 hours. Concretely, when the difference between the current `current_minute` and the set's `last_sterilized_at_minute` reaches **4320 minutes or more** (the 72-hour conversion is exact), the set is considered `EXPIRED`. The boundary is inclusive on the high side: a set whose elapsed time is exactly 4320 minutes is `EXPIRED`; a set whose elapsed time is 4319 minutes remains `CLEAN_STERILIZED`. Expiry is enforced lazily on every read of the set — both the get-by-id and the list capability auto-flip any qualifying `CLEAN_STERILIZED` set to `EXPIRED` before responding — and eagerly via the sterilization sweep capability described in §2.5, which iterates every `CLEAN_STERILIZED` set, flips qualifying ones to `EXPIRED`, appends one `AuditEntry` per affected set with `action` `'STERILIZATION_EXPIRED'`, and reports the `expired_count` on the response.

A scheduling attempt against an instrument set in any non-clean state surfaces a precise reason. When the set is `SOILED`, `IN_STERILIZATION`, or `CHECKED_OUT`, the call is rejected with `ERR_INSTRUMENT_NOT_STERILIZED`. When the set is `EXPIRED`, the call is rejected with `ERR_INSTRUMENT_EXPIRED`. When the set's `current_case_id` indicates it is reserved to a different case but the status flip to `CHECKED_OUT` has not yet landed, the call is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`. When the set's `specialty` does not equal the case's `specialty_required`, the call is rejected with `ERR_INSTRUMENT_SPECIALTY_MISMATCH`.

### 3.6. Surgery Execution: Confirmation, Start, and Completion

Once a case is `SCHEDULED`, each `CaseAssignment` must be individually confirmed by a `Scheduler`, advancing the assignment from `RESERVED` to `CONFIRMED` and writing an `AuditEntry` with `action` `'ASSIGNMENT_CONFIRMED'`. Confirmation is gated only by the owning case being in `SCHEDULED` (otherwise `ERR_INVALID_STATE`).

Surgery start is a `Scheduler`-driven transition from `SCHEDULED` to `IN_PROGRESS`. The single precondition is that **every** `CaseAssignment` on the case has `status` equal to `CONFIRMED`; if any assignment is still in `RESERVED`, the call is rejected with `ERR_ASSIGNMENT_NOT_CONFIRMED`. On success, the system sets the case's `actual_start_minute` to the value of `current_minute` at the moment of the call, advances the `InstrumentBooking` from `RESERVED` to `CHECKED_OUT` (the underlying `InstrumentSet` is already in `CHECKED_OUT` from scheduling — this is the booking-side parity update only), and writes an `AuditEntry` with `action` `'CASE_STARTED'`. A request to start a case that is not in `SCHEDULED` is rejected with `ERR_CASE_NOT_SCHEDULED`.

Completion advances the case from `IN_PROGRESS` to `COMPLETED`, again driven by a `Scheduler`. The optional `implant_cost_actual` in the request body is persisted onto the case if supplied — when not supplied, the case retains the default `null` and the eventual final-cost calculation falls back to `implant_cost_estimate`. The system sets the case's `actual_end_minute` to the current `current_minute`, cascades every `CaseAssignment` for the case from `CONFIRMED` to `COMPLETED`, advances the `InstrumentBooking` from `CHECKED_OUT` to `RETURNED_SOILED`, flips the underlying `InstrumentSet`'s `sterilization_status` from `CHECKED_OUT` to `SOILED` and sets its `current_case_id` back to `null`, computes the case's chronological actual cost (described in §3.9) and writes it to the settlement's `final_total_amount`, and writes an `AuditEntry` with `action` `'CASE_COMPLETED'`. A request to complete a case that is not in `IN_PROGRESS` is rejected with `ERR_CASE_NOT_IN_PROGRESS`.

The two computed staff workload totals visible on a staff read are derived from the same set of `CaseAssignment` rows but with different filters and different time inputs. The forward-looking `planned_workload_minutes` sums `assigned_end_minute` minus `assigned_start_minute` over every `CaseAssignment` for this staff member whose `status` is one of `RESERVED`, `CONFIRMED`, or `COMPLETED` — that is, every still-on-the-books assignment, including those not yet started. `RELEASED` and `PREEMPTED` assignments are excluded because they no longer represent committed time. The chronological `actual_workload_minutes` sums the **owning case's** `actual_end_minute` minus `actual_start_minute` over only those `CaseAssignment` rows whose `status` is `COMPLETED`, joining each assignment to its owning `SurgicalCase`. Because the same assignment can contribute different durations to the two totals when the actual surgery ran longer or shorter than planned, a staff member's planned and actual workloads will routinely differ even though they are computed from the same ground-truth set of assignments. Both values are recomputed on every staff read; the system does not persist them.

### 3.7. Cancellation and Cascade Refund

Cancellation is performed by a `Scheduler` and is permitted on any non-terminal case — `APPROVED`, `SCHEDULED`, or `IN_PROGRESS`. Cancellation of a case in any other state (`REQUESTED`, `REJECTED`, `COMPLETED`, `CANCELLED`, or `PREEMPTED`) is rejected with `ERR_CASE_NOT_CANCELLABLE`.

The cascade depends on the `status` from which the case is cancelled.

Cancellation of an `APPROVED` case has no resources pinned yet. The system advances the case to `CANCELLED` and cascades the owning `Settlement` from `DRAFT` to `REFUNDED`. Because no schedule has yet computed an `estimated_total_amount`, that field is still `null` at this point and the system treats it as `0.0` for the purpose of writing `refund_amount` on the settlement — the refund record carries `0.0`. An `AuditEntry` with `action` `'CASE_CANCELLED'` is appended.

Cancellation of a `SCHEDULED` case unwinds the resource pinning. The case advances to `CANCELLED`. Every `CaseAssignment` on the case (in either `RESERVED` or `CONFIRMED`) cascades to `RELEASED`. The `InstrumentBooking` cascades from `RESERVED` to `RELEASED`. The underlying `InstrumentSet`'s `sterilization_status` flips from `CHECKED_OUT` to `SOILED` and its `current_case_id` is set back to `null`. The owning `Settlement` cascades from `DRAFT` to `REFUNDED` with its `refund_amount` set to the value of `estimated_total_amount` at the moment of cancellation. An `AuditEntry` with `action` `'CASE_CANCELLED'` is appended.

Cancellation of an `IN_PROGRESS` case is the exceptional path that arises when surgery has begun but the team aborts. The case advances to `CANCELLED`, the `actual_end_minute` is set to the current `current_minute` so the duration is recorded, every `CaseAssignment` (in `CONFIRMED`) cascades to `RELEASED`, the `InstrumentBooking` cascades from `CHECKED_OUT` to `RELEASED`, the underlying `InstrumentSet`'s `sterilization_status` flips from `CHECKED_OUT` to `SOILED` and its `current_case_id` is set to `null`, and the owning `Settlement` cascades to `REFUNDED` with `refund_amount` set to `estimated_total_amount`. An `AuditEntry` with `action` `'CASE_CANCELLED'` is appended.

When a settlement's lifecycle has progressed beyond `DRAFT` to `PRE_AUTHORIZED` at the moment its owning case is cancelled, the cascade still lands on `REFUNDED`, with `refund_amount` set to the coalesce of `final_total_amount` (if non-`null`), then `estimated_total_amount` (if non-`null`), then `0.0`. When a settlement is already `ITEMIZED` at the moment its owning case is cancelled (the exceptional path: a completed case under settlement workflow gets cancelled), the cascade still lands on `REFUNDED`, with `refund_amount` set to `final_total_amount`. In all cancellation paths, `updated_at` and `version` are bumped on every entity touched by the cascade — the case, every assignment, the booking, the instrument set, and the settlement.

### 3.8. Emergency Insertion and Priority-Based Preemption

Emergency cases follow a dedicated insertion flow that compresses the request → approve → schedule sequence into a single atomic operation and may displace conflicting non-emergency cases. The capability is `Scheduler`-only and accepts `patient_id`, `surgery_type`, `specialty_required`, `scheduled_room_id`, `planned_start_minute`, `planned_end_minute`, a `staff_assignments` list, an `instrument_set_id`, and an optional `implant_cost_estimate`. On success the new case is created with `priority` equal to `EMERGENCY`, `pre_op_assessment_attached` and `informed_consent_verified` both forced to `true` (the emergency context bypasses the request-time consent and assessment gates that govern routine flow), `status` advanced from `APPROVED` to `SCHEDULED` in one transaction, and a 201 status code on the response. An `AuditEntry` with `action` `'EMERGENCY_INSERTED'` is appended for the new case.

Before the new case is admitted, the system identifies the **preemptable pool** by scanning every existing `SurgicalCase` whose `status` is `SCHEDULED` and which overlaps the new case in at least one of three ways. The first overlap mode is shared room with time-and-buffer collision: the existing case's `scheduled_room_id` equals the new case's `scheduled_room_id` and the existing case's window `[planned_start_minute, planned_end_minute + turnover_buffer_minutes)` intersects the same shape on the new case. The second is shared staff: the existing case has a `CaseAssignment` whose `staff_id` matches one of the new case's requested `staff_id` values, and the existing case's planned window `[planned_start_minute, planned_end_minute)` overlaps the new case's planned window. The third is shared instrument: the existing case has an `InstrumentBooking` whose `instrument_set_id` equals the new case's `instrument_set_id` and the planned windows overlap. `IN_PROGRESS` cases are protected — they are never preemptable; the emergency must wait or use a different room. Any conflicting case whose own `priority` is `EMERGENCY` halts the entire request: the system rejects the emergency-insert with `ERR_CANNOT_PREEMPT_EMERGENCY` and performs no partial preemption.

Eligible cases — those that overlap the new case and whose own `priority` is not `EMERGENCY` — are preempted in a single atomic step. There is no ranking; every eligible case is preempted. For each preempted case, the system advances the case from `SCHEDULED` to `PREEMPTED`, sets `preempted_at_minute` to the current `current_minute`, sets `preempted_by_case_id` to the new emergency case's id, cascades every `CaseAssignment` (in `RESERVED` or `CONFIRMED`) to `PREEMPTED`, cascades the `InstrumentBooking` to `PREEMPTED`, flips the underlying `InstrumentSet`'s `sterilization_status` from `CHECKED_OUT` to `SOILED` and clears its `current_case_id`, cascades the owning `Settlement` to `REFUNDED` with `refund_amount` set to `estimated_total_amount`, and appends one `AuditEntry` per preempted case with `action` `'EMERGENCY_PREEMPT'`. If the preemptable pool is empty, the new emergency case is simply scheduled directly without displacement. The same business-safety, referential, and capacity checks that govern routine scheduling — staff qualification, shift coverage, role compatibility, room specialty, instrument specialty, and the rolling working-hours cap — apply to emergency insertion.

### 3.9. Settlement: Provisional Estimates, Final Costs, and Multi-Payer Splits

A `Settlement` is created with `status` `DRAFT` at the moment its owning case is approved (see §3.2). Its `case_id` is the owning case's id; one settlement exists per case.

**Provisional cost estimate.** When a case advances from `APPROVED` to `SCHEDULED`, the system computes the provisional total and writes it to `estimated_total_amount`. The computation is forward-looking: it uses the planned interval and the staff/room/instrument set selected at scheduling. First, it derives the planned duration in minutes as `planned_end_minute` minus `planned_start_minute`. It then converts that duration into billable hours by dividing by 60 and rounding **up** to the next whole number — billing is whole-hour, with any partial hour counted as a full hour. It then computes each cost component, rounding each to two decimal places half-up before summing: the room component is the billable hours multiplied by the operating room's `hourly_rate`; each staff component is the billable hours multiplied by that staff member's `hourly_rate`, computed once per `CaseAssignment` on the case at the moment of scheduling (when each assignment is in `RESERVED`); the instrument component is the per-set base fee of 150.00 currency units (one set per case); and the implant component is the case's `implant_cost_estimate`. Each per-component value is rounded to two decimal places half-up first, and only then are the four (or more, given multiple staff) components summed to produce `estimated_total_amount`. The settlement's `implant_cost` is set to the rounded implant component as part of the same write.

**Final settlement cost.** When the case advances from `IN_PROGRESS` to `COMPLETED`, the system computes the chronological actual total and writes it to `final_total_amount`. The structure is identical to the provisional calculation but the inputs are different: actual duration is `actual_end_minute` minus `actual_start_minute`, billable hours are derived by dividing the actual duration by 60 and rounding **up** to the next whole number, the staff components are computed only over `CaseAssignment` rows now in `COMPLETED`, and the implant component uses `implant_cost_actual` if non-`null` and falls back to `implant_cost_estimate` if `implant_cost_actual` is `null`. Per-component half-up rounding to two decimal places again precedes the sum. As a result, when actual duration exceeds planned duration the final total exceeds the estimate, and vice versa — the same settlement carries two different totals computed from the same staff and room set.

**Pre-authorization.** A `BillingAdmin` records insurance pre-authorization on a `DRAFT` settlement, supplying an `insurance_pre_auth_reference` (a free-text reference string). Pre-authorization is gated by the owning case being in `APPROVED`, `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` (otherwise `ERR_INVALID_STATE`). On success the settlement advances from `DRAFT` to `PRE_AUTHORIZED`, the supplied `insurance_pre_auth_reference` is persisted, and an `AuditEntry` with `action` `'SETTLEMENT_PRE_AUTHORIZED'` is appended.

**Itemization and per-payer split.** A `BillingAdmin` itemises a `PRE_AUTHORIZED` settlement once the owning case has reached `COMPLETED`; if the case is not in `COMPLETED` the call is rejected with `ERR_CASE_NOT_COMPLETED`. The request body carries `insurance_split`, an array of records each holding a `payer_id` and an integer `percentage`. The percentages must sum to exactly 100 — anything else is rejected with `ERR_INVALID_INSURANCE_SPLIT` — and the array order is significant: index 0 is the primary payer, and the relative input order is preserved on the persisted record. On success the settlement advances from `PRE_AUTHORIZED` to `ITEMIZED`. The system computes `line_items` as one entry per cost component (the room, each staff member, the instrument, and the implant), each entry carrying a `description`, a `category`, and a `fee` drawn from the corresponding component of the final settlement breakdown. It also computes `per_payer_amounts` as follows: for each entry in `insurance_split` in input order, the per-payer amount is the settlement's `final_total_amount` multiplied by that entry's `percentage` and divided by 100, then rounded to two decimal places half-up; the resulting record carries the entry's `payer_id` and that rounded amount. After every per-payer amount has been computed, the system computes the rounding remainder as `final_total_amount` minus the sum of the per-payer amounts (this remainder may be positive, zero, or negative) and adds it entirely to the primary payer (the entry at index 0). The other payers' amounts are left unchanged. The result is that the sum of `per_payer_amounts` equals `final_total_amount` exactly, while the primary payer absorbs any half-up rounding residue. An `AuditEntry` with `action` `'SETTLEMENT_ITEMIZED'` is appended.

**Settlement.** A `BillingAdmin` finalises an `ITEMIZED` settlement, advancing it from `ITEMIZED` to `SETTLED`. The single precondition is that `insurance_pre_auth_reference` is non-`null`; otherwise the call is rejected with `ERR_INSURANCE_PRE_AUTH_REQUIRED` (HTTP 402). An `AuditEntry` with `action` `'SETTLEMENT_SETTLED'` is appended.

**Refund cascades.** A settlement that has not yet `SETTLED` follows the cancellation and preemption cascades described in §3.7 and §3.8: a `DRAFT` settlement cascades to `REFUNDED` with `refund_amount` set to the coalesce of `final_total_amount`, `estimated_total_amount`, and `0.0` in that order; a `PRE_AUTHORIZED` settlement cascades to `REFUNDED` using the same coalesce; an `ITEMIZED` settlement cascades to `REFUNDED` with `refund_amount` set to `final_total_amount`. Settlement state-transition calls against settlements not in the expected source state are rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

All endpoints use POST for new-resource creation (returning HTTP 201) and POST for state-changing operations on existing resources (returning HTTP 200 with the updated resource); GET endpoints return HTTP 200. Path parameters are `caseId`, `roomId`, `staffId`, `instrumentSetId`, `assignmentId`, and `settlementId`. The body conventions, request fields, and response shape for each endpoint are reconstructed from §2 and §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST   | `/operating-rooms`                                          | Create a new operating room                                       | Scheduler |
| GET    | `/operating-rooms`                                          | List operating rooms                                              | Any |
| GET    | `/operating-rooms/{roomId}`                                 | Get a specific operating room                                     | Any |
| POST   | `/surgical-cases`                                           | Create a new surgical case request                                | SurgicalCoordinator |
| GET    | `/surgical-cases`                                           | List surgical cases                                               | Any |
| GET    | `/surgical-cases/{caseId}`                                  | Get a specific surgical case                                      | Any |
| POST   | `/surgical-cases/{caseId}/approve`                          | Department-head approval (REQUESTED → APPROVED)                   | DepartmentHead |
| POST   | `/surgical-cases/{caseId}/reject`                           | Department-head rejection (REQUESTED → REJECTED)                  | DepartmentHead |
| POST   | `/surgical-cases/{caseId}/schedule`                         | Schedule an APPROVED case onto room, staff, and instrument set    | Scheduler |
| POST   | `/surgical-cases/{caseId}/start`                            | Begin surgery (SCHEDULED → IN_PROGRESS)                           | Scheduler |
| POST   | `/surgical-cases/{caseId}/complete`                         | Complete surgery (IN_PROGRESS → COMPLETED)                        | Scheduler |
| POST   | `/surgical-cases/{caseId}/cancel`                           | Cancel a non-terminal case with cascade refund                    | Scheduler |
| POST   | `/surgical-cases/emergency-insert`                          | Insert an EMERGENCY case with cascade preemption                  | Scheduler |
| GET    | `/surgical-cases/{caseId}/assignments`                      | List assignments for a case                                       | Any |
| POST   | `/surgical-cases/{caseId}/assignments/{assignmentId}/confirm` | Confirm a RESERVED assignment (RESERVED → CONFIRMED)            | Scheduler |
| POST   | `/staff`                                                    | Create a staff roster entry                                       | Scheduler |
| GET    | `/staff`                                                    | List staff                                                        | Any |
| GET    | `/staff/{staffId}`                                          | Get a specific staff member (with computed workload totals)       | Any |
| POST   | `/instrument-sets`                                          | Create an instrument set (initial state SOILED)                   | Scheduler |
| GET    | `/instrument-sets`                                          | List instrument sets (auto-applies expiration on read)            | Any |
| GET    | `/instrument-sets/{instrumentSetId}`                        | Get a specific instrument set (auto-applies expiration on read)   | Any |
| POST   | `/instrument-sets/{instrumentSetId}/start-sterilization`    | Begin sterilization (SOILED \| EXPIRED → IN_STERILIZATION)        | Scheduler |
| POST   | `/instrument-sets/{instrumentSetId}/complete-sterilization` | Complete sterilization (IN_STERILIZATION → CLEAN_STERILIZED)      | Scheduler |
| GET    | `/settlements`                                              | List settlements                                                  | Any, BillingAdmin |
| GET    | `/settlements/{settlementId}`                               | Get a specific settlement                                         | Any, BillingAdmin |
| POST   | `/settlements/{settlementId}/pre-authorize`                 | Record insurance pre-authorization (DRAFT → PRE_AUTHORIZED)       | BillingAdmin |
| POST   | `/settlements/{settlementId}/itemize`                       | Itemize and split (PRE_AUTHORIZED → ITEMIZED)                     | BillingAdmin |
| POST   | `/settlements/{settlementId}/settle`                        | Mark settlement settled (ITEMIZED → SETTLED)                      | BillingAdmin |
| GET    | `/audit-entries`                                            | List audit entries (filters: entity_type, entity_id, action)      | Any |
| POST   | `/_clock/advance`                                           | Advance the logical clock (test-driving capability)               | Scheduler |
| POST   | `/_sweep/sterilization`                                     | Force a sterilization-expiration sweep                            | Scheduler |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_STAFF_NOT_FOUND` | 404 |
| `ERR_INSTRUMENT_SET_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_REQUESTED` | 409 |
| `ERR_CASE_NOT_APPROVED` | 409 |
| `ERR_CASE_NOT_SCHEDULED` | 409 |
| `ERR_CASE_NOT_IN_PROGRESS` | 409 |
| `ERR_CASE_NOT_COMPLETED` | 409 |
| `ERR_CASE_NOT_CANCELLABLE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 |
| `ERR_INSTRUMENT_NOT_STERILIZED` | 409 |
| `ERR_INSTRUMENT_EXPIRED` | 409 |
| `ERR_INSTRUMENT_NOT_AVAILABLE` | 409 |
| `ERR_PRE_OP_ASSESSMENT_MISSING` | 400 |
| `ERR_INFORMED_CONSENT_MISSING` | 400 |
| `ERR_QUALIFICATION_MISMATCH` | 400 |
| `ERR_STAFF_OUT_OF_SHIFT` | 400 |
| `ERR_STAFF_ROLE_MISMATCH` | 400 |
| `ERR_ROOM_SPECIALTY_RESTRICTED` | 400 |
| `ERR_INSTRUMENT_SPECIALTY_MISMATCH` | 400 |
| `ERR_ROOM_TIME_CONFLICT` | 409 |
| `ERR_STAFF_TIME_CONFLICT` | 409 |
| `ERR_INSTRUMENT_TIME_CONFLICT` | 409 |
| `ERR_STAFF_WORKING_HOURS_EXCEEDED` | 422 |
| `ERR_CANNOT_PREEMPT_EMERGENCY` | 409 |
| `ERR_INVALID_INSURANCE_SPLIT` | 400 |
| `ERR_INSURANCE_PRE_AUTH_REQUIRED` | 402 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_TIME_PARAMETERS` | 400 |
| `ERR_STALE_DATA` | 409 |
