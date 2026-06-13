# Chiropractic Practice API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Chiropractic Practice API, a back-office system that runs a multi-provider chiropractic clinic from the first intake exam through long-term maintenance care. The practice's daily reality is a tangle of competing constraints: a patient's insurance carrier will only pay for a finite number of visits per benefit year, treatment plans evolve through clinical phases of differing intensity, recurring weekly appointment series must be threaded around provider availability and room turnover, and the same adjustment may be billed three completely different ways depending on whether the patient pays cash, carries insurance, or holds a wellness membership.

The API is the single source of truth for scheduling, clinical documentation, and money. It models the patient as the clinical aggregate root — exams, treatment plans, phases, appointment series, appointments, SOAP notes, and ledger entries all hang off the patient — while providers, treatment rooms, fee schedules, wellness plans, and insurance policies are configured as shared resources referenced wherever they are needed. Every booking reserves an insurance cap slot, every completed visit posts a charge whose amount depends on the patient's payer mode, and every no-show or late cancellation accrues a strike that can ultimately dismiss a patient from the practice. Because so many of these effects cascade — completing the last visit of a phase advances the plan, regressing a phase regenerates a whole series of appointments and re-reserves cap slots — the system resolves every consequence of an action atomically inside the request that triggered it.

The audience for this document is the engineering team building the service. It describes the domain rules first and the wire contract second; implementers should expect to assemble the full behaviour of any single endpoint from the workflow narratives in Section 3, the cross-cutting principles in Section 2, and the endpoint and error tables in Sections 4 and 5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `Provider`, `FrontDesk`, `BillingClerk`, and `PracticeAdmin`. If either header is missing, or `X-User-Role` does not name one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation per the authorization rules summarized in the endpoint table of Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide the practice's work along business lines. A `Provider` is a licensed chiropractor who owns all clinical authorship — creating and finalizing exams, proposing/activating/discontinuing/regressing treatment plans and adding phases, authoring and signing SOAP notes, and completing appointments. A `FrontDesk` operator owns the front-of-house scheduling flow — registering patients, checking patients in, cancelling and marking no-shows. A `BillingClerk` owns the money flow downstream of attendance — adjudicating insurance and writing off charges. A `PracticeAdmin` is the operational administrator who configures providers, rooms, fee schedules, and wellness plans, suspends providers, sets the practice clock, and can act alongside a `Provider` to discontinue a plan. Several operations are shared: booking an appointment and generating an appointment series may be done by either `Provider` or `FrontDesk`; posting a patient payment may be done by `FrontDesk` or `BillingClerk`; and adding an insurance policy may be done by `FrontDesk`, `BillingClerk`, or `PracticeAdmin`. Read access to the practice's resources is broadly available to all four roles unless the endpoint table narrows it.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider foreign key to `X-User-ID`. In particular, finalizing an exam requires that the exam's `provider_id` equal the acting provider's `X-User-ID`, and signing a SOAP note requires that the note's `provider_id` equal both the acting provider's `X-User-ID` and the appointment's `provider_id`. When `X-User-Role` is `FrontDesk`, `BillingClerk`, or `PracticeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with no upper bound.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every primary resource — `Provider`, `TreatmentRoom`, `FeeSchedule`, `WellnessPlan`, `Patient`, `InsurancePolicy`, `ExamRecord`, `TreatmentPlan`, `PlanPhase`, `AppointmentSeries`, `Appointment`, and `SoapNote` — carries a standard set of system-managed fields:

