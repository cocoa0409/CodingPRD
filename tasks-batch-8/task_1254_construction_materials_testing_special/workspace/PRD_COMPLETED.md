# Construction Materials Testing API — Product Requirements Document

## 1. Introduction

Construction materials testing and special inspection agencies operate under a hard regulatory contract: every structural observation, every cylinder break, and every inspector day on site must trace back to an approved statement of special inspections, and the authority having jurisdiction will not close a permit until the agency can demonstrate — with dated, attributed evidence — that every required test passed or that every failure was corrected and independently verified. Today this evidence chain lives in spreadsheets, emailed PDFs, and lab notebooks, which makes the final compliance letter an archaeology project rather than a query.

This document specifies an API that runs the agency's full evidence chain as a single, state-driven workflow. A project is opened against a building permit, its statement of special inspections is drafted, submitted, and approved under optimistic concurrency control; technicians are dispatched against certified scope lines; field tests and laboratory cylinder breaks are evaluated synchronously against the governing acceptance criteria; every nonconformance automatically opens a tracked report with a remediation deadline and an escalation clock; the inspector's daily report flows to the building official; discrepancies are negotiated with the contractor or the engineer of record; and only when every gate clears may the final compliance letter be issued. The letter is not the end of the story — a building official may void it, returning the project to active remediation.

The audience is the engineering team implementing this service. Section 2 defines the system-wide contracts that every endpoint obeys. Section 3 walks the business workflows in the order a project lives them. Section 4 is the endpoint index, and Section 5 the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the caller's role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the endpoint's authorized list, or that fails an entity-backed ownership check (for example, a technician attempting to complete another technician's assignment), is rejected with `ERR_FORBIDDEN`.

Seven roles exist, spelled exactly as follows: `AgencyAdmin`, `ProjectManager`, `EngineerOfRecord`, `Technician`, `LabAnalyst`, `Contractor`, and `BuildingOfficial`.

- `AgencyAdmin` is the agency back office: it owns reference data (projects, technicians, certifications, laboratories) and the operations checkpoints.
- `ProjectManager` owns the statement of special inspections lifecycle and the dispatch board, and issues the final compliance letter.
- `EngineerOfRecord` is the structural engineer of record: it approves or rejects submitted SSI revisions and answers engineering-routed discrepancies.
- `Technician` is the certified field inspector. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on any resource that references a `Technician` compare the resource's technician foreign-key field to `X-User-ID`. This is the only entity-backed role.
- `LabAnalyst` schedules and records cylinder breaks at the testing laboratory.
- `Contractor` submits corrections to nonconformance reports and answers contractor-routed discrepancies.
- `BuildingOfficial` is the authority-having-jurisdiction official who acknowledges daily reports and may void an issued letter.

For the six opaque roles — `AgencyAdmin`, `ProjectManager`, `EngineerOfRecord`, `LabAnalyst`, `Contractor`, and `BuildingOfficial` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `letter_issued_by` on a project when the compliance letter is issued, or as `acknowledged_by` on a daily report) but does not compare it to any entity's `id`.

All roles may call every read endpoint. Write privileges are segregated per the endpoint table in Section 4.

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
- Requests to an unknown route, or to a known route with an unsupported method, receive the same error envelope with `error_id` `ERR_NOT_FOUND` and HTTP status 404.

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0. A non-numeric `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_VALIDATION`. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. Unless a list endpoint states otherwise, results are ordered by `created_at` ascending — the order in which records came into existence, which for numbered artifacts such as NCRs is also the order of their sequential labels. Optional list filters match exactly; a filter value that matches no record simply yields an empty page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every entity in this API — projects, SSI revisions, scope items, technicians, assignments, field tests, lab samples, labs, nonconformance reports, daily inspection reports, and discrepancy tickets — carries four common properties. The `id` is a server-minted UUID with no type prefix; whenever a URL contains an `{id}` segment, it refers to this value. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, stamped from the logical clock described in §2.5. The `version` is an integer that starts at 1 on creation and increments by one on every mutation of that resource; it is the basis of the optimistic concurrency rule in §2.7.

### 2.5. The Logical Clock

All timestamps the server writes — submissions, approvals, detections, completions, letter issuance — are read from a single logical clock, never from wall-clock time. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An `AgencyAdmin` may advance it through an administrative clock-setting capability whose request carries a `to_iso8601` instant; the capability responds with the now-current `current_utc` value. Any parseable ISO 8601 instant is accepted — the clock may be set forward or backward. Deadlines, break windows, escalation scores, and age calculations throughout this document are all evaluated against this clock.

### 2.6. Measurement Precision and Rounding Conventions

Three precision regimes govern every computed number in the system, and all rounding is round half up.

