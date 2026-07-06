# Pain Management API — Product Requirements Document

## 1. Introduction

Pain management clinics operate at the intersection of clinical care and controlled-substance regulation. A single patient may move from an outside referral, through intake, into a treatment plan that forks toward either an interventional procedure (an injection or radiofrequency ablation performed in a fluoroscopy suite) or a medication path anchored by controlled-substance prescriptions. Every opioid touchpoint along that journey — the opioid treatment agreement, the state PDMP (Prescription Drug Monitoring Program) database query, the periodic urine drug screen, the pill-count audit — is a compliance checkpoint whose failure has legal as well as clinical weight.

This document specifies the Pain Management API, a system of record that governs this entire journey while continuously reconciling each patient's aggregate opioid exposure, expressed as a daily morphine milligram equivalent (MED). The API enforces a strict segregation of duties between the prescriber who writes and signs, the compliance officer who audits and clears, the intake coordinator who handles logistics and scheduling, and the prior-authorization clerk who manages payer approvals. It treats the fluoroscopy suite as a shared, conserved booking resource; it treats each patient's controlled-substance ledger as a conserved quantity that must balance across every prescribe, suspend, and discontinue event; and it exposes a logical clock so that time-dependent compliance windows can be exercised deterministically.

The requirements below define the resource model, the state machines that drive each clinical object, the dual-variant MED and pill-count calculations, the validation and safety gates, and the exact error semantics the implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting compliance principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles: `ClinicAdmin`, `IntakeCoordinator`, `Prescriber`, `ComplianceOfficer`, and `PriorAuthClerk`.

Two of these roles are entity-backed, and three are opaque. When `X-User-Role` is `Prescriber`, `X-User-ID` is the `id` of the acting `Provider`, and that provider must have `role_kind` `PRESCRIBER`; ownership checks on any resource that references a provider — for example, the counter-signing constraint on an opioid agreement — compare the resource's provider foreign key to `X-User-ID`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise the `id` of the acting `Provider`, and that provider must have `role_kind` `COMPLIANCE_OFFICER`; this identity anchors the segregation of duties between prescribing and compliance oversight. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `IntakeCoordinator` and when `X-User-Role` is `PriorAuthClerk`: in both cases `X-User-ID` is an opaque operator identifier not tied to any persisted entity, which the server does not compare to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- **`updated_at`** — an ISO 8601 UTC timestamp indicating when the resource was last modified; refreshed on every mutation.
- **`version`** — a system-managed integer that starts at its initial value and increments by one with every modification to the resource. This field also underpins optimistic concurrency control where noted.

One entity is deliberately leaner. A `PdmpCheck` is an immutable audit record: it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field. Every other entity in this specification — `Clinic`, `Provider`, `Patient`, `OpioidAgreement`, `TreatmentPlan`, `FluoroscopySuite`, `Procedure`, `PriorAuthorization`, `Prescription`, `UrineDrugScreen`, `PillCountAudit`, and `ControlledSubstanceLedger` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. The Logical Clock

Each `Clinic` maintains its own logical clock, exposed as the `current_utc` field. This clock is the sole time reference for every compliance and scheduling window in the system: intake due-dates, agreement expiry, PDMP freshness, screen due-dates, procedure start gating, and elapsed-day calculations all read `current_utc` rather than wall-clock time. On server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly moved it stays at that default and never falls back to wall-clock time. An administrative test-driving capability advances the clock for a named clinic to a supplied instant, identifying the target clinic by `clinic_id` and the new value by `to_iso8601`; applying it sets that clinic's `current_utc` to the supplied value.

### 2.6. Precision and Rounding

All MED (morphine milligram equivalent) quantities and pill-count expectations that the system rounds are rounded to exactly 2 decimal places using the round-half-up method. This applies to `provisional_daily_med_mg`, `final_daily_med_mg`, the patient's aggregate `current_daily_med_mg`, the ledger totals, and the forward-looking pill-count expectation `expected_pills_forward`. Fluoroscopy suite scheduling is evaluated at minute granularity, and agreement expiry and freshness windows are evaluated at second granularity.

### 2.7. Nested Resource Retrieval and Referential Integrity

Many endpoints address resources through a nested path, such as a procedure that lives beneath a clinic and a patient. When a path carries multiple resource identifiers, the system validates their existence in strict left-to-right order and rejects the request at the first identifier that does not resolve, returning the not-found error for that specific resource type — `ERR_CLINIC_NOT_FOUND`, then `ERR_PATIENT_NOT_FOUND`, and so on down the path. A request for a procedure under a non-existent patient therefore fails with `ERR_PATIENT_NOT_FOUND` before the procedure is ever looked up.

Beyond path identifiers, several create operations reference other resources through the request body. When creating a procedure, activating a prescription, or performing a pill-count audit, the referenced foreign-key bodies — the suite (`suite_id`), the prior authorization (`prior_auth_id`), the prescribing provider (`prescriber_id`), the counted prescription (`prescription_id`), and the treatment plan (`treatment_plan_id`) — must exist and must belong to the same clinic as the enclosing patient. A missing or cross-clinic reference is rejected with the corresponding not-found error for that resource type.

