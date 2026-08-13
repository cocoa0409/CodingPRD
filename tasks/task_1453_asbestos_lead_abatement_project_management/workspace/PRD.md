# Asbestos & Lead Abatement Project Management API — Product Requirements Document

## 1. Introduction

Renovation and demolition work on older buildings collides with two of the most heavily regulated hazards in construction: asbestos-containing materials and lead-based paint. For an abatement contractor, the project file is not paperwork produced after the fact — it is the legal record that the structure was surveyed before disturbance, that the regulator was notified and the mandatory waiting period observed, that containment held negative pressure while certified workers removed the material, that independent air sampling proved the space safe to re-occupy, and that every bag of hazardous waste traveled under a traceable manifest to a facility approved to receive it. Gaps in that chain create liability measured in decades, and a single untracked bag or lapsed respirator fit-test can void an otherwise clean closeout.

This document specifies the Asbestos & Lead Abatement Project Management API, the system of record for that lifecycle. The API governs twelve resource families — projects, surveys, bulk samples, workers, crew assignments, regulatory notifications, containments, air tests, waste manifests, disposal facilities, relocation units, and relocation records — from project intake through final closeout. All business resources are served under the `/abatement` prefix, and a small administrative capability drives the server's logical clock for time-dependent rules. The design favors immediate consistency: every derived quantity (square footage, fees, tonnage, scheduled hours) is recomputed at the moment the underlying fact changes, and state transitions cascade across related resources so the record can never show, for example, an open re-occupancy gate while a failed clearance test stands unremediated.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API: authentication, response shape, pagination, time, precision, concurrency, and the validation pipeline.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles:

- `ContractorAdmin` — the abatement contractor's office administrator. Owns projects, worker registration and recertification, regulatory filings, facility registration and suspension, relocation units and records, project start and closeout, and the logical clock.
- `Supervisor` — a certified on-site supervisor, who is also a registered Worker in the system. Owns containment design, installation, verification, and revision; crew assignment scheduling; manifest creation, sealing, and shipping; and daily air monitoring.
- `IndustrialHygienist` — the independent third-party hygienist/laboratory. Records sample results and air-test results, and is the only role that may create or report `CLEARANCE`-phase air tests.
- `RegulatorClerk` — regulator staff. Acknowledges filed notifications.
- `FacilityOperator` — a disposal facility operator. Records delivery and confirms or rejects manifests addressed to their own facility.

Beyond authentication, each endpoint restricts which roles may call it; a call from a role outside the permitted set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Read endpoints (all GET operations) are available to all five roles.

Role identity is bound to `X-User-ID` as follows. When `X-User-Role` is `Supervisor`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks on any resource that references a `Worker` compare the resource's foreign-key field to `X-User-ID`. The server also records this identifier when the supervisor verifies a containment (`verified_by_user_id`) or seals a manifest (`sealed_by_user_id`). When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the `id` of the acting `DisposalFacility`; delivery, confirmation, and rejection of a manifest require `X-User-ID` to equal the manifest's `facility_id`, failing with `ERR_FACILITY_MISMATCH` (HTTP 403) otherwise. When `X-User-Role` is `ContractorAdmin`, `IndustrialHygienist`, or `RegulatorClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `result_recorded_by_user_id` on an air test, which the result-recording transition writes — but does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Both are optional on every list endpoint.

Unless otherwise specified for a particular endpoint, list endpoints return resources sorted by `created_at` in ascending order. One deliberate exception exists: the notification listing of a project is ordered by `filed_at` descending, breaking ties by `created_at` descending (see §3.3).

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled Sweeps

All time-dependent behavior in the system — waiting periods, certification lapse, assignment completion, unit cleaning release, and every recorded timestamp — reads from a single server-managed **logical clock**, never from wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ContractorAdmin`-only test-driving capability advances the clock by supplying a `to_iso8601` timestamp; the response echoes the new time as `current_utc`. Timestamps the server writes itself — `filed_at`, `acknowledged_at`, `last_verified_at`, `delivered_at`, `returned_at` — are all drawn from this clock at the instant the operation executes.

Advancing the clock fires three sweeps, in every case comparing against the new current time:

1. **Worker lapse evaluation.** Any `ACTIVE` worker whose earliest of `cert_expires_at`, `medical_clearance_expires_at`, and `respirator_fit_expires_at` has been reached — that is, the current time is at or after the earliest of the three — transitions to `LAPSED`, firing the assignment and project cascades described in §3.5.
2. **Assignment completion.** Every crew assignment in `SCHEDULED` or `SUSPENDED` status whose `end_at` is at or before the current time transitions to `COMPLETED`.
3. **Unit cleaning release.** Every relocation unit in `CLEANING` status whose `cleaning_until` has been reached or passed transitions back to `AVAILABLE`.

### 2.5. Common Resource Properties and Derived Fields

Every resource in this API carries a uniform set of system-managed properties; no resource family is exempt:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every mutation of the resource, and which anchors optimistic concurrency control where that mechanism applies (§2.8).

Many resources additionally expose **derived fields** computed by the server rather than supplied by clients — for example a sample-derived survey aggregate such as `acm_sq_ft_final`, an assignment's `scheduled_hours`, a manifest's `net_weight_lbs`, `net_tons`, and frozen `fee_cents`, a containment's `air_changes_per_hour` and `machines_required`, a worker's `assigned_scheduled_hours`, or a facility's `delivered_tons_current_month`. Derived fields are read-only to clients and are recomputed immediately, within the same request, whenever an input they depend on changes. A recomputation that changes a derived field on a resource is itself a mutation of that resource: its `updated_at` refreshes and its `version` increments.

### 2.6. Units, Precision, and Rounding Discipline

Numeric discipline is fixed per quantity kind, and all rounding uses the round-half-up method:

