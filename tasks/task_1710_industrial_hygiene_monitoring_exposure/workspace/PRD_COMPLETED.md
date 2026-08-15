# Industrial Hygiene Monitoring API — Product Requirements Document

## 1. Introduction

A certified industrial hygienist (CIH) firm lives and dies by the defensibility of its exposure records. Regulators, courts, and client safety committees expect a continuous evidentiary chain: similar-exposure groups defined with a written rationale, sampling pumps calibrated before and after every shift, laboratory results tied to detection and quantitation limits, statistical comparisons against OSHA permissible exposure limits and ACGIH threshold limit values, and — when an exceedance is found — control recommendations, respirator fit testing, employee notification, and multi-decade record retention. Today this chain is reconstructed from field notebooks, spreadsheets, and laboratory PDFs, and every hand-off is an opportunity for a broken chain of custody or a missed notification deadline.

This document specifies the Industrial Hygiene Monitoring API, the system of record for that entire pipeline. It governs the full campaign lifecycle — defining similar-exposure groups, sizing and approving sampling plans, calibrating pumps and collecting field samples, entering laboratory results under detection-limit rules, computing exposure statistics and classifications, driving control recommendations through implementation and verification, qualifying workers for respirator use, notifying employees within a fixed working-day deadline, and archiving signed assessments only after their retention period has elapsed. The API enforces segregation of duties at every evidentiary boundary: the hygienist who drafts a plan never approves it, the technician who collects a sample never analyzes it, and the hygienist who prepares an assessment never signs it.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and conventions that apply uniformly across the API; §3 then walks the monitoring campaign as a workflow narrative.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty or all-whitespace value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). If the named role is not authorized for the target operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

The system recognizes seven roles, spelled exactly as follows: `FirmAdmin`, `IndustrialHygienist`, `CIHDirector`, `FieldTechnician`, `LabAnalyst`, `SiteSafetyManager`, and `Employee`. A `FirmAdmin` administers the firm's reference data — sites, employees, exposure limits, and pumps — performs retention archival, and drives the logical clock. An `IndustrialHygienist` defines similar-exposure groups and memberships, drafts and submits sampling plans, prepares exposure assessments, proposes control recommendations, and sends notifications. A `CIHDirector` is the certifying officer: approving or rejecting plans, signing or returning assessments, holding the legal-hold toggle, verifying implemented controls, and deciding medical clearances. A `FieldTechnician` calibrates pumps, collects and seals field samples, and records fit-test results. A `LabAnalyst` opens analysis batches and enters laboratory results. A `SiteSafetyManager` is the client-side counterpart who accepts, rejects, and implements controls, requests medical clearances, schedules fit tests, and sends notifications. An `Employee` is a monitored worker whose exclusive write capability is acknowledging their own exposure notifications.

Role identity is resolved as follows. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee record; ownership checks on any resource that references an Employee compare the resource's employee reference field to `X-User-ID` — concretely, acknowledging a notification requires `X-User-ID` to equal that notification's `employee_id`. When `X-User-Role` is any of `FirmAdmin`, `IndustrialHygienist`, `CIHDirector`, `FieldTechnician`, `LabAnalyst`, or `SiteSafetyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on the resources the operator touches (for example as `created_by_user_id` on a sampling plan or `performed_by_user_id` on a calibration) but never compares it to an entity's `id`. All seven roles may use every read operation; write operations are restricted as enumerated in §4.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; unlike entity timestamps (§2.4), this envelope field is generated from the server's wall clock, and the logical clock of §2.5 governs entity timestamps and date comparisons only, not this field.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400). Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties broken by insertion order — the earliest-created resource first. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource in this API — sites, employees, exposure limits, similar-exposure groups, memberships, sampling plans, pumps, calibrations, field samples, lab batches, lab results, exposure assessments, control recommendations, notifications, medical clearances, and fit tests — carries a uniform set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` records when the resource was created and `updated_at` when it was last modified; both are ISO 8601 UTC timestamps with three fractional digits, and both are driven by the logical clock described in §2.5, never by wall-clock time. The `version` is a system-managed integer that starts at 1 on creation and increments on every mutation of the resource — including cascaded writes that only touch computed fields — so a client reading `version` always observes the resource's latest state. When a single request mutates several entities, all of those changes commit atomically within that request, and each mutated row takes its own `updated_at` refresh and `version` increment.

### 2.5. The Logical Clock and Scheduled State Sweeps

All entity dates and timestamps in the system are logical-clock driven. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time. A `FirmAdmin` may set the logical clock through a dedicated administrative capability that accepts a `to_iso8601` timestamp and responds with the resulting `current_utc` value, echoed back exactly as supplied. Setting the clock triggers three time-based sweeps, each governed by a strictly-greater comparison: every medical clearance in `CLEARED` status whose `expiry_date` is before the new current date transitions to `EXPIRED`, and every respirator fit test in `PASSED` status tied to such a clearance expires along with it; every fit test in `PASSED` status whose own `expiry_date` is before the new current date transitions to `EXPIRED`; and every notification in `PENDING` status whose `due_date` is before the new current date transitions to `OVERDUE`. On an expiry date or due date itself, nothing transitions — the date must be strictly in the past.

### 2.6. Numeric Precision and Chained Rounding

