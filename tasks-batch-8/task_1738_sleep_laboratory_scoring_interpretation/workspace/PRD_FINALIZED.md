# Sleep Lab Scoring API — Product Requirements Document

## 1. Introduction

An AASM-accredited sleep laboratory operates as a chain of custody for clinical evidence: a referral arrives, insurance authorizes a fixed number of nights, a technologist staffs the night and runs the acquisition, a scorer stages the recording epoch by epoch, a physician interprets the accepted scoring against turnaround SLAs, and — where therapy is indicated — a prescription is handed off to a durable medical equipment vendor whose adherence follow-up closes the loop. Each handoff in that chain is a place where quality, compliance, or revenue can be silently lost.

This document specifies the Sleep Lab Scoring API, the system of record for that chain. It governs study scheduling for in-lab and home study types with insurance authorization windows and approved-nights quotas, technologist night staffing with capacity enforcement, raw study scoring with a formal inter-rater reliability program, the physician interpretation queue with business- and calendar-hours turnaround accounting, split-night protocol decision rules, therapy titration pressure recommendations, prescription generation, DME order dispatch and adherence follow-up, and the accreditation-facing quality metrics that the medical director must report.

Two design commitments run through every workflow. First, segregation of duties is enforced mechanically: the scorer who staged a study may not be the physician who signs its interpretation, reliability rescoring is always performed by a different scorer than the primary, and ownership rules bind technologists, scorers, and physicians to their own work items. Second, all time in the system is logical: every server-stamped timestamp reads a controllable logical clock rather than the wall clock, so that authorization expiry, turnaround measurement, and scheduled-date checks are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly six roles: `Scheduler`, `SleepTechnologist`, `Scorer`, `InterpretingPhysician`, `DmeCoordinator`, and `LabDirector`. Each operation is restricted to a designated set of roles (enumerated per endpoint in §4); an authenticated caller whose role is not permitted for the operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `SleepTechnologist`, `X-User-ID` is the `id` of the acting Technologist; ownership checks on any resource that references a Technologist compare the resource's `technologist_id` field to `X-User-ID`. When `X-User-Role` is `Scorer`, `X-User-ID` is the `id` of the acting Scorer, compared against a task's `scorer_id`. When `X-User-Role` is `InterpretingPhysician`, `X-User-ID` is the `id` of the acting Physician; it is captured as the authoring `physician_id` when a report is created, and later report and prescription actions compare against that stored author. When `X-User-Role` is `Scheduler`, `DmeCoordinator`, or `LabDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Laboratory Time

All server-stamped timestamps in the system — including `created_at`, `updated_at`, `decided_at`, `confirmed_at`, `acquisition_completed_at`, `submitted_at`, `signed_at`, `finalized_at`, `ordered_at`, `dispatched_at`, `delivered_at`, and `adjudicated_at` — read a single logical clock, never the wall clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it advances only when a `LabDirector` invokes the administrative clock-setting capability with a `to_iso8601` instant; the response echoes the new logical time as `current_utc`. Before any such call, the clock continues to read the startup default.

Every calendar-date comparison in the system — a study's `scheduled_date`, an authorization's `window_start` and `window_end`, a staffing assignment's `shift_date` — is evaluated against the UTC calendar date of the logical clock. Advancing the clock has one systemic side effect: when the logical date passes the `window_end` of an `APPROVED` authorization whose parent order is `AUTHORIZED`, the authorization transitions to `EXPIRED` and the parent order transitions to `EXPIRED` with it.

### 2.5. Common Resource Properties

Every resource in the system — Patient, ReferralOrder, InsuranceAuthorization, Bed, Technologist, Scorer, Physician, StaffingAssignment, SleepStudy, ScoringTask, InterpretationReport, TherapyPrescription, DmeOrder, and InterRaterCase — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (§2.7).

System-driven mutations count as mutations: when a cascade described in §2.8 or §3 changes a resource, that resource's `updated_at` refreshes and its `version` increments.

### 2.6. Numeric Precision and Rounding Conventions

The laboratory computes several families of derived numbers, each with a pinned precision:

- **Respiratory indexes** (`ahi`, `rdi`, `rei`, and the study-level snapshots derived from them) are rounded to exactly 1 decimal place using round-half-up — so 11.25 becomes 11.3, and banker's rounding is never used.
- **Inter-rater agreement metrics** (`ahi_delta`, `percent_agreement`, `rolling_agreement_index`) use 2 decimal places, round-half-up. The rounding is applied per case before any rolling mean is computed: the rolling index averages the per-case `percent_agreement` values exactly as stored (each already rounded to 2 decimals), then rounds that mean half-up to 2 decimals. Averaging raw unrounded ratios instead is a violation of this contract.
- **Turnaround measurements** (`turnaround_business_hours`, `turnaround_calendar_hours`) accumulate whole minutes, divide by 60, and round half-up to 1 decimal place.
- **Pressure recommendations** (`recommended_cpap_cm`) are rounded to the nearest 0.5 cm H2O step, round-half-up — so 11.26 becomes 11.5 and 11.24 becomes 11.0.
- **Quality-metric percentages** are reported with 2 decimal places, round-half-up.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent aggregate before adding a child to it. The version field is a non-optional input on exactly these three operations; no other endpoint takes a version field.

- Submitting an insurance authorization against a referral order requires `expected_referral_order_version`, carrying the client's last observed `version` of the order. If the order's current `version` has advanced beyond the supplied value — for example because another authorization was created in the interim, legitimately superseding the prior one — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating an interpretation report requires `expected_sleep_study_version`, matching the study's current `version`. A report created since the client's last read legitimately supersedes a prior draft, so a stale `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a therapy prescription requires `expected_interpretation_report_version`, matching the report's current `version`; a prescription created in the interim legitimately supersedes the prior active one, so a stale `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Within the request evaluation pipeline (§2.9), the stale-version check runs after ownership checks and before the entity state preconditions.

### 2.8. Cross-Entity State Propagation

State in this system propagates across aggregate boundaries without requiring a client call on the affected resource. The propagations that recur throughout §3 are: recording a payer decision flips the parent referral order between `AUTH_IN_PROGRESS` and `AUTHORIZED` or `AUTH_DENIED`; creating a new authorization supersedes the order's prior live authorizations; completing acquisition fulfills the parent order; a no-show increments the order's `no_show_count` and may push the order into `NEEDS_PROVIDER_REVIEW`; creating a report supersedes an existing draft report for the same study; creating a prescription supersedes the report's active prescriptions and cancels their dispatched DME orders; DME delivery fulfills the parent prescription; and a scorer entering `REMEDIATION` recalls all of that scorer's open tasks, pushing affected studies back to the scoring queue. Each such propagation is an independent mutation of the affected resource, refreshing its `updated_at` and incrementing its `version` per §2.5.

