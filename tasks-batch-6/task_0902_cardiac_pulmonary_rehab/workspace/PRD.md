# Cardiac & Pulmonary Rehab Program API — Product Requirements Document

## 1. Introduction

Cardiac and pulmonary rehabilitation is a physician-directed, medically monitored program in which patients recovering from cardiac events or living with chronic pulmonary disease progress through structured, supervised exercise, education, and goal-setting. Each course of care is bounded by two independent scarcity constraints that the program staff must reconcile continuously: a clinical authorization cap (the well-known 36-session ceiling) and a payer-imposed visit limit that governs how many sessions may actually be billed. This API is the system of record that coordinates the full arc of a rehab episode — from the referring physician's initial referral and risk stratification, through program creation, insurance authorization, and monitored-exercise scheduling, to outcome measurement, billing reconciliation, discharge, and enrollment in an ongoing maintenance program.

The system serves four distinct operational roles whose surfaces rarely overlap: referring physicians who originate referrals, rehab coordinators who run day-to-day program operations, rehab clinicians (exercise physiologists) who supervise sessions and record vitals, and billing specialists who manage the revenue cycle. Because clinical safety and financial accuracy are both first-class concerns, the API enforces monitored-exercise safety thresholds (oxygen saturation, exertion, telemetry requirements) alongside a ledger-style billing model that distinguishes provisional estimates from adjudicated settlements. The requirements below specify the complete contract every implementation must satisfy.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `ReferringPhysician`, `RehabCoordinator`, `RehabClinician`, and `BillingSpecialist`.

Two of these roles are backed by a persisted entity, which ties `X-User-ID` to resource ownership:

- When `X-User-Role` is `ReferringPhysician`, `X-User-ID` is the `id` of the acting `Physician`. Ownership checks on any resource that references a `Physician` compare the resource's foreign-key field to `X-User-ID`; in particular, a referring physician may only create a referral in which the `physician_id` equals their own `X-User-ID`.
- When `X-User-Role` is `RehabClinician`, `X-User-ID` is the `id` of the acting `Clinician`. Ownership checks on any resource that references a `Clinician` compare the resource's `clinician_id` to `X-User-ID`.

The other two roles are opaque:

- When `X-User-Role` is `RehabCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The coordinator owns configuration records, referral decisions, the program lifecycle, authorizations, session scheduling and rescheduling, and maintenance management.
- When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. The billing specialist owns the claim lifecycle.

Read endpoints (all `GET` operations) are available to all four roles. The patient billing statement is readable by both `RehabCoordinator` and `BillingSpecialist`. Placing a program on hold may be initiated by either a `RehabCoordinator` or a `RehabClinician`; all other program-lifecycle transitions are `RehabCoordinator`-only. The per-operation authorization matrix is summarized in the endpoint table in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All primary resources — `Patient`, `Physician`, `Clinician`, `MonitoringStation`, `Referral`, `RehabProgram`, `InsuranceAuthorization`, `RehabSession`, `CarePlanItem`, `OutcomeAssessment`, `BillingClaim`, and `MaintenanceProgram` — carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations to its derived counters and billing totals.
- `version`: an integer that begins at 1 on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in §2.6.

All timestamps and the logical "now" are governed by the server's logical clock. The clock starts at exactly `2026-05-01T00:00:00Z`; before any client sets it, reads of the current instant return exactly this default, and the server never falls back to wall-clock time. An administrative test-driving capability lets an operator advance the logical clock to a supplied instant (`to_iso8601`), and the response echoes the new `current_utc`.

### 2.5. Nested Resource Retrieval and Referential Integrity

For any request that names resources by identifier — whether in the URL path or as foreign keys in the body — the system validates existence left to right, in the order the identifiers appear. The first identifier that does not resolve to an existing resource produces that resource's specific not-found error (for example, `ERR_PROGRAM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CARE_PLAN_ITEM_NOT_FOUND`, `ERR_OUTCOME_NOT_FOUND`, or `ERR_MAINTENANCE_NOT_FOUND`), each returned with HTTP 404. Existence is checked before any state or business rule.

Beyond mere existence, several operations require that cross-aggregate references be mutually consistent. When a claim is created, the referenced session and authorization must both belong to the same program as the claim; when a session is scheduled, its station and clinician must resolve and the session's program must be the one named. A reference that resolves but points into the wrong program (or otherwise fails cross-aggregate consistency) is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409). This consistency check applies to claim creation and to session scheduling.

A malformed body — a missing required field, a value of the wrong type, or an unparseable payload — is rejected with `ERR_VALIDATION` (HTTP 400). When an enum-typed field carries a value outside its declared set, the rejection is `ERR_INVALID_ENUM` (HTTP 400).

### 2.6. Optimistic Concurrency Control on Session Scheduling

Scheduling a new session is the one write that participates in optimistic concurrency control, because the program's remaining-capacity picture shifts with every scheduling, completion, void, and missed-session cascade. A request to schedule a session must carry `expected_program_version`, a non-optional field whose value is the client's last observed `version` of the target `RehabProgram`. If `expected_program_version` does not equal the program's current `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). This forces a client that scheduled against a now-outdated view of remaining capacity to re-read the program and re-derive its capacity assumption from a fresh version before retrying. No other endpoint accepts or requires a version field.

