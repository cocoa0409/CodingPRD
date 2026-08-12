# Home Dialysis Supply Logistics API — Product Requirements Document

## 1. Introduction

A home dialysis program succeeds or fails on logistics discipline: patients must be trained and certified before they ever run a machine at home, their residences must pass water, electrical, and storage suitability checks, machines must be assigned, maintained, and covered by an emergency backup plan, and a monthly rhythm of supply orders, deliveries, treatment logs, and clinical reviews must be sustained indefinitely. When any link in that chain weakens — a lapsed certification, a machine overdue for service, a stretch of missing logs, a waste spike — the program must degrade gracefully into restricted states rather than fail silently, and it must support an orderly transition of the patient back to in-center care with a coded reason when home dialysis is no longer appropriate.

This document specifies the REST API that operates such a program, mounted under `/api`. It governs six cooperating roles with deliberate segregation of duties, a derived patient **posture** that gates clinical and commercial actions, an optimistic-concurrency protocol on the three operations that supersede existing state, and a server-held logical clock that drives every time-dependent rule. The API is the single source of truth for training records, home assessments and remediation work, machine assignment and maintenance, emergency backup plans, monthly supply orders and their delivery appointments, treatment logs and clinical reviews, in-center backup slots, waste and return accounting, and home-to-center transition records.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The API recognizes six roles: `Patient`, `HomeNurse`, `Nephrologist`, `SupplyCoordinator`, `BiomedTechnician`, and `ProgramAdmin`. Each endpoint admits a defined set of roles (see §4); a caller whose role is not admitted to an endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All read endpoints are open to every authenticated role.

When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting Patient; ownership checks on any resource that references a Patient compare the resource's foreign-key field to `X-User-ID`. A Patient-role caller may therefore only create or act upon their own records — their own supply orders (create, line edits, submit, cancel), their own treatment logs (create, amend), their own backup slot reservations (book, cancel), their own waste and return reports, and their own transition requests. Any Patient-role write whose target belongs to a different patient is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

When `X-User-Role` is `HomeNurse`, `Nephrologist`, `SupplyCoordinator`, `BiomedTechnician`, or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `trainer_user_id` on a recorded TrainingAttempt, as `assessed_by_user_id` on a HomeAssessment, or as `signed_off_by_user_id` when an attempt is signed off — but it does not compare it to any entity's `id`. The segregation-of-duties rules in §2.11 compare these recorded operator identifiers, never entity ids.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its rows sorted by `created_at` in ascending order, with ties on `created_at` broken by server-side insertion order (records created earlier within the same clock instant sort first), and pagination slices that deterministic order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every resource in the system — DialysisProgram, Patient, TrainingAttempt, HomeAssessment, HomeModificationWorkOrder, DialysisMachine, MaintenanceEvent, EmergencyBackupPlan, SupplyOrder, DeliveryAppointment, TreatmentLog, ClinicalReview, InCenterChair, BackupSlotReservation, WasteReturnRecord, and TransitionRecord — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations driven by cascades and derived-field recomputation. This field backs the optimistic concurrency protocol of §2.8.

### 2.5. The Logical Clock and Lazy State Evaluation

All time-dependent rules in the system — certification currency, assessment validity, plan expiry, review overdue detection, missed-log streaks, no-show detection, transition completion, and every "not before now" check — read a single server-held **logical clock**. At startup, before any clock call, the logical clock reads exactly 2026-05-01T00:00:00Z; the server must never fall back to wall-clock time. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`; after any advance, lazy evaluations are re-applied on subsequent reads and mutations.

Several states are **lazy**: they are not written by a background job but are applied whenever the record — or its owning patient — is read or mutated. An EmergencyBackupPlan whose `last_drill_at` lies ninety or more days in the past reads as `EXPIRED`. A BackupSlotReservation still `RESERVED` once the clock has passed its `slot_end` reads as `NO_SHOW` and increments the patient's `no_show_count`. A temporary TransitionRecord whose `effective_to` has passed reads as `COMPLETED`, with the patient-side consequences described in §3.9. A ClinicalReview whose `due_at` falls before the current clock instant counts as overdue for posture purposes. The `missed_log_streak` derivation of §3.6 is likewise recomputed against the clock on every patient read.

### 2.6. Validation Pipeline and Check Ordering

Every request is validated against a fixed pipeline, and earlier stages mask later ones — a request rejected at an earlier stage never reaches later checks. The stages, in order, are:

1. **Header presence** — `X-User-ID` and `X-User-Role` present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role is admitted to the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Patient ownership** — for Patient-role writes, the caller owns the target (`ERR_FORBIDDEN_OWNERSHIP`).
4. **Existence** — path identifiers exist, validated left to right, and body foreign-key references exist (`ERR_NOT_FOUND`).
5. **State validity** — the target resource is in a state from which the requested transition exists, per the entity state machines; the optimistic-concurrency version match on the three concurrency-guarded endpoints is evaluated at this stage as `ERR_STALE_VERSION` alongside the per-entity invalid-state errors such as `ERR_ORDER_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`, `ERR_WORK_ORDER_INVALID_STATE`, `ERR_MACHINE_INVALID_STATE`, `ERR_EVENT_INVALID_STATE`, `ERR_APPOINTMENT_INVALID_STATE`, `ERR_LOG_INVALID_STATE`, `ERR_REVIEW_NOT_PENDING`, `ERR_SLOT_INVALID_STATE`, `ERR_WASTE_RECORD_NOT_REPORTED`, `ERR_TRANSITION_INVALID_STATE`, `ERR_ATTEMPT_NOT_RECORDED`, `ERR_PLAN_NOT_ACTIVE`, and `ERR_PATIENT_INVALID_STATE`.
6. **Segregation of duties and clinical safety** — `ERR_SOD_SIGNOFF_BY_TRAINER`, `ERR_SOD_ASSESSOR_SELF_ACCEPT`, `ERR_POSTURE_NOT_ORDERABLE`, and `ERR_REASON_REQUIRES_PHYSICIAN`.
7. **Clock-relative temporal rules** — `ERR_ORDER_MONTH_IN_PAST`, `ERR_SLOT_IN_PAST`, `ERR_LOG_DATE_IN_FUTURE`, `ERR_MONTH_NOT_ENDED`, `ERR_EVENT_WINDOW_PASSED`, `ERR_TRANSITION_EFFECTIVE_IN_FUTURE`, and `ERR_SLOT_TOO_LATE_TO_CANCEL`.
8. **Uniqueness and overlap** — `ERR_DUPLICATE_TREATMENT_DATE`, `ERR_SERIAL_NUMBER_EXISTS`, duplicate `chair_code` (reported as `ERR_INVALID_REQUEST`), `ERR_MONTH_ORDER_EXISTS`, `ERR_ACTIVE_APPOINTMENT_EXISTS`, `ERR_OPEN_APPOINTMENTS_EXIST`, `ERR_CHAIR_SLOT_OVERLAP`, `ERR_EVENT_WINDOW_OVERLAP`, `ERR_MACHINE_BUSY_MAINTENANCE`, `ERR_SLOT_DAILY_CAP_EXCEEDED`, and `ERR_OPEN_TRANSITION_EXISTS`.
9. **Cross-entity referential state** — the readiness gates (`ERR_TRAINING_INCOMPLETE`, `ERR_ASSESSMENT_NOT_CURRENT`, `ERR_NO_MACHINE_ASSIGNED`, `ERR_NO_ACTIVE_PLAN`, `ERR_READINESS_GATES_NOT_MET`, `ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE`), `ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT`, `ERR_PLAN_NOT_ACTIVE`, `ERR_CHAIR_OUT_OF_SERVICE`, `ERR_BACKUP_MACHINE_NOT_IN_STOCK`, `ERR_MACHINE_MAINTENANCE_DUE`, `ERR_MACHINE_REFERENCED_BY_PLAN`, `ERR_WORK_ORDERS_OUTSTANDING`, `ERR_ASSESSMENT_RESULT_FAIL`, `ERR_ATTEMPT_NOT_PASSING`, `ERR_UNREVIEWED_LOGS_REMAIN`, `ERR_REASON_NOT_SUBSTANTIATED`, `ERR_REVERSAL_TARGET_INVALID`, and `ERR_PATIENT_NOT_ACTIVE_HOME`.
10. **Quota and fiscal checks, always last** — `ERR_STORAGE_CAPACITY_EXCEEDED` (evaluated before the allowance bound, per §3.5), `ERR_ALLOWANCE_EXCEEDED`, `ERR_QUANTITY_EXCEEDS_ON_HAND`, and `ERR_DELIVERED_UNITS_INVALID`.

### 2.7. Nested Resource Retrieval

Requests that target nested resources validate path identifiers strictly from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in the path that does not correspond to an existing resource; the system does not evaluate later identifiers or business rules once an earlier segment has failed. The same `ERR_NOT_FOUND` rejection applies to foreign-key references supplied in a request body — for example, a payload naming a `patient_id`, `machine_id`, `supply_order_id`, `chair_id`, `assessment_id`, `backup_machine_id`, or `reversal_of_id` that does not exist.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, because each of them legitimately **supersedes** existing state and therefore must not be driven by a stale view of the superseded aggregate:

- Creating a monthly supply order (`POST /api/supply-orders`) requires the non-optional field `expected_patient_version`, carrying the client's last observed `version` of the target Patient. If the patient's current `version` has advanced beyond the supplied value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because order creation supersedes an existing `DRAFT` order for the same patient and month (§3.5), and a client holding an outdated patient view must not be allowed to supersede on that basis.
- Creating an emergency backup plan (`POST /api/emergency-backup-plans`) likewise requires `expected_patient_version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch, because plan creation supersedes the patient's prior `ACTIVE` or `EXPIRED` plan (§3.4).
- Assigning a dialysis machine (`POST /api/dialysis-machines/{id}/assign`) requires the non-optional field `expected_machine_version`, carrying the client's last observed `version` of the DialysisMachine. A mismatch with the machine's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because assignment supersedes the machine's current assignment when it moves from one patient to another (§3.4).