### 2.9. Request Evaluation Pipeline

Every request is evaluated against a fixed pipeline of checks, and a request fails at the first check it violates. The ordering is significant: an earlier failure masks later ones, so clients always observe the highest-priority applicable error. The stages, in order, are:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and the role recognized (`ERR_UNAUTHENTICATED`).
2. **Role authorization** — the role is permitted for this endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Existence** — every referenced resource id exists, validated left-to-right: path identifiers first, then body foreign keys in declaration order (`ERR_NOT_FOUND`).
4. **Request shape** — required fields present, enum members valid, numeric ranges and steps valid: `approved_nights` between 1 and 2; `patient_capacity` between 1 and 4; `total_recording_time_minutes` at least 60; the device-specific prescription field sets for each `device_type`; `window_end` no earlier than `window_start`; patient `mrn` uniqueness; return `reason` length. The applicable errors are `ERR_INVALID_REQUEST`, `ERR_RX_DEVICE_FIELDS_INVALID`, `ERR_AUTH_WINDOW_INVALID`, `ERR_DUPLICATE_MRN`, and `ERR_INSUFFICIENT_REASON`.
5. **Ownership** — the caller owns the work item: `X-User-ID` must equal the task's `scorer_id` for start and submit (`ERR_NOT_TASK_OWNER`), the report's `physician_id` for sign, finalize, addenda, and prescription actions (`ERR_NOT_REPORT_AUTHOR`), or the assignment's `technologist_id` for confirm (`ERR_STAFFING_NOT_OWN`).
6. **Optimistic concurrency** — where §2.7 applies, `expected_referral_order_version`, `expected_sleep_study_version`, or `expected_interpretation_report_version` must match the parent's current `version` (`ERR_STALE_VERSION`); this stage runs before the state preconditions.
7. **State preconditions** — the entity state machines of §3: order authorizable or reviewable, authorization pending, staffing assignment planned, study in the correct phase, split applicable, undecided, or required, task startable, submittable, or submitted, report signable, prescription orderable, DME order actionable, reliability case open, scorer reinstatable. Errors include `ERR_ORDER_NOT_AUTHORIZABLE_STATE`, `ERR_AUTH_NOT_PENDING`, `ERR_ORDER_NOT_REVIEWABLE`, `ERR_STAFFING_INVALID_STATE`, `ERR_STUDY_NOT_IN_PROGRESS`, `ERR_SPLIT_NOT_APPLICABLE`, `ERR_SPLIT_ALREADY_DECIDED`, `ERR_SPLIT_DECISION_REQUIRED`, `ERR_STUDY_NOT_SCORABLE`, `ERR_TASK_NOT_STARTABLE`, `ERR_TASK_NOT_SUBMITTABLE`, `ERR_TASK_NOT_SUBMITTED`, `ERR_TASK_TERMINAL`, `ERR_STUDY_NOT_SCORED`, `ERR_REPORT_INVALID_STATE`, `ERR_RX_INVALID_STATE`, `ERR_DME_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_SCORER_NOT_REMEDIATION`, and `ERR_ORDER_NOT_AUTHORIZED`.
8. **Clinical safety and segregation of duties** — the split-night central-predominance exclusion, the rescorer-is-not-primary-scorer rule, and the report-signer-is-not-primary-scorer rule (`ERR_SPLIT_CENTRAL_PREDOMINANCE`, `ERR_SOD_PRIMARY_SCORER`, `ERR_SOD_REPORT_SCORER`).
9. **Referential coherence** — the study's patient matches the order's patient, the study type matches the order's requested type, bed presence rules by study type, bed active and titration-capable where required, scorer active and pool membership for rescores, tasks belong to the named study, case tasks reference the same study with the correct kinds, and the report's primary task is the study's accepted primary (`ERR_STUDY_TYPE_MISMATCH`, `ERR_BED_REQUIRED_FOR_IN_LAB`, `ERR_BED_NOT_ALLOWED_FOR_HST`, `ERR_BED_INACTIVE`, `ERR_BED_NOT_TITRATION_CAPABLE`, `ERR_SCORER_NOT_IN_POOL`, `ERR_SCORER_IN_REMEDIATION`, `ERR_INVALID_PRIMARY_TASK`, `ERR_CASE_TASKS_INVALID`, `ERR_THERAPY_NOT_INDICATED`).
10. **Temporal windows** — the `scheduled_date` falls inside the approved authorization window, and check-in happens on the scheduled night per the logical clock (`ERR_AUTH_WINDOW_VIOLATION`, `ERR_STUDY_NOT_TONIGHT`).
11. **Resource conflicts and uniqueness** — bed-night pairwise exclusion, one non-cancelled staffing assignment per technologist per night, one non-terminal primary scoring task per study, one non-terminal DME order per prescription, one reliability case per rescore task (`ERR_BED_NIGHT_CONFLICT`, `ERR_TECH_DOUBLE_BOOKED`, `ERR_PRIMARY_TASK_EXISTS`, `ERR_DME_ORDER_ACTIVE`, `ERR_CASE_ALREADY_EXISTS`).
12. **Aggregate capacity** — confirmed technologist capacity covers the night's scheduled in-lab studies, both when scheduling and when cancelling a confirmed assignment (`ERR_CAPACITY_EXCEEDED`, `ERR_CAPACITY_WOULD_BE_VIOLATED`).
13. **Authorized-nights quota** — the order still has unconsumed approved nights (`ERR_AUTH_NIGHTS_EXHAUSTED`).

### 2.10. Referenced-Resource Existence Checks

Whenever a request references resources by identifier — whether in the URL path or in the request body — existence is validated left-to-right: path parameters first, in the order they appear in the path, then body foreign-key fields in their declaration order. The first identifier that does not correspond to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), and no later validation stage runs.

## 3. Business Logic & Workflows

### 3.1. Patient Registration and Referral Intake

A `Scheduler` registers each patient with a medical record number `mrn`, the patient's `full_name`, and `date_of_birth` as an ISO calendar date. The `mrn` must be unique across the laboratory; registering a duplicate is rejected with `ERR_DUPLICATE_MRN`.

Against a registered patient, the `Scheduler` opens a **ReferralOrder** by supplying the `patient_id`, the `ordering_provider_name`, the `requested_study_type` — one of `PSG_DIAGNOSTIC`, `HST`, `SPLIT_NIGHT`, or `TITRATION_PAP` — and the primary referral diagnosis `icd10_primary`. An optional `priority` defaults to `ROUTINE`; marking the order `STAT` switches its turnaround service level from the business-hours variant to the calendar-hours variant (see §3.6). A new order begins in `RECEIVED` status with its `no_show_count` at zero, and orders may be listed filtered by `patient_id` or `status`.

