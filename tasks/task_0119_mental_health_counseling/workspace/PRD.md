# Mental Health Counseling Practice API — Product Requirements Document

## 1. Introduction

Modern outpatient mental-health practices operate at the intersection of clinical safety, regulatory compliance, and revenue-cycle hygiene. A single forty-five-minute therapy visit can implicate state licensure boundaries, an interstate telehealth compact, a sliding-fee scale tied to federal poverty guidelines, a payer contract with deductible-and-copay arithmetic, and the supervised-practice hour ledger that pre-licensed associates must satisfy before sitting for licensure exams. Today these concerns live in disconnected spreadsheets, EHR add-ons, and clearinghouse portals, which makes it impossible to assert simple truths such as *"this clinician is currently allowed to see this patient via telehealth, and the resulting charge will reconcile with the contracted allowed amount."*

This document specifies the Mental Health Counseling Practice Management API — a single back-end that owns therapist credentialing, state-license tracking, supervised-hour accrual, appointment scheduling, crisis assessment, safety-plan management, and CPT 90791/90834 billing under either in-network insurance or a self-pay sliding-fee scale. The API is the system of record for every artifact it produces: every credential decision, every scheduling decision, every clinical-safety hold, and every cent that lands on a patient's invoice. All endpoints are mounted under the URL prefix `/practice`.

Two cross-cutting design pressures shape the rest of this specification. First, clinical safety preempts everything: a patient flagged at HIGH crisis risk cannot be seen until a safety plan has been recorded, regardless of the calendar or the billing posture. Second, every claim must be derivable from the appointment that produced it — sliding-fee tier, payer contract mode, deductible state, and the therapist's rack rates must all be reconstructible after the fact from data this API owns.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. When either header is missing or `X-User-Role` is not one of the four recognised values, the request is rejected with `ERR_AUTH_REQUIRED` (HTTP 401). When the headers are well-formed but the role is not permitted to invoke the target endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four recognised values of `X-User-Role` are `PracticeAdmin`, `Therapist`, `Supervisor`, and `BillingClerk`.

- A `PracticeAdmin` is a practice-management operator. `X-User-ID` for this role is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to an entity's `id`. `PracticeAdmin` is the only role permitted to create, update, activate, suspend, reinstate, or deactivate therapists; to create, verify, or revoke state licenses; to create supervisors and supervision assignments and to terminate the latter; to void sessions; to rescind safety plans; and to advance the deterministic test clock.
- A `Therapist` is the clinical user actually delivering care. When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist` entity; ownership checks on any resource that references a `Therapist` (for example, the `therapist_id` foreign key carried by an `Appointment` or a `SupervisionAssignment`) compare the resource's foreign-key field to `X-User-ID`. `Therapist` is the only role permitted to create the `Session` under a checked-in appointment, to complete that session, to record a crisis assessment for a patient, and to author a safety plan for a patient.
- A `Supervisor` is a senior clinician providing oversight to pre-licensed associates. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Supervisor` entity; ownership checks compare a resource's `supervisor_id` foreign key to `X-User-ID`. The supervisor's API surface is read-only.
- A `BillingClerk` handles revenue-cycle work. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity; the server may record it but does not match it against an entity `id`. `BillingClerk` shares insurance-plan creation with `PracticeAdmin`, may PATCH a patient (for example, to reset `deductible_remaining_cents` at year-end), may void a claim within the void window, and reads the claim and insurance-plan resources.

Roles share many GET endpoints; precise authorisation per endpoint is summarised in §4.

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; values outside this range are rejected as schema-validation failures. `offset` defaults to 0 and must be a non-negative integer. Results within a page are sorted by `created_at` in ascending order, so that pagination over a stable result set is deterministic. For every list response the envelope's `meta` block carries `limit`, `offset`, `total_count` (the total number of resources matching the filter, independent of the page), and `has_more` (true when more pages exist beyond the current one).

### 2.4. Common Resource Properties and Versioning