Endpoints not named in this section accept no version field at all. Note that the three guarded creations themselves advance the relevant parent `version` — creating an order or a plan increments the Patient's `version`, and assigning a machine increments the machine's `version` — so every successful supersede invalidates previously observed versions.

### 2.9. Numeric Precision, Rounding, and Money

Monetary amounts are integer cents throughout; no money field carries a fractional part. Wherever rounding is specified, the method is **round half up**. Two disciplines are pinned and must not be reordered. First, per-line rounding precedes summation for both the order handling fee and the return credit: each line amount is rounded half up to whole cents on its own, and only the rounded line amounts are summed — the sum-then-round order is forbidden, because the two orders diverge whenever fractional half-cent line amounts pair up (two lines rated at 10.5 and 12.5 cents round to 11 and 13 and total 24 per-line, versus 23 if summed first). Second, the order grand total follows a fixed evaluation order — exact subtotal first, then the volume discount keyed on that subtotal (never on the post-discount total), then the grand total — as specified in §3.5.

Machine runtime figures (`total_runtime_hours`, `runtime_hours_at_last_service`, `runtime_hours_at_service`) are expressed in hours at two decimal places. The rolling adherence percentage is reported at one decimal place, rounded half up. Water chloramine is compared at full floating-point precision — a reading of exactly 0.1 ppm passes the assessment threshold, because the comparison is inclusive. The monthly waste ratio is likewise compared at full float precision against an inclusive threshold. All unit quantities — allowances, on-hand counts, delivered units, consumption units — are integers.

### 2.10. Patient Posture: The Derived Readiness Gate

Every Patient carries a derived `posture`, one of `NOT_READY`, `HOME_READY`, `AT_RISK`, or `BLOCKED`. Posture is never stored as an input; it is re-evaluated on every read of the patient and after every mutation that touches one of its inputs — training sign-off, assessment acceptance, machine assignment or unassignment, maintenance start or completion, plan creation, drill, or lazy expiry, review sign-off or escalation, waste verification, log creation, and clock-driven lazy evaluation. The patient roster list re-evaluates posture per row. The derivation is a precedence ladder, evaluated top-down with the first matching rung winning:

1. A patient in `TRAINING` is `NOT_READY`.
2. A patient in `TRANSITIONED_OUT` is `BLOCKED`.
3. A patient who has never been activated (`ever_home_ready` still false) is `HOME_READY` when all four readiness gates below hold, and `NOT_READY` otherwise.
4. The patient is `BLOCKED` when any of the following holds: some training module lacks a `SIGNED_OFF` passing attempt whose `signed_off_at` is strictly more recent than 365 days ago (certification expired); no `ACCEPTED` assessment has an `accepted_at` strictly more recent than 730 days ago (assessment expired); a `PENDING` ClinicalReview has its `due_at` before the current clock instant (review overdue); an open escalation exists — an `ESCALATED` review created after the most recent `SIGNED_OFF` review, or any `ESCALATED` review at all when no review was ever signed off; or `retraining_required` is true.
5. Failing that, the patient is `AT_RISK` when any of the following holds: no machine with status `ASSIGNED` is assigned to the patient; the assigned machine is `maintenance_due` or `UNDER_MAINTENANCE`; no EmergencyBackupPlan is `ACTIVE` (the plan is missing, `EXPIRED`, `SUPERSEDED`, or `CLOSED`); the `missed_log_streak` has reached the program's `max_missed_log_streak`; or `waste_alert_active` is true.
6. Otherwise the patient is `HOME_READY`.

The four **readiness gates** referenced by rung 3 — and checked explicitly by activation, reinstatement, and reversal activation — are: certification current (every module has a `SIGNED_OFF` passing attempt signed off strictly within the last 365 days), assessment current (an `ACCEPTED` assessment accepted strictly within the last 730 days), machine assigned (a machine `ASSIGNED` to the patient), and plan active (an EmergencyBackupPlan in `ACTIVE`). Posture gates commerce directly: order submission requires `HOME_READY` or `AT_RISK`, and a patient whose posture is `NOT_READY` or `BLOCKED` is rejected with `ERR_POSTURE_NOT_ORDERABLE`.

### 2.11. Segregation of Duties and Clinical Governance

Clinical record-keeping is deliberately split so that no single operator both performs and certifies the same act. A HomeNurse who records a training attempt may not sign it off: sign-off by the attempt's own `trainer_user_id` is rejected with `ERR_SOD_SIGNOFF_BY_TRAINER` (HTTP 403). A HomeNurse who performed a home assessment may neither accept it nor send it to remediation: either action by the assessment's `assessed_by_user_id` is rejected with `ERR_SOD_ASSESSOR_SELF_ACCEPT` (HTTP 403). Resubmission after remediation refreshes `assessed_by_user_id` to the resubmitting nurse, so a fresh acceptance must again come from a different nurse (§3.3). Two further clinical safety gates are enforced in the same pipeline stage: order submission requires an orderable posture (`ERR_POSTURE_NOT_ORDERABLE`), and the `MEDICAL_COMPLICATION` transition reason may be requested only by a `Nephrologist` (`ERR_REASON_REQUIRES_PHYSICIAN`).

## 3. Business Logic & Workflows

### 3.1. Program Setup and Patient Enrollment

Everything begins with the program itself. A `ProgramAdmin` creates a DialysisProgram with a display `name` and three policy knobs: `review_cadence_treatments` (an integer of at least 1 — the unreviewed-log count at which the system auto-opens a cadence ClinicalReview, §3.6), `max_missed_log_streak` (an integer of at least 1 — the missed-log streak that pushes a patient toward `AT_RISK`, §3.6), and `waste_ratio_alert_threshold` (greater than 0 and at most 1 — the monthly waste ratio at which the waste alert latches, §3.8). The program also carries its `supply_catalog`: a list of catalog entries, each naming a `sku` that is unique within the program, a display `name`, a `unit_price_cents`, a `handling_rate_cents` that may be fractional (a rate such as 10.5 cents per unit is legitimate), and a `unit_credit_cents` used when returns are credited. Program rosters, machine fleets, and chair inventories are listable per program, and the roster accepts optional `posture` and `program_status` filters with posture re-evaluated per row; the fleet list filters by `status` and `assigned_patient_id`, and the chair list by `in_service`.

A `HomeNurse` enrolls a patient into a program by supplying `program_id`, `full_name`, `prescription_treatments_per_week` (an integer from 1 to 7), and `prescription_units_per_treatment` (at least 1). A new patient starts with `program_status` `TRAINING` and posture `NOT_READY`; the latches `ever_home_ready`, `retraining_required`, and `waste_alert_active` all start false, `no_show_count` starts at 0, `storage_cap_units` is 0 until an assessment is accepted, and `on_hand_units` and `missed_log_streak` are derived continuously per §3.5 and §3.6. Prescription management belongs to the `Nephrologist`, who may update `prescription_treatments_per_week` and `prescription_units_per_treatment`; the change increments the patient's `version` and affects only future submit-time allowance evaluations — an allowance already stored on a submitted order is never retroactively altered.

