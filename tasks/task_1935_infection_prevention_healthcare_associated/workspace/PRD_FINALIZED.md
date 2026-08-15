# Infection Prevention & Healthcare-Associated Infection Surveillance API — Product Requirements Document

## 1. Introduction

Hospitals participating in the National Healthcare Safety Network carry a dual obligation: they must detect healthcare-associated infections early enough to intervene, and they must submit monthly surveillance data whose integrity survives external audit. Both obligations rest on the same raw material — device-day denominators collected nightly on each unit, operative procedures logged by the OR, positive specimens called in by the laboratory, and a stream of hand-hygiene and isolation-precaution observations gathered by unit leadership. When that raw material lives in disconnected spreadsheets, infection preventionists spend their days reconciling rows instead of investigating clusters, and a single late correction to a denominator row can silently invalidate a submission that has already been accepted.

This document specifies an API that gives the infection prevention program one coherent system of record. The service governs the full surveillance cycle: registration of facilities and units with their NHSN baseline rates, admission and movement of patients, recording of device episodes and operative procedures, opening and adjudication of suspected infection cases under the CLABSI, CAUTI, and SSI definitions, monthly compilation of denominator and numerator data into a submittable summary, automated outbreak-cluster detection with a director-led investigation workflow, isolation precaution ordering with compliance audit, a hand-hygiene observation program, occupational exposure follow-up for employees, and corrective action plans that close the loop back to the unit.

Two design commitments run through the specification. First, segregation of duties is structural: the infection preventionist who prepares and submits a monthly summary may not accept it, and the originator of a corrective action plan may not verify it — both checks are enforced server-side against the acting user's identity. Second, time is a first-class input. Because surveillance rules depend on calendar dates, rolling windows, and overdue thresholds, the server maintains a logical clock that tests and operators can set explicitly; every rule that asks "is this draw overdue?" or "does this specimen date fall inside the window?" reads that clock rather than wall time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled as follows:

- `PlatformAdmin` — facility and unit configuration, and operation of the logical clock.
- `InfectionPreventionist` — surveillance case work-up and adjudication, monthly summary preparation and submission, isolation ordering, outbreak opening, and corrective-action drafting.
- `InfectionControlDirector` — monthly summary review (accept or reject), outbreak confirmation and closure, and corrective-action verification. This role is deliberately disjoint from `InfectionPreventionist` so that segregation-of-duties checks have teeth.
- `UnitNurseManager` — census operations (admission, transfer, discharge), device episodes, surgical procedures, daily denominator collection and correction, isolation start and discontinue, isolation compliance audits, and hand-hygiene observations.
- `EmployeeHealthNurse` — the employee registry and the occupational-exposure follow-up protocol.

For all five roles — `PlatformAdmin`, `InfectionPreventionist`, `InfectionControlDirector`, `UnitNurseManager`, and `EmployeeHealthNurse` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution (for example, as `submitted_by_user_id` and `accepted_by_user_id` on a monthly summary, `adjudicated_by_user_id` on an infection case, `ordered_by_user_id` on an isolation order, `auditor_user_id` on a compliance audit, `observer_user_id` on a hand-hygiene observation, `created_by_user_id` and `verified_by_user_id` on a corrective action plan), and it compares those recorded identifiers against the incoming `X-User-ID` where a segregation-of-duties rule applies — but it never matches `X-User-ID` against the `id` of any `Employee`, `Patient`, or other entity row.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer that starts at 1 and increments by one on every mutation of the resource, including mutations driven by cascades and recomputes rather than by a direct client write.

A recomputation that refreshes derived fields on a resource — for instance, a monthly summary whose SIR fields are recalculated after a new case is adjudicated — is a mutation of that resource and therefore updates its `updated_at` and increments its `version`, even though no client wrote to the summary directly.

### 2.5. Validation Priority Ordering

When a single request violates more than one rule, the error it receives is determined by a fixed priority order, evaluated top-down; the request reports the violation with the lowest priority number.

1. **Presence of identity headers.** Missing or empty `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before anything else is examined.
2. **Role authorization.** A role not on the endpoint's authorized list yields `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Request schema.** Missing required fields, invalid enum values, integer range violations (such as a value that must be at least 0 or at least 1), string minimum-length violations, and violated conditional-required pairings all yield `ERR_INVALID_REQUEST` (HTTP 400). The conditional pairings are: `surgical_procedure_id` is required if and only if the case's `case_type` is `SSI`; `linked_device_episode_id` is required if and only if `case_type` is `CLABSI` or `CAUTI`; `date_of_event` is required if and only if the adjudication `outcome` is `ADJUDICATED_HAI`; and `ssi_depth` is required if and only if an SSI case is being adjudicated to `ADJUDICATED_HAI`.
4. **Existence of referenced resources.** Path identifiers are validated left to right, and then foreign-key identifiers in the request body are validated in payload declaration order. The first missing reference produces the resource-specific not-found error (`ERR_FACILITY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_DEVICE_EPISODE_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`, `ERR_INFECTION_CASE_NOT_FOUND`, `ERR_DEVICE_DAY_COUNT_NOT_FOUND`, `ERR_MONTHLY_SUMMARY_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`, `ERR_ISOLATION_ORDER_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`, or `ERR_CAP_NOT_FOUND`, each HTTP 404).
5. **State preconditions.** The target resource must be in a state that permits the action — a case must be reviewable, adjudicatable, or reopenable; a summary submittable, reviewable, or amendable; an investigation confirmable or closable; an isolation order startable, not already discontinued, or active for audit; an exposure at the correct stage; a corrective action plan activatable, submittable, or verifiable; a patient `ADMITTED`; a device episode `ACTIVE`. Each action names its own domain-specific error (all HTTP 409), but they share this priority tier.
5.5. **Covering-summary lock.** Mutations that would alter the inputs of a monthly summary — creating or correcting a device-day row, recording a surgical procedure, adjudicating or reopening an infection case — are rejected with `ERR_SUMMARY_LOCKED` (HTTP 409) when the covering summary exists and is not in a mutable status.
6. **Outbreak posture gate.** Submission of a monthly summary while its unit's `surveillance_posture` is `OUTBREAK` is rejected with `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` (HTTP 403).
6.5. **Segregation of duties.** Acceptance of a summary by the user who submitted it, or verification of a corrective action plan by the user who created it, is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403).
7. **Temporal window rules.** Evaluated in a pinned sub-order: first the repeat-infection-timeframe block on case creation (`ERR_REPEAT_INFECTION_TIMEFRAME`), then the date-of-event placement inside the infection window period (`ERR_DOE_OUTSIDE_IWP`), then the healthcare-associated day rule (`ERR_DOE_NOT_HAI_DAY_RULE`), then the SSI surveillance window (`ERR_SSI_WINDOW_EXPIRED`), then the device-day rule (`ERR_DEVICE_DAY_RULE_NOT_MET`), then the exposure draw windows (`ERR_BASELINE_WINDOW_MISSED`, `ERR_DRAW_OUTSIDE_WINDOW`), and finally the lost-to-followup overdue threshold (`ERR_EXPOSURE_NOT_OVERDUE`). All are HTTP 422.
7.5. **Interval overlap.** Device-episode overlap for the same patient and device type yields `ERR_DEVICE_EPISODE_OVERLAP`; surgical-procedure overlap for the same patient yields `ERR_PROCEDURE_OVERLAP` (both HTTP 409).
8. **Cross-entity referential coherence.** A linked device episode belonging to a different patient yields `ERR_EPISODE_PATIENT_MISMATCH`; a linked surgical procedure belonging to a different patient yields `ERR_PROCEDURE_PATIENT_MISMATCH`; an invalid corrective-action source reference yields `ERR_CAP_SOURCE_INVALID` (all HTTP 422).
9. **Uniqueness and intra-row constraints.** Duplicate keys and within-row constraint violations — `ERR_DUPLICATE_DEVICE_DAY_COUNT`, `ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS`, `ERR_DUPLICATE_SUMMARY_MONTH`, `ERR_DUPLICATE_ISOLATION_ORDER`, `ERR_DUPLICATE_OUTBREAK_OPEN`, `ERR_AUDIT_ELEMENTS_INVALID`, `ERR_DUPLICATE_NHSN_ORG_ID`, and `ERR_DUPLICATE_MRN` (HTTP 409 for the duplicates, HTTP 422 for `ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS` and `ERR_AUDIT_ELEMENTS_INVALID`).

