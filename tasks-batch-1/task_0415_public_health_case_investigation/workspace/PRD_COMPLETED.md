# Public Health Case Investigation API — Product Requirements Document

## 1. Introduction

Public health agencies must move a reportable condition from the moment a laboratory result lands in their inbox all the way through to a state-level disease report — and they must do it consistently across many overlapping jurisdictions, against shifting infectious-period science, and under audit. This document specifies an API for a public-health surveillance platform that orchestrates that entire arc: electronic lab report (ELR) intake, case interview and exposure-window computation, contact elicitation and notification, quarantine and isolation monitoring, laboratory-result linkage, outbreak-cluster detection, cross-jurisdiction case transfer, and reporting to a state/NEDSS feed.

The platform is organized around a deterministic surveillance clock so that every temporal calculation — infectious windows, quarantine release dates, isolation end dates, monitoring elapse checks — is reproducible rather than wall-clock dependent. The reader should treat the system as a workflow engine layered over a compliance ledger: cases and contacts march through well-defined state machines, several operations cascade across multiple resources at once, and counts that summarize the live caseload (active monitoring per jurisdiction, contacts per case, members per cluster) are conserved quantities that the system must keep exactly balanced as those workflows advance and reverse. The intended operators are jurisdiction administrators who configure the program, intake processors who receive lab reports, case investigators who work cases, contact tracers who pursue exposed individuals, and epidemiology analysts who manage clusters, transfers, and state reporting.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles: `JurisdictionAdmin`, `IntakeProcessor`, `CaseInvestigator`, `ContactTracer`, and `EpiAnalyst`.

Two of these roles are program-wide and carry no jurisdiction scoping. When `X-User-Role` is `JurisdictionAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the administrator configures programs, jurisdictions, and reportable conditions and operates across the whole program. When `X-User-Role` is `EpiAnalyst`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the analyst manages clusters, transfers, and exports program-wide. The server may record such an opaque identifier but never compares it against any entity's `id`.

The other three roles are jurisdiction-scoped and are bound to a concrete jurisdiction. When `X-User-Role` is `IntakeProcessor`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks compare the target resource's jurisdiction to `X-User-ID`. When `X-User-Role` is `CaseInvestigator`, `X-User-ID` is the `id` of the acting `Jurisdiction`, and the investigator may act only on cases whose `jurisdiction_id` equals `X-User-ID`. When `X-User-Role` is `ContactTracer`, `X-User-ID` is the `id` of the acting `Jurisdiction`, and the tracer may act only on contacts whose `monitoring_jurisdiction_id` equals `X-User-ID`. Any attempt by a scoped role to operate on a resource outside its own jurisdiction is denied with `ERR_JURISDICTION_SCOPE_VIOLATION`. This scope check applies to the case interview, classify, close, reopen, and link-lab-result operations, and to the full contact lifecycle.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; an out-of-range `limit` is not rejected but is clamped into that range (a value below 1 is raised to 1, a value above 100 is lowered to 100). The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Surveillance Clock

Most resources in the system — surveillance programs, jurisdictions, reportable conditions, cases, lab results, contacts, monitoring periods, jurisdiction transfers, outbreak clusters, and NEDSS exports — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification to the resource.
- `version` (integer): a system-managed counter that starts at its initial value and increments by one on every mutation of the resource.

There is one deliberate exception. An `ExposureEvent` is an append-only encounter record: it carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because it is never modified after creation.

Time in this system does not come from the wall clock. Each `SurveillanceProgram` owns a deterministic surveillance clock exposed as `current_date`, a UTC date-time that defaults to `2026-01-01T00:00:00.000Z` when the program is created and advances only through the explicit clock-setting capability. Every temporal computation in the platform — infectious windows, quarantine and isolation end dates, the elapsed-monitoring check — reads `current_date` rather than the host's real time, which makes those computations fully reproducible.

### 2.5. Nested Resource Retrieval and Referential Integrity

Resources in this platform form flat peer collections beneath the surveillance program rather than deep URL nesting, but many operations address a resource by an identifier embedded in the path and reference further resources by foreign keys in the body. When a path contains a resource identifier, the system validates it before doing any business work: an unknown program, jurisdiction, condition, case, contact, lab result, monitoring period, transfer, cluster, export, or exposure event surfaces the matching not-found error (`ERR_PROGRAM_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_CONDITION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_LAB_RESULT_NOT_FOUND`, `ERR_MONITORING_PERIOD_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_CLUSTER_NOT_FOUND`, `ERR_EXPORT_NOT_FOUND`, or `ERR_EXPOSURE_EVENT_NOT_FOUND`). When a path carries several identifiers, they are validated left to right, and the first one that does not resolve produces its own not-found error before any later identifier is examined.

The same not-found discipline extends to foreign keys supplied in a request body. On any create or resolve operation, the foreign keys it accepts — `program_id`, `jurisdiction_id`, `condition_code`, `source_case_id`, `lab_result_id`, `contact_id`, `to_jurisdiction_id`, and `case_id` — must each reference an existing row within the same program; an unresolved reference yields the corresponding not-found error. Referential validation of path identifiers and body foreign keys happens before any state or business-rule evaluation.

### 2.6. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed precedence so that the rejection a client sees is deterministic. Header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) is checked first. Role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`) is checked second. Existence of every path identifier (the relevant not-found error) is third, evaluated left to right. Existence of every body foreign key within the program (the relevant not-found error) is fourth. The jurisdiction scope check (`ERR_JURISDICTION_SCOPE_VIOLATION`) for scoped roles is fifth. For the transfer-request operation, the optimistic-concurrency check on the case version (`ERR_STALE_CASE_VERSION`) is sixth and therefore precedes every state and business check on the case. The state-legality check for the requested transition (a state-specific conflict error) is seventh. Domain-specific temporal and business constraints follow after that, and field-level input validation (`ERR_INVALID_REQUEST`) governs malformed or out-of-domain inputs. Where two business checks on the same operation have a defined order — for example lab-linkage condition matching before patient matching — that order is stated alongside the workflow it guards.

