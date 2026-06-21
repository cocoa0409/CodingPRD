# Adult Day Health & PACE Program API — Product Requirements Document

## 1. Introduction

The Program of All-Inclusive Care for the Elderly (PACE) blends day-health services with full clinical and financial responsibility for a frail, nursing-home-eligible population. A single center must simultaneously screen applicants for nursing-facility level of care, author an interdisciplinary care plan, enroll members on a strict first-of-month cadence, run a daily attendance floor with transportation and on-site nursing, and reconcile a capitated Medicaid/Medicare payment stream — all while honoring a segregation-of-duties model in which the staff who enroll members are deliberately barred from certifying their clinical eligibility or finalizing their bills.

This document specifies a REST API that governs that entire arc. The system is, at heart, two things layered together: a compliance-audit engine that gates every clinically or fiscally consequential action behind certifications, level-of-care validity windows, census limits, and roster caps; and a ledger-reconciliation engine that derives each participant's billed and reconciled totals from their child capitation rows and attendance history, keeping those derived fields consistent through finalizations, voids, and the cascading teardown of a disenrollment. The requirements below describe the contracts, the cross-cutting principles, and the per-workflow business logic that an implementer must reproduce exactly.

Because PACE billing is capitated and enrollment is locked in for a window after it becomes effective, the system also carries real money-movement consequences for timing: a voluntary departure inside the lock-in window assesses a penalty, a partial month may be prorated by calendar day, and a stale view of a participant's billing state must never be allowed to overwrite a fresher one. These concerns surface throughout the specification and are not optional.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across the entire API. Domain-specific workflows are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly five roles, spelled precisely as follows: `ProgramAdmin`, `IntakeCoordinator`, `MedicalDirector`, `NurseStaff`, and `BillingSpecialist`. These roles are deliberately disjoint — the model is one of segregation of duties. An `IntakeCoordinator` enrolls members but may neither certify their level of care nor finalize their billing; a `MedicalDirector` holds clinical authority but cannot enroll or bill; a `BillingSpecialist` owns the money but cannot enroll, certify, or approve a disenrollment. When a request carries a recognized role that is nonetheless not permitted to perform the requested operation under the matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All five roles use an opaque identity model. When `X-User-Role` is `ProgramAdmin`, `IntakeCoordinator`, `MedicalDirector`, `NurseStaff`, or `BillingSpecialist`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`, and ownership of a resource is never determined by matching `X-User-ID` against a stored foreign key. Authorization is governed entirely by the role, not by the identity of the individual operator.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. This constraint is applied by clamping rather than rejection: a supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, and the clamped value is what appears in `meta.limit`. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0, and a negative `offset` is likewise clamped up to 0. A `limit` or `offset` that is present but not a valid integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by the `created_at` timestamp in ascending order. Every list-style response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and System-Managed Fields

Most resources in this system carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 when the resource is created and increments by one on every mutation; it underpins the optimistic concurrency control described below.

One entity is an exception. A `MedicationAdministration` is an append-only event record: once written it is never modified. It therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field. Every other entity (Program, Participant, Enrollment, LevelOfCareAssessment, CarePlan, CarePlanGoal, AttendanceDay, TransportLeg, MedicationOrder, CapitationPayment, and DisenrollmentRequest) carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Resource Existence, Nested References, and Request Validation

Resources in this domain are addressed as peers under the `/pace` mount; a participant, its care plans, its attendance days, and its capitation rows are each reachable by their own identifier, and parent context travels as a foreign-key field inside the request body rather than as a deeper path segment. Whenever an operation references resources — both the identifier in the path and any foreign-key references in the body — the server validates them left to right. The path identifier is checked first; if it names no existing resource, the request fails with `ERR_NOT_FOUND` (HTTP 404) before any body reference is examined. Body foreign keys are then validated in turn, each producing the same `ERR_NOT_FOUND` if it dangles.

After existence, the system checks that the request body is well-formed: all required fields present, each value of the correct type, every enum value drawn from its legal set, and every integer within its declared range. A malformed, mistyped, illegal-enum, or out-of-range body is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

These two checks sit near the top of a fixed validation precedence that governs every endpoint. Authentication (`ERR_UNAUTHENTICATED`, 401) is evaluated first, then role authorization (`ERR_UNAUTHORIZED`, 403), then resource existence (`ERR_NOT_FOUND`, 404), then request well-formedness (`ERR_INVALID_REQUEST`, 400), then — for state-driven operations — whether the target resource is in a legal state for the transition (`ERR_INVALID_STATE`, HTTP 409). Only after all of these pass does the system evaluate the domain-specific business rules described in Section 3. This ordering is significant: an authentication failure must surface before a permission failure, a missing resource before a malformed body, and a bad state before any business-safety or fiscal check, so that a single request never masks an earlier-priority fault behind a later one.

### 2.6. State Propagation, Cascades, and Derived Fields

Many operations in this system mutate more than one entity. When the server changes a resource as a side effect of an operation on another — closing an enrollment when a disenrollment finalizes, superseding a care plan when a successor activates, cancelling a day's transport legs when the day is cancelled — each affected resource independently has its `updated_at` refreshed and, where it carries one, its `version` incremented. These cascades are not optional bookkeeping; they are part of the operation's contract and are detailed per-workflow in Section 3.