### 2.8. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. Authentication comes first: the presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) is checked before anything else, then role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`). Existence checks follow: first the path resource identifiers left-to-right, then the body foreign-key references, each yielding the appropriate not-found error. On the procedure-schedule operation specifically, the optimistic-concurrency check on the clinic version is evaluated next, before any business logic. State validity of the target resource is then checked (the relevant `ERR_*_STATE_INVALID`). Only after all of the above do the business rules run: referential business checks (prior-authorization approval and target-kind match, treatment-plan path), then the controlled-substance safety gates (opioid agreement, PDMP freshness, and patient-flag checks), then temporal and capacity constraints (suite conflict), then constraint checks (taper step), then the referential discharge guard, and finally the fiscal authorized-units check. Where a specific operation's ordering matters, it is restated in the relevant workflow narrative in Section 3.

### 2.9. Controlled-Substance Ledger and MED Conservation

Each patient owns exactly one `ControlledSubstanceLedger`, created automatically when the patient is registered. The ledger is the conserved-quantity backbone of controlled-substance accounting. It tracks three running sums, each expressed in daily MED milligrams: `total_active_med_mg`, the sum of `provisional_daily_med_mg` across the patient's `ACTIVE` and `TAPERING` prescriptions; `suspended_med_mg`, the MED currently parked in `SUSPENDED` prescriptions; and `discontinued_med_mg`, the running sum of MED that discontinuation has removed. Across every prescribe, suspend, and discontinue event, the sum of `total_active_med_mg`, `suspended_med_mg`, and `discontinued_med_mg` is invariant: MED is never created or destroyed by a state change, only moved between these three accounts. Whenever any of these accounts changes, the patient's own `current_daily_med_mg` is recomputed as the sum of `provisional_daily_med_mg` over that patient's `ACTIVE` and `TAPERING` prescriptions, rounded to two decimal places, so that the patient record and the ledger's active total always agree.

### 2.10. Cascading Consistency

Several operations mutate more than one resource in a single transaction, and every branch of every cascade must land. When a compliance event flags a patient, when an opioid agreement is revoked, or when a patient is discharged, the system propagates the consequences down through prescriptions, the ledger, the patient's aggregate MED, and — for discharge — procedures and the suites they occupy. Each secondary resource touched by a cascade is itself a mutation: its `updated_at` is refreshed and its `version` is incremented. The specific cascades are described where their triggering workflow lives in Section 3.

### 2.11. Optimistic Concurrency on Suite Scheduling

The fluoroscopy suite's booking capacity is a clinic-wide shared resource, so every successful suite scheduling increments the enclosing `Clinic`'s `version` by one. To protect a client from scheduling against a stale view of that shared capacity, the scheduling operation for a requested procedure requires the client to supply `expected_clinic_version`, carrying the `version` of the clinic the client last observed. If `expected_clinic_version` does not match the clinic's current `version` — because another writer has scheduled a procedure and advanced the version since the client last read it — the scheduling request is rejected with `ERR_STALE_CLINIC_VERSION` (HTTP 412), before any business logic runs, preventing the client from booking against booking state it has not observed. This is the only operation that takes a version field; no other endpoint requires or accepts one.

## 3. Business Logic & Workflows

### 3.1. Clinic Setup, Providers, and Compliance Policy

A `ClinicAdmin` stands up the environment. Creating a clinic establishes the compliance policy holder: the request supplies the clinic `name` and its US `state_code`, and may optionally set two policy thresholds. The first, `med_review_threshold_mg`, is the daily MED at or above which a prescription is treated as a high-scrutiny controlled prescription requiring the full opioid-compliance package; it defaults to 90 when omitted. The second, `pill_count_tolerance`, is the absolute pill-count discrepancy in whole pills at or below which an audit is judged consistent; it defaults to 2 when omitted. A freshly created clinic's logical clock (`current_utc`) begins at the startup default described in Section 2.5.

The same administrator registers `Provider` records against a clinic. Each provider carries a `clinic_id` tying it to its clinic, a `full_name`, a `dea_number` (the DEA registration number authorizing controlled-substance prescribing), and a `role_kind`, which must be either `PRESCRIBER` — a provider who may write prescriptions and counter-sign agreements — or `COMPLIANCE_OFFICER` — a provider who may clear flags and result screens. Any other `role_kind` value is rejected as an invalid enum value. The administrator also creates `FluoroscopySuite` records, each with a `clinic_id`, a `name` such as a suite label, and an optional `cleanup_buffer_minutes` that defaults to 15 and represents the mandatory cleanup time that must follow every procedure before the next may begin in that suite. A new suite's `booked_minutes` — the conserved sum of `duration_minutes` across its `SCHEDULED` procedures — starts at 0.

### 3.2. Referral and Intake

The patient journey begins when an `IntakeCoordinator` registers a referral. Registration supplies the patient's `full_name` and `referral_source` (the referring provider or facility); the system assigns a `clinic_id`, sets `status` to `REFERRED`, initializes `compliance_flag` to `NONE`, sets `current_daily_med_mg` to 0, initializes `open_uds_count` to 0, and creates the patient's `ControlledSubstanceLedger` row. The patient's `intake_utc` begins unset.