Cancelling an order is possible from every non-terminal state. From `RECEIVED`, `AUTH_IN_PROGRESS`, `AUTHORIZED`, or `SCHEDULED`, cancellation is blocked while a linked study is `IN_PROGRESS` (`ERR_ORDER_HAS_ACTIVE_STUDY`); when it proceeds, any live authorization in `SUBMITTED` or `APPROVED` is withdrawn (transitioned to `WITHDRAWN`), and — from `RECEIVED` or `SCHEDULED` — any linked study still in `SCHEDULED` is transitioned to `CANCELLED`. From `AUTH_DENIED`, cancellation succeeds unconditionally with no cascading effects. `FULFILLED`, `CANCELLED`, and `EXPIRED` are the order's terminal states.

### 3.2. Insurance Authorization and the Approved-Nights Quota

Before a study can be scheduled, the payer must authorize it. A `Scheduler` submits an **InsuranceAuthorization** against an order whose `status` is `RECEIVED`, `AUTH_DENIED`, or `AUTHORIZED` — any other state is rejected with `ERR_ORDER_NOT_AUTHORIZABLE_STATE`. The submission carries the `payer_name`, the payer-issued `authorization_number`, the number of `approved_nights` (one or two), and the authorized service window `window_start` through `window_end`, both inclusive calendar dates; a `window_end` earlier than `window_start` is rejected with `ERR_AUTH_WINDOW_INVALID`. The submission must also carry `expected_referral_order_version` per §2.7.

Submission creates the authorization in `SUBMITTED` status, moves the order to `AUTH_IN_PROGRESS`, increments the order's `version` by one, and transitions every prior `SUBMITTED` or `APPROVED` authorization of the same order to `SUPERSEDED`. Re-authorizing an `AUTHORIZED` order therefore retires the live `APPROVED` authorization; studies already scheduled under it are grandfathered and unaffected. Authorizations may be listed filtered by `order_id` or `status`.

Recording the payer's decision requires the authorization to still be `SUBMITTED` (`ERR_AUTH_NOT_PENDING`). The authorization's `decided_at` remains null until a decision is recorded. An `outcome` of `APPROVED` stamps `decided_at` from the logical clock, transitions the authorization to `APPROVED`, and flips the order from `AUTH_IN_PROGRESS` to `AUTHORIZED`. An `outcome` of `DENIED` stamps `decided_at`, transitions the authorization to `DENIED`, and flips the order to `AUTH_DENIED`. Should the logical clock later advance past the `window_end` of an `APPROVED` authorization while the order remains `AUTHORIZED`, the authorization expires to `EXPIRED` and takes the order to `EXPIRED` with it (§2.4).

Each `APPROVED` authorization funds a fixed quota of study nights. An order's **consumed nights** are the count of its linked studies in any of `SCHEDULED`, `IN_PROGRESS`, `SCORING_QUEUED`, `SCORING_IN_PROGRESS`, `SCORED`, `INTERPRETATION_IN_PROGRESS`, `INTERPRETED`, or `REPORT_FINALIZED`; studies in `NO_SHOW`, `CANCELLED`, or `TECHNICAL_FAILURE` do not consume a night. Scheduling a new study requires the consumed count to be strictly less than the `approved_nights` of the order's `APPROVED` authorization; a request that would exceed the quota is rejected with `ERR_AUTH_NIGHTS_EXHAUSTED`.

No-shows erode the order itself. Every no-show (§3.4) increments the order's `no_show_count` by one. While the count stays below two, the order falls back from `SCHEDULED` to `AUTHORIZED` and may be rebooked. The moment the count reaches two, the order leaves `SCHEDULED` for `NEEDS_PROVIDER_REVIEW`, and further scheduling is blocked while it sits there. A `Scheduler` resolves the review with an `action`: `REINSTATE` returns the order to `AUTHORIZED` and resets `no_show_count` to zero, while `CANCEL` transitions the order to `CANCELLED` and withdraws any live `SUBMITTED` or `APPROVED` authorization. Either action on an order not in `NEEDS_PROVIDER_REVIEW` is rejected with `ERR_ORDER_NOT_REVIEWABLE`.

### 3.3. Beds, Staff Registry, and Night Coverage

The `LabDirector` maintains the laboratory's physical and human resources. Each **Bed** is registered with a unique `room_label`, a `titration_capable` flag (default false) marking beds wired for PAP titration equipment, and an `is_active` flag (default true) controlling schedulability. A **Technologist** is registered with a `full_name`, a `credential` of `RPSGT` or `CPSGT`, and an `is_active` flag defaulting to true. A **Scorer** is registered with a `full_name`, a `credential` of `RPSGT` or `RST`, a National Provider Identifier `npi` used for scorer-versus-interpreter segregation of duties, and an optional `reliability_pool` flag (default false) enrolling the scorer in the inter-rater program; a new scorer's `reliability_status` begins at `PROVISIONAL`, `consecutive_nonconcordant` at zero, and `rolling_agreement_index` stays null until at least three adjudicated cases exist (§3.8). A **Physician** is registered with a `full_name`, an `npi` compared against scoring-task scorer identifiers at report signing, a `board_certified` flag defaulting to false, and an `is_active` flag defaulting to true.

Night coverage is planned through **StaffingAssignment** records, each pairing a `technologist_id` with a `shift_date` and a `patient_capacity` — the maximum number of in-lab patients that technologist covers that night, between one and four, defaulting to two under the AASM 2:1 ratio. An assignment begins `PLANNED`, and a technologist may hold only one non-`CANCELLED` assignment per `shift_date`; a second plan for the same technologist and night is rejected with `ERR_TECH_DOUBLE_BOOKED`. Assignments may be listed filtered by `technologist_id`, `shift_date`, or `status`.

Confirmation is personal: only the assigned technologist may confirm the shift, meaning `X-User-ID` must equal the assignment's `technologist_id` (`ERR_STAFFING_NOT_OWN`), and only a `PLANNED` assignment can be confirmed (`ERR_STAFFING_INVALID_STATE`). Confirmation stamps `confirmed_at` from the logical clock — it is null until this moment — and moves the assignment to `CONFIRMED`. The `LabDirector` may cancel an assignment from `PLANNED` freely, but cancelling a `CONFIRMED` assignment is capacity-guarded: letting `c` be that assignment's `patient_capacity`, the cancellation is rejected with `ERR_CAPACITY_WOULD_BE_VIOLATED` unless the night's occupied in-lab count remains no greater than the remaining confirmed capacity after subtracting `c`. Cancelling from any other state is rejected with `ERR_STAFFING_INVALID_STATE`.

Two aggregates define a night's capacity. The **confirmed capacity** of a date is the sum of `patient_capacity` over that date's `CONFIRMED` staffing assignments. The **occupied count** of a date is the number of studies scheduled for that date that carry a `bed_id` and are in `SCHEDULED` or `IN_PROGRESS`. Scheduling an in-lab study is only permitted when the occupied count plus one does not exceed the confirmed capacity — an occupied count exactly equal to capacity means the night is full, and the scheduling attempt is rejected with `ERR_CAPACITY_EXCEEDED`. The cancel guard above is the mirror image of the same arithmetic.