Certain Participant fields are **derived** and must always be reconcilable from the participant's child rows rather than set independently. The `ledger_billed_cents` field equals the sum of `total_billed_cents` over the participant's `CapitationPayment` rows that are in `FINALIZED` status. The `ledger_reconciled_cents` field equals the sum of `reconciled_cents` over the participant's `CapitationPayment` rows that are in `RECONCILED` status. The `lifetime_attendance_days` field equals the count of the participant's `AttendanceDay` rows in `COMPLETED` status. Likewise, the Program's `enrolled_count` equals the number of that program's participants whose `status` is `ENROLLED`. Whenever a child event changes one of these aggregates — a capitation finalize, void, or reconcile; an attendance completion; an enrollment or disenrollment — the corresponding derived field is updated so that it never drifts from the true total. In particular, voiding a previously `FINALIZED` capitation payment removes it from the `FINALIZED` set, so `ledger_billed_cents` returns to exactly its pre-finalize value.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are integers denominated in whole cents — `medicaid_share_cents`, `medicare_share_cents`, `supplement_cents`, `total_billed_cents`, `reconciled_cents`, `recoup_cents`, `lock_in_penalty_cents`, the program rate fields, and the derived ledger totals. Wherever a calculation produces a fractional cent — chiefly when a proration factor or a lock-in fraction multiplies a monthly rate — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly at the halfway point rounds up, away from zero). Where a calculation specifies that several components are rounded independently and then summed, the rounding is applied to each component first and the rounded components are added afterward; the sum is not re-rounded. Counts such as `covered_days`, `completed_days`, `enrolled_count`, and `lifetime_attendance_days` are exact integers.

### 2.8. Optimistic Concurrency Control on Participant Billing

Two billing-critical operations are guarded by optimistic concurrency control keyed on the Participant's `version`, because both read the participant's ledger or enrollment state, act on it, and write it back — and a stale snapshot would corrupt the ledger.

The first is finalizing a capitation payment. That request must carry `expected_participant_version`, a non-optional field whose value is the `version` of the target participant as the client last observed it. If `expected_participant_version` does not match the participant's current `version` at the moment of finalize — for example because a finalize for another month, or an enroll/disenroll cascade, has already advanced the participant since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no shares are computed and no ledger is debited.

The second is finalizing a disenrollment. That request likewise must carry `expected_participant_version` matching the participant's current `version`. If a capitation finalize (or any other mutation) has advanced the participant's `version` since the client read it, the disenrollment finalize is rejected with `ERR_STALE_VERSION` (HTTP 412), so that the cascade never runs against a participant snapshot that no longer reflects the latest billed state. Both of these rules are expressed purely in terms of stale-versus-current version comparison; they are not about requests overlapping in time. Endpoints other than these two capitation-finalize and disenrollment-finalize operations do not take a version field and perform no OCC check.

### 2.9. Time, the Logical Clock, and Date Gating

Several rules in this system are time-gated against a logical "current" instant rather than wall-clock time: whether a level-of-care assessment has expired, whether a participant is old enough to enroll, and whether a voluntary disenrollment falls inside the lock-in window. The server maintains a settable current UTC instant for this purpose. An administrative test-driving capability pins that instant to a supplied value (carried in the request body as `to_iso8601`) and returns the new value as `current_utc`; all subsequent time-gated logic reads from this pinned clock.

## 3. Business Logic & Workflows

### 3.1. Establishing the Program

A PACE center is represented by a **Program**, created by a `ProgramAdmin`. Creation requires a `name` and a two-letter `state_code` (the state of operation, which drives the Medicaid rate), together with two capacity figures and the monthly rates. The `state_code` is validated only as a required non-empty string; its two-letter form is a documentation convention and the server enforces no length or character-set restriction on it, so a value that is not exactly two letters is still accepted. The `daily_census_capacity` is the maximum number of participants who may be physically present — that is, `CHECKED_IN` — on any single attendance day, and must be at least 1. The `max_roster` is a separate ceiling: the maximum number of participants the program may carry in `ENROLLED` status at once, also at least 1, and independent of the daily live-census cap. Two rate fields, `medicaid_monthly_rate_cents` and `medicare_monthly_rate_cents`, give the state Medicaid and the Medicare Part C+D capitation per member-month in cents, each at least 0.

Three further inputs are optional at creation. The `medicare_only_supplement_cents` is the extra monthly amount a Medicare-only participant self-pays on top of the Medicaid share, defaulting to 0 and at least 0. The `lock_in_days` is the number of days after an enrollment becomes effective during which a finalized voluntary disenrollment incurs the lock-in penalty; it defaults to 30 and is at least 0. The `loc_validity_days` is the number of days a certified level-of-care assessment remains valid before recertification is required, defaulting to 365. On creation the program's `status` is `OPEN`, its `enrolled_count` is 0, and its `version` is 1.

A program's `status` is either `OPEN` or `SUSPENDED`. A `ProgramAdmin` may move an `OPEN` program to `SUSPENDED` and may return a `SUSPENDED` program to `OPEN`. While a program is `SUSPENDED`, two operations are blocked and rejected with `ERR_PROGRAM_SUSPENDED`: enrolling a participant, and finalizing a capitation payment. All other reads and clinical operations remain available during suspension.

### 3.2. Applicants, Level-of-Care Certification, and Eligibility

A participant begins life as an **applicant**. An `IntakeCoordinator` creates a `Participant` by supplying the `program_id` it belongs to, the participant's `full_name`, their `date_of_birth`, and the `dual_eligible` flag — `true` for a member dually eligible for both Medicaid and Medicare, `false` for a Medicare-only member who self-pays the Medicaid share as a supplement. A new participant starts in `APPLICANT` status with all ledger fields (`ledger_billed_cents`, `ledger_reconciled_cents`, `lifetime_attendance_days`) at 0 and `version` 1. Its `enrollment_effective_date`, `active_loc_assessment_id`, `active_care_plan_id`, and `active_enrollment_id` are all null until the corresponding milestones are reached. The full status progression is `APPLICANT → ELIGIBLE → ENROLLED → DISENROLLMENT_PENDING → DISENROLLED`, with `DISENROLLED` terminal.