Scheduling intake advances the patient from `REFERRED` to `INTAKE_SCHEDULED`. The coordinator supplies the appointment time as `intake_utc`; this is permitted only while the patient is in `REFERRED` status (otherwise `ERR_PATIENT_STATE_INVALID`), and the supplied `intake_utc` must be at or after the clinic's `current_utc` (otherwise `ERR_INTAKE_IN_PAST`). On success the patient's `intake_utc` is set to the supplied value.

Completing intake advances the patient from `INTAKE_SCHEDULED` to `INTAKE_COMPLETE`. This requires the patient to be in `INTAKE_SCHEDULED` (otherwise `ERR_PATIENT_STATE_INVALID`) and requires that the clinic's `current_utc` has reached or passed the patient's `intake_utc` — that is, `current_utc` is at or after `intake_utc` (otherwise `ERR_INTAKE_NOT_DUE`).

Activating the patient advances them from `INTAKE_COMPLETE` to `ACTIVE`. This requires the patient to be in `INTAKE_COMPLETE` (otherwise `ERR_PATIENT_STATE_INVALID`) and requires that at least one `TreatmentPlan` for the patient has already reached `ACTIVE`, `PROCEDURE_PATH`, or `MEDICATION_PATH` (otherwise `ERR_NO_ACTIVE_PLAN`). A patient with no live plan cannot enter active care.

### 3.3. Treatment Plans and the Procedure/Medication Fork

A `Prescriber` proposes a `TreatmentPlan` for a patient by supplying the `modality`, which must be one of `INJECTION`, `RFA`, or `MEDICATION`; any other value is an invalid enum value. From the modality the system derives two booleans: `requires_procedure` is true for `INJECTION` and `RFA` and false otherwise, and `requires_medication` is true for `MEDICATION` and false otherwise. Each plan carries its `patient_id`. A new plan starts in `PROPOSED`.

The plan is a branching fork-join machine. Approving a proposed plan moves it from `PROPOSED` to `ACTIVE`, permitted only while the plan is `PROPOSED` (otherwise `ERR_PLAN_STATE_INVALID`). Routing an `ACTIVE` plan sends it onto exactly one branch. If the plan is a procedure-path plan (`requires_procedure` is true), routing moves it from `ACTIVE` to `PROCEDURE_PATH`, and only from that point may procedures reference the plan. If instead the plan is a medication plan (`requires_medication` is true), routing moves it from `ACTIVE` to `MEDICATION_PATH`, and only from that point may prescriptions reference the plan. Both routing branches require the plan to be `ACTIVE` (otherwise `ERR_PLAN_STATE_INVALID`); the procedure branch additionally requires `requires_procedure` to be true, and the medication branch additionally requires `requires_medication` to be true, and a mismatch between the requested branch and the plan's modality is rejected with `ERR_PLAN_MODALITY_MISMATCH`.

The two branches rejoin at completion. Completing a procedure-path plan moves it from `PROCEDURE_PATH` to `COMPLETED`, but only if every procedure referencing that plan is already `COMPLETED` or `CANCELLED` (otherwise `ERR_OPEN_PROCEDURES_EXIST`); the plan must be in `PROCEDURE_PATH` to attempt this (otherwise `ERR_PLAN_STATE_INVALID`). Symmetrically, completing a medication-path plan moves it from `MEDICATION_PATH` to `COMPLETED`, but only if every prescription referencing that plan is already `DISCONTINUED` (otherwise `ERR_OPEN_PRESCRIPTIONS_EXIST`); the plan must be in `MEDICATION_PATH` to attempt this (otherwise `ERR_PLAN_STATE_INVALID`).

### 3.4. Opioid Agreements and PDMP Checks

Before high-MED opioids can flow, two compliance artifacts must be in place. A `Prescriber` drafts an `OpioidAgreement` for a patient by supplying the `patient_id` and the `prescriber_id` of the provider who will counter-sign; the agreement is created in `DRAFT` with `signed_utc` and `expires_utc` both unset.

Counter-signing moves the agreement from `DRAFT` to `ACTIVE`. It is permitted only while the agreement is `DRAFT` (otherwise `ERR_AGREEMENT_STATE_INVALID`), and the acting prescriber's own `Provider.id` (that is, `X-User-ID`) must equal the agreement's `prescriber_id` (otherwise `ERR_NOT_AGREEMENT_PRESCRIBER`). On success the system stamps `signed_utc` with the clinic's `current_utc` and sets `expires_utc` to `signed_utc` plus the agreement validity window of 365 days. An agreement is unexpired precisely while the clinic's `current_utc` is strictly before `expires_utc`; at the instant `current_utc` equals `expires_utc`, the agreement is `EXPIRED`. This expiry is evaluated by the system at prescription-activation time — an `ACTIVE` agreement whose `expires_utc` the clock has reached is treated as `EXPIRED` — and no separate action is required to age it out.