- **`id`**: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`**: an ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- **`updated_at`**: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource's properties.
- **`version`**: an integer that starts at the resource's creation value and increments by one with every mutation. It is the basis of the optimistic concurrency control described in Section 2.7.

Two entities are deliberate exceptions. A `LedgerEntry` and the `PracticeClock` are append-only or singleton records that are never mutated in place; each carries only `id` and `created_at`, and neither has an `updated_at` nor a `version` field. When a derived field such as a patient's `ledger_balance_cents` or a plan's `current_phase` changes as the byproduct of another action, the owning resource's `updated_at` is refreshed and its `version` is incremented exactly as it would be for a direct edit.

### 2.5. Hierarchical Consistency and Cascading Effects

The clinical hierarchy is strict: a `Patient` owns its `InsurancePolicy`, `ExamRecord`, `TreatmentPlan`, and `Appointment` records; a `TreatmentPlan` owns its `PlanPhase` and `AppointmentSeries` records; an `Appointment` owns its `SoapNote`. Many state transitions in Section 3 ripple outward across these boundaries, and every such ripple resolves inside the triggering request. When a plan is discontinued, every non-terminal phase under it is cancelled and every `SCHEDULED` series is cancelled, which in turn cancel-releases each still-`BOOKED` appointment the series generated and frees the insurance cap slots those appointments held. When a phase's last planned visit is completed, the phase completes and the next phase advances — or, if it was the final phase, the plan itself completes. When a patient accrues enough strikes to be dismissed, every `BOOKED` or `CHECKED_IN` appointment for that patient is cancel-released and any `ACTIVE` plan is discontinued. Each entity that the cascade touches has its own `updated_at` refreshed and its own `version` incremented as part of the same atomic operation.

### 2.6. Nested Resource Retrieval and Existence Ordering

Most clinical endpoints address a resource through a nested path that begins with a patient and descends to a leaf (for example, an appointment, exam, plan, phase, series, or SOAP note under a patient). The server validates path identifiers left to right. It first confirms the patient named by the leading path segment exists, rejecting with `ERR_PATIENT_NOT_FOUND` if it does not; only then does it look up the nested leaf resource, rejecting with `ERR_RESOURCE_NOT_FOUND` if the leaf (an appointment, exam, plan, phase, series, SOAP note, provider, or room named in the path) does not resolve. This ordering guarantees that a missing patient always surfaces before a missing child. Separately, any foreign key supplied in a request body — a referenced provider, room, fee schedule, policy, wellness plan, exam, or phase — that does not resolve to an existing resource is rejected with `ERR_REFERENCE_NOT_FOUND`.

### 2.7. Optimistic Concurrency on Plan Activation

Activating a treatment plan is the one operation guarded by optimistic concurrency control, because activation promotes the plan to the patient's single `ACTIVE` plan and legitimately supersedes any prior `PROPOSED` plan. The activation request must carry `expected_patient_version`, a non-optional field whose value is the `version` of the patient the client last observed. The server compares it to the patient's current `version`. If another writer has activated a plan in the meantime — bumping the patient's `version` since the client read it — the supplied `expected_patient_version` will no longer match the current value, and the activation is rejected as stale with `ERR_STALE_PATIENT_VERSION` (HTTP 412). This prevents a client from promoting a plan against a patient record it has not observed in its current form. No other endpoint takes a version field; activation is the only writer in the system that performs this check.

### 2.8. Monetary Values, Counts, and Rounding

All money in the system is represented as a whole number of cents in integer fields whose names end in `_cents`. Whenever a calculation multiplies cents by a fractional rate — a coinsurance fraction, a wellness overage discount, or a late-cancel multiplier — the product is rounded to a whole number of cents using the round-half-up method (a value exactly at the halfway point rounds up) before it is used or stored. Cap counts and visit counts are whole integers and are never rounded fractionally; they are incremented and decremented by one at a time as visits are reserved, committed, or released.

### 2.9. The Patient Ledger

Each patient carries a running `ledger_balance_cents` that represents the outstanding patient-owed balance: the sum of every patient-responsibility charge and no-show fee posted against the patient, less the patient payments and write-offs applied. The balance may go negative, representing a credit. The balance is backed by an append-only log of `LedgerEntry` records; each entry records its `patient_id`, an optional `appointment_id` (absent for standalone payments), an `entry_type`, a signed `amount_cents`, and an optional `memo`. An `entry_type` is one of `CHARGE`, `INSURANCE_PAYMENT`, `PATIENT_PAYMENT`, `NO_SHOW_FEE`, or `WRITE_OFF`. A `CHARGE` or `NO_SHOW_FEE` carries a positive `amount_cents` that increases the patient balance; an `INSURANCE_PAYMENT`, `PATIENT_PAYMENT`, or `WRITE_OFF` carries a negative `amount_cents` that decreases it. The ledger is the authoritative record from which `ledger_balance_cents` is derived, and every charge, payment, fee, adjudication, and write-off described in Section 3 appends exactly one ledger entry as it mutates the balance.

### 2.10. Scheduling Resources: Providers, Rooms, and Buffers

Appointments consume two shared resources at once: a provider and a treatment room. A `Provider` carries a `full_name`, an `npi` (the ten-digit National Provider Identifier), a `license_state` (the two-letter state of licensure), and a `status` of `ACTIVE` or `SUSPENDED`; a `SUSPENDED` provider may not be assigned to any new appointment. A `TreatmentRoom` carries a `name`, a `room_type` of `ADJUSTMENT` or `IMAGING`, a `turnover_buffer_minutes` value, and a `status` of `OPEN` or `CLOSED`; a `CLOSED` room rejects new bookings. The `turnover_buffer_minutes` is the mandatory number of idle minutes a room needs after one appointment ends before the next may start, and it defaults to 0 when omitted at creation. Provider conflict checks treat appointment intervals as half-open, so two appointments that merely touch end-to-end do not conflict; room conflict checks instead require a gap at least as large as the room's buffer, so adjacency alone is not enough when a buffer is configured. Section 3 details exactly how these two checks differ.

## 3. Business Logic & Workflows

### 3.1. Configuring the Practice

Before any patient can be scheduled, a `PracticeAdmin` stands up the practice's shared resources. Providers are created with their `full_name`, `npi`, and `license_state`; a newly created provider begins `ACTIVE` and can later be moved to `SUSPENDED`. Treatment rooms are created with a `name`, a `room_type`, and an optional `turnover_buffer_minutes`, beginning `OPEN`; a room may later be closed, after which new bookings and series against it are rejected with `ERR_RESOURCE_UNAVAILABLE` while any already-`BOOKED` appointments in it remain undisturbed.

Fee schedules drive every charge. A `FeeSchedule` is created for a particular `visit_type` — one of `ADJUSTMENT`, `EXAM`, `RE_EXAM`, `X_RAY`, or `THERAPY` — and carries a `cash_rate_cents` (the list/cash price for that visit type) and a `billed_amount_cents` (the amount submitted to insurance for that visit type). At most one fee schedule per `visit_type` may be `ACTIVE` at a time: creating a new fee schedule for a `visit_type` retires any prior `ACTIVE` schedule for the same `visit_type`, moving it to `RETIRED` while the new one becomes `ACTIVE`. Wellness memberships are configured as a `WellnessPlan` with a `name`, a `monthly_fee_cents` recurring membership fee, an `included_adjustments_per_month` count of adjustments fully covered each calendar month, and an `overage_discount_pct` — a fraction between 0.0 and 1.0 inclusive applied to the cash rate for adjustments beyond the included count. Wellness plans are immutable configuration in this version and remain `ACTIVE` with no retire transition.

The practice runs on a deterministic clock. A `PracticeClock` exposes a single `current_utc` instant that the system consults for every late-cancel-window and benefit-year calculation. A `PracticeAdmin` may set this clock to a supplied `current_utc` for test-driving, and any role may read it.

### 3.2. Registering Patients and Their Coverage

A `FrontDesk` operator (or a `PracticeAdmin`) registers a patient with a `full_name`, a `date_of_birth` given as an ISO 8601 date, and a `payer_mode` selecting which billing algorithm will apply to that patient's visits. The `payer_mode` is one of `INSURANCE`, `CASH`, or `WELLNESS` and defaults to `CASH`. A wellness patient must also supply a `wellness_plan_id` naming the membership they hold; a cash or insurance patient must not supply one. This coherence is enforced at registration: a `WELLNESS` registration without a `wellness_plan_id`, or a `CASH`/`INSURANCE` registration that carries one, is rejected with `ERR_PAYER_MODE_MISMATCH`. A newly registered patient starts `ACTIVE` with a `no_show_strike_count` of 0, a `ledger_balance_cents` of 0, and `is_dismissed` false.

Insurance coverage is recorded as an `InsurancePolicy` attached to the patient. Adding a policy captures the `carrier_name`, the `annual_visit_cap` (the maximum chiropractic visits the carrier will cover this benefit year), a `deductible_total_cents` (the annual deductible), a `coinsurance_pct` (the patient's coinsurance fraction, between 0.0 and 1.0 inclusive, applied to the allowed amount after the deductible), and an `allowed_amount_cents` (the carrier-allowed contracted rate per covered visit). A new policy begins `ACTIVE` with its counters zeroed: `visits_reserved` and `visits_committed` both 0, and `deductible_met_cents` 0. A `BillingClerk` or `PracticeAdmin` may terminate a policy, moving it to `TERMINATED`; a terminated policy covers no new visits, though slots it has already reserved or committed are left untouched. The `patient_id` linking a policy to its patient is set by the server from the path.

The `no_show_strike_count`, `ledger_balance_cents`, and `is_dismissed` flags on a patient are computed, never client-supplied. A patient is dismissed automatically the moment the strike count reaches the dismissal threshold of five strikes (see Section 3.7), at which point `is_dismissed` becomes true and the patient's `status` moves to the terminal `DISMISSED`. A `DISMISSED` patient may no longer be the subject of a booking, series generation, exam, or plan operation; such attempts are rejected with `ERR_PATIENT_DISMISSED`.

### 3.3. The Clinical Intake: Exams and Treatment Plans

Clinical care begins with an exam. A `Provider` creates an `ExamRecord` against a patient by supplying the authoring `provider_id`, an `exam_type` of `INITIAL` or `RE_EXAM`, an optional `imaging_ordered` flag indicating whether X-ray imaging was ordered (defaulting to false), a `severity_score` from 1 to 10 inclusive that seeds the recommended phase frequency, and optional free-text `findings`. The exam's `patient_id` is set from the path. An exam begins in `DRAFT` and only the authoring provider may finalize it: finalization requires the exam still be `DRAFT` and that its `provider_id` equal the acting provider's `X-User-ID`, and on success the exam transitions `DRAFT → FINALIZED`. Only a `FINALIZED` exam may justify a treatment plan.

A `Provider` then proposes a `TreatmentPlan` by naming the `exam_record_id` of the finalized exam that justifies it; the plan's `patient_id` comes from the path. A new plan is `PROPOSED` with its `current_phase` defaulting to `ACUTE`, its `total_planned_visits` and `visits_delivered` both 0. The plan's `total_planned_visits` is maintained as the sum of `planned_visit_count` across all of its non-`CANCELLED` phases, and `visits_delivered` counts the appointments under the plan whose attendance reached `ATTENDED`. The provider builds out the plan by adding one or more phases. Each `PlanPhase` is created with a `phase_type` of `ACUTE`, `CORRECTIVE`, or `MAINTENANCE`, a `sequence_index` (a zero-based ordinal position; phases advance in ascending order and the index must be unique within a plan), a `visits_per_week` frequency from 1 to 7 inclusive, and a `planned_visit_count` of at least 1 total adjustments planned for the phase. A phase begins `PENDING` with `visits_completed` 0, and adding a phase recomputes the plan's `total_planned_visits`. Its `treatment_plan_id` is set from the path.

Activation is the gate between planning and execution. Activating a plan requires that the plan still be `PROPOSED`, that its referenced exam be `FINALIZED`, that the plan have at least one phase, and that the patient have no other plan already `ACTIVE`. If the referenced exam is not finalized, or activation is attempted with zero phases, the request is rejected with `ERR_PLAN_NOT_READY`; if the patient already holds an `ACTIVE` plan, it is rejected with `ERR_ACTIVE_PLAN_EXISTS`. The request must also carry `expected_patient_version` matching the patient's current `version` per Section 2.7, failing with `ERR_STALE_PATIENT_VERSION` otherwise. On success the plan transitions `PROPOSED → ACTIVE`; the phase with the lowest `sequence_index` transitions `PENDING → IN_PROGRESS` and the plan's `current_phase` is set to that phase's `phase_type`; and the patient's `version` is incremented by one. A `Provider` (or, jointly, a `PracticeAdmin`) may discontinue an `ACTIVE` plan, moving it `ACTIVE → DISCONTINUED`; this cascades to cancel every non-terminal phase and every `SCHEDULED` series under the plan, releasing the cap slots of the appointments those series generated as described in Section 2.5.

### 3.4. Phase Progression and the Re-Exam Regression Cycle

Phases progress as visits are delivered. A phase that is `IN_PROGRESS` completes automatically the moment its `visits_completed` reaches its `planned_visit_count`, transitioning `IN_PROGRESS → COMPLETED`. When a phase completes, the system advances forward: if a higher-`sequence_index` phase is still `PENDING`, the next such phase transitions `PENDING → IN_PROGRESS` and becomes the plan's `current_phase`; a phase may only advance to `IN_PROGRESS` once no sibling phase of lower `sequence_index` remains `PENDING` or `IN_PROGRESS`. If instead the completed phase was the highest-`sequence_index` phase and it was a `MAINTENANCE` phase, the completion bubbles up to move the plan `ACTIVE → COMPLETED`.

The plan's phases form a cycle rather than a straight line, because a re-exam can send corrective care back to an acute footing. A `Provider` may regress a plan by referencing a re-exam `exam_record_id` and the `plan_phase_id` of the corrective phase to roll back. Regression is only allowed when that phase has `phase_type` `CORRECTIVE` and is currently `IN_PROGRESS`, and when the referenced re-exam is a `FINALIZED` `RE_EXAM` whose `severity_score` is at least the regression severity threshold of 6; any other combination is rejected with `ERR_REGRESSION_NOT_ALLOWED`. On a valid regression the corrective phase transitions `IN_PROGRESS → PENDING`, and the lowest-`sequence_index` `ACUTE` phase that had already `COMPLETED` is moved back to `IN_PROGRESS` with its `visits_completed` reset to 0; the plan's `current_phase` returns to `ACUTE`. As part of the same operation, the `SCHEDULED` appointment series for the regressed phases is set to `REGENERATED` and a fresh series is generated at the acute frequency, which re-reserves cap slots for the new appointments. This is the cyclic shape `CORRECTIVE → PENDING` paired with `COMPLETED → IN_PROGRESS` on the acute phase, distinct from the ordinary linear forward advance.

### 3.5. Materializing Appointment Series and Booking Visits

Once a phase is in flight, its prescribed frequency is materialized into concrete appointments through an appointment series. A `FrontDesk` or `Provider` operator creates an `AppointmentSeries` against a plan by supplying the `plan_phase_id` of the phase whose frequency the series realizes, a default `provider_id` and `treatment_room_id` for the generated appointments, a `start_date` (the ISO 8601 date of the first appointment), a `weekday_pattern` (an array of weekday integers, 0 for Monday through 6 for Sunday, on which visits recur each week), a `start_time_minutes` (minutes after midnight used as the start time of every generated appointment, from 0 up to but not including 1440), and a `duration_minutes` length from 1 to 240 inclusive applied to every generated appointment. For insurance patients the series may also carry an `insurance_policy_id`. The series' `treatment_plan_id` is set from the path, and `generated_count` records how many appointments it materialized.

Generation produces exactly `planned_visit_count` appointments for the named phase. The system walks forward from `start_date`: within each calendar week, beginning with the week that contains `start_date`, it visits the weekdays in `weekday_pattern` in ascending order, skips any date earlier than `start_date`, and emits one appointment for each remaining matching date, advancing to the next week and repeating until exactly `planned_visit_count` appointments have been emitted. Each generated appointment's start instant combines its date with `start_time_minutes` in UTC, and its end instant is that start plus `duration_minutes`. Every generated appointment is checked for schedule conflicts against existing `BOOKED` appointments on the same provider and the same room (Section 3.6), and for insurance patients each booking reserves a cap slot. The series begins `SCHEDULED` and on a successful materialization `generated_count` equals the phase's `planned_visit_count`; a series later superseded by a re-plan is moved to `REGENERATED` and one cancelled with its plan is moved to `CANCELLED`, both of which cancel-release each still-`BOOKED` appointment they generated and free its cap slots. Series materialization imposes no state-machine legality precondition on the named phase or its plan: the request is accepted whatever the phase's status (`PENDING`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`) and whatever the plan's status, so the fixed-order `ERR_INVALID_STATE` step of Section 3.6 has no condition to fire against on this endpoint, and generation proceeds directly to the dismissed-patient guard and the scheduling and cap business rules. In particular, generating a series against a cancelled or otherwise non-active phase is not rejected with `ERR_INVALID_STATE` ahead of the cap check; any `ERR_VISIT_CAP_EXCEEDED` arising from the projected reservations is the failure that surfaces.