### 2.7. Monetary Precision and Rounding

Monetary quantities are stored and computed as integer cents; there is no fractional-cent representation. Wherever a calculation floors a value at zero, it does so by taking the greater of zero and the computed figure. Where the session pricing calculation multiplies a base rate by a risk multiplier (§3.7), the product is rounded to a whole number of cents using the round-half-up convention before any surcharge is added or any cap is applied.

Two computations round to units coarser than cents. The six-minute-walk improvement percentage (§3.6) is rounded half up to one decimal place. The patient statement dollar total (§3.7) rounds each individual claim's patient-responsibility cents to whole dollars — half up — and only then sums those per-claim dollar amounts; the order matters and must not be replaced by summing cents first and rounding once.

### 2.8. Session Authorization Accounting

Every `RehabProgram` carries an `authorized_session_cap` — the clinical ceiling on sessions, which defaults to 36 (the standard cardiac/pulmonary rehab authorization) but may be set lower at creation for a shorter authorization. Against this cap the program maintains derived counters, each recomputed whenever a session is created, completed, voided, or marked missed:

- `sessions_used` is the count of this program's sessions in `COMPLETED` status.
- `sessions_scheduled` is the count of this program's sessions in `SCHEDULED` status.
- `sessions_remaining_authorized` is the chronological, completed-only remainder: the `authorized_session_cap` minus `sessions_used`.

A forward-looking projection — the cap minus `sessions_used` minus `sessions_scheduled` — governs whether another session may be booked. Scheduling (whether creating a new session or rescheduling a missed one) is permitted only while the sum of `sessions_used` and `sessions_scheduled` is strictly less than `authorized_session_cap`; a request that would push that sum to or past the cap is rejected with `ERR_SESSION_CAP_REACHED` (HTTP 409). Voiding a completed session decrements `sessions_used`, deliberately conserving the identity that `authorized_session_cap` equals `sessions_used` plus `sessions_remaining_authorized`.

### 2.9. Cascading State Propagation and Billing Reconciliation

Certain program-level transitions cascade to their child sessions. Whenever a program leaves the operational track — moving from `ACTIVE` to `ON_HOLD`, or being withdrawn from `DRAFT`, `ACTIVE`, or `ON_HOLD` — every one of that program's sessions still in `SCHEDULED` status is transitioned to `CANCELLED`, releasing its station and clinician interval. Each such cascade, like any mutation, refreshes the affected resources' `updated_at` and increments their `version`.

On the billing side, the program continuously reconciles four money counters over all of its claims that are not in `VOID` status: `total_billed_cents` sums each claim's `billed_amount_cents`; `total_reimbursed_cents` sums each claim's reimbursement (the adjudicated figure for a paid claim, otherwise the estimate); `total_patient_responsibility_cents` sums each claim's patient responsibility; and `outstanding_balance_cents` sums the patient-responsibility amounts of claims currently in `DENIED` status (the portion not recovered from the payer). These totals are recomputed on claim submission, adjudication, resubmission, and voiding, so that over the set of non-void claims the billed total always equals the sum of reimbursed and patient-responsibility totals.

### 2.10. Monitored-Exercise Safety and Scheduling Protocols

