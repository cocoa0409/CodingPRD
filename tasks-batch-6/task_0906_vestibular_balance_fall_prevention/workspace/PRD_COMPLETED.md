# Vestibular, Balance & Fall-Prevention Clinic API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Vestibular, Balance & Fall-Prevention Clinic API, a back-office platform that coordinates the full clinical journey of a patient referred for dizziness, imbalance, or recurrent falls. The workflow begins when a referring provider sends a patient to the clinic and continues through balance and gait assessment, care planning, insurance authorization against a finite pool of covered visits, scheduled therapy sessions in specialized rooms, home-safety evaluation, assistive-device referral, linkage to evidence-based community fall-prevention programs, periodic reassessment, and a final outcome summary.

The platform serves three collaborating staff roles whose responsibilities intersect but do not fully overlap: a front-desk intake function, licensed therapists, and a supervising clinician. Because a single therapy episode touches a patient's clinical risk profile, a payer's authorized-visit cap, a room and clinician calendar, and a running patient-responsibility balance all at once, the system must keep these derived quantities continuously reconciled. The requirements below define exactly how risk is scored, how authorized visits are reserved and released, how billing is stamped and reversed, and how the plan's lifecycle cascades through its dependent records so that every derived field remains consistent with the events that produced it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting rules that apply uniformly across every endpoint. All resource paths are mounted under the API root.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles, spelled precisely as follows: `IntakeCoordinator`, `Clinician`, and `ClinicSupervisor`.

- **`IntakeCoordinator`** handles front-desk intake, scheduling, authorizations, and community linkage. When `X-User-Role` is `IntakeCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`ClinicSupervisor`** oversees approvals, plan activation and discharge, and resource setup. When `X-User-Role` is `ClinicSupervisor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.
- **`Clinician`** is a licensed therapist who performs assessments, therapy sessions, home-safety evaluations, and reassessments. When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician` entity. Ownership checks on any resource that references a clinician compare that resource's clinician foreign key to `X-User-ID`: finalizing an assessment or a reassessment, and marking a session attended or no-show, all require that the acting clinician's `X-User-ID` equal the target resource's `clinician_id`. When it does not, the request is rejected with `ERR_NOT_OWNER`.

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

### 2.3. Pagination and Listing

List endpoints accept two pagination query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 or above 100 is clamped to the nearest bound rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` value that does not parse as an integer falls back silently to its default. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

Beyond pagination, list endpoints support reverse-reachability filtering by exact match on selected fields. Referrals may be filtered by `patient_id` and `status`. Assessments may be filtered by `patient_id`, `referral_id`, `clinician_id`, and `status`. Care plans may be filtered by `patient_id`, `assessment_id`, and `status`. Reassessments may be filtered by `care_plan_id`, `clinician_id`, and `status`. Authorizations may be filtered by `patient_id`, `care_plan_id`, and `status`. Sessions may be filtered by `care_plan_id`, `clinician_id`, `room_id`, `authorization_id`, `attendance_status`, and `billing_status`. Home-safety evaluations may be filtered by `patient_id`, `care_plan_id`, and `status`. Device referrals may be filtered by `patient_id`, `care_plan_id`, `home_safety_evaluation_id`, `status`, and `source`. Community linkages may be filtered by `patient_id`, `care_plan_id`, `assessment_id`, and `status`.

### 2.4. Common Resource Properties and Numeric Precision

Every resource in this system is a top-level record and carries the same system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is stamped once at creation, and `updated_at` is refreshed on every mutation. The `version` field is an integer that begins at `1` on creation and increments by one on every mutation of the resource. All entities in this system carry the full set — `id`, `created_at`, `updated_at`, and `version`.

Fall-risk and hazard scores are integer point totals; their tier comparisons use inclusive "at least" and exclusive "below" boundaries exactly as described in §3, and no rounding is involved. All monetary quantities — `allowed_amount_cents`, `copay_cents`, `estimated_patient_responsibility_cents`, and `patient_responsibility_cents` — are integer counts of whole cents. Wherever a copay is derived from a payer allowed amount and a coinsurance fraction, the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). The coinsurance fraction `coinsurance_pct` is a number between 0 and 1 inclusive and preserves its input precision.

### 2.5. Versioning and Optimistic Concurrency Control