Single appointments may also be booked directly. Booking an `Appointment` supplies a `provider_id`, a `treatment_room_id`, a `visit_type`, a `scheduled_start` (the ISO 8601 UTC start instant), and a `duration_minutes`; the server computes `scheduled_end` as the start plus `duration_minutes`. A booking may optionally carry a `plan_phase_id` (the phase the visit counts toward; absent for unplanned visits), an `insurance_policy_id` (the policy a cap slot is reserved against, for insurance patients only), an `appointment_series_id` (linking a generated visit back to its series; absent for ad-hoc single appointments), and a `replaces_appointment_id` (set when this booking is a reschedule replacement for a cancelled appointment). A new appointment begins with `attendance_status` `BOOKED` and `billing_status` `UNBILLED`; its `patient_id` comes from the path, and its computed money and counter fields — `counts_against_cap`, `patient_responsibility_cents`, `insurance_paid_cents`, and `no_show_fee_cents` — start at 0/false and are filled in by later transitions.

### 3.6. Scheduling Safety: Availability, Room Type, Conflicts, and Caps

Every booking and every generated series appointment passes a battery of scheduling checks, and these checks are evaluated in a fixed order so that the most fundamental problems surface first. The order is: header authentication, then role authorization, then existence of the patient and any nested path resource, then existence of every body foreign key, then well-formedness and enum-domain validity of the body, then state-machine legality of the requested transition, then — for activation only — the optimistic-concurrency version check, then the patient-not-dismissed guard, then the business constraints below. Concretely, an authentication failure (`ERR_UNAUTHENTICATED`) precedes an authorization failure (`ERR_FORBIDDEN_ROLE`), which precedes a missing-patient (`ERR_PATIENT_NOT_FOUND`) or missing-leaf (`ERR_RESOURCE_NOT_FOUND`) failure, which precedes a missing-body-reference (`ERR_REFERENCE_NOT_FOUND`) failure, which precedes a malformed-body (`ERR_INVALID_REQUEST`) failure, which precedes an illegal-state (`ERR_INVALID_STATE`) failure, which precedes the stale-version (`ERR_STALE_PATIENT_VERSION`) check, which precedes the dismissed-patient (`ERR_PATIENT_DISMISSED`) guard, which precedes the booking-specific business rules.