- **Areas** (`quantity_sq_ft`, `declared_acm_sq_ft`, the survey aggregates, `total_acm_sq_ft`) are carried at 2 decimal places, rounded half up.
- **Weights** are carried in pounds at 2 decimal places (`net_weight_lbs`) and in tons at 4 decimal places (`net_tons`, `delivered_tons_current_month`), rounded half up. One ton is exactly 2,000 pounds.
- **Money** is carried as integer cents — `base_abatement_cost_cents`, `estimated_disposal_cost_cents`, `fee_cents`, `final_disposal_cost_cents`, `insurance_surcharge_cents`, `total_project_cost_cents`. Any multiplication that produces fractional cents is rounded half up to whole cents.
- **Durations** (`scheduled_hours`, `assigned_scheduled_hours`) are expressed in hours at 2 decimal places, rounded half up.
- **Threshold comparisons** for air clearance are made at 3 decimal places against 0.010 fibers per cubic centimeter; containment pressure readings are evaluated against -0.020 inches of water gauge.
- **Waiting-period arithmetic** is exact to the second, with each waiting day defined as exactly 86,400 seconds.

Enum fields accept only the exact uppercase strings documented for them in §3; any other value is a field-validation failure.

### 2.7. Provisional and Final Figures: The Dual-Variant Principle

The system deliberately carries paired estimates rather than overwriting one figure with another. A survey tracks both `acm_sq_ft_provisional` — the planning quantity that treats still-unresolved samples as assumed-positive, used in notification and planning contexts — and `acm_sq_ft_final`, the regulatory quantity that counts only confirmed-positive samples, used for closeout. A project similarly carries `estimated_disposal_cost_cents`, a survey-derived figure computed under a standard density assumption before any waste exists, alongside `final_disposal_cost_cents`, the sum of actual frozen manifest fees as disposal is confirmed. The two variants of each pair diverge whenever reality departs from assumption — whenever a sample is still pending, or whenever manifested weight differs from the density assumption — and both remain visible on the resource so that planners and auditors can see exactly where the divergence arose. The precise formulas live with their workflows in §3.2 and §3.7.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and both reject stale writes with `ERR_STALE_VERSION` (HTTP 412):

- A `POST /abatement/notifications` request must carry `expected_project_version` holding the `version` of the parent project as the client last observed it. If the project's current `version` has advanced beyond that value, the filing is rejected. This guard exists because filing a new notification legitimately supersedes the previously filed one: a client acting on a stale project view would otherwise silently supersede a notification it never saw.
- A `POST /abatement/containments/{id}/revise` request must carry `expected_containment_version` holding the containment's `version` as the client last observed it; a mismatch with the containment's current `version` rejects the revision. This guard exists because a revision recomputes `machines_required` from design inputs, so a stale client would otherwise silently overwrite another revision's design.

No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.9. Validation Pipeline and Error Precedence

Every request is evaluated against an ordered pipeline of checks. A request that would fail several checks is rejected with the error belonging to the **earliest** rung of the pipeline — earlier failures mask later ones. The rungs, in order, are:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the five declared roles (`ERR_UNAUTHENTICATED`, 401).
2. **Authorization** — the role is permitted for this endpoint, including entity-backed ownership: a `FacilityOperator` whose `X-User-ID` does not equal the target manifest's `facility_id` fails with `ERR_FACILITY_MISMATCH` (403); any other role violation fails with `ERR_UNAUTHORIZED_ROLE` (403).
3. **Field validation** — required fields are present, JSON types are correct, enum members are valid, numeric ranges are sane (`ERR_VALIDATION`, 400).
4. **Existence** — every referenced resource exists (`ERR_*_NOT_FOUND`, 404; see §2.11).
5. **Stale version** — optimistic concurrency where §2.8 applies (`ERR_STALE_VERSION`, 412).
6. **State gates** — the target's state machine permits the transition, terminal states are locked, and cross-entity status gates hold: the survey is `IN_LAB` before sample results, project status windows guard assignment, manifest, and air-test creation, and the containment is `VERIFIED` before abatement starts (`ERR_INVALID_STATE`, 409).
7. **Safety rules** — worker fitness (`ERR_WORKER_NOT_FIT`), certification-level match (`ERR_CERTIFICATION_MISMATCH`), negative-pressure sufficiency (`ERR_PRESSURE_INSUFFICIENT`), segregation of duties on clearance results (`ERR_SEGREGATION_OF_DUTIES`), and the re-occupancy gate (`ERR_REOCCUPANCY_BLOCKED`).
8. **Temporal rules** — notification acknowledgement (`ERR_NOTIFICATION_NOT_ACKNOWLEDGED`), waiting period (`ERR_WAITING_PERIOD_NOT_ELAPSED`), assignment window validity (`ERR_INVALID_WINDOW`), and supervisor coverage (`ERR_SUPERVISOR_COVERAGE_REQUIRED`).
9. **Facility referential rules** — the facility is `APPROVED` (`ERR_FACILITY_NOT_APPROVED`) and accepts the project's hazard class (`ERR_FACILITY_HAZARD_MISMATCH`).
10. **Business constraints** — one survey per project (`ERR_SURVEY_ALREADY_EXISTS`), one containment per project (`ERR_CONTAINMENT_ALREADY_EXISTS`), all samples reported before finalization (`ERR_SAMPLES_STILL_PENDING`), no overlapping assignments (`ERR_ASSIGNMENT_OVERLAP`), relocation unit availability (`ERR_UNIT_NOT_AVAILABLE`) and capacity (`ERR_UNIT_CAPACITY_EXCEEDED`), and no outstanding manifests at the gates that require them (`ERR_MANIFESTS_OUTSTANDING`).
11. **Fiscal checks** — manifest net weight must be positive (`ERR_MANIFEST_WEIGHT_INVALID`) and facility monthly capacity must not be exceeded (`ERR_FACILITY_CAPACITY_EXCEEDED`).

Where several same-rung rules guard one endpoint, §3 states them in the order they are evaluated.

### 2.10. Cascading State Propagation and Terminal Lockdown