Activation moves a patient from `TRAINING` to `ACTIVE_HOME` and is performed by a `Nephrologist`. Four readiness gates are checked in a fixed order, and the first failure is what the caller sees: training certification first (every `module_code` must have a `SIGNED_OFF` passing attempt whose `signed_off_at` is strictly more recent than 365 days ago, else `ERR_TRAINING_INCOMPLETE`), then assessment currency (the latest `ACCEPTED` assessment must have `accepted_at` strictly more recent than 730 days ago, else `ERR_ASSESSMENT_NOT_CURRENT`), then machine assignment (a machine with status `ASSIGNED` and `assigned_patient_id` naming this patient must exist, else `ERR_NO_MACHINE_ASSIGNED`), and finally the emergency plan (an EmergencyBackupPlan in `ACTIVE` must exist, else `ERR_NO_ACTIVE_PLAN`). On success the server latches `ever_home_ready` to true — it never returns to false — recomputes posture (expected `HOME_READY`), and increments the patient's `version`.

A `Nephrologist` may manually suspend an `ACTIVE_HOME` patient by supplying a non-empty `reason` (an empty or missing reason is `ERR_INVALID_REQUEST`), moving the patient to `SUSPENDED`. A manual suspend deliberately touches nothing else: the machine assignment, the emergency plans, and any open orders all survive (contrast the transition-driven suspension of §3.9). Reinstatement by a `Nephrologist` moves `SUSPENDED` back to `ACTIVE_HOME`; the checks run in a pinned order — first, no `HOME_TO_CENTER` TransitionRecord in `ACTIVE` may exist for the patient (`ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE` is reported ahead of any gate failure), and then all four readiness gates must pass or the reinstatement is rejected with `ERR_READINESS_GATES_NOT_MET`. Posture is recomputed on success. Lifecycle actions attempted from a state that lacks the transition — suspending a `TRAINING` patient, activating a patient already activated, or any lifecycle action after `TRANSITIONED_OUT` — are rejected with `ERR_PATIENT_INVALID_STATE`.

### 3.2. Training Certification and Sign-Off

Competency is certified module by module across five modules: `WATER_HANDLING`, `MACHINE_OPERATION`, `ASEPTIC_TECHNIQUE`, `EMERGENCY_RESPONSE`, and `SUPPLY_STORAGE`. A `HomeNurse` records a TrainingAttempt with `patient_id`, `module_code`, and `score_pct` (an integer from 0 to 100). The server stamps the attempt with the caller's identifier as `trainer_user_id`, computes `is_passing` — a score of at least 80 passes — and starts the attempt in `RECORDED`. Until sign-off, `signed_off_by_user_id` and `signed_off_at` are null.

Sign-off is also performed by a `HomeNurse`, but never the same one. The attempt must currently be `RECORDED` (`ERR_ATTEMPT_NOT_RECORDED`), it must be passing (`ERR_ATTEMPT_NOT_PASSING`), and the signing nurse's `X-User-ID` must differ from `trainer_user_id` (`ERR_SOD_SIGNOFF_BY_TRAINER`, per §2.11). A successful sign-off stamps `signed_off_by_user_id` with the signer and `signed_off_at` with the current logical clock, moves the attempt to `SIGNED_OFF` (terminal), clears the patient's `retraining_required` latch if it was set — any passing sign-off clears it, regardless of module — and recomputes posture. Certification currency is measured from `signed_off_at`: an attempt stops satisfying the certification gate 365 days after sign-off (the boundary is strict — a sign-off exactly 365 days ago does not count). A patient's attempts are listable with optional `module_code` and `status` filters.

### 3.3. Home Assessment, Remediation, and Modification Work Orders

A `HomeNurse` submits a HomeAssessment for a patient, declaring an `assessment_kind` of `INITIAL`, `REASSESSMENT`, or `POST_MODIFICATION`, together with four measurements: `water_chloramine_ppm` (non-negative), `electrical_dedicated_circuit`, `electrical_voltage_verified`, and `storage_area_sqft` (greater than zero). The server records the caller as `assessed_by_user_id` and immediately computes two derived values, both on initial submission and again on every resubmission. The first is `storage_cap_units`: four units per certified square foot, rounded down to a whole unit, and capped at 400 units. The second is `result`, which is `PASS` only when all four conditions hold — chloramine at most 0.1 ppm compared at full precision so that exactly 0.1 passes, a dedicated electrical circuit present, voltage verified, and at least 25 square feet of certified storage — and `FAIL` otherwise. The assessment starts `SUBMITTED`.