Among the booking-specific business rules, the assigned provider must be `ACTIVE` (not `SUSPENDED`) and the assigned room must be `OPEN` (not `CLOSED`), failing with `ERR_RESOURCE_UNAVAILABLE`. An `X_RAY` visit must be booked into a room whose `room_type` is `IMAGING`, failing with `ERR_ROOM_TYPE_MISMATCH`. The provider must not be double-booked: the new appointment's half-open interval from its start up to (but not including) its end must not intersect any `BOOKED` or `CHECKED_IN` appointment for the same provider — two appointments that merely abut, where one ends exactly when the next begins, do not conflict — and a true overlap is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`. The room must respect its turnover buffer: the new appointment's start must be at or after the prior room appointment's end plus that room's `turnover_buffer_minutes`, so that a non-zero buffer makes mere adjacency insufficient; a start earlier than that is rejected with `ERR_ROOM_BUFFER_CONFLICT`. For an insurance patient, the booking must name an `insurance_policy_id` belonging to that patient and `ACTIVE`, failing with `ERR_POLICY_REQUIRED`.

The insurance visit cap is the practice's allocation pool. Only the visit types `ADJUSTMENT`, `THERAPY`, and `RE_EXAM` count against the cap; `EXAM` and `X_RAY` visits never consume a cap slot. When an insurance patient books a cap-counting visit, the system projects the policy's usage as its current `visits_reserved` plus `visits_committed` plus the one new booking. If that projection is greater than the policy's `annual_visit_cap`, the booking is rejected with `ERR_VISIT_CAP_EXCEEDED`; a projection exactly equal to the cap is allowed, filling the final slot. On a successful cap-counting booking the policy's `visits_reserved` is incremented by one and the appointment's `counts_against_cap` is set true; for non-cap-counting visits and for cash or wellness patients no slot is reserved and `counts_against_cap` stays false. When a series is materialized for an insurance patient, the cap check runs for each generated booking, and if the batch would push usage past the cap at any point during generation the entire series is rejected atomically with `ERR_VISIT_CAP_EXCEEDED` and no partial series is created. Cash and wellness patients reserve no cap and are subject only to the schedule-conflict checks.