Because monitored exercise carries clinical risk, the API enforces safety and scheduling constraints at booking time and at completion. A program stratified as `HIGH` risk may only run a `MONITORED_EXERCISE` session on a `TELEMETRY` station; booking or rescheduling such a session onto a non-telemetry station is rejected with `ERR_TELEMETRY_STATION_REQUIRED` (HTTP 422). A session's proposed interval must not overlap another `SCHEDULED` session on the same station: the interval is treated as half-open on `[scheduled_start, scheduled_end)`, so exact adjacency (one session's end equal to the next session's start) is allowed, but any true overlap is rejected with `ERR_STATION_OVERLAP` (HTTP 409). The supervising clinician must additionally be free within a 15-minute turnover buffer of any other `SCHEDULED` session; two of that clinician's sessions must therefore be separated by more than 15 minutes, and adjacency within 15 minutes is not allowed, with violations rejected as `ERR_CLINICIAN_UNAVAILABLE` (HTTP 409). Finally, `scheduled_end` must be strictly after `scheduled_start`, or the request is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 400).

These checks are evaluated in a fixed precedence, which matters when several could fire at once. The system evaluates, in order: authentication, then role and ownership authorization, then existence of every path and foreign-key resource, then (for session scheduling only) the optimistic-concurrency version check, then the target's state legality, then cross-aggregate reference consistency, then the telemetry-station safety rule, then station overlap, then clinician turnover availability, then the strictly-positive time range, and finally the 36-session capacity cap. Thus, for example, a stale program version surfaces as `ERR_STALE_PROGRAM_VERSION` before any scheduling-conflict or capacity check is even attempted, and a cross-program reference surfaces before the telemetry check.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Patients, Physicians, Clinicians, and Stations

Before any clinical work begins, a `RehabCoordinator` establishes the reference records the rest of the system points at. A `Patient` is registered with a medical record number `mrn` (unique per patient), a `full_name`, and a `date_of_birth` given as an ISO 8601 calendar date. A referring physician's record captures the physician's `full_name`, their National Provider Identifier `npi`, and an optional `specialty` label. A rehab clinician's record captures a `full_name` and a `credential`, which is one of `RN`, `RRT`, or `EP` (exercise physiologist). A monitoring station is registered with a `name` (for example, "Treadmill-1") and a `station_type` of either `TELEMETRY` or `STANDARD`. These are simple registries; each of these four resource types is created only by a coordinator and is thereafter readable by any role.

### 3.2. Referral Intake and Risk Stratification

The clinical episode originates when a `ReferringPhysician` submits a referral. The referral names the `patient_id` and the `physician_id` (which must equal the caller's own `X-User-ID`), declares the `program_type` as either `CARDIAC` or `PULMONARY`, records the free-text `indication` (the diagnosis driving the referral), and assigns a `risk_stratification` of `LOW`, `MODERATE`, or `HIGH`. This AACVPR-style tier is the physician's clinical judgment of the patient's risk and, once carried forward into the program, drives both the telemetry requirement and the billing multiplier. A newly created referral begins in `PENDING` status.

A `RehabCoordinator` then dispositions the pending referral by supplying a `decision` of either `ACCEPT` or `DECLINE`, moving the referral from `PENDING` to `ACCEPTED` or from `PENDING` to `DECLINED` respectively. A decision may only be rendered on a referral that is still `PENDING`; otherwise the request is rejected with `ERR_REFERRAL_NOT_PENDING`. A `decision` value that is neither `ACCEPT` nor `DECLINE` is rejected with `ERR_INVALID_DECISION` (HTTP 400). Referrals may be listed and filtered by `patient_id` or `physician_id` to support reverse lookup from those records.

### 3.3. Program Creation, Insurance Authorization, and Activation

Once a referral is `ACCEPTED`, a `RehabCoordinator` creates the `RehabProgram` from it. Program creation takes the `referral_id`, an optional `current_phase`, and an optional `authorized_session_cap`. The referral must be in `ACCEPTED` status, or creation is rejected with `ERR_REFERRAL_NOT_ACCEPTED`. On creation, the program copies `patient_id`, `program_type`, and `risk_stratification` from the referral; `current_phase` defaults to `PHASE_I` when not supplied and may otherwise be `PHASE_II` or `PHASE_III` (`PHASE_I` is inpatient, `PHASE_II` is outpatient monitored, and `PHASE_III` is the maintenance track); `authorized_session_cap` defaults to 36 when omitted; and the program starts in `DRAFT` status. The coordinator may later update `current_phase` as the patient progresses. Programs may be listed and filtered by `patient_id` or `referral_id`.

The program's payer coverage is captured as one or more insurance authorizations. A coordinator creates an `InsuranceAuthorization` against a `program_id`, recording the `payer_name`, the `authorized_visits` (a positive integer visit-limit of billable sessions), the `allowed_amount_cents` (the payer's allowed amount per visit, used for estimated reimbursement), and the per-visit `copay_cents`. An authorization begins in `PENDING`. Approving it — permitted only while it is `PENDING`, else `ERR_AUTHORIZATION_NOT_PENDING` — moves it to `APPROVED`. Each authorization tracks `visits_billed`, the count of non-void claims drawn against it; when `visits_billed` reaches `authorized_visits`, the authorization automatically transitions to `EXHAUSTED`. Authorizations may be listed and filtered by `program_id`.