A `ComplianceOfficer` may revoke an `ACTIVE` agreement, moving it from `ACTIVE` to `REVOKED`; this is permitted only while the agreement is `ACTIVE` (otherwise `ERR_AGREEMENT_STATE_INVALID`). Revocation cascades: every `ACTIVE` or `TAPERING` opioid prescription for that agreement's patient is moved to `SUSPENDED`. Each such suspension moves that prescription's `provisional_daily_med_mg` out of the ledger's `total_active_med_mg` and into `suspended_med_mg`, and the ledger recompute re-derives the patient's `current_daily_med_mg`. Every prescription and the ledger touched by this cascade has its `updated_at` refreshed and `version` incremented.

Separately, a `Prescriber` records a `PdmpCheck` — a query against the state PDMP database — by supplying the `patient_id`, the `queried_by_provider_id` (the prescriber who ran the query), an optional `outside_med_mg` reporting the out-of-clinic daily MED the database returned (a non-negative number defaulting to 0), and the `outcome`, which must be either `CLEAR` or `CONCERN`, where `CONCERN` indicates overlapping outside prescriptions; any other outcome value is an invalid enum value. The system stamps `queried_utc` with the clinic's `current_utc` at query time. A PDMP check is considered fresh while the clinic's `current_utc` is strictly before `queried_utc` plus the freshness window; freshness is what the prescription-activation gate consults.

### 3.5. Prescriptions, the MED Ledger, and the Taper Cycle

A `Prescriber` proposes a `Prescription` for a patient by supplying the `prescriber_id`, an optional `prior_auth_id`, the `drug_name`, the per-unit `dose_mg`, the `units_per_day`, the drug's `conversion_factor` (its MED conversion factor, for example 1.5 for oxycodone), the `day_supply`, the `pills_dispensed`, and an optional `taper_step_pct`. Each prescription carries its `patient_id`. At proposal time the system computes `provisional_daily_med_mg` as the projected steady-state daily MED assuming the full prescribed schedule is taken every day for the whole `day_supply`: it is the product of `dose_mg`, `units_per_day`, and `conversion_factor`, rounded to two decimal places. A new prescription starts in `PROPOSED`; its `final_daily_med_mg` begins unset.

Activating a prescription moves it from `PROPOSED` to `ACTIVE` and requires the prescription to be `PROPOSED` (otherwise `ERR_RX_STATE_INVALID`). Activation is where the controlled-substance safety gates fire, but only for a controlled prescription whose `provisional_daily_med_mg` is at or above the clinic's `med_review_threshold_mg`. For such a prescription, three gates apply, and below the threshold none of them apply. First, an `OpioidAgreement` for the patient must be `ACTIVE` and unexpired (otherwise `ERR_OPIOID_AGREEMENT_REQUIRED`). Second, a fresh `PdmpCheck` must exist for the patient — one whose `queried_utc` plus the freshness window still lies strictly ahead of the clinic's `current_utc` (otherwise `ERR_PDMP_CHECK_REQUIRED`). Third, the supplied `prior_auth_id` must reference an `APPROVED` `PriorAuthorization` whose `target_kind` is `PRESCRIPTION` (otherwise `ERR_PRIOR_AUTH_NOT_APPROVED`), and that authorization's `authorized_units` must be at least the requested `day_supply` (otherwise `ERR_AUTHORIZED_UNITS_EXCEEDED`). Independently of the MED threshold, activating an opioid prescription for a patient whose `compliance_flag` is `FLAGGED` is refused with `ERR_PATIENT_FLAGGED`; such a patient must be cleared first. On successful activation the prescription's `provisional_daily_med_mg` is added to the ledger's `total_active_med_mg`, and the patient's `current_daily_med_mg` is recomputed.

The prescription machine is cyclic around tapering. Starting a taper moves an `ACTIVE` prescription to `TAPERING`; this requires the prescription to be `ACTIVE` (otherwise `ERR_RX_STATE_INVALID`) and requires `taper_step_pct` to be present and strictly greater than 0 and at most 100 (otherwise `ERR_TAPER_STEP_INVALID`). Re-escalating returns a `TAPERING` prescription to `ACTIVE`, permitted only while the prescription is `TAPERING` (otherwise `ERR_RX_STATE_INVALID`). A prescription may also be suspended automatically by the system as part of the opioid-agreement revocation cascade or the inconsistent-screen cascade; suspension applies to a prescription that is `ACTIVE` or `TAPERING` and moves its `provisional_daily_med_mg` from `total_active_med_mg` to `suspended_med_mg`, then recomputes the patient's `current_daily_med_mg`.

Discontinuation is the terminal transition and may be requested from `ACTIVE`, `TAPERING`, or `SUSPENDED`; from any other state it is rejected with `ERR_RX_STATE_INVALID`. On discontinuation the system computes `final_daily_med_mg` chronologically from the actual elapsed course. It first determines the elapsed whole days as the number of whole 86,400-second days between the prescription's creation time and the clinic's `current_utc`, taking the floor and then the larger of that value and 1 so at least one day is counted; it then caps this at `day_supply`, taking the smaller of the elapsed days and `day_supply` to obtain the effective days. The `final_daily_med_mg` is `provisional_daily_med_mg` scaled by the fraction of effective days over `day_supply`, rounded to two decimal places. Because a prescription discontinued before its full course elapses is scaled below unity, its `final_daily_med_mg` is lower than its `provisional_daily_med_mg` for identical dose inputs; the two are equal only when the full course has elapsed. Discontinuation is a compensating ledger move: the prescription's `provisional_daily_med_mg` is moved out of whichever account currently holds it — `total_active_med_mg` if the prescription was `ACTIVE` or `TAPERING`, or `suspended_med_mg` if it was `SUSPENDED` — and into `discontinued_med_mg`, after which the patient's `current_daily_med_mg` is recomputed. The three-account sum remains invariant across the move.