Two operations advance a care plan's `version` as a deliberate side effect: opening a reassessment on an active plan and creating a community-program linkage against a plan each increment the plan's `version` by one. Of these, only community-linkage creation is guarded by optimistic concurrency control. A linkage-create request must include `expected_care_plan_version` carrying the `version` of the target `CarePlan` that the client last observed. If that value does not equal the plan's current `version` at the moment of the write, the request is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), because the client has not observed a supersession that already advanced the plan. This is purely a version-mismatch check: the plan stays `ACTIVE` throughout, so the rejection reflects stale data rather than an ineligible plan state. Opening a reassessment is an ordinary create and takes no version field. No other endpoint accepts a version field.

### 2.6. Cascading Consistency and Derived-Field Reconciliation

Several operations mutate more than one record. When a care plan is discharged, when a reassessment is finalized, and when a home-safety evaluation is finalized, the system propagates the change to dependent records in the same operation and refreshes each touched record's `updated_at` and `version`. The precise cascade behavior for each of these is defined in §3 alongside the workflow that triggers it.

Two care-plan fields are running derived totals that must always agree with the events that produced them. The `visits_used` counter on an authorization is defined as the number of that authorization's sessions whose `attendance_status` is `SCHEDULED`, `ATTENDED`, or `NO_SHOW` — cancelled sessions are excluded, so whenever a session is cancelled the counter is recomputed downward. The `patient_responsibility_cents` total on a care plan is defined as the sum of `copay_cents` over that plan's sessions whose `billing_status` is `BILLED`; it moves up when a session is billed and down when a billed session is reversed. Because both are recomputed from the current set of qualifying rows, they never drift from the underlying sessions.

### 2.7. Reference Resolution and Existence Checks

Requests routinely reference other records by id, both through path parameters and through foreign-key fields in the request body. The system resolves these references left to right — path identifiers first, then body references in the order they are documented — and rejects the request at the first reference that does not resolve, using the not-found error specific to that entity: `ERR_PATIENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CARE_PLAN_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_HOME_SAFETY_NOT_FOUND`, `ERR_DEVICE_REFERRAL_NOT_FOUND`, `ERR_LINKAGE_NOT_FOUND`, and `ERR_REASSESSMENT_NOT_FOUND`. Each of these carries HTTP 404.

### 2.8. Validation Order

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then, for the owner-scoped clinician operations, the ownership check (`ERR_NOT_OWNER`). Next comes body-shape validation: a missing required field or a value of the wrong type yields `ERR_VALIDATION`, and an enum-typed field carrying a value outside its declared set yields `ERR_INVALID_ENUM`. After the body is well-formed, every referenced id is resolved for existence as described in §2.7. Only then are state and business rules evaluated: the generic state check and its specific siblings (`ERR_INVALID_STATE`, `ERR_ASSESSMENT_NOT_FINALIZED`, `ERR_PLAN_NOT_ACTIVE`, `ERR_AUTH_NOT_APPROVED`), followed by the session time-range check (`ERR_INVALID_TIME_RANGE`), the community-linkage eligibility check (`ERR_TIER_NOT_ELIGIBLE`), the two scheduling-conflict checks (`ERR_CLINICIAN_DOUBLE_BOOKED` and `ERR_ROOM_BUFFER_CONFLICT`), the visit-cap check (`ERR_VISIT_CAP_EXCEEDED`), and finally the optimistic-concurrency check on linkage creation (`ERR_STALE_PLAN_VERSION`). Within a single operation, an earlier check always pre-empts a later one.

### 2.9. Logical Clock

The server keeps a logical clock used for all timestamps and for evaluating scheduling windows. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. Any of the three roles may advance the clock by supplying a target instant in the `to_iso8601` field; this is a test-driving capability and has no other side effect than moving the clock to the provided instant.

## 3. Business Logic & Workflows

### 3.1. Patient Registration and Referral Triage

The clinical record begins with a patient. An `IntakeCoordinator` registers a patient by supplying `full_name`, `date_of_birth` (an ISO date in `YYYY-MM-DD` form), and `insurance_member_id`. A newly registered patient enters `ACTIVE` status; the only other patient status is `DISCHARGED`.