### 3.7. The Visit Day: Check-In, Documentation, Completion, Cancellation, and No-Shows

On the day of care, a `FrontDesk` operator checks the patient in. Check-in requires the appointment be `BOOKED`, the patient be `ACTIVE`, and the assigned provider be `ACTIVE`, and on success the appointment transitions `BOOKED → CHECKED_IN`. The attending `Provider` documents the visit with a SOAP note before it can be completed. A `SoapNote` is created against the appointment with the authoring `provider_id` and the four clinical sections `subjective`, `objective`, `assessment`, and `plan`; its `appointment_id` is set from the path and there is at most one note per appointment. The note's author must match the appointment's provider, so a `provider_id` that differs from the appointment's `provider_id` is rejected with `ERR_SOAP_PROVIDER_MISMATCH`. A note begins `DRAFT`; signing it requires the note be `DRAFT`, that its `provider_id` equal both the acting provider's `X-User-ID` and the appointment's `provider_id`, and that the appointment be `CHECKED_IN` (the note is signed before completion). Signing transitions the note `DRAFT → SIGNED`, after which it is immutable, and a signed note is the prerequisite that unblocks completion.

Completion is where attendance and money converge. Completing an appointment requires it be `CHECKED_IN` and that a `SIGNED` SOAP note exist for it; a completion attempted without a signed note is rejected with `ERR_SOAP_NOTE_REQUIRED`. On completion the appointment transitions `CHECKED_IN → ATTENDED`. If the appointment counted against the cap, its slot moves from reserved to committed — the policy's `visits_reserved` is decremented by one and its `visits_committed` is incremented by one. If the appointment carries a `plan_phase_id`, that phase's `visits_completed` is incremented by one and the plan's `visits_delivered` is incremented by one. The system then computes the patient's responsibility (Section 3.8), setting `patient_responsibility_cents` and `insurance_paid_cents`; moves `billing_status` `UNBILLED → POSTED`; appends a `CHARGE` ledger entry whose `amount_cents` equals the positive `patient_responsibility_cents`; and adds that amount to the patient's `ledger_balance_cents`. Finally, if completing this visit makes the phase's `visits_completed` equal its `planned_visit_count`, the phase-completion bubble-up of Section 3.4 runs.