All arithmetic in the system uses decimal arithmetic, and all rounding is round half up. Concentrations, time-weighted averages, and assessment statistics are stored rounded half up to four decimal places; pump drift percentages are stored rounded half up to two decimal places; air volumes are stored rounded half up to one decimal place; and the mean flow used as an intermediate in volume computation is rounded half up to three decimal places. Where a calculation is specified as a chain of steps — most importantly the air-volume-and-concentration chain of §3.5 — rounding is applied at every step and each rounded result feeds the next step; deferring rounding to the end of the chain is non-conformant and produces different stored values. One deliberate exception governs exposure classification: the confidence limits used to decide an assessment's `exposure_class` are the unrounded values, even though the stored `ucl95` and `lcl95` are rounded to four decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a stale client view with the same error. Creating an exposure assessment (POST `/ih/exposure-assessments`) requires the request to carry `expected_seg_version`, holding the `version` of the parent similar-exposure group as the client last observed it. If the group's current `version` no longer matches — because, for example, another writer has since created an assessment against the same group (which legitimately supersedes the previously signed one) or signed one (which rewrites the group's `current_class` and `next_sample_due_date`) — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from assessing a group state it has not observed. Revising a draft sampling plan (PUT `/ih/sampling-plans/{id}`) likewise requires `expected_plan_version` carrying the client's last observed `version` of that plan; a mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so that one hygienist's revision cannot silently overwrite another's. No other endpoint accepts a version field; all other write conflicts are arbitrated by state preconditions rather than version checks.

### 2.8. Validation Pipeline and Evaluation Order

Every request is evaluated against a fixed validation pipeline, and the first failing stage determines the error returned — later stages are never consulted for that request. The stages run in this order. First, header presence: `X-User-ID` and `X-User-Role` must both be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, role authorization: the declared role must be permitted on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`. Third, request-body schema: required fields must be present — including the conditional rules that a `PERSONAL` sample requires `employee_id`, `pump_id`, and `pre_calibration_id` while a `FIELD_BLANK` forbids all three, and that a `PPE_RESPIRATOR` control requires `assigned_protection_factor` while any other control type forbids it — enum values must be drawn from their declared sets, numeric ranges must be respected, and an end date may not precede its start date on either a plan window or a batch window; failures surface as `ERR_INVALID_REQUEST` or `ERR_INVALID_DATE_RANGE`. Request bodies are strict JSON objects: a body that parses to a non-object is rejected with `ERR_INVALID_REQUEST`; a missing or unparseable body is treated as an empty object; an operation that declares body parameters rejects any additional undeclared field with `ERR_INVALID_REQUEST`, while an operation declaring no body parameters ignores the body entirely; a field present with a JSON null value counts as absent for required, optional, and forbidden-field rules alike; and calendar-date fields must be strict `YYYY-MM-DD` strings. Fourth, existence: path identifiers are resolved left to right, then body-referenced identifiers in their declared input order; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND`. Immediately after existence resolution — ahead of every later stage — result entry applies the one-result-per-sample rule: a sample that already carries a laboratory result is rejected with `ERR_RESULT_ALREADY_EXISTS` (§3.5). Fifth, optimistic concurrency: the `expected_seg_version` or `expected_plan_version` check of §2.7 runs here — after existence, before any state or business rule — and a mismatch yields `ERR_STALE_VERSION`. Sixth, state preconditions: the target entity must be in a status that permits the requested operation, else the operation's state error (`ERR_PLAN_INVALID_STATE`, `ERR_PLAN_NOT_OPEN_FOR_SAMPLING`, `ERR_PLAN_NOT_READY_FOR_ASSESSMENT`, `ERR_SAMPLE_INVALID_STATE`, `ERR_CALIBRATION_ALREADY_RECORDED`, `ERR_ASSESSMENT_INVALID_STATE`, `ERR_CONTROL_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`, `ERR_FIT_TEST_NOT_RECORDABLE`, or `ERR_NOTIFICATION_INVALID_STATE`). Seventh, cross-entity referential coherence: the sampled employee's membership, the calibration's pump, the batch's analyte, and the fit test's clearance ownership (§3.4, §3.5, §3.8). Eighth, segregation-of-duties and safety gates (§2.9). Ninth, temporal windows: the plan collection window, the batch intake window, and the retention gate. Tenth and last, uniqueness and capacity constraints: duplicate limits, pump serials, and memberships; pump double-booking; calibration reuse; batch capacity and contamination; the one-open-assessment-per-group rule; and the complete-field sample-count gate.

### 2.9. Segregation of Duties and Chain of Custody

Three evidentiary hand-offs are protected by segregation of duties, each enforced by comparing the acting operator's `X-User-ID` against the identifier recorded at the earlier step. A sampling plan may not be approved by the operator who created it: if the approver's `X-User-ID` equals the plan's `created_by_user_id`, the approval is rejected with `ERR_SOD_PLAN_APPROVER` (403). A laboratory result may not be entered by the operator who collected the sample: if the entering analyst's `X-User-ID` equals the sample's `collected_by_user_id`, the entry is rejected with `ERR_SOD_CHAIN_OF_CUSTODY` (403), preserving an unbroken chain of custody between field and laboratory. An exposure assessment may not be signed by the operator who prepared it: if the signer's `X-User-ID` equals the assessment's `prepared_by_user_id`, the signature is rejected with `ERR_SOD_ASSESSMENT_SIGNER` (403). Beyond these pairwise rules, safety gates guard specific transitions: a result may be entered only against a sample whose calibration is `VALID` (`ERR_CALIBRATION_NOT_VALID`; this gate applies to `PERSONAL` samples only, a `FIELD_BLANK` carrying no calibration), a fit-test result only against a current `CLEARED` medical clearance (`ERR_MEDICAL_CLEARANCE_NOT_CURRENT`), a respirator control may be accepted only when every group member is fit-tested and medically cleared (`ERR_FIT_TEST_MISSING_FOR_PPE`), and archival is blocked while an assessment is under legal hold (`ERR_LEGAL_HOLD_ACTIVE`).

### 2.10. Cascading Consistency and Counter Reconciliation

The system maintains derived counts and parent statuses automatically; no client ever writes them directly. A sampling plan carries two counters: `active_sample_count`, the number of its `PERSONAL` samples in `COLLECTED`, `SEALED`, or `ANALYZED` status, and `analyzed_valid_count`, the number of its `PERSONAL` samples in `ANALYZED` status; both counters stand at zero on a newly created plan, and `FIELD_BLANK` samples never enter either counter. These counters are recomputed whenever a sample is created, invalidated, or analyzed, and the recomputation by itself does not advance the plan's `version` — only an actual plan status transition does. A similar-exposure group's `headcount` is likewise the count of membership rows pointing at it, maintained on membership creation and transfer. Because invalidating a sample subtracts one from `active_sample_count` and collecting a replacement adds one back, the invalidate-then-replace pair leaves the count unchanged. When a counter change breaks a plan's completion criteria — an invalidation that drops the active or analyzed count below the requirement — the plan regresses automatically as described in §3.3, and when a contaminated blank invalidates already-analyzed samples the regression can reach through the plan to void its unsigned assessments (§3.5); each such cascade hops from trigger to sample to plan to assessment, mutating every affected row with its own `version` increment as §2.4 requires.

## 3. Business Logic & Workflows

This section walks the monitoring campaign as it actually unfolds: reference data first, then exposure groups, the sampling plan, field work, laboratory analysis, the exposure assessment, controls, health qualification, and finally notification and retention. Request parameters, thresholds, and error conditions are described where they arise in that narrative.

### 3.1. Reference Data: Sites, Employees, Exposure Limits, and Pumps

Everything begins with the client site. A `FirmAdmin` registers a site with its display `name` and an `industry_code` (a NAICS-style classifier), and may set `retention_years`, the number of years exposure records must be retained before archival is permitted; when omitted, `retention_years` defaults to 30, and it must be at least 1. This retention setting later determines each signed assessment's `retention_until` date (§3.9).

Employees are registered at a site with a `site_id` naming the employing site, the worker's `full_name`, an `external_ref` carrying the client-side employee number — accepted as-is, with no uniqueness constraint enforced by the system — and a `job_title` that later supports the rationale for similar-exposure grouping.

Exposure limits are the regulatory yardsticks of the whole system. A `FirmAdmin` registers a limit with an `analyte_code` identifying the substance (for example, PB for lead), a `basis` of either `OSHA_PEL` or `ACGIH_TLV`, a `limit_type` of either `TWA8` (an eight-hour time-weighted average limit) or `CEILING` (a never-exceed instantaneous limit), and the limit concentration `limit_mg_m3` in milligrams per cubic meter, which must be greater than zero. The optional `action_fraction` defines the action level as a fraction of the limit; it defaults to 0.1 and must be strictly greater than zero and strictly less than one. A registered limit carries a system-enforced `uniqueness` constraint on the triple of `analyte_code`, `basis`, and `limit_type`: registering a second limit with the same triple is rejected with `ERR_DUPLICATE_LIMIT` (409).

Sampling pumps are registered per site with a `site_id` and a `serial_number`; the serial must be unique within its site, and a duplicate registration is rejected with `ERR_DUPLICATE_PUMP_SERIAL` (409).

### 3.2. Similar-Exposure Groups and Memberships

An `IndustrialHygienist` defines a **similar-exposure group** (SEG) — the population of workers whose exposure profile is homogeneous enough to be monitored as a unit — by naming its owning `site_id`, giving the group a `name`, and writing a `task_description` describing the task or process that defines the group. Every SEG is governed by exactly one exposure limit, referenced as `exposure_limit_id`, and the group's `analyte_code` must equal the analyte of that linked limit; a mismatch is rejected with `ERR_ANALYTE_MISMATCH` (422). A new group starts with `headcount` zero, `current_class` `NONE` (the classification axis also takes the values `BELOW_ACTION`, `BELOW_PEL_MONITOR`, `UNCERTAIN`, and `ABOVE_PEL`, always assigned later from the latest signed assessment), and `next_sample_due_date` null until the group's first signed assessment sets it.

Workers join a group through memberships. Creating a membership references the `seg_id` and the `employee_id`, with an optional `is_primary` flag (default false) marking the worker's primary group. The membership's `uniqueness` constraint binds the pair: a second membership for the same employee in the same group is rejected with `ERR_DUPLICATE_MEMBERSHIP` (409). Each creation increments the group's `headcount` by one and advances the group's `version`. A membership may later be transferred to another group of the same site by supplying `target_seg_id`; a target group belonging to a different site is rejected with `ERR_INVALID_REQUEST`. A transfer into a group where the employee already holds a membership is rejected with `ERR_DUPLICATE_MEMBERSHIP` (409), while naming the membership's current group as the target is permitted as a no-op move: the membership and that single group each take a `version` increment and headcounts stand unchanged. A transfer decrements the source group's `headcount` by one and increments the destination group's by one — the site-wide sum of headcounts is conserved — and each of the two groups and the membership itself takes a `version` increment. Group `headcount` and `current_class` are the two inputs that size every sampling plan drafted against the group (§3.3).

### 3.3. The Sampling Plan Lifecycle

A sampling plan is the unit of campaign design. An `IndustrialHygienist` drafts a plan against a `seg_id`, declaring a `purpose` of `INITIAL` (the default), `FOLLOWUP`, or `VERIFICATION`; a collection window from `planned_start_date` through `planned_end_date`, both inclusive, with the end date no earlier than the start date (a reversed window is rejected with `ERR_INVALID_DATE_RANGE`); and two methodological rules used later in the laboratory calculations: `unsampled_time_rule`, either `ZERO_FILL` (the default, the OSHA convention) or `WORST_CASE`, and `volume_basis`, either `MEAN_FLOW` (the default) or `PRE_FLOW` (§3.5 explains how each governs the computed concentration and time-weighted average). The creator's `X-User-ID` is captured as `created_by_user_id`, the `approved_by_user_id` remains null until approval, and the plan is born in `DRAFT` status.

The plan's `required_sample_count` is computed at creation, and recomputed on every revision while the plan remains in `DRAFT`. A `VERIFICATION` plan always requires exactly 3 samples, skipping the sizing table and the adjustment below. For `INITIAL` and `FOLLOWUP` plans, the base requirement is looked up from the group's current `headcount`: a headcount of seven or fewer requires exactly that many samples; eight or nine requires seven; ten requires eight; eleven or twelve requires nine; thirteen or fourteen requires ten; fifteen through seventeen requires eleven; eighteen through twenty requires twelve; twenty-one through twenty-four requires thirteen; twenty-five through twenty-nine requires fourteen; thirty through thirty-seven requires fifteen; thirty-eight through forty-nine requires sixteen; and fifty or more requires seventeen. When the group's `current_class` at computation time is `UNCERTAIN` or `ABOVE_PEL`, three samples are added to the base; otherwise nothing is added. The final requirement is the larger of 3 and the adjusted base. For example, a group of three with class `NONE` drafting an `INITIAL` plan requires 3 samples; the same group with class `UNCERTAIN` drafting a `FOLLOWUP` plan requires 6; and a group of twenty-five drafting a `VERIFICATION` plan requires 3.

While the plan is in `DRAFT`, the owning hygienist may revise its window or its methodological rules; such a revision must carry `expected_plan_version` per §2.7 and recomputes the `required_sample_count` from the group's then-current `headcount` and `current_class`, incrementing the plan's `version`. When a revision supplies only one bound of the window, the new bound is validated against the stored other bound — the merged window must still satisfy end-no-earlier-than-start, else `ERR_INVALID_DATE_RANGE` — and this merged-window check runs after the plan's existence is resolved and before the optimistic-concurrency check. Revision is a `DRAFT`-only privilege: once the plan has moved on, the attempt is rejected as `ERR_PLAN_INVALID_STATE` (409).

Submitting the plan moves it `DRAFT → PENDING_APPROVAL`; submitting from any other status is rejected with `ERR_PLAN_INVALID_STATE`. A `CIHDirector` then dispositions it. Approval moves `PENDING_APPROVAL → APPROVED`, records the approver in `approved_by_user_id`, and is subject to the segregation-of-duties rule of §2.9: an approver whose `X-User-ID` equals the plan's `created_by_user_id` is rejected with `ERR_SOD_PLAN_APPROVER`. Rejection returns the plan `PENDING_APPROVAL → DRAFT` so the hygienist can revise it — the draft-submit-reject loop may repeat as many times as needed, and the `required_sample_count` is recomputed on the next revision while back in `DRAFT`. Approving or rejecting from any status other than `PENDING_APPROVAL` is rejected with `ERR_PLAN_INVALID_STATE`.

Once `APPROVED`, the plan is open for field work. When the field team believes collection is finished, the hygienist completes the field phase, moving `APPROVED → FIELD_COMPLETE` — but only if `active_sample_count` is at least `required_sample_count`; otherwise the completion is rejected with `ERR_INSUFFICIENT_VALID_SAMPLES` (409). Completing from any status other than `APPROVED` is `ERR_PLAN_INVALID_STATE`. From `FIELD_COMPLETE`, the plan advances itself: after each laboratory result is entered, once every active `PERSONAL` sample of the plan has reached `ANALYZED` and `analyzed_valid_count` is at least `required_sample_count`, the plan transitions `FIELD_COMPLETE → LAB_COMPLETE` automatically. `LAB_COMPLETE` is the plan's terminal status — laboratory work is done and the plan is ready for assessment.

Two regression loops keep the counters honest. If a sample invalidation while the plan is `FIELD_COMPLETE` drops `active_sample_count` below `required_sample_count`, the plan falls back `FIELD_COMPLETE → APPROVED` so replacement samples can be collected. If blank contamination (§3.5) invalidates already-analyzed samples while the plan is `LAB_COMPLETE`, dropping `analyzed_valid_count` below the requirement, the plan falls back `LAB_COMPLETE → APPROVED` — and any exposure assessment of that plan still in `DRAFT` or `UNDER_REVIEW` is voided with it, moving to `VOID`. An assessment already `SIGNED` is never voided: signed records are immutable. Every transition in this lifecycle, manual or automatic, increments the plan's `version`.

### 3.4. Pump Calibration and Field Sample Collection

Before any personal sample is collected, the pump that will draw it must be calibrated. A `FieldTechnician` records a pre-sampling calibration against a `pump_id` with the measured `pre_flow_lpm` flow rate in liters per minute, which must be greater than zero; the calibration is born with `result` `PENDING`, its `post_flow_lpm` and `drift_pct` null until the post-sampling flow is recorded, the technician's `X-User-ID` captured as `performed_by_user_id`, and `linked_sample_id` null until a sample references it.

Sample collection logs one record per sampled medium. A `FieldTechnician` logs a sample against an `APPROVED` plan via `sampling_plan_id` — collection against a plan in any other status is rejected with `ERR_PLAN_NOT_OPEN_FOR_SAMPLING` (409) — choosing a `sample_type` of `PERSONAL` or `FIELD_BLANK`. A `PERSONAL` sample must carry `employee_id`, `pump_id`, and `pre_calibration_id`; a `FIELD_BLANK` must carry none of the three, and violating either conditional rule is rejected with `ERR_INVALID_REQUEST`. The `collection_date` must fall within the plan's window from `planned_start_date` through `planned_end_date`, inclusive at both ends, else `ERR_SAMPLE_OUTSIDE_PLAN_WINDOW` (422). The `start_minute` is expressed in minutes after midnight, from 0 through 1439, and `duration_minutes` may range from 1 to 960 — a sixteen-hour ceiling. The collector's `X-User-ID` is captured as `collected_by_user_id`, and the sample is born in `COLLECTED` status.

Three referential checks protect a `PERSONAL` sample's integrity, all surfaced as 422 errors. The sampled employee must hold a membership in the plan's group, else `ERR_EMPLOYEE_NOT_SEG_MEMBER`. The referenced calibration must belong to the same pump the sample names — the calibration's pump must equal the sample's `pump_id` — else `ERR_CALIBRATION_PUMP_MISMATCH`. And the calibration must not already be linked to another sample that has not been invalidated, else `ERR_CALIBRATION_IN_USE` (409); a calibration serves at most one live sample at a time, and creating the sample records it in the calibration's `linked_sample_id`. Pumps themselves may not be double-booked: on a single `collection_date`, a pump may not appear on two non-`INVALIDATED` samples whose time intervals overlap, where each sample's interval begins at its `start_minute` and runs `duration_minutes` minutes forward, including the starting minute but excluding the ending minute; intervals that merely touch end-to-start are permitted. An overlapping booking is rejected with `ERR_PUMP_DOUBLE_BOOKED` (409). Creating a `PERSONAL` sample adds one to the plan's `active_sample_count`; per §2.10 this counter update does not by itself advance the plan's `version`.

Chain of custody continues with sealing: a technician seals a `COLLECTED` sample, moving it `COLLECTED → SEALED` and incrementing its `version`; sealing from any other status is rejected with `ERR_SAMPLE_INVALID_STATE` (409). A sample's `status` therefore walks from `COLLECTED` to `SEALED` and on to `ANALYZED`, with `INVALIDATED` as the off-ramp. A hygienist may manually invalidate a sample while it is `COLLECTED` or `SEALED`, optionally supplying a free-text `reason`; the stored `invalidate_reason` records `MANUAL`, and the attempt from any other status is `ERR_SAMPLE_INVALID_STATE`. A sample carries no `invalidate_reason` at all until it is invalidated. System-driven invalidation sets `invalidate_reason` to `PUMP_DRIFT` or `BLANK_CONTAMINATION` instead (§3.4 below and §3.5), and the contamination cascade can invalidate even an `ANALYZED` sample. Any invalidation recomputes the plan's counters, releases the calibration link by resetting the calibration's `linked_sample_id` to null, regresses the plan `FIELD_COMPLETE → APPROVED` or `LAB_COMPLETE → APPROVED` if the counters fall below the requirement, and increments the sample's `version`. The sample's computed fields — `air_volume_liters`, `concentration_mg_m3`, `sample_twa_mg_m3`, and `is_detect` — remain null until analysis (§3.5).

After sampling, the technician records the post-sampling flow `post_flow_lpm` on the `PENDING` calibration. The system computes `drift_pct` as the absolute difference between the post-sampling and pre-sampling flow rates, divided by `pre_flow_lpm`, multiplied by one hundred, and rounded half up to two decimal places. The calibration's `result` becomes `INVALID` only when `drift_pct` is strictly greater than 5.00; a drift of exactly 5.00 records `VALID`. Recording a post-flow on a calibration whose `result` is already `VALID` or `INVALID` is rejected with `ERR_CALIBRATION_ALREADY_RECORDED` (409). An `INVALID` verdict cascades immediately: the calibration's linked sample, if still `COLLECTED` or `SEALED`, is invalidated with `invalidate_reason` `PUMP_DRIFT`, which recomputes the plan's counters and may regress the plan as described above. Both terminal verdicts store `post_flow_lpm` and `drift_pct` and increment the calibration's `version`.

### 3.5. Laboratory Analysis and the Blank-Contamination Cascade

A `LabAnalyst` opens an analysis batch for a site, naming the `analyte_code` the batch will measure, the limit of detection `lod_ug` in micrograms (greater than zero), and the limit of quantitation `loq_ug` (no smaller than `lod_ug`). The batch accepts results only within an intake window from `window_start_date` through `window_end_date`, inclusive at both ends, with the end no earlier than the start (else `ERR_INVALID_DATE_RANGE`), and holds at most `max_capacity` results (at least 1). A new batch's `intake_count` is zero and its `contaminated` flag is false.

Result entry is the most heavily gated write in the system. A `LabAnalyst` enters a result by naming the `field_sample_id`, the `lab_batch_id`, and the measured `mass_ug` in micrograms (zero or more). One result per sample: a sample that already carries a result — as every `ANALYZED` sample does, and as a sample invalidated after analysis does — is rejected with `ERR_RESULT_ALREADY_EXISTS` (409), and this check precedes the state gates. A never-resulted sample must be `SEALED`; entering against a `COLLECTED` or `INVALIDATED` sample is rejected with `ERR_SAMPLE_INVALID_STATE`. The sample's plan must be `FIELD_COMPLETE` or `LAB_COMPLETE`; entering against a plan in any other status is rejected with `ERR_PLAN_INVALID_STATE`. The batch's `analyte_code` must equal the analyte of the group the sample's plan belongs to, else `ERR_ANALYTE_MISMATCH`. The current logical date must fall within the batch's intake window, inclusive at both ends, else `ERR_BATCH_WINDOW_CLOSED` (422). A batch whose `intake_count` has reached `max_capacity` rejects further intake with `ERR_BATCH_CAPACITY_FULL` (409), and a batch whose `contaminated` flag is set rejects all further intake with `ERR_BATCH_NOT_ACCEPTING` (409). Finally, the two safety gates of §2.9 apply: the entering analyst must not be the sample's collector (`ERR_SOD_CHAIN_OF_CUSTODY`), and the sample's calibration must stand at `VALID` — post-flow recorded and drift within limit — else `ERR_CALIBRATION_NOT_VALID` (409); as §2.9 notes, this calibration gate does not apply to a `FIELD_BLANK`, which carries no calibration.

A successful entry records the analyst's `X-User-ID` as `entered_by_user_id` and the logical timestamp as `reported_at`, increments the batch's `intake_count`, and derives two flags on the result: `is_detect`, true when `mass_ug` is at least the batch's `lod_ug`, and `is_quantifiable`, true when `mass_ug` is at least the batch's `loq_ug`. The sample transitions `SEALED → ANALYZED`, and a `PERSONAL` sample's four computed fields are filled in by the pinned calculation chain below; a `FIELD_BLANK` — carrying neither pump nor calibration — receives only its `is_detect` flag, its `air_volume_liters`, `concentration_mg_m3`, and `sample_twa_mg_m3` remaining null. For a `PERSONAL` sample the plan's `analyzed_valid_count` is recomputed, and if the plan now satisfies the completion rule of §3.3 it advances `FIELD_COMPLETE → LAB_COMPLETE`.

The air-volume-and-concentration chain runs in a pinned step order, rounding at every step (§2.6). First, the flow used: when the plan's `volume_basis` is `MEAN_FLOW`, the arithmetic mean of `pre_flow_lpm` and `post_flow_lpm`, rounded half up to three decimal places; when `PRE_FLOW`, the `pre_flow_lpm` value exactly as entered, with no averaging and no rounding. Second, `air_volume_liters` is that flow multiplied by `duration_minutes`, rounded half up to one decimal place. Third, `concentration_mg_m3` is `mass_ug` divided by `air_volume_liters`, rounded half up to four decimal places — micrograms per liter is numerically identical to milligrams per cubic meter, so the quotient is recorded directly. Consider a calibration of 1.5 liters per minute both before and after, a sixty-minute sample, and a measured mass of 5 micrograms: the flow used is 1.5, the volume 90.0 liters, and the concentration 0.0556 milligrams per cubic meter, and continuing this example into the time-weighted average below yields 0.0070 — whereas deferring all rounding to the end would wrongly yield 0.0069. The choice of basis matters too: with a pre-flow of 2.000, a post-flow of 1.900, a 200-minute sample, and a mass of 25 micrograms, `MEAN_FLOW` produces a time-weighted average of 0.0267 while `PRE_FLOW` produces 0.0260.

Immediately afterward the sample's eight-hour time-weighted average, `sample_twa_mg_m3`, is computed. A sample lasting at least 420 minutes — a seven-hour full-shift threshold — is a full-shift sample: its average is the concentration multiplied by `duration_minutes` and divided by 480 (the eight-hour shift basis), rounded half up to four decimal places. For a short sample under 420 minutes, the plan's `unsampled_time_rule` decides: under `ZERO_FILL` the same formula applies, so unsampled minutes contribute zero exposure; under `WORST_CASE` the sample is assigned the full measured concentration as its average, treating the entire shift as spent at that level. The two rules diverge sharply: a concentration of 0.0833 measured over 120 minutes yields 0.0208 under `ZERO_FILL` but 0.0833 under `WORST_CASE`. The sample's own `is_detect` flag is set from the same mass-versus-`lod_ug` comparison as the result's.

The blank-contamination cascade is the system's harshest integrity mechanism. If the analyzed sample is a `FIELD_BLANK` whose `mass_ug` reaches or exceeds the batch's `lod_ug`, the batch's `contaminated` flag is set to true and intake closes at once. Worse, every sibling sample already `ANALYZED` in that batch is invalidated with `invalidate_reason` `BLANK_CONTAMINATION` — the only path that invalidates an `ANALYZED` sample. Each such invalidation recomputes its plan's counters, and a plan that drops below its requirement regresses `LAB_COMPLETE → APPROVED` as §3.3 describes, voiding any of the plan's assessments still in `DRAFT` or `UNDER_REVIEW` (their `review_status` becomes `VOID`) while leaving `SIGNED` assessments untouched.

### 3.6. Exposure Assessment: Statistics, Classification, and Signature

With a plan `LAB_COMPLETE`, an `IndustrialHygienist` creates the exposure assessment that interprets it. The request names the `sampling_plan_id` — a plan not yet `LAB_COMPLETE` is rejected with `ERR_PLAN_NOT_READY_FOR_ASSESSMENT` (409) — and must carry `expected_seg_version` per §2.7, rejecting a stale view of the group with `ERR_STALE_VERSION` (412). A group may host at most one assessment whose `review_status` is `DRAFT` or `UNDER_REVIEW`; opening a second is rejected with `ERR_ASSESSMENT_ALREADY_OPEN` (409). Creation copies the plan's group into the assessment's `seg_id`, captures the creator as `prepared_by_user_id`, and supersedes the group's prior signed-and-current assessment if one exists: that prior assessment moves `SIGNED → SUPERSEDED`, its `is_current` flips to false, its own `version` increments, and the new assessment records it in `supersedes_assessment_id` (null when there is none). Creation itself also advances the group's `version` — this is precisely why the concurrency guard exists. The new assessment is born with `review_status` `DRAFT` and `is_current` false.

The statistical input set is the plan's `PERSONAL` samples in `ANALYZED` status; `FIELD_BLANK` and `INVALIDATED` samples never enter, and the set's size is recorded as `n_valid`. Because some samples may be non-detects, censored substitution runs first. The stored `substitution_rule` is `SQRT2` when the set holds at least 3 samples and at least half of them are detects (their `is_detect` true); otherwise it is `HALF`. For each non-detect sample, the system derives its detection-limit-equivalent time-weighted average: the batch's `lod_ug` divided by that sample's `air_volume_liters`, rounded half up to four decimal places, then multiplied by the sample's `duration_minutes` and divided by 480, rounded half up to four decimal places. Under `SQRT2`, the substituted value is that equivalent divided by the square root of two, rounded half up to four decimal places; under `HALF`, the equivalent divided by two, rounded half up to four decimal places — an equivalent of 0.0052, for instance, enters as 0.0037 under `SQRT2` and 0.0026 under `HALF`, and the two rules can yield different statistics and classifications. Detected samples enter with their stored `sample_twa_mg_m3` exactly as recorded. All statistics below operate on these substituted values, precisely as rounded here.

For a limit of `limit_type` `TWA8`, the system computes lognormal statistics over the substituted values. Each value is transformed by the natural logarithm; the `geo_mean` is the exponential of the arithmetic mean of those log values, and the `gsd` is the exponential of their sample standard deviation — the square root of the sum of squared deviations from the log mean, divided by one less than the count. The degrees of freedom are the lesser of one-less-than-the-count and ten, and the 95th-percentile Student t factor for that degree of freedom is taken from a fixed table: 6.314 for one degree of freedom, 2.920 for two, 2.353 for three, 2.132 for four, 2.015 for five, 1.943 for six, 1.895 for seven, 1.860 for eight, 1.833 for nine, and 1.812 for ten. The `ucl95` is the exponential of (the log mean plus the t factor times the standard deviation divided by the square root of the count); the `lcl95` is the exponential of (the log mean minus that same product). Each stored statistic is rounded half up to four decimal places, but classification always uses the unrounded values. When the set holds a single value, the standard deviation is undefined and is pinned to zero, so both confidence limits equal the geometric mean; the same collapse occurs whenever all substituted values are identical.

Classification compares the unrounded limits against two thresholds: L, the governing limit's `limit_mg_m3`, and A, the action level, which is L multiplied by the limit's `action_fraction`. Every comparison is strict, and the rules are evaluated in order. If `lcl95` is strictly greater than L, the `exposure_class` is `ABOVE_PEL` — a statistically certain exceedance. Otherwise, if `ucl95` is strictly greater than L, the class is `UNCERTAIN` — a possible exceedance that mandates a short re-sampling interval. Otherwise, if `ucl95` is strictly greater than A, the class is `BELOW_PEL_MONITOR` — controlled, with periodic monitoring. Otherwise the class is `BELOW_ACTION`. Because the comparisons are strict, an upper confidence limit exactly equal to L falls through to the third or fourth rule rather than `UNCERTAIN`, and one exactly equal to A classifies `BELOW_ACTION`.

For a limit of `limit_type` `CEILING`, no statistics are computed at all: `geo_mean`, `gsd`, `ucl95`, and `lcl95` are null. Classification instead uses the largest `concentration_mg_m3` among the input samples: `ABOVE_PEL` when that maximum is strictly greater than L; `BELOW_PEL_MONITOR` when it is strictly greater than A but not greater than L; and `BELOW_ACTION` otherwise.

The review axis then runs its course, cycling independently of the frozen classification. Submitting the assessment moves it `DRAFT → UNDER_REVIEW` (from any other status, `ERR_ASSESSMENT_INVALID_STATE`). A `CIHDirector` may return it `UNDER_REVIEW → DRAFT` for rework — the loop may repeat indefinitely, and the computed `exposure_class` does not change across it — or sign it, moving `UNDER_REVIEW → SIGNED`. Signing carries the segregation-of-duties gate of §2.9: a signer whose `X-User-ID` equals `prepared_by_user_id` is rejected with `ERR_SOD_ASSESSMENT_SIGNER`. Both actions increment the assessment's `version`.

Signature is the system's great fan-out moment, and its evaluation order is pinned. First the raw statistics and `exposure_class` stand as computed at creation. Second, every regulatory consequence keys off that raw class: `signed_at` and `signed_by_user_id` are recorded; `retention_until` is set to the signed calendar date advanced by the site's `retention_years` whole calendar years, preserving month and day (a February 29 signed date lands on February 28 of a non-leap target year); `is_current` becomes true; the group's `current_class` is set to the assessment's `exposure_class`; and the group's `next_sample_due_date` is set to the signed date plus the re-sampling interval for the class — 30 days for `ABOVE_PEL`, 90 days for `UNCERTAIN`, 180 days for `BELOW_PEL_MONITOR`, and 360 days for `BELOW_ACTION`. Both the assessment's and the group's `version` increment. The fan-out then creates one `PENDING` notification per current membership of the group, due fifteen working days after the signed date (§3.9), and — when the class is `ABOVE_PEL` — auto-drafts a control recommendation on the assessment being signed: an `ENGINEERING` control of `HIGH` priority, born `PROPOSED`, with `auto_created` true. Only after all of that is `adjusted_class` derived, per §3.7's respirator rule; where it applies, it never rewrites any of the raw-class consequences above.

### 3.7. Control Recommendations and Verification Sampling

An `IndustrialHygienist` proposes a control on an assessment by naming the `exposure_assessment_id`, choosing a `control_type` of `ENGINEERING`, `ADMINISTRATIVE`, or `PPE_RESPIRATOR`, writing a `description`, and setting a `priority` of `HIGH`, `MEDIUM`, or `LOW`. The `assigned_protection_factor` — the respirator's rated protection factor, which must be greater than 1 — is required exactly when the `control_type` is `PPE_RESPIRATOR` and forbidden on any other type; violating either rule is rejected with `ERR_INVALID_REQUEST`. Manually drafted controls are born `PROPOSED` with `auto_created` false; the auto-drafted `ABOVE_PEL` control of §3.6 arrives with `auto_created` true. A control's `verification_plan_id` and `implemented_at` remain null until implementation.

A `SiteSafetyManager` dispositions a `PROPOSED` control. Rejection moves it `PROPOSED → REJECTED`, a terminal status. Acceptance moves it `PROPOSED → ACCEPTED`, with a hard gate for respirator controls: accepting a `PPE_RESPIRATOR` control requires every employee holding a current membership in the parent group to hold at least one fit test in `PASSED` status whose `expiry_date` is on or after the current date, and at least one medical clearance in `CLEARED` status whose `expiry_date` is on or after the current date; if even one member lacks either credential, acceptance is rejected with `ERR_FIT_TEST_MISSING_FOR_PPE` (422). Acting on a control in any status other than `PROPOSED` is rejected with `ERR_CONTROL_INVALID_STATE` (409).

Implementation moves `ACCEPTED → IMPLEMENTED` and requires the parent assessment to stand at `SIGNED`, else `ERR_ASSESSMENT_NOT_SIGNED` (409); acting from any status other than `ACCEPTED` is `ERR_CONTROL_INVALID_STATE`. Implementation stamps `implemented_at` with the logical now and auto-creates a verification sampling plan for the same group: `purpose` `VERIFICATION`, a window opening the calendar day after the implementation date and closing thirty days after it, status `DRAFT`, the implementer's `X-User-ID` as its creator, the default methodological rules (`ZERO_FILL` unsampled time and `MEAN_FLOW` volume basis), and — per the flat rule of §3.3 — a `required_sample_count` of 3. The new plan's identifier is recorded in the control's `verification_plan_id`. Implementation also pulls the group's `next_sample_due_date` forward: it becomes the earlier of its existing value and the date fourteen days after implementation; if no due date exists yet, the fourteen-day candidate wins. The group's `version` increments with this update.

Verification closes the loop. A `CIHDirector` verifies an `IMPLEMENTED` control — any other status is `ERR_CONTROL_INVALID_STATE` — and the verification succeeds only when the control's verification plan holds an assessment that is current (`is_current` true), `SIGNED`, and classified `BELOW_ACTION` or `BELOW_PEL_MONITOR`; anything short of that is rejected with `ERR_VERIFICATION_NOT_CLEAN` (409). Success moves the control `IMPLEMENTED → VERIFIED`, its terminal success status. Every control action in this lifecycle — accept, reject, implement, verify — increments the control's `version`.

The protection factor earns a second life at assessment signature time. After the raw class and all its regulatory consequences are fixed (§3.6), the system checks whether the assessment being signed carries at least one `PPE_RESPIRATOR` control in `ACCEPTED`, `IMPLEMENTED`, or `VERIFIED` status. If so, the unrounded `ucl95` and `lcl95` are each divided by that control's `assigned_protection_factor` — when several controls qualify, the one created most recently — each quotient rounded half up to four decimal places, and the same strict classification thresholds of §3.6 are applied to the adjusted pair to produce the assessment's `adjusted_class`. Without a qualifying control, `adjusted_class` is null — as it always is for a `CEILING`-governed assessment, which carries no confidence limits to adjust. The adjusted class is informational only: it never rewrites the group's `current_class`, its due date, or any notification.

### 3.8. Medical Clearance and Respirator Fit Testing

Respirator controls rest on two worker-qualification records. A `SiteSafetyManager` requests a medical clearance for an `employee_id`; the clearance is born `REQUESTED`, with `decided_at`, `decided_by_user_id`, and `expiry_date` all null. A `CIHDirector` decides it by supplying a `decision` of `CLEARED` or `DENIED`; deciding a clearance no longer in `REQUESTED` is rejected with `ERR_CLEARANCE_INVALID_STATE` (409). Either decision stamps `decided_at` and `decided_by_user_id` and increments the clearance's `version`; a `CLEARED` decision additionally sets `expiry_date` to the calendar date one year — 365 days — after the decision date, while `DENIED` is terminal with no expiry. Thereafter the clock sweep of §2.5 moves a `CLEARED` clearance to `EXPIRED` once the current date passes its `expiry_date`, and every fit test still `PASSED` against that clearance expires with it.

Fit tests hang off a specific clearance. A `SiteSafetyManager` schedules a test with the `employee_id`, the `medical_clearance_id`, the `respirator_model` tested, and the `test_date`; the referenced clearance must belong to that same employee, else `ERR_CLEARANCE_EMPLOYEE_MISMATCH` (422). The test is born `SCHEDULED`, its `expiry_date` derived at scheduling as the `test_date` plus 365 days, and `recorded_by_user_id` null until a result is recorded. A `FieldTechnician` records the outcome by supplying a `result` of `PASS` or `FAIL`, moving the test `SCHEDULED → PASSED` or `SCHEDULED → FAILED`; recording from any other status is rejected with `ERR_FIT_TEST_NOT_RECORDABLE` (409). Both outcomes are gated on medical currency: the linked clearance must stand at `CLEARED` with the current date on or before its `expiry_date`, else `ERR_MEDICAL_CLEARANCE_NOT_CURRENT` (422) — the gate applies equally to a failing result. Recording stamps `recorded_by_user_id` and increments the test's `version`, as does every later transition. A `PASSED` test later moves to `EXPIRED` when the current date passes its own `expiry_date`, or immediately when its linked clearance expires; `FAILED` and `EXPIRED` are terminal.

### 3.9. Employee Notification, Retention, and Archival

The moment an assessment is signed, every current member of the group receives a notification: one `PENDING` record per membership, each naming the `employee_id` and the `exposure_assessment_id`, with `sent_at`, `sent_by_user_id`, and `acknowledged_at` all null. The `due_date` gives the worker fifteen working days — Monday through Friday, with no holiday calendar — counted so that exactly fifteen working days fall between the signed date and the due date: counting begins the calendar day after the signed date and includes the due date itself. An assessment signed on Monday 2026-08-10 therefore produces notifications due Monday 2026-08-31.

Sending is shared between the `IndustrialHygienist` and the `SiteSafetyManager`: a notification in `PENDING` or `OVERDUE` moves to `SENT`, stamping `sent_at` and `sent_by_user_id` and incrementing the notification's `version`; sending from any other status is rejected with `ERR_NOTIFICATION_INVALID_STATE` (409). The clock sweep of §2.5 moves a `PENDING` notification to `OVERDUE` once the current date is strictly later than its `due_date` — on the due date itself it remains `PENDING` — and an `OVERDUE` notification is sent through the same action as a pending one. Acknowledgment belongs to the worker alone: an `Employee` acknowledges a `SENT` notification, moving it to its terminal `ACKNOWLEDGED` status, stamping `acknowledged_at`, and incrementing its `version`. The state gate runs first — acknowledging from any status other than `SENT` is rejected with `ERR_NOTIFICATION_INVALID_STATE` — and ownership is enforced only then: the caller's `X-User-ID` must equal the notification's `employee_id`, and anyone else's attempt is rejected with `ERR_ACK_FORBIDDEN` (403).

Retention closes the record's life. An assessment's `retention_until` — set at signature as the signed date plus the site's `retention_years` calendar years, same month and day — is the earliest archival date: an assessment signed 2026-08-10 under a thirty-year retention may be archived on 2056-08-10 itself, the gate being inclusive. A `CIHDirector` may toggle an assessment's `legal_hold` flag (default false) through the assessment update operation, which increments the assessment's `version`; a hold blocks archival. A `FirmAdmin` archives an assessment from `SIGNED` or `SUPERSEDED` — any other `review_status` is rejected with `ERR_ASSESSMENT_INVALID_STATE` — provided the current logical date is on or after `retention_until` (earlier attempts are rejected with `ERR_RETENTION_NOT_MET`, 409) and `legal_hold` is false (a live hold is rejected with `ERR_LEGAL_HOLD_ACTIVE`, 409). Archival moves the assessment to `ARCHIVED`, clears `is_current`, increments its `version`, and excludes it from the assessment list unless the caller passes `include_archived` as true; an archived assessment remains retrievable directly by its identifier.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints are mounted under the `/ih` prefix. Request payloads, computed fields, side effects, and error conditions are governed by the narratives of §2 and §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ih/sites` | Create a client site | FirmAdmin |
| GET | `/ih/sites` | List sites | All roles |
| GET | `/ih/sites/{id}` | Get a site | All roles |
| POST | `/ih/employees` | Register an employee at a site | FirmAdmin |
| GET | `/ih/employees` | List employees; optional `site_id` filter | All roles |
| GET | `/ih/employees/{id}` | Get an employee | All roles |
| POST | `/ih/exposure-limits` | Register a PEL/TLV limit; unique on the analyte-basis-type triple | FirmAdmin |
| GET | `/ih/exposure-limits` | List limits; optional `analyte_code` filter | All roles |
| GET | `/ih/exposure-limits/{id}` | Get a limit | All roles |
| POST | `/ih/pumps` | Register a sampling pump; serial unique per site | FirmAdmin |
| GET | `/ih/pumps` | List pumps; optional `site_id` filter | All roles |
| GET | `/ih/pumps/{id}` | Get a pump | All roles |
| POST | `/ih/segs` | Define a similar-exposure group; analyte must match the linked limit | IndustrialHygienist |
| GET | `/ih/segs` | List groups; optional `site_id` and `exposure_limit_id` filters | All roles |
| GET | `/ih/segs/{id}` | Get a group, including `headcount`, `current_class`, `next_sample_due_date`, and `version` | All roles |
| POST | `/ih/seg-memberships` | Add an employee to a group | IndustrialHygienist |
| GET | `/ih/seg-memberships` | List memberships; optional `seg_id` and `employee_id` filters | All roles |
| GET | `/ih/seg-memberships/{id}` | Get a membership | All roles |
| POST | `/ih/seg-memberships/{id}/transfer` | Move the membership to another group of the same site | IndustrialHygienist |
| POST | `/ih/sampling-plans` | Create a draft sampling plan; sample requirement computed at creation | IndustrialHygienist |
| GET | `/ih/sampling-plans` | List plans; optional `seg_id` filter | All roles |
| GET | `/ih/sampling-plans/{id}` | Get a plan | All roles |
| PUT | `/ih/sampling-plans/{id}` | Revise a draft plan (OCC-guarded); recomputes the sample requirement | IndustrialHygienist |
| POST | `/ih/sampling-plans/{id}/submit` | Submit a draft plan for approval | IndustrialHygienist |
| POST | `/ih/sampling-plans/{id}/approve` | Approve a pending plan; approver must differ from creator | CIHDirector |
| POST | `/ih/sampling-plans/{id}/reject` | Return a pending plan to draft for revision | CIHDirector |
| POST | `/ih/sampling-plans/{id}/complete-field` | Close field work once enough valid samples exist | IndustrialHygienist |
| POST | `/ih/pump-calibrations` | Record a pre-sampling flow (calibration pending) | FieldTechnician |
| GET | `/ih/pump-calibrations` | List calibrations; optional `pump_id` filter | All roles |
| GET | `/ih/pump-calibrations/{id}` | Get a calibration | All roles |
| POST | `/ih/pump-calibrations/{id}/record-post` | Record the post-sampling flow; computes drift and verdict, cascades on invalid | FieldTechnician |
| POST | `/ih/field-samples` | Log a collected sample against an approved plan | FieldTechnician |
| GET | `/ih/field-samples` | List samples; optional `sampling_plan_id`, `employee_id`, `pump_id`, `pre_calibration_id` filters | All roles |
| GET | `/ih/field-samples/{id}` | Get a sample | All roles |
| POST | `/ih/field-samples/{id}/seal` | Seal a collected sample (chain of custody) | FieldTechnician |
| POST | `/ih/field-samples/{id}/invalidate` | Manually invalidate a collected or sealed sample | IndustrialHygienist |
| POST | `/ih/lab-batches` | Open an analysis batch with detection limits and an inclusive intake window | LabAnalyst |
| GET | `/ih/lab-batches` | List batches; optional `site_id` filter | All roles |
| GET | `/ih/lab-batches/{id}` | Get a batch | All roles |
| POST | `/ih/lab-results` | Enter a result; analyzes the sample and may trigger contamination or completion cascades | LabAnalyst |
| GET | `/ih/lab-results` | List results; optional `field_sample_id` and `lab_batch_id` filters | All roles |
| GET | `/ih/lab-results/{id}` | Get a result | All roles |
| POST | `/ih/exposure-assessments` | Create an assessment for a lab-complete plan (OCC-guarded on the group); computes statistics and class, supersedes the prior signed assessment | IndustrialHygienist |
| GET | `/ih/exposure-assessments` | List assessments; optional `seg_id`, `sampling_plan_id`, `supersedes_assessment_id`, `include_archived` filters | All roles |
| GET | `/ih/exposure-assessments/{id}` | Get an assessment (archived assessments remain retrievable by id) | All roles |
| POST | `/ih/exposure-assessments/{id}/submit-review` | Submit a draft assessment for certification review | IndustrialHygienist |
| POST | `/ih/exposure-assessments/{id}/sign` | Sign an assessment; signer must differ from preparer; fires group, notification, and control fan-out | CIHDirector |
| POST | `/ih/exposure-assessments/{id}/reject-review` | Return an assessment to draft for rework | CIHDirector |
| PUT | `/ih/exposure-assessments/{id}` | Toggle the assessment's legal hold | CIHDirector |
| POST | `/ih/exposure-assessments/{id}/archive` | Archive a signed or superseded assessment past its retention date | FirmAdmin |
| POST | `/ih/control-recommendations` | Propose a control on an assessment | IndustrialHygienist |
| GET | `/ih/control-recommendations` | List controls; optional `exposure_assessment_id` and `verification_plan_id` filters | All roles |
| GET | `/ih/control-recommendations/{id}` | Get a control | All roles |
| POST | `/ih/control-recommendations/{id}/accept` | Accept a proposed control; respirator controls require every group member qualified | SiteSafetyManager |
| POST | `/ih/control-recommendations/{id}/reject` | Reject a proposed control | SiteSafetyManager |
| POST | `/ih/control-recommendations/{id}/implement` | Mark an accepted control implemented; spawns the verification plan and pulls the due date forward | SiteSafetyManager |
| POST | `/ih/control-recommendations/{id}/verify` | Verify an implemented control against a clean signed verification assessment | CIHDirector |
| POST | `/ih/medical-clearances` | Request a medical clearance for an employee | SiteSafetyManager |
| GET | `/ih/medical-clearances` | List clearances; optional `employee_id` filter | All roles |
| GET | `/ih/medical-clearances/{id}` | Get a clearance | All roles |
| POST | `/ih/medical-clearances/{id}/decide` | Decide a requested clearance (cleared or denied) | CIHDirector |
| POST | `/ih/fit-tests` | Schedule a fit test against a clearance of the same employee | SiteSafetyManager |
| GET | `/ih/fit-tests` | List fit tests; optional `employee_id` and `medical_clearance_id` filters | All roles |
| GET | `/ih/fit-tests/{id}` | Get a fit test | All roles |
| POST | `/ih/fit-tests/{id}/record-result` | Record a pass/fail result; requires a current cleared clearance | FieldTechnician |
| GET | `/ih/notifications` | List notifications; optional `employee_id` and `exposure_assessment_id` filters | All roles |
| GET | `/ih/notifications/{id}` | Get a notification | All roles |
| POST | `/ih/notifications/{id}/send` | Send a pending or overdue notification | IndustrialHygienist, SiteSafetyManager |
| POST | `/ih/notifications/{id}/acknowledge` | Acknowledge a sent notification; the addressed employee only | Employee |
| POST | `/ih/_clock/set_current_utc` | Set the logical clock and run the time-based sweeps | FirmAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SOD_PLAN_APPROVER` | 403 Forbidden |
| `ERR_SOD_CHAIN_OF_CUSTODY` | 403 Forbidden |
| `ERR_SOD_ASSESSMENT_SIGNER` | 403 Forbidden |
| `ERR_ACK_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_OPEN_FOR_SAMPLING` | 409 Conflict |
| `ERR_PLAN_NOT_READY_FOR_ASSESSMENT` | 409 Conflict |
| `ERR_SAMPLE_INVALID_STATE` | 409 Conflict |
| `ERR_CALIBRATION_ALREADY_RECORDED` | 409 Conflict |
| `ERR_CALIBRATION_NOT_VALID` | 409 Conflict |
| `ERR_CALIBRATION_IN_USE` | 409 Conflict |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_ALREADY_OPEN` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_SIGNED` | 409 Conflict |
| `ERR_CONTROL_INVALID_STATE` | 409 Conflict |
| `ERR_VERIFICATION_NOT_CLEAN` | 409 Conflict |
| `ERR_CLEARANCE_INVALID_STATE` | 409 Conflict |
| `ERR_FIT_TEST_NOT_RECORDABLE` | 409 Conflict |
| `ERR_NOTIFICATION_INVALID_STATE` | 409 Conflict |
| `ERR_LEGAL_HOLD_ACTIVE` | 409 Conflict |
| `ERR_RETENTION_NOT_MET` | 409 Conflict |
| `ERR_DUPLICATE_LIMIT` | 409 Conflict |
| `ERR_DUPLICATE_PUMP_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 Conflict |
| `ERR_PUMP_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BATCH_CAPACITY_FULL` | 409 Conflict |
| `ERR_BATCH_NOT_ACCEPTING` | 409 Conflict |
| `ERR_RESULT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_INSUFFICIENT_VALID_SAMPLES` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_EMPLOYEE_NOT_SEG_MEMBER` | 422 Unprocessable Entity |
| `ERR_CALIBRATION_PUMP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ANALYTE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLEARANCE_EMPLOYEE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MEDICAL_CLEARANCE_NOT_CURRENT` | 422 Unprocessable Entity |
| `ERR_FIT_TEST_MISSING_FOR_PPE` | 422 Unprocessable Entity |
| `ERR_SAMPLE_OUTSIDE_PLAN_WINDOW` | 422 Unprocessable Entity |
| `ERR_BATCH_WINDOW_CLOSED` | 422 Unprocessable Entity |