### 3.4. The Study Night: Scheduling, Split-Night Decisions, and Acquisition

A `Scheduler` books a **SleepStudy** against an `AUTHORIZED` order — any other order state is rejected with `ERR_ORDER_NOT_AUTHORIZED`. The booking payload names the `patient_id`, the authorizing `order_id`, the `study_type`, the night `scheduled_date`, and, for in-lab types, the `bed_id`. The payload's `patient_id` must be the patient the order belongs to, and the `study_type` must equal the order's `requested_study_type` (`ERR_STUDY_TYPE_MISMATCH`). Bed rules depend on the type: `PSG_DIAGNOSTIC`, `SPLIT_NIGHT`, and `TITRATION_PAP` studies require a `bed_id` (`ERR_BED_REQUIRED_FOR_IN_LAB`), while an `HST` study must not carry one (`ERR_BED_NOT_ALLOWED_FOR_HST`). The referenced bed must be active (`ERR_BED_INACTIVE`), and `TITRATION_PAP` and `SPLIT_NIGHT` additionally require a `titration_capable` bed (`ERR_BED_NOT_TITRATION_CAPABLE`). Temporally, the `scheduled_date` must fall within the approved authorization's `window_start`-to-`window_end` window, inclusive on both ends; a date outside the window is rejected with `ERR_AUTH_WINDOW_VIOLATION`, and this temporal check runs before the bed-night conflict check. The bed-night itself must be free: the same `bed_id` and `scheduled_date` may not be held by another study in `SCHEDULED` or `IN_PROGRESS` (`ERR_BED_NIGHT_CONFLICT`). Finally the capacity and quota checks of §3.3 and §3.2 apply (`ERR_CAPACITY_EXCEEDED`, `ERR_AUTH_NIGHTS_EXHAUSTED`). A successful booking creates the study in `SCHEDULED` and moves the order from `AUTHORIZED` to `SCHEDULED`. Studies may be listed filtered by `patient_id`, `order_id`, `bed_id`, `status`, or `scheduled_date`.

On the night of the study, a `SleepTechnologist` checks the patient in. Check-in requires the study to be `SCHEDULED` and the logical clock's UTC calendar date to equal the `scheduled_date`; a date mismatch is rejected with `ERR_STUDY_NOT_TONIGHT`, and any other study state with `ERR_STUDY_NOT_IN_PROGRESS`. Successful check-in moves the study to `IN_PROGRESS`.

For a `SPLIT_NIGHT` study, the technologist records the protocol branch exactly once, while the study is `IN_PROGRESS`. Recording it for any other study type is rejected with `ERR_SPLIT_NOT_APPLICABLE`, and a second attempt once `split_outcome` is set is rejected with `ERR_SPLIT_ALREADY_DECIDED`. The decision payload carries the `intended_outcome` (`CONVERT_TO_TITRATION` or `CONTINUE_DIAGNOSTIC`), the `diagnostic_minutes_observed`, the `partial_ahi_observed`, a `central_predominance_flag`, the `remaining_minutes_available` in the night, and an optional `override_reason`.

An intended outcome of `CONTINUE_DIAGNOSTIC` records the branch with no eligibility gate — the four threshold inputs are still stored. An intended outcome of `CONVERT_TO_TITRATION` runs the full eligibility gate, and the gate evaluates safety before thresholds. A `central_predominance_flag` of true excludes split-night titration outright (`ERR_SPLIT_CENTRAL_PREDOMINANCE`). The diagnostic portion must have accumulated at least 120 minutes; fewer minutes are rejected with `ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET`. The partial AHI then gates conversion in three bands: at least 40.0 qualifies outright; at least 20.0 but below 40.0 qualifies only when an `override_reason` of at least ten characters accompanies the request, and without one the request is rejected with `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`; below 20.0 the request is always rejected with `ERR_SPLIT_AHI_THRESHOLD_NOT_MET`. Finally, at least 180 minutes must remain available for titration; fewer remaining minutes are rejected with `ERR_SPLIT_INSUFFICIENT_REMAINING`. An override never waives the other constraints: a partial AHI in the override band still requires at least 120 diagnostic minutes and at least 180 remaining minutes. Either outcome is stored on the study as `split_outcome`, alongside `split_diagnostic_minutes` and `split_partial_ahi` taken from the observed values; all three remain unset until the decision is recorded.

Completing the acquisition requires the study to be `IN_PROGRESS` (`ERR_STUDY_NOT_IN_PROGRESS`) and, for a `SPLIT_NIGHT` study, requires the split decision to be recorded first (`ERR_SPLIT_DECISION_REQUIRED`). Every completion supplies `total_recording_time_minutes` of at least 60 (`ERR_INVALID_REQUEST`). A `TITRATION_PAP` study — or a `SPLIT_NIGHT` study whose `split_outcome` is `CONVERT_TO_TITRATION` — must additionally supply `titration_final_pressure_cm`, the ending PAP pressure in cm H2O, together with `leak_95th_l_min`, the 95th-percentile mask leak in L/min; omitting either is rejected with `ERR_INVALID_REQUEST`. Completion stamps `acquisition_completed_at` from the logical clock — null until this moment — moves the study to `SCORING_QUEUED`, and fulfills the order (`SCHEDULED` → `FULFILLED`).

Three early exits exist for a booked night. A `Scheduler` or `SleepTechnologist` may mark a `SCHEDULED` study as a no-show, moving it to `NO_SHOW` and firing the order-level counter cascade of §3.2. A `Scheduler` may cancel a `SCHEDULED` study, moving it to `CANCELLED` and, when the order is `SCHEDULED`, returning it to `AUTHORIZED`. A `SleepTechnologist` may declare a technical failure on an `IN_PROGRESS` study, moving it to `TECHNICAL_FAILURE` and likewise returning a `SCHEDULED` order to `AUTHORIZED` so the night can be rebooked. Each requires the named starting state (`ERR_STUDY_NOT_IN_PROGRESS` otherwise).

### 3.5. Scoring Assignments and Respiratory Index Computation

Once acquisition completes, the `LabDirector` assigns scoring work. Creating a **ScoringTask** names the `study_id`, the `scorer_id`, and the `assignment_kind` — `PRIMARY` or `RELIABILITY_RESCORE`. A primary assignment requires the study to be `SCORING_QUEUED`; a reliability rescore requires the study to be `SCORED` or beyond — otherwise `ERR_STUDY_NOT_SCORABLE`. A study may hold only one non-terminal `PRIMARY` task at a time (`ERR_PRIMARY_TASK_EXISTS`). The named scorer must be active; a `RELIABILITY_RESCORE` additionally requires a scorer enrolled in the reliability pool (`ERR_SCORER_NOT_IN_POOL`), and the rescorer must not be the scorer of the study's accepted primary task (`ERR_SOD_PRIMARY_SCORER`). A scorer whose `reliability_status` is `REMEDIATION` may not receive new assignments at all (`ERR_SCORER_IN_REMEDIATION`). A new task begins in `ASSIGNED`. Tasks may be listed filtered by `study_id`, `scorer_id`, or `status`.