Referrals arrive next. An `IntakeCoordinator` records a referral for a patient by supplying the referred patient via `patient_id`, the `referral_source` describing the referring provider, and the `reason` for the referral, such as dizziness or recurrent falls. A referral opens in `RECEIVED` status. Triage is a decision step: acting on a referral still in `RECEIVED`, an operator supplies a `decision` of either `ACCEPT`, which advances the referral to `ACCEPTED`, or `DECLINE`, which moves it to the terminal `DECLINED` state. A referral that is not in `RECEIVED` cannot be triaged again and yields `ERR_INVALID_STATE`. Referral triage may be performed by an `IntakeCoordinator` or a `ClinicSupervisor`.

### 3.2. Balance and Gait Assessment; Fall-Risk Scoring

Clinical staff and rooms are registered before assessment work begins. A `ClinicSupervisor` registers a `Clinician` with a `full_name`, a `discipline` of either `PT` or `OT`, and an `npi`; and registers a `TherapyRoom` with a `name` and a `room_type` of `BALANCE_GYM`, `EXAM`, or `GAIT_LAB`.

A `Clinician` opens a balance and gait assessment by identifying the assessed patient with `patient_id`, the originating referral with `referral_id`, and the assessing clinician (the owner for later finalization) with `clinician_id`, together with the measured inputs: comfortable gait speed in meters per second as `gait_speed_m_s`, the Timed-Up-and-Go completion time in seconds as `tug_seconds`, the Berg Balance Scale total as `berg_balance_score` (an integer from 0 through 56), the count of prescription medications as `medication_count`, and the number of self-reported falls in the prior twelve months as `self_report_fall_count`. A new assessment enters `DRAFT` status.

**Screening score at creation.** The moment an assessment is created, the system computes a provisional `screening_score` from self-report inputs alone. It is ten points for each self-reported fall — that is, `self_report_fall_count` multiplied by ten — plus a flat fifteen points when the patient is on four or more medications (that is, when `medication_count` is at least four), and zero medication points otherwise. The screening variant deliberately ignores the gait, Timed-Up-and-Go, and Berg measurements, and it does not assign a risk tier; `fall_risk_tier` stays null while the assessment is in `DRAFT`, as does `clinical_score`, which remains null until the assessment is finalized.

**Clinical score at finalize.** Finalizing an assessment (`DRAFT → FINALIZED`) is restricted to the owning clinician and computes the final measured composite `clinical_score` as the sum of five component scores:

- Gait points: thirty when `gait_speed_m_s` is below 0.60; otherwise twenty when it is below 0.80; otherwise ten when it is below 1.00; otherwise zero.
- Timed-Up-and-Go points: thirty when `tug_seconds` is at least 13.5; otherwise twenty when it is at least 12.0; otherwise ten when it is at least 10.0; otherwise zero.
- Berg points: thirty when `berg_balance_score` is at most 20; otherwise fifteen when it is at most 40; otherwise zero.
- Medication points: ten when `medication_count` is at least four; otherwise zero.
- History points: ten when `self_report_fall_count` is at least two; otherwise five when it is exactly one; otherwise zero.

The resulting `clinical_score` ranges from 0 to 110. From it the system derives `fall_risk_tier`: `HIGH` when the score is at least 50, otherwise `MODERATE` when the score is at least 25, otherwise `LOW`. Finalization is permitted only from `DRAFT`; a second finalize attempt is rejected with `ERR_INVALID_STATE`, and a finalize by anyone other than the clinician named in `clinician_id` is rejected with `ERR_NOT_OWNER`.

### 3.3. Care Plan Creation, Activation, and Visit Targets