Acceptance is performed by a `HomeNurse` other than the assessor. The assessment must be `SUBMITTED` (`ERR_ASSESSMENT_INVALID_STATE`), its computed `result` must be `PASS` (`ERR_ASSESSMENT_RESULT_FAIL`), and the caller must not be the `assessed_by_user_id` (`ERR_SOD_ASSESSOR_SELF_ACCEPT`). Acceptance stamps `accepted_at` with the logical clock and fires a three-link cascade: any previously `ACCEPTED` assessment for the same patient becomes `SUPERSEDED` (its terminal state); the patient's `storage_cap_units` is recomputed from the newly accepted assessment; and a cap-shrink cascade sweeps the patient's open orders — every SupplyOrder in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` whose `on_hand_units` plus `provisional_total_units` now exceeds the shrunken cap is `CANCELLED`, together with any `SCHEDULED` delivery appointments on those orders. Posture is then recomputed. Assessment currency lasts 730 days from `accepted_at`, again strictly.

Alternatively, a `HomeNurse` other than the assessor may send a `SUBMITTED` assessment to `REMEDIATION_REQUIRED` (the same `ERR_ASSESSMENT_INVALID_STATE` and `ERR_SOD_ASSESSOR_SELF_ACCEPT` guards apply). The assessment gate itself is unchanged by this move: only a current `ACCEPTED` assessment satisfies it. While an assessment sits in `REMEDIATION_REQUIRED`, a `HomeNurse` opens HomeModificationWorkOrders against it, each carrying `patient_id`, the `assessment_id` of the assessment being remediated, a `work_type` of `PLUMBING`, `ELECTRICAL`, or `STORAGE_BUILDOUT`, and a `cost_estimate_cents` of zero or more; a new work order is `REQUESTED`.

Work orders follow their own small lifecycle. A `ProgramAdmin` approves and schedules one — from `REQUESTED`, or from `INSPECTED_FAIL` as a rework cycle — by storing `scheduled_window_start` and `scheduled_window_end`, which must be strictly ordered with the start before the end (`ERR_INVALID_REQUEST`); the order becomes `SCHEDULED`. A `BiomedTechnician` then completes a `SCHEDULED` order by recording `final_cost_cents` (zero or more, else `ERR_INVALID_REQUEST`), moving it to `COMPLETED`, and subsequently inspects a `COMPLETED` order with a `passed` flag — true moves it to `INSPECTED_PASS` and false to `INSPECTED_FAIL`. Cancellation by a `HomeNurse` or `ProgramAdmin` is allowed from `REQUESTED` or `SCHEDULED` and lands in `CANCELLED`. `INSPECTED_PASS` and `CANCELLED` are terminal. Any approve, complete, inspect, or cancel attempted from a state without that transition is `ERR_WORK_ORDER_INVALID_STATE`. Work orders are listable per patient (with optional `status` and `work_type` filters) and per assessment (filter `status`).

Resubmission returns a `REMEDIATION_REQUIRED` assessment to `SUBMITTED` with fresh measurements supplied in the payload (`water_chloramine_ppm`, `electrical_dedicated_circuit`, `electrical_voltage_verified`, `storage_area_sqft`). It is permitted only when every work order linked to the assessment is settled — `INSPECTED_PASS` or `CANCELLED`; anything still outstanding is rejected with `ERR_WORK_ORDERS_OUTSTANDING`. Resubmission replaces the measurement fields, recomputes `result` and `storage_cap_units`, and refreshes `assessed_by_user_id` to the resubmitting nurse, which means the next acceptance must again come from a different nurse. Assessments are retrievable individually and listable per patient with a `status` filter.

### 3.4. Machines, Maintenance, and Emergency Backup Plans

A `BiomedTechnician` registers each dialysis machine with `program_id`, `serial_number` (unique within its program — a duplicate is `ERR_SERIAL_NUMBER_EXISTS`), and `model`; a new machine is `IN_STOCK` and unassigned (`assigned_patient_id` null). Three figures are derived whenever the machine is read: `total_runtime_hours` is the sum of `duration_minutes` over every TreatmentLog recorded on the machine, across all log statuses, divided by sixty and carried at two decimal places; `runtime_hours_at_last_service` is the `runtime_hours_at_service` snapshot of the machine's latest `COMPLETED` MaintenanceEvent (ordered by `updated_at`, ties broken by `created_at`), or 0 when no event has ever completed; and `maintenance_due` is true exactly when the difference between the two is at least 500 hours — a machine at exactly 500.0 hours since service is due, because the comparison is inclusive.

Assignment is the first of the three optimistic-concurrency operations of §2.8. A `BiomedTechnician` assigns a machine by supplying `patient_id` and `expected_machine_version`; a version mismatch is `ERR_STALE_VERSION` (HTTP 412). Beyond that, the machine must be `IN_STOCK` or `ASSIGNED` (`ERR_MACHINE_INVALID_STATE`), it must not be maintenance-due (`ERR_MACHINE_MAINTENANCE_DUE`), and the target patient must exist and not be `TRANSITIONED_OUT` (`ERR_PATIENT_NOT_ACTIVE_HOME`). Assigning a machine that is already `ASSIGNED` to a *different* patient is a legitimate reassignment that supersedes the prior assignment; attempting to assign it to the patient who already holds it is a no-op rejection with `ERR_INVALID_REQUEST`. Either way, success writes `assigned_patient_id`, increments the machine's `version`, and recomputes posture — for the new patient, and on reassignment for the old patient as well, who immediately loses the machine gate. Unassignment moves an `ASSIGNED` machine back to `IN_STOCK` (`ERR_MACHINE_INVALID_STATE` from any other state), clears `assigned_patient_id`, increments `version`, and recomputes the former patient's posture. A `ProgramAdmin` may decommission an `IN_STOCK` machine (`ERR_MACHINE_INVALID_STATE` otherwise), but only while no EmergencyBackupPlan in `ACTIVE` or `EXPIRED` references it as its `backup_machine_id` (`ERR_MACHINE_REFERENCED_BY_PLAN`); decommissioning cancels the machine's `SCHEDULED` maintenance events and lands the machine in the terminal `DECOMMISSIONED` state.

Maintenance events are scheduled by a `BiomedTechnician` with `machine_id`, an `event_type` of `PREVENTIVE`, `REPAIR`, or `DECONTAMINATION`, and a service window `window_start` to `window_end` (the end must be strictly after the start, else `ERR_INVALID_REQUEST`). Maintenance windows on a machine are **closed intervals**: a new event whose window touches or overlaps another `SCHEDULED` or `IN_PROGRESS` event on the same machine — endpoint contact counts as conflict here — is rejected with `ERR_EVENT_WINDOW_OVERLAP`. Starting an event requires it to be `SCHEDULED` and the machine to be `IN_STOCK` or `ASSIGNED` (an `UNDER_MAINTENANCE` or `DECOMMISSIONED` machine yields `ERR_EVENT_INVALID_STATE`), requires that no other event is already `IN_PROGRESS` on the same machine (`ERR_MACHINE_BUSY_MAINTENANCE`), and requires the current clock to be no later than `window_end` (`ERR_EVENT_WINDOW_PASSED`). On start the machine moves to `UNDER_MAINTENANCE`, retaining any `assigned_patient_id`; because the posture machine gate requires status `ASSIGNED`, an assigned patient's posture degrades to `AT_RISK` for the duration of the work. Completing an `IN_PROGRESS` event snapshots `runtime_hours_at_service` from the machine's current `total_runtime_hours`, returns the machine to `ASSIGNED` when an assignment is still recorded and to `IN_STOCK` otherwise, recomputes `maintenance_due` (now false until another 500 hours accrue), and recomputes the assigned patient's posture. A `SCHEDULED` event may be cancelled by a `BiomedTechnician`; events are also cancelled by the system when their machine is decommissioned or when a transition activation unassigns the machine (§3.9). Events are listable per machine with `status` and `event_type` filters; the logs recorded on a machine are listable with a `status` filter; the plans referencing a machine are listable with a `status` filter; and the machines currently or previously assigned to a patient are listable with a `status` filter — filtering to `ASSIGNED` isolates the current machine.

Every home patient must have an EmergencyBackupPlan. A `HomeNurse` creates one with `patient_id`, a `plan_mode` of `IN_CENTER_CHAIR`, `BACKUP_MACHINE`, or `BOTH`, and — as the second optimistic-concurrency operation of §2.8 — `expected_patient_version`; a stale patient version is rejected with `ERR_STALE_VERSION` (HTTP 412). Unless the mode is `IN_CENTER_CHAIR`, a `backup_machine_id` is required (`ERR_BACKUP_MACHINE_REQUIRED`) and must reference a machine currently `IN_STOCK` (`ERR_BACKUP_MACHINE_NOT_IN_STOCK`). Creation supersedes the patient's prior plan: a previous `ACTIVE` or `EXPIRED` plan becomes `SUPERSEDED`, the new plan starts `ACTIVE` with `last_drill_at` set to the current clock, the patient's `version` increments, and posture is recomputed. Plans age lazily: once the clock reaches ninety days past `last_drill_at`, the plan reads as `EXPIRED` and the plan gate is lost at the next posture evaluation. A `HomeNurse` records an emergency drill on a plan that is `ACTIVE` or `EXPIRED` — on `SUPERSEDED` or `CLOSED` plans the drill is rejected with `ERR_PLAN_NOT_ACTIVE` — which sets `last_drill_at` to now, returns an `EXPIRED` plan to `ACTIVE`, and recomputes posture. When a patient reaches `TRANSITIONED_OUT`, the plan — `ACTIVE` or `EXPIRED` — moves to the terminal `CLOSED` state; during a merely temporary center stay the plan is retained and its drill clock keeps running (§3.9). A patient's plans are listable with a `status` filter, with lazy expiry applied at read.

### 3.5. The Monthly Order and Delivery Cycle

The supply order is the program's monthly commercial heartbeat. A patient (owning the record per §2.1) creates a draft with `patient_id`, an `order_month` in `YYYY-MM` form, order `lines` — each naming a `sku` from the program catalog and a `quantity` of at least 1 — and `expected_patient_version` (the third optimistic-concurrency operation of §2.8; a stale patient version is `ERR_STALE_VERSION`, HTTP 412). The month may not lie before the current clock month, at creation or at submission (`ERR_ORDER_MONTH_IN_PAST`). Creation is a create-with-supersede: if a `DRAFT` order already exists for the same patient and month, it becomes `SUPERSEDED`; but if an order for that patient and month exists in `SUBMITTED`, `APPROVED`, or `CLOSED`, creation is rejected outright with `ERR_MONTH_ORDER_EXISTS`. The new order starts `DRAFT` on the lifecycle axis and `UNFULFILLED` on the delivery axis, with `delivered_units_total` at 0, and the patient's `version` increments.

The order's money fields are computed on creation and recomputed on every line edit. `provisional_total_units` is the sum of the line quantities. `subtotal_cents` is each line's quantity multiplied by its catalog `unit_price_cents`, summed exactly. `handling_fee_cents` is a 500-cent base plus a per-line charge: each line's quantity multiplied by its catalog `handling_rate_cents`, rounded half up to whole cents per line, and only then summed — the per-line rounding discipline of §2.9 is pinned, so two lines rated 10.5 and 12.5 cents contribute 11 and 13, never a rounded-down 23. `discount_cents` is five percent of the subtotal rounded half up when the subtotal reaches twenty thousand cents, and zero otherwise; eligibility is keyed on `subtotal_cents` and never on the post-discount total, so an order sitting exactly at the threshold receives its discount. Finally `grand_total_cents` is the subtotal minus the discount plus the handling fee. A patient edits `lines` while the order is `DRAFT` or `CHANGES_REQUESTED` (from any other state, `ERR_ORDER_INVALID_STATE`); editing a `CHANGES_REQUESTED` order returns it to `DRAFT`, and every edit recomputes all money fields.

Submission runs a gate ladder in a pinned order, and the state check outranks every business check: the order must be `DRAFT` or `CHANGES_REQUESTED` (`ERR_ORDER_INVALID_STATE`); the month must not be in the past (`ERR_ORDER_MONTH_IN_PAST`); the patient's posture must be `HOME_READY` or `AT_RISK` (`ERR_POSTURE_NOT_ORDERABLE`); the lines must be non-empty with every `sku` in the catalog and every `quantity` at least 1 (`ERR_INVALID_REQUEST`); no other order for the same patient and month may sit in `SUBMITTED`, `APPROVED`, or `CLOSED` (`ERR_MONTH_ORDER_EXISTS`); and then the two quota bounds, storage before allowance. At the moment of submission two values are evaluated and stored on the order: `standard_allowance_units`, the patient's current `prescription_treatments_per_week` times four weeks times `prescription_units_per_treatment` — a forward-looking figure that ignores what actually happened and is never recomputed after a later prescription change — and `carried_adjustment_units`, the `adjustment_units` of the patient's `CLOSED` order for the calendar month immediately preceding `order_month`, or 0 when no such order exists (a first month carries 0). The storage bound compares physical room: if `on_hand_units` plus `provisional_total_units` exceeds `storage_cap_units`, submission is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`. Only if storage passes does the allowance bound apply: if `provisional_total_units` exceeds `standard_allowance_units` plus `carried_adjustment_units`, the rejection is `ERR_ALLOWANCE_EXCEEDED`. On success the order moves to `SUBMITTED`.