Work on a task is personal to its scorer: starting or submitting requires `X-User-ID` to equal the task's `scorer_id` (`ERR_NOT_TASK_OWNER`). Starting is permitted from `ASSIGNED` and from `RETURNED_FOR_REVISION` (`ERR_TASK_NOT_STARTABLE` otherwise) and moves the task to `IN_PROGRESS`. When the task is a `PRIMARY`, the study follows it from `SCORING_QUEUED` to `SCORING_IN_PROGRESS`; a returned task being resumed finds its study already there. Once a task reaches `ACCEPTED` or `RECALLED` it is terminal, and any further action on it is rejected with `ERR_TASK_TERMINAL`, a guard that fires ahead of the more specific startable, submittable, and submitted checks.

Submitting requires the task to be `IN_PROGRESS` (`ERR_TASK_NOT_SUBMITTABLE`). The scorer reports the staged event counts — `obstructive_apneas`, `central_apneas`, `mixed_apneas`, `hypopneas`, and `reras`, each zero or more — together with `epochs_total`, the number of 30-second epochs staged, which must be greater than zero. The time base differs by study type, and getting it wrong is rejected with `ERR_INVALID_REQUEST`: for the in-lab types (`PSG_DIAGNOSTIC`, `SPLIT_NIGHT`, `TITRATION_PAP`), `total_sleep_time_minutes` is required and must be greater than zero, while `total_recording_time_minutes` is optional but, when present, must be at least `total_sleep_time_minutes`; for `HST`, `total_sleep_time_minutes` must be omitted entirely and `total_recording_time_minutes` is required and must be greater than zero. Submission stamps `submitted_at` from the logical clock — it always reflects the latest submission — moves the task to `SUBMITTED`, and computes the respiratory indexes.

The event total is the sum of obstructive, central, and mixed apneas plus hypopneas. For in-lab studies, `ahi` is the event total multiplied by 60 and divided by `total_sleep_time_minutes`, rounded half-up to one decimal place; `rdi` repeats the same computation with the `reras` added to the event total; `rei` is null. For `HST`, `rei` is the event total multiplied by 60 and divided by `total_recording_time_minutes`, rounded half-up to one decimal place, and both `ahi` and `rdi` are null. Because the home variant divides by recording time rather than sleep time, identical event counts yield a strictly smaller index whenever recording time exceeds sleep time.

Review belongs to an `InterpretingPhysician`. Accepting a `SUBMITTED` task (`ERR_TASK_NOT_SUBMITTED` otherwise) moves it to `ACCEPTED`; task-kind and study-state consistency is guaranteed by construction, since a submitted primary implies its study is `SCORING_IN_PROGRESS` and a rescore exists only on scored-or-later studies. Accepting a `PRIMARY` additionally moves the study from `SCORING_IN_PROGRESS` to `SCORED` and snapshots the indexes onto it — `accepted_ahi` and `accepted_rdi` for in-lab studies, `accepted_rei` for `HST` — with all three snapshot fields null until this moment and the inapplicable ones remaining null. Alternatively the physician returns a `SUBMITTED` task with a `reason` of at least ten characters (shorter reasons are rejected with `ERR_INSUFFICIENT_REASON`); the task moves to `RETURNED_FOR_REVISION`, the reason is stored on `returned_reason` (null unless the task has been returned), and the scorer may resume the revision loop by starting the task again.

### 3.6. Physician Interpretation and Report Finalization

An `InterpretingPhysician` opens an **InterpretationReport** for a scored study by supplying the `study_id`, the `primary_scoring_task_id` of the accepted primary task being interpreted, the `diagnosis_code`, and `expected_sleep_study_version` per §2.7. Creation enforces, within the state-precondition group and in this relative order: first, a live report in `SIGNED`, `FINALIZED`, or `ADDENDUM_OPEN` already covering the study blocks creation with `ERR_FINAL_REPORT_EXISTS`; then the study must be `SCORED` or `INTERPRETATION_IN_PROGRESS` (`ERR_STUDY_NOT_SCORED`). The named `primary_scoring_task_id` must be the study's accepted `PRIMARY` task (`ERR_INVALID_PRIMARY_TASK`). Creation captures the author from `X-User-ID` into `physician_id`, opens the report in `DRAFT`, moves the study from `SCORED` to `INTERPRETATION_IN_PROGRESS` — a superseding creation while a prior draft exists leaves the study in `INTERPRETATION_IN_PROGRESS` — increments the study's `version` by one, and transitions any existing `DRAFT` report for the study to `SUPERSEDED`. Reports may be listed filtered by `study_id`, `physician_id`, or `primary_scoring_task_id`.

Signing is reserved to the report's author (`ERR_NOT_REPORT_AUTHOR`) and requires the report to be in `DRAFT` (`ERR_REPORT_INVALID_STATE`). Segregation of duties applies at the pen: the signing physician's `npi` must differ from the `npi` of the scorer who staged the accepted primary task (`ERR_SOD_REPORT_SCORER`). Signing stamps `signed_at` from the logical clock — null until the report is signed — and computes three families of derived values.

First, severity. The `index_at_interpretation` is the study's `accepted_rei` for `HST` and its `accepted_ahi` otherwise. The `severity` bands against that index are: `NORMAL` below 5.0, `MILD` at least 5.0 but below 15.0, `MODERATE` at least 15.0 but below 30.0, and `SEVERE` at least 30.0 — each boundary is inclusive on the higher band, so exactly 15.0 is `MODERATE`.

Second, turnaround. The `turnaround_calendar_hours` measure the whole minutes from `acquisition_completed_at` to `signed_at`, divided by 60 and rounded half-up to one decimal, counting every wall-clock hour including nights and weekends. The `turnaround_business_hours` accumulate only the intersection of that same interval with the laboratory's business window — Monday through Friday, 08:00:00Z to 17:00:00Z UTC, with Saturdays and Sundays contributing zero — again in whole minutes divided by 60 and rounded half-up to one decimal, so an interval spanning a weekend yields a far smaller business value than its calendar twin.

Third, the service-level verdict `sla_breached`. For a `ROUTINE` order the business-hours variant governs: a turnaround strictly greater than 48.0 business hours is a breach, and exactly 48.0 is not. For a `STAT` order the calendar variant governs: strictly greater than 24.0 calendar hours is a breach, and exactly 24.0 is not.