Once an assessment is finalized, an `IntakeCoordinator` or `ClinicSupervisor` opens a care plan for the patient by supplying `patient_id` and the source `assessment_id`. The referenced assessment must be `FINALIZED`; a plan created from an assessment still in `DRAFT` is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`. On creation the plan copies the assessment's `fall_risk_tier` into its own `fall_risk_tier` and derives `target_visits` from that tier: twelve visits for `HIGH`, eight for `MODERATE`, and four for `LOW`. A new plan opens in `DRAFT` status, with `patient_responsibility_cents` initialized to zero and `estimated_patient_responsibility_cents` still null.

A `ClinicSupervisor` activates a plan, moving it from `DRAFT` to `ACTIVE`; activation from any other state is rejected with `ERR_INVALID_STATE`. Scheduling sessions, linking to community programs, and opening reassessments are all permitted only while the plan is `ACTIVE`; attempting any of them against a non-`ACTIVE` plan is rejected with `ERR_PLAN_NOT_ACTIVE`.

### 3.4. Insurance Authorization and Estimated Responsibility

Coverage for a plan's visits is captured in an insurance authorization. An `IntakeCoordinator` or `ClinicSupervisor` creates one against the covered patient via `patient_id` and the funded plan via `care_plan_id`, recording the insurer as `payer_name`, the hard cap on reserved visits as `visits_authorized`, the payer allowed amount per visit in cents as `allowed_amount_cents`, and the patient coinsurance fraction as `coinsurance_pct`. A new authorization opens in `PENDING` status with `visits_used` at zero.

A `ClinicSupervisor` decides an authorization by supplying a `decision`. A `DENY` moves it to the terminal `DENIED` state. An `APPROVE` moves a `PENDING` authorization to `APPROVED` and, at that moment, computes the plan's forward-looking `estimated_patient_responsibility_cents` as the plan's `target_visits` multiplied by the per-visit copay, where the per-visit copay is the authorization's `allowed_amount_cents` multiplied by its `coinsurance_pct`, rounded half-up to whole cents. This estimate is a single projection made before any visit is delivered and is distinct from the running actual responsibility described in §3.6. Deciding an authorization that is not `PENDING` is rejected with `ERR_INVALID_STATE`.

### 3.5. Session Scheduling: Rooms, Clinicians, and the Visit Cap

Therapy sessions are the unit of delivered care and the point at which authorized visits are reserved. An `IntakeCoordinator` or `ClinicSupervisor` schedules a session by naming the plan via `care_plan_id`, the treating clinician (the owner for attend and no-show) via `clinician_id`, the booked room via `room_id`, and the funding authorization via `authorization_id`, along with `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants, start inclusive and end exclusive) and the billed `cpt_code`. A new session opens with `attendance_status` of `SCHEDULED`, `billing_status` of `UNBILLED`, and `copay_cents` initialized to zero (it is stamped only when the session is attended), and reserving the visit adds one to the authorization's `visits_used`.

Scheduling is subject to a sequence of constraints. The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and the authorization must be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`). The `scheduled_end` must be strictly after `scheduled_start`; an end that is equal to or before the start yields `ERR_INVALID_TIME_RANGE`. Two temporal conflict checks then apply. First, no other non-cancelled session for the same clinician may overlap the requested half-open interval; because intervals are half-open, one session ending exactly when another begins is allowed, but any true overlap is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED`. Second, sessions sharing a room must respect a fifteen-minute turnover buffer: the gap between the earlier session's end and the later session's start must be at least fifteen minutes, and any overlap is likewise rejected; a violation yields `ERR_ROOM_BUFFER_CONFLICT`. Both conflict checks disregard sessions whose `attendance_status` is `CANCELLED`.

Finally, the visit cap is enforced: a session may be reserved only while the authorization's `visits_used` is strictly below its `visits_authorized`. If reserving another visit would bring `visits_used` to or beyond the cap, the request is rejected with `ERR_VISIT_CAP_EXCEEDED`.

### 3.6. Attendance, Billing, and Cancellation

Attendance and billing are parallel dimensions of a session that evolve independently. The `attendance_status` moves through `SCHEDULED`, `ATTENDED`, `NO_SHOW`, or `CANCELLED`, while the `billing_status` moves through `UNBILLED`, `BILLED`, or `REVERSED`.

When the owning `Clinician` marks a `SCHEDULED` session attended, its `attendance_status` becomes `ATTENDED` and, on the billing dimension, its `billing_status` becomes `BILLED`. At that moment the system stamps `copay_cents` as the session authorization's `allowed_amount_cents` multiplied by its `coinsurance_pct`, rounded half-up to whole cents, and adds that stamped copay to the plan's running `patient_responsibility_cents`. Marking a session that is not `SCHEDULED` yields `ERR_INVALID_STATE`, and a non-owning clinician is rejected with `ERR_NOT_OWNER`.

When the owning `Clinician` marks a `SCHEDULED` session a no-show, its `attendance_status` becomes `NO_SHOW`; billing is untouched (it remains `UNBILLED`), and the reserved visit is deliberately not released — a no-show still consumes its authorized visit, so `visits_used` does not change.