Resources in this domain do not change state in isolation. When a fact changes on one resource, the server itself transitions every related resource whose state depends on that fact, inside the same request — a failed clearance test pushes the containment into recleaning, the project follows it, and housed relocation records extend, without any client issuing separate calls. Each resource mutated by such a cascade is independently mutated: its `updated_at` refreshes and, where the transition is documented to do so, its `version` increments.

Terminal states are locked. A `CLOSED` project, a `FINALIZED` survey, a `REPORTED` sample or air test, a `COMPLETED` or `CANCELLED` assignment, a `SUPERSEDED` notification, a `CONFIRMED` or `VOIDED` manifest, a `SUSPENDED` facility, and a `RETURNED` relocation record admit no further transitions; any attempt to act on a resource from a state that does not permit the transition — terminal or otherwise — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.11. Nested Resource Retrieval

Requests that address nested resources validate every referenced identifier in strict left-to-right order — path identifiers first, then body references — and reject with the 404 error of the **first** reference that does not resolve. Each resource family has its own error identifier: `ERR_PROJECT_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_CONTAINMENT_NOT_FOUND`, `ERR_AIR_TEST_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, and `ERR_RELOCATION_NOT_FOUND` (all HTTP 404). A request that names a missing project and a missing sample therefore reports the project error, and body references are validated in the order `project_id`, `survey_id`, `worker_id`, `unit_id`, `facility_id`.

## 3. Business Logic & Workflows

### 3.1. Project Intake and Registry Setup

A `ContractorAdmin` opens an abatement engagement by creating a **project** with a `name`, the `site_address` of the structure, a `work_type` of either `RENOVATION` or `DEMOLITION`, a `hazard_class` of `ASBESTOS`, `LEAD`, or `MIXED`, an informational `planned_start`, and the contracted `base_abatement_cost_cents` (an integer number of cents, zero or greater). A new project begins in `DRAFT` status with its `reoccupancy_status` `BLOCKED` and every computed figure at zero: `total_acm_sq_ft`, `estimated_disposal_cost_cents`, `manifested_weight_lbs`, `final_disposal_cost_cents`, `insurance_surcharge_cents`, and `total_project_cost_cents`.

The project's `status` walks a cyclic lifecycle: `DRAFT` → `ASSESSED` → `IN_PROGRESS` ⇄ `SUSPENDED` → `AWAITING_CLEARANCE` ⇄ `RECLEANING` → `CLOSED`. The forward legs are earned — assessment comes only from a finalized survey, the start of abatement only after the regulator's waiting period — while the `RECLEANING` leg loops the project back whenever clearance testing fails.

Before fieldwork begins, the office also populates two registries. A **disposal facility** is registered with its `name`, EPA identification number `epa_id`, the non-empty `accepted_hazards` subset drawn from `ASBESTOS` and `LEAD`, and a `monthly_capacity_tons` ceiling greater than zero; a new facility is `APPROVED` with `delivered_tons_current_month` at zero. A **relocation unit** is registered with a `unit_label` and a `capacity_persons` of at least one; a new unit is `AVAILABLE` with `cleaning_until` unset.

### 3.2. Survey, Sampling, and Laboratory Results

Regulation requires the survey to precede everything else. A `ContractorAdmin` creates the project's **survey** with a payload carrying the `project_id`, the certified inspector's `surveyor_name`, and the `survey_date`. The project must still be in `DRAFT` (otherwise `ERR_INVALID_STATE`), and a project may have at most one survey — a second attempt is rejected with `ERR_SURVEY_ALREADY_EXISTS`. The survey starts in `DRAFT` with its three aggregates — `acm_sq_ft_provisional`, `acm_sq_ft_final`, and `friable_acm_sq_ft_final` — at zero.

While the survey remains in `DRAFT`, the administrator adds **bulk samples** to it (adding to a survey that has left `DRAFT` fails with `ERR_INVALID_STATE`). Each sample names its `survey_id`, the `material` sampled (for example, pipe insulation), a `location_desc` saying where in the building it was taken, the represented `quantity_sq_ft` (strictly greater than zero), whether the material is `friable`, and optionally the lead content `lead_ppm`, which defaults to null. A sample's `lab_result` is drawn from `PENDING`, `POSITIVE`, and `NEGATIVE`; a newly added sample starts at `PENDING` with its sample status also `PENDING`, and every added sample immediately recomputes the survey's aggregates.

Submitting the survey moves it from `DRAFT` to `IN_LAB` and requires at least one sample; submitting a sample-less survey fails with `ERR_VALIDATION` (400). Once the survey is `IN_LAB`, an `IndustrialHygienist` records each sample's result, moving the sample from `PENDING` to `REPORTED`. Recording against a survey that is not `IN_LAB` fails with `ERR_INVALID_STATE`. The result payload carries the `lab_result`; when that result is `POSITIVE`, the `asbestos_pct` must be present and lie between 1 and 100 inclusive, or the recording is rejected with `ERR_VALIDATION`. A `lead_ppm` may also be supplied or corrected at result time. Each recorded result recomputes the survey's quantity aggregates at 2 decimal places, rounded half up:

- `acm_sq_ft_provisional` — the planning variant — sums `quantity_sq_ft` over all samples of the survey whose `lab_result` is `PENDING` or `POSITIVE`. Pending samples are treated as assumed-positive, so this variant diverges from the final figure whenever any sample remains unresolved.
- `acm_sq_ft_final` — the regulatory variant — sums `quantity_sq_ft` over samples whose `lab_result` is `POSITIVE` only.
- `friable_acm_sq_ft_final` sums `quantity_sq_ft` over samples whose `lab_result` is `POSITIVE` and whose `friable` flag is true.

Finalizing the survey moves it from `IN_LAB` to `FINALIZED` and is permitted only when every sample of the survey has been reported; if even one sample is still `PENDING`, finalization fails with `ERR_SAMPLES_STILL_PENDING`. Finalization is the hinge of the whole project: the parent project automatically transitions from `DRAFT` to `ASSESSED`, the project's `total_acm_sq_ft` is set to the survey's `acm_sq_ft_final`, the project's `estimated_disposal_cost_cents` is computed under the density assumption described in §3.7, and the project's `version` increments by 1.

### 3.3. Regulatory Notification and the Waiting Period

With the project `ASSESSED`, a `ContractorAdmin` files a **regulatory notification** naming the `project_id` (the project must be `ASSESSED`, otherwise `ERR_INVALID_STATE`), a `notification_type` of `INITIAL`, `REVISION`, or `EMERGENCY`, and the `declared_acm_sq_ft` being disturbed (strictly greater than zero). Because filing supersedes whatever was filed before, the request must also carry `expected_project_version` equal to the project's current `version`; if another write has advanced the project since the client last read it, the filing is rejected with `ERR_STALE_VERSION` (412) rather than silently superseding a notification the client never saw.

At filing, the server stamps `filed_at` from the logical clock and computes the waiting window: `waiting_days` is 3 for an `EMERGENCY` notification and 10 for `INITIAL` or `REVISION`, and `earliest_start_at` is `filed_at` plus that many calendar days of exactly 86,400 seconds each, computed to the second. The notification begins in `FILED` status with `acknowledged_at` unset. Filing a new notification for a project that already has one in `FILED` or `ACKNOWLEDGED` status automatically transitions the earlier one to `SUPERSEDED`, and the filing itself increments the project's `version` by 1. Whenever the system speaks of a project's "latest" notification — including the notification listing of a project — it means the ordering by `filed_at` descending with ties broken by `created_at` descending.

A `RegulatorClerk` then acknowledges the filing, moving it from `FILED` to `ACKNOWLEDGED` and stamping `acknowledged_at` with the current logical time.

Starting abatement is the most heavily gated action in the system. A `ContractorAdmin` triggers the transition from `ASSESSED` to `IN_PROGRESS`, and the gate evaluates four conditions in order: the project's latest notification must be `ACKNOWLEDGED` (a missing or unacknowledged filing fails with `ERR_NOTIFICATION_NOT_ACKNOWLEDGED`); the current logical time must be at or after that notification's `earliest_start_at` — equality is allowed — otherwise `ERR_WAITING_PERIOD_NOT_ELAPSED`; the project's containment must exist and be `VERIFIED`, otherwise `ERR_INVALID_STATE`; and supervisor coverage must exist — at least one crew assignment of the project with `role_on_site` `SUPERVISOR` in `SCHEDULED` status whose window covers the current instant, meaning its `start_at` is at or before now and its `end_at` is strictly after now — otherwise `ERR_SUPERVISOR_COVERAGE_REQUIRED`. A successful start increments the project's `version` by 1.

### 3.4. Containment Engineering and Negative-Air Verification

A `Supervisor` designs the project's single **containment** by supplying the `project_id` (the project must be `ASSESSED`, otherwise `ERR_INVALID_STATE`; a second containment for the same project is rejected with `ERR_CONTAINMENT_ALREADY_EXISTS`), the enclosed `work_area_volume_cuft` (strictly greater than zero), and a `containment_class` of `FULL`, `MINI_ENCLOSURE`, or `GLOVE_BAG`. The design begins in `DESIGNED` status.

Negative-air sizing follows immediately from the design inputs. The required `air_changes_per_hour` is 4 for a `FULL` containment, 6 for a `MINI_ENCLOSURE`, and 0 for a `GLOVE_BAG`. A glove-bag operation needs no negative-air machines at all, so `machines_required` is 0. Otherwise the machine count is the work-area volume multiplied by the air-changes-per-hour figure, divided by the hourly throughput of one machine — each machine moves 2,000 cubic feet per minute, hence 120,000 cubic feet per hour — with the quotient rounded up to a whole number, and the result then raised to at least 1 machine: the ceiling is applied first, then the floor of one machine.

While the containment remains `DESIGNED`, the supervisor may revise it, supplying a new `work_area_volume_cuft`, a new `containment_class`, or both. Because a revision recomputes the machine count from design inputs, the request must carry `expected_containment_version` matching the containment's current `version`; a stale revision is rejected with `ERR_STALE_VERSION` (412) instead of silently overwriting another designer's work. A successful revision stays in `DESIGNED`, recomputes `air_changes_per_hour` and `machines_required`, and increments the containment's `version` by 1.

Installation moves the containment from `DESIGNED` to `INSTALLED` and requires the project to be `ASSESSED` (otherwise `ERR_INVALID_STATE`). Verification — whether from `INSTALLED` or, after a clearance failure, from `RECLEAN_REQUIRED` — moves it to `VERIFIED`. The verifying `Supervisor` supplies a `pressure_reading_inwg`, which must be at or below -0.020 inches of water gauge; equality passes, and anything higher (insufficient negative pressure) fails with `ERR_PRESSURE_INSUFFICIENT` (422). A successful verification records the reading in `last_pressure_reading_inwg`, stamps `verified_by_user_id` with the verifier's `X-User-ID`, and sets `last_verified_at` to the current logical time. That `verified_by_user_id` is the segregation-of-duties anchor for clearance testing (§3.6), and `last_verified_at` becomes the window boundary for counting clearance passes. When the verification comes from `RECLEAN_REQUIRED`, it additionally returns the project from `RECLEANING` to `AWAITING_CLEARANCE`.

### 3.5. Workforce Certification and Crew Scheduling

Nobody works an abatement site on goodwill alone. A `ContractorAdmin` registers each **worker** with a `full_name`, a `certification_level` of `SUPERVISOR` or `HANDLER`, and three expiry timestamps: `cert_expires_at` for the certification itself, `medical_clearance_expires_at` for the medical surveillance clearance, and `respirator_fit_expires_at` for the respirator fit-test. A registered worker starts `ACTIVE` with `assigned_scheduled_hours` at zero.

Crew assignments are created by a `ContractorAdmin` or a `Supervisor` with a payload naming the `project_id`, the `worker_id`, the `role_on_site` (`SUPERVISOR` or `HANDLER`), and a half-open window from `start_at` (inclusive) to `end_at` (exclusive). Creation evaluates its checks in order: field validation first, then existence of the referenced project and worker, then the cross-entity project-state gate (`ERR_INVALID_STATE`), then two worker safety checks — the worker must be `ACTIVE` with all three expiry timestamps falling strictly after `start_at` (an expiry exactly equal to `start_at` renders the worker unfit, `ERR_WORKER_NOT_FIT`, 422), and a `role_on_site` of `SUPERVISOR` requires the worker's `certification_level` to be `SUPERVISOR` (`ERR_CERTIFICATION_MISMATCH`, 422) — then the window itself, where an `end_at` that is not strictly after `start_at` fails with `ERR_INVALID_WINDOW` (422), and finally overlap: the worker must have no existing `SCHEDULED` assignment whose `start_at` falls before the new `end_at` while the new `start_at` falls before that assignment's `end_at`. Because windows are half-open, back-to-back assignments that merely touch are allowed; a true overlap is rejected with `ERR_ASSIGNMENT_OVERLAP` (409).

A created assignment is `SCHEDULED`, and its `scheduled_hours` — the window length in hours at 2 decimal places, rounded half up — feeds the worker's `assigned_scheduled_hours`, which is the sum of `scheduled_hours` over that worker's `SCHEDULED` assignments only, recomputed at 2 decimal places whenever an assignment is created, cancelled, suspended, restored, or completed. Cancelling an assignment (a `ContractorAdmin` or `Supervisor` action) moves it from `SCHEDULED` to `CANCELLED` and recomputes the worker's hours. The clock sweep moves a `SCHEDULED` or `SUSPENDED` assignment whose `end_at` has been reached to `COMPLETED`; completing a `SUSPENDED` assignment needs no hours recomputation, since suspended time was already excluded from the worker's total.

Lapse is automatic. When the logical clock reaches the earliest of a worker's three expiry fields, the worker transitions from `ACTIVE` to `LAPSED`, and the lapse cascades in two links. Link 1: every `SCHEDULED` assignment of that worker transitions to `SUSPENDED`, and the worker's hours are recomputed with the suspended assignments excluded. Link 2: for each project that had at least one assignment suspended by link 1, if the project is `IN_PROGRESS` and no remaining `SCHEDULED` `SUPERVISOR` assignment covers the current instant, the project itself transitions from `IN_PROGRESS` to `SUSPENDED`, incrementing its `version` by 1 — the site cannot lawfully run without supervisor coverage.

Recertification reverses the lapse. A `ContractorAdmin` supplies new values for any of `cert_expires_at`, `medical_clearance_expires_at`, and `respirator_fit_expires_at`; only if, after applying the provided fields, all three expiries fall strictly after the current time does the worker return from `LAPSED` to `ACTIVE` — otherwise the request fails with `ERR_WORKER_NOT_FIT` (422). On a successful recertification, every `SUSPENDED` assignment of the worker whose `end_at` is still in the future transitions back to `SCHEDULED`, and the worker's assigned hours are recomputed.

Manual stop-work follows the same coverage logic. A `ContractorAdmin` or `Supervisor` may suspend an `IN_PROGRESS` project, moving it to `SUSPENDED` and incrementing its `version` by 1. Resumption moves the project from `SUSPENDED` back to `IN_PROGRESS` and again requires supervisor coverage — at least one `SCHEDULED` `SUPERVISOR` assignment whose window covers now — failing with `ERR_SUPERVISOR_COVERAGE_REQUIRED` when none exists; a successful resume also increments the project's `version` by 1.

### 3.6. Air Monitoring, Clearance Testing, and the Re-occupancy Gate

Air monitoring brackets the physical work. An **air test** is collected by naming the `project_id`, a `phase` of `BASELINE`, `DAILY`, or `CLEARANCE`, and the `collected_at` instant; a new test is `COLLECTED` with `result_f_cc` unset, `outcome` `NA`, and `result_recorded_by_user_id` unset. Each phase is gated on the project's status: a `BASELINE` test requires the project to be `ASSESSED`; a `DAILY` test requires `IN_PROGRESS`, `SUSPENDED`, or `RECLEANING`; a `CLEARANCE` test requires `AWAITING_CLEARANCE`. A collection attempted outside the phase's window fails with `ERR_INVALID_STATE`. Roles are phase-bound as well: `Supervisor` and `IndustrialHygienist` may collect `BASELINE` and `DAILY` tests, but only an `IndustrialHygienist` may collect a `CLEARANCE` test — a `Supervisor` attempting one is rejected with `ERR_UNAUTHORIZED_ROLE` (403). The project's air-test listing supports an optional `phase` filter alongside pagination.

Only an `IndustrialHygienist` records results, moving a test from `COLLECTED` to `REPORTED` by supplying the `result_f_cc` fiber count. The recording stamps `result_recorded_by_user_id` with the hygienist's `X-User-ID` and computes the `outcome`. For `BASELINE` and `DAILY` tests the `outcome` remains `NA`. For a `CLEARANCE` test, the `outcome` is `PASS` when `result_f_cc` is strictly below 0.010 fibers per cubic centimeter and `FAIL` otherwise — a result of exactly 0.010 is a `FAIL` — with the comparison made at three decimal places. Segregation of duties guards the clearance verdict: the hygienist recording a `CLEARANCE` result must not be the same `X-User-ID` recorded as the containment's `verified_by_user_id`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (409).

A failed clearance cascades through three links. Link 1 moves the project's containment from `VERIFIED` to `RECLEAN_REQUIRED`. Link 2 moves the project from `AWAITING_CLEARANCE` to `RECLEANING`, recomputes its `reoccupancy_status` to `BLOCKED`, and increments the project's `version` by 1. Link 3 transitions every relocation record of the project still in `HOUSED` status to `EXTENDED`, incrementing each record's `extension_count` by 1 — the occupants cannot come home yet. When re-cleaning is complete, a fresh containment verification (§3.4) returns the project from `RECLEANING` to `AWAITING_CLEARANCE`, incrementing its `version` again, and the cycle of clearance testing resumes.

A passing clearance recomputes the project's `reoccupancy_status`, which is the system's re-occupancy gate and is computed as follows. Let the verification instant be the containment's `last_verified_at`, treating it as unset if the containment was never verified. Count the project's `CLEARANCE`-phase tests in `REPORTED` status whose `collected_at` is strictly after that verification instant — a test collected at the exact same instant as the verification does not count, and if the containment was never verified every reported clearance test counts — splitting them into passes (`outcome` `PASS`) and fails (`outcome` `FAIL`). The `reoccupancy_status` is `OPEN` exactly when there are zero fails and at least 2 passes in that window; otherwise it is `BLOCKED`. The gate recomputes on every clearance result, every containment verification, and every reclean cascade.

Entry into the clearance phase itself is earned: a `Supervisor` completes the work phase, moving the project from `IN_PROGRESS` to `AWAITING_CLEARANCE`, only when no manifest of the project remains in `DRAFT` — unsealed manifests mean unaccounted waste and the transition fails with `ERR_MANIFESTS_OUTSTANDING`. Completion increments the project's `version` by 1.

### 3.7. Waste Manifesting and Disposal Settlement

Every bag of waste leaving the site travels under a **waste manifest**. A `Supervisor` creates one while the project is `IN_PROGRESS` or `RECLEANING` (any other project state fails with `ERR_INVALID_STATE`), supplying the `project_id`, the destination `facility_id`, the `bags_count` (at least 1), and the `gross_weight_lbs` including packaging (strictly greater than zero). At creation the server computes the net weight: `net_weight_lbs` is the gross weight minus a tare of 2 pounds per bag, at 2 decimal places, and if that net weight is not strictly positive the manifest is rejected with `ERR_MANIFEST_WEIGHT_INVALID` (422). The `net_tons` is the net pounds divided by 2,000, carried at 4 decimal places, rounded half up. A new manifest is in `DRAFT` with `fee_cents`, `sealed_by_user_id`, `delivered_at`, and `reject_reason` unset. The project's manifest listings — and the facility's — support an optional `status` filter.

Sealing a manifest, again a `Supervisor` action, moves it from `DRAFT` to `SEALED` and freezes its disposal fee. Sealing requires the project to be `IN_PROGRESS` or `RECLEANING` and the project's containment to be `VERIFIED` or `RECLEAN_REQUIRED`; either failure is an `ERR_INVALID_STATE`. The frozen `fee_cents` uses two-tier pricing: when the manifest's own `net_tons` is at most 10 tons the rate is 15,000 cents per ton, and above 10 tons the rate is 12,500 cents per ton; the fee is the manifest's `net_tons` multiplied by its tier rate, rounded half up to whole cents. The rounding order is pinned: each manifest's fee is rounded individually at seal time, and the project's `final_disposal_cost_cents` is the sum of those already-rounded `fee_cents` over manifests in `CONFIRMED` status only — summing unrounded fees and rounding once at the project level is forbidden because it produces different cents. Sealing also stamps `sealed_by_user_id` with the supervisor's `X-User-ID` and recomputes the project's `manifested_weight_lbs`, which is always the sum of `net_weight_lbs` over the project's manifests in `SEALED`, `IN_TRANSIT`, `DELIVERED`, or `CONFIRMED` status.

Shipping moves a manifest from `SEALED` to `IN_TRANSIT` under a `Supervisor`'s hand. Delivery is the facility's affair: a `FacilityOperator` records delivery, moving the manifest from `IN_TRANSIT` to `DELIVERED`, and the gate evaluates four conditions in order — the operator's `X-User-ID` must equal the manifest's `facility_id` (`ERR_FACILITY_MISMATCH`, 403); the facility must be `APPROVED` (`ERR_FACILITY_NOT_APPROVED`, 409); the facility's `accepted_hazards` must cover the project's `hazard_class`, where a `MIXED` project requires both `ASBESTOS` and `LEAD` to be present and any other class requires that class itself (`ERR_FACILITY_HAZARD_MISMATCH`, 422); and the facility's `delivered_tons_current_month` plus the manifest's `net_tons` must not exceed `monthly_capacity_tons`, with equality allowed (`ERR_FACILITY_CAPACITY_EXCEEDED`, 422). A recorded delivery stamps `delivered_at` from the logical clock and recomputes the facility's `delivered_tons_current_month`.

That monthly figure is the sum of `net_tons` over the facility's manifests in `DELIVERED` or `CONFIRMED` status whose `delivered_at` falls within the current UTC calendar month — from the first instant of the month, inclusive, to the first instant of the next month, exclusive — carried at 4 decimal places, rounded half up. Manifests in `REJECTED`, `IN_TRANSIT`, `SEALED`, `DRAFT`, or `VOIDED` status never count toward it.

From `DELIVERED`, the facility either confirms or rejects, and both actions require the same facility identity — `X-User-ID` equal to the manifest's `facility_id`, else `ERR_FACILITY_MISMATCH`. **Confirmation** moves the manifest to `CONFIRMED` and recomputes the project's `manifested_weight_lbs`, its `final_disposal_cost_cents`, and the project cost rollup described below. **Rejection** moves it to `REJECTED`, stores the supplied `reason` in `reject_reason`, and recomputes the facility's `delivered_tons_current_month` with the rejected manifest now excluded. A manifest in `DRAFT` or `REJECTED` may also be **voided** by a `Supervisor` or `ContractorAdmin`, moving it to `VOIDED` and recomputing the project's `manifested_weight_lbs` with voided manifests excluded from the aggregation.

Suspending a facility is the office's enforcement lever. A `ContractorAdmin` moves a facility from `APPROVED` to `SUSPENDED`, and the suspension cascades: every manifest addressed to that facility still `IN_TRANSIT` transitions to `REJECTED` with its `reject_reason` set to the literal `FACILITY_SUSPENDED`, and for each affected manifest the owning project's `manifested_weight_lbs` and the facility's `delivered_tons_current_month` are recomputed.

The project's money story closes with two formulas. The **estimated** disposal cost, computed at survey finalization (§3.2), assumes a debris density of one and a half pounds per square foot: the estimated tonnage is `total_acm_sq_ft` multiplied by 1.5 and divided by 2,000, the same two-tier rate applies — 15,000 cents per ton at or below 10 tons, 12,500 cents per ton above — and the product is rounded half up to whole cents to become `estimated_disposal_cost_cents`. The estimate diverges from the final figure whenever the actual manifested weight differs from the density assumption. The **project cost rollup** then runs in a pinned evaluation order whenever the base or disposal figures change: first the subtotal is `base_abatement_cost_cents` plus `final_disposal_cost_cents`; then `insurance_surcharge_cents` is 8 percent of that pre-surcharge subtotal, rounded half up to whole cents — the surcharge never compounds on itself and there is no iteration; finally `total_project_cost_cents` is the subtotal plus the surcharge.

### 3.8. Occupant Relocation and Project Closeout

Abatement displaces people, and the system tracks where they go. A `ContractorAdmin` relocates a household by creating a **relocation record** naming the `project_id` — the project must be `ASSESSED` or `IN_PROGRESS`, otherwise `ERR_INVALID_STATE` — along with the `unit_id` of the temporary housing unit, the `household_name`, the number of `persons` (at least 1), and the `move_out_at` instant when the occupants vacate and unit occupation begins. Unit availability is checked two ways, both failing with `ERR_UNIT_NOT_AVAILABLE` (409): the unit must be `AVAILABLE`, or `CLEANING` with the requested `move_out_at` at or after its `cleaning_until`; and no other relocation record for that unit may be in `HOUSED` or `EXTENDED` status. Capacity is a separate check: `persons` may not exceed the unit's `capacity_persons`, failing with `ERR_UNIT_CAPACITY_EXCEEDED` (422). A created record is `HOUSED` with `extension_count` at zero and `returned_at` unset, and the unit automatically transitions from `AVAILABLE` to `OCCUPIED`.

When the clearance gate stands open, a `ContractorAdmin` records the household's return, moving the record from `HOUSED` — or from `EXTENDED`, after one or more clearance-failure extensions (§3.6) — to `RETURNED`. Return requires the project's `reoccupancy_status` to be `OPEN` and otherwise fails with `ERR_REOCCUPANCY_BLOCKED` (409). The return stamps `returned_at` from the logical clock and moves the unit from `OCCUPIED` to `CLEANING` with `cleaning_until` set one day after the return; the clock sweep later releases the unit from `CLEANING` back to `AVAILABLE` once that instant is reached.

Closing the project is the final act and belongs to a `ContractorAdmin`. The transition from `AWAITING_CLEARANCE` to `CLOSED` evaluates its gates in order: first the re-occupancy gate — the project's `reoccupancy_status` must be `OPEN` and every relocation record of the project must be `RETURNED`, with either failure reported as `ERR_REOCCUPANCY_BLOCKED` (409); then the waste ledger — every manifest of the project must be in `CONFIRMED` or `VOIDED` status, with any other status reported as `ERR_MANIFESTS_OUTSTANDING` (409). A successful close increments the project's `version` by 1, and `CLOSED` is terminal: the record now stands as the complete liability file — survey, notification, containment, monitoring, manifests, and occupant return — for the life of the building.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that act on an existing resource — state transitions, result recording, design revision, clock advancement — return `200 OK`, as do all reads. Request and response bodies follow the narratives of §3; the table below is the index of operations and their authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; fires lapse, completion, and cleaning sweeps | ContractorAdmin |
| POST | `/abatement/projects` | Create an abatement project (DRAFT, reoccupancy BLOCKED) | ContractorAdmin |
| GET | `/abatement/projects/{id}` | Fetch a project with computed fields | All roles |
| POST | `/abatement/projects/{id}/start-abatement` | ASSESSED → IN_PROGRESS (notification, waiting period, containment, coverage gates) | ContractorAdmin |
| POST | `/abatement/projects/{id}/suspend` | IN_PROGRESS → SUSPENDED (manual stop-work) | ContractorAdmin, Supervisor |
| POST | `/abatement/projects/{id}/resume` | SUSPENDED → IN_PROGRESS (supervisor coverage required) | ContractorAdmin, Supervisor |
| POST | `/abatement/projects/{id}/complete-work` | IN_PROGRESS → AWAITING_CLEARANCE (no DRAFT manifests) | Supervisor |
| POST | `/abatement/projects/{id}/close` | AWAITING_CLEARANCE → CLOSED (reoccupancy OPEN, manifests settled, relocations returned) | ContractorAdmin |
| POST | `/abatement/surveys` | Create the project's survey (project DRAFT; one per project) | ContractorAdmin |
| GET | `/abatement/surveys/{id}` | Fetch a survey with quantity aggregates | All roles |
| GET | `/abatement/projects/{id}/surveys` | List the project's surveys (0 or 1) | All roles |
| POST | `/abatement/surveys/{id}/submit` | DRAFT → IN_LAB (requires at least one sample) | ContractorAdmin |
| POST | `/abatement/surveys/{id}/finalize` | IN_LAB → FINALIZED (all samples REPORTED); drives project to ASSESSED | ContractorAdmin |
| POST | `/abatement/samples` | Add a bulk sample to a DRAFT survey | ContractorAdmin |
| GET | `/abatement/surveys/{id}/samples` | List samples of a survey | All roles |
| POST | `/abatement/samples/{id}/result` | PENDING → REPORTED (POSITIVE requires `asbestos_pct`) | IndustrialHygienist |
| POST | `/abatement/workers` | Register a worker with certification, medical, and respirator expiries | ContractorAdmin |
| GET | `/abatement/workers/{id}` | Fetch a worker with `assigned_scheduled_hours` | All roles |
| POST | `/abatement/workers/{id}/recertify` | LAPSED → ACTIVE when all three expiries are strictly future; restores assignments | ContractorAdmin |
| POST | `/abatement/assignments` | Create a crew assignment (fitness, certification, window, overlap, state gates) | ContractorAdmin, Supervisor |
| GET | `/abatement/projects/{id}/assignments` | List assignments of a project | All roles |
| GET | `/abatement/workers/{id}/assignments` | List assignments of a worker | All roles |
| POST | `/abatement/assignments/{id}/cancel` | SCHEDULED → CANCELLED | ContractorAdmin, Supervisor |
| POST | `/abatement/notifications` | File a regulatory notification (project ASSESSED; supersedes prior filing; OCC on project) | ContractorAdmin |
| GET | `/abatement/projects/{id}/notifications` | List a project's notifications, latest first | All roles |
| POST | `/abatement/notifications/{id}/acknowledge` | FILED → ACKNOWLEDGED | RegulatorClerk |
| POST | `/abatement/containments` | Create the project's containment design (project ASSESSED; one per project) | Supervisor |
| GET | `/abatement/projects/{id}/containments` | List the project's containments (0 or 1) | All roles |
| POST | `/abatement/containments/{id}/install` | DESIGNED → INSTALLED | Supervisor |
| POST | `/abatement/containments/{id}/verify` | INSTALLED or RECLEAN_REQUIRED → VERIFIED with pressure reading | Supervisor |
| POST | `/abatement/containments/{id}/revise` | DESIGNED → DESIGNED revision (recomputes machine count; OCC on containment) | Supervisor |
| POST | `/abatement/air-tests` | Collect an air test (phase gates; CLEARANCE is hygienist-only) | Supervisor, IndustrialHygienist |
| GET | `/abatement/projects/{id}/air-tests` | List a project's air tests (optional `phase` filter) | All roles |
| POST | `/abatement/air-tests/{id}/result` | COLLECTED → REPORTED; CLEARANCE computes PASS/FAIL and fires the reclean cascade | IndustrialHygienist |
| POST | `/abatement/manifests` | Create a waste manifest (project IN_PROGRESS or RECLEANING; net weight validated) | Supervisor |
| GET | `/abatement/projects/{id}/manifests` | List a project's manifests (optional `status` filter) | All roles |
| GET | `/abatement/facilities/{id}/manifests` | List manifests addressed to a facility (optional `status` filter) | All roles |
| POST | `/abatement/manifests/{id}/seal` | DRAFT → SEALED; fee computed and frozen | Supervisor |
| POST | `/abatement/manifests/{id}/ship` | SEALED → IN_TRANSIT | Supervisor |
| POST | `/abatement/manifests/{id}/deliver` | IN_TRANSIT → DELIVERED (facility identity, approval, hazard, capacity gates) | FacilityOperator |
| POST | `/abatement/manifests/{id}/confirm` | DELIVERED → CONFIRMED | FacilityOperator |
| POST | `/abatement/manifests/{id}/reject` | DELIVERED → REJECTED with reason | FacilityOperator |
| POST | `/abatement/manifests/{id}/void` | DRAFT or REJECTED → VOIDED | Supervisor, ContractorAdmin |
| POST | `/abatement/facilities` | Register an approved disposal facility | ContractorAdmin |
| GET | `/abatement/facilities/{id}` | Fetch a facility with `delivered_tons_current_month` | All roles |
| POST | `/abatement/facilities/{id}/suspend` | APPROVED → SUSPENDED; rejects in-transit manifests | ContractorAdmin |
| POST | `/abatement/relocation-units` | Register a temporary housing unit | ContractorAdmin |
| GET | `/abatement/relocation-units/{id}` | Fetch a relocation unit | All roles |
| POST | `/abatement/relocations` | Relocate a household (unit availability and capacity enforced) | ContractorAdmin |
| GET | `/abatement/projects/{id}/relocations` | List relocation records of a project | All roles |
| GET | `/abatement/relocation-units/{id}/relocations` | List relocation records of a unit | All roles |
| POST | `/abatement/relocations/{id}/return` | HOUSED or EXTENDED → RETURNED (reoccupancy OPEN); unit → CLEANING | ContractorAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are documented in §2 and §3 alongside the workflows that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FACILITY_MISMATCH` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_SURVEY_NOT_FOUND` | 404 |
| `ERR_SAMPLE_NOT_FOUND` | 404 |
| `ERR_WORKER_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_CONTAINMENT_NOT_FOUND` | 404 |
| `ERR_AIR_TEST_NOT_FOUND` | 404 |
| `ERR_MANIFEST_NOT_FOUND` | 404 |
| `ERR_FACILITY_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_RELOCATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SURVEY_ALREADY_EXISTS` | 409 |
| `ERR_CONTAINMENT_ALREADY_EXISTS` | 409 |
| `ERR_SAMPLES_STILL_PENDING` | 409 |
| `ERR_NOTIFICATION_NOT_ACKNOWLEDGED` | 409 |
| `ERR_WAITING_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_SUPERVISOR_COVERAGE_REQUIRED` | 409 |
| `ERR_WORKER_NOT_FIT` | 422 |
| `ERR_CERTIFICATION_MISMATCH` | 422 |
| `ERR_ASSIGNMENT_OVERLAP` | 409 |
| `ERR_PRESSURE_INSUFFICIENT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_REOCCUPANCY_BLOCKED` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_UNIT_CAPACITY_EXCEEDED` | 422 |
| `ERR_FACILITY_NOT_APPROVED` | 409 |
| `ERR_FACILITY_HAZARD_MISMATCH` | 422 |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 |
| `ERR_MANIFEST_WEIGHT_INVALID` | 422 |
| `ERR_MANIFESTS_OUTSTANDING` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