Concrete strength figures are expressed on a 10-psi grid: a cylinder set's average is the arithmetic mean of its cylinder strengths, rounded half up to the nearest multiple of 10 psi, so that 4215 psi becomes 4220 psi while 4214.9 psi becomes 4210 psi. Rounding order is pinned — each set is averaged and rounded first, and every downstream aggregate (including moving averages) consumes only these rounded set averages. Soil compaction percentages are computed to exactly 1 decimal place, round half up. Escalation scores and day counts use integer arithmetic with whole-day flooring.

Boundary comparisons throughout the system are inclusive in the direction stated with each rule: a compaction percentage landing exactly on its threshold passes, a break landing exactly at its tolerance limit is within tolerance, a scope item whose conforming count exactly reaches its requirement is satisfied, and an escalation score landing exactly on the escalation threshold escalates.

### 2.7. Optimistic Concurrency Control on SSI Approval

Exactly one write operation in the API is version-guarded: the engineer's decision on a submitted SSI revision. That request must carry `expected_project_version`, a non-optional field holding the `version` of the parent project as the client last observed it. If the project's current `version` has advanced beyond what the client saw — because another approval or rejection landed in the meantime — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because approval legitimately supersedes whatever revision is currently approved, and an approver reasoning from a stale project view must not silently supersede a revision it never observed. No other endpoint takes a version field. `expected_project_version` must be an integer; a non-integer value is `ERR_VALIDATION`. On the decision endpoint the checks run in this order: the revision's state check, payload validation, the stale-version comparison, and finally the project-completion gate of §2.10.

### 2.8. Nested Path Resolution and Same-Project Reference Scope

Where a URL nests resources — a project's SSI revisions, an assignment's field tests, a lab's samples — path identifiers are validated left to right: the project first, then the revision, assignment, sample, test, report, or ticket. The first segment that fails to resolve yields `ERR_NOT_FOUND`. Cross-references supplied in request bodies must resolve inside the same project scope: a scope item referenced at assignment creation must belong to that project's currently approved revision, the assignments cited in a daily report must belong to the submitting technician, that project, and that report date, and evidence cited at correction verification must live on the same scope item. A reference that exists but resolves outside its expected scope is rejected with `ERR_REFERENCE_MISMATCH`. A body-supplied reference that fails to resolve at all surfaces as `ERR_NOT_FOUND` for the primary entity references of creation requests (`technician_id` at assignment creation, `assignment_id` at field-test and lab-sample creation, `lab_id` at lab-sample creation) and as `ERR_REFERENCE_MISMATCH` for scoped citations (`scope_item_id` at assignment creation, the assignment citations of a daily report, an optional `scope_item_id` on a discrepancy, and `evidence_field_test_id` at correction verification).

### 2.9. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic. First, authentication: presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`). Second, authorization: the caller's role against the endpoint's role list (`ERR_FORBIDDEN`). Authorization checks that depend on the target entity are applied once the target has resolved: entity-backed ownership rules (`ERR_FORBIDDEN`) and discrepancy routing mismatches (`ERR_DISCREPANCY_ROUTING`) surface after path resolution and before the target's state check, while segregation-of-duties violations on correction verification (`ERR_SEGREGATION_OF_DUTIES`) surface after the correction's state check. Third, existence of path identifiers, left to right (`ERR_NOT_FOUND`). Fourth, state: whether the target resource's current state permits the operation (`ERR_INVALID_STATE`), a tier that also carries the domain state errors `ERR_PROJECT_COMPLETED`, `ERR_LETTER_ALREADY_ISSUED`, `ERR_NO_LETTER_TO_VOID`, `ERR_TEST_NOT_VOIDABLE`, and `ERR_NO_RESULT_RECORDED`; within this tier the target resource's own state check precedes the project-completion gate. Fifth, technician fitness for dispatch: active status, certification presence, level sufficiency, and certification currency (`ERR_TECHNICIAN_INACTIVE`, `ERR_CERTIFICATION_MISSING`, `ERR_CERTIFICATION_INSUFFICIENT`, `ERR_CERTIFICATION_EXPIRED`). Sixth, temporal occupancy: technician window overlap on assignment creation and break-date equality on break scheduling (`ERR_TECHNICIAN_DOUBLE_BOOKED`, `ERR_BREAK_DATE_MISMATCH`). Seventh, uniqueness and aggregate gates: unique `permit_number`, `employee_code`, and `lab_code` at creation, the one-daily-report rule, and the posture gate on letter issuance (`ERR_VALIDATION`, `ERR_DUPLICATE_DAILY_REPORT`, `ERR_POSTURE_NOT_READY`). Eighth, cross-reference scope (`ERR_SSI_NOT_APPROVED`, then `ERR_REFERENCE_MISMATCH`). Ninth and last, laboratory day capacity (`ERR_LAB_DAY_CAPACITY`).

Malformed payloads — a missing required field, an unknown enum value, a malformed date or time, an `end_time` that is not after `start_time` — are rejected with `ERR_VALIDATION`. On requests that create a root-level resource (projects, technicians, laboratories, assignments, field tests, lab samples, daily reports, discrepancies) payload validation runs before any business rule is consulted. SSI revision creation first resolves the parent project and applies the project-completion gate, then validates the payload. On every other request acting on an existing resource, the target's existence and current-state checks run before payload validation — except correction verification, which validates `outcome` before the state check.