### 2.7. State Propagation, Cascades, and Conserved Counters

Several operations in this system mutate more than one resource in a single atomic step, and the platform must keep the dependent counters exactly balanced. Whenever a resource is mutated — including when it is touched only as the secondary effect of an operation on another resource — its `updated_at` is refreshed and its `version` is incremented (for resources that carry a version).

Three counts are conserved quantities that the system maintains by paired increment/decrement actions rather than recomputation from scratch on read:

- `Jurisdiction.active_monitoring_count` tracks the number of contacts currently in `MONITORING_ACTIVE` whose `monitoring_jurisdiction_id` equals that jurisdiction's `id`. It rises by one when a contact begins active monitoring and falls by one whenever such a contact leaves active monitoring (completion, void, promotion, or a not-a-case cascade), and it moves between jurisdictions when a case is rehomed.
- `Case.contact_count` tracks the number of non-`VOIDED` contacts whose `source_case_id` equals that case's `id`. It rises by one when a contact is elicited and falls by one when such a contact is voided.
- `OutbreakCluster.member_case_count` tracks the number of cases whose `cluster_id` equals that cluster's `id`.

These counters are described in detail alongside the workflows that move them in Section 3; the principle to carry forward here is that no workflow may leave a counter out of step with the rows it summarizes.

### 2.8. Optimistic Concurrency on Jurisdiction Transfers

Routing a case to another jurisdiction is the one operation in this platform protected by optimistic concurrency control. A request to open a jurisdiction transfer must carry `expected_case_version`, the value of the target case's `version` that the requester last observed. Before any state or business precondition on the case is evaluated, the system compares `expected_case_version` to the case's current `version`; if they differ, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP status 412. A prior transfer request, a classification, or a lab-result link may have legitimately advanced the case's `version` and changed the jurisdiction or status the requester was reasoning about, so a mismatched version means the requester's view is stale and the transfer is refused rather than allowed to route a case the requester no longer understands. This `expected_case_version` field is required only on the transfer-request operation; no other endpoint in the system accepts or requires a version field.

### 2.9. Precision and Date Arithmetic

All scoring computations in this system — the contact priority score, the case completeness score, and the member and onset aggregates on a cluster — produce integers. The priority and completeness scores are clamped to the inclusive range from 0 to 100. Date computations — infectious window bounds, quarantine end, isolation end — operate in whole days against UTC-midnight datetimes: adding or subtracting a number of days shifts the date by that many 24-hour days and leaves the time-of-day at UTC midnight. There are no fractional-day or monetary roundings in this domain; the only rounding-equivalent operation is the clamp on the two scores.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Programs, Jurisdictions, and Reportable Conditions

A `JurisdictionAdmin` bootstraps the surveillance environment. Creating a `SurveillanceProgram` requires a `name` and accepts an optional `description`; on creation the program's `current_date` is initialized to `2026-01-01T00:00:00.000Z`. The administrator may later advance the deterministic clock through a clock-setting capability that accepts a `to_iso8601` instant and assigns it to the program's `current_date`; this is the only way `current_date` ever changes.

Beneath a program, the administrator registers jurisdictions and reportable conditions, each referencing its program through `program_id`. A `Jurisdiction` is created with a `name` and a five-digit county `fips_code`; the `fips_code` must be unique across the jurisdictions of the same program, and a duplicate is rejected with `ERR_DUPLICATE_KEY`. Each jurisdiction begins with its `active_monitoring_count` at 0.

A `ReportableCondition` captures the epidemiological parameters that drive every downstream window and threshold for one condition. It is created with a `condition_code` — which must be unique within the program, again rejecting a collision with `ERR_DUPLICATE_KEY` — and a human-readable `display_name`. The condition then defines the infectious-period geometry through `presymptomatic_days`, the non-negative number of days before onset or specimen collection at which the infectious period opens, and `infectious_tail_days`, the non-negative number of days after that anchor at which it closes. Quarantine behavior is governed by `quarantine_days`, the standard quarantine length in days measured from last exposure; `test_based_release_days`, the reduced quarantine length applied when a qualifying negative test exists, which must not exceed `quarantine_days`; and `test_release_earliest_offset_days`, the earliest day after last exposure at which a negative specimen can qualify for test-based release, defaulting to 5. Isolation behavior is governed by `isolation_min_days`, the minimum isolation length in days from onset or specimen, and `fever_free_days`, the number of days of symptom resolution required after the last symptomatic date before isolation may end. Clustering behavior is governed by `cluster_min_cases`, the minimum number of confirmed cases sharing a condition, location, and onset window required to auto-form an outbreak cluster (defaulting to 3 and never below 2), and `cluster_window_days`, the maximum gap in days between member case onset dates for cluster co-membership (defaulting to 14). Finally, `requires_lab_confirmation` is a boolean defaulting to true; when true, classifying a case to confirmed demands at least one positive linked lab result. All of these day-count parameters are non-negative integers.

### 3.2. Lab Report Intake, Linkage, and Correction

An `IntakeProcessor` receives electronic lab reports. Submitting a `LabResult` requires its `program_id`, the reporting `jurisdiction_id` derived from the facility, the `condition_code` under test, the de-identified `patient_reference`, a `result_value` that is one of `POSITIVE`, `NEGATIVE`, or `INDETERMINATE`, and the `specimen_collection_date`. A freshly intaken result begins in `RECEIVED`.