Review belongs to a `SupplyCoordinator` acting on a `SUBMITTED` order. The `decision` must be `APPROVE` or `REQUEST_CHANGES` (anything else is `ERR_INVALID_REQUEST`); `APPROVE` moves the order to `APPROVED` and `REQUEST_CHANGES` moves it to `CHANGES_REQUESTED`, and an optional `note` is stored as the order's `review_note`. Cancellation — by the patient or a `SupplyCoordinator` — is available from `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `APPROVED` (`ERR_ORDER_INVALID_STATE` otherwise) and lands in `CANCELLED`; cancelling a `DRAFT`, `SUBMITTED`, or `APPROVED` order also cancels its `SCHEDULED` delivery appointments.

Closing is the month-end reconciliation, performed by a `SupplyCoordinator`. The order must be `APPROVED` (`ERR_ORDER_INVALID_STATE`), the first day of the month after `order_month` must have been reached on the logical clock (`ERR_MONTH_NOT_ENDED`), and no `SCHEDULED` delivery appointment may remain on the order (`ERR_OPEN_APPOINTMENTS_EXIST`). At close the system replays the month: `actualized_units` is the sum of `consumption_units` over the patient's TreatmentLog rows dated inside the order month, first and last day inclusive, across every log status — `SUBMITTED`, `REVIEWED`, and `FLAGGED` alike; and `adjustment_units` is `actualized_units` minus the stored `standard_allowance_units`, which may be negative. That delta is exactly what the next month's `carried_adjustment_units` picks up, so a patient who under-consumed finds next month's allowance room reduced, and one who over-consumed finds it enlarged. The order lands in the terminal `CLOSED` state.

The order row thus carries two independent axes on one record: `order_status` (the lifecycle: `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED`, `CLOSED`, `SUPERSEDED`, `CANCELLED`) and `fulfillment_status` (delivery progress: `UNFULFILLED`, `PARTIALLY_DELIVERED`, `DELIVERED`). Fulfillment transitions never change `order_status`, and lifecycle transitions never change `fulfillment_status`; both are readable on the same entity.

Deliveries execute against an `APPROVED` order. A `SupplyCoordinator` schedules a DeliveryAppointment with `supply_order_id`, `window_start`, and `window_end`; the order must be `APPROVED` (`ERR_ORDER_INVALID_STATE`), at most one appointment per order may be `SCHEDULED` at a time (`ERR_ACTIVE_APPOINTMENT_EXISTS`), the `window_start` must not be in the past and its calendar date must fall inside the order month (`ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH`), and the window must run at least 120 and at most 720 minutes with the end after the start (`ERR_INVALID_REQUEST`). Completing a `SCHEDULED` appointment records `delivered_units`, which must be at least 1 and at most the order's remaining undelivered units — `provisional_total_units` minus `delivered_units_total` — with any other value rejected as `ERR_DELIVERED_UNITS_INVALID`. Each completion adds the delivered units to the order's `delivered_units_total` and to the patient's `on_hand_units`, and advances the fulfillment axis: `UNFULFILLED` to `PARTIALLY_DELIVERED` on a partial completion, further partial completions holding at `PARTIALLY_DELIVERED`, a completion that brings the cumulative total to the full `provisional_total_units` moving the axis to `DELIVERED` — including directly from `UNFULFILLED` when a single appointment delivers the whole order. A `SupplyCoordinator` may instead fail a `SCHEDULED` appointment with a non-empty `failure_reason` (`ERR_INVALID_REQUEST`), or cancel it; appointments are also cancelled by the system when their order is cancelled, when the cap-shrink cascade of §3.3 cancels the order, or when a transition activation cascades (§3.9). Complete, fail, or cancel from a non-`SCHEDULED` appointment is `ERR_APPOINTMENT_INVALID_STATE`. Appointments are listable per order with a `status` filter, and orders are listable per patient with `order_month` and `order_status` filters.

### 3.6. Treatment Logging and Clinical Review

Day-to-day care produces the TreatmentLog. A patient — who must be `ACTIVE_HOME` (`ERR_PATIENT_NOT_ACTIVE_HOME`) — submits a log with `patient_id`, `machine_id`, `treatment_date`, `duration_minutes`, and `consumption`. The machine must currently be `ASSIGNED` to this very patient (`ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT`). The `treatment_date` is a `YYYY-MM-DD` calendar date that may not lie after the current clock date (`ERR_LOG_DATE_IN_FUTURE`), and at most one log exists per patient per date (`ERR_DUPLICATE_TREATMENT_DATE`). `duration_minutes` runs from 30 to 600. The `consumption` array lists `{sku, units}` pairs drawn from the program catalog, each with `units` at least 1, and may be empty. The server sums the lines into `consumption_units`, requires that sum to fit within the patient's `on_hand_units` (`ERR_QUANTITY_EXCEEDS_ON_HAND`), and debits it immediately; the machine's runtime recomputes from the new log, and posture recomputes. The log starts `SUBMITTED`.

On-hand inventory is a strict accounting identity, recomputed from the ledger of physical events: the units delivered across the patient's `DELIVERED` appointments, minus the `consumption_units` of all the patient's logs regardless of status, minus the `total_units` of the patient's `CREDITED` or `VERIFIED` waste-return records. `REJECTED` records contribute nothing. Mutation-time guards keep the figure from ever going negative — log creation and waste reporting both require the debited amount to fit within the current on-hand.

Log review is nurse work: a `HomeNurse` marks a `SUBMITTED` log `REVIEWED`, or flags it with a non-empty `flag_note`, moving it to `FLAGGED`. A flagged log returns to `SUBMITTED` only through amendment by the patient, who may supply a corrected `duration_minutes` and `consumption`. Amendment settles inventory by restore-then-subtract: the old `consumption_units` are first credited back to `on_hand_units`, then the new sum is subtracted — and the net increase must fit within the on-hand balance, else `ERR_QUANTITY_EXCEEDS_ON_HAND`. The machine's runtime recomputes from the amended duration, and the `flag_note` is cleared. Mark-reviewed or flag on a non-`SUBMITTED` log, or amend on a non-`FLAGGED` log, is `ERR_LOG_INVALID_STATE`. A patient's logs are listable with `status` and `treatment_date` filters.

Logging cadence is monitored two ways. The first is the instantaneous `missed_log_streak`: the expected interval between logs is seven days divided by the patient's `prescription_treatments_per_week`, rounded down to whole days but never less than one day; the anchor is the `treatment_date` of the patient's latest log of any status, or the date of the patient's `created_at` when no logs exist; silence is the whole days from the anchor to the current clock date, never negative; and the streak is that silence divided by the expected interval, rounded down. A streak greater than or equal to the program's `max_missed_log_streak` contributes `AT_RISK` at rung 5 of the posture ladder — a patient who logged today has streak 0 even after a bad month. The second monitor is the cadence trigger on log creation: after inserting the new log, the server counts the patient's logs in `SUBMITTED` or `FLAGGED`, and when that count reaches the program's `review_cadence_treatments` while no `PENDING` review exists for the patient, it opens a ClinicalReview with `due_reason` `CADENCE`, `period_start` set to the day after the latest prior review's `period_end` (or the date of the patient's `created_at` when there is no prior review), `period_end` set to the new log's `treatment_date`, and `due_at` set to five days after creation.

ClinicalReview rows are always system-created — there is no endpoint that opens one directly. The review carries its `patient_id`, the covered `period_start` and `period_end`, its `due_reason` (`CADENCE` or `ESCALATION`), the `due_at` deadline, and — all null until sign-off — its `outcome`, `adherence_rolling_pct`, and `signed_off_at`. Sign-off belongs to the `Nephrologist` and requires the review `PENDING` (`ERR_REVIEW_NOT_PENDING`), an `outcome` drawn from `CONTINUE`, `MODIFY_PRESCRIPTION`, `REQUIRE_RETRAINING`, or `RECOMMEND_TRANSITION` (`ERR_INVALID_REQUEST`), and a clean period: no log of the patient dated inside the inclusive period may remain `SUBMITTED` or `FLAGGED` (`ERR_UNREVIEWED_LOGS_REMAIN`). At sign-off the server stamps `signed_off_at`, clears the patient's `waste_alert_active` latch, computes `adherence_rolling_pct`, and recomputes posture. The rolling adherence looks back over the trailing 28 calendar days ending at the clock date: the scheduled count is `prescription_treatments_per_week` times four, the actual count is the number of the patient's logs of any status with `treatment_date` inside the window, and the percentage is the smaller of actual and scheduled divided by scheduled, times one hundred, rounded half up to one decimal place — so a patient who logged five times early in the window and then fell silent reports 41.7 against a thrice-weekly prescription, even as the streak monitor escalates. If the outcome is `REQUIRE_RETRAINING`, the patient's `retraining_required` latch sets, which drives posture to `BLOCKED` at the next evaluation until any passing attempt is signed off (§3.2).