Signing also moves the study from `INTERPRETATION_IN_PROGRESS` to `INTERPRETED`. The author may then finalize a `SIGNED` report (`ERR_REPORT_INVALID_STATE` otherwise), which stamps `finalized_at` at this first finalization, moves the report to `FINALIZED`, and moves the study to `REPORT_FINALIZED`. Finalized reports support an addendum cycle: opening an addendum requires the author and a `FINALIZED` report, moves it to `ADDENDUM_OPEN`, and increments `addendum_count` — which begins at zero — by one; closing the addendum requires the author and an `ADDENDUM_OPEN` report and returns it to `FINALIZED`.

### 3.7. Therapy Prescription and DME Fulfillment

Where interpretation indicates therapy, the author creates a **TherapyPrescription** against a report in `SIGNED` or `FINALIZED` — any other report state is rejected with `ERR_REPORT_INVALID_STATE` — carrying `expected_interpretation_report_version` per §2.7. A report whose signed `severity` is `NORMAL` does not support PAP therapy and rejects prescription creation with `ERR_THERAPY_NOT_INDICATED`. The payload names the `report_id`, a `device_type` of `CPAP`, `APAP`, or `BIPAP`, a `mask_type` of `NASAL`, `FULL_FACE`, or `NASAL_PILLOWS`, and an optional `humidification` flag defaulting to true. Device-specific pressure fields must be present and coherent for the chosen `device_type`, with violations rejected as `ERR_RX_DEVICE_FIELDS_INVALID`: `CPAP` requires `cpap_pressure_cm` between 4.0 and 20.0 cm H2O inclusive in 0.5 steps; `APAP` requires `apap_min_cm` strictly below `apap_max_cm`, both within 4.0 to 20.0 inclusive and on 0.5 steps; `BIPAP` requires `bipap_epap_cm` strictly below `bipap_ipap_cm`, both within 4.0 to 25.0 inclusive and on 0.5 steps. Creation opens the prescription in `DRAFT`, denormalizes the report's study onto the prescription's `study_id`, increments the report's `version` by one, and supersedes any existing `DRAFT` or `ORDERED` prescription on the same report — a supersession that also cancels any linked DME order still in `DISPATCHED`. Prescriptions may be listed filtered by `report_id` or `study_id`.

For titration contexts, the physician may consult a computed pressure recommendation. It is available only for a `TITRATION_PAP` study, or a `SPLIT_NIGHT` study whose `split_outcome` is `CONVERT_TO_TITRATION`, that has an accepted `PRIMARY` scoring task; anything else is rejected with `ERR_TITRATION_RECOMMENDATION_UNAVAILABLE`. The recommendation reads three study values: the raw ending pressure `titration_final_pressure_cm`, the `accepted_ahi` as the residual index, and the `leak_95th_l_min`. Its evaluation order is pinned. First the raw pressure determines a band: at most 10.0 cm is the low band, anything above is the high band, and the band is computed from the raw pressure alone — it is never recomputed after adjustment. The residual index contributes an adjustment of 1.0 when at least 10.0, 0.5 when at least 5.0 but below 10.0, and 0.0 below 5.0. The leak contributes 0.5 when the band is low and the leak exceeds 24.0 L/min, 1.0 when the band is high and the leak exceeds 36.0 L/min, and 0.0 otherwise. The recommendation is the raw pressure plus both adjustments, clamped to no less than 4.0 and no more than 20.0, then rounded to the nearest 0.5 step round-half-up (§2.6). The response reports the result as `recommended_cpap_cm` alongside the inputs `raw_pressure_cm`, `residual_ahi`, and `leak_95th_l_min`.

Only the report's author may order or cancel a prescription (`ERR_NOT_REPORT_AUTHOR`). Ordering requires `DRAFT` (`ERR_RX_INVALID_STATE`), stamps `ordered_at` from the logical clock — null until the prescription is ordered — and moves the prescription to `ORDERED`. Cancelling requires `DRAFT` or `ORDERED` (`ERR_RX_INVALID_STATE` otherwise) and moves it to `CANCELLED`; cancelling an `ORDERED` prescription also cancels a linked DME order still in `DISPATCHED`. Delivery of the equipment fulfills an `ORDERED` prescription automatically.

The `DmeCoordinator` then runs fulfillment. Dispatching a **DmeOrder** names the `prescription_id` and the `vendor_name`; the prescription must be `ORDERED` (`ERR_RX_INVALID_STATE` otherwise), and a prescription may have only one non-terminal DME order at a time (`ERR_DME_ORDER_ACTIVE`). Dispatch creates the order in `DISPATCHED` and stamps `dispatched_at`. Orders may be listed filtered by `prescription_id` or `status`. From `DISPATCHED`, the coordinator records delivery — stamping `delivered_at`, which is null until this moment, moving the order to `DELIVERED`, and fulfilling the parent prescription (`ORDERED` → `FULFILLED`) — or records a vendor decline to `DECLINED`, or cancels the order to `CANCELLED`; each of these three actions requires `DISPATCHED` (`ERR_DME_INVALID_STATE` otherwise).

Thirty days after delivery, the coordinator records adherence follow-up on a `DELIVERED` order (`ERR_DME_INVALID_STATE` otherwise), supplying `usage_hours_avg`, the average nightly usage hours over the window, and `compliant_nights_percent`, the percentage of nights with at least four hours of usage; the values are stored on the order as `follow_up_usage_hours_avg` and `follow_up_compliant_nights_percent`. The order is adherence-compliant when average usage is at least 4.0 hours and the compliant-nights percentage is at least 70.0 — both boundaries inclusive, so exactly 4.0 hours and exactly 70.0 percent pass. The verdict is stored in `adherence_compliant`, which is null until follow-up is recorded: a compliant order moves to `FOLLOW_UP_PASSED`, and a non-compliant order moves to `ADHERENCE_REVIEW`. From `ADHERENCE_REVIEW`, the coordinator resolves the case with an `action` — `CONTINUE_THERAPY` or `ESCALATE_TO_PHYSICIAN` — which is stored as `resolution_action`, null until resolution, and moves the order to `FOLLOW_UP_RESOLVED`.

### 3.8. Inter-Rater Reliability and Accreditation Metrics

The laboratory's accreditation program pairs independent rescoring against accepted primaries. The `LabDirector` opens an **InterRaterCase** by naming the `study_id`, the `primary_task_id`, and the `rescore_task_id`. Both tasks must be `ACCEPTED`, of kinds `PRIMARY` and `RELIABILITY_RESCORE` respectively, on the same study, and staged by different scorers (`ERR_CASE_TASKS_INVALID`); a rescore task may appear in only one case (`ERR_CASE_ALREADY_EXISTS`). A new case begins `OPEN`. Cases may be listed filtered by `study_id`, `primary_task_id`, or `rescore_task_id`.