At intake the system attempts automatic linkage. If exactly one non-closed case — that is, a case in `OPEN` or `UNDER_INVESTIGATION` — exists in the program whose `patient_reference` and `condition_code` both match the incoming result, the result is linked to that case: its `status` advances `RECEIVED → LINKED`, its `linked_case_id` is set to that case, and the case's `linked_positive_count` and `completeness_score` are recomputed. If no such single matching case exists, the result instead becomes `UNLINKED` and carries no `linked_case_id`. The `UNLINKED` state is also the state from which a result can later be linked by hand.

A case investigator may link a result to a case manually rather than relying on the intake auto-match. The result supplied by `lab_result_id` must be in `RECEIVED` or `UNLINKED` to be linkable; a result in any other state is rejected with `ERR_LAB_NOT_LINKABLE`. The target case must not be `CLOSED`, or the link is rejected with `ERR_CASE_NOT_LINKABLE`. Two attribute checks then run in a fixed order: the lab result's `condition_code` must equal the case's `condition_code`, checked first and rejected with `ERR_LAB_CONDITION_MISMATCH`; and the lab result's `patient_reference` must equal the case's `patient_reference`, checked second and rejected with `ERR_LAB_PATIENT_MISMATCH`. On success the result transitions `RECEIVED → LINKED` (or `UNLINKED → LINKED`), its `linked_case_id` is set to the case, and the case's `linked_positive_count` (the number of linked results whose `result_value` is `POSITIVE`) and `completeness_score` are recomputed; the manual-link operation returns the updated lab result object in its `data` field.

When a corrected result arrives, the intake processor supersedes the prior one. Only a result in `LINKED` may be superseded; otherwise the request is rejected with `ERR_LAB_NOT_SUPERSEDABLE`. Superseding moves the result `LINKED → SUPERSEDED`, clears its `linked_case_id`, and recomputes the previously linked case's `linked_positive_count` and `completeness_score` so the case no longer counts the detached result.

### 3.3. Opening and Interviewing a Case

A case enters the system either from the lab side or by hand. Both an `IntakeProcessor` and a `CaseInvestigator` may open a `Case`, supplying its `program_id`, owning `jurisdiction_id` (which drives jurisdiction scoping), `condition_code` (which must match a reportable condition in the program), and a de-identified `patient_reference`. Optionally, the opener may supply the `source_lab_result_id` of the ELR result that spawned the case, the `symptom_onset_date`, the `specimen_collection_date`, the `last_symptomatic_date`, the `is_symptomatic` flag (defaulting to true), and an `exposure_setting_location_id` — a free-text location key such as a facility or event identifier used later for outbreak co-location. A new case begins in `OPEN` with `classification` `SUSPECT`, `completeness_score` 0, `contact_count` 0, and `linked_positive_count` 0. A case promoted from a contact additionally carries a `source_contact_id` linking back to the contact that produced it.

The investigation begins with the case interview, which advances the case from `OPEN` to `UNDER_INVESTIGATION` (and likewise re-enters `UNDER_INVESTIGATION` from `REOPENED` on the revert loop described later). The interview is legal only when the case is in `OPEN` or `REOPENED`; from any other state it is rejected with `ERR_CASE_NOT_INTERVIEWABLE`. The acting investigator's jurisdiction must cover the case's `jurisdiction_id`, or the request is denied with `ERR_JURISDICTION_SCOPE_VIOLATION`. The interview accepts (and may revise) `symptom_onset_date`, `specimen_collection_date`, `last_symptomatic_date`, and `is_symptomatic`. If the resulting `is_symptomatic` is true, a `symptom_onset_date` must be present; otherwise a `specimen_collection_date` must be present. Failing this requirement raises `ERR_ONSET_OR_SPECIMEN_REQUIRED`.

A successful interview sets `interview_completed` to true, computes the infectious window, and recomputes the completeness score. The infectious window is the central exposure-period gate. Let the matching reportable condition supply the geometry. When the case is symptomatic, the anchor date is `symptom_onset_date`; when it is asymptomatic, the anchor date is `specimen_collection_date`. The `infectious_start_date` is the anchor shifted earlier by `presymptomatic_days` days, and the `infectious_end_date` is the anchor shifted later by `infectious_tail_days` days; both are stored as UTC-midnight datetimes. Because the symptomatic and asymptomatic variants anchor on different dates, the same calendar inputs can yield a different window depending on `is_symptomatic`. The window is treated as a closed, inclusive interval from `infectious_start_date` through `infectious_end_date`, and it is the gate that governs which exposure encounters may be recorded against the case.

### 3.4. Classifying, Closing, and Reopening a Case

Once a case has been interviewed, a `CaseInvestigator` classifies it. Classification is legal only from `UNDER_INVESTIGATION`; attempting it from any other state is rejected with `ERR_CASE_NOT_CLASSIFIABLE`, and attempting it before the interview has run (that is, while `interview_completed` is false) is rejected with `ERR_INTERVIEW_NOT_COMPLETE`. The submitted `classification` must be one of `CONFIRMED`, `PROBABLE`, or `NOT_A_CASE`; any other value is rejected with `ERR_INVALID_CLASSIFICATION`. A successful classify advances the case `UNDER_INVESTIGATION → CLASSIFIED`, sets `classification` to the requested value, and recomputes the completeness score. The three classification branches carry distinct side effects.