Activating a `DRAFT` program moves it to `ACTIVE`, but only when three conditions all hold: the program is in `DRAFT` (else `ERR_PROGRAM_NOT_DRAFT`), at least one `APPROVED` insurance authorization exists for the program (else `ERR_NO_APPROVED_AUTHORIZATION`), and at least one `FINALIZED` `BASELINE` outcome assessment exists for the program (else `ERR_BASELINE_OUTCOME_REQUIRED`). Only after activation may sessions be scheduled and completed.

### 3.4. Scheduling Monitored Sessions

With the program `ACTIVE`, a `RehabCoordinator` schedules sessions. The scheduling request identifies the `program_id`, the supervising `clinician_id`, the occupied `station_id`, the `session_type` (`MONITORED_EXERCISE`, `EDUCATION`, or `ASSESSMENT`), the session's `phase` label (`PHASE_I`, `PHASE_II`, or `PHASE_III`), and the interval endpoints `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants). The request must also carry `expected_program_version` as described in §2.6. A session may only be scheduled while its parent program is `ACTIVE`; scheduling against a program in any other status is rejected with `ERR_PROGRAM_NOT_ACTIVE`. A newly scheduled session begins in `SCHEDULED` status; the act of scheduling increments the program's `version` by one and recomputes `sessions_scheduled`.

Scheduling is where the safety and capacity guards of §2.8 and §2.10 apply in concert — the telemetry-station rule for `HIGH`-risk monitored exercise, station non-overlap, clinician turnover buffer, a strictly-positive interval, and the 36-session cap — all evaluated in the precedence spelled out in §2.10.

### 3.5. Session Execution: Completion, Vitals, Missed Sessions, and Corrections