Adjudicating an `OPEN` case (`ERR_CASE_INVALID_STATE` otherwise) supplies `epochs_concordant`, the number of epochs staged identically by both scorers — at least zero and no more than the rescore task's `epochs_total` (`ERR_INVALID_REQUEST`). Adjudication stamps `adjudicated_at`, moves the case to `ADJUDICATED`, and computes the agreement metrics. Each task's index snapshot is its `rei` for an `HST` study and its `ahi` otherwise, stored on the case as `ahi_primary` and `ahi_rescore`. The `ahi_delta` is the absolute difference of the two snapshots, rounded half-up to two decimals. The `percent_agreement` is `epochs_concordant` expressed as a percentage of the rescore task's `epochs_total`, rounded half-up to two decimals. The case is `concordant` when the delta is at most 2.0 and the percent agreement is at least 85.0.

Adjudication then cascades into the rescorer's reliability record. A concordant case resets the scorer's `consecutive_nonconcordant` to zero; a non-concordant case increments it by one. The scorer's `rolling_agreement_index` is the mean of the per-case `percent_agreement` values — exactly as stored, each already rounded to two decimals — over the scorer's last five adjudicated cases as rescorer, ordered by `adjudicated_at` ascending with ties broken by `created_at` ascending, the mean itself rounded half-up to two decimals; it remains null while the scorer has fewer than three adjudicated cases. The `reliability_status` then recomputes: `REMEDIATION` when `consecutive_nonconcordant` has reached two — regardless of case count — or when at least three cases exist and the rolling index is below 80.0; `CONSISTENT` when at least three cases exist, the rolling index is at least 90.0, and the consecutive count is below two; `WATCH` when at least three cases exist, the rolling index is at least 80.0 but below 90.0, and the consecutive count is below two; and `PROVISIONAL` in every other configuration. A scorer entering `REMEDIATION` fires the recall cascade: every one of that scorer's tasks in `ASSIGNED`, `IN_PROGRESS`, or `RETURNED_FOR_REVISION` is recalled to `RECALLED`, and each recalled `PRIMARY` task pushes its study back from `SCORING_IN_PROGRESS` to `SCORING_QUEUED` for reassignment. A scorer may leave remediation only through the `LabDirector`'s reinstatement, which requires `reliability_status` of `REMEDIATION` (`ERR_SCORER_NOT_REMEDIATION`), returns the scorer to `PROVISIONAL`, and resets `consecutive_nonconcordant` to zero.