Escalation is the sharp edge: a `HomeNurse` or `Nephrologist` may escalate a `PENDING` review to `ESCALATED`. The open-escalation condition of the posture ladder now holds, so posture recomputes to `BLOCKED`, and the escalation cascade cancels the patient's open orders in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` — `APPROVED` orders are deliberately untouched. A `PENDING` review whose `due_at` passes without sign-off also blocks posture (rung 4) until it is resolved. Reviews are listable per patient with `status` and `due_reason` filters, with lazy overdue evaluation applied at read.

### 3.7. In-Center Backup Slot Reservations

When a home patient needs a chair in the center — the `IN_CENTER_CHAIR` leg of the backup plan — the program books slots against registered InCenterChairs. A `ProgramAdmin` registers each chair with `program_id` and a `chair_code` unique within the program (a duplicate is `ERR_INVALID_REQUEST`); `in_service` defaults to true, and a `ProgramAdmin` toggles it to take a chair out of service or return it. Booking is done by the patient, who must own the reservation and be `ACTIVE_HOME` (`ERR_PATIENT_NOT_ACTIVE_HOME`), supplying `patient_id`, `chair_id`, `slot_start`, and `slot_end`. The guards, in their pipeline stages: an `ACTIVE` EmergencyBackupPlan must exist for the patient (`ERR_PLAN_NOT_ACTIVE`); the chair must be in service (`ERR_CHAIR_OUT_OF_SERVICE`); `slot_start` must not lie before the current clock (`ERR_SLOT_IN_PAST`); the slot must run at least 60 and at most 480 minutes (`ERR_SLOT_DURATION_INVALID`); and the new slot must not collide — chair slots are **half-open intervals**, so a reservation starting exactly when another ends is adjacency, not conflict, while a genuine intersection with another `RESERVED` reservation on the same chair is `ERR_CHAIR_SLOT_OVERLAP`. Finally, a patient may hold at most two `RESERVED` reservations on the same calendar service day (`ERR_SLOT_DAILY_CAP_EXCEEDED`). A successful booking is `RESERVED`.

The patient cancels a reservation only while the clock is still before `slot_start` (`ERR_SLOT_TOO_LATE_TO_CANCEL`), and only from `RESERVED` (`ERR_SLOT_INVALID_STATE`); a `HomeNurse` marks attendance by moving `RESERVED` to `COMPLETED`. Lazily, once the clock passes `slot_end` on a still-`RESERVED` reservation, it reads as `NO_SHOW` and the patient's `no_show_count` increments by one. Transition activation (§3.9) cancels the patient's future `RESERVED` reservations. Reservations are listable per patient and per chair with a `status` filter, with lazy no-show applied at read.

### 3.8. Waste Reporting, Returns, and Crediting

Spoiled, expired, or unused supplies are reported by the patient as a WasteReturnRecord: `patient_id`, a `record_type` of `WASTE` or `RETURN`, an `activity_month` in `YYYY-MM` form that buckets the record for ratio and credit accounting, and `lines` of `{sku, units, expired}` — catalog skus, `units` at least 1, and an `expired` flag per line (expired return lines earn zero credit). The server sums the lines into `total_units` and requires it to fit within the patient's `on_hand_units` (`ERR_QUANTITY_EXCEEDS_ON_HAND`), but nothing leaves on-hand at report time. The record starts `REPORTED`.

Verification belongs to the `SupplyCoordinator`, who passes an `approved` flag on a `REPORTED` record (`ERR_WASTE_RECORD_NOT_REPORTED` from any other state). Rejection — `approved` false — lands the record in `REJECTED`: no on-hand change, no credit, and no effect on any accounting ever after. Approval of a `WASTE` record lands it in `VERIFIED`: the `total_units` leave the patient's on-hand balance, `credit_cents` stays 0, and the month's waste ratio re-evaluates. That ratio divides the verified waste of the month — the summed `total_units` of the patient's `VERIFIED` `WASTE` records with this `activity_month`, including the one just verified — by the units delivered in the month (the summed `delivered_units` of the patient's `DELIVERED` appointments whose `window_start` date falls inside `activity_month`), and is defined as 0 when nothing was delivered. When the ratio reaches the program's `waste_ratio_alert_threshold` — the comparison is inclusive — the patient's `waste_alert_active` latches true and, if no `PENDING` review exists for the patient, an `ESCALATION` ClinicalReview is created; posture recomputes, and the alert persists until the next review sign-off clears it (§3.6).

Approval of a `RETURN` record lands it in `CREDITED`: the `total_units` leave on-hand and `credit_cents` is computed. The credit first establishes **delivered attribution** for the month, and the attribution order is pinned: each `DELIVERED` appointment's `delivered_units` are allocated to its order's lines in stored line order, each line filled up to its `quantity` before the next line receives any units; a sku's delivered-in-month figure is then the total units allocated to it across the patient's `DELIVERED` appointments whose `window_start` date falls inside `activity_month`. With attribution in hand, the record's lines are credited in request order. An `expired` line earns zero. For any other line, the eligible units are the line's `units` capped by the sku's delivered-in-month units not already covered by the patient's previously `CREDITED` return lines for the same month and sku, and never below zero. A full-credit allowance of ten units per sku per month applies: units previously credited for that sku and month consume the allowance (counted only up to ten), and the full-credit portion of this line is the smaller of its eligible units and the allowance remaining. Whatever eligible units exceed the full-credit portion form the overage. The line's credit is the full-credit portion times the catalog `unit_credit_cents`, plus the overage times `unit_credit_cents` times one half, that overage product rounded half up to whole cents; `credit_cents` sums the line credits — per-line rounding, then summation, the same discipline as the handling fee. Records are listable per patient with `record_type`, `status`, and `activity_month` filters.

### 3.9. Transitions Between Home and Center Care

A transition records a move between home and in-center dialysis with a coded reason. A patient or a `Nephrologist` requests one with `patient_id`, a `direction` of `HOME_TO_CENTER` or `CENTER_TO_HOME`, a `reason_code` of `PATIENT_CHOICE`, `MEDICAL_COMPLICATION`, `SUPPLY_FAILURE`, `MACHINE_FAILURE`, `HOME_UNSUITABLE`, `TRAINING_INCOMPLETE`, or `NON_ADHERENCE`, an `effective_from` activation date, an optional `effective_to` end date, and — for reversals — a `reversal_of_id`. The shape rules come first: a temporary `HOME_TO_CENTER` requires `effective_to` strictly after `effective_from`; a permanent `HOME_TO_CENTER` leaves `effective_to` null; a `CENTER_TO_HOME` must leave `effective_to` null; violations of these range rules are `ERR_INVALID_EFFECTIVE_RANGE`. A `CENTER_TO_HOME` without `reversal_of_id` is `ERR_REVERSAL_TARGET_REQUIRED`, and the referenced record must be an `ACTIVE` `HOME_TO_CENTER` transition of the same patient (`ERR_REVERSAL_TARGET_INVALID`) — the link is self-referential, record to record. The `MEDICAL_COMPLICATION` reason may be requested only by a `Nephrologist` (`ERR_REASON_REQUIRES_PHYSICIAN`). Three reasons must be substantiated by recent history, else `ERR_REASON_NOT_SUBSTANTIATED`: `MACHINE_FAILURE` requires a `REPAIR` maintenance event `IN_PROGRESS` or `COMPLETED` on the patient's assigned machine with `window_end` within the last thirty days; `SUPPLY_FAILURE` requires a `FAILED` delivery appointment with `window_start` within the last thirty days; and `TRAINING_INCOMPLETE` requires the patient's posture to currently be `NOT_READY`. One more guard: a new `HOME_TO_CENTER` is rejected with `ERR_OPEN_TRANSITION_EXISTS` while another `HOME_TO_CENTER` for the patient sits in `REQUESTED`, `APPROVED`, or `ACTIVE` and not reversed. A new record is `REQUESTED`.