### 2.10. The Project Completion Gate

A project whose final compliance letter has been issued is closed for new work: mutations that open or advance field activity under a project in `COMPLETED` status — creating, submitting, or approving an SSI revision, creating, dispatching, or completing an assignment, recording or voiding a field test, logging a lab sample, filing a daily report, or raising a discrepancy — are rejected with `ERR_PROJECT_COMPLETED`. The remaining transitions stay available so that in-flight evidence can settle: cancelling an assignment, scheduling, recording, or discarding a break, submitting or verifying a correction, acknowledging a daily report, and responding to or resolving a discrepancy are all still permitted. Reads remain open to all roles. The gate lifts only if the building official voids the letter, which returns the project to `ACTIVE`.

## 3. Business Logic & Workflows

### 3.1. Opening the Project and the Statement of Special Inspections

Work begins when an `AgencyAdmin` registers a project with its `name`, `permit_number`, `jurisdiction`, `contractor_name`, and `building_official_name`. The permit number is unique across all projects; a duplicate is rejected with `ERR_VALIDATION`. A new project starts in `ACTIVE` status with `compliance_posture` of `IN_PROGRESS`, an `open_ncr_count` of zero, `letter_status` of `NONE`, and no approved statement yet — `current_approved_ssi_id`, `letter_issued_at`, `letter_issued_by`, and `letter_void_reason` are all null.