For accreditation reporting, the `LabDirector` consults the quality summary, which reports `reports_signed_total` and how many of them breached the turnaround SLA as `sla_breached_total`, the resulting `sla_compliance_percent`, the reliability program's `cases_adjudicated_total` and `cases_concordant_total` with the resulting `inter_rater_concordant_percent`, and the current `scorers_in_remediation_total`. Percentages are reported with two decimals round-half-up, and a metric whose denominator is empty reports 100.00.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Request payloads, preconditions, and side effects for every operation are specified in §2 and §3; this table is the routing and authorization index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Register a patient | Scheduler |
| GET | `/patients/{patientId}` | Get a patient | All roles |
| POST | `/referral-orders` | Create a referral order for a patient | Scheduler |
| GET | `/referral-orders` | List referral orders (filterable) | All roles |
| GET | `/referral-orders/{orderId}` | Get a referral order | All roles |
| POST | `/referral-orders/{orderId}/authorizations` | Submit an insurance authorization (supersedes live auth; OCC on order version) | Scheduler |
| GET | `/authorizations` | List authorizations (filterable) | All roles |
| GET | `/authorizations/{authorizationId}` | Get an authorization | All roles |
| POST | `/authorizations/{authorizationId}/decision` | Record the payer decision on a submitted authorization | Scheduler |
| POST | `/referral-orders/{orderId}/provider-review` | Resolve a needs-provider-review order (reinstate or cancel) | Scheduler |
| POST | `/referral-orders/{orderId}/cancel` | Cancel a non-terminal order | Scheduler |
| POST | `/beds` | Register a lab bed | LabDirector |
| POST | `/technologists` | Register a technologist | LabDirector |
| POST | `/scorers` | Register a scorer | LabDirector |
| GET | `/scorers/{scorerId}` | Get a scorer (reliability telemetry) | All roles |
| POST | `/scorers/{scorerId}/reinstate` | Reinstate a remediation scorer to provisional | LabDirector |
| POST | `/physicians` | Register an interpreting physician | LabDirector |
| POST | `/staffing-assignments` | Plan a technologist night shift | LabDirector |
| GET | `/staffing-assignments` | List staffing assignments (filterable) | All roles |
| GET | `/staffing-assignments/{staffingAssignmentId}` | Get a staffing assignment | All roles |
| POST | `/staffing-assignments/{staffingAssignmentId}/confirm` | Assigned technologist confirms the shift | SleepTechnologist |
| POST | `/staffing-assignments/{staffingAssignmentId}/cancel` | Cancel a staffing assignment (capacity-guarded) | LabDirector |
| POST | `/sleep-studies` | Schedule a study against an authorized order | Scheduler |
| GET | `/sleep-studies` | List sleep studies (filterable) | All roles |
| GET | `/sleep-studies/{studyId}` | Get a sleep study | All roles |
| POST | `/sleep-studies/{studyId}/check-in` | Check the patient in on the scheduled night | SleepTechnologist |
| POST | `/sleep-studies/{studyId}/split-decision` | Record the one-shot split-night protocol decision | SleepTechnologist |
| POST | `/sleep-studies/{studyId}/complete-acquisition` | Complete acquisition; study enters the scoring queue and the order is fulfilled | SleepTechnologist |
| POST | `/sleep-studies/{studyId}/no-show` | Mark a scheduled study as no-show | Scheduler, SleepTechnologist |
| POST | `/sleep-studies/{studyId}/cancel` | Cancel a scheduled study | Scheduler |
| POST | `/sleep-studies/{studyId}/technical-failure` | Fail an in-progress study for technical reasons | SleepTechnologist |
| GET | `/sleep-studies/{studyId}/titration-recommendation` | Computed CPAP pressure recommendation for titration studies | InterpretingPhysician |
| POST | `/scoring-tasks` | Assign a scoring task (primary or reliability rescore) | LabDirector |
| GET | `/scoring-tasks` | List scoring tasks (filterable) | All roles |
| GET | `/scoring-tasks/{scoringTaskId}` | Get a scoring task | All roles |
| POST | `/scoring-tasks/{scoringTaskId}/start` | Scorer starts (or resumes after return) a task | Scorer |
| POST | `/scoring-tasks/{scoringTaskId}/submit` | Scorer submits epoch-level counts; indexes computed | Scorer |
| POST | `/scoring-tasks/{scoringTaskId}/accept` | Physician accepts a submitted task | InterpretingPhysician |
| POST | `/scoring-tasks/{scoringTaskId}/return` | Physician returns a submitted task for revision | InterpretingPhysician |
| POST | `/interpretation-reports` | Create a report draft for a scored study (supersedes existing draft; OCC on study version) | InterpretingPhysician |
| GET | `/interpretation-reports` | List reports (filterable) | All roles |
| GET | `/interpretation-reports/{interpretationReportId}` | Get a report | All roles |
| POST | `/interpretation-reports/{interpretationReportId}/sign` | Author signs the report; severity, turnaround, and SLA computed | InterpretingPhysician |
| POST | `/interpretation-reports/{interpretationReportId}/finalize` | Author finalizes a signed report | InterpretingPhysician |
| POST | `/interpretation-reports/{interpretationReportId}/open-addendum` | Author opens an addendum on a finalized report | InterpretingPhysician |
| POST | `/interpretation-reports/{interpretationReportId}/close-addendum` | Author closes the addendum | InterpretingPhysician |
| POST | `/therapy-prescriptions` | Create a therapy prescription on a signed/finalized report (supersedes active rx; OCC on report version) | InterpretingPhysician |
| GET | `/therapy-prescriptions` | List prescriptions (filterable) | All roles |
| GET | `/therapy-prescriptions/{therapyPrescriptionId}` | Get a prescription | All roles |
| POST | `/therapy-prescriptions/{therapyPrescriptionId}/order` | Author orders the prescription | InterpretingPhysician |
| POST | `/therapy-prescriptions/{therapyPrescriptionId}/cancel` | Author cancels the prescription | InterpretingPhysician |
| POST | `/dme-orders` | Dispatch a DME order for an ordered prescription | DmeCoordinator |
| GET | `/dme-orders` | List DME orders (filterable) | All roles |
| GET | `/dme-orders/{dmeOrderId}` | Get a DME order | All roles |
| POST | `/dme-orders/{dmeOrderId}/deliver` | Vendor delivered and set up the device | DmeCoordinator |
| POST | `/dme-orders/{dmeOrderId}/decline` | Vendor declines the order | DmeCoordinator |
| POST | `/dme-orders/{dmeOrderId}/cancel` | Coordinator cancels a dispatched order | DmeCoordinator |
| POST | `/dme-orders/{dmeOrderId}/record-follow-up` | Record 30-day adherence follow-up; branches on compliance | DmeCoordinator |
| POST | `/dme-orders/{dmeOrderId}/resolve-adherence` | Resolve an adherence review | DmeCoordinator |
| POST | `/inter-rater-cases` | Open a reliability case pairing an accepted primary and an accepted rescore task | LabDirector |
| GET | `/inter-rater-cases` | List reliability cases (filterable) | All roles |
| GET | `/inter-rater-cases/{interRaterCaseId}` | Get a reliability case | All roles |
| POST | `/inter-rater-cases/{interRaterCaseId}/adjudicate` | Adjudicate a case; computes agreement and cascades scorer reliability status | LabDirector |
| GET | `/quality-metrics/summary` | Accreditation quality dashboard: turnaround SLA compliance and inter-rater concordance | LabDirector |
| POST | `/_clock/set_current_utc` | Set the logical clock; advancing past an approved authorization's window end expires it and its authorized order | LabDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_TASK_OWNER` | 403 Forbidden |
| `ERR_NOT_REPORT_AUTHOR` | 403 Forbidden |
| `ERR_STAFFING_NOT_OWN` | 403 Forbidden |
| `ERR_SOD_PRIMARY_SCORER` | 422 Unprocessable Entity |
| `ERR_SOD_REPORT_SCORER` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_AUTHORIZABLE_STATE` | 409 Conflict |
| `ERR_AUTH_NOT_PENDING` | 409 Conflict |
| `ERR_AUTH_WINDOW_INVALID` | 400 Bad Request |
| `ERR_DUPLICATE_MRN` | 400 Bad Request |
| `ERR_ORDER_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_ORDER_HAS_ACTIVE_STUDY` | 409 Conflict |
| `ERR_ORDER_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_AUTH_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_STUDY_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BED_REQUIRED_FOR_IN_LAB` | 400 Bad Request |
| `ERR_BED_NOT_ALLOWED_FOR_HST` | 400 Bad Request |
| `ERR_BED_INACTIVE` | 422 Unprocessable Entity |
| `ERR_BED_NOT_TITRATION_CAPABLE` | 422 Unprocessable Entity |
| `ERR_BED_NIGHT_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_WOULD_BE_VIOLATED` | 422 Unprocessable Entity |
| `ERR_AUTH_NIGHTS_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STAFFING_INVALID_STATE` | 409 Conflict |
| `ERR_STUDY_NOT_TONIGHT` | 422 Unprocessable Entity |
| `ERR_STUDY_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_SPLIT_NOT_APPLICABLE` | 409 Conflict |
| `ERR_SPLIT_ALREADY_DECIDED` | 409 Conflict |
| `ERR_SPLIT_DECISION_REQUIRED` | 409 Conflict |
| `ERR_SPLIT_CENTRAL_PREDOMINANCE` | 422 Unprocessable Entity |
| `ERR_SPLIT_MIN_DIAGNOSTIC_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SPLIT_AHI_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SPLIT_INSUFFICIENT_REMAINING` | 422 Unprocessable Entity |
| `ERR_STUDY_NOT_SCORABLE` | 409 Conflict |
| `ERR_PRIMARY_TASK_EXISTS` | 409 Conflict |
| `ERR_SCORER_IN_REMEDIATION` | 422 Unprocessable Entity |
| `ERR_SCORER_NOT_IN_POOL` | 422 Unprocessable Entity |
| `ERR_TASK_NOT_STARTABLE` | 409 Conflict |
| `ERR_TASK_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_TASK_NOT_SUBMITTED` | 409 Conflict |
| `ERR_TASK_TERMINAL` | 409 Conflict |
| `ERR_INSUFFICIENT_REASON` | 400 Bad Request |
| `ERR_STUDY_NOT_SCORED` | 409 Conflict |
| `ERR_INVALID_PRIMARY_TASK` | 422 Unprocessable Entity |
| `ERR_FINAL_REPORT_EXISTS` | 409 Conflict |
| `ERR_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_TITRATION_RECOMMENDATION_UNAVAILABLE` | 409 Conflict |
| `ERR_THERAPY_NOT_INDICATED` | 422 Unprocessable Entity |
| `ERR_RX_DEVICE_FIELDS_INVALID` | 400 Bad Request |
| `ERR_RX_INVALID_STATE` | 409 Conflict |
| `ERR_DME_ORDER_ACTIVE` | 409 Conflict |
| `ERR_DME_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CASE_TASKS_INVALID` | 422 Unprocessable Entity |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_SCORER_NOT_REMEDIATION` | 409 Conflict |