Appointments that fall through have their own outcomes, all driven by a `FrontDesk` operator and all consulting the practice clock's `current_utc`. A clean cancellation — moving a `BOOKED` appointment to `CANCELLED` — is permitted only when the current time is strictly earlier than the appointment's `scheduled_start` minus the late-cancel window of 24 hours; it releases any reserved cap slot (decrementing `visits_reserved` by one) and assesses no fee, leaving `no_show_fee_cents` at 0. If the cancellation instead falls within the late window — at or after `scheduled_start` minus 24 hours but still before `scheduled_start` — the appointment moves `BOOKED → LATE_CANCEL`: the cap slot is released, the patient's `no_show_strike_count` is incremented by one, a no-show fee is computed (Section 3.8) and recorded in `no_show_fee_cents`, a `NO_SHOW_FEE` ledger entry is appended and added to `ledger_balance_cents`, and `billing_status` moves to `POSTED`. A no-show — applied when the slot has elapsed — moves a `BOOKED` appointment to `NO_SHOW` when the current time is at or after `scheduled_start`, or a `CHECKED_IN` appointment to `NO_SHOW` when the current time is at or after its `scheduled_end` (checked in but never completed); in both cases the cap slot is released, the strike count is incremented by one, a no-show fee is computed and recorded, a `NO_SHOW_FEE` ledger entry is appended and added to the balance, and `billing_status` moves to `POSTED`.

Strikes accumulate across both no-shows and late cancellations in `no_show_strike_count`, and when that count reaches the dismissal threshold of five, the patient is dismissed: `is_dismissed` becomes true and `status` moves to the terminal `DISMISSED`. Dismissal cascades — every remaining `BOOKED` or `CHECKED_IN` appointment for the patient is cancel-released, freeing its cap slots, and any `ACTIVE` treatment plan is discontinued. A request that targets a transition the appointment's current state does not allow is rejected with `ERR_INVALID_STATE`.

### 3.8. Billing the Visit: Patient Responsibility, No-Show Fees, Adjudication, and Write-Offs

The amount a patient owes for a completed visit is computed at completion from the `ACTIVE` fee schedule for the appointment's `visit_type` and the patient's `payer_mode`, and the three payer modes use three different algorithms.

For a **cash** patient, the patient responsibility is simply the fee schedule's `cash_rate_cents` and `insurance_paid_cents` is 0.

For a **wellness** patient, non-adjustment visits are billed at the `cash_rate_cents` with `insurance_paid_cents` 0, exactly as cash. Adjustments are governed by the membership's monthly inclusion. The system counts this patient's `ATTENDED` `ADJUSTMENT` appointments that fall in the same calendar month as this visit (by `scheduled_start`, in UTC), including this one, ordered by `scheduled_start` ascending and breaking ties by `created_at` ascending; this visit's one-based position in that ordering is its ordinal. If the ordinal is less than or equal to the wellness plan's `included_adjustments_per_month`, the visit is fully included and the patient responsibility is 0. Otherwise it is an overage: the discount is the `cash_rate_cents` multiplied by the plan's `overage_discount_pct`, rounded half up to whole cents, and the patient responsibility is the `cash_rate_cents` minus that discount. In all wellness cases `insurance_paid_cents` is 0.

For an **insurance** patient, the calculation works from the policy's `allowed_amount_cents`. The remaining deductible is the policy's `deductible_total_cents` minus its `deductible_met_cents`, floored at 0 so it is never negative. The amount applied to the deductible is the smaller of the allowed amount and that remaining deductible, and the patient pays this portion dollar-for-dollar. The amount after the deductible is the allowed amount minus the amount applied to the deductible; the coinsurance is that after-deductible amount multiplied by the policy's `coinsurance_pct`, rounded half up to whole cents. The patient responsibility is the sum of the amount applied to the deductible and the coinsurance, and `insurance_paid_cents` is the allowed amount minus the patient responsibility. The increase to the policy's `deductible_met_cents` by the amount applied to the deductible is not made at completion; it is applied later at adjudication.

The **no-show fee** is tiered by the patient's strike count after the current strike has been recorded. With a strike count of 1 or 2 the base fee is 2500 cents; with 3 or 4 it is 5000 cents; with 5 or more it is 7500 cents. A `NO_SHOW` is charged the full base fee. A `LATE_CANCEL` is charged the base fee multiplied by the late-cancel multiplier of 0.5, rounded half up to whole cents. The resulting amount is stored in `no_show_fee_cents`.