### 3.6. Prior Authorizations

A `PriorAuthClerk` submits a `PriorAuthorization` for a patient, supplying the polymorphic `target_kind` — either `PROCEDURE` or `PRESCRIPTION`, any other value being an invalid enum value — the `payer` name, and the `authorized_units`, which for a prescription target represents an authorized day-supply and for a procedure target represents an authorized procedure count. Each authorization carries its `patient_id` and starts in `SUBMITTED`.

Deciding an authorization moves it from `SUBMITTED` to either `APPROVED` or `DENIED` according to the supplied `decision`; either outcome requires the authorization to be `SUBMITTED` (otherwise `ERR_PA_STATE_INVALID`). An invalid `decision` enum value is rejected as an invalid enum value. Downstream, a procedure schedule consumes an authorization whose `target_kind` is `PROCEDURE`, and a prescription activation consumes one whose `target_kind` is `PRESCRIPTION`; in each case the authorization must be `APPROVED` and its `target_kind` must match the operation (otherwise `ERR_PRIOR_AUTH_NOT_APPROVED`), and its `authorized_units` must be at least the requested units — the `day_supply` for a prescription, or 1 for a procedure — with a shortfall rejected as `ERR_AUTHORIZED_UNITS_EXCEEDED`.

### 3.7. Procedure Scheduling in the Fluoroscopy Suite

An `IntakeCoordinator` requests a `Procedure` against a procedure-path plan. The request supplies the `treatment_plan_id` of the plan the procedure belongs to, the `suite_id` of the fluoroscopy suite, the `prior_auth_id` of the authorizing prior authorization, the `start_utc` at which the procedure begins (inclusive), and the `duration_minutes`; the procedure's end is `start_utc` plus `duration_minutes` and is treated as exclusive. Each procedure carries its `patient_id` and starts in `REQUESTED`.

Scheduling a requested procedure moves it from `REQUESTED` to `SCHEDULED` and is the system's most heavily guarded transition. Because suite capacity is a clinic-wide shared resource, the request must carry `expected_clinic_version` matching the clinic's current `version`, checked first; a mismatch is rejected with `ERR_STALE_CLINIC_VERSION` as described in Section 2.11. The procedure must be in `REQUESTED` (otherwise `ERR_PROCEDURE_STATE_INVALID`). The referenced `PriorAuthorization` must be `APPROVED` with `target_kind` `PROCEDURE` (otherwise `ERR_PRIOR_AUTH_NOT_APPROVED`), and because a procedure consumes a single unit, the authorization's `authorized_units` must be at least 1 (otherwise `ERR_AUTHORIZED_UNITS_EXCEEDED`). The referenced `TreatmentPlan` must be on `PROCEDURE_PATH` (otherwise `ERR_PLAN_NOT_ON_PROCEDURE_PATH`).

The final gate is the suite time-conflict check. The system treats each scheduled procedure as occupying a half-open, cleanup-buffered interval: the interval begins at the procedure's `start_utc` and ends at `start_utc` plus `duration_minutes` plus the suite's `cleanup_buffer_minutes`, with the end excluded. The requested procedure conflicts with an existing `SCHEDULED` procedure in the same suite when the requested start falls strictly before the existing procedure's buffered end and the existing procedure's start falls strictly before the requested procedure's buffered end. Any such overlap is rejected with `ERR_SUITE_TIME_CONFLICT`. When scheduling succeeds, the suite's `booked_minutes` is increased by the procedure's `duration_minutes`, and the clinic's `version` is incremented by one.

Completing a scheduled procedure moves it from `SCHEDULED` to `COMPLETED`; this requires the procedure to be `SCHEDULED` (otherwise `ERR_PROCEDURE_STATE_INVALID`) and requires the clinic's `current_utc` to have reached or passed the procedure's `start_utc` (otherwise `ERR_PROCEDURE_NOT_STARTED`). On completion the suite's `booked_minutes` is decreased by the procedure's `duration_minutes`. Cancelling a procedure is permitted while it is either `SCHEDULED` or `REQUESTED` (otherwise `ERR_PROCEDURE_STATE_INVALID`) and moves it to `CANCELLED`; if the procedure was `SCHEDULED`, cancellation is a compensating action that decreases the suite's `booked_minutes` by the procedure's `duration_minutes`, leaving `booked_minutes` unchanged across a schedule-then-cancel pair, whereas cancelling a merely `REQUESTED` procedure touches no suite booking because none was ever taken.

### 3.8. Urine Drug Screens and the Recollect Loop