If the requested classification is `CONFIRMED` and the matching condition's `requires_lab_confirmation` is true, the case's `linked_positive_count` must be at least 1, or the classify is rejected with `ERR_LAB_CONFIRMATION_REQUIRED`. On a confirmed classification the system computes the isolation end date. When the case is symptomatic, the anchor is `symptom_onset_date`; the minimum end is that anchor plus `isolation_min_days` days, and if a `last_symptomatic_date` is present a symptom-resolution end is computed as that date plus `fever_free_days` days, with `isolation_end_date` taking whichever of the minimum end and the symptom-resolution end falls later. When no `last_symptomatic_date` is present, the symptom-resolution end is taken to equal the minimum end, so the minimum end wins. When the case is asymptomatic, the anchor is `specimen_collection_date` and `isolation_end_date` is simply that anchor plus `isolation_min_days` days. Additionally, when a case is confirmed and carries an `exposure_setting_location_id`, the system runs the outbreak-cluster evaluation described below, which may set the case's `cluster_id`, increment an existing cluster's `member_case_count`, or create a new cluster.

If the requested classification is `PROBABLE`, the case is simply marked classified with no isolation computation, no cluster evaluation, and no cascade — the completeness score is still recomputed.

If the requested classification is `NOT_A_CASE`, the system runs a depth-three cascade. Every non-`VOIDED` contact whose `source_case_id` equals this case is voided. For each such contact that is in `MONITORING_ACTIVE`, its `ACTIVE` monitoring period is first released to `RELEASED_EARLY` and the contact's `monitoring_jurisdiction`'s `active_monitoring_count` is decremented by one; then, for every voided contact, the case's `contact_count` is decremented by one. The case's completeness score is recomputed after the cascade settles.

A classified case is closed by a case investigator. Closing is legal only from `CLASSIFIED`, rejected otherwise with `ERR_CASE_NOT_CLOSEABLE`. Two further guards protect the close: no contact whose `source_case_id` equals this case may be in `MONITORING_ACTIVE`, or the close is rejected with `ERR_ACTIVE_MONITORING_EXISTS`; and no jurisdiction transfer for this case may be in `REQUESTED`, or the close is rejected with `ERR_TRANSFER_PENDING_EXISTS`. A successful close advances the case `CLASSIFIED → CLOSED`. `CLOSED` is the terminal resting state of the case lifecycle.

A closed case can be reopened by a case investigator, forming the cyclic revert loop. Reopen is legal only from `CLOSED`, rejected otherwise with `ERR_CASE_NOT_REOPENABLE`. Reopening advances the case `CLOSED → REOPENED`, resets `classification` to `SUSPECT`, sets `interview_completed` back to false, clears `infectious_start_date`, `infectious_end_date`, and `isolation_end_date`, and recomputes the completeness score. From `REOPENED` the case re-enters investigation through a fresh interview, recomputing the infectious window and completeness score exactly as the first interview did.

### 3.5. Investigation Completeness Scoring

The `completeness_score` is an integer from 0 to 100 that summarizes how thoroughly a case has been worked, and it is recomputed on each of the investigation's milestones: interview, classify, and reopen on the case itself; lab-result link and supersede; and contact elicitation and void. The score starts at zero and accumulates four independent contributions. Forty points are added when `interview_completed` is true. Twenty points are added when both `infectious_start_date` and `infectious_end_date` are present. Twenty points are added when the case's `contact_count` is at least 1. Twenty points are added when the case has at least one linked positive lab result, or equivalently when the case has at least one `LINKED` lab result whose `linked_case_id` references it. The sum, which ranges from 0 through 100, is stored as the integer `completeness_score`.

### 3.6. Contact Elicitation and Prioritization

A `ContactTracer` elicits the contacts named during a case interview. Eliciting a `Contact` requires its `program_id`, the `source_case_id` of the index case, the responsible `monitoring_jurisdiction_id`, a de-identified `contact_reference`, the `exposure_setting` (one of `HOUSEHOLD`, `HEALTHCARE`, `WORKPLACE`, `SOCIAL`, or `COMMUNITY`), the closest `proximity_meters` during exposure (a non-negative number), the total `cumulative_exposure_minutes` (a non-negative integer), and the `last_exposure_date` that drives the quarantine math. An optional `is_high_risk_contact` flag (defaulting to false) marks a vulnerable contact such as someone immunocompromised or elderly. A newly elicited contact begins in `ELICITED`. Eliciting a contact increments the source case's `contact_count` by one and recomputes that case's completeness score.

At elicitation the system computes the contact's priority score and band. The score begins from a base determined by `exposure_setting`: 50 for `HOUSEHOLD`, 40 for `HEALTHCARE`, 25 for `WORKPLACE`, 15 for `SOCIAL`, and 10 for `COMMUNITY`. A proximity bonus is added: 20 points when `proximity_meters` is less than 1, 10 points when `proximity_meters` is at most 2 (but not less than 1), and 0 points otherwise. A duration bonus is added: 15 points when `cumulative_exposure_minutes` is at least 15, 5 points when it is at least 5 (but below 15), and 0 points otherwise. A vulnerability bonus of 20 points is added when `is_high_risk_contact` is true, and 0 otherwise. The raw sum of base, proximity, duration, and vulnerability is then clamped into the inclusive range 0 to 100 to produce the integer `priority_score`. The `priority_band` is derived from the score: `HIGH` when `priority_score` is at least 70, `MEDIUM` when it is at least 40 (but below 70), and `LOW` otherwise.

### 3.7. Quarantine Windows and Qualifying Tests