A `Nephrologist` approves or denies a `REQUESTED` record (`ERR_TRANSITION_INVALID_STATE` from any other state), moving it to `APPROVED` or the terminal `DENIED`. Activation, also by a `Nephrologist`, requires the record `APPROVED` (`ERR_TRANSITION_INVALID_STATE`), the `effective_from` date reached on the logical clock (`ERR_TRANSITION_EFFECTIVE_IN_FUTURE`), and a compatible patient state — `HOME_TO_CENTER` requires `ACTIVE_HOME` or `SUSPENDED`, while `CENTER_TO_HOME` requires `SUSPENDED` (`ERR_PATIENT_STATE_BLOCKS_TRANSITION`).

Activating a `HOME_TO_CENTER` fires the full cascade. A temporary transition (one with an `effective_to`) drops the patient to `SUSPENDED`; a permanent one moves the patient to the terminal `TRANSITIONED_OUT` — including directly from `SUSPENDED` when the patient was already suspended. In both cases the assigned machine returns from `ASSIGNED` to `IN_STOCK` with `assigned_patient_id` cleared (when the machine is already `IN_STOCK` this first link is inert and only the remaining cascades fire), that machine's `SCHEDULED` maintenance events are cancelled, every open order in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `APPROVED` is cancelled together with its `SCHEDULED` delivery appointments, and the patient's future `RESERVED` slot reservations are cancelled. A permanent transition additionally closes the emergency plan — `ACTIVE` or `EXPIRED` becomes `CLOSED` — while a temporary one retains the plan and lets the drill clock keep running. This stands in deliberate contrast to a manual suspend (§3.1), which touches none of these.

Activating a `CENTER_TO_HOME` reversal re-checks all four readiness gates of §2.10 — certification current, assessment current, machine assigned, plan active — so the machine must have been re-assigned and the plan re-drilled beforehand; any gate failure is `ERR_READINESS_GATES_NOT_MET`. On success the patient returns from `SUSPENDED` to `ACTIVE_HOME`, and the reversed `HOME_TO_CENTER` record flips from `ACTIVE` to `REVERSED`.

A temporary transition completes lazily: once the clock passes `effective_to`, the record moves from `ACTIVE` to `COMPLETED` and the patient returns from `SUSPENDED` to `ACTIVE_HOME` with **no** readiness-gate recheck — the posture recompute applies and may well land the patient at `AT_RISK`. Records are retrievable individually and listable per patient with `status` and `direction` filters, with lazy completion applied at read; the reversals referencing a given record are listable as well.

## 4. Endpoint Definitions