With the project open, a `ProjectManager` drafts the statement of special inspections. Each revision is created together with its scope items atomically: the request carries `specified_fc_psi` (an integer, the specified concrete compressive strength f'c, for example 4000), an optional `acceptance_method_concrete` of `MOVING_AVERAGE` or `INDIVIDUAL_SET` defaulting to `MOVING_AVERAGE`, and a `scope_items` array holding at least one line. Each scope item declares its `test_method` — one of `CONCRETE_STRENGTH`, `SOIL_COMPACTION`, `WELD_VISUAL`, or `BOLT_TENSION` — a free-text `description` such as "footing concrete, pour #3", the `required_cert_level` a dispatched technician must hold (1, 2, or 3), the `required_count` of conforming results needed to satisfy the line (at least 1), and an `is_structural` flag, defaulting to false, marking lines whose failure raises a structural-severity nonconformance. Soil lines additionally declare a `proctor_method` of `STANDARD` (the default) or `MODIFIED`, and must carry both `standard_max_density_pcf` and `modified_max_density_pcf` reference densities; for non-soil methods those two density fields are null. Scope items are born with `completed_count` zero and `status` of `OPEN`, each pinned to its owning revision via `ssi_revision_id`, and a listing of a revision's scope items returns them in creation order.

A revision receives its `revision_number` automatically — a per-project monotone sequence starting at 1, assigned in creation order — and starts in `DRAFT`. Submission by a `ProjectManager` moves it `DRAFT → SUBMITTED` and stamps `submitted_at` from the clock; submitting an empty revision with no scope items is rejected with `ERR_INVALID_STATE`, and submission under a completed project fails with `ERR_PROJECT_COMPLETED`.

The `EngineerOfRecord` then decides. The decision request carries `decision` — `APPROVE` or `REJECT` — plus the optimistic-concurrency field described in §2.7. Approval moves the revision `SUBMITTED → APPROVED`, stamps `approved_at`, flips any previously approved revision of the same project to `SUPERSEDED`, points the project's `current_approved_ssi_id` at the newly approved revision, increments the project's `version` by one, and recomputes the project's compliance posture. Rejection moves the revision `SUBMITTED → REJECTED`, terminal, and still increments the project `version` by one. Both decision branches require the project to be `ACTIVE`; both are guarded by the stale-version rule, so an approval or rejection grounded in an outdated project view fails with `ERR_STALE_VERSION` rather than silently rewriting history. `REJECTED` and `SUPERSEDED` are terminal; a superseded revision's scope items remain as an immutable snapshot, and assignments already pinned to it are never migrated. A project's revisions may be listed with an optional `status` filter, and a single revision may be fetched on its own.

### 3.2. Technician Roster and Certifications

An `AgencyAdmin` maintains the field roster. A technician is registered with `full_name` and an agency-wide unique `employee_code` — a duplicate code is rejected with `ERR_VALIDATION` — and starts in `ACTIVE` status. Certifications may be supplied at creation and are later appended one at a time through a dedicated capability; each entry in the `certifications` array is a triple of `method` (one of the four test methods), `level` (1 through 3), and `expires_at` (an ISO date). When a technician leaves active duty, deactivation moves `status` from `ACTIVE` to `INACTIVE`; deactivating a technician who is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The technician's historical assignments and recorded results keep their attribution untouched.

### 3.3. Dispatching the Field

A `ProjectManager` builds the dispatch board by creating inspection assignments. Creation takes `project_id`, `scope_item_id`, `technician_id`, the scheduled `work_date` (an ISO date), and a time window `start_time` to `end_time` in 24-hour HH:MM form; an `end_time` that is not after `start_time` is rejected with `ERR_VALIDATION`. The scope item must belong to the project's currently approved SSI revision: if the project has no approved revision at all, creation fails with `ERR_SSI_NOT_APPROVED` — this check runs before the scope item is examined; if the scope item belongs to another project or to a revision that is not the current approved one, it fails with `ERR_REFERENCE_MISMATCH`, as does a `scope_item_id` that resolves to nothing at all. A `technician_id` that does not reference an existing technician is rejected with `ERR_NOT_FOUND`. At creation the assignment pins `ssi_revision_id` to the project's `current_approved_ssi_id`, and that pin is permanent — later approved revisions do not migrate existing assignments.

The new assignment occupies the technician's calendar. Windows are half-open intervals on a given `work_date`: a new window overlapping an existing `REQUESTED` or `DISPATCHED` assignment of the same technician on the same date is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`, while two windows that merely touch — one ending exactly when the other begins — are both allowed. The assignment list supports optional filters on `project_id`, `scope_item_id`, `technician_id`, `status`, and `work_date`.

Dispatch is the certification gate. Moving an assignment `REQUESTED → DISPATCHED` requires, in order after the generic checks: the technician is `ACTIVE` (otherwise `ERR_TECHNICIAN_INACTIVE`); the technician holds a certification whose `method` matches the scope item's `test_method` (otherwise `ERR_CERTIFICATION_MISSING`); that certification's `level` is at least the scope item's `required_cert_level` (otherwise `ERR_CERTIFICATION_INSUFFICIENT`); and its `expires_at` falls strictly after the assignment's `work_date` (otherwise `ERR_CERTIFICATION_EXPIRED`). When the technician holds several certifications for the method, the highest-level one is the certification evaluated for level and currency. Dispatch under a completed project fails with `ERR_PROJECT_COMPLETED`.

Plans change. Cancellation from either `REQUESTED` or `DISPATCHED` moves the assignment to `CANCELLED` and frees the technician's window; the same cancellation capability called with `requeue` set to true on a `DISPATCHED` assignment instead returns it to `REQUESTED` — a requeue loop for re-dispatch — and likewise frees the window. The cancellation request body is optional, `requeue` is honored only as the JSON boolean `true`, and `requeue` on a `REQUESTED` assignment cancels it outright, there being no earlier state to return to. Completion is the technician's own act: only the technician whose `id` matches the assignment's `technician_id` may complete it (anyone else gets `ERR_FORBIDDEN`), and only from `DISPATCHED`, and only when at least one field test or lab sample has been recorded against it (otherwise `ERR_NO_RESULT_RECORDED`) — any recorded field test, even one later voided, or any lab sample in any status satisfies this gate. Completion stamps `completed_at`, stores an optional `completion_note`, moves the assignment to `COMPLETED`, and recomputes the project's compliance posture, since the set of completed-but-uncovered assignments feeds the readiness gate.

### 3.4. Field Test Results and On-the-Spot Evaluation

On a dispatched assignment, the assigned technician records field tests directly: the request carries the `assignment_id` and a method-shaped `measured_values` object. The server copies `test_method`, `technician_id`, and `project_id` from the assignment and its scope item at creation — attribution that later drives segregation of duties — and evaluates the result synchronously, before the response returns. Field tests exist for the three non-concrete methods only: a field test against a `CONCRETE_STRENGTH` scope item is rejected with `ERR_VALIDATION`, concrete evidence living solely in the laboratory chain of §3.5. A field test exists only in `RECORDED` or `VOIDED` status; its verdict lands in `result` as `CONFORMING` or `NONCONFORMING`, with the evaluation trail preserved in `result_details` — `relative_compaction_pct`, `threshold_pct`, and `proctor_method` for soil compaction, `defect_count` for weld visual, and `bolts_tested` and `bolts_passed` for bolt tension.

Soil compaction is evaluated against the scope item's proctor curve. When the item's `proctor_method` is `STANDARD`, the reference density is `standard_max_density_pcf` and the pass threshold is 95.0 percent; when it is `MODIFIED`, the reference is `modified_max_density_pcf` and the threshold relaxes to 92.0 percent — identical field density can therefore flip verdicts between the two curves. The relative compaction is one hundred times the measured `field_dry_density_pcf` divided by the applicable reference density, rounded half up to one decimal place and exposed as `relative_compaction_pct` alongside the applied `threshold_pct` in the result details. A result at or above the threshold conforms — exactly 95.0 passes, 94.9 fails. Weld visual inspection is stricter to state: the test conforms only when `defect_count` is zero. Bolt tension conforms only when `bolts_tested` is at least one and every tested bolt passed — `bolts_passed` equal to `bolts_tested`.

Consequences differ by verdict. A conforming test increments its scope item's `completed_count` by one; when that count reaches the item's `required_count`, the item's `status` flips from `OPEN` to `SATISFIED` — exactly reaching the requirement satisfies it — and the project's posture is recomputed. A nonconforming test auto-creates a nonconformance report with `source_type` of `FIELD_TEST`, severity `STRUCTURAL` when the scope item's `is_structural` flag is true and `MAJOR` otherwise, increments the project's `open_ncr_count` by one, and recomputes posture.

A recorded test may later be voided by a `ProjectManager`, but only a conforming one: voiding a `NONCONFORMING` test — or one already `VOIDED` — is rejected with `ERR_TEST_NOT_VOIDABLE`, because a failure's NCR must run to verification rather than be erased. Voiding is a compensating action: the scope item's `completed_count` decrements by one, the item reopens to `OPEN` if the count falls back below its requirement, and posture is recomputed.

### 3.5. Laboratory Samples: Cast, Schedule, Break

Concrete strength evidence travels a longer chain. Before any sample can reference one, an `AgencyAdmin` registers each testing laboratory with its `name`, an agency-wide unique `lab_code` — a duplicate is rejected with `ERR_VALIDATION` — and a `daily_break_capacity`, the maximum number of samples that may be break-scheduled per calendar day, which must be at least 1.

On a dispatched assignment whose scope item is a `CONCRETE_STRENGTH` line, the assigned technician logs a cast cylinder set with its `assignment_id`, the `lab_id` of the laboratory that will break it, the `cast_at` field-casting timestamp, and a `required_break_age_days` of 7, 28, or 56. An `assignment_id` or `lab_id` that does not resolve is rejected with `ERR_NOT_FOUND`, and logging on an assignment whose scope item is not `CONCRETE_STRENGTH` is rejected with `ERR_VALIDATION`. The server computes `break_due_at` as exactly `required_break_age_days` days after `cast_at`, and the sample enters `CAST` status.

A `LabAnalyst` then books the break. The requested `break_scheduled_date` must equal the calendar date of `break_due_at` — a mismatch is rejected with `ERR_BREAK_DATE_MISMATCH`. The laboratory's day load is an aggregate bucket: the count of that lab's samples sharing the same `break_scheduled_date` and sitting in `BREAK_SCHEDULED` status must remain strictly below the lab's `daily_break_capacity`; a day already at capacity rejects with `ERR_LAB_DAY_CAPACITY`, while a day at one below capacity still accepts. Samples in `CAST`, `REPORTED`, or `DISCARDED` occupy no slot. A successful booking moves the sample `CAST → BREAK_SCHEDULED` and consumes one slot of that lab-day.

Recording the break moves the sample `BREAK_SCHEDULED → REPORTED` and releases the day-load slot. The analyst supplies `broken_at` and the `cylinder_strengths_psi` array (at least one strength). From these the server derives, in order: the `set_average_psi` on the 10-psi grid of §2.6; the `age_at_break_hours`, the elapsed hours between `cast_at` and `broken_at` rounded half up to whole hours; and the tolerance pair `within_tolerance` and `flagged_out_of_tolerance`. Tolerance depends on the required age: a 7-day break allows 6 hours of absolute deviation from `break_due_at`, a 28-day break allows 24 hours, a 56-day break allows 48 hours, and any other age allows 12 hours; landing exactly at the limit is within tolerance, and `flagged_out_of_tolerance` is simply the negation of `within_tolerance`. The sample's `result_details` preserves the acceptance inputs: `individual_floor` under both variants, plus `moving_average_psi` and the `window` of set averages under `MOVING_AVERAGE`.

The acceptance verdict `break_result` then follows the acceptance method pinned on the assignment's SSI revision, using the revision's `specified_fc_psi` as f'c. Under the `MOVING_AVERAGE` variant, the server assembles the rounded set averages of every reported, non-discarded sample pinned to the same scope item — including this one — ordered by `break_due_at` ascending and then `created_at` ascending, takes the last three of them (or fewer when fewer exist), and averages those on the same 10-psi grid to form the moving average. The set conforms when the moving average reaches f'c and every set average inside the window clears the individual floor: for f'c of 5000 psi or less the floor is 500 psi below f'c, and for higher strengths it is nine-tenths of f'c rounded half up to a whole psi — so a single below-f'c set can still pass. Under the `INDIVIDUAL_SET` variant the current set stands alone and conforms only when its own `set_average_psi` reaches f'c; identical cylinder data can flip the verdict between the two variants.

Consequences mirror the field-test cascades, with one addition. A conforming break increments the scope item's `completed_count` (possibly flipping it to `SATISFIED`) and recomputes posture. A nonconforming break auto-creates an NCR with `source_type` of `LAB_SAMPLE`, severity `STRUCTURAL` or `MAJOR` by the same `is_structural` rule as field tests, and increments `open_ncr_count`. Independently of the verdict, a sample flagged out of tolerance auto-creates a second NCR at severity `MINOR` with its own increment of `open_ncr_count` — so one record-break can raise two reports. A cast sample that will never be broken (damaged in transit, mislabeled) may be discarded by a `LabAnalyst`, moving `CAST → DISCARDED` with no further effect; discarded samples never enter acceptance input sets. The samples at a lab may be listed with an optional `break_scheduled_date` filter, which is exactly the day-load observation.

### 3.6. Nonconformance Reports, Correction, and Escalation

Nonconformance reports are never created by hand — they arise only from the system cascades described above. Each receives a per-project sequential `ncr_number` in creation order (`NCR-0001`, `NCR-0002`, and so on), carries the `project_id` inherited from the source result's assignment, a polymorphic `source_type` of `FIELD_TEST` or `LAB_SAMPLE` with the corresponding `source_id`, the `scope_item_id` copied from that assignment, an auto-generated `description`, a computed `severity` of `MINOR`, `MAJOR`, or `STRUCTURAL`, and a `detected_at` clock timestamp. The remediation `deadline_date` falls 30 days after detection for `MINOR`, 14 days for `MAJOR`, and 7 days for `STRUCTURAL`. A fresh report is `OPEN` with `rejection_count` and `escalation_score` zero and `correction_note`, `verified_by_technician_id`, and `evidence_field_test_id` all null. The project NCR list orders by creation and accepts optional `status`, `severity`, and `scope_item_id` filters.

Remediation is a cycle. A `Contractor` submits a correction — the request carries the `correction_note` — moving the report from `OPEN` (or from `ESCALATED`, described below) to `CORRECTION_SUBMITTED`. Verification belongs to a `Technician` other than the one whose result raised the report: the verifier's `X-User-ID` must differ from the source field test's recorded technician, or, for lab-sourced reports, from the technician of the assignment that cast the sample; a self-verification is rejected with `ERR_SEGREGATION_OF_DUTIES`. The verification request carries an `outcome` of `VERIFIED` or `REJECTED` plus an optional `verification_note`, and may cite an `evidence_field_test_id` — a retest that must reference a `RECORDED` field test with a `CONFORMING` result on the same scope item, failing which the request is rejected with `ERR_REFERENCE_MISMATCH`. Evidence is examined, and stored on the report, only for a `VERIFIED` outcome; a `REJECTED` outcome ignores any `evidence_field_test_id`. A `VERIFIED` outcome records `verified_by_technician_id`, decrements the project's `open_ncr_count` by one as a compensating action, recomputes posture, and moves the report to `VERIFIED`, its terminal state. A `REJECTED` outcome returns the report to `OPEN`, increments `rejection_count` by one, and clears the `correction_note` for another remediation round.

Time pressure is applied by an admin-only daily sweep capability. On each run it recomputes the `escalation_score` of every `OPEN` report — reports in `CORRECTION_SUBMITTED` or `ESCALATED` are not scored — and escalates those reaching the threshold. The score counts `days_open` as whole days between detection and the current clock date, floored at zero, and days past deadline as the whole days by which the clock has passed `deadline_date`, floored at zero. A `STRUCTURAL` report even one day past its deadline scores 100 outright. Otherwise the score starts from a severity base — 20 for `MINOR`, 40 for `MAJOR`, 60 for `STRUCTURAL` — adds 2 points per day open, 3 points per day overdue, and 15 points per rejection, capped at 100. A score of 70 or more moves the report `OPEN → ESCALATED`; exactly 70 escalates. Escalated reports still accept contractor corrections, and every escalation recomputes the affected project's posture. The sweep responds with the `escalated_ncr_ids` it acted on.

### 3.7. The Daily Inspection Report to the Building Official

At the end of a field day, each technician files one daily report per project per day. The request carries `project_id`, the `report_date` it covers, the `assignment_ids` being reported on, and a narrative `summary` of work performed, conditions, and observations; the report's `technician_id` is set from the caller's `X-User-ID` as attribution. Every cited assignment must be `COMPLETED`, must belong to this technician and this project, must have a `work_date` equal to the `report_date`, and must not already be covered by another report — a citation violating any of these is rejected with `ERR_REFERENCE_MISMATCH`. One report per project, technician, and date is the hard rule: a second submission for the same triple is rejected with `ERR_DUPLICATE_DAILY_REPORT`. The report is created directly in `SUBMITTED` status, each referenced assignment's `covered_by_dir_id` is pointed at the new report — the coverage marker that feeds the readiness gate — and the project's posture is recomputed. Reports may be listed per project with optional `technician_id` and `report_date` filters. Receipt closes when the `BuildingOfficial` acknowledges the report, moving it `SUBMITTED → ACKNOWLEDGED` and recording `acknowledged_by`; acknowledging an already-acknowledged report is a state error.

### 3.8. Discrepancy Resolution with the Contractor and Engineer

Field conditions sometimes disagree with the contract documents without constituting a failed test. A `Technician` raises a discrepancy ticket with `project_id`, a short `subject`, a `description` of the conflicting condition, and a `routed_to` of `CONTRACTOR` or `ENGINEER` naming the party that must respond; a `scope_item_id` may optionally relate the ticket to a scope line — when supplied it must reference a scope item belonging to a revision of the same project (any revision, not only the approved one), failing which the request is rejected with `ERR_REFERENCE_MISMATCH`. The ticket records `raised_by_technician_id` from the caller, starts in `RAISED` with `round_count` at 1 and `response_text` null, and its existence immediately weighs on the readiness gate — raising one recomputes the project posture, because any ticket in `RAISED` or `RESPONSE_SUBMITTED` blocks readiness.

Only the routed party may respond: a ticket routed to `CONTRACTOR` is answered by a `Contractor`, one routed to `ENGINEER` by the `EngineerOfRecord`, and any other role attempting to respond is rejected with `ERR_DISCREPANCY_ROUTING`. A response stores `response_text` and moves the ticket `RAISED → RESPONSE_SUBMITTED`. Resolution is again a technician's act — any technician may decide, not only the one who raised the ticket — with an `outcome`: `ACCEPT` moves the ticket to `RESOLVED` — terminal — and recomputes posture as the open-discrepancy gate clears, while `REJECT` sends it back to `RAISED`, increments `round_count` by one, and clears `response_text` for another negotiation round. A project's tickets may be listed with an optional `status` filter.

### 3.9. Compliance Posture and the Final Letter

Every project's `compliance_posture` is derived, never set directly, and it is recomputed on any mutation touching NCR status, scope item status, daily-report coverage, discrepancy status, or letter status. The derivation evaluates four gates in a fixed order. First, if `letter_status` is `ISSUED`, the posture is `LETTER_ISSUED`. Otherwise, if `open_ncr_count` — the number of the project's reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` — is greater than zero, the posture is `NONCONFORMANCE_OUTSTANDING`. Otherwise, readiness requires all of: an approved revision exists (`current_approved_ssi_id` is not null), every scope item of that revision is `SATISFIED`, no discrepancy ticket of the project sits in `RAISED` or `RESPONSE_SUBMITTED`, and every `COMPLETED` assignment of the project has a non-null `covered_by_dir_id`; when all four hold, the posture is `READY_FOR_LETTER`. Failing that, the posture is `IN_PROGRESS`.

Issuance is the `ProjectManager`'s act and is doubly gated: the posture must be exactly `READY_FOR_LETTER` (otherwise `ERR_POSTURE_NOT_READY`) and `letter_status` must not already be `ISSUED` (otherwise `ERR_LETTER_ALREADY_ISSUED`). Issuing sets `letter_status` to `ISSUED`, stamps `letter_issued_at` from the clock, records the caller as `letter_issued_by`, moves the project's `status` to `COMPLETED` — which activates the completion gate of §2.10 — and the posture becomes `LETTER_ISSUED`.

The cycle can reopen. The `BuildingOfficial` may void an issued letter by supplying a `void_reason`, which is stored as `letter_void_reason`; voiding requires `letter_status` to be `ISSUED` (otherwise `ERR_NO_LETTER_TO_VOID`), and `letter_issued_at` and `letter_issued_by` are left untouched by the void. The letter flips to `VOIDED`, the project returns to `ACTIVE`, and the posture is recomputed from the current evidence — landing back at `READY_FOR_LETTER` or lower — leaving the project open for remediation and a possible re-issue.

## 4. Endpoint Definitions

The API is mounted under `/api`. Endpoints that create a new resource respond with 201 and the created resource; endpoints that modify, transition, or acknowledge an existing resource respond with 200; reads respond with 200. All bodies and errors follow the envelopes of §2.2, and all list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/projects | Create a project (status `ACTIVE`, posture `IN_PROGRESS`, `open_ncr_count` 0, `letter_status` `NONE`) | AgencyAdmin |
| GET | /api/projects/{id} | Get a project including computed posture, `open_ncr_count`, and letter fields | All roles |
| POST | /api/projects/{id}/ssi-revisions | Create an SSI revision with its scope items atomically (array, min 1) | ProjectManager |
| GET | /api/projects/{id}/ssi-revisions | List SSI revisions of a project, optional `status` filter | All roles |
| GET | /api/ssi-revisions/{id} | Get one SSI revision | All roles |
| POST | /api/ssi-revisions/{id}/submit | Submit a `DRAFT` revision to the engineer of record | ProjectManager |
| POST | /api/ssi-revisions/{id}/approve | Engineer decision (`decision` = APPROVE/REJECT), OCC-guarded via `expected_project_version` | EngineerOfRecord |
| GET | /api/ssi-revisions/{id}/scope-items | List scope items of a revision in creation order | All roles |
| POST | /api/technicians | Create a technician (status `ACTIVE`), optional initial certifications | AgencyAdmin |
| GET | /api/technicians/{id} | Get a technician including the certifications array | All roles |
| POST | /api/technicians/{id}/certifications | Append one certification (`method`, `level`, `expires_at`) | AgencyAdmin |
| POST | /api/technicians/{id}/deactivate | Deactivate a technician; existing assignments keep attribution | AgencyAdmin |
| POST | /api/assignments | Create an assignment (`REQUESTED`); pins the current approved revision; checks window overlap | ProjectManager |
| GET | /api/assignments | List assignments with optional filters | All roles |
| GET | /api/assignments/{id} | Get one assignment | All roles |
| POST | /api/assignments/{id}/dispatch | Dispatch a `REQUESTED` assignment; enforces the certification gate | ProjectManager |
| POST | /api/assignments/{id}/cancel | Cancel from `REQUESTED`/`DISPATCHED`; `requeue` returns to `REQUESTED` | ProjectManager |
| POST | /api/assignments/{id}/complete | Technician completes own `DISPATCHED` assignment with at least one result | Technician |
| POST | /api/field-tests | Record a field test on a `DISPATCHED` assignment; result computed synchronously | Technician |
| GET | /api/assignments/{id}/field-tests | List field tests of an assignment | All roles |
| POST | /api/field-tests/{id}/void | Void a `CONFORMING` recorded test (compensating action) | ProjectManager |
| POST | /api/lab-samples | Log a cast cylinder set on a `DISPATCHED` concrete assignment | Technician |
| GET | /api/lab-samples/{id} | Get one lab sample | All roles |
| GET | /api/assignments/{id}/lab-samples | List lab samples collected on an assignment | All roles |
| POST | /api/lab-samples/{id}/schedule-break | Book the break on the due date; enforces per-lab per-day capacity | LabAnalyst |
| POST | /api/lab-samples/{id}/record-break | Record break results; computes average, tolerance, verdict; may raise NCR(s) | LabAnalyst |
| POST | /api/lab-samples/{id}/discard | Discard a `CAST` sample that will never be broken | LabAnalyst |
| POST | /api/labs | Register a laboratory | AgencyAdmin |
| GET | /api/labs/{id} | Get a lab | All roles |
| GET | /api/labs/{id}/lab-samples | List samples at a lab, optional `break_scheduled_date` day filter | All roles |
| GET | /api/projects/{id}/ncrs | List NCRs of a project in creation order, optional filters | All roles |
| POST | /api/ncrs/{id}/submit-correction | Contractor submits a correction for an `OPEN` or `ESCALATED` NCR | Contractor |
| POST | /api/ncrs/{id}/verify | Technician verifies or rejects a correction (segregation of duties enforced) | Technician |
| POST | /api/daily-reports | Technician submits the daily report (one per project/technician/date) | Technician |
| GET | /api/projects/{id}/daily-reports | List daily reports of a project, optional filters | All roles |
| POST | /api/daily-reports/{id}/acknowledge | Building official acknowledges a daily report | BuildingOfficial |
| POST | /api/discrepancies | Technician raises a discrepancy routed to `CONTRACTOR` or `ENGINEER` | Technician |
| GET | /api/projects/{id}/discrepancies | List discrepancies of a project, optional `status` filter | All roles |
| POST | /api/discrepancies/{id}/respond | Routed party responds to the ticket | Contractor, EngineerOfRecord |
| POST | /api/discrepancies/{id}/resolve | Technician accepts (`RESOLVED`) or rejects (back to `RAISED`) the response | Technician |
| POST | /api/projects/{id}/issue-letter | Issue the final compliance letter; requires `READY_FOR_LETTER` | ProjectManager |
| POST | /api/projects/{id}/void-letter | Building official voids an issued letter; project returns to `ACTIVE` | BuildingOfficial |
| POST | /api/_clock/set_current_utc | Set the logical clock (ISO 8601); startup default 2026-05-01T00:00:00Z | AgencyAdmin |
| POST | /api/ops/run-daily-sweep | Recompute escalation scores of `OPEN` NCRs; escalate those at the threshold | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue is the index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_DISCREPANCY_ROUTING | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_PROJECT_COMPLETED | 409 |
| ERR_TECHNICIAN_INACTIVE | 409 |
| ERR_CERTIFICATION_MISSING | 409 |
| ERR_CERTIFICATION_INSUFFICIENT | 409 |
| ERR_CERTIFICATION_EXPIRED | 409 |
| ERR_TECHNICIAN_DOUBLE_BOOKED | 409 |
| ERR_NO_RESULT_RECORDED | 409 |
| ERR_TEST_NOT_VOIDABLE | 409 |
| ERR_LAB_DAY_CAPACITY | 409 |
| ERR_DUPLICATE_DAILY_REPORT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_POSTURE_NOT_READY | 409 |
| ERR_LETTER_ALREADY_ISSUED | 409 |
| ERR_NO_LETTER_TO_VOID | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SSI_NOT_APPROVED | 422 |
| ERR_REFERENCE_MISMATCH | 422 |
| ERR_BREAK_DATE_MISMATCH | 422 |