The moment a contact is elicited, the system also computes its quarantine end on the standard basis. Using the source case's condition parameters, the standard quarantine end is the contact's `last_exposure_date` plus `quarantine_days` days, and this STANDARD computation sets `quarantine_release_basis` to `STANDARD` and writes `quarantine_end_date`. The earliest date at which a negative specimen could qualify for an abbreviated release is the `last_exposure_date` plus `test_release_earliest_offset_days` days.

A contact tracer may later record a qualifying test for the contact by supplying a `result_value` and a `specimen_collection_date`. A test qualifies — setting `has_qualifying_negative_test` to true — when its `result_value` is `NEGATIVE` and its `specimen_collection_date` is on or after that earliest qualifying date. When a qualifying negative test exists, the quarantine is recomputed on the test-based basis: `quarantine_release_basis` becomes `TEST_BASED` and `quarantine_end_date` becomes the `last_exposure_date` plus `test_based_release_days` days, which (because `test_based_release_days` does not exceed `quarantine_days`) is the same as or earlier than the standard end for the same `last_exposure_date`. If no qualifying negative test exists, the quarantine stays on the standard basis. Both variants compute in whole days against UTC-midnight datetimes.

### 3.8. Notification, Monitoring, and Release

With a contact elicited, the tracer drives notification. Queuing a contact for notification advances it to `NOTIFICATION_PENDING` and is legal only from `ELICITED` or from `NOTIFICATION_FAILED` (the retry path); from any other state it is rejected with `ERR_CONTACT_NOT_QUEUEABLE`, and the acting tracer's jurisdiction must cover the contact's `monitoring_jurisdiction_id` or the request is denied with `ERR_JURISDICTION_SCOPE_VIOLATION`. Recording a notification outcome is legal only from `NOTIFICATION_PENDING`, rejected otherwise with `ERR_CONTACT_NOT_PENDING_NOTIFICATION`; the request carries an `outcome`. A `SUCCESS` outcome advances the contact `NOTIFICATION_PENDING → NOTIFIED` and increments `notification_attempts` by one; a `FAILED` outcome advances `NOTIFICATION_PENDING → NOTIFICATION_FAILED` and likewise increments `notification_attempts` by one, after which the contact can be re-queued, looping back to `NOTIFICATION_PENDING`.

Before monitoring can be activated, the tracer schedules a monitoring period for the contact. A `MonitoringPeriod` is created with a `monitoring_type` — `QUARANTINE` for an exposed contact or `ISOLATION` for a confirmed case's promoted contact — an inclusive `start_date`, and an inclusive `end_date` that must be on or after `start_date`. The period's `jurisdiction_id` is copied from the contact's `monitoring_jurisdiction_id` at scheduling time, and the period begins in `SCHEDULED`. A new monitoring period must not share any day with an existing non-terminal monitoring period (one in `SCHEDULED` or `ACTIVE`) for the same contact; an overlap is rejected with `ERR_MONITORING_PERIOD_OVERLAP`. Adjacency is permitted: a period whose `start_date` equals the prior period's `end_date` plus one day does not overlap.

Starting monitoring activates the contact and consumes the scheduled period. It is legal only from `NOTIFIED`, rejected otherwise with `ERR_CONTACT_NOT_NOTIFIED`. The contact's `quarantine_end_date` must already be present (set at elicitation), or the request is rejected with `ERR_QUARANTINE_WINDOW_MISSING`, and a `SCHEDULED` monitoring period for the contact must exist, or the request is rejected with `ERR_NO_SCHEDULED_MONITORING`. On success the contact advances `NOTIFIED → MONITORING_ACTIVE`, its scheduled monitoring period advances `SCHEDULED → ACTIVE` — when more than one `SCHEDULED` period exists for the contact, the earliest one by `created_at` ascending is the one activated — and the contact's `monitoring_jurisdiction`'s `active_monitoring_count` is incremented by one.

Completing monitoring is legal only from `MONITORING_ACTIVE`, rejected otherwise with `ERR_CONTACT_NOT_MONITORING`. It additionally requires that the program's `current_date` has reached or passed the contact's `quarantine_end_date`; if the window has not yet elapsed, the request is rejected with `ERR_MONITORING_NOT_ELAPSED`. On success the contact advances `MONITORING_ACTIVE → MONITORING_COMPLETE`, its active monitoring period advances `ACTIVE → COMPLETED`, and the `monitoring_jurisdiction`'s `active_monitoring_count` is decremented by one. `MONITORING_COMPLETE` is a terminal state.

### 3.9. Voiding and Promoting Contacts

A contact may be voided either manually by a tracer or as the cascade from a not-a-case classification. Voiding is legal only when the contact is in `ELICITED`, `NOTIFICATION_PENDING`, `NOTIFIED`, `NOTIFICATION_FAILED`, or `MONITORING_ACTIVE`; from any terminal state it is rejected with `ERR_CONTACT_NOT_VOIDABLE`. Voiding advances the contact to `VOIDED`, decrements the source case's `contact_count` by one, and recomputes the source case's completeness score. If the contact was in `MONITORING_ACTIVE` at the time of voiding, its `ACTIVE` monitoring period is additionally released to `RELEASED_EARLY` and the `monitoring_jurisdiction`'s `active_monitoring_count` is decremented by one. `VOIDED` is terminal.