Cancellation is available to an `IntakeCoordinator`, a `Clinician`, or a `ClinicSupervisor` and is not owner-scoped. A `SCHEDULED` session may be cancelled: its `attendance_status` becomes `CANCELLED` and its authorization's `visits_used` is recomputed downward, releasing the reservation; because such a session was never billed, no billing reversal occurs. An `ATTENDED` session may also be cancelled as a compensating action: its `attendance_status` becomes `CANCELLED`, its `billing_status` becomes `REVERSED`, the stamped `copay_cents` is subtracted back out of the plan's `patient_responsibility_cents`, and its authorization's `visits_used` is recomputed downward. A cancellation attempt against a session in any other attendance state is rejected with `ERR_INVALID_STATE`.

The running `patient_responsibility_cents` is always the sum of the per-session `copay_cents` over the plan's sessions whose `billing_status` is `BILLED`. Each session's copay is rounded to whole cents when it is stamped at attend time, and the running total adds those already-rounded integers — copays are rounded per session first and only then summed. This billed total diverges from the estimate of §3.4 whenever the number of delivered visits differs from the plan's `target_visits`.

### 3.7. Home-Safety Evaluation and Assistive-Device Referral

A `Clinician` opens a home-safety evaluation for a patient via `patient_id` against the associated plan via `care_plan_id`, recording five hazard counts: `loose_rugs`, `poor_lighting_rooms`, `missing_grab_bars`, `unsecured_stairs`, and `clutter_pathways`. A new evaluation is in `DRAFT`.