### 2.6. The Logical Clock and Calendar Semantics

The server maintains a logical clock that governs every time-dependent rule in the system: rolling detection windows, draw due dates, overdue flags, and lost-to-followup eligibility all read this clock. At startup, before any operator action, the logical clock reads exactly `2026-08-01T00:00:00Z`. It never falls back to wall-clock time on its own; a `PlatformAdmin` advances it through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value, and the capability responds with the resulting `current_utc` reading. The move is not required to be monotonic — operators may move the clock freely in either direction.

Calendar-day reasoning is always performed in UTC. When a rule speaks of a "calendar date," it means the UTC calendar date of the timestamp in question; day boundaries fall at `00:00:00Z`.

### 2.7. Precision and Rounding

Two rounding disciplines coexist in the system, and each calculated field declares which one it uses. Rates and predicted-event figures used in surveillance ratios are rounded to exactly 3 decimal places using round-half-up. Compliance percentages — the isolation audit's `compliance_pct` and the hand-hygiene rates — are rounded to exactly 1 decimal place using round-half-up. In both cases the rounding is applied once, at the point the value is stored or returned; chained re-rounding of already-rounded values is not performed except where a formula explicitly consumes a stored, already-rounded input (the SIR does exactly that, dividing by the stored rounded predicted value). All numeric values are returned in response bodies as JSON numbers, not strings.

### 2.8. Optimistic Concurrency Control

Two write endpoints guard against stale overwrites with an optimistic concurrency check, and only those two endpoints take a version field.

Correcting a device-day denominator row requires the request to carry `expected_device_day_count_version`, holding the `version` of the `DeviceDayCount` row as the client last observed it. Because a denominator row remains in `DRAFT` across corrections and every correction is a legitimate write, nothing in the state machine would stop a second correction issued with a previously valid version from silently overwriting a row it has never seen; the OCC check is the only guard. If the supplied value does not match the row's current `version`, the correction is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating a facility's configuration requires the request to carry `expected_facility_version`, holding the `version` of the `Facility` as the client last observed it. Baseline updates are always semantically valid writes and each one triggers recomputation of every mutable monthly summary across the facility's units, so a stale write would silently discard an intervening update without this check. A mismatch against the facility's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named above do not accept a version field and perform no OCC check.

### 2.9. Surveillance Posture: The Unit-Level Aggregate

Each unit carries a computed `surveillance_posture` of `NORMAL`, `ELEVATED`, or `OUTBREAK`. Posture is not set directly by any client; it is a pure function of the unit's open investigations and open corrective action plans, recomputed on every mutation of either. A unit is in `OUTBREAK` posture whenever at least one of its `OutbreakInvestigation` rows has status `CONFIRMED`. Otherwise it is `ELEVATED` whenever at least one investigation is `TRIGGERED`, or at least one corrective action plan is in `ACTIVE`, `VERIFICATION_PENDING`, or `ESCALATED`. Otherwise it is `NORMAL`. Every recomputation that changes the posture is a mutation of the unit and increments its `version`.

The posture machine permits a direct jump from `NORMAL` to `OUTBREAK` when an investigation is confirmed while no intermediate driver was active, and a fall from `OUTBREAK` back to `ELEVATED` when the last confirmed investigation closes while other drivers remain. Posture has one hard downstream effect: a monthly summary for a unit in `OUTBREAK` posture cannot be submitted — the posture gate in §2.5 — because submission during a confirmed outbreak would freeze denominators exactly when they are most likely to be corrected.

### 2.10. The Covering Summary Lock

A monthly summary, once it leaves the mutable tier, freezes its inputs. A summary's status is mutable when it is `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`; it is locked when `SUBMITTED` or `ACCEPTED`. While the covering summary for a unit and month — the summary whose `month` matches the calendar month of the row in question — is locked, five operations are rejected with `ERR_SUMMARY_LOCKED`: creating a device-day count for that unit-month, correcting one, recording a surgical procedure whose `performed_at` falls in that unit-month, adjudicating an infection case whose attributed unit and date-of-event month are covered by the locked summary, and reopening a case covered by it. Rejection and amendment of a summary compensate by reverting that unit-month's denominator rows from `LOCKED` back to `DRAFT`, restoring writability.

### 2.11. Cascades and Hierarchical Consistency

Several operations mutate more than one resource in a single transaction, and the PRD names each cascade at the point of the workflow that triggers it. The general principles are uniform: every cascade target is mutated independently, refreshing its `updated_at` and incrementing its `version`; cascades run immediately within the same request, with no deferred queue; and a cascade never skips a target because the target "looks unchanged" — recomputation rewrites the derived fields even when the new values equal the old. The three structural cascades are: summary submission locking its denominator rows (and rejection or amendment unlocking them); adjudication of a case recomputing its covering summary and then running cluster detection, which may create an investigation, which in turn recomputes unit posture; and a non-compliant isolation audit creating an `ACTIVE` corrective action plan, which recomputes unit posture.

## 3. Business Logic & Workflows

### 3.1. Facility Configuration and Unit Registration

A `PlatformAdmin` onboards a hospital by creating a facility. The creation payload carries the facility's display `name`, its `nhsn_org_id` (the NHSN organization identifier, unique across all facilities — a duplicate is rejected with `ERR_DUPLICATE_NHSN_ORG_ID`), and three predicted-event baselines: `clabsi_baseline_per_1000` (predicted CLABSI events per thousand central-line days), `cauti_baseline_per_1000` (predicted CAUTI events per thousand urinary-catheter days), and `ssi_baseline_per_procedure` (predicted SSI events per risk-weighted procedure). Two optional thresholds govern reporting: `sir_high_threshold`, which defaults to 1.25 and sets the SIR value at or above which a monthly summary's `sir_flag` reads `HIGH`; and `hh_min_opportunities`, which defaults to 30 and sets the minimum number of hand-hygiene opportunities a unit must record in a month for its compliance rate to be reportable.