When a monitored or notified contact becomes symptomatic, the tracer promotes it into a new index case, establishing the platform's self-referential lineage. Promotion is legal only from `MONITORING_ACTIVE` or `NOTIFIED`, rejected otherwise with `ERR_CONTACT_NOT_PROMOTABLE`, and the request must supply a `symptom_onset_date`, without which it is rejected with `ERR_ONSET_OR_SPECIMEN_REQUIRED`. Promotion creates a new `Case` in `OPEN` with `classification` `SUSPECT`, whose `source_contact_id` points back to this contact, whose `jurisdiction_id` is the contact's `monitoring_jurisdiction_id`, and whose `condition_code` is copied from the contact's source case; the new case's `patient_reference` is copied from the contact's `contact_reference`, its `is_symptomatic` is set to true and its `symptom_onset_date` is the value supplied on the promote request (with `specimen_collection_date`, `last_symptomatic_date`, and `exposure_setting_location_id` left unset), and the operation returns that newly created case with HTTP `201 Created`; the contact's `promoted_case_id` is set to the new case's id and the contact advances to `PROMOTED_TO_CASE`. Because that new case's `source_contact_id` references a contact whose own `source_case_id` is the origin case, the lineage links the new case back through the contact to its originating case. If the contact was in `MONITORING_ACTIVE` when promoted, its `ACTIVE` monitoring period is released to `RELEASED_EARLY` and the `monitoring_jurisdiction`'s `active_monitoring_count` is decremented by one; promotion from `NOTIFIED` touches no monitoring counts because no active period exists. `PROMOTED_TO_CASE` is terminal.

### 3.10. Recording Exposure Encounters

A contact tracer records the individual encounters between a contact and its index case as exposure events. Appending an `ExposureEvent` to a contact requires an `encounter_date` and accepts an optional free-text `setting_note`; the event's `program_id` and `case_id` are copied from the contact at creation (the `case_id` derived from the contact's `source_case_id`). The encounter is admissible only when its `encounter_date` falls inside the index case's closed, inclusive infectious window — that is, on or after the case's `infectious_start_date` and on or before its `infectious_end_date`. An encounter outside that window is rejected with `ERR_ENCOUNTER_OUTSIDE_INFECTIOUS_WINDOW`. Because the infectious window is established by the case interview, exposure events can only be recorded against a case whose interview has produced a window.

### 3.11. Outbreak Cluster Detection and Closure

Whenever a case is confirmed and carries an `exposure_setting_location_id`, the system evaluates outbreak-cluster membership. The clustering key is the pairing of the case's `condition_code` and its `exposure_setting_location_id`. The candidate peers are the other confirmed cases in the same program that share that key and whose `symptom_onset_date` falls within `cluster_window_days` days of this case's `symptom_onset_date` — meaning the absolute difference in whole days between the two onset dates is at most `cluster_window_days`. Candidate peers are considered in order of `symptom_onset_date` ascending, with `created_at` ascending as the tie-break. The prospective group is those candidate peers together with this case.

The evaluation resolves in one of three ways. If there is already an `ACTIVE` outbreak cluster that shares the same clustering key and whose anchor case lies within the onset window of this case, the case joins it: the case's `cluster_id` is set to that cluster, the cluster's `member_case_count` is incremented by one, and the cluster's `earliest_onset_date` and `latest_onset_date` are recomputed. Otherwise, if the size of the prospective group is at least the condition's `cluster_min_cases`, a new `OutbreakCluster` is created in `ACTIVE` status: its `condition_code` and `exposure_setting_location_id` are the shared key, its `anchor_case_id` is the group member with the earliest `symptom_onset_date` (with `created_at` ascending as the tie-break), every confirmed member of the group has its `cluster_id` set to the new cluster, the cluster's `member_case_count` is set to the size of the group, and its `earliest_onset_date` and `latest_onset_date` are the minimum and maximum onset dates over the members. If neither condition holds, there is no cluster change and the case's `cluster_id` stays unset. The `member_case_count` always equals the number of cases whose `cluster_id` references the cluster.

An `EpiAnalyst` may close an active cluster. Closing is legal only from `ACTIVE`, rejected otherwise with `ERR_CLUSTER_NOT_CLOSEABLE`, and advances the cluster `ACTIVE → CLOSED`. A case's cluster can be retrieved by a reverse lookup that returns the zero-or-one cluster the case belongs to; this lookup responds with an array-shaped envelope (`response_type` `"array"` with pagination `meta`) whose `data` array holds the single cluster when the case has one and is empty otherwise.

### 3.12. Cross-Jurisdiction Case Transfer

Routing a case to another jurisdiction is an `EpiAnalyst` workflow with its own request-and-resolve lifecycle. Requesting a transfer supplies the `program_id`, the `case_id` being transferred, the receiving `to_jurisdiction_id`, the `expected_case_version` for the concurrency check, and an optional free-text `reason`. The case must be in `UNDER_INVESTIGATION` or `CLASSIFIED` to be transferable, rejected otherwise with `ERR_CASE_NOT_TRANSFERABLE`. As described in Section 2.8, the `expected_case_version` must equal the case's current `version` before any state or business check, failing with `ERR_STALE_CASE_VERSION` (HTTP 412). The `to_jurisdiction_id` must differ from the case's current `jurisdiction_id`, or the request is rejected with `ERR_SAME_JURISDICTION_TRANSFER`. And no other transfer for this case may already be in `REQUESTED`, or the request is rejected with `ERR_TRANSFER_PENDING_EXISTS`.

A successful request creates a `JurisdictionTransfer` in `REQUESTED` whose `from_jurisdiction_id` is copied from the case's current `jurisdiction_id`, drives the case from its current state (`UNDER_INVESTIGATION` or `CLASSIFIED`) into `TRANSFER_PENDING` while remembering the prior state to restore on resolution, and increments the case's `version` by one. While the case sits in `TRANSFER_PENDING`, only the transfer resolution can move it.