Finalizing an evaluation (`DRAFT → FINALIZED`) computes `home_hazard_score` as a weighted total: three points per loose rug, two points per poorly lit room, five points per location missing grab bars, five points per unsecured stair run, and two points per cluttered pathway. From that total the system derives `hazard_tier`: `HIGH` when the score is at least 20, otherwise `MODERATE` when the score is at least 10, otherwise `LOW`. Finalizing an evaluation that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`.

Finalization carries a cascade. When and only when `hazard_tier` resolves to `HIGH`, the system automatically creates an assistive-device referral in the same operation: its `source` is `AUTO_HAZARD`, its `status` opens at `PENDING`, its `home_safety_evaluation_id` points back to this evaluation, and its `device_type` is `GRAB_BAR` when the evaluation recorded one or more `missing_grab_bars` and `ROLLATOR` otherwise. The evaluation's `generated_device_referral_id` is set to the new referral's id; for evaluations whose tier is `LOW` or `MODERATE`, no referral is created and `generated_device_referral_id` stays null.

Assistive-device referrals may also be created manually. A `Clinician` or `ClinicSupervisor` creates one by naming the referred patient via `patient_id` and the associated plan via `care_plan_id`, choosing a `device_type` of `CANE`, `WALKER`, `ROLLATOR`, or `GRAB_BAR`, and optionally supplying `home_safety_evaluation_id` to tie it to a specific evaluation. A manually created referral has `source` of `MANUAL` and opens in `PENDING`. A `ClinicSupervisor` advances a referral by supplying a `decision`: from `PENDING`, an `APPROVE` moves it to `APPROVED` and a `DECLINE` moves it to the terminal `DECLINED`; from `APPROVED`, a `DISPENSE` moves it to the terminal `DISPENSED`. A decision that does not match the referral's current state is rejected with `ERR_INVALID_STATE`.

### 3.8. Community-Program Linkage and Supersession

Patients at elevated risk are linked to an evidence-based community fall-prevention program. An `IntakeCoordinator` or `ClinicSupervisor` creates a linkage by naming the linked patient via `patient_id`, the plan via `care_plan_id`, and the eligibility-source assessment via `assessment_id`, choosing a `program_name` from `MATTER_OF_BALANCE`, `TAI_CHI_MOVING_FOR_BETTER_BALANCE`, `STEPPING_ON`, and `OTAGO`, and supplying `expected_care_plan_version`. The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and the referenced assessment must be `FINALIZED` with a `fall_risk_tier` of either `MODERATE` or `HIGH`; an assessment whose tier is `LOW` (or an assessment not finalized) makes the patient ineligible, and the request is rejected with `ERR_TIER_NOT_ELIGIBLE`.

A plan carries at most one non-terminal linkage at a time. Creating a fresh linkage supersedes any prior linkage on the same plan that is still in `REFERRED` or `ENROLLED`, moving that prior linkage to the terminal `WITHDRAWN` state as a side effect of the create, and it increments the plan's `version` by one. Because that supersession advances the plan's `version`, linkage creation is guarded by optimistic concurrency as described in §2.5: the supplied `expected_care_plan_version` must equal the plan's current `version`, and a mismatch is rejected with `ERR_STALE_PLAN_VERSION`. A newly created linkage opens in `REFERRED`.

An `IntakeCoordinator` or `ClinicSupervisor` advances a linkage's lifecycle by supplying `new_status`. From `REFERRED`, a linkage may move to `ENROLLED` or to the terminal `DECLINED`. From `ENROLLED`, it may move to the terminal `COMPLETED` or the terminal `WITHDRAWN`. A requested transition that the linkage's current state does not admit is rejected with `ERR_INVALID_STATE`.

### 3.9. Reassessment, Discharge, and Outcome

The care plan follows a cyclic rhythm between `ACTIVE` and `UNDER_REASSESSMENT`. A `Clinician` opens a reassessment against an `ACTIVE` plan by naming the reassessing clinician (the owner for finalization) via `clinician_id` and supplying re-measured inputs: `gait_speed_m_s`, `tug_seconds`, `berg_balance_score` (again 0 through 56), `medication_count`, and `self_report_fall_count`. Opening a reassessment creates it in `DRAFT` with `clinical_score` and `fall_risk_tier` both null until finalization, moves the plan from `ACTIVE` to `UNDER_REASSESSMENT`, and increments the plan's `version` by one. This create is not version-guarded and takes no `expected_care_plan_version`.

Finalizing a reassessment is restricted to the owning clinician and is permitted only while the reassessment is `DRAFT` and its parent plan is `UNDER_REASSESSMENT`; otherwise the finalize is rejected with `ERR_INVALID_STATE`, and a non-owner is rejected with `ERR_NOT_OWNER`. Finalization computes the reassessment's `clinical_score` and `fall_risk_tier` using exactly the clinical scoring rules of §3.2, then cascades to the plan: the plan's `fall_risk_tier` is overwritten with the reassessment's new tier, the plan's `target_visits` is recomputed from that new tier (twelve for `HIGH`, eight for `MODERATE`, four for `LOW`), and the plan returns from `UNDER_REASSESSMENT` to `ACTIVE`.

A `ClinicSupervisor` discharges an `ACTIVE` plan, moving it to the terminal `DISCHARGED` state; discharging a plan that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. Discharge carries a depth-three cascade. Every session on the plan whose `attendance_status` is `SCHEDULED` is moved to `CANCELLED`; sessions already `ATTENDED` or `NO_SHOW` are left intact. For each session cancelled this way, its authorization's `visits_used` is recomputed downward, releasing the reservation. Because the sessions cancelled here were `SCHEDULED` and therefore unbilled, no billing reversal occurs in this cascade.

At any time an outcome summary may be requested for a plan. The summary reports `tier_at_intake`, taken from the `fall_risk_tier` of the plan's originating finalized assessment; `tier_current`, the plan's current `fall_risk_tier`; and `clinical_score_delta`. To compute the delta, the system selects the latest finalized reassessment for the plan — the finalized reassessment with the greatest `created_at`, breaking ties by the largest `version` (never by id) — and reports that reassessment's `clinical_score` minus the originating assessment's `clinical_score`; when the plan has no finalized reassessment, `clinical_score_delta` is null. The summary also reports `attended_visit_count`, the number of the plan's sessions whose `attendance_status` is `ATTENDED`; `total_patient_responsibility_cents`, equal to the plan's running `patient_responsibility_cents`; and `improvement_flag`, which is true only when `clinical_score_delta` is present and less than zero, indicating a lower (improved) score at reassessment.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; state-transition and other modification operations, and all reads, return `200 OK`. In the table below, "All roles" denotes `IntakeCoordinator`, `Clinician`, and `ClinicSupervisor`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving) | All roles |
| POST | `/patients` | Register a patient | IntakeCoordinator |
| GET | `/patients/{id}` | Fetch a patient | All roles |
| POST | `/referrals` | Create a referral | IntakeCoordinator |
| GET | `/referrals/{id}` | Fetch a referral | All roles |
| GET | `/referrals` | List/filter referrals | All roles |
| POST | `/referrals/{id}/decision` | Accept or decline a referral | IntakeCoordinator, ClinicSupervisor |
| POST | `/clinicians` | Register a clinician | ClinicSupervisor |
| GET | `/clinicians/{id}` | Fetch a clinician | All roles |
| POST | `/rooms` | Register a therapy room | ClinicSupervisor |
| GET | `/rooms/{id}` | Fetch a therapy room | All roles |
| POST | `/assessments` | Create a balance/gait assessment (DRAFT) | Clinician |
| GET | `/assessments/{id}` | Fetch an assessment | All roles |
| GET | `/assessments` | List/filter assessments | All roles |
| POST | `/assessments/{id}/finalize` | Finalize an assessment | Clinician |
| POST | `/care-plans` | Create a care plan from a finalized assessment | IntakeCoordinator, ClinicSupervisor |
| GET | `/care-plans/{id}` | Fetch a care plan | All roles |
| GET | `/care-plans` | List/filter care plans | All roles |
| POST | `/care-plans/{id}/activate` | Activate a DRAFT care plan | ClinicSupervisor |
| POST | `/care-plans/{id}/discharge` | Discharge an ACTIVE care plan | ClinicSupervisor |
| GET | `/care-plans/{id}/outcome` | Computed outcome summary for a care plan | All roles |
| POST | `/care-plans/{id}/reassessments` | Open a reassessment against an ACTIVE plan | Clinician |
| GET | `/reassessments/{id}` | Fetch a reassessment | All roles |
| GET | `/reassessments` | List/filter reassessments | All roles |
| POST | `/reassessments/{id}/finalize` | Finalize a reassessment | Clinician |
| POST | `/authorizations` | Create an insurance authorization | IntakeCoordinator, ClinicSupervisor |
| GET | `/authorizations/{id}` | Fetch an authorization | All roles |
| GET | `/authorizations` | List/filter authorizations | All roles |
| POST | `/authorizations/{id}/decision` | Approve or deny an authorization | ClinicSupervisor |
| POST | `/sessions` | Schedule a therapy session | IntakeCoordinator, ClinicSupervisor |
| GET | `/sessions/{id}` | Fetch a session | All roles |
| GET | `/sessions` | List/filter sessions | All roles |
| POST | `/sessions/{id}/attend` | Mark a session attended and bill it | Clinician |
| POST | `/sessions/{id}/no-show` | Mark a session no-show | Clinician |
| POST | `/sessions/{id}/cancel` | Cancel a scheduled or attended session | All roles |
| POST | `/home-safety-evaluations` | Create a home-safety evaluation (DRAFT) | Clinician |
| GET | `/home-safety-evaluations/{id}` | Fetch a home-safety evaluation | All roles |
| GET | `/home-safety-evaluations` | List/filter home-safety evaluations | All roles |
| POST | `/home-safety-evaluations/{id}/finalize` | Finalize an evaluation; may auto-create a device referral | Clinician |
| POST | `/device-referrals` | Create an assistive-device referral (manual) | Clinician, ClinicSupervisor |
| GET | `/device-referrals/{id}` | Fetch an assistive-device referral | All roles |
| GET | `/device-referrals` | List/filter device referrals | All roles |
| POST | `/device-referrals/{id}/decision` | Approve, decline, or dispense a device referral | ClinicSupervisor |
| POST | `/community-linkages` | Create a community-program linkage (version-guarded supersede-create) | IntakeCoordinator, ClinicSupervisor |
| GET | `/community-linkages/{id}` | Fetch a community-program linkage | All roles |
| GET | `/community-linkages` | List/filter community linkages | All roles |
| POST | `/community-linkages/{id}/status` | Advance a linkage lifecycle | IntakeCoordinator, ClinicSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_CLINICIAN_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_CARE_PLAN_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_HOME_SAFETY_NOT_FOUND` | 404 |
| `ERR_DEVICE_REFERRAL_NOT_FOUND` | 404 |
| `ERR_LINKAGE_NOT_FOUND` | 404 |
| `ERR_REASSESSMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_AUTH_NOT_APPROVED` | 409 |
| `ERR_TIER_NOT_ELIGIBLE` | 422 |
| `ERR_CLINICIAN_DOUBLE_BOOKED` | 409 |
| `ERR_ROOM_BUFFER_CONFLICT` | 409 |
| `ERR_VISIT_CAP_EXCEEDED` | 409 |
| `ERR_STALE_PLAN_VERSION` | 412 |