Every resource created by this API carries a server-minted `id` formatted as a UUID; no domain prefix is added and the value is not derived from any business identifier. Every resource also carries a `created_at` timestamp in ISO 8601 UTC with three fractional digits, set at creation time and never modified thereafter. Resources that are mutated after creation additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at 1 and increments by exactly 1 on every successful mutation. Two of the entities in this domain are append-only and therefore carry only `id` and `created_at`, with no `updated_at` and no `version` field: the `SupervisionAssignment` (whose lifecycle field `status` is itself updated, but exposed without `version` because the append-only assignment ledger is the supervised practice's legal audit artifact) and the `CrisisAssessment` (which is a clinical record fixed at the moment of finalisation).

Optimistic concurrency control applies to every PATCH/PUT endpoint and to every state-transition POST that accepts a `version` field. When the client supplies `version` in the request body, the server compares it against the current entity version; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the client omits `version`, the OCC check is skipped and the request proceeds.

### 2.5. Path-Based Resource Resolution

Every nested URL path is resolved from left to right. For a request such as a state-license verification under a therapist, the server first resolves the therapist `id`, then the license `id` underneath it, and rejects with `ERR_NOT_FOUND` (HTTP 404) the moment any segment fails to resolve. Body-referenced foreign keys (for instance `therapist_id`, `patient_id`, `insurance_plan_id`, `supervisor_id`, `trigger_assessment_id`) are resolved during request-body validation; failure to resolve any of these is reported as `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Precision and Rounding

All monetary fields in this API are stored as integer cents. Where a calculation produces a fractional cent (for example, the sliding-fee multiplication of a rack rate by a tier percentage), the result is rounded half-up to the nearest whole cent before storage. Where the calculation is a straight subtraction or `min()` between integer cents, no rounding is required because the result is already integer-valued. Negative monetary inputs are rejected with `ERR_INVALID_AMOUNT` (HTTP 422).

### 2.7. Status Codes and Validation Ordering

New-resource creation endpoints return HTTP 201; idempotent reads and mutating transitions on existing resources return HTTP 200. Schema validation — required fields, types, regex constraints — is the lowest-priority gate and returns `ERR_VALIDATION` (HTTP 400) when violated. Every endpoint runs the following pipeline before performing any side effects, and the rejection that surfaces is the first one to fail in this order: (1) authentication header presence and recognised role; (2) endpoint-level role authorisation; (3) URL-path entity resolution; (4) body foreign-key resolution; (5) state-machine admissibility; (6) endpoint-specific clinical and fiscal preconditions; (7) optimistic-concurrency `version` match; (8) schema validation. Within (6), the safety-related checks always evaluate ahead of fiscal or scheduling checks — for example, on appointment check-in the patient's safety-plan requirement is evaluated before any license-coverage or check-in-window check, so that a safety-plan gap surfaces as `ERR_SAFETY_PLAN_REQUIRED` rather than being masked by a later check.

### 2.8. The Deterministic Clock

This API exposes a deterministic logical clock that all time-dependent rules consult: license expiry, check-in windows, no-show eligibility, the claim-void window, and the assessment-recency precondition for recording a new crisis assessment. The clock is read via a read-only capability and advanced via an admin-only test-driving capability that accepts a target instant `to` in ISO 8601 UTC. Advancing the clock is the moment at which any deferred automatic transition becomes visible — most importantly, the expiry of a `StateLicense` once the new clock has reached or passed its `expires_on`.

### 2.9. Hierarchical Consistency and Cascades

State transitions in this domain are rarely isolated: a therapist suspension, a license expiry, a license revocation, a crisis-assessment finalisation, a safety-plan creation, and a session completion all fan out through deterministic side-effect cascades that this API performs synchronously within the originating request. When a cascade touches a resource, that resource's `updated_at` is refreshed and its `version` is incremented exactly once. Cascades are depth-bounded (the longest in this domain reaches depth three — a single `/sessions/{id}/complete` mutates the session, the appointment, the billing claim, the patient's deductible, the therapist's supervision-hours ledger, and the therapist's licensure-exam eligibility flag — all atomically) and every cascade described in §3 must complete before the originating request returns.

### 2.10. Concurrency Serialisation

Several state-changing operations may be invoked simultaneously by different clients against the same resource. The API enforces first-writer-wins semantics on the relevant lifecycle field. Two simultaneous check-ins on the same appointment serialise on `Appointment.status`: exactly one transitions `SCHEDULED → CHECKED_IN`, and the loser observes the new `CHECKED_IN` state and is rejected with `ERR_APPT_NOT_OPEN`. Two simultaneous complete requests on the same session — or a complete racing a void on the same session — serialise on `Session.status`; the loser is rejected with `ERR_SESSION_NOT_OPEN`. Two simultaneous void requests on the same claim serialise on `BillingClaim.status`; the loser is rejected with `ERR_CLAIM_NOT_POSTED`. A session-complete racing a therapist-suspension on the owning therapist serialises on `Therapist.credential_status` measured at the start of the complete: if the suspension lands first the complete is rejected with `ERR_THERAPIST_NOT_ACTIVE`, and if the complete lands first the session finishes normally and the suspension only places the therapist's *future* `SCHEDULED` appointments on hold. Two safety plans posted for the same patient at the same instant are intentionally not serialised at the request layer — both calls succeed with HTTP 201, the chronologically later writer's plan becomes the `ACTIVE` plan, and the earlier plan is auto-marked `SUPERSEDED` by monotonic `created_at` ordering.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Therapist and Their State Licenses

A practice administrator brings a new clinician into the system by recording the therapist's `full_name` and `npi`. The `npi` is the National Provider Identifier, a ten-digit numeric string that must match the regular shape of ten digits and be unique within the practice. At creation the administrator also selects a `supervision_track` — either `PRE_LICENSED` for an associate accruing supervised hours toward licensure, or `LICENSED` for a fully licensed clinician — and may optionally set `psypact_enrolled` to true to indicate that the therapist has joined the PSYPACT interstate compact for telehealth. Two private-pay rack rates are recorded at the same time, both as integer cents and both required to be at least zero: `pricing_rack_90791_cents` is the practice's rack rate for a CPT 90791 diagnostic intake, and `pricing_rack_90834_cents` is the rack rate for a CPT 90834 forty-five-minute therapy session. A new therapist is born in `credential_status = PROVISIONAL`, with `supervision_hours_accrued` initialised to 0.00 and `licensure_exam_eligible` initialised to false.

Each clinician practices under one or more state-issued licences. A license is created under its owning therapist with a `state_code` (the two-letter US state code, matching the regular shape of two uppercase letters), a `license_number`, an `issued_on` date, and an `expires_on` date (both in UTC midnight). A new license is born in `status = PENDING`. A practice administrator subsequently verifies the license, transitioning it from `PENDING` to `ACTIVE`, but only when the current clock date is on or after `issued_on` and strictly before `expires_on`. Two automatic and one administrative path then take it out of `ACTIVE`: when the deterministic clock advances to an instant on or after the license's `expires_on`, the license transitions from `ACTIVE` to `EXPIRED`; an administrator may also revoke the license directly, transitioning it from `ACTIVE` to `REVOKED`. In both cases, if the owning therapist no longer has any other `ACTIVE` license, the system propagates the loss of coverage downstream: every future `SCHEDULED` appointment for that therapist transitions to `HELD` with `hold_reason = LICENSE_GAP`. The cascade is depth-two — the clock advance (or the revoke) is the originating event, and the appointment holds are the cascade's leaves.

Mutable therapist attributes — `psypact_enrolled`, `pricing_rack_90791_cents`, `pricing_rack_90834_cents` — can be amended at any time by an administrator. Patient-related demographics such as a clinician's clinical notes are not part of this resource. Every PATCH refreshes the therapist's `updated_at` and increments `version` by one, and an optional `version` may be supplied to engage the optimistic concurrency check.

### 3.2. Activation and the Pre-Licensed Hour Ledger

A `PROVISIONAL` therapist is promoted to `ACTIVE` by an administrative activation. The system requires at least one of the therapist's licenses to be in `status = ACTIVE`; without it, the request is rejected with `ERR_NO_ACTIVE_LICENSE`. For a `PRE_LICENSED` therapist the system additionally requires two things: the therapist must have accumulated at least 3000.00 hours in `supervision_hours_accrued` (the boundary is inclusive, so exactly 3000.00 qualifies), and there must be a `SupervisionAssignment` with `status = ACTIVE` pairing this therapist with a supervisor. If either requirement is unmet, the request is rejected with `ERR_SUPERVISION_INCOMPLETE`. A `LICENSED` therapist needs only the active-license requirement to activate. The transition writes `credential_status := ACTIVE` and recomputes `licensure_exam_eligible`.

`licensure_exam_eligible` is a derived boolean that is set to true exactly when `supervision_hours_accrued` has reached or exceeded the 3000.00-hour threshold and `credential_status` is one of `PROVISIONAL` or `ACTIVE`. It is recomputed whenever `supervision_hours_accrued` changes (forward or in reverse) and whenever `credential_status` changes.

An `ACTIVE` therapist may be temporarily taken off duty by an administrator. The suspension transition takes the therapist from `ACTIVE` to `SUSPENDED` with no clinical preconditions and writes `credential_status := SUSPENDED`. It then cascades: every future `SCHEDULED` appointment (where `scheduled_start` is after the current clock) for this therapist transitions to `HELD` with `hold_reason = LICENSE_GAP`. The reinstatement is the inverse: an administrator returns the therapist from `SUSPENDED` to `ACTIVE`, provided the therapist still has at least one `ACTIVE` license; the cascade unholds every appointment that was placed in `HELD` with `hold_reason = LICENSE_GAP` for this therapist, returning each from `HELD` back to `SCHEDULED`. Deactivation is the irreversible end of a therapist's lifecycle: an administrator may move the therapist from `ACTIVE` to `DEACTIVATED` or from `SUSPENDED` to `DEACTIVATED`, but only when no appointment for the therapist remains in any of `SCHEDULED`, `HELD`, or `CHECKED_IN`.

### 3.3. Supervision Assignments

A `Supervisor` is recorded with their `full_name`, their `home_state_code` (two-letter US state where the supervisor is fully licensed), and an `active` flag that defaults to true indicating availability for new supervisees. To pair a pre-licensed therapist with a supervisor, an administrator creates a `SupervisionAssignment` referencing the `therapist_id`, the `supervisor_id`, and a `started_on` date. The assignment is born in `status = ACTIVE` with `ended_on` left null. A supervision assignment carries `id` and `created_at` but, by design, no `updated_at` and no `version` field; mutations to its `status` field are recorded on the lifecycle ledger rather than through the optimistic-concurrency channel. The assignment is terminated by an administrative termination action, which writes `status := TERMINATED` and stamps `ended_on` to the current clock instant. Terminating a supervision assignment under a `PRE_LICENSED` therapist immediately makes any subsequent session-completion on that therapist's behalf fail until a new active assignment exists.

### 3.4. Patient Intake and the Sliding-Fee Scale

A `Patient` is recorded with the patient's `full_name`, their `state_of_residence` (two-letter US state code, matching the regular shape of two uppercase letters), the household's gross annual income in cents (`household_income_cents`, must be at least zero) and the number of household members (`household_size`, must be at least one). An optional `insurance_plan_id` links the patient to an `InsurancePlan` for in-network billing; when this reference is null, the patient is in self-pay mode and the sliding-fee scale governs every claim. At creation the system also initialises `deductible_remaining_cents` to zero (administrators may later adjust this value at year-end via PATCH), initialises `latest_crisis_level` to null, and initialises `safety_plan_required` to false.

The system immediately computes the patient's `sliding_fee_tier_pct` from the household inputs. The calculation first looks up a federal poverty level base in cents for the household size: 1,497,000 cents for a household of one, 2,044,000 cents for a household of two, 2,591,000 cents for a household of three, and 3,138,000 cents for a household of four. For households larger than four, the base is extended by adding 547,000 cents per additional person beyond four — so a household of five uses 3,685,000 cents as its base. If `household_income_cents` is zero or below, the household's poverty ratio is treated as zero; otherwise the poverty ratio is `household_income_cents` divided by that base, computed as a floating-point ratio at full precision (no rounding). The tier is then assigned by walking five inclusive upper bounds in order: a ratio that is at most 1.00 yields `sliding_fee_tier_pct` of 20; a ratio that exceeds 1.00 but is at most 1.50 yields 40; a ratio that exceeds 1.50 but is at most 2.00 yields 60; a ratio that exceeds 2.00 but is at most 2.50 yields 80; any ratio above 2.50 yields 100. The brackets are left-open and right-closed except the first, which is closed on both sides at the lower end. The tier is recomputed whenever a PATCH changes either `household_income_cents` or `household_size`.

A patient PATCH may also update `state_of_residence` or `insurance_plan_id`; either change refreshes `updated_at` and increments `version`. A `BillingClerk` shares PATCH authority with `PracticeAdmin` for this resource so that year-end deductible resets can be performed without administrative privileges.

### 3.5. Insurance Plans and Patient Responsibility

An `InsurancePlan` is created with the payer's commercial name in `payer_name`, an internal `plan_code` that must be unique within the practice, a `network_status` of either `IN_NETWORK` or `OUT_OF_NETWORK`, and a `contract_mode` of either `DEDUCTIBLE_FIRST` or `COPAY_ONLY`. The contracted allowed amounts per session are recorded in `allowed_amount_90791_cents` and `allowed_amount_90834_cents`, and the per-visit copay (used by `COPAY_ONLY` contracts and used by `DEDUCTIBLE_FIRST` once the deductible is met) is recorded in `copay_cents`. All three monetary fields must be at least zero. The plan is created jointly by `PracticeAdmin` or `BillingClerk`; updates are not exposed in this version of the API.

The `network_status` of `OUT_OF_NETWORK` does not produce in-network claim arithmetic. When a patient with such a plan completes a session, the resulting `BillingClaim` is treated as `SELF_PAY` (the practice does not bill out-of-network payers from this API), and the sliding-fee rules govern the resulting charge. The patient should be re-pointed to a different `InsurancePlan` or to self-pay through a PATCH if the contractual posture changes.

### 3.6. Scheduling, Holds, and Check-In

Scheduling an appointment requires the practice-internal `therapist_id` for the clinician, the `patient_id` for the patient, the `cpt_code` (either `90791` for the diagnostic intake or `90834` for the 45-minute individual session), and the `modality` (either `IN_PERSON` or `TELEHEALTH`). The session window is given by `scheduled_start` and `scheduled_end` (both ISO 8601 UTC instants), and the `patient_state_on_day` records the two-letter US state where the patient will physically be on the day of the appointment — for telehealth this anchors the clinician's licensure check, and for in-person visits it is typically the practice's state of operation. `scheduled_end` must be strictly after `scheduled_start` and the minimum session length is one minute; violations return `ERR_INVALID_TIMERANGE`. Either `PracticeAdmin` or `Therapist` may schedule. The appointment is born in `status = SCHEDULED` with `hold_reason` left null.

Two scheduling collision rules guard the calendar. The proposed window must not overlap any existing appointment for the same therapist whose status is one of `SCHEDULED`, `HELD`, or `CHECKED_IN`, where overlap is computed under half-open `[scheduled_start, scheduled_end)` semantics — so back-to-back appointments whose former's `scheduled_end` exactly equals the latter's `scheduled_start` are explicitly allowed. Violations are rejected with `ERR_THERAPIST_DOUBLE_BOOKED`. The proposed window must also leave a minimum gap of five minutes from any existing appointment for the same patient whose status is `SCHEDULED`, `HELD`, or `CHECKED_IN`: formally, either the new appointment's `scheduled_start` minus the other's `scheduled_end` is at least five minutes, or the other's `scheduled_start` minus the new appointment's `scheduled_end` is at least five minutes. Zero-gap adjacency for the same patient is rejected with `ERR_PATIENT_DOUBLE_BOOKED`. Both collision rules also fire on a PATCH that reschedules an existing appointment.

A `SCHEDULED` appointment may be moved to `HELD` automatically by the system as a consequence of one of three originating events: the owning therapist becomes `SUSPENDED`, the therapist loses license coverage for `patient_state_on_day` (via a license expiry or revocation that empties the active-license set), or the patient's `safety_plan_required` becomes true (because a `CrisisAssessment` finalised at `HIGH` with no current `ACTIVE` plan). When both a license condition and a safety-plan condition apply at the same instant, `hold_reason = SAFETY_PLAN_MISSING` takes precedence over `hold_reason = LICENSE_GAP`. A `HELD` appointment returns automatically from `HELD` to `SCHEDULED` once the originating condition has cleared — that is, the therapist returns to `ACTIVE`, a covering license is verified, or an `ACTIVE` safety plan is recorded — at which point `hold_reason` is cleared back to null.

A `SCHEDULED` appointment is checked in by the acting therapist or a practice administrator. The check-in is admitted only when the current clock is within the window `[scheduled_start − 15min, scheduled_start + 30min]`; outside this window the request is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`. Several additional checks gate the transition. The acting therapist's `credential_status` must be one of `PROVISIONAL` or `ACTIVE` (pre-licensed associates may see patients while accruing supervised hours; `SUSPENDED` and `DEACTIVATED` are rejected with `ERR_THERAPIST_NOT_ACTIVE`). The therapist must hold an `ACTIVE` `StateLicense` whose `state_code` equals `patient_state_on_day`, or — for telehealth coverage under the interstate compact — the therapist must have `psypact_enrolled = true`, `patient_state_on_day` must be a PSYPACT-participating state, and the therapist must hold at least one `ACTIVE` license whose `state_code` is itself a PSYPACT-participating state. The PSYPACT state set comprises AL, AR, AZ, CO, CT, DC, DE, FL, GA, IL, KS, KY, ME, MD, MN, NE, NV, NH, NJ, NC, OH, OK, PA, TN, TX, UT, VA, WA, WV, WI, WY. Failure of the license coverage check is rejected with `ERR_LICENSE_GAP_FOR_STATE`. The patient's `safety_plan_required` must be false; if it is true, the request is rejected with `ERR_SAFETY_PLAN_REQUIRED` before any license or scheduling check is consulted. If the therapist is on the `PRE_LICENSED` track, a `SupervisionAssignment` with `status = ACTIVE` must exist for that therapist at check-in time. When all checks pass, the appointment transitions from `SCHEDULED` to `CHECKED_IN`. A check-in attempted on an appointment whose status is no longer `SCHEDULED` — including the loser of a concurrent check-in race — is rejected with `ERR_APPT_NOT_OPEN`.

A `SCHEDULED` or `HELD` appointment may be cancelled by the acting therapist or by an administrator at any moment strictly before `scheduled_start`; the transition takes the appointment to `CANCELLED` and clears `hold_reason` to null when the source state was `HELD`. A `SCHEDULED` appointment that the patient never attended may be marked as a no-show after `scheduled_end` has passed; the transition takes the appointment to `NO_SHOW`. Both cancel and mark-no-show are mutually exclusive with check-in and lose to check-in under the same `ERR_APPT_NOT_OPEN` rejection if a check-in landed first.

### 3.7. The Session, the Claim, and the Hour Ledger

Once an appointment is `CHECKED_IN`, the acting therapist opens a clinical `Session` underneath it by supplying `actual_duration_minutes` (the realised session length, at least one minute). The session is born in `status = IN_PROGRESS`, its `type` is mirrored from the parent appointment's `cpt_code` — `INTAKE` when `cpt_code = 90791` and `INDIVIDUAL` when `cpt_code = 90834` — and `supervision_credit_hours` is initialised to 0.0 (it is computed at completion time).

Completion is the single richest cascade in this API. The therapist completes the session, which the system admits only when the owning appointment is in `CHECKED_IN`, when `actual_duration_minutes` is set, and — for a `PRE_LICENSED` therapist — when a `SupervisionAssignment` with `status = ACTIVE` exists for the therapist at the moment of completion. The first failure of the session-state precondition is rejected with `ERR_SESSION_NOT_OPEN`; the supervised-status failure is rejected with `ERR_NO_ACTIVE_SUPERVISOR`; an attempt to complete a session whose therapist is no longer `ACTIVE` or `PROVISIONAL` is rejected with `ERR_THERAPIST_NOT_ACTIVE`. On success the session transitions from `IN_PROGRESS` to `COMPLETED`, its `supervision_credit_hours` is computed (1.00 for `INDIVIDUAL`, 1.50 for `INTAKE`), and the owning appointment also transitions to `COMPLETED`.

In the same atomic cascade a `BillingClaim` is auto-posted underneath the appointment. The claim's `appointment_id` is the parent appointment, `patient_id` is copied from the appointment, `cpt_code` is a snapshot of the appointment's `cpt_code`, and `posted_at` is stamped to the completion instant. The claim's `billing_mode` and `insurance_plan_id` are determined from the patient's posture at the moment of completion: if the patient's `insurance_plan_id` points to a plan whose `network_status` is `IN_NETWORK`, the claim records `billing_mode = INSURANCE_IN_NETWORK` and `insurance_plan_id` is snapshot from the plan; otherwise the claim records `billing_mode = SELF_PAY` and `insurance_plan_id` is null. The claim is born in `status = POSTED`.

For a `SELF_PAY` claim, the `charged_amount_cents` is computed from the therapist's rack rate and the patient's sliding-fee tier. The rack rate is `pricing_rack_90791_cents` when the procedure is the 90791 intake, and `pricing_rack_90834_cents` when the procedure is the 90834 forty-five-minute session. The charge is that rack rate multiplied by `sliding_fee_tier_pct` and divided by 100, with the result rounded half-up to the nearest cent. The full charge becomes `patient_responsibility_cents`, and `insurer_paid_cents` is zero. For an `INSURANCE_IN_NETWORK` claim, the `charged_amount_cents` is the contracted allowed amount on the plan — `allowed_amount_90791_cents` for the intake and `allowed_amount_90834_cents` for the 45-minute session. The patient's responsibility then depends on the contract mode and on the patient's deductible state at the moment of completion. When `contract_mode = DEDUCTIBLE_FIRST` and the patient still has `deductible_remaining_cents` greater than zero, the patient pays the smaller of the allowed amount and the remaining deductible — this is the deductible-first phase — and the insurer pays the rest of the allowed amount; the patient's `deductible_remaining_cents` is decreased by exactly that paid amount. When `contract_mode = DEDUCTIBLE_FIRST` and the deductible is already exhausted (zero), the patient pays the smaller of the plan's `copay_cents` and the allowed amount, and the insurer pays the remainder of the allowed amount; this is the deductible-first after-met phase. When `contract_mode = COPAY_ONLY`, the patient pays the smaller of `copay_cents` and the allowed amount irrespective of any deductible state, and the insurer pays the remainder. The three modes share identical inputs but produce different numbers — the contract mode is the pivot. `insurer_paid_cents` is always `charged_amount_cents − patient_responsibility_cents` for in-network claims, and zero for self-pay claims.

Session completion also moves the supervised-hour ledger forward. The system adds the session's `supervision_credit_hours` (1.00 or 1.50) to the therapist's `supervision_hours_accrued` and rounds the running total half-up to two decimal places. Immediately after, `licensure_exam_eligible` is recomputed: it becomes true when the new `supervision_hours_accrued` is at least 3000.00 and the therapist's `credential_status` is one of `PROVISIONAL` or `ACTIVE`, and false otherwise. The full cascade from a single complete request thus reaches depth three: the session transition feeds the claim, the claim's posting feeds the deductible adjustment, the session transition also feeds the supervised-hour increment, and the increment feeds the licensure-eligibility recomputation.

A session that has not yet been completed may be voided by an administrator. The void transitions the session from `IN_PROGRESS` to `VOIDED`, and as a compensating action also transitions the owning appointment to `CANCELLED`. A void attempted on a session whose status is no longer `IN_PROGRESS` is rejected with `ERR_SESSION_NOT_OPEN`.

### 3.8. Claim Voids and Compensating Reversals

A `BillingClaim` in `status = POSTED` may be voided by a `PracticeAdmin` or by a `BillingClerk`, but only when the owning session was completed within the last seven days as measured against the deterministic clock; an attempt outside that window is rejected with `ERR_VOID_WINDOW_EXPIRED`. A void on a claim that has already been voided is rejected with `ERR_CLAIM_NOT_POSTED`. The void transitions the claim from `POSTED` to `VOIDED` and triggers a compensating reversal across the resources that the original posting touched. For an `INSURANCE_IN_NETWORK` claim, the amount previously consumed against the patient's deductible — equal to the smaller of `charged_amount_cents` at posting and `deductible_remaining_cents` at posting — is restored to `Patient.deductible_remaining_cents`. The therapist's `supervision_hours_accrued` is reduced by the owning session's `supervision_credit_hours` (1.00 or 1.50) using the same round-half-up-to-two-decimal-places rule, and `licensure_exam_eligible` is recomputed against the reduced total — so the flag may flip from true back to false. Finally, the owning session is moved to `status = VOIDED` and the owning appointment is moved to `status = CANCELLED`.

### 3.9. Crisis Assessment and Safety Plans

Crisis assessment is the clinical safety control that preempts every fiscal and scheduling concern in the system. A therapist records a `CrisisAssessment` under a patient by supplying five integer factor scores: `si_score` (suicidal-ideation factor, 0 through 4 inclusive), `pa_score` (prior-attempts factor, 0 through 3 inclusive), `su_score` (substance-use factor, 0 through 2 inclusive), `so_score` (social-isolation factor, 0 through 2 inclusive), and `am_score` (access-to-means factor, 0 through 2 inclusive). The body also names the assessing `therapist_id`. The assessment is admitted only when the acting therapist has had a `CHECKED_IN` or `COMPLETED` appointment with this patient at any time in the prior ninety days, or when the acting therapist holds an active credential and is on duty. The assessment is born in (and stays in) `status = FINALIZED`; this record carries `id` and `created_at` but no `updated_at` and no `version`, and the moment of finalisation is recorded in `assessed_at`.

The `composite_score` is computed in a pinned order. Each of the five factor scores is multiplied by its weight — 4.005 for the suicidal-ideation factor, 3.005 for the prior-attempts factor, 2.005 for the substance-use factor, 1.005 for the social-isolation factor, and 2.505 for the access-to-means factor. Each of the five per-factor products is rounded half-up to two decimal places first, *then* the five rounded per-factor values are summed, *then* the sum is rounded half-up to two decimal places to produce `composite_score`. The order is load-bearing: rounding before summation, not the other way around. The `risk_level` is then bucketed by walking two inclusive lower bounds in order: a `composite_score` of at least 23.55 yields `HIGH`; a `composite_score` below 23.55 but at least 15.00 yields `MODERATE`; anything below 15.00 yields `LOW`. The finalised assessment writes the patient's `latest_crisis_level` to the bucketed `risk_level`. If the new `risk_level` is `HIGH` and no `SafetyPlan` with `status = ACTIVE` exists for this patient, the system also sets `safety_plan_required` to true, which in turn triggers the appointment-hold cascade described in §3.6 — every future `SCHEDULED` appointment for this patient transitions to `HELD` with `hold_reason = SAFETY_PLAN_MISSING`. That depth-three cascade — assessment finalise → patient flag → appointment hold — completes atomically within the originating request.

A therapist clears the safety requirement by authoring a `SafetyPlan` for the patient. The plan body must reference a `trigger_assessment_id` — the `CrisisAssessment` that triggered the requirement — and that referenced assessment must belong to this same patient and have `risk_level = HIGH`; violations are rejected with `ERR_HIGH_ASSESSMENT_REQUIRED`. The plan also captures `warning_signs`, `coping_strategies`, an array of `support_contacts` (each an object with a name and a phone number; the array must have at least one entry), a `crisis_hotline` 24/7 phone number, and a `means_restriction_plan`. The new plan is born in `status = ACTIVE`. Creating the plan supersedes any prior `ACTIVE` plan for this patient (the prior plan transitions from `ACTIVE` to `SUPERSEDED`), sets the patient's `safety_plan_required` to false, and unholds every `HELD` appointment for this patient whose `hold_reason = SAFETY_PLAN_MISSING`, returning each from `HELD` back to `SCHEDULED`. When two safety plans are posted for the same patient at essentially the same instant, both succeed; the chronologically later writer becomes the `ACTIVE` plan and the earlier is auto-marked `SUPERSEDED` by `created_at` ordering.

A safety plan may be rescinded by a practice administrator once the patient's clinical picture has improved. Rescission is admitted only when the patient's most recent `CrisisAssessment` has `risk_level` in either `LOW` or `MODERATE`; an attempt while the latest assessment is still `HIGH` is rejected with `ERR_RISK_STILL_HIGH`. The transition takes the plan from `ACTIVE` to `RESCINDED`.

## 4. Endpoint Definitions

All endpoints listed below are rooted at the `/practice` prefix. Creation endpoints return HTTP 201 and the created resource in `data`. State-transition endpoints and PATCH endpoints return HTTP 200 with the mutated resource. GET endpoints return HTTP 200. Request bodies, response payloads, and side-effect cascades are specified in §3 and are not duplicated here; consult §3 to reconstruct the full request and the full reaction.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/practice/therapists` | Create a new therapist record. | `PracticeAdmin` |
| GET | `/practice/therapists/{id}` | Read a therapist. | `PracticeAdmin`, `Therapist`, `Supervisor`, `BillingClerk` |
| GET | `/practice/therapists` | List therapists; filters by `credential_status`, `supervision_track`. | `PracticeAdmin`, `BillingClerk` |
| PATCH | `/practice/therapists/{id}` | Update rack rates and PSYPACT enrolment. | `PracticeAdmin` |
| POST | `/practice/therapists/{id}/activate` | Activate a PROVISIONAL or SUSPENDED therapist. | `PracticeAdmin` |
| POST | `/practice/therapists/{id}/suspend` | Suspend an ACTIVE therapist. | `PracticeAdmin` |
| POST | `/practice/therapists/{id}/reinstate` | Alias of activate from SUSPENDED. | `PracticeAdmin` |
| POST | `/practice/therapists/{id}/deactivate` | Permanently deactivate a therapist. | `PracticeAdmin` |
| POST | `/practice/therapists/{tid}/licenses` | Create a state license in PENDING. | `PracticeAdmin` |
| POST | `/practice/therapists/{tid}/licenses/{id}/verify` | Move a PENDING license to ACTIVE. | `PracticeAdmin` |
| POST | `/practice/therapists/{tid}/licenses/{id}/revoke` | Revoke an ACTIVE license. | `PracticeAdmin` |
| GET | `/practice/therapists/{tid}/licenses` | List licenses for a therapist; filter by `status`. | `PracticeAdmin`, `Therapist`, `BillingClerk` |
| POST | `/practice/supervisors` | Create a supervisor. | `PracticeAdmin` |
| GET | `/practice/supervisors/{id}` | Read a supervisor. | `PracticeAdmin`, `Supervisor` |
| POST | `/practice/supervision-assignments` | Pair a pre-licensed therapist with a supervisor. | `PracticeAdmin` |
| POST | `/practice/supervision-assignments/{id}/terminate` | Terminate an ACTIVE supervision assignment. | `PracticeAdmin` |
| POST | `/practice/patients` | Create a patient; sliding-fee tier computed immediately. | `PracticeAdmin`, `Therapist` |
| GET | `/practice/patients/{id}` | Read a patient. | `PracticeAdmin`, `Therapist`, `BillingClerk` |
| PATCH | `/practice/patients/{id}` | Update demographics, income, insurance, or deductible. | `PracticeAdmin`, `BillingClerk` |
| POST | `/practice/insurance-plans` | Create an insurance plan contract. | `PracticeAdmin`, `BillingClerk` |
| GET | `/practice/insurance-plans/{id}` | Read an insurance plan. | `PracticeAdmin`, `BillingClerk` |
| POST | `/practice/appointments` | Schedule an appointment. | `PracticeAdmin`, `Therapist` |
| GET | `/practice/appointments/{id}` | Read an appointment. | `PracticeAdmin`, `Therapist`, `BillingClerk` |
| PATCH | `/practice/appointments/{id}` | Reschedule or change modality (SCHEDULED/HELD only). | `PracticeAdmin`, `Therapist` |
| POST | `/practice/appointments/{id}/check-in` | Check the patient in. | `Therapist`, `PracticeAdmin` |
| POST | `/practice/appointments/{id}/cancel` | Cancel a SCHEDULED or HELD appointment. | `Therapist`, `PracticeAdmin` |
| POST | `/practice/appointments/{id}/mark-no-show` | Mark a SCHEDULED appointment as a no-show after end. | `Therapist`, `PracticeAdmin` |
| POST | `/practice/appointments/{id}/sessions` | Create the IN_PROGRESS Session for a CHECKED_IN appointment. | `Therapist` |
| GET | `/practice/appointments` | List appointments; filter by `therapist_id`, `patient_id`, `status`. | `PracticeAdmin`, `Therapist`, `BillingClerk` |
| POST | `/practice/sessions/{id}/complete` | Complete an IN_PROGRESS Session; cascades. | `Therapist` |
| POST | `/practice/sessions/{id}/void` | Void an IN_PROGRESS Session. | `PracticeAdmin` |
| GET | `/practice/sessions/{id}` | Read a session. | `PracticeAdmin`, `Therapist`, `BillingClerk` |
| GET | `/practice/claims/{id}` | Read a billing claim. | `PracticeAdmin`, `BillingClerk` |
| POST | `/practice/claims/{id}/void` | Void a POSTED claim within the 7-day window. | `PracticeAdmin`, `BillingClerk` |
| GET | `/practice/claims` | List claims; filter by `patient_id`, `status`, `billing_mode`. | `PracticeAdmin`, `BillingClerk` |
| POST | `/practice/patients/{pid}/crisis-assessments` | Finalize a crisis assessment for a patient. | `Therapist` |
| GET | `/practice/patients/{pid}/crisis-assessments` | List crisis assessments for a patient. | `Therapist`, `PracticeAdmin` |
| POST | `/practice/patients/{pid}/safety-plans` | Create a safety plan; supersedes prior ACTIVE plan. | `Therapist` |
| POST | `/practice/safety-plans/{id}/rescind` | Rescind an ACTIVE safety plan. | `PracticeAdmin` |
| GET | `/practice/patients/{pid}/safety-plans` | List safety plans for a patient; filter by `status`. | `Therapist`, `PracticeAdmin` |
| POST | `/practice/_clock/advance` | Advance the deterministic clock to the supplied `to` instant. | `PracticeAdmin` |
| GET | `/practice/_clock` | Read the current deterministic clock. | `PracticeAdmin`, `Therapist`, `Supervisor`, `BillingClerk` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_INVALID_TIMERANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_APPT_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_POSTED` | 409 |
| `ERR_VOID_WINDOW_EXPIRED` | 409 |
| `ERR_SAFETY_PLAN_REQUIRED` | 409 |
| `ERR_HIGH_ASSESSMENT_REQUIRED` | 422 |
| `ERR_RISK_STILL_HIGH` | 409 |
| `ERR_THERAPIST_NOT_ACTIVE` | 409 |
| `ERR_LICENSE_GAP_FOR_STATE` | 409 |
| `ERR_NO_ACTIVE_LICENSE` | 409 |
| `ERR_NO_ACTIVE_SUPERVISOR` | 409 |
| `ERR_SUPERVISION_INCOMPLETE` | 409 |
| `ERR_THERAPIST_DOUBLE_BOOKED` | 409 |
| `ERR_PATIENT_DOUBLE_BOOKED` | 409 |
| `ERR_OUTSIDE_CHECKIN_WINDOW` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