The analyst resolves the transfer by supplying a `status` of `ACCEPTED` or `REJECTED`. Resolution is legal only while the transfer is in `REQUESTED`, rejected otherwise with `ERR_TRANSFER_NOT_RESOLVABLE`. Accepting advances the transfer `REQUESTED → ACCEPTED` and rehomes the case: the case's `jurisdiction_id` becomes the transfer's `to_jurisdiction_id`, and a depth-three cascade follows — every non-`VOIDED` contact whose `source_case_id` equals the case and whose `monitoring_jurisdiction_id` equals the old jurisdiction is reassigned to the new `to_jurisdiction_id`, and for any such contact in `MONITORING_ACTIVE` its contribution to the active-monitoring count moves from the old jurisdiction's `active_monitoring_count` to the new jurisdiction's. Rejecting advances the transfer `REQUESTED → REJECTED` and performs no rehome. In both cases the case's status is restored to whichever prior state was remembered when the transfer was requested — `UNDER_INVESTIGATION → TRANSFER_PENDING` is restored to `UNDER_INVESTIGATION`, and `CLASSIFIED → TRANSFER_PENDING` is restored to `CLASSIFIED`. Both `ACCEPTED` and `REJECTED` are terminal states for the transfer.

### 3.13. State and NEDSS Reporting

An `EpiAnalyst` generates a state/NEDSS export snapshot for a case. Generating a `NedssExport` supplies the `program_id` and the `case_id`. The case's `classification` must be `CONFIRMED` or `PROBABLE` to be reportable; any other classification is rejected with `ERR_EXPORT_CASE_NOT_REPORTABLE`. On creation the export begins in `GENERATED` and captures a point-in-time snapshot: its `snapshot_classification` records the case's classification at export time (either `CONFIRMED` or `PROBABLE`), its `snapshot_completeness_score` records the case's `completeness_score` at export time, and a server-minted `nedss_message_id` is assigned.

The analyst then transmits the export. Transmission is legal only from `GENERATED`, rejected otherwise with `ERR_EXPORT_NOT_TRANSMITTABLE`. Because an export is a frozen snapshot, the system guards against transmitting stale data: the referenced case's current `classification` must still equal the export's `snapshot_classification`, or transmission is rejected with `ERR_EXPORT_SNAPSHOT_STALE`. A successful transmit advances the export `GENERATED → TRANSMITTED` and finalizes the `nedss_message_id`. Alternatively, a generated export may be voided; voiding is legal only from `GENERATED`, rejected otherwise with `ERR_EXPORT_NOT_VOIDABLE`, and advances the export `GENERATED → VOIDED`. Both `TRANSMITTED` and `VOIDED` are terminal.