A `ComplianceOfficer` schedules a `UrineDrugScreen` for a patient by supplying the `due_utc` at which the screen should be collected and the `expected_substances` — the substances that should be present given the patient's active prescriptions. The screen carries its `patient_id`, starts in `SCHEDULED` with `collected_utc` unset, `detected_substances` unset, and `recollect_count` at 0. Each patient's `open_uds_count` reflects the number of that patient's screens currently in `SCHEDULED` or `COLLECTED` state.

An `IntakeCoordinator` collects a scheduled screen, moving it from `SCHEDULED` to `COLLECTED`; this requires the screen to be `SCHEDULED` (otherwise `ERR_UDS_STATE_INVALID`) and requires the clinic's `current_utc` to have reached or passed the screen's `due_utc` (otherwise `ERR_UDS_NOT_DUE`). On collection the screen's `collected_utc` is set to the clinic's `current_utc`.

A `ComplianceOfficer` results a collected screen by supplying the `detected_substances` actually found. Resulting requires the screen to be `COLLECTED` (otherwise `ERR_UDS_STATE_INVALID`); the server then compares the detected set against the expected set. If the set of `detected_substances` equals the set of `expected_substances`, the screen moves from `COLLECTED` to `RESULTED_CONSISTENT` with no further effect. If the two sets differ, the screen moves from `COLLECTED` to `RESULTED_INCONSISTENT` and triggers a compliance cascade: the patient's `compliance_flag` is set to `FLAGGED`, and that flagging then suspends each `ACTIVE` or `TAPERING` opioid prescription for the patient, moving each such prescription's `provisional_daily_med_mg` from the ledger's `total_active_med_mg` to `suspended_med_mg` and recomputing the patient's `current_daily_med_mg`. Every prescription and the ledger touched by this cascade has its `updated_at` refreshed and `version` incremented.

An inconsistent screen can be recollected, closing the cyclic loop: recollection moves the screen from `RESULTED_INCONSISTENT` back to `SCHEDULED`, permitted only while the screen is `RESULTED_INCONSISTENT` (otherwise `ERR_UDS_STATE_INVALID`). Recollection increments the screen's `recollect_count` by one, resets its `detected_substances` to unset, and takes a fresh `due_utc` supplied on the request.

### 3.9. Pill-Count Audits and the Dual Expectation

A `ComplianceOfficer` performs a `PillCountAudit` against a specific prescription by supplying the `prescription_id` being counted, the `audit_utc` at which the count was performed, and the `counted_pills` physically found in the bottle. The audit carries its `patient_id`. At creation the system computes two independent expectations of how many pills should remain, and they can differ.

Both expectations start from the same elapsed-day basis: the number of whole 86,400-second days between the prescription's creation time and the audit's `audit_utc`, floored and floored again at 0 so it is never negative, then capped at the prescription's `day_supply` by taking the smaller of the two. The forward-looking expectation, `expected_pills_forward`, is the `pills_dispensed` minus the product of the fractional `units_per_day` and the capped elapsed days, rounded once at the end to two decimal places. The chronological expectation, `expected_pills_chronological`, instead consumes whole pills day by day: each elapsed day consumes the ceiling of `units_per_day` whole pills, and these per-day whole-pill amounts are summed across the capped elapsed days, so `expected_pills_chronological` equals `pills_dispensed` minus the ceiling of `units_per_day` multiplied by the capped elapsed days. When `units_per_day` is fractional, the per-day ceiling makes the chronological consumption exceed the forward consumption, so the two expectations diverge; only when `units_per_day` is already a whole number do they coincide.

The compliance decision uses the chronological value, not the forward one. The audit's `discrepancy_pills` is the absolute difference between `expected_pills_chronological` and `counted_pills`. The `result` is `CONSISTENT` when `discrepancy_pills` is at or below the clinic's `pill_count_tolerance`, and `INCONSISTENT` otherwise. An `INCONSISTENT` result triggers the same compliance cascade as an inconsistent screen: the patient's `compliance_flag` is set to `FLAGGED`, each `ACTIVE` or `TAPERING` opioid prescription for the patient is suspended, each such prescription's `provisional_daily_med_mg` is moved from the ledger's `total_active_med_mg` to `suspended_med_mg`, and the patient's `current_daily_med_mg` is recomputed, with `updated_at` and `version` refreshed on every prescription and the ledger touched.

### 3.10. Clearing Flags, Discharge, and Segregation of Duties

Clearing a flagged patient is reserved to a `ComplianceOfficer` and, by segregation of duties, must be a distinct provider from the prescriber who wrote the suspended prescriptions; the entity-backed identities described in Section 2.1 anchor that separation. Clearing sets the patient's `compliance_flag` to `CLEARED`, which re-opens the patient to opioid activation that the `FLAGGED` state had blocked.