Clinical eligibility is established through a **level-of-care assessment**. Either a `MedicalDirector` or an `IntakeCoordinator` may create a `LevelOfCareAssessment`, supplying the `participant_id`, the clinical `nf_score` (a nursing-facility eligibility score from 0 to 100), the date it was performed as `assessed_on`, and optionally an `nf_threshold` (the minimum score that certifies nursing-home level of care, defaulting to 60). A new assessment is `PENDING`. Its status set is `PENDING | CERTIFIED | DENIED | EXPIRED | SUPERSEDED`, with `DENIED`, `EXPIRED`, and `SUPERSEDED` terminal.

Certification is a clinical act reserved to the `MedicalDirector` alone — an `IntakeCoordinator` may author an assessment but may never certify it. To move a `PENDING` assessment to `CERTIFIED`, the assessment must be `PENDING` (otherwise `ERR_INVALID_STATE`) and its `nf_score` must be at least its `nf_threshold` (otherwise `ERR_LOC_BELOW_THRESHOLD`). On certification the system sets `expires_on` to `assessed_on` advanced by the program's `loc_validity_days`; if a prior `CERTIFIED` assessment already exists for that participant, that prior assessment transitions to `SUPERSEDED`; the participant's `active_loc_assessment_id` is pointed at the newly certified assessment; and if the participant was still in `APPLICANT` status, the participant bubbles up to `ELIGIBLE`. Because pointing `active_loc_assessment_id` at the newly certified assessment is itself a mutation of the participant, the participant's `version` increments on every successful certification — both the initial certification that bubbles an `APPLICANT` up to `ELIGIBLE` and any later recertification of an already-`ELIGIBLE` or `ENROLLED` participant. A `MedicalDirector` may instead deny a `PENDING` assessment, moving it to `DENIED` with no change to the participant.

A certified assessment does not stay valid forever. When the current clock date is past `expires_on`, a `CERTIFIED` assessment is treated as `EXPIRED` for the purposes of any gate that requires certification, so long as no newer `CERTIFIED` assessment exists; this expiry is evaluated at enroll time and at capitation-finalize time. Separately, whenever a newer assessment for the same participant becomes `CERTIFIED`, the older one is `SUPERSEDED`.

### 3.3. Authoring the Interdisciplinary Care Plan