Downstream of attendance, a `BillingClerk` reconciles insurance and bad debt; the billing dimension evolves independently of attendance. Adjudication requires the appointment be `POSTED`, be `ATTENDED`, belong to an `INSURANCE` patient, and carry an `insurance_policy_id`. On success the `billing_status` moves `POSTED → ADJUDICATED`; an `INSURANCE_PAYMENT` ledger entry is appended whose `amount_cents` is the negative of `insurance_paid_cents`; and the policy's `deductible_met_cents` is increased by the amount that was applied to the deductible for this visit. The attendance dimension is untouched, so an `ATTENDED`/`POSTED` appointment becomes `ATTENDED`/`ADJUDICATED`. A write-off requires only that the appointment be `POSTED`; it moves `billing_status` `POSTED → WRITTEN_OFF`, appends a `WRITE_OFF` ledger entry whose `amount_cents` is the negative of `patient_responsibility_cents`, and subtracts that amount from the patient's `ledger_balance_cents`, reversing the original charge so the patient's net balance returns to where it stood before that visit's charge was posted.

Patient payments close the loop. A `FrontDesk` or `BillingClerk` operator posts a payment of a positive `amount_cents` against a patient; a non-positive amount is rejected with `ERR_VALIDATION`. The payment appends a `PATIENT_PAYMENT` ledger entry carrying the negative of `amount_cents` and decrements the patient's `ledger_balance_cents` by `amount_cents`. Other semantic body validations are enforced in the same field-validation tier and likewise surface as `ERR_VALIDATION`: a series `weekday_pattern` must be non-empty with every entry in the range 0 through 6, a phase `sequence_index` must be unique within its plan, and an exam `severity_score` must lie between 1 and 10 inclusive.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that read a resource or drive a state transition on an existing resource return a `200 OK` status code. List endpoints accept the pagination query parameters `limit` and `offset` of Section 2.3 in addition to the filters noted in their descriptions. Where a description mentions filters, each named filter is an optional query parameter on that endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/providers` | Create a provider | PracticeAdmin |
| GET | `/providers` | List providers (optional `status` filter) | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| GET | `/providers/{providerId}` | Get a provider | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| POST | `/providers/{providerId}/suspend` | Suspend a provider | PracticeAdmin |
| POST | `/treatment-rooms` | Create a treatment room | PracticeAdmin |
| GET | `/treatment-rooms` | List treatment rooms (optional `status`, `room_type` filters) | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| GET | `/treatment-rooms/{roomId}` | Get a treatment room | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| POST | `/treatment-rooms/{roomId}/close` | Close a treatment room | PracticeAdmin |
| POST | `/fee-schedules` | Create a fee schedule (retires the prior active one for the visit type) | PracticeAdmin |
| GET | `/fee-schedules` | List fee schedules (optional `visit_type`, `status` filters) | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| POST | `/wellness-plans` | Create a wellness plan | PracticeAdmin |
| GET | `/wellness-plans` | List wellness plans (optional `status` filter) | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| POST | `/_clock/set` | Set the deterministic practice clock | PracticeAdmin |
| GET | `/_clock` | Read the deterministic practice clock | PracticeAdmin, FrontDesk, Provider, BillingClerk |
| POST | `/patients` | Register a patient | FrontDesk, PracticeAdmin |
| GET | `/patients` | List patients (optional `status`, `payer_mode`, `wellness_plan_id` filters) | FrontDesk, PracticeAdmin, Provider, BillingClerk |
| GET | `/patients/{patientId}` | Get a patient | FrontDesk, PracticeAdmin, Provider, BillingClerk |
| POST | `/patients/{patientId}/payments` | Post a patient payment | FrontDesk, BillingClerk |
| GET | `/patients/{patientId}/ledger-entries` | List a patient's ledger entries (optional `entry_type`, `appointment_id` filters) | FrontDesk, PracticeAdmin, BillingClerk |
| POST | `/patients/{patientId}/insurance-policies` | Add an insurance policy to a patient | FrontDesk, BillingClerk, PracticeAdmin |
| GET | `/patients/{patientId}/insurance-policies` | List a patient's insurance policies (optional `status` filter) | FrontDesk, BillingClerk, PracticeAdmin, Provider |
| POST | `/patients/{patientId}/insurance-policies/{policyId}/terminate` | Terminate an insurance policy | BillingClerk, PracticeAdmin |
| POST | `/patients/{patientId}/exams` | Create an exam record | Provider |
| GET | `/patients/{patientId}/exams` | List a patient's exams (optional `status`, `exam_type` filters) | Provider, FrontDesk, PracticeAdmin |
| POST | `/patients/{patientId}/exams/{examId}/finalize` | Finalize a draft exam | Provider |
| POST | `/patients/{patientId}/treatment-plans` | Propose a treatment plan | Provider |
| GET | `/patients/{patientId}/treatment-plans` | List a patient's treatment plans (optional `status` filter) | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/patients/{patientId}/treatment-plans/{planId}` | Get a treatment plan | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| POST | `/patients/{patientId}/treatment-plans/{planId}/phases` | Add a plan phase | Provider |
| GET | `/patients/{patientId}/treatment-plans/{planId}/phases` | List plan phases (optional `status` filter) | Provider, FrontDesk, PracticeAdmin |
| POST | `/patients/{patientId}/treatment-plans/{planId}/activate` | Activate a proposed plan | Provider |
| POST | `/patients/{patientId}/treatment-plans/{planId}/discontinue` | Discontinue an active plan | Provider, PracticeAdmin |
| POST | `/patients/{patientId}/treatment-plans/{planId}/re-exam-regress` | Regress a corrective phase after a re-exam | Provider |
| POST | `/patients/{patientId}/treatment-plans/{planId}/series` | Materialize a phase's recurring appointment series | FrontDesk, Provider |
| GET | `/patients/{patientId}/treatment-plans/{planId}/series` | List appointment series under a plan (optional `plan_phase_id`, `status` filters) | FrontDesk, Provider, PracticeAdmin |
| POST | `/patients/{patientId}/appointments` | Book a single appointment | FrontDesk, Provider |
| GET | `/patients/{patientId}/appointments` | List a patient's appointments (optional `attendance_status`, `billing_status`, `appointment_series_id`, `plan_phase_id`, `insurance_policy_id`, `provider_id` filters) | FrontDesk, Provider, PracticeAdmin, BillingClerk |
| GET | `/patients/{patientId}/appointments/{apptId}` | Get an appointment | FrontDesk, Provider, PracticeAdmin, BillingClerk |
| POST | `/patients/{patientId}/appointments/{apptId}/check-in` | Check a patient in | FrontDesk |
| POST | `/patients/{patientId}/appointments/{apptId}/soap-note` | Create a draft SOAP note | Provider |
| GET | `/patients/{patientId}/appointments/{apptId}/soap-note` | List the appointment's SOAP note (optional `status` filter) | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| POST | `/patients/{patientId}/appointments/{apptId}/soap-note/sign` | Sign the draft SOAP note | Provider |
| POST | `/patients/{patientId}/appointments/{apptId}/complete` | Complete (attend) an appointment | Provider |
| POST | `/patients/{patientId}/appointments/{apptId}/cancel` | Cancel a booked appointment | FrontDesk |
| POST | `/patients/{patientId}/appointments/{apptId}/no-show` | Mark an appointment a no-show | FrontDesk |
| POST | `/patients/{patientId}/appointments/{apptId}/adjudicate` | Adjudicate insurance for a posted, attended appointment | BillingClerk |
| POST | `/patients/{patientId}/appointments/{apptId}/write-off` | Write off a posted appointment's charge | BillingClerk |
| GET | `/appointments` | Cross-aggregate appointment search (filters `patient_id`, `provider_id`, `treatment_room_id`, `insurance_policy_id`, `appointment_series_id`, `plan_phase_id`, `replaces_appointment_id`, `attendance_status`, `billing_status`) | FrontDesk, Provider, PracticeAdmin, BillingClerk |
| GET | `/appointments/{apptId}` | Get an appointment by id | FrontDesk, Provider, PracticeAdmin, BillingClerk |
| GET | `/appointment-series` | Cross-aggregate series search (filters `treatment_plan_id`, `plan_phase_id`, `provider_id`, `treatment_room_id`, `status`) | FrontDesk, Provider, PracticeAdmin |
| GET | `/appointment-series/{seriesId}` | Get an appointment series by id | FrontDesk, Provider, PracticeAdmin |
| GET | `/plan-phases` | Cross-aggregate phase search (filters `treatment_plan_id`, `status`) | Provider, FrontDesk, PracticeAdmin |
| GET | `/plan-phases/{phaseId}` | Get a plan phase by id | Provider, FrontDesk, PracticeAdmin |
| GET | `/treatment-plans` | Cross-aggregate plan search (filters `patient_id`, `exam_record_id`, `status`) | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/treatment-plans/{planId}` | Get a treatment plan by id | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/exams` | Cross-aggregate exam search (filters `patient_id`, `provider_id`, `status`, `exam_type`) | Provider, FrontDesk, PracticeAdmin |
| GET | `/exams/{examId}` | Get an exam by id | Provider, FrontDesk, PracticeAdmin |
| GET | `/insurance-policies` | Cross-aggregate policy search (filters `patient_id`, `status`) | FrontDesk, BillingClerk, PracticeAdmin, Provider |
| GET | `/insurance-policies/{policyId}` | Get an insurance policy by id | FrontDesk, BillingClerk, PracticeAdmin, Provider |
| GET | `/soap-notes` | Cross-aggregate SOAP note search (filters `appointment_id`, `provider_id`, `status`) | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/soap-notes/{noteId}` | Get a SOAP note by id | Provider, FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/ledger-entries` | Cross-aggregate ledger search (filters `patient_id`, `appointment_id`, `entry_type`) | FrontDesk, PracticeAdmin, BillingClerk |
| GET | `/ledger-entries/{entryId}` | Get a ledger entry by id | FrontDesk, PracticeAdmin, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PATIENT_VERSION` | 412 Precondition Failed |
| `ERR_PATIENT_DISMISSED` | 409 Conflict |
| `ERR_PAYER_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RESOURCE_UNAVAILABLE` | 409 Conflict |
| `ERR_ROOM_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_ROOM_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_POLICY_REQUIRED` | 422 Unprocessable Entity |
| `ERR_VISIT_CAP_EXCEEDED` | 409 Conflict |
| `ERR_SOAP_NOTE_REQUIRED` | 409 Conflict |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 Conflict |
| `ERR_PLAN_NOT_READY` | 409 Conflict |
| `ERR_SOAP_PROVIDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REGRESSION_NOT_ALLOWED` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