Discharge is the patient's terminal transition and is reserved to a `Prescriber`. It moves the patient from `ACTIVE` to `DISCHARGED` and requires the patient to be `ACTIVE` (otherwise `ERR_PATIENT_STATE_INVALID`). Discharge is blocked while any prescription for the patient is still `ACTIVE` or `SUSPENDED` (otherwise `ERR_ACTIVE_PRESCRIPTIONS_EXIST`) — the taper-and-discharge workflow requires those prescriptions to be discontinued first. On a permitted discharge the system runs a cascade: every procedure for the patient that is still `REQUESTED` or `SCHEDULED` is moved to `CANCELLED`, and each cancelled procedure that had been `SCHEDULED` debits its suite by decreasing that suite's `booked_minutes` by the procedure's `duration_minutes`; additionally, every treatment plan for the patient that is not already in a terminal state is moved to `CANCELLED`. Each resource touched by the discharge cascade has its `updated_at` refreshed and `version` incremented.

The patient's controlled-substance ledger remains readable throughout, giving prescribers and compliance officers a reverse view of the MED accounting for reconciliation and audit.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock set — return `200 OK`. All list and single-resource reads return `200 OK`. Request bodies, response payloads, and side effects for each operation are governed by the narratives in Section 3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinics` | Create a clinic | ClinicAdmin |
| GET | `/clinics/{clinicId}` | Get a clinic | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| POST | `/_clock/set_current_utc` | Set a clinic's logical clock (test-driving) | ClinicAdmin |
| POST | `/clinics/{clinicId}/providers` | Create a provider | ClinicAdmin |
| GET | `/clinics/{clinicId}/providers` | List providers for a clinic | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients` | Register a referral | IntakeCoordinator |
| GET | `/clinics/{clinicId}/patients` | List patients for a clinic | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/clinics/{clinicId}/patients/{patientId}` | Get a patient | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/schedule-intake` | Schedule intake appointment | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/complete-intake` | Complete intake | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/activate` | Activate patient into care | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/discharge` | Discharge a patient | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/clear-flag` | Clear a flagged patient | ComplianceOfficer |
| GET | `/clinics/{clinicId}/patients/{patientId}/controlled-substance-ledger` | Read the patient's MED ledger | ClinicAdmin, Prescriber, ComplianceOfficer |
| POST | `/clinics/{clinicId}/opioid-agreements` | Draft an opioid agreement | Prescriber |
| GET | `/clinics/{clinicId}/opioid-agreements` | List opioid agreements | ClinicAdmin, Prescriber, ComplianceOfficer |
| POST | `/clinics/{clinicId}/opioid-agreements/{agreementId}/counter-sign` | Counter-sign an agreement | Prescriber |
| POST | `/clinics/{clinicId}/opioid-agreements/{agreementId}/revoke` | Revoke an active agreement | ComplianceOfficer |
| POST | `/clinics/{clinicId}/pdmp-checks` | Record a PDMP query | Prescriber |
| GET | `/clinics/{clinicId}/pdmp-checks` | List PDMP checks | ClinicAdmin, Prescriber, ComplianceOfficer |
| POST | `/clinics/{clinicId}/patients/{patientId}/treatment-plans` | Create a treatment plan | Prescriber |
| GET | `/clinics/{clinicId}/patients/{patientId}/treatment-plans` | List a patient's treatment plans | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/treatment-plans/{planId}/approve` | Approve a proposed plan | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/treatment-plans/{planId}/route` | Route an active plan onto its branch | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/treatment-plans/{planId}/complete` | Complete a plan at the fork-join | Prescriber |
| POST | `/clinics/{clinicId}/fluoroscopy-suites` | Create a fluoroscopy suite | ClinicAdmin |
| GET | `/clinics/{clinicId}/fluoroscopy-suites` | List fluoroscopy suites | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/prior-authorizations` | Submit a prior authorization | PriorAuthClerk |
| GET | `/clinics/{clinicId}/patients/{patientId}/prior-authorizations` | List a patient's prior authorizations | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/prior-authorizations/{paId}/decide` | Approve or deny a prior authorization | PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/procedures` | Request a procedure | IntakeCoordinator |
| GET | `/clinics/{clinicId}/patients/{patientId}/procedures` | List a patient's procedures | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/procedures/{procedureId}/schedule` | Schedule a requested procedure | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/procedures/{procedureId}/complete` | Complete a scheduled procedure | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/procedures/{procedureId}/cancel` | Cancel a procedure | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/prescriptions` | Propose a prescription | Prescriber |
| GET | `/clinics/{clinicId}/patients/{patientId}/prescriptions` | List a patient's prescriptions | ClinicAdmin, Prescriber, ComplianceOfficer, PriorAuthClerk |
| POST | `/clinics/{clinicId}/patients/{patientId}/prescriptions/{rxId}/activate` | Activate a proposed prescription | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/prescriptions/{rxId}/start-taper` | Begin tapering a prescription | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/prescriptions/{rxId}/re-escalate` | Return a tapering prescription to active | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/prescriptions/{rxId}/discontinue` | Discontinue a prescription | Prescriber |
| POST | `/clinics/{clinicId}/patients/{patientId}/urine-drug-screens` | Schedule a urine drug screen | ComplianceOfficer |
| GET | `/clinics/{clinicId}/patients/{patientId}/urine-drug-screens` | List a patient's urine drug screens | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer |
| POST | `/clinics/{clinicId}/patients/{patientId}/urine-drug-screens/{udsId}/collect` | Collect a scheduled screen | IntakeCoordinator |
| POST | `/clinics/{clinicId}/patients/{patientId}/urine-drug-screens/{udsId}/result` | Result a collected screen | ComplianceOfficer |
| POST | `/clinics/{clinicId}/patients/{patientId}/urine-drug-screens/{udsId}/recollect` | Recollect after an inconsistent result | ComplianceOfficer |
| POST | `/clinics/{clinicId}/patients/{patientId}/pill-count-audits` | Perform a pill-count audit | ComplianceOfficer |
| GET | `/clinics/{clinicId}/patients/{patientId}/pill-count-audits` | List a patient's pill-count audits | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/providers/{providerId}` | Get a provider by id | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/providers` | List providers, optionally by clinic | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/patients/{patientId}` | Get a patient by id | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/patients` | List patients, optionally by clinic or status | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/prescriptions/{prescriptionId}` | Get a prescription by id | ClinicAdmin, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/prescriptions` | List prescriptions by patient, prescriber, or prior-auth | ClinicAdmin, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/prior-authorizations/{paId}` | Get a prior authorization by id | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/prior-authorizations` | List prior authorizations by patient | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/opioid-agreements` | List opioid agreements by clinic, patient, or prescriber | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/opioid-agreements/{agreementId}` | Get an opioid agreement by id | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/pdmp-checks` | List PDMP checks by clinic, patient, or querying provider | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/pdmp-checks/{pdmpCheckId}` | Get a PDMP check by id | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/treatment-plans` | List treatment plans by patient | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/treatment-plans/{planId}` | Get a treatment plan by id | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer, PriorAuthClerk |
| GET | `/fluoroscopy-suites` | List fluoroscopy suites by clinic | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/fluoroscopy-suites/{suiteId}` | Get a fluoroscopy suite by id | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/procedures` | List procedures by patient, suite, plan, or prior-auth | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/procedures/{procedureId}` | Get a procedure by id | ClinicAdmin, IntakeCoordinator, Prescriber, PriorAuthClerk |
| GET | `/urine-drug-screens` | List urine drug screens by patient | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer |
| GET | `/urine-drug-screens/{udsId}` | Get a urine drug screen by id | ClinicAdmin, IntakeCoordinator, Prescriber, ComplianceOfficer |
| GET | `/pill-count-audits` | List pill-count audits by patient or prescription | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/pill-count-audits/{auditId}` | Get a pill-count audit by id | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/controlled-substance-ledger` | List controlled-substance ledgers by patient | ClinicAdmin, Prescriber, ComplianceOfficer |
| GET | `/controlled-substance-ledger/{ledgerId}` | Get a controlled-substance ledger by id | ClinicAdmin, Prescriber, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 422 Unprocessable Entity |
| `ERR_CLINIC_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_TREATMENT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SUITE_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_NOT_FOUND` | 404 Not Found |
| `ERR_PRIOR_AUTH_NOT_FOUND` | 404 Not Found |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_UDS_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CLINIC_VERSION` | 412 Precondition Failed |
| `ERR_PATIENT_STATE_INVALID` | 409 Conflict |
| `ERR_AGREEMENT_STATE_INVALID` | 409 Conflict |
| `ERR_PLAN_STATE_INVALID` | 409 Conflict |
| `ERR_PA_STATE_INVALID` | 409 Conflict |
| `ERR_PROCEDURE_STATE_INVALID` | 409 Conflict |
| `ERR_RX_STATE_INVALID` | 409 Conflict |
| `ERR_UDS_STATE_INVALID` | 409 Conflict |
| `ERR_INTAKE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INTAKE_NOT_DUE` | 409 Conflict |
| `ERR_UDS_NOT_DUE` | 409 Conflict |
| `ERR_PROCEDURE_NOT_STARTED` | 409 Conflict |
| `ERR_SUITE_TIME_CONFLICT` | 409 Conflict |
| `ERR_NO_ACTIVE_PLAN` | 409 Conflict |
| `ERR_PLAN_MODALITY_MISMATCH` | 409 Conflict |
| `ERR_PLAN_NOT_ON_PROCEDURE_PATH` | 409 Conflict |
| `ERR_PRIOR_AUTH_NOT_APPROVED` | 409 Conflict |
| `ERR_OPEN_PROCEDURES_EXIST` | 409 Conflict |
| `ERR_OPEN_PRESCRIPTIONS_EXIST` | 409 Conflict |
| `ERR_NOT_AGREEMENT_PRESCRIBER` | 403 Forbidden |
| `ERR_OPIOID_AGREEMENT_REQUIRED` | 403 Forbidden |
| `ERR_PDMP_CHECK_REQUIRED` | 403 Forbidden |
| `ERR_PATIENT_FLAGGED` | 403 Forbidden |
| `ERR_TAPER_STEP_INVALID` | 422 Unprocessable Entity |
| `ERR_ACTIVE_PRESCRIPTIONS_EXIST` | 409 Conflict |
| `ERR_AUTHORIZED_UNITS_EXCEEDED` | 402 Payment Required |