Enrollment cannot proceed without an active care plan, and a care plan is the product of an interdisciplinary review cycle. An `IntakeCoordinator` creates a `CarePlan` by supplying the `participant_id`; optionally a `supersedes_care_plan_id` naming the prior active plan this draft is intended to replace on activation (null for a participant's first plan); and optionally `required_disciplines`, the set of discipline codes whose signatures are mandatory before the plan may be activated, defaulting to `["RN", "SW", "MEDICAL_DIRECTOR"]` and drawn from the value set `{RN, SW, PT, DIETICIAN, MEDICAL_DIRECTOR}`. A new plan is `DRAFT`, its `idt_disciplines_signed` set is empty, and its `goal_count` is 0. The care-plan status set is `DRAFT | IN_REVIEW | ACTIVE | REVISION | SUPERSEDED | VOID`, with `SUPERSEDED` and `VOID` terminal.

A plan is fleshed out with **goals**. An `IntakeCoordinator` or a `MedicalDirector` adds a `CarePlanGoal` under a plan, supplying the owning `discipline` (one of `RN | SW | PT | DIETICIAN | MEDICAL_DIRECTOR`), a `description` narrative, and optionally `target_attendance_days` (the attendance days targeted for the goal, defaulting to 0 and at least 0). Each new goal is `OPEN`; its lifecycle status set is `OPEN | MET | DISCONTINUED`. Adding a goal increments the plan's `goal_count`.

Signatures accumulate on the plan through a discipline-signing action available to a `MedicalDirector`, `NurseStaff`, or `IntakeCoordinator`: the supplied `discipline` is added to `idt_disciplines_signed` as an idempotent set insertion, so signing the same discipline twice leaves the set unchanged.

The plan then moves through a review loop. An `IntakeCoordinator` submits a `DRAFT` plan for review, advancing it to `IN_REVIEW`; submission requires at least one goal (`goal_count` of 1 or more), failing which it is rejected with `ERR_CARE_PLAN_NO_GOALS`, and the plan must be in `DRAFT` to submit from draft (otherwise `ERR_INVALID_STATE`). A `MedicalDirector` reviewing an `IN_REVIEW` plan may send it back by requesting a revision, which moves it to `REVISION` and clears `idt_disciplines_signed` to empty (a revision invalidates every prior signature). From `REVISION` the `IntakeCoordinator` resubmits through the same `/submit` action, returning the plan to `IN_REVIEW`; this resubmission likewise requires `goal_count` of at least 1 (`ERR_CARE_PLAN_NO_GOALS`) and that the plan be in `REVISION` (`ERR_INVALID_STATE`). The single `/submit` endpoint thus serves both transitions: it accepts a plan whose status is either `DRAFT` or `REVISION` and advances it to `IN_REVIEW`, rejecting any other status with `ERR_INVALID_STATE`. This `IN_REVIEW → REVISION → IN_REVIEW` cycle may repeat any number of times.

Activation is the `MedicalDirector`'s act. An `IN_REVIEW` plan transitions to `ACTIVE` only when every discipline listed in `required_disciplines` is present in `idt_disciplines_signed` — set membership is what matters, so extra signatures beyond the required set are permitted and never block activation, but a missing required signature rejects the activation with `ERR_IDT_INCOMPLETE`; the plan must be `IN_REVIEW` to activate (otherwise `ERR_INVALID_STATE`). Activation supersedes the predecessor in one step: if the participant already had a different active plan, that prior plan transitions to `SUPERSEDED`, and that prior plan's medication orders in `ORDERED`, `ACTIVE`, or `HELD` status are all cascaded to `DISCONTINUED`. The participant's `active_care_plan_id` is then pointed at the newly activated plan and the participant's `version` increments.

An `ACTIVE` plan may itself be sent back for revision by the `MedicalDirector`, moving it to `REVISION` while it remains the participant's active plan throughout, and clearing `idt_disciplines_signed` to empty. An `IntakeCoordinator` may void a plan that is in `DRAFT`, `IN_REVIEW`, or `REVISION` (otherwise `ERR_INVALID_STATE`), but never one that is currently the participant's active plan — an attempt to void the participant's active care plan is rejected with `ERR_CANNOT_VOID_ACTIVE`. The active-plan check takes precedence over the state check: when the target plan is the participant's active care plan, the rejection is `ERR_CANNOT_VOID_ACTIVE` even though that plan's status is not one of `DRAFT`, `IN_REVIEW`, or `REVISION` (so this `ERR_CANNOT_VOID_ACTIVE` case is evaluated before the `ERR_INVALID_STATE` state check).

### 3.4. Enrollment

Enrolling a participant is the `IntakeCoordinator`'s act and is the gate at which the most safety and capacity rules converge. The request supplies a single field, `enrollment_effective_date`, the first-of-month date on which membership begins. Enrollment drives the participant from `ELIGIBLE` to `ENROLLED`, and every one of the following preconditions must hold, each with its own rejection. These same-class business checks are evaluated in a fixed order so that exactly one rejection surfaces: first the `ELIGIBLE` state check, then the program-`OPEN` check, then the certified-level-of-care check, then the active-care-plan check, then the age check, then the first-of-month check, and finally the roster-capacity check.

- The participant must be in `ELIGIBLE` status (otherwise `ERR_INVALID_STATE`).
- The participant must have a non-null `active_loc_assessment_id` pointing at an assessment that is `CERTIFIED` and not past its `expires_on` as of the current clock date (otherwise `ERR_LOC_NOT_CERTIFIED`).
- The participant must have a non-null `active_care_plan_id` — an `ACTIVE` care plan must exist (otherwise `ERR_NO_ACTIVE_CARE_PLAN`).
- The program must be `OPEN`, not `SUSPENDED` (otherwise `ERR_PROGRAM_SUSPENDED`).
- The program's `enrolled_count` must be below its `max_roster` (otherwise `ERR_CAPACITY_EXCEEDED`).
- The participant must be at least 55 years old as of `enrollment_effective_date`, computed against the participant's `date_of_birth` (otherwise `ERR_AGE_INELIGIBLE`).
- The `enrollment_effective_date` must be the first of its month — its day-of-month must equal 01 (otherwise `ERR_NOT_FIRST_OF_MONTH`).

On a successful enroll the system creates an `Enrollment` in `OPEN` status carrying the `participant_id` and the `enrollment_effective_date`, and computes its `lock_in_end_date` as the `enrollment_effective_date` advanced by the program's `lock_in_days`. The participant's `active_enrollment_id` is set to the new enrollment, the participant's own `enrollment_effective_date` is set to the effective date, the program's `enrolled_count` increases by 1, and the participant's `version` increments. An enrollment's status is `OPEN` or `CLOSED`; its `disenrollment_effective_date` stays null while `OPEN` and is set when disenrollment finalizes.

### 3.5. The Daily Attendance Floor and Transportation

Day-to-day operations revolve around the **attendance day**. An `IntakeCoordinator` or `NurseStaff` schedules an `AttendanceDay` for a participant, supplying the `participant_id`, the `service_date`, and optionally `meals_provided` (meals served that day, defaulting to 1 and constrained to the range 0 through 3), `activities_count` (therapeutic activities joined, defaulting to 0), and `transport_required` (whether program transportation is scheduled, defaulting to true). The day's `service_date` must be unique per participant; a second day on the same date for the same participant is rejected with `ERR_DUPLICATE_PERIOD`. A new day is `SCHEDULED` with `transport_leg_count` of 0; its status set is `SCHEDULED | CHECKED_IN | COMPLETED | NO_SHOW | CANCELLED`, with `COMPLETED`, `NO_SHOW`, and `CANCELLED` terminal.

Checking a participant in for the day is a `NurseStaff` action that moves the day from `SCHEDULED` to `CHECKED_IN`. Three conditions gate it: the day must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`); the participant must be `ENROLLED` (otherwise `ERR_PARTICIPANT_NOT_ENROLLED`); and the live census must have room. Live census is the count of that program's attendance days that are currently `CHECKED_IN` and share the same `service_date` as the day being checked in. If that count is already at or above the program's `daily_census_capacity`, the check-in is rejected with `ERR_CENSUS_FULL` — at exactly capacity the next check-in is refused, while at one below capacity it is admitted. Days that have already reached `COMPLETED` do not count toward live census, since the participant has departed for the day.

A `CHECKED_IN` day is closed out by `NurseStaff` completing it, moving it to `COMPLETED` and incrementing the participant's `lifetime_attendance_days` by 1. Alternatively, `NurseStaff` may mark a `SCHEDULED` day as a `NO_SHOW`, or `NurseStaff` or an `IntakeCoordinator` may cancel a day that is `SCHEDULED` or `CHECKED_IN`, moving it to `CANCELLED` (a cancel attempt on a day in any other state is rejected with `ERR_INVALID_STATE`). Whenever a day moves to `NO_SHOW` or `CANCELLED`, every `PLANNED` transport leg under that day is cascaded to `CANCELLED`.

**Transportation** is modeled as legs under a day. An `IntakeCoordinator` or `NurseStaff` adds a `TransportLeg` by supplying the `attendance_day_id`, the `direction` (`PICKUP` or `DROPOFF`), the pickup/drop-off window as `window_start_min` and `window_end_min` (each expressed as minutes from midnight), and the `vehicle_id` identifying the logical vehicle. Adding a leg increments the day's `transport_leg_count`. A leg is created `PLANNED`; its status is `PLANNED` or `CANCELLED`. The window must be valid: `window_start_min` falls in the range 0 through 1439, `window_end_min` is strictly greater than `window_start_min` and at most 1440 — an end not strictly after the start, or a window outside the 0-to-1440 bounds, is rejected with `ERR_INVALID_WINDOW`. Furthermore, a new leg may not overlap any existing `PLANNED` leg assigned to the same `vehicle_id` on the same `service_date`; intervals are treated as half-open, so a leg that merely touches another at an endpoint (one ending exactly when the next begins) does not overlap, but any genuine overlap is rejected with `ERR_TRANSPORT_OVERLAP`.

### 3.6. Nursing and Medication Services

Medication management is anchored to an active care plan. A `MedicalDirector` or `NurseStaff` creates a `MedicationOrder` against a plan by supplying the `participant_id`, the `care_plan_id` the order belongs to, the `drug_name`, and the `daily_doses` scheduled per attendance day (at least 1). A new order is `ORDERED` with `administered_count` 0; its status set is `ORDERED | ACTIVE | HELD | DISCONTINUED`, with `DISCONTINUED` terminal.

`NurseStaff` runs the order lifecycle. Activating an `ORDERED` order moves it to `ACTIVE`, but only if the order's `care_plan_id` references a plan that is currently `ACTIVE` — otherwise the activation is rejected with `ERR_CARE_PLAN_NOT_ACTIVE` (and an order not in `ORDERED` is rejected with `ERR_INVALID_STATE`). An `ACTIVE` order may be put on `HELD`, and a `HELD` order may be resumed back to `ACTIVE` — resuming likewise requires the referenced care plan to be `ACTIVE`, failing with `ERR_CARE_PLAN_NOT_ACTIVE` if it is not. An order in `ORDERED`, `ACTIVE`, or `HELD` may be discontinued (by `NurseStaff` or a `MedicalDirector`), moving it to `DISCONTINUED`.

Each dose event is captured as a `MedicationAdministration`, recorded by `NurseStaff` by supplying the `medication_order_id`, the `attendance_day_id` on which the dose was given, the `outcome` (`GIVEN`, `REFUSED`, or `HELD`), and the `administered_at` timestamp. The referenced day must be in `CHECKED_IN` or `COMPLETED` status; an administration whose day is in any other state is rejected with `ERR_CARE_PLAN_NOT_ACTIVE`. When the recorded `outcome` is `GIVEN`, the order's `administered_count` increases by 1; other outcomes leave the count unchanged. As noted in Section 2.4, a `MedicationAdministration` is an append-only record carrying only `id` and `created_at`.

### 3.7. Capitated Billing and Reconciliation

PACE pays per member-month, and the **capitation payment** is the unit of billing. A `BillingSpecialist` creates a `CapitationPayment` in `DRAFT` by supplying the `participant_id`, the `service_month` (a first-of-month date identifying the billed month, with day-of-month 01), and optionally the `proration_mode` (`FULL_MONTH` or `DAILY`, defaulting to `FULL_MONTH`). The `service_month` is unique per participant; a duplicate month for the same participant is rejected with `ERR_DUPLICATE_PERIOD`. The payment's status set is `DRAFT | FINALIZED | RECONCILED | VOID`, with `RECONCILED` and `VOID` terminal. The component fields `medicaid_share_cents`, `medicare_share_cents`, `supplement_cents`, `total_billed_cents`, and `covered_days` are computed at finalize time, not at creation.

**Finalizing** is the `BillingSpecialist`'s act and carries the most gating. Beyond the OCC requirement on `expected_participant_version` described in Section 2.8, finalize requires: the payment is in `DRAFT` (otherwise `ERR_INVALID_STATE`); the program is `OPEN` (otherwise `ERR_PROGRAM_SUSPENDED`); the participant had an enrollment covering at least one calendar day of the `service_month` (otherwise `ERR_NO_COVERAGE_FOR_MONTH`); and the participant's `active_loc_assessment_id` is `CERTIFIED` with the first day of the `service_month` falling on or before its `expires_on` (otherwise `ERR_LOC_NOT_CERTIFIED`). These checks are evaluated in that listed order — `DRAFT` state, then program-`OPEN`, then coverage, then certified level of care — and the OCC `expected_participant_version` comparison (`ERR_STALE_VERSION`) is evaluated last, only after all four of those checks pass.

The amount owed is computed as follows. Let the number of calendar days in the `service_month` be its natural length (28, 29, 30, or 31). The `covered_days` is the count of calendar days `d` within the `service_month` for which the participant's enrollment window covers `d` — that is, the enrollment's effective date is on or before `d`, and either no disenrollment effective date is set or `d` is strictly before it. The disenrollment effective date itself is therefore not a covered day; the covered window is the half-open interval running from the effective date up to but excluding the disenrollment date. The evaluation then proceeds in a fixed order: first compute `covered_days`; second select three bases; third apply a single proration factor to each base; fourth round each of the three results independently to whole cents using round-half-up; fifth sum the three rounded components.

The proration factor depends on `proration_mode`. Under `FULL_MONTH` the factor is exactly 1 — the whole member-month is billed regardless of how many days were covered (though at least one covered day is still required to finalize). Under `DAILY` the factor is `covered_days` divided by the number of calendar days in the month, applied to each base before its independent rounding.

The three bases depend on the participant's `dual_eligible` flag. The Medicare base is always the program's `medicare_monthly_rate_cents`. For a dual-eligible participant, the Medicaid base is the program's `medicaid_monthly_rate_cents` and the supplement base is 0. For a non-dual (Medicare-only) participant, the Medicaid base is 0 and the supplement base is the sum of the program's `medicaid_monthly_rate_cents` and its `medicare_only_supplement_cents` — the Medicare-only member self-pays the Medicaid share, plus the configured supplement, as the `supplement_cents` line. Each share is the product of its base and the factor, rounded half-up to whole cents: `medicare_share_cents` from the Medicare base, `medicaid_share_cents` from the Medicaid base, and `supplement_cents` from the supplement base. The `total_billed_cents` is the sum of those three rounded components. On finalize the payment moves to `FINALIZED`, `total_billed_cents` is added to the participant's `ledger_billed_cents`, and the participant's `version` increments.

**Reconciliation** confirms the money. A `BillingSpecialist` reconciles a `FINALIZED` payment, optionally supplying `recoup_cents` (an amount clawed back, for example on a retroactive disenrollment, defaulting to 0 and at least 0). The `recoup_cents` may not exceed `total_billed_cents`; a recoup larger than what was billed is rejected with `ERR_RECOUP_EXCEEDS_BILLED`, and a payment not in `FINALIZED` is rejected with `ERR_INVALID_STATE`. On reconcile the `reconciled_cents` is set to `total_billed_cents` minus `recoup_cents`, the payment moves to `RECONCILED`, and that `reconciled_cents` is added to the participant's `ledger_reconciled_cents`.

**Voiding** unwinds a payment. A `BillingSpecialist` may void a payment that is in `DRAFT` or `FINALIZED` (otherwise `ERR_INVALID_STATE`), moving it to `VOID`. If the payment being voided was `FINALIZED`, its `total_billed_cents` is subtracted back out of the participant's `ledger_billed_cents` as a compensating entry, so the ledger returns exactly to its pre-finalize value with no drift; voiding a `DRAFT` payment that was never finalized touches no ledger.

A separate computed read serves the **ancillary meal and activity charge** for a participant over a service month. This read sums a per-day charge across only those `AttendanceDay` rows that are `COMPLETED` and whose `service_date` falls in the queried month, supplied as a `service_month` query parameter (a date in the target month; only its year and month are used to match days, and a request that omits `service_month` is rejected with `ERR_INVALID_REQUEST`); days that are `SCHEDULED`, `CHECKED_IN`, `NO_SHOW`, or `CANCELLED` are excluded. Each included day contributes a meal charge equal to its `meals_provided` multiplied by 850 cents, plus a flat activity bonus of 200 cents when that day's `activities_count` is greater than zero (and no bonus when it is zero). The activity bonus is a single flat amount per qualifying day — it is not multiplied by the number of activities. The read returns the queried `service_month`, the count of `completed_days` included, and the summed `month_ancillary_cents`.

### 3.8. Disenrollment and the Cascade

A member leaves the program through a **disenrollment request**, which may be voluntary or involuntary and which moves through a controlled fork before it takes effect. An `IntakeCoordinator`, `MedicalDirector`, or `ProgramAdmin` submits a `DisenrollmentRequest` by supplying the `participant_id`, the `kind` (`VOLUNTARY` for a participant-requested departure or `INVOLUNTARY` for a program-initiated for-cause one), the `reason_code` (one of `MOVED | DISSATISFIED | DECEASED | LOSS_OF_ELIGIBILITY | NONPAYMENT | DISRUPTIVE | FRAUD`), and the `requested_effective_date`. The request's status set is `SUBMITTED | APPROVED | FINALIZED | DENIED | WITHDRAWN`, with `FINALIZED`, `DENIED`, and `WITHDRAWN` terminal. Unlike an enrollment effective date, the `requested_effective_date` may be any calendar date, including mid-month, since a death or move rarely falls on the first; daily proration consumes it directly.

From `SUBMITTED` the request forks. A `MedicalDirector` may **approve** it, which requires the request be `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and the participant be `ENROLLED` (otherwise `ERR_PARTICIPANT_NOT_ENROLLED`); approval moves the request to `APPROVED`, drives the participant from `ENROLLED` to `DISENROLLMENT_PENDING`, and increments the participant's `version`. Because the participant leaves `ENROLLED` at approval, the program's derived `enrolled_count` (per Section 2.6, the count of that program's `ENROLLED` participants) is updated here and decreases by 1 — the drop occurs at approval, not at finalize. Alternatively the `MedicalDirector` may **deny** it, but only a `VOLUNTARY` request may be denied — an `INVOLUNTARY` for-cause request cannot be denied and the attempt is rejected with `ERR_INVOLUNTARY_CANNOT_DENY` (and a non-`SUBMITTED` request with `ERR_INVALID_STATE`); a successful deny moves the request to `DENIED` with no participant change.

Once `APPROVED`, the path again forks. An `IntakeCoordinator` may **withdraw** a request, but only a `VOLUNTARY` one — an `INVOLUNTARY` request cannot be withdrawn and the attempt is rejected with `ERR_WITHDRAW_NOT_ALLOWED` (and a request not in `APPROVED` with `ERR_INVALID_STATE`); withdrawal moves the request to `WITHDRAWN` and returns the participant from `DISENROLLMENT_PENDING` back to `ENROLLED`, incrementing the participant's `version`. Because the participant re-enters `ENROLLED`, the program's derived `enrolled_count` is updated here and increases by 1 again, restoring it to its pre-approval value.

**Finalizing** the disenrollment is the `BillingSpecialist`'s act and triggers the full teardown. Beyond the OCC requirement on `expected_participant_version` from Section 2.8, finalize requires the request be `APPROVED` (otherwise `ERR_INVALID_STATE`) and the participant be in `DISENROLLMENT_PENDING` (otherwise `ERR_PARTICIPANT_NOT_ENROLLED`). These checks are evaluated in that order — request-`APPROVED` first, then participant-`DISENROLLMENT_PENDING` — and the OCC `expected_participant_version` comparison (`ERR_STALE_VERSION`) is evaluated last, only after both of those checks pass. On finalize the participant moves from `DISENROLLMENT_PENDING` to `DISENROLLED` and the following cascade runs atomically:

- The participant's open `Enrollment` moves to `CLOSED` and its `disenrollment_effective_date` is set to the request's `requested_effective_date`.
- The participant's `ACTIVE` care plan is torn down: for any non-death reason the plan moves to `SUPERSEDED`, but when the `reason_code` is `DECEASED` it moves to `VOID` instead. In either case that plan's medication orders in `ORDERED`, `ACTIVE`, or `HELD` status are all cascaded to `DISCONTINUED`.
- Every `AttendanceDay` for the participant that is still `SCHEDULED` or `CHECKED_IN` moves to `CANCELLED`, and each such day's `PLANNED` transport legs are cascaded to `CANCELLED`.
- The participant's `active_enrollment_id` and `active_care_plan_id` are cleared to null. The program's derived `enrolled_count` is reconciled per Section 2.6 to the count of `ENROLLED` participants; because the participant already left `ENROLLED` at approval (moving to `DISENROLLMENT_PENDING`), the count was already decremented there and finalize leaves it unchanged rather than decrementing it a second time.
- The request moves to `FINALIZED` and the participant's `version` increments.

Finally, the **lock-in penalty** is assessed during finalize. The penalty applies only to a `VOLUNTARY` request whose effective date falls inside the lock-in window. Let the finalize date be the request's `requested_effective_date` and the window end be the enrollment's `lock_in_end_date` (its effective date advanced by the program's `lock_in_days`). If the `kind` is not `VOLUNTARY`, the `lock_in_penalty_cents` is 0. If the finalize date is on or after the `lock_in_end_date`, the penalty is 0 — landing exactly on the end date incurs no penalty. Otherwise the request is inside the window, and the penalty is one Medicare member-month prorated by the unserved fraction of the window: the number of whole calendar days remaining (the `lock_in_end_date` minus the finalize date) is multiplied by the program's `medicare_monthly_rate_cents`, divided by the program's `lock_in_days`, and rounded half-up to whole cents, yielding `lock_in_penalty_cents`. A finalize one day before the end date therefore produces a strictly positive penalty.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, every lifecycle action, and the suspend/reopen and clock controls — return `200 OK`. Read operations return `200 OK`. The complete request and response semantics for each operation are described in the Section 3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pace/programs` | Create a PACE program/center | ProgramAdmin |
| GET | `/pace/programs/{program_id}` | Get a program | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/programs/{program_id}/suspend` | Suspend a program | ProgramAdmin |
| POST | `/pace/programs/{program_id}/reopen` | Reopen a suspended program | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Pin the server's current UTC instant | ProgramAdmin |
| POST | `/pace/participants` | Create a participant (applicant) | IntakeCoordinator |
| GET | `/pace/participants/{participant_id}` | Get a participant | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/participants` | List participants | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/participants/{participant_id}/enroll` | Enroll an eligible participant | IntakeCoordinator |
| GET | `/pace/participants/{participant_id}/attendance-summary` | Computed ancillary meal/activity charge over a month | ProgramAdmin, BillingSpecialist, IntakeCoordinator |
| GET | `/pace/enrollments/{enrollment_id}` | Get an enrollment | ProgramAdmin, IntakeCoordinator, BillingSpecialist |
| GET | `/pace/enrollments` | List enrollments | ProgramAdmin, IntakeCoordinator, BillingSpecialist |
| POST | `/pace/loc-assessments` | Create a level-of-care assessment | MedicalDirector, IntakeCoordinator |
| GET | `/pace/loc-assessments/{assessment_id}` | Get a level-of-care assessment | ProgramAdmin, IntakeCoordinator, MedicalDirector, BillingSpecialist |
| GET | `/pace/loc-assessments` | List level-of-care assessments | ProgramAdmin, IntakeCoordinator, MedicalDirector, BillingSpecialist |
| POST | `/pace/loc-assessments/{assessment_id}/certify` | Certify nursing-home level of care | MedicalDirector |
| POST | `/pace/loc-assessments/{assessment_id}/deny` | Deny a level-of-care assessment | MedicalDirector |
| POST | `/pace/care-plans` | Create a care plan draft | IntakeCoordinator |
| GET | `/pace/care-plans/{care_plan_id}` | Get a care plan | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/care-plans` | List care plans | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/care-plans/{care_plan_id}/goals` | Add a goal to a care plan | IntakeCoordinator, MedicalDirector |
| GET | `/pace/care-plan-goals/{goal_id}` | Get a care plan goal | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/care-plan-goals` | List care plan goals | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/care-plans/{care_plan_id}/sign` | Record an IDT discipline signature | MedicalDirector, NurseStaff, IntakeCoordinator |
| POST | `/pace/care-plans/{care_plan_id}/submit` | Submit a care plan for IDT review | IntakeCoordinator |
| POST | `/pace/care-plans/{care_plan_id}/request-revision` | Send a care plan back for revision | MedicalDirector |
| POST | `/pace/care-plans/{care_plan_id}/activate` | Activate a reviewed care plan | MedicalDirector |
| POST | `/pace/care-plans/{care_plan_id}/void` | Void a non-active draft/review care plan | IntakeCoordinator |
| POST | `/pace/attendance-days` | Schedule an attendance day | IntakeCoordinator, NurseStaff |
| GET | `/pace/attendance-days/{day_id}` | Get an attendance day | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/attendance-days` | List attendance days | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/attendance-days/{day_id}/check-in` | Check a participant in for the day | NurseStaff |
| POST | `/pace/attendance-days/{day_id}/complete` | Complete a checked-in day | NurseStaff |
| POST | `/pace/attendance-days/{day_id}/no-show` | Mark a scheduled day as no-show | NurseStaff |
| POST | `/pace/attendance-days/{day_id}/cancel` | Cancel a scheduled or checked-in day | NurseStaff, IntakeCoordinator |
| POST | `/pace/transport-legs` | Add a transport leg to an attendance day | IntakeCoordinator, NurseStaff |
| GET | `/pace/transport-legs/{leg_id}` | Get a transport leg | ProgramAdmin, IntakeCoordinator, NurseStaff, BillingSpecialist |
| GET | `/pace/transport-legs` | List transport legs | ProgramAdmin, IntakeCoordinator, NurseStaff, BillingSpecialist |
| POST | `/pace/medication-orders` | Create a medication order against a care plan | MedicalDirector, NurseStaff |
| GET | `/pace/medication-orders/{order_id}` | Get a medication order | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/medication-orders` | List medication orders | ProgramAdmin, IntakeCoordinator, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/medication-orders/{order_id}/activate` | Activate a medication order | NurseStaff |
| POST | `/pace/medication-orders/{order_id}/hold` | Hold an active medication order | NurseStaff |
| POST | `/pace/medication-orders/{order_id}/resume` | Resume a held medication order | NurseStaff |
| POST | `/pace/medication-orders/{order_id}/discontinue` | Discontinue a medication order | NurseStaff, MedicalDirector |
| POST | `/pace/medication-administrations` | Record a medication administration event | NurseStaff |
| GET | `/pace/medication-administrations/{administration_id}` | Get a medication administration event | ProgramAdmin, MedicalDirector, NurseStaff, BillingSpecialist |
| GET | `/pace/medication-administrations` | List medication administration events | ProgramAdmin, MedicalDirector, NurseStaff, BillingSpecialist |
| POST | `/pace/capitation-payments` | Create a draft capitation payment | BillingSpecialist |
| GET | `/pace/capitation-payments/{payment_id}` | Get a capitation payment | ProgramAdmin, BillingSpecialist, IntakeCoordinator |
| GET | `/pace/capitation-payments` | List capitation payments | ProgramAdmin, BillingSpecialist, IntakeCoordinator |
| POST | `/pace/capitation-payments/{payment_id}/finalize` | Finalize a draft capitation payment | BillingSpecialist |
| POST | `/pace/capitation-payments/{payment_id}/reconcile` | Reconcile a finalized payment | BillingSpecialist |
| POST | `/pace/capitation-payments/{payment_id}/void` | Void a draft or finalized payment | BillingSpecialist |
| POST | `/pace/disenrollment-requests` | Submit a disenrollment request | IntakeCoordinator, MedicalDirector, ProgramAdmin |
| GET | `/pace/disenrollment-requests/{request_id}` | Get a disenrollment request | ProgramAdmin, IntakeCoordinator, MedicalDirector, BillingSpecialist |
| GET | `/pace/disenrollment-requests` | List disenrollment requests | ProgramAdmin, IntakeCoordinator, MedicalDirector, BillingSpecialist |
| POST | `/pace/disenrollment-requests/{request_id}/approve` | Approve a disenrollment request | MedicalDirector |
| POST | `/pace/disenrollment-requests/{request_id}/deny` | Deny a voluntary disenrollment request | MedicalDirector |
| POST | `/pace/disenrollment-requests/{request_id}/finalize` | Finalize disenrollment with full cascade | BillingSpecialist |
| POST | `/pace/disenrollment-requests/{request_id}/withdraw` | Withdraw a voluntary disenrollment request | IntakeCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROGRAM_SUSPENDED` | 409 |
| `ERR_PARTICIPANT_NOT_ENROLLED` | 409 |
| `ERR_LOC_NOT_CERTIFIED` | 409 |
| `ERR_LOC_BELOW_THRESHOLD` | 409 |
| `ERR_NO_ACTIVE_CARE_PLAN` | 409 |
| `ERR_IDT_INCOMPLETE` | 409 |
| `ERR_CARE_PLAN_NO_GOALS` | 409 |
| `ERR_CARE_PLAN_NOT_ACTIVE` | 409 |
| `ERR_CANNOT_VOID_ACTIVE` | 409 |
| `ERR_WITHDRAW_NOT_ALLOWED` | 409 |
| `ERR_INVOLUNTARY_CANNOT_DENY` | 409 |
| `ERR_NOT_FIRST_OF_MONTH` | 422 |
| `ERR_AGE_INELIGIBLE` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_TRANSPORT_OVERLAP` | 409 |
| `ERR_DUPLICATE_PERIOD` | 409 |
| `ERR_CENSUS_FULL` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_COVERAGE_FOR_MONTH` | 409 |
| `ERR_RECOUP_EXCEEDS_BILLED` | 422 |
| `ERR_STALE_VERSION` | 412 |