Successful operations that create a new resource return HTTP 201; all other successful operations — reads, state transitions, edits, and the clock set — return HTTP 200. Error responses follow the envelope of §2.2 with the codes of §5. Request bodies, response payloads, filters, and side effects are defined by the workflows of §3; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/dialysis-programs` | Create a dialysis program with cadence/threshold config and supply catalog | ProgramAdmin |
| GET | `/api/dialysis-programs/{id}` | Get a program | All roles |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving; startup default 2026-05-01T00:00:00Z) | ProgramAdmin |
| GET | `/api/dialysis-programs/{id}/patients` | List patients of a program | All roles |
| GET | `/api/dialysis-programs/{id}/dialysis-machines` | List machines of a program | All roles |
| GET | `/api/dialysis-programs/{id}/in-center-chairs` | List chairs of a program | All roles |
| POST | `/api/patients` | Enroll a patient (intake with initial prescription) | HomeNurse |
| GET | `/api/patients/{id}` | Get a patient (posture, streak, and lazy states re-evaluated at read) | All roles |
| PATCH | `/api/patients/{id}/prescription` | Update prescription (affects future submit-time allowance evaluations only) | Nephrologist |
| POST | `/api/patients/{id}/activate` | TRAINING → ACTIVE_HOME (four readiness gates) | Nephrologist |
| POST | `/api/patients/{id}/suspend` | ACTIVE_HOME → SUSPENDED (manual; keeps machine, plans, orders) | Nephrologist |
| POST | `/api/patients/{id}/reinstate` | SUSPENDED → ACTIVE_HOME (no ACTIVE HOME_TO_CENTER; gates re-checked) | Nephrologist |
| POST | `/api/training-attempts` | Record a training attempt (trainer = caller) | HomeNurse |
| POST | `/api/training-attempts/{id}/sign-off` | Sign off a passing attempt; signer must differ from trainer | HomeNurse |
| GET | `/api/patients/{id}/training-attempts` | List a patient's training attempts | All roles |
| POST | `/api/home-assessments` | Submit a home assessment (result and storage cap computed; assessor = caller) | HomeNurse |
| GET | `/api/home-assessments/{id}` | Get an assessment | All roles |
| GET | `/api/patients/{id}/home-assessments` | List a patient's assessments | All roles |
| POST | `/api/home-assessments/{id}/accept` | Accept a PASS assessment; supersedes prior ACCEPTED; cap-shrink cascade | HomeNurse |
| POST | `/api/home-assessments/{id}/require-remediation` | SUBMITTED → REMEDIATION_REQUIRED (not the assessor) | HomeNurse |
| POST | `/api/home-assessments/{id}/resubmit` | REMEDIATION_REQUIRED → SUBMITTED with new measurements | HomeNurse |
| POST | `/api/home-modification-work-orders` | Open a remediation work order against a REMEDIATION_REQUIRED assessment | HomeNurse |
| GET | `/api/patients/{id}/home-modification-work-orders` | List a patient's work orders | All roles |
| GET | `/api/home-assessments/{id}/home-modification-work-orders` | List work orders linked to an assessment | All roles |
| POST | `/api/home-modification-work-orders/{id}/approve` | Approve and schedule (REQUESTED → SCHEDULED; INSPECTED_FAIL → SCHEDULED rework) | ProgramAdmin |
| POST | `/api/home-modification-work-orders/{id}/complete` | SCHEDULED → COMPLETED with final cost | BiomedTechnician |
| POST | `/api/home-modification-work-orders/{id}/inspect` | COMPLETED → INSPECTED_PASS (passed=true) or INSPECTED_FAIL (passed=false) | BiomedTechnician |
| POST | `/api/home-modification-work-orders/{id}/cancel` | REQUESTED or SCHEDULED → CANCELLED | HomeNurse, ProgramAdmin |
| POST | `/api/dialysis-machines` | Register a machine (IN_STOCK) | BiomedTechnician |
| GET | `/api/dialysis-machines/{id}` | Get a machine (runtime and maintenance_due recomputed at read) | All roles |
| POST | `/api/dialysis-machines/{id}/assign` | Assign to a patient; from ASSIGNED reassigns; OCC on machine version | BiomedTechnician |
| POST | `/api/dialysis-machines/{id}/unassign` | ASSIGNED → IN_STOCK | BiomedTechnician |
| POST | `/api/dialysis-machines/{id}/decommission` | IN_STOCK → DECOMMISSIONED; SCHEDULED events cancelled | ProgramAdmin |
| GET | `/api/dialysis-machines/{id}/maintenance-events` | List a machine's maintenance events | All roles |
| GET | `/api/dialysis-machines/{id}/treatment-logs` | List treatment logs recorded on a machine | All roles |
| GET | `/api/dialysis-machines/{id}/emergency-backup-plans` | List backup plans referencing a machine | All roles |
| GET | `/api/patients/{id}/dialysis-machines` | List machines currently or previously assigned to a patient | All roles |
| POST | `/api/maintenance-events` | Schedule a maintenance event (closed-interval overlap check) | BiomedTechnician |
| POST | `/api/maintenance-events/{id}/start` | SCHEDULED → IN_PROGRESS; machine → UNDER_MAINTENANCE | BiomedTechnician |
| POST | `/api/maintenance-events/{id}/complete` | IN_PROGRESS → COMPLETED; runtime snapshot; machine status restored | BiomedTechnician |
| POST | `/api/maintenance-events/{id}/cancel` | SCHEDULED → CANCELLED | BiomedTechnician |
| POST | `/api/emergency-backup-plans` | Create a plan (ACTIVE); supersedes prior ACTIVE/EXPIRED plan; OCC on patient version | HomeNurse |
| POST | `/api/emergency-backup-plans/{id}/drill` | Record an emergency drill; EXPIRED → ACTIVE or ACTIVE refresh | HomeNurse |
| GET | `/api/patients/{id}/emergency-backup-plans` | List a patient's plans (lazy EXPIRED applied) | All roles |
| POST | `/api/supply-orders` | Create a DRAFT monthly order; supersedes an existing DRAFT; OCC on patient version | Patient |
| GET | `/api/supply-orders/{id}` | Get an order (both status axes) | All roles |
| GET | `/api/patients/{id}/supply-orders` | List a patient's orders | All roles |
| PATCH | `/api/supply-orders/{id}` | Edit lines in DRAFT or CHANGES_REQUESTED (latter returns to DRAFT); money recomputed | Patient |
| POST | `/api/supply-orders/{id}/submit` | DRAFT or CHANGES_REQUESTED → SUBMITTED through the full gate ladder | Patient |
| POST | `/api/supply-orders/{id}/review` | SUBMITTED → APPROVED (APPROVE) or CHANGES_REQUESTED (REQUEST_CHANGES) | SupplyCoordinator |
| POST | `/api/supply-orders/{id}/cancel` | Cancel from DRAFT, SUBMITTED, CHANGES_REQUESTED, or APPROVED | Patient, SupplyCoordinator |
| POST | `/api/supply-orders/{id}/close` | APPROVED → CLOSED after month end; actualized reconciliation | SupplyCoordinator |
| POST | `/api/delivery-appointments` | Schedule a delivery for an APPROVED order (one SCHEDULED per order) | SupplyCoordinator |
| GET | `/api/supply-orders/{id}/delivery-appointments` | List an order's delivery appointments | All roles |
| POST | `/api/delivery-appointments/{id}/complete` | SCHEDULED → DELIVERED with delivered_units; on-hand and fulfillment updated | SupplyCoordinator |
| POST | `/api/delivery-appointments/{id}/fail` | SCHEDULED → FAILED | SupplyCoordinator |
| POST | `/api/delivery-appointments/{id}/cancel` | SCHEDULED → CANCELLED | SupplyCoordinator |
| POST | `/api/treatment-logs` | Submit a treatment log; consumption debited; cadence review evaluated | Patient |
| GET | `/api/patients/{id}/treatment-logs` | List a patient's treatment logs | All roles |
| POST | `/api/treatment-logs/{id}/mark-reviewed` | SUBMITTED → REVIEWED | HomeNurse |
| POST | `/api/treatment-logs/{id}/flag` | SUBMITTED → FLAGGED | HomeNurse |
| POST | `/api/treatment-logs/{id}/amend` | FLAGGED → SUBMITTED with corrected fields; restore-then-subtract | Patient |
| GET | `/api/patients/{id}/clinical-reviews` | List a patient's clinical reviews (system-created) | All roles |
| POST | `/api/clinical-reviews/{id}/sign-off` | PENDING → SIGNED_OFF; computes rolling adherence; period logs must be reviewed | Nephrologist |
| POST | `/api/clinical-reviews/{id}/escalate` | PENDING → ESCALATED; posture BLOCKED; open non-approved orders cancelled | HomeNurse, Nephrologist |
| POST | `/api/in-center-chairs` | Register an in-center chair | ProgramAdmin |
| GET | `/api/in-center-chairs/{id}` | Get a chair | All roles |
| PATCH | `/api/in-center-chairs/{id}` | Toggle in_service | ProgramAdmin |
| POST | `/api/backup-slot-reservations` | Book an in-center backup slot (plan, chair, overlap, daily-cap guards) | Patient |
| GET | `/api/patients/{id}/backup-slot-reservations` | List a patient's reservations (lazy NO_SHOW applied) | All roles |
| GET | `/api/in-center-chairs/{id}/backup-slot-reservations` | List a chair's reservations (lazy NO_SHOW applied) | All roles |
| POST | `/api/backup-slot-reservations/{id}/cancel` | RESERVED → CANCELLED (before slot start) | Patient |
| POST | `/api/backup-slot-reservations/{id}/complete` | RESERVED → COMPLETED (nurse marks attendance) | HomeNurse |
| POST | `/api/waste-return-records` | Report waste or a return (no on-hand change until verified) | Patient |
| GET | `/api/patients/{id}/waste-return-records` | List a patient's waste and return records | All roles |
| POST | `/api/waste-return-records/{id}/verify` | REPORTED → CREDITED (RETURN), VERIFIED (WASTE), or REJECTED | SupplyCoordinator |
| POST | `/api/transition-records` | Request a transition with reason coding and substantiation | Patient, Nephrologist |
| GET | `/api/transition-records/{id}` | Get a transition record (lazy COMPLETED applied) | All roles |
| GET | `/api/patients/{id}/transition-records` | List a patient's transitions (lazy COMPLETED applied) | All roles |
| GET | `/api/transition-records/{id}/reversals` | List CENTER_TO_HOME reversals referencing this transition | All roles |
| POST | `/api/transition-records/{id}/approve` | REQUESTED → APPROVED | Nephrologist |
| POST | `/api/transition-records/{id}/deny` | REQUESTED → DENIED | Nephrologist |
| POST | `/api/transition-records/{id}/activate` | APPROVED → ACTIVE once effective_from reached; fires the full cascade | Nephrologist |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status. Trigger conditions are defined where each guard lives — §2 for pipeline-wide rules and §3 for workflow-specific rules.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_EFFECTIVE_RANGE` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TRAINING_INCOMPLETE` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_CURRENT` | 409 Conflict |
| `ERR_NO_MACHINE_ASSIGNED` | 409 Conflict |
| `ERR_NO_ACTIVE_PLAN` | 409 Conflict |
| `ERR_READINESS_GATES_NOT_MET` | 409 Conflict |
| `ERR_ACTIVE_TRANSITION_BLOCKS_REINSTATE` | 409 Conflict |
| `ERR_PATIENT_NOT_ACTIVE_HOME` | 409 Conflict |
| `ERR_PATIENT_INVALID_STATE` | 409 Conflict |
| `ERR_ATTEMPT_NOT_RECORDED` | 409 Conflict |
| `ERR_ATTEMPT_NOT_PASSING` | 409 Conflict |
| `ERR_SOD_SIGNOFF_BY_TRAINER` | 403 Forbidden |
| `ERR_SOD_ASSESSOR_SELF_ACCEPT` | 403 Forbidden |
| `ERR_ASSESSMENT_RESULT_FAIL` | 409 Conflict |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_WORK_ORDERS_OUTSTANDING` | 409 Conflict |
| `ERR_WORK_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_MACHINE_INVALID_STATE` | 409 Conflict |
| `ERR_MACHINE_MAINTENANCE_DUE` | 409 Conflict |
| `ERR_MACHINE_REFERENCED_BY_PLAN` | 409 Conflict |
| `ERR_SERIAL_NUMBER_EXISTS` | 409 Conflict |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_INVALID_STATE` | 409 Conflict |
| `ERR_MACHINE_BUSY_MAINTENANCE` | 409 Conflict |
| `ERR_EVENT_WINDOW_PASSED` | 422 Unprocessable Entity |
| `ERR_BACKUP_MACHINE_REQUIRED` | 400 Bad Request |
| `ERR_BACKUP_MACHINE_NOT_IN_STOCK` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_MONTH_IN_PAST` | 422 Unprocessable Entity |
| `ERR_MONTH_ORDER_EXISTS` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_POSTURE_NOT_ORDERABLE` | 403 Forbidden |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MONTH_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_OPEN_APPOINTMENTS_EXIST` | 409 Conflict |
| `ERR_ACTIVE_APPOINTMENT_EXISTS` | 409 Conflict |
| `ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_DELIVERED_UNITS_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TREATMENT_DATE` | 409 Conflict |
| `ERR_LOG_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_MACHINE_NOT_ASSIGNED_TO_PATIENT` | 409 Conflict |
| `ERR_LOG_INVALID_STATE` | 409 Conflict |
| `ERR_UNREVIEWED_LOGS_REMAIN` | 409 Conflict |
| `ERR_REVIEW_NOT_PENDING` | 409 Conflict |
| `ERR_CHAIR_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_SLOT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_SLOT_DURATION_INVALID` | 400 Bad Request |
| `ERR_CHAIR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_SLOT_DAILY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SLOT_INVALID_STATE` | 409 Conflict |
| `ERR_SLOT_TOO_LATE_TO_CANCEL` | 422 Unprocessable Entity |
| `ERR_QUANTITY_EXCEEDS_ON_HAND` | 422 Unprocessable Entity |
| `ERR_WASTE_RECORD_NOT_REPORTED` | 409 Conflict |
| `ERR_REVERSAL_TARGET_REQUIRED` | 400 Bad Request |
| `ERR_REVERSAL_TARGET_INVALID` | 409 Conflict |
| `ERR_REASON_REQUIRES_PHYSICIAN` | 403 Forbidden |
| `ERR_REASON_NOT_SUBSTANTIATED` | 409 Conflict |
| `ERR_OPEN_TRANSITION_EXISTS` | 409 Conflict |
| `ERR_TRANSITION_INVALID_STATE` | 409 Conflict |
| `ERR_PATIENT_STATE_BLOCKS_TRANSITION` | 409 Conflict |
| `ERR_TRANSITION_EFFECTIVE_IN_FUTURE` | 409 Conflict |