Across every workflow above, field-level input validation applies: enum-typed fields must carry a recognized member, numeric fields such as `proximity_meters` and `cumulative_exposure_minutes` and the condition's day-counts must be non-negative, a monitoring period's `end_date` must be at or after its `start_date`, a classify value must be in the allowed set, and a transfer's `to_jurisdiction_id` must differ from its origin. A malformed body, a missing required field, or any such out-of-domain input is rejected with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, clock control, and lab supersession — return a `200 OK` status code. List and retrieval operations also return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/surveillance/programs` | Create a surveillance program | JurisdictionAdmin |
| GET | `/surveillance/programs/{programId}` | Get a surveillance program | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/programs/{programId}/clock/set` | Set the deterministic surveillance clock | JurisdictionAdmin |
| POST | `/surveillance/jurisdictions` | Create a jurisdiction | JurisdictionAdmin |
| GET | `/surveillance/jurisdictions` | List jurisdictions (filterable by program_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/jurisdictions/{jurisdictionId}` | Get a jurisdiction | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/reportable-conditions` | Define a reportable condition | JurisdictionAdmin |
| GET | `/surveillance/reportable-conditions` | List reportable conditions (filterable by program_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/reportable-conditions/{conditionId}` | Get a reportable condition | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/lab-results` | Electronic lab report intake with auto-linkage | IntakeProcessor |
| GET | `/surveillance/lab-results` | List lab results (filterable by program_id, linked_case_id, jurisdiction_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/lab-results/{labResultId}` | Get a lab result | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/lab-results/{labResultId}/supersede` | Supersede a linked lab result | IntakeProcessor |
| POST | `/surveillance/cases` | Open a case | IntakeProcessor, CaseInvestigator |
| GET | `/surveillance/cases` | List cases (filterable by program_id, jurisdiction_id, condition_code, status, cluster_id, source_contact_id, source_lab_result_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/cases/{caseId}` | Get a case | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/cases/{caseId}/interview` | Record the case interview | CaseInvestigator |
| POST | `/surveillance/cases/{caseId}/classify` | Classify the case | CaseInvestigator |
| POST | `/surveillance/cases/{caseId}/close` | Close a classified case | CaseInvestigator |
| POST | `/surveillance/cases/{caseId}/reopen` | Reopen a closed case | CaseInvestigator |
| POST | `/surveillance/cases/{caseId}/link-lab-result` | Manually link a lab result to a case | CaseInvestigator |
| GET | `/surveillance/cases/{caseId}/cluster` | Reverse-lookup the cluster a case belongs to | JurisdictionAdmin, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/contacts` | Elicit a contact for an index case | ContactTracer |
| GET | `/surveillance/contacts` | List contacts (filterable by program_id, source_case_id, monitoring_jurisdiction_id, status, priority_band, promoted_case_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/contacts/{contactId}` | Get a contact | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/contacts/{contactId}/qualifying-test` | Record a qualifying test for a contact | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/queue-notification` | Queue a contact for notification | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/record-notification` | Record a notification outcome | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/monitoring-periods` | Schedule a monitoring period for a contact | ContactTracer |
| GET | `/surveillance/monitoring-periods` | List monitoring periods (filterable by program_id, contact_id, jurisdiction_id, status) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/monitoring-periods/{monitoringPeriodId}` | Get a monitoring period | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/contacts/{contactId}/start-monitoring` | Activate monitoring | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/complete-monitoring` | Complete monitoring | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/promote` | Promote a symptomatic contact into a new case | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/void` | Void a contact | ContactTracer |
| POST | `/surveillance/contacts/{contactId}/exposure-events` | Append an exposure encounter | ContactTracer |
| GET | `/surveillance/exposure-events` | List exposure events (filterable by program_id, contact_id, case_id) | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/exposure-events/{exposureEventId}` | Get an exposure event | JurisdictionAdmin, IntakeProcessor, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/jurisdiction-transfers` | Request transfer of a case to another jurisdiction | EpiAnalyst |
| GET | `/surveillance/jurisdiction-transfers` | List jurisdiction transfers (filterable by program_id, case_id, to_jurisdiction_id, from_jurisdiction_id, status) | JurisdictionAdmin, EpiAnalyst, CaseInvestigator |
| GET | `/surveillance/jurisdiction-transfers/{transferId}` | Get a jurisdiction transfer | JurisdictionAdmin, EpiAnalyst, CaseInvestigator |
| PUT | `/surveillance/jurisdiction-transfers/{transferId}` | Resolve a transfer (accept or reject) | EpiAnalyst |
| GET | `/surveillance/outbreak-clusters` | List outbreak clusters (filterable by program_id, condition_code, exposure_setting_location_id, status, anchor_case_id) | JurisdictionAdmin, CaseInvestigator, ContactTracer, EpiAnalyst |
| GET | `/surveillance/outbreak-clusters/{clusterId}` | Get an outbreak cluster | JurisdictionAdmin, CaseInvestigator, ContactTracer, EpiAnalyst |
| POST | `/surveillance/outbreak-clusters/{clusterId}/close` | Close an active outbreak cluster | EpiAnalyst |
| POST | `/surveillance/nedss-exports` | Generate a NEDSS export snapshot | EpiAnalyst |
| GET | `/surveillance/nedss-exports` | List NEDSS exports (filterable by program_id, case_id, status) | JurisdictionAdmin, EpiAnalyst |
| GET | `/surveillance/nedss-exports/{exportId}` | Get a NEDSS export | JurisdictionAdmin, EpiAnalyst |
| POST | `/surveillance/nedss-exports/{exportId}/transmit` | Transmit a generated NEDSS export | EpiAnalyst |
| POST | `/surveillance/nedss-exports/{exportId}/void` | Void a generated NEDSS export | EpiAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_JURISDICTION_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_CONDITION_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTACT_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_RESULT_NOT_FOUND` | 404 Not Found |
| `ERR_MONITORING_PERIOD_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_CLUSTER_NOT_FOUND` | 404 Not Found |
| `ERR_EXPORT_NOT_FOUND` | 404 Not Found |
| `ERR_EXPOSURE_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ONSET_OR_SPECIMEN_REQUIRED` | 400 Bad Request |
| `ERR_INVALID_CLASSIFICATION` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_CASE_NOT_INTERVIEWABLE` | 409 Conflict |
| `ERR_CASE_NOT_CLASSIFIABLE` | 409 Conflict |
| `ERR_INTERVIEW_NOT_COMPLETE` | 409 Conflict |
| `ERR_CASE_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_CASE_NOT_REOPENABLE` | 409 Conflict |
| `ERR_CASE_NOT_TRANSFERABLE` | 409 Conflict |
| `ERR_CASE_NOT_LINKABLE` | 409 Conflict |
| `ERR_ACTIVE_MONITORING_EXISTS` | 409 Conflict |
| `ERR_TRANSFER_PENDING_EXISTS` | 409 Conflict |
| `ERR_SAME_JURISDICTION_TRANSFER` | 409 Conflict |
| `ERR_LAB_CONFIRMATION_REQUIRED` | 409 Conflict |
| `ERR_LAB_NOT_LINKABLE` | 409 Conflict |
| `ERR_LAB_CONDITION_MISMATCH` | 409 Conflict |
| `ERR_LAB_PATIENT_MISMATCH` | 409 Conflict |
| `ERR_LAB_NOT_SUPERSEDABLE` | 409 Conflict |
| `ERR_CONTACT_NOT_QUEUEABLE` | 409 Conflict |
| `ERR_CONTACT_NOT_PENDING_NOTIFICATION` | 409 Conflict |
| `ERR_CONTACT_NOT_NOTIFIED` | 409 Conflict |
| `ERR_CONTACT_NOT_MONITORING` | 409 Conflict |
| `ERR_CONTACT_NOT_PROMOTABLE` | 409 Conflict |
| `ERR_CONTACT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_QUARANTINE_WINDOW_MISSING` | 409 Conflict |
| `ERR_NO_SCHEDULED_MONITORING` | 409 Conflict |
| `ERR_MONITORING_NOT_ELAPSED` | 409 Conflict |
| `ERR_MONITORING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ENCOUNTER_OUTSIDE_INFECTIOUS_WINDOW` | 409 Conflict |
| `ERR_TRANSFER_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_CLUSTER_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_EXPORT_CASE_NOT_REPORTABLE` | 409 Conflict |
| `ERR_EXPORT_NOT_TRANSMITTABLE` | 409 Conflict |
| `ERR_EXPORT_SNAPSHOT_STALE` | 409 Conflict |
| `ERR_EXPORT_NOT_VOIDABLE` | 409 Conflict |