Updating a facility's baselines is the OCC-guarded write described in §2.8, taking `expected_facility_version` alongside any of `name`, the three baseline fields, `sir_high_threshold`, or `hh_min_opportunities`. The update increments the facility's `version` by one and immediately recomputes the predicted and SIR fields of every monthly summary in a mutable status — `OPEN`, `REJECTED`, or `UNDER_AMENDMENT` — across all of the facility's units, each such recompute incrementing that summary's own `version`.

Units are created within a facility by a `PlatformAdmin` supplying `facility_id`, a display `name`, a `unit_type` of `ICU`, `WARD`, `STEP_DOWN`, or `OR`, and an `nhsn_location_code` that is unique within the facility. A new unit begins with `surveillance_posture` set to `NORMAL`. Units may be listed with an optional `facility_id` filter.

### 3.2. Patient Census: Admission, Transfer, and Discharge

A `UnitNurseManager` registers an inpatient admission by supplying the patient's `mrn` — a medical record number unique across the hospital, with duplicates rejected as `ERR_DUPLICATE_MRN` — the `admitted_at` timestamp, and the `unit_id` of the initial inpatient unit. The admission calendar date counts as day 1 for the healthcare-associated day rule described later. The new patient starts in `ADMITTED` status with `current_unit_id` equal to the admitting unit, and the system seeds the patient's `unit_stays` array with a single entry recording that unit, an arrival at `admitted_at`, and no departure.

Each entry in `unit_stays` is a half-open interval — the patient occupies the unit from `arrived_at` up to but not including `departed_at` — and `departed_at` remains null while the stay is active. Transferring a patient requires the patient to be `ADMITTED` (otherwise `ERR_PATIENT_NOT_ADMITTED`) and takes `to_unit_id` and `transferred_at`; the destination must differ from the patient's current unit (`ERR_INVALID_REQUEST` otherwise). The transfer closes the current stay by setting its `departed_at` to `transferred_at`, appends a new stay for the destination unit arriving at `transferred_at` with null departure, and moves `current_unit_id` to `to_unit_id`, incrementing the patient's `version`. Discharge takes `discharged_at`, requires `ADMITTED` status under the same `ERR_PATIENT_NOT_ADMITTED` guard, closes the open stay at that timestamp, sets the patient's `discharged_at`, moves `current_unit_id` to null, and transitions the patient to `DISCHARGED`. The patient list may be filtered by `current_unit_id`, `unit_id`, or `status`.

The stay history is not merely informational: the date-of-event unit attribution rule in §3.5 reads it to decide which unit an infection belongs to.

### 3.3. Device Episodes and Surgical Procedures

When a central line, urinary catheter, or ventilator is placed, a `UnitNurseManager` records a device episode with the `patient_id`, a `device_type` of `CENTRAL_LINE`, `URINARY_CATHETER`, or `VENTILATOR`, and the `placed_at` timestamp. The episode's `unit_id` is computed at creation from the patient's `current_unit_id` — this is the device-attribution unit, and it does not follow later transfers. The episode begins `ACTIVE` with `removed_at` null. Removal, performed by a `UnitNurseManager` supplying `removed_at`, requires the episode to be `ACTIVE` (`ERR_DEVICE_EPISODE_NOT_ACTIVE` otherwise) and requires `removed_at` to be no earlier than `placed_at` (`ERR_INVALID_REQUEST`); it transitions the episode to `REMOVED`. Episodes may be listed with `patient_id`, `unit_id`, or `device_type` filters.

Two episodes for the same patient and the same `device_type` may not overlap: their half-open intervals `[placed_at, removed_at)` must be disjoint, and a collision is rejected with `ERR_DEVICE_EPISODE_OVERLAP`. Because the interval is half-open, a back-to-back placement — one episode's `placed_at` exactly equal to another's `removed_at` — is permitted.