A `RehabClinician` completes a scheduled session, at which point the exercise vitals are recorded: the pre-exercise heart rate `pre_hr`, the post-exercise heart rate `post_hr`, the post-exercise oxygen saturation `post_spo2`, the Borg rating of perceived exertion `rpe` (a 6–20 scale), and the `exercise_minutes` of monitored activity. Completion is allowed only when the session is `SCHEDULED` (else `ERR_SESSION_NOT_SCHEDULED`) and the parent program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`), moving the session from `SCHEDULED` to `COMPLETED`. Completing a session increments `sessions_used` by one, resets the program's `consecutive_missed_count` to zero, and increments the program's `version` by one.

At completion the system evaluates the recorded vitals for an adverse event and stores the result in `adverse_event`. The session is flagged adverse when the recorded post-exercise oxygen saturation is present and below 85 percent, or when the recorded rating of perceived exertion is present and at least 18. The oxygen-saturation boundary is strict — a `post_spo2` of exactly 85 is not adverse, while 84 is — whereas the exertion boundary is inclusive, so an `rpe` of 18 is adverse but 17 is not. When either vital is absent it does not contribute to the determination. If the completed session is adverse, the program is immediately driven from `ACTIVE` to `ON_HOLD`, which in turn cascades to cancel the program's remaining `SCHEDULED` sessions per §2.9.

When a patient does not show, the clinician marks the scheduled session as missed, moving it from `SCHEDULED` to `MISSED`; this increments the program's `consecutive_missed_count` and its `version`. Three consecutive missed sessions signal disengagement: if `consecutive_missed_count` reaches 3 while the program is `ACTIVE`, the program is automatically moved from `ACTIVE` to `ON_HOLD`, again cascading to cancel remaining scheduled sessions. Any subsequent completed session resets the consecutive-missed count to zero, and resuming a held program (see below) likewise resets it.

A `RehabCoordinator` may reschedule a missed session, moving it back from `MISSED` to `SCHEDULED` with a new `scheduled_start` and `scheduled_end` (and optionally a new `clinician_id` or `station_id`). Rescheduling is permitted only on a `MISSED` session (else `ERR_SESSION_NOT_MISSED`) and re-applies the same booking guards as initial scheduling — the new interval must clear station overlap (`ERR_STATION_OVERLAP`), the clinician turnover buffer (`ERR_CLINICIAN_UNAVAILABLE`), the telemetry-station rule for high-risk monitored exercise (`ERR_TELEMETRY_STATION_REQUIRED`), the strictly-positive time range (`ERR_INVALID_TIME_RANGE`), and the 36-session cap (`ERR_SESSION_CAP_REACHED`). A coordinator may also cancel a scheduled session outright, moving it from `SCHEDULED` to `CANCELLED` (only from `SCHEDULED`, else `ERR_SESSION_NOT_SCHEDULED`).

A completed session can be voided by a coordinator as a compensating correction, moving it from `COMPLETED` to `VOIDED`. Voiding is allowed only when the session is `COMPLETED` (else `ERR_SESSION_NOT_COMPLETED`) and no non-void billing claim references it (else `ERR_SESSION_HAS_ACTIVE_CLAIM`). Voiding decrements `sessions_used` by one and increments the program's `version`, reversing the accounting effect of the original completion. Sessions may be listed and filtered by `program_id`, `clinician_id`, `station_id`, or `status`.

### 3.6. Care Plan Items and Six-Minute-Walk Outcomes

A `RehabClinician` builds out the program's care plan by adding items to a `program_id`. Each `CarePlanItem` has an `item_type` of either `EDUCATION_MODULE` or `GOAL`, a `title` (the education topic or goal statement), and an optional `target_description` giving a measurable target for a goal. Items begin `OPEN`. A clinician resolves an open item by supplying a `resolution` of `ACHIEVED`, `NOT_ACHIEVED`, or `WAIVED`, moving the item from `OPEN` to the corresponding terminal state; resolving an item that is not `OPEN` is rejected with `ERR_CARE_ITEM_NOT_OPEN`. Items may be listed and filtered by `program_id` or `item_type`. As noted in §3.8, program discharge also resolves any still-open `GOAL` items automatically.

Functional outcomes are measured with the six-minute walk test (6MWT). A clinician records an `OutcomeAssessment` against a `program_id`, giving the `timing` (`BASELINE` or `DISCHARGE`), the walked `distance_meters`, and an optional `assessment_type` that defaults to `SIX_MINUTE_WALK`. An assessment begins as `DRAFT`. Finalizing it moves it from `DRAFT` to `FINALIZED` and may optionally correct the distance via `final_distance_meters` supplied at finalize; finalizing an assessment that is not `DRAFT` is rejected with `ERR_OUTCOME_NOT_DRAFT`. Finalizing a `DISCHARGE` assessment additionally requires that a `FINALIZED` `BASELINE` assessment already exist for the program, else `ERR_BASELINE_OUTCOME_REQUIRED`. Outcomes may be listed and filtered by `program_id` or `timing`.

The improvement figures on a discharge assessment are computed against the program's finalized baseline. The `improvement_meters` is the discharge distance minus the baseline distance, and `improvement_pct` is that same difference divided by the baseline distance, multiplied by 100, and rounded half up to one decimal place. This calculation has two variants that can differ. While the discharge assessment is still `DRAFT`, the provisional improvement uses the draft `distance_meters` (against the finalized baseline distance) and reflects an un-verified value that may still be corrected. Once the discharge assessment is `FINALIZED`, the verified improvement uses the possibly-corrected `final_distance_meters`, and its `improvement_meters` and `improvement_pct` may differ from the provisional figures.

### 3.7. Billing: Claim Pricing, Adjudication, and Reconciliation

A `BillingSpecialist` owns the claim lifecycle. A `BillingClaim` is created against a `program_id`, a `session_id`, and an `authorization_id`. The referenced session must be `COMPLETED`, the referenced authorization must be `APPROVED` and belong to the same program, and — because a claim consumes a payer visit — creation is refused once the authorization's `visits_billed` has reached its `authorized_visits`, rejected as `ERR_VISIT_LIMIT_REACHED`. Creating a claim increments the authorization's `visits_billed` by one and starts the claim in `DRAFT`.

At creation the claim's `billed_amount_cents` is computed and frozen. The base rate is chosen by the session's `session_type`: 15000 cents for `MONITORED_EXERCISE`, 8000 cents for `EDUCATION`, and 10000 cents for `ASSESSMENT`. That base is multiplied by the risk multiplier for the program's `risk_stratification` — 1.00 for `LOW`, 1.10 for `MODERATE`, and 1.25 for `HIGH` — and the product is rounded half up to a whole number of cents. A telemetry surcharge of 3000 cents is then added when the billed session's station is of type `TELEMETRY`, and nothing is added for a standard station. Finally the amount is capped at 20000 cents: `billed_amount_cents` is the smaller of the surcharged figure and 20000 cents.

Also frozen at creation are the estimated reimbursement figures, which use the authorization's contracted rate. The `estimated_reimbursement_cents` is the greater of zero and the quantity (the smaller of `billed_amount_cents` and the authorization's `allowed_amount_cents`, minus the `copay_cents`). The `estimated_patient_responsibility_cents` is `billed_amount_cents` minus `estimated_reimbursement_cents`. While the claim is in `DRAFT` or `SUBMITTED`, its `patient_responsibility_cents` mirrors this estimated responsibility.

Submitting a `DRAFT` claim moves it to `SUBMITTED` (only from `DRAFT`, else `ERR_CLAIM_NOT_SUBMITTABLE`) and recomputes the program's billing totals. Adjudicating a `SUBMITTED` claim (else `ERR_CLAIM_NOT_ADJUDICABLE`) takes an `outcome` of either `PAID` or `DENIED`. On a `PAID` outcome, the payer returns an `adjudicated_allowed_cents`; the `adjudicated_reimbursement_cents` becomes the greater of zero and (`adjudicated_allowed_cents` minus `copay_cents`), and the claim's `patient_responsibility_cents` becomes `billed_amount_cents` minus `adjudicated_reimbursement_cents`. Because the payer's adjudicated allowed amount typically differs from the contracted allowed amount, the adjudicated reimbursement and patient responsibility usually differ from the earlier estimates. On a `DENIED` outcome, a `denial_reason` is recorded, the claim's `patient_responsibility_cents` becomes the full `billed_amount_cents`, and the program's `outstanding_balance_cents` increases by that `billed_amount_cents`.

A `DENIED` claim may be resubmitted, moving it from `DENIED` back to `SUBMITTED` (only from `DENIED`, else `ERR_CLAIM_NOT_DENIED`); resubmission subtracts that claim's `billed_amount_cents` from the program's `outstanding_balance_cents`, reversing the denial's balance addition. A claim may also be voided from `DRAFT`, `SUBMITTED`, or `DENIED` (else `ERR_CLAIM_NOT_VOIDABLE`), moving it to `VOID`; voiding decrements the authorization's `visits_billed` by one and recomputes the program's billing totals, and if the voided claim had been `DENIED`, it also subtracts that claim's `billed_amount_cents` from `outstanding_balance_cents`. Claims may be listed and filtered by `program_id`, `session_id`, `authorization_id`, or `status`.

The patient statement, readable by a coordinator or a billing specialist, aggregates the program's non-void claims in `created_at` ascending order. For each such claim, its `patient_responsibility_cents` is converted to whole dollars by rounding half up; these per-claim dollar figures are then summed to produce `statement_total_dollars`. The statement response also reports the `claim_count` of non-void claims, the program's `total_patient_responsibility_cents`, and its `outstanding_balance_cents`. The per-claim-then-sum ordering is deliberate and distinct from summing cents first.

### 3.8. Discharge, Maintenance Enrollment, and Withdrawal

Placing an `ACTIVE` program `ON_HOLD` — whether requested by a coordinator or clinician, or triggered automatically by an adverse completion or the third consecutive miss — is permitted only from `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`) and carries an optional `reason`; the transition cancels every remaining `SCHEDULED` session as described in §2.9. Resuming a held program returns it from `ON_HOLD` to `ACTIVE` (only from `ON_HOLD`, else `ERR_PROGRAM_NOT_ON_HOLD`) and resets `consecutive_missed_count` to zero.

Discharge concludes the episode, moving an `ACTIVE` program to `DISCHARGED`. It requires that the program be `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`), that no session remain in `SCHEDULED` status (else `ERR_ACTIVE_SESSIONS_EXIST`), and that at least one `FINALIZED` `DISCHARGE` outcome assessment exist for the program (else `ERR_NO_FINALIZED_DISCHARGE_OUTCOME`). Discharge has two side effects: any still-`OPEN` `GOAL` care plan items are transitioned to `NOT_ACHIEVED`, and a new `MaintenanceProgram` is created in `ACTIVE` status.

The maintenance program copies the source `program_id` and `patient_id` and is tiered by the discharge functional gain. Its `tier` is `INTENSIVE` when the finalized discharge assessment's `improvement_pct` is strictly less than 10.0 percent, reflecting a low functional gain that warrants closer maintenance; otherwise the tier is `STANDARD`. The `monthly_visit_allowance` follows from the tier: 4 monthly visits for a `STANDARD` tier and 8 for an `INTENSIVE` tier. A coordinator may cancel an active maintenance program, moving it from `ACTIVE` to `CANCELLED` (only from `ACTIVE`, else `ERR_MAINTENANCE_NOT_ACTIVE`). Maintenance programs may be listed and filtered by `program_id` or `patient_id`.

A program that the patient abandons is withdrawn. Withdrawal is permitted from `DRAFT`, `ACTIVE`, or `ON_HOLD` (an already-terminal program is rejected with `ERR_PROGRAM_ALREADY_TERMINAL`), carries an optional `reason`, moves the program to `WITHDRAWN`, and cancels every remaining `SCHEDULED` session per §2.9.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all lifecycle transitions and the logical-clock control, return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rehab/patients` | Register a patient | RehabCoordinator |
| GET | `/rehab/patients/{patientId}` | Get a patient | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/physicians` | Register a referring physician record | RehabCoordinator |
| GET | `/rehab/physicians/{physicianId}` | Get a physician | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/clinicians` | Register a rehab clinician record | RehabCoordinator |
| GET | `/rehab/clinicians/{clinicianId}` | Get a clinician | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/stations` | Register a monitoring/exercise station | RehabCoordinator |
| GET | `/rehab/stations/{stationId}` | Get a station | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/referrals` | Create a referral with risk stratification | ReferringPhysician |
| GET | `/rehab/referrals/{referralId}` | Get a referral | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/referrals` | List referrals | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/referrals/{referralId}/decision` | Accept or decline a pending referral | RehabCoordinator |
| POST | `/rehab/programs` | Create a program from an ACCEPTED referral | RehabCoordinator |
| GET | `/rehab/programs/{programId}` | Get a program with computed capacity & billing fields | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/programs` | List programs | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/programs/{programId}/activate` | Activate a DRAFT program | RehabCoordinator |
| POST | `/rehab/programs/{programId}/hold` | Place an ACTIVE program ON_HOLD | RehabCoordinator, RehabClinician |
| POST | `/rehab/programs/{programId}/resume` | Resume an ON_HOLD program | RehabCoordinator |
| POST | `/rehab/programs/{programId}/discharge` | Discharge an ACTIVE program | RehabCoordinator |
| POST | `/rehab/programs/{programId}/withdraw` | Withdraw a program | RehabCoordinator |
| GET | `/rehab/programs/{programId}/statement` | Computed patient billing statement | RehabCoordinator, BillingSpecialist |
| POST | `/rehab/authorizations` | Create an insurance authorization for a program | RehabCoordinator |
| GET | `/rehab/authorizations/{authorizationId}` | Get an authorization | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/authorizations` | List authorizations | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/authorizations/{authorizationId}/approve` | Approve a PENDING authorization | RehabCoordinator |
| POST | `/rehab/sessions` | Schedule a session (OCC on program version) | RehabCoordinator |
| GET | `/rehab/sessions/{sessionId}` | Get a session incl. vitals & adverse_event | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/sessions` | List sessions | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/sessions/{sessionId}/complete` | Record vitals and complete the session | RehabClinician |
| POST | `/rehab/sessions/{sessionId}/mark-missed` | Mark a scheduled session as missed | RehabClinician |
| POST | `/rehab/sessions/{sessionId}/reschedule` | Reschedule a MISSED session | RehabCoordinator |
| POST | `/rehab/sessions/{sessionId}/cancel` | Cancel a SCHEDULED session | RehabCoordinator |
| POST | `/rehab/sessions/{sessionId}/void` | Void a COMPLETED session | RehabCoordinator |
| POST | `/rehab/care-plan-items` | Add an education module or goal | RehabClinician |
| GET | `/rehab/care-plan-items/{itemId}` | Get a care plan item | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/care-plan-items` | List care plan items | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/care-plan-items/{itemId}/resolve` | Resolve an OPEN item | RehabClinician |
| POST | `/rehab/outcomes` | Record a 6MWT outcome assessment as DRAFT | RehabClinician |
| GET | `/rehab/outcomes/{outcomeId}` | Get an outcome assessment | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/outcomes` | List outcomes | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/outcomes/{outcomeId}/finalize` | Finalize a DRAFT outcome | RehabClinician |
| POST | `/rehab/claims` | Create a claim for a COMPLETED session | BillingSpecialist |
| GET | `/rehab/claims/{claimId}` | Get a claim | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/claims` | List claims | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/claims/{claimId}/submit` | Submit a DRAFT claim | BillingSpecialist |
| POST | `/rehab/claims/{claimId}/adjudicate` | Adjudicate a SUBMITTED claim (PAID or DENIED) | BillingSpecialist |
| POST | `/rehab/claims/{claimId}/resubmit` | Resubmit a DENIED claim | BillingSpecialist |
| POST | `/rehab/claims/{claimId}/void` | Void a DRAFT/SUBMITTED/DENIED claim | BillingSpecialist |
| GET | `/rehab/maintenance-programs/{maintenanceId}` | Get a maintenance program | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| GET | `/rehab/maintenance-programs` | List maintenance programs | ReferringPhysician, RehabCoordinator, RehabClinician, BillingSpecialist |
| POST | `/rehab/maintenance-programs/{maintenanceId}/cancel` | Cancel an ACTIVE maintenance program | RehabCoordinator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | RehabCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PHYSICIAN_NOT_FOUND` | 404 |
| `ERR_CLINICIAN_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_CARE_PLAN_ITEM_NOT_FOUND` | 404 |
| `ERR_OUTCOME_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_MAINTENANCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_INVALID_DECISION` | 400 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_REFERRAL_NOT_PENDING` | 409 |
| `ERR_PROGRAM_NOT_DRAFT` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_PROGRAM_NOT_ON_HOLD` | 409 |
| `ERR_PROGRAM_ALREADY_TERMINAL` | 409 |
| `ERR_AUTHORIZATION_NOT_PENDING` | 409 |
| `ERR_SESSION_NOT_SCHEDULED` | 409 |
| `ERR_SESSION_NOT_MISSED` | 409 |
| `ERR_SESSION_NOT_COMPLETED` | 409 |
| `ERR_SESSION_HAS_ACTIVE_CLAIM` | 409 |
| `ERR_OUTCOME_NOT_DRAFT` | 409 |
| `ERR_CARE_ITEM_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_SUBMITTABLE` | 409 |
| `ERR_CLAIM_NOT_ADJUDICABLE` | 409 |
| `ERR_CLAIM_NOT_DENIED` | 409 |
| `ERR_CLAIM_NOT_VOIDABLE` | 409 |
| `ERR_MAINTENANCE_NOT_ACTIVE` | 409 |
| `ERR_NO_APPROVED_AUTHORIZATION` | 409 |
| `ERR_BASELINE_OUTCOME_REQUIRED` | 409 |
| `ERR_NO_FINALIZED_DISCHARGE_OUTCOME` | 409 |
| `ERR_ACTIVE_SESSIONS_EXIST` | 409 |
| `ERR_REFERRAL_NOT_ACCEPTED` | 409 |
| `ERR_CROSS_PROGRAM_REFERENCE` | 409 |
| `ERR_TELEMETRY_STATION_REQUIRED` | 422 |
| `ERR_STATION_OVERLAP` | 409 |
| `ERR_CLINICIAN_UNAVAILABLE` | 409 |
| `ERR_SESSION_CAP_REACHED` | 409 |
| `ERR_VISIT_LIMIT_REACHED` | 409 |