Operative procedures are recorded by a `UnitNurseManager` with the `patient_id`, a free-text `procedure_code` carrying the NHSN operative procedure code, the `performed_at` start timestamp, `duration_minutes` (whole minutes, at least 1), an `asa_score` from 1 to 5, a `wound_class` of `CLEAN`, `CLEAN_CONTAMINATED`, `CONTAMINATED`, or `DIRTY`, and an optional `implant` flag defaulting to false that extends SSI surveillance of this procedure to ninety days. The procedure's `unit_id` is the patient's `current_unit_id` at creation — the operating unit. A procedure occupies the closed interval from `performed_at` through `performed_at` plus `duration_minutes`, inclusive of both endpoints; two procedures for the same patient whose closed intervals share even a single instant are rejected with `ERR_PROCEDURE_OVERLAP`. Recording a procedure is blocked with `ERR_SUMMARY_LOCKED` when the covering monthly summary (the procedure's unit, the month of `performed_at`) exists and is not mutable, and a successful recording recomputes the covering summary's `procedure_count`, `predicted_ssi`, and `sir_ssi` when that summary is mutable. Procedures may be listed with `patient_id` or `unit_id` filters.

### 3.4. Opening a Suspected Infection Case

An `InfectionPreventionist` opens a surveillance case by supplying the `patient_id`, a `case_type` of `CLABSI`, `CAUTI`, `SSI`, or `OTHER_BSI`, the `suspected_organism` name, and the `first_positive_specimen_at` collection timestamp. Two conditional references ride along: `surgical_procedure_id` is required exactly when `case_type` is `SSI` and must be absent or null otherwise, and `linked_device_episode_id` is required exactly when `case_type` is `CLABSI` or `CAUTI` and must be absent or null otherwise; violating either pairing yields `ERR_INVALID_REQUEST`. When present, each reference must also point at a row belonging to the same patient — a device episode of a different patient yields `ERR_EPISODE_PATIENT_MISMATCH`, and a procedure of a different patient yields `ERR_PROCEDURE_PATIENT_MISMATCH`.

Creation fixes three things immediately. The case's `unit_id` is taken from the patient's `current_unit_id` (it may later be re-attributed at adjudication). The case's `status` starts at `SUSPECTED`. And the system computes the **infection window period**: `infection_window_start` is the calendar date of `first_positive_specimen_at` minus three calendar days, at `00:00:00Z`, and `infection_window_end` is the calendar date of `first_positive_specimen_at` plus three calendar days, at `23:59:59Z` — a closed seven-calendar-day window, inclusive at both ends.

Creation is also where the **repeat infection timeframe** block applies. If the same patient already has an `ADJUDICATED_HAI` case of the same `case_type` whose `date_of_event` calendar date, extended thirteen calendar days forward, contains the new case's specimen calendar date — that is, the new specimen date falls anywhere from the earlier case's date of event through thirteen days after it, inclusive — creation is rejected with `ERR_REPEAT_INFECTION_TIMEFRAME`. Only `ADJUDICATED_HAI` cases block; cases sitting in `SUSPECTED`, `UNDER_REVIEW`, `RULED_OUT`, or `REOPENED` do not.

### 3.5. Review, Adjudication, and the Attribution Cascade

Beginning review moves a case from `SUSPECTED` — or from `REOPENED`, since the machine is cyclic — into `UNDER_REVIEW`. Any other starting state is rejected with `ERR_CASE_NOT_REVIEWABLE`.

Adjudication is the pivot of the whole surveillance loop. An `InfectionPreventionist` adjudicates an `UNDER_REVIEW` case — anything else yields `ERR_CASE_NOT_ADJUDICATABLE` — with an `outcome`, a free-text `rationale` of at least ten characters (stored on the case as `adjudication_rationale`), and, when the outcome is `ADJUDICATED_HAI`, a `date_of_event` plus (for SSI cases) an `ssi_depth` of `SURFACE`, `DEEP`, or `ORGAN_SPACE`. Ruling the case out requires only the `outcome` and `rationale`: it records `adjudicated_by_user_id` and `adjudication_rationale`, sets `is_hai` to false, leaves `date_of_event` and `rit_blocked_until` null, and lands the case in `RULED_OUT`.

Adjudicating to `ADJUDICATED_HAI` runs a fixed evaluation sequence, and each step consumes only the results of earlier steps:

1. The infection window period is already computed from `first_positive_specimen_at`.
2. The supplied `date_of_event` must fall inside that window, inclusive — otherwise `ERR_DOE_OUTSIDE_IWP`.
3. The healthcare-associated day rule: the calendar date of `date_of_event` must be at least two calendar days after the calendar date of the patient's `admitted_at`, remembering that the admission date itself is day 1 — otherwise `ERR_DOE_NOT_HAI_DAY_RULE`.
4. For an SSI case, the surveillance window: the calendar date of `date_of_event` must be no later than the calendar date of the linked procedure's `performed_at` plus twenty-nine days when the procedure had no implant (a thirty-day window counting the procedure date as the first day), or plus eighty-nine days when `implant` is true (a ninety-day window) — otherwise `ERR_SSI_WINDOW_EXPIRED`.
5. For a CLABSI or CAUTI case, the device-day rule: the linked episode must have been placed at least two calendar days before the date of event, and the episode must cover the date of event — `placed_at` no later than `date_of_event`, and either `removed_at` still null or `removed_at` no earlier than `date_of_event` — otherwise `ERR_DEVICE_DAY_RULE_NOT_MET`.
6. The covering monthly summary — the summary for the case's attributed unit and the calendar month of `date_of_event` — must, if it exists, be in `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`; otherwise the adjudication is rejected with `ERR_SUMMARY_LOCKED`.

With the date of event validated, `is_hai` is set true, and the system sets `rit_blocked_until` to the date-of-event calendar date plus thirteen calendar days at `23:59:59Z` — a fourteen-day inclusive window that powers the repeat-infection block above.

Attribution then decides which unit owns the case, under the **transfer-out rule**. The system finds the patient's stay covering the date of event — the stay whose `arrived_at` is no later than the date of event and whose `departed_at` is either null or strictly after it. When the date of event's calendar date equals that covering stay's arrival calendar date, and an earlier stay exists whose departure calendar date equals the date of event's calendar date, the case is attributed to that earlier stay's unit — the unit the patient transferred out of on the day the infection declared. In every other case the case is attributed to the covering stay's unit. The case's `unit_id` is rewritten to the attributed unit.

The cascade then fires in order. The covering monthly summary, if it exists and is mutable, has its observed and provisional counts, predicted figures, SIR fields, and `sir_flag` recomputed, incrementing the summary's `version`. Cluster detection then runs for the attributed unit and the case's `suspected_organism`, as described in §3.7; if the threshold is crossed, the system creates an `OutbreakInvestigation` in `TRIGGERED` status with `origin` `AUTO_THRESHOLD`. That investigation creation recomputes the unit's `surveillance_posture` — a freshly `TRIGGERED` investigation drives `ELEVATED` — and increments the unit's `version`.

Reopening is available from either soft-terminal state. A reopen, carrying a `reason` of at least ten characters, requires the case to be `ADJUDICATED_HAI` or `RULED_OUT` (`ERR_CASE_NOT_REOPENABLE` otherwise) and is blocked by a locked covering summary — located by the month of `date_of_event` for an adjudicated case, or by the month of `first_positive_specimen_at` for a ruled-out one — with `ERR_SUMMARY_LOCKED`. Reopening clears `date_of_event`, `is_hai`, and `rit_blocked_until` to null, lands the case in `REOPENED`, and recomputes the covering summary's counts, SIRs, and `sir_flag` when mutable. Reopening does not remove any investigation the case once triggered; unit posture is unchanged by a reopen.

### 3.6. Device-Day Denominators and Reconciliation

Each unit reports its denominator data daily. A `UnitNurseManager` records a `DeviceDayCount` row with the `unit_id`, the `count_date` (a UTC calendar date, midnight-normalized), and four non-negative integers: `central_line_days`, `urinary_catheter_days`, `ventilator_days`, and `patient_days`. Each of the three device-day figures must be no greater than `patient_days`; a violation is rejected with `ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS`. Only one row may exist per unit and calendar date — a duplicate yields `ERR_DUPLICATE_DEVICE_DAY_COUNT`. A new row starts in `DRAFT`, and creating it recomputes the covering monthly summary when that summary exists and is mutable; creating it is rejected with `ERR_SUMMARY_LOCKED` when the covering summary is locked. Rows may be listed with `unit_id` or `month` filters.

Corrections use the OCC-guarded write from §2.8: the request supplies all four count fields plus `expected_device_day_count_version`, the row must currently be `DRAFT` (a `LOCKED` row is frozen by its covering summary and surfaces through the summary-lock rule), and a stale version is rejected with `ERR_STALE_VERSION`. A successful correction increments the row's `version` by one and recomputes the covering summary when mutable.

A read-only reconciliation capability lets any role compare recorded denominators against an episode-derived expectation for a given `unit_id`, `device_type`, and `count_date`. The expected device days are the count of device episodes for that unit and device type that touched any instant of the calendar day — episodes placed before the next day's midnight and either never removed or removed no earlier than that day's midnight. Attribution follows the `unit_id` recorded on the episode at creation; transfers do not split a day between units. The response carries `expected_device_days`, the `recorded_device_days` from the matching row (null when no row exists), their `delta` computed as `recorded_device_days` minus `expected_device_days` (null when no row exists), and a `matches` boolean.

### 3.7. Monthly Summaries and the NHSN Submission Cycle

An `InfectionPreventionist` creates the monthly summary for a unit with just `unit_id` and a `month` in `YYYY-MM` form. One summary may exist per unit and month; a duplicate is `ERR_DUPLICATE_SUMMARY_MONTH`. Creation computes the full panel immediately and lands the summary in `OPEN`. Summaries may be listed with `unit_id` or `status` filters.

The denominator fields are straight aggregations over the unit's `DRAFT` or `LOCKED` denominator rows whose `count_date` falls in the month: `central_line_days`, `urinary_catheter_days`, `ventilator_days`, and `patient_days_total` are the respective sums. `procedure_count` is the number of surgical procedures attributed to the unit whose `performed_at` falls in the month.

The observed counts come in two variants. The **final** variant counts cases attributed to the unit whose status is `ADJUDICATED_HAI` and whose `date_of_event` calendar date falls in the month — producing `clabsi_count`, `cauti_count`, and `ssi_count` by case type. The **provisional** variant previews month-to-date exposure before adjudication completes: `provisional_clabsi_count`, `provisional_cauti_count`, and `provisional_ssi_count` each equal the corresponding final count plus cases of that type still in `UNDER_REVIEW` whose `first_positive_specimen_at` calendar date falls in the month. Provisional figures are therefore never smaller than their final counterparts for identical underlying data.

Predicted events use the facility baselines. `predicted_clabsi` is the facility's `clabsi_baseline_per_1000` multiplied by the month's `central_line_days` and divided by one thousand, rounded to three decimal places half-up; `predicted_cauti` follows the same shape with `cauti_baseline_per_1000` over `urinary_catheter_days`. `predicted_ssi` is the facility's `ssi_baseline_per_procedure` multiplied by the sum of risk weights over the month's procedures, rounded to three decimals half-up. A procedure's risk weight is 2.0 (high) when its `asa_score` is at least 4 or its `wound_class` is `CONTAMINATED` or `DIRTY`; 1.0 (low) when its `asa_score` is at most 2 and its `wound_class` is `CLEAN`; and 1.5 (medium) in every other case.

Each standardized infection ratio divides the observed count by the stored, already-rounded predicted value and rounds the quotient to three decimal places half-up. Under the NHSN not-calculated rule, when the predicted value is below 1.0 the corresponding SIR is null rather than a number — the boundary is exactly 1.0, so a predicted value of exactly 1.0 does produce a ratio. This yields `sir_clabsi`, `sir_cauti`, and `sir_ssi` on the final variant, and `provisional_sir_clabsi`, `provisional_sir_cauti`, and `provisional_sir_ssi` dividing each provisional count by the same stored predicted value under the same not-calculated rule. The `sir_flag` reads `HIGH` when any non-null SIR — across the three final ratios — is at least the facility's `sir_high_threshold`; `NORMAL` when at least one SIR is calculable and every calculable one sits below the threshold; and `NOT_CALCULATED` when no SIR is calculable at all.

The summary then moves through its review cycle. Submission — from `OPEN`, `REJECTED`, or `UNDER_AMENDMENT`, anything else rejected with `ERR_SUMMARY_NOT_SUBMITTABLE` — records `submitted_by_user_id` from the acting user's header, cascades every denominator row for the unit and month into `LOCKED`, and is refused outright with `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` when the unit's `surveillance_posture` is `OUTBREAK`. The submitted summary lands in `SUBMITTED`.

An `InfectionControlDirector` then reviews. Acceptance requires `SUBMITTED` status (`ERR_SUMMARY_NOT_REVIEWABLE`) and enforces segregation of duties: the accepting user's `X-User-ID` must differ from `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTY`. Acceptance records `accepted_by_user_id` and lands the summary in `ACCEPTED`. Rejection, also from `SUBMITTED` under the same `ERR_SUMMARY_NOT_REVIEWABLE` guard, takes a `reason`, lands the summary in `REJECTED`, and compensates by reverting that unit-month's denominator rows from `LOCKED` back to `DRAFT`.

An accepted summary is soft-terminal. Amendment — allowed only from `ACCEPTED`, otherwise `ERR_SUMMARY_NOT_AMENDABLE` — takes a `reason`, increments `amendment_count` by one, clears both `submitted_by_user_id` and `accepted_by_user_id` to null, reverts the denominator rows to `DRAFT`, and lands the summary in `UNDER_AMENDMENT`, from which the submit-review cycle can run again.

### 3.8. Outbreak Detection and Cluster Investigation

Cluster detection runs automatically after every adjudication to `ADJUDICATED_HAI`, once attribution has settled. The rolling detection window spans fourteen calendar days inclusive: from the logical clock's current calendar date minus thirteen days at `00:00:00Z` through the current calendar date at `23:59:59Z`. The cluster is the set of cases attributed to the same unit, with a `suspected_organism` equal under case-insensitive exact string matching, in `ADJUDICATED_HAI` status, whose `date_of_event` calendar date falls inside that window. When the cluster holds at least three cases — exactly three triggers; two does not — and no investigation already exists for that unit and organism (compared case-insensitively) in `TRIGGERED` or `CONFIRMED` status, the system creates an `OutbreakInvestigation` with status `TRIGGERED`, `origin` `AUTO_THRESHOLD`, the window bounds stored as `detection_window_start` and `detection_window_end`, the contributing case ids captured in `trigger_case_ids` ordered by `date_of_event` ascending and then `created_at` ascending, and `contributing_case_count` frozen at the cluster size. That creation recomputes the unit's posture.

An `InfectionPreventionist` may also open an investigation manually for a `unit_id` and `organism`; a manual investigation takes `origin` `MANUAL`, snapshots the same matching cluster into `trigger_case_ids` and `contributing_case_count` at creation, starts in `TRIGGERED`, and recomputes posture. A duplicate open investigation — same unit, same organism under case-insensitive comparison, existing status `TRIGGERED` or `CONFIRMED` — is rejected with `ERR_DUPLICATE_OUTBREAK_OPEN`. Investigations may be listed with `unit_id` or `status` filters.

An `InfectionControlDirector` disposes of investigations. Confirmation requires `TRIGGERED` status (`ERR_OUTBREAK_NOT_CONFIRMABLE`) and at least one contributing case — a `contributing_case_count` of zero is rejected with `ERR_OUTBREAK_EMPTY_CLUSTER`. Confirmation lands the investigation in `CONFIRMED` and drives the unit's posture to `OUTBREAK`. Ruling out, also from `TRIGGERED` under `ERR_OUTBREAK_NOT_CONFIRMABLE`, takes a `reason`, lands the investigation in `RULED_OUT`, and recomputes posture — which may drop the unit from `ELEVATED` to `NORMAL` when no other drivers remain. Closure requires `CONFIRMED` or `RULED_OUT` status (`ERR_OUTBREAK_NOT_CLOSABLE`), and closing from `CONFIRMED` additionally requires at least one corrective action plan with `source_type` `OUTBREAK` referencing this investigation to have reached `VERIFIED` — otherwise `ERR_OUTBREAK_CLOSE_BLOCKED`. Closure lands the investigation in the terminal `CLOSED` state and recomputes posture; the unit leaves `OUTBREAK` when no other confirmed investigation remains.

### 3.9. Isolation Precautions and Compliance Audit

An `InfectionPreventionist` orders isolation for an admitted patient — a discharged patient yields `ERR_PATIENT_NOT_ADMITTED` — by supplying the `patient_id` and a `precaution_type` of `CONTACT`, `DROPLET`, or `AIRBORNE`. At most one order per patient and precaution type may be open at a time, where open means `ORDERED` or `ACTIVE`; a conflicting second order is rejected with `ERR_DUPLICATE_ISOLATION_ORDER`. The new order records the patient's `current_unit_id` as its `unit_id`, stamps `ordered_by_user_id` from the acting user and `ordered_at` from the clock, and starts with `status` `ORDERED` and `compliance_status` `NOT_AUDITED`. Orders may be listed with `patient_id`, `unit_id`, or `status` filters.

The order carries **two independent state axes**. The status axis runs `ORDERED` to `ACTIVE` to `DISCONTINUED`; the compliance axis runs from `NOT_AUDITED` to `COMPLIANT` or `NON_COMPLIANT` and is driven solely by audits. A `UnitNurseManager` starts an order that is `ORDERED` (`ERR_ISOLATION_ORDER_NOT_STARTABLE` otherwise), which sets `started_at` and lands the status axis in `ACTIVE`. Discontinuing works from either `ORDERED` or `ACTIVE` (`ERR_ISOLATION_ALREADY_DISCONTINUED` otherwise), sets `discontinued_at`, and lands the order in terminal `DISCONTINUED` — while leaving `compliance_status` exactly as it stands. A discontinuation never resets the compliance axis.

Compliance audits are performed by a `UnitNurseManager` against an `ACTIVE` order — auditing an order in any other status is rejected with `ERR_ISOLATION_ORDER_NOT_ACTIVE`. The audit payload carries the `isolation_order_id`, the `observed_at` timestamp, `elements_checked` (at least 1), and `elements_passed` (at least 0 and no greater than `elements_checked`, else `ERR_AUDIT_ELEMENTS_INVALID`). The system stamps `auditor_user_id` from the acting user, computes `compliance_pct` as one hundred times `elements_passed` divided by `elements_checked`, rounded to one decimal place half-up, and derives the audit's `outcome`: `COMPLIANT` when the rounded percentage is at least 90.0, `NON_COMPLIANT` otherwise. The comparison happens after rounding, so an audit at exactly 90.0 is compliant while one at 88.9 is not.

The order's `compliance_status` then follows last-audit-wins: it takes the `outcome` of the most recent audit by `observed_at`, breaking ties by the audit's `created_at`. When that latest outcome is `NON_COMPLIANT`, the compliance-axis mutation cascades: the system creates a `CorrectiveActionPlan` for the order's unit with `source_type` `ISOLATION_AUDIT`, `source_ref_id` pointing at the audit, a system-generated `description`, a `due_date` fourteen days after the audit's `observed_at`, `created_by_user_id` set to the literal string `system`, and status starting directly at `ACTIVE`. That plan creation recomputes the unit's posture, driving `ELEVATED`. Audits may be listed with an `isolation_order_id` filter.

### 3.10. Hand Hygiene Observation Program

A `UnitNurseManager` records each observed hand-hygiene opportunity with the `unit_id`, the `observed_at` timestamp, an `opportunity_type` of `BEFORE_PATIENT_CONTACT`, `AFTER_PATIENT_CONTACT`, `ASEPTIC_TASK`, `BODY_FLUID_RISK`, or `AFTER_SURROUNDINGS`, and an `action` of `COMPLIANT` or `MISSED`. The system stamps `observer_user_id` from the acting user. Observations are immutable once recorded — no update or delete exists — and may be listed with `unit_id` or `month` filters, where month membership is by the UTC calendar date of `observed_at`.

The unit's compliance rate for a month is computed on demand. Let the month's observations be those for the unit whose `observed_at` date falls in the requested `month`; `total_count` is their number and `compliant_count` is the number whose `action` is `COMPLIANT`. The month is **reportable** — the response's `reportable` flag — only when `total_count` reaches the facility's `hh_min_opportunities`; below that floor both rates come back null.

Two variants are computed, always as month-level aggregates rounded once. The simple rate, `simple_rate_pct`, is one hundred times `compliant_count` divided by `total_count`, rounded to one decimal place half-up. The opportunity-weighted rate, `weighted_rate_pct`, weights each observation by type — 2.0 for `ASEPTIC_TASK`, 1.5 for `BODY_FLUID_RISK`, and 1.0 for `BEFORE_PATIENT_CONTACT`, `AFTER_PATIENT_CONTACT`, and `AFTER_SURROUNDINGS` — and divides the weighted sum over compliant observations by the weighted sum over all observations, multiplies by one hundred, and rounds once to one decimal half-up. Computing per-week rounded rates and averaging them is not permitted; the aggregate-then-round order is pinned because the two orders yield different numbers. For identical underlying observations the two variants generally differ, giving reviewers an unweighted figure for default reporting and a risk-adjusted one for review.

### 3.11. Employee Exposure Follow-Up

An `EmployeeHealthNurse` registers employees with an `employee_code` (unique identifier), a free-text `role_title`, and a `home_unit_id`; employees may be listed with a `home_unit_id` filter. When an occupational exposure occurs, the nurse reports it with the `employee_id`, an optional `source_patient_id` (null when the source is unknown), an `exposure_type` of `PERCUTANEOUS`, `MUCOUS_MEMBRANE`, or `SKIN`, the `occurred_at` timestamp that anchors every subsequent due date, and the source's three serostatuses — `source_hbv_status`, `source_hcv_status`, and `source_hiv_status`, each `UNKNOWN`, `NEGATIVE`, or `POSITIVE`. The new exposure starts in `REPORTED` with `recorded_stages` empty and `next_draw_due_at` set to `occurred_at` plus seventy-two hours — the baseline draw's due instant. Exposures may be listed with `employee_id`, `status`, or `source_patient_id` filters.

The follow-up protocol is a strict sequence of stages — `BASELINE`, then `WEEK_6`, then `WEEK_12`, then `WEEK_24` — and draws must be recorded strictly in that order. Recording the source serologies moves a `REPORTED` exposure to `SOURCE_EVALUATED`, updating the three source status fields from the payload; acting on an exposure in any other state is rejected with `ERR_EXPOSURE_INVALID_STAGE`.

Each draw is recorded with its `stage`, the `drawn_at` timestamp, and the `result`. The baseline draw requires `SOURCE_EVALUATED` status and must be drawn no later than seventy-two hours after `occurred_at`; a later baseline is `ERR_BASELINE_WINDOW_MISSED`. Recording the baseline appends `{stage: BASELINE, drawn_at, result}` to `recorded_stages`, moves the exposure through `BASELINE_COMPLETE` and on into `FOLLOWUP_IN_PROGRESS` automatically, and sets `next_draw_due_at` to the week-six due instant, `occurred_at` plus forty-two days.

Follow-up draws require `FOLLOWUP_IN_PROGRESS` status and require the supplied `stage` to equal the next unrecorded stage in the fixed order — otherwise `ERR_EXPOSURE_INVALID_STAGE`. Each follow-up stage has a due offset and an acceptance window: `WEEK_6` is due at forty-two days after `occurred_at`, `WEEK_12` at eighty-four days, and `WEEK_24` at one hundred sixty-eight days; a draw is accepted only when `drawn_at` falls no earlier than seven days before its due instant and no later than twenty-eight days after it, otherwise `ERR_DRAW_OUTSIDE_WINDOW`. The week-twenty-four window therefore runs from one hundred sixty-one days through one hundred ninety-six days after the exposure. Recording `WEEK_6` or `WEEK_12` appends to `recorded_stages` and advances `next_draw_due_at` to the next stage's due instant; recording `WEEK_24` completes the protocol, landing the exposure in terminal `COMPLETED` with `next_draw_due_at` null.

When a follow-up stage has gone more than twenty-eight days past its due instant — the logical clock later than `next_draw_due_at` plus twenty-eight days — the nurse may mark the exposure lost to follow-up; attempting it earlier is `ERR_EXPOSURE_NOT_OVERDUE`, and attempting it from any status other than `FOLLOWUP_IN_PROGRESS` is `ERR_EXPOSURE_INVALID_STAGE`. Marking lost lands the exposure in terminal `LOST_TO_FOLLOWUP` with `next_draw_due_at` null.

At read time, every exposure exposes `current_stage_overdue`: true exactly when the logical clock is later than `next_draw_due_at` and the exposure's status is one of `REPORTED`, `SOURCE_EVALUATED`, `BASELINE_COMPLETE`, or `FOLLOWUP_IN_PROGRESS`.

### 3.12. Corrective Action Plans

Corrective action plans close the loop from a detected problem back to the unit. An `InfectionPreventionist` creates one with the `unit_id` it corrects, a `source_type` of `OUTBREAK`, `ISOLATION_AUDIT`, `HAND_HYGIENE`, or `SIR_HIGH`, a `source_ref_id` pointing at the originating record, a `description` of at least ten characters, and a `due_date`. The reference is polymorphic and is existence-checked against the type pinned by `source_type`: an `OUTBREAK` source must reference an `OutbreakInvestigation` that has reached `CONFIRMED`; an `ISOLATION_AUDIT` source references an `IsolationComplianceAudit`; a `SIR_HIGH` source references a `MonthlySummary`; and a `HAND_HYGIENE` source references the `Unit` itself. A missing reference, a reference to a non-existent entity, a type mismatch, or an `OUTBREAK` reference to an investigation that is not `CONFIRMED` is rejected with `ERR_CAP_SOURCE_INVALID`. A manually created plan starts in `DRAFT` with `failure_count` zero and `created_by_user_id` stamped from the acting user. (System-created plans from the audit cascade of §3.9 instead start directly in `ACTIVE`, carry a system-generated `description`, a `due_date` of the audit's `observed_at` plus fourteen days, and `created_by_user_id` set to `system`.) Plans may be listed with `unit_id` or `status` filters.

Activation moves a `DRAFT` plan to `ACTIVE` (`ERR_CAP_NOT_ACTIVATABLE` otherwise) and recomputes unit posture — an `ACTIVE` plan drives `ELEVATED`. When evidence of completion is ready, the preventionist submits the plan for verification with `evidence_notes` of at least twenty characters; this requires `ACTIVE` status (`ERR_CAP_NOT_SUBMITTABLE`) and lands the plan in `VERIFICATION_PENDING`.

Verification belongs to an `InfectionControlDirector` and requires `VERIFICATION_PENDING` (`ERR_CAP_NOT_VERIFIABLE`). Segregation of duties applies: the verifying user's `X-User-ID` must differ from `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTY` — with the deliberate consequence that system-created plans, whose `created_by_user_id` is the literal `system`, are verifiable by any director. Verification stamps `verified_by_user_id`, lands the plan in terminal `VERIFIED`, and recomputes posture, since a verified plan no longer drives `ELEVATED`.

Failed verification carries a `reason`, requires the same `VERIFICATION_PENDING` status under `ERR_CAP_NOT_VERIFIABLE`, and increments `failure_count` by one. While the resulting count is still below two, the plan returns to `ACTIVE` for rework; on the failure that brings the count to two, the plan instead moves to terminal `ESCALATED`. Both branches recompute unit posture, and an `ESCALATED` plan continues to drive `ELEVATED` — an unresolved escalation is exactly the signal posture exists to carry.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. The API is mounted under `/api`. Request payloads, preconditions, and side effects for each operation are specified in §2 and §3; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/api/facilities` | Create a facility with SIR baselines | PlatformAdmin |
| GET | `/api/facilities/{id}` | Get a facility | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| PUT | `/api/facilities/{id}` | Update facility baselines (OCC-guarded; recomputes mutable summaries) | PlatformAdmin |
| POST | `/api/units` | Create a unit in a facility | PlatformAdmin |
| GET | `/api/units` | List units, optional facility filter | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/units/{id}` | Get a unit with recomputed posture | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/units/{id}/hand-hygiene-rate` | Computed hand-hygiene rates for a unit-month | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/patients` | Register an inpatient admission | UnitNurseManager |
| GET | `/api/patients` | List patients | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/patients/{id}` | Get a patient | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/patients/{id}/transfer` | Transfer an admitted patient to another unit | UnitNurseManager |
| POST | `/api/patients/{id}/discharge` | Discharge an admitted patient | UnitNurseManager |
| POST | `/api/employees` | Register an employee | EmployeeHealthNurse |
| GET | `/api/employees` | List employees | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/employees/{id}` | Get an employee | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/device-episodes` | Record a device placement | UnitNurseManager |
| GET | `/api/device-episodes` | List device episodes | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/device-episodes/{id}` | Get a device episode | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/device-episodes/{id}/remove` | Mark a device removed | UnitNurseManager |
| POST | `/api/surgical-procedures` | Record an operative procedure | UnitNurseManager |
| GET | `/api/surgical-procedures` | List surgical procedures | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/surgical-procedures/{id}` | Get a surgical procedure | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/infection-cases` | Open a suspected HAI case | InfectionPreventionist |
| GET | `/api/infection-cases` | List infection cases | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/infection-cases/{id}` | Get an infection case | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/infection-cases/{id}/begin-review` | Move a suspected or reopened case into review | InfectionPreventionist |
| POST | `/api/infection-cases/{id}/adjudicate` | Adjudicate a case to HAI or ruled out | InfectionPreventionist |
| POST | `/api/infection-cases/{id}/reopen` | Reopen an adjudicated or ruled-out case | InfectionPreventionist |
| POST | `/api/device-day-counts` | Record a daily denominator row | UnitNurseManager |
| GET | `/api/device-day-counts` | List device day count rows | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/device-day-counts/reconcile` | Compare recorded device days against episode-derived expectation | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/device-day-counts/{id}` | Get a device day count row | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| PUT | `/api/device-day-counts/{id}` | Correct a denominator row (OCC-guarded) | UnitNurseManager |
| POST | `/api/monthly-summaries` | Create the monthly summary for a unit-month | InfectionPreventionist |
| GET | `/api/monthly-summaries` | List monthly summaries | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/monthly-summaries/{id}` | Get a monthly summary | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/monthly-summaries/{id}/submit` | Submit a summary for NHSN review | InfectionPreventionist |
| POST | `/api/monthly-summaries/{id}/accept` | Accept a submitted summary | InfectionControlDirector |
| POST | `/api/monthly-summaries/{id}/reject` | Reject a submitted summary | InfectionControlDirector |
| POST | `/api/monthly-summaries/{id}/amend` | Amend an accepted summary back under amendment | InfectionPreventionist |
| POST | `/api/outbreak-investigations` | Manually open an outbreak investigation | InfectionPreventionist |
| GET | `/api/outbreak-investigations` | List outbreak investigations | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/outbreak-investigations/{id}` | Get an outbreak investigation | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/outbreak-investigations/{id}/confirm` | Confirm a triggered investigation | InfectionControlDirector |
| POST | `/api/outbreak-investigations/{id}/rule-out` | Rule out a triggered investigation | InfectionControlDirector |
| POST | `/api/outbreak-investigations/{id}/close` | Close a confirmed or ruled-out investigation | InfectionControlDirector |
| POST | `/api/isolation-orders` | Order isolation precautions for a patient | InfectionPreventionist |
| GET | `/api/isolation-orders` | List isolation orders | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/isolation-orders/{id}` | Get an isolation order | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/isolation-orders/{id}/start` | Start an ordered isolation precaution | UnitNurseManager |
| POST | `/api/isolation-orders/{id}/discontinue` | Discontinue an isolation order | UnitNurseManager |
| POST | `/api/isolation-compliance-audits` | Audit an active isolation order | UnitNurseManager |
| GET | `/api/isolation-compliance-audits` | List isolation compliance audits | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/isolation-compliance-audits/{id}` | Get an isolation compliance audit | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/hand-hygiene-observations` | Record a hand-hygiene opportunity observation | UnitNurseManager |
| GET | `/api/hand-hygiene-observations` | List hand-hygiene observations | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/hand-hygiene-observations/{id}` | Get a hand-hygiene observation | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/employee-exposures` | Report an occupational exposure | EmployeeHealthNurse |
| GET | `/api/employee-exposures` | List employee exposures | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/employee-exposures/{id}` | Get an employee exposure | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/employee-exposures/{id}/record-source-serologies` | Record source serologies for a reported exposure | EmployeeHealthNurse |
| POST | `/api/employee-exposures/{id}/record-draw` | Record a serology draw for the next stage | EmployeeHealthNurse |
| POST | `/api/employee-exposures/{id}/mark-lost-to-followup` | Mark a follow-up exposure lost to follow-up | EmployeeHealthNurse |
| POST | `/api/corrective-action-plans` | Create a corrective action plan | InfectionPreventionist |
| GET | `/api/corrective-action-plans` | List corrective action plans | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| GET | `/api/corrective-action-plans/{id}` | Get a corrective action plan | PlatformAdmin, InfectionPreventionist, InfectionControlDirector, UnitNurseManager, EmployeeHealthNurse |
| POST | `/api/corrective-action-plans/{id}/activate` | Activate a draft corrective action plan | InfectionPreventionist |
| POST | `/api/corrective-action-plans/{id}/submit-for-verification` | Submit an active plan for verification | InfectionPreventionist |
| POST | `/api/corrective-action-plans/{id}/verify` | Verify a pending corrective action plan | InfectionControlDirector |
| POST | `/api/corrective-action-plans/{id}/fail-verification` | Fail verification of a pending plan | InfectionControlDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this table is a lookup index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 Not Found |
| `ERR_DEVICE_EPISODE_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_NOT_FOUND` | 404 Not Found |
| `ERR_INFECTION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DEVICE_DAY_COUNT_NOT_FOUND` | 404 Not Found |
| `ERR_MONTHLY_SUMMARY_NOT_FOUND` | 404 Not Found |
| `ERR_OUTBREAK_NOT_FOUND` | 404 Not Found |
| `ERR_ISOLATION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_OBSERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_EXPOSURE_NOT_FOUND` | 404 Not Found |
| `ERR_CAP_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_CASE_NOT_ADJUDICATABLE` | 409 Conflict |
| `ERR_CASE_NOT_REOPENABLE` | 409 Conflict |
| `ERR_SUMMARY_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_SUMMARY_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_SUMMARY_NOT_AMENDABLE` | 409 Conflict |
| `ERR_SUMMARY_LOCKED` | 409 Conflict |
| `ERR_OUTBREAK_NOT_CONFIRMABLE` | 409 Conflict |
| `ERR_OUTBREAK_EMPTY_CLUSTER` | 409 Conflict |
| `ERR_OUTBREAK_NOT_CLOSABLE` | 409 Conflict |
| `ERR_OUTBREAK_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_ISOLATION_ORDER_NOT_STARTABLE` | 409 Conflict |
| `ERR_ISOLATION_ALREADY_DISCONTINUED` | 409 Conflict |
| `ERR_ISOLATION_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_EXPOSURE_INVALID_STAGE` | 409 Conflict |
| `ERR_CAP_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_CAP_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_CAP_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_PATIENT_NOT_ADMITTED` | 409 Conflict |
| `ERR_DEVICE_EPISODE_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTY` | 403 Forbidden |
| `ERR_REPEAT_INFECTION_TIMEFRAME` | 422 Unprocessable Entity |
| `ERR_DOE_OUTSIDE_IWP` | 422 Unprocessable Entity |
| `ERR_DOE_NOT_HAI_DAY_RULE` | 422 Unprocessable Entity |
| `ERR_SSI_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DEVICE_DAY_RULE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_BASELINE_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_DRAW_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_NOT_OVERDUE` | 422 Unprocessable Entity |
| `ERR_DEVICE_EPISODE_OVERLAP` | 409 Conflict |
| `ERR_PROCEDURE_OVERLAP` | 409 Conflict |
| `ERR_EPISODE_PATIENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROCEDURE_PATIENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CAP_SOURCE_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DEVICE_DAY_COUNT` | 409 Conflict |
| `ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SUMMARY_MONTH` | 409 Conflict |
| `ERR_DUPLICATE_ISOLATION_ORDER` | 409 Conflict |
| `ERR_DUPLICATE_OUTBREAK_OPEN` | 409 Conflict |
| `ERR_AUDIT_ELEMENTS_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_NHSN_ORG_ID` | 409 Conflict |
| `ERR_DUPLICATE_MRN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
