# Material Testing Lab API — Product Requirements Document

## 1. Introduction

Construction material testing laboratories sit at the intersection of regulatory compliance and operational throughput. A single concrete cube, rebar bundle, or asphalt core arriving at the front desk must be tracked from the moment it is logged with its witness-sampling record, through tester assignment and instrument booking, into the testing bay, back out through multi-level technical review and authorized signature, and finally onto an issued report and invoice that the project owner can place in their compliance file. Every step touches one of three audiences — the client paying for the test, the laboratory's accreditation authority, and the project manager whose construction schedule depends on the result — and a slip at any step can invalidate the work for all three.

This document specifies the API that backs the laboratory's sample-to-report workflow. It binds together the registration desk's clerical work, the testing floor's experimental work, the review office's verification work, and the back office's billing work into a single audit-traceable system. Key obligations the API must enforce include: segregation of duties between tester, reviewer, and signatory; calibration validity of every instrument used; qualification validity of every tester at the moment of assignment; and the financial relationship between deposits, urgent-handling surcharges, package discounts, and refunds for tests that fail even after a single permitted retest. A test-driving clock-advance capability allows operations and integration tests to deterministically observe the system's response to time-dependent transitions (calibration lapses, qualification expirations, and the 30-day report archival window) without waiting in wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API MUST carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the server rejects the request with `ERR_AUTH_MISSING` (HTTP 401). If `X-User-Role` is present but does not exactly match one of the five declared role names — `LabClerk`, `Tester`, `Reviewer`, `Signatory`, `LabManager` — the request is rejected with `ERR_AUTH_INVALID` (HTTP 401). Once the role is recognised, the server checks the role-based access matrix for the targeted endpoint; if the role lacks permission, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). These three checks are evaluated strictly in this order, before any business validation runs. The single exception is the test-driving and event-injection endpoints (clock-advance and event-emit), which the operator may invoke without the standard auth-presence check; all other endpoints require both headers.

The five roles divide laboratory responsibility along a segregation-of-duties spine:

- A `LabClerk` is the front-desk operator who registers samples, creates testing tasks, and books instruments. When `X-User-Role` is `LabClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records this id on audit entries (as `actor_id` on `AuditEvent` and `DataModification`) but does not compare it to any entity's `id`.
- A `Tester` performs tests, submits records, and drafts reports. When `X-User-Role` is `Tester`, `X-User-ID` is the `id` of the acting `Tester` entity; ownership checks on any resource that references a `Tester` — most importantly the `assigned_tester_id` on `TestTask` and the `tester_id` on `TestRecord` — compare the resource's foreign-key field to `X-User-ID`.
- A `Reviewer` performs second-level technical review. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `Reviewer` entity, used to populate `reviewer_id` on `Report` when review is approved.
- A `Signatory` provides the authorized electronic signature, issues the report to the client, and may recall it. When `X-User-Role` is `Signatory`, `X-User-ID` is the `id` of the acting `Signatory` entity; it is written to `signatory_id` on `Report` at signing time.
- A `LabManager` administers laboratory operations: clients, testers, reviewers, signatories, instruments, invoices, audit, and the test-driving capabilities. When `X-User-Role` is `LabManager`, `X-User-ID` is an opaque operator identifier, recorded on audit and modification entries but not compared to any entity's `id`.

Because of the entity-backed identity for `Tester`, `Reviewer`, and `Signatory`, certain read endpoints are scoped: a `Tester` reading `GET /testers/{id}` may only read their own row (the path id must equal `X-User-ID`). For all five roles the authoritative permission listing is the §4 endpoint table.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10; the minimum is 1 and the maximum is 100. The default `offset` is 0 and the minimum is 0. If a caller supplies a value outside these bounds, the request is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). Results are returned in ascending order by `created_at`. Each list response surfaces four pagination fields in the `meta` envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, plus a `created_at` timestamp. Most resources additionally carry an `updated_at` timestamp and an integer `version` that starts at 1 and is incremented by 1 on every mutation that changes a stored field. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits.

Two resource types are deliberately append-only and lack `updated_at` and `version`: `InstrumentBooking` and `DataModification` carry only `id` and `created_at`. (The booking row may transition through its own `status` enumeration, but its envelope fields are not re-versioned; revising a booking is performed by cancelling and creating a new one.) `AuditEvent` is also append-only and is identified internally by `subject_type` and `subject_id` rather than by an envelope-managed `version`.

All PATCH endpoints require the client to include the current `version` in the request body. If the supplied `version` does not equal the current row `version`, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Successful PATCH operations bump `version` by one and refresh `updated_at`. The `version` field is required on the PATCH endpoints that declare it (PATCH on `Client`, `Tester`, `Instrument`, and `TestRecord`); supplying a non-matching value is the only way to fail the concurrency check, and omitting the field on those endpoints is itself a malformed request rejected with `ERR_VALIDATION`.

### 2.5. Cascading State Changes and the Hierarchical Sample Lifecycle

The system enforces strict cascade semantics whenever a state change on a parent or shared resource invalidates an outstanding child. When an `Instrument` enters `CALIBRATION_DUE` because the logical clock has advanced past its `calibration_valid_to`, every future-dated `RESERVED` booking whose `slot_start` lies after the lapsed boundary is cancelled, and each affected `TestTask` returns from `ASSIGNED` to `PENDING_ASSIGNMENT`, and the prior tester's `active_task_count` is decremented by one. When an `Instrument` is taken `OUT_OF_SERVICE` by a manual failure report, every `RESERVED` booking whose `slot_end` is after the current moment is cancelled, and each affected task is bounced back to `PENDING_ASSIGNMENT` regardless of whether it was `ASSIGNED` or `IN_PROGRESS`. When a `Tester`'s qualification expires under a clock-advance sweep and `qualification_posture` flips to `LAPSED`, every `TestTask` currently `ASSIGNED` to that tester is auto-reverted to `PENDING_ASSIGNMENT`. When a single `TestTask` completes successfully, the linked `InstrumentBooking` transitions to `COMPLETED`, the instrument's `usage_minutes_total` accrues the booked duration, the tester's `active_task_count` decreases by one, and — if this completion was the last outstanding task under the parent `Sample` — the sample transitions from `IN_TESTING` to `TESTED`. Each cascade hop refreshes the touched resource's `updated_at` and increments its `version` (except for the version-less booking row).

### 2.6. Nested-Path Resolution

Many endpoints embed identifiers in the URL: `POST /samples/{id}/tasks`, `POST /instruments/{id}/bookings`, `GET /clients/{id}`, `POST /reports/{id}/sign`, and so on. Path segments are resolved strictly left-to-right; the first segment whose id does not match an existing resource yields `ERR_NOT_FOUND` (HTTP 404) without attempting to resolve later segments or body foreign keys. The same `ERR_NOT_FOUND` is returned when a foreign-key field in the request body — such as `sample_id`, `task_id`, `client_id`, `instrument_id`, `record_id`, `reviewer_id`, or `signatory_id` — references a resource that does not exist.

### 2.7. Validation Ordering

When multiple validations could apply to the same request, the server evaluates them in a fixed priority order so that the rejection a caller sees is the highest-priority root cause rather than a downstream symptom. First come the three auth checks already described: header presence (`ERR_AUTH_MISSING`), role-name validity (`ERR_AUTH_INVALID`), then per-endpoint RBAC (`ERR_FORBIDDEN`). Next, path-segment existence and body foreign-key existence (`ERR_NOT_FOUND`), followed by the target resource's status check against the requested state transition (`ERR_INVALID_STATE`). Business-safety checks come next, in this order: segregation of duties on report sign (`ERR_SEGREGATION_OF_DUTIES`), signatory scope match (`ERR_SIGNATORY_SCOPE_MISMATCH`), reviewer scope match (`ERR_REVIEWER_SCOPE_MISMATCH`), and the instrument-calibration validity check at report-issue time (`ERR_REPORT_BLOCKED_INSTRUMENT_LAPSED`). Then the business-referential rules: test-method to material-category coupling (`ERR_TEST_METHOD_NOT_SUPPORTED`) and witness-record consistency (`ERR_WITNESS_RECORD_INCONSISTENT`). Then the business-temporal pair on instrument booking: the calibration-window enclosure check (`ERR_BOOKING_OUTSIDE_CALIBRATION`) comes before the overlap-conflict check (`ERR_INSTRUMENT_SLOT_CONFLICT`). Then business-constraint rules in this order: tester workload cap (`ERR_TESTER_WORKLOAD_EXCEEDED`), qualified-tester availability (`ERR_NO_QUALIFIED_TESTER`), retest-limit cap (`ERR_RETEST_LIMIT_EXCEEDED`), invoice eligibility (`ERR_INVOICE_INELIGIBLE_TASKS`), deposit non-overdraw (`ERR_DEPOSIT_OVERDRAW`), modification-reason presence (`ERR_DATA_MODIFICATION_REASON_REQUIRED`), the optimistic-concurrency check (`ERR_VERSION_CONFLICT`), pagination-parameter bounds (`ERR_INVALID_PAGINATION`), and finally the generic body shape and enum check (`ERR_VALIDATION`).

### 2.8. Precision, Rounding, and Monetary Representation

All monetary fields are stored as integers in cents. Wherever a calculation requires rounding — surcharge derivation, refund derivation, package-discount derivation — the system rounds half up. Each pinned rounding step is taken individually before any aggregation: a line's `surcharge_cents` and `refund_cents` are each rounded to integer cents on their own line before line totals are summed, and the package discount is rounded once on the aggregate gross-of-deposit total. Numeric test results are rounded half up to one decimal place. Booking-driven instrument-usage accruals are rounded up to the next whole minute. The `usage_minutes_total` field on `Instrument` is therefore a strict ceiling: a slot one second longer than a whole minute counts as the next whole minute.

### 2.9. Half-Open Time Intervals

Time intervals used for instrument bookings follow the half-open `[slot_start, slot_end)` convention. Two bookings on the same instrument are considered to overlap if and only if their half-open intervals intersect. Two bookings that touch at exactly the same instant — where the new booking's `slot_start` equals an existing booking's `slot_end`, or the new booking's `slot_end` equals an existing booking's `slot_start` — do not overlap and may both exist. For boundary inclusivity on the calibration window: a booking whose `slot_end` equals `calibration_valid_to` is considered entirely within the window because the booking interval is half-open.

### 2.10. Test-Driving Clock and External Event Synchronisation

To support deterministic operation of time-dependent transitions, the API exposes an admin-only clock-advance capability that takes a target instant `to` and advances the logical clock to that instant, running all due sweeps in order: instrument calibration lapses (every `Instrument` whose `calibration_valid_to` precedes the new clock crosses to `CALIBRATION_DUE` with its cascade), qualification recomputation across all testers (with the `at_clock_advance` cascade variant), and the 30-day report archive sweep (every `Report` whose `issued_at` is at least 30 days before the new clock transitions to `ARCHIVED`). Separately, an event-injection capability takes an `event_type` and a `payload` and synchronises with three external systems: `PaymentReceived` credits a deposit or marks an `Invoice` as `PAID`; `AccreditationScopeChanged` updates the laboratory's internal accreditation allowed-categories snapshot; `ProjectStatusUpdate` is stored as a no-op snapshot for project-management integration.

## 3. Business Logic & Workflows

### 3.1. Client Registration and Financial Standing

A `LabClerk` does not create clients — that responsibility belongs to a `LabManager`, who registers a `Client` by providing a `name` and a `contact_email`. An optional `contract_id` may be supplied at creation or set later via a contact-update operation; when present, it qualifies the client for the contract-pricing variant of invoice calculation. The same update operation may revise `contact_email` and `contract_id`; both updates require the current `version` in the request body, and a mismatched value rejects the update with `ERR_VERSION_CONFLICT`.

Each `Client` carries two server-maintained money fields: `deposit_balance_cents` is the outstanding prepaid deposit the laboratory holds for the client, and `outstanding_balance_cents` is the net amount the client owes across all `ISSUED` unpaid invoices. Both default to zero on registration. The deposit balance is credited when the laboratory receives a `PaymentReceived` external event whose payload omits an invoice reference; the same event with an invoice reference instead marks the named `Invoice` as `PAID` once the supplied `amount_cents` equals the invoice's `total_due_cents`. When that match succeeds, the invoice's `paid_at` is set to the event timestamp and the client's `outstanding_balance_cents` is reduced by the invoice's `total_due_cents`.

### 3.2. Sample Registration, Identification, and Storage

The act of registering a sample is the lab's contract that this specific physical artefact will be tracked end-to-end. A `LabClerk` registers a `Sample` by supplying the owning `client_id`, the `source_project` it was taken from, the `material_category` enumeration value (one of `CONCRETE`, `STEEL_REBAR`, `SOIL`, `ASPHALT`, or `CEMENT`), a free-text `specification` such as "C30 cube 150mm" or "HRB400 D16", a boolean `witness_sampled` flag, an optional `witness_name`, and a `handover_record` object carrying three required keys: `delivered_by` (the person who handed the sample over), `received_by` (the clerk who took receipt), and `handover_at` (the ISO 8601 timestamp of the handover). If `witness_sampled` is true and `witness_name` is missing or empty, registration is rejected with `ERR_WITNESS_RECORD_INCONSISTENT`; symmetrically, if `witness_sampled` is false and a non-null `witness_name` is supplied, registration is rejected with the same error. The witness-record check is paired with witness consistency in both directions because both inconsistencies are equally damaging at audit time.

On successful registration the server mints two server-controlled identifiers and sets the sample's status to `REGISTERED`. The `sample_code` is the laboratory's human-readable identification code with the format `{MATERIAL3}-{YYYYMMDD}-{SEQ4}`, where `MATERIAL3` is the first three letters of the material category (`CON` for `CONCRETE`, `STE` for `STEEL_REBAR`, `SOI` for `SOIL`, `ASP` for `ASPHALT`, `CEM` for `CEMENT`), `YYYYMMDD` is the registration date in UTC, and `SEQ4` is a four-digit zero-padded sequence that restarts at `0001` each combination of (material category, UTC date). The `storage_location` is the allocated storage bin in the format `BIN-{material_category}-{NN}`. The `sample_code` is globally unique across the laboratory's lifetime. Both fields are computed at registration and are not user-supplied. The sample initially carries no test tasks; its lifecycle advances only when the first task is created against it (transitioning the sample to `IN_TESTING`). After all of its tasks finish and the resulting reports have been issued or archived, the sample can be disposed by a `LabClerk`, transitioning from `TESTED` to the terminal `DISPOSED` status; disposal is rejected with `ERR_INVALID_STATE` if any of the sample's reports is not yet in `ISSUED` or `ARCHIVED`.

### 3.3. Test-Task Configuration and Method-Category Coupling

A `LabClerk` creates a `TestTask` under a registered sample by supplying the `test_method` enumeration value and the optional `urgent` boolean (default false). Each test method is coupled to exactly one material category: `COMPRESSION_STRENGTH` may only be performed on `CONCRETE` samples, `TENSILE_STRENGTH` on `STEEL_REBAR`, `COMPACTION_DENSITY` on `SOIL`, `MARSHALL_STABILITY` on `ASPHALT`, and `SETTING_TIME` on `CEMENT`. If the supplied `test_method` does not match the sample's `material_category` under this coupling, task creation is rejected with `ERR_TEST_METHOD_NOT_SUPPORTED`. Once accepted, the task starts in the `PENDING_ASSIGNMENT` state, and the server mints a `priority_seq` that ranks urgent tasks ahead of non-urgent ones; within the same urgency bucket, earlier `created_at` ranks first. The first successful task creation under a sample also advances the parent sample from `REGISTERED` to `IN_TESTING`.

Task creation synchronously invokes the tester-assignment selector. The selector enumerates every `Tester` whose `qualification_posture` is `QUALIFIED` or `EXPIRING_SOON` and whose `qualifications` contain at least one entry whose `material_category` matches the task's sample's `material_category` with `valid_from` on or before today's UTC date and `valid_to` on or after today's UTC date — testers whose `qualification_posture` is `LAPSED` are excluded. Among the eligible testers the selector additionally requires `active_task_count` strictly less than `max_concurrent_tasks`; if no tester satisfies this combined filter, no assignment is made and the task remains `PENDING_ASSIGNMENT`, awaiting either an explicit re-attempt by a `LabManager` or the next clock-advance retry. If the eligible-and-available set is empty for the qualification-and-posture reason (i.e. no tester is qualified at all), explicit assignment attempts on this task are rejected with `ERR_NO_QUALIFIED_TESTER`. If qualified testers exist but every one of them is at the workload cap, the assignment is rejected with `ERR_TESTER_WORKLOAD_EXCEEDED`. The boundary on the workload check is strict in one direction: a tester with `active_task_count` exactly one below `max_concurrent_tasks` may still be selected (the post-assignment count equals the cap), but a tester at the cap cannot.

Among eligible-and-available testers, the selector ranks first by `active_task_count` ascending (workload balancing), then by `created_at` ascending, then by `id` ascending; the first tester in this ordering is chosen. The chosen tester's `assigned_tester_id` is written onto the task, the tester's `active_task_count` is incremented by one, and the task transitions from `PENDING_ASSIGNMENT` to `ASSIGNED`. Urgent and non-urgent task creation share the same selector body — the difference is purely the `priority_seq` ranking, which interleaves the two streams so that an urgent task created at the same instant as a non-urgent one is processed first; non-urgent tasks defer to any concurrent urgent tasks needing assignment.

Once a task is `ASSIGNED`, two further administrative operations are available to a `LabManager`. Reassignment forces the task back to `PENDING_ASSIGNMENT` and releases the resources — the previous tester's `active_task_count` is decremented, the task's `assigned_tester_id` is cleared, and any linked `InstrumentBooking` is cancelled. The same reversion fires automatically under a clock-advance sweep when the assigned tester's `qualification_posture` flips to `LAPSED`. Cancellation moves the task from `ASSIGNED` directly to `CANCELLED` provided no `TestRecord` has yet been submitted; on cancellation the tester's `active_task_count` is decremented and any linked booking transitions to `CANCELLED`.

### 3.4. Instrument Ledger, Calibration, and Booking

Each piece of testing equipment is registered to the instrument ledger with a lab-internal `asset_code` (unique across all instruments), a `capabilities` array listing the test methods it can perform, and a calibration window bounded by `calibration_valid_from` (inclusive start) and `calibration_valid_to` (inclusive end). The instrument starts in the `AVAILABLE` status with `usage_minutes_total` at zero.

A `LabClerk` or a `Tester` reserves an instrument slot for a task by submitting a booking with `task_id`, `slot_start`, and `slot_end`. The booking's interval must satisfy two conditions: `slot_start` must be strictly before `slot_end`, and the half-open interval `[slot_start, slot_end)` must be entirely within the instrument's calibration window `[calibration_valid_from, calibration_valid_to]`. A booking whose `slot_end` exactly equals `calibration_valid_to` is allowed because the booking interval is half-open and does not actually consume the boundary instant. Violations of either calibration-window condition reject the booking with `ERR_BOOKING_OUTSIDE_CALIBRATION`. Independently, the new interval must not intersect any existing booking on the same instrument whose status is `RESERVED` or `COMPLETED`; two bookings that touch at exactly `slot_end == other.slot_start` do not intersect and both may be created. An overlap rejects the new booking with `ERR_INSTRUMENT_SLOT_CONFLICT`. When two callers submit simultaneous bookings whose intervals would overlap, the system serialises first-writer-wins on the (instrument, overlapping-interval) pair: exactly one booking succeeds, and the loser receives `ERR_INSTRUMENT_SLOT_CONFLICT`. A successful booking creates a row in the `RESERVED` status and writes its id back to the task as `instrument_booking_id`.

An instrument may be taken `OUT_OF_SERVICE` by a manual failure report from a `LabManager`. The transition cascades: every `RESERVED` booking on the instrument with a `slot_end` strictly after the current instant is cancelled, and each affected task drops back to `PENDING_ASSIGNMENT` whether it was `ASSIGNED` or `IN_PROGRESS` at the time. Returning to service moves the instrument back to `AVAILABLE` without re-booking the lost slots. When recalibration is complete, a `LabManager` may update `calibration_valid_from` and `calibration_valid_to` to cover the present instant; if the previous status was `CALIBRATION_DUE` and the new window encloses now, the status transitions to `AVAILABLE`. The same update endpoint can revise `capabilities`. All such updates require the current `version`. Retiring an instrument is permitted only when no `RESERVED` booking references it; the instrument is marked `RETIRED` and the request returns HTTP 204 with no body.

### 3.5. Tester, Reviewer, and Signatory Roster

A `LabManager` creates a `Tester` by supplying `full_name`, a `qualifications` array, and an optional `max_concurrent_tasks` cap (default 5). Each entry in `qualifications` is an object with three keys: `material_category` (the category the tester is qualified for), `valid_from` (the date the qualification becomes effective), and `valid_to` (the date the qualification expires, inclusive). The server computes `active_task_count` (which counts test tasks where `assigned_tester_id` equals this tester's `id` and `status` is one of `ASSIGNED`, `IN_PROGRESS`, or `AWAITING_RETEST`), and `qualification_posture` (an enumeration of `QUALIFIED`, `EXPIRING_SOON`, or `LAPSED`).

The `qualification_posture` is reconciled on every qualification mutation and on every clock-advance, by the following deterministic procedure. Today's UTC date is established as the reference. The set of qualifications currently in effect is the subset of entries whose `valid_from` is on or before today and whose `valid_to` is on or after today. Among those in-effect qualifications, the expiring-soon subset is the entries whose `valid_to` minus today is at most 30 days — a qualification with exactly 30 days remaining counts as expiring soon. If the in-effect set is empty, the posture is `LAPSED`. Otherwise, if the expiring-soon subset is non-empty, the posture is `EXPIRING_SOON`. Otherwise, the posture is `QUALIFIED`. The mutation-triggered reconciliation only updates the tester's own row; the clock-advance reconciliation additionally cascades when a tester flips to `LAPSED` — every `ASSIGNED` `TestTask` belonging to that tester is auto-reverted to `PENDING_ASSIGNMENT`, with the tester's `active_task_count` decremented and `assigned_tester_id` cleared on each reverted task.

A `Reviewer` is created with `full_name` and `scope_categories` (an array of material-category values the reviewer may review). A `Signatory` is created with `full_name`, a `signature_certificate_id` referencing the electronic-signature certificate to be embedded in issued reports, and `scope_categories` (an array of material-category values within the signatory's authorization scope).

### 3.6. Test Execution and Data Capture

Once a task is `ASSIGNED`, the assigned `Tester` advances it to `IN_PROGRESS` by starting work. Starting work requires four conditions in addition to the standard auth checks: the caller's `X-User-ID` must equal the task's `assigned_tester_id`; the task's `instrument_booking_id` must be non-null; the referenced `InstrumentBooking` must be in the `RESERVED` status; and the referenced `Instrument` must be in the `AVAILABLE` status. Any condition unmet rejects the start with `ERR_INVALID_STATE`.

During testing the tester submits one or more `TestRecord` rows. Each record carries the `task_id`, the `tester_id` (which must equal the task's `assigned_tester_id`), a `raw_data` object holding the instrument-output blob as delivered (peak load in kilonewtons, accompanying readings, etc., shaped by the test method), an optional `supersedes_record_id` linking the record to the abnormal record it replaces during a retest, and on submission gets a server-computed `calculated_result`, an `abnormal_flag` boolean, and a `status` that starts at `DRAFT` and auto-advances to `SUBMITTED`. The `raw_data` is stored verbatim and is never overwritten; correcting an instrument-output value is performed through the data-modification log rather than by replacing the raw field.

The `calculated_result` is derived from `raw_data` together with the parent sample's `specification`, by a method-specific formula. For `COMPRESSION_STRENGTH`, the area of the test cross-section is parsed from the specification string (for example "C30 cube 150mm" yields 150 multiplied by 150 equal to 22500 square millimetres), and the result in megapascals is the peak load in kilonewtons multiplied by one thousand and then divided by that area in square millimetres, with the final value rounded half up to one decimal place. For `TENSILE_STRENGTH`, the result in megapascals is the peak load in kilonewtons multiplied by one thousand and divided by the cross-sectional area derived from the rebar specification, rounded half up to one decimal place. The other three methods follow analogous per-method shapes against their own raw-data keys and specification-derived parameters, each producing a numeric result rounded half up to one decimal place.

Each method has a two-sided expected band: the lower bound for `COMPRESSION_STRENGTH` is 20.0 and the upper bound is 60.0; for `TENSILE_STRENGTH` the band is 400.0 to 600.0; for `COMPACTION_DENSITY` it is 1.9 to 2.6; for `MARSHALL_STABILITY` it is 7.5 to 18.0; and for `SETTING_TIME` it is 45.0 to 600.0. The `abnormal_flag` is true if and only if the `calculated_result` is strictly less than the lower bound for the method or strictly greater than the upper bound; a result exactly equal to the lower bound is not abnormal, and a result exactly equal to the upper bound is not abnormal — boundaries are inclusive on the in-band side.

### 3.7. Retest Workflow and Single-Retest Cap

When a tester submits the first `TestRecord` on a task and the `abnormal_flag` is true while the task's `retest_count` is still zero, the system triggers the retest workflow: the task transitions from `IN_PROGRESS` to `AWAITING_RETEST`, and the parent sample transitions from `IN_TESTING` to `RETESTING` (these two cascades together let querying parties see at a glance that the sample is mid-revision). The retest itself is begun by submitting a second `TestRecord` whose `supersedes_record_id` references the abnormal record; the task transitions from `AWAITING_RETEST` back to `IN_PROGRESS`, the `retest_count` is incremented from zero to one, and the previous `SUBMITTED` record transitions from `SUBMITTED` to `SUPERSEDED` (but remains queryable for traceability).

The cap is strict: at most one retest per task. A second retest attempt — that is, a submission whose `supersedes_record_id` is present while the task's `retest_count` is already one — is rejected with `ERR_RETEST_LIMIT_EXCEEDED`. If the retest's new record is itself abnormal, the workflow is not re-triggered: the record is recorded, the task remains in `IN_PROGRESS`, and the test concludes either by a subsequent non-abnormal record or by explicit completion. Subsequent abnormal records on the same task after the cap is reached do not move the task back to `AWAITING_RETEST`, and they do not move the sample back to `RETESTING`.

Task completion fires only when exactly one `TestRecord` on the task is in `SUBMITTED` status with `abnormal_flag` false; the completion cascade moves the task to `COMPLETED`, decrements the tester's `active_task_count`, transitions the linked `InstrumentBooking` to `COMPLETED`, accrues the booking's duration to the instrument's `usage_minutes_total` (rounded up to the next whole minute), and — if this completion is the last outstanding task on the parent sample — advances the sample from `IN_TESTING` to `TESTED`. Should a tester finalise a record while a `LabManager` simultaneously cancels the task, exactly one operation wins; the loser is rejected with `ERR_INVALID_STATE`.

### 3.8. Data Modification Log and Audit Trail

Sometimes a tester needs to revise the raw-data blob on a `SUBMITTED` record — a transcription error, an instrument-channel mislabel, a unit slip. The modification operation accepts a partial `raw_data` patch alongside a free-text `reason` and the current `version`. The `reason` MUST be non-empty; an empty or absent reason rejects the modification with `ERR_DATA_MODIFICATION_REASON_REQUIRED`. For each field actually changed, the server appends an immutable `DataModification` row recording the `record_id`, the modifying user's role (`actor_role`) and identifier (`actor_id`, captured from `X-User-Role` and `X-User-ID`), the `field_path` of the modified key in dot notation (for instance `raw_data.peak_load_kn` or `calculated_result`), the `previous_value` and `new_value` (both stored as JSON-serialised strings), and the supplied `reason`. The `calculated_result` and `abnormal_flag` are recomputed against the new `raw_data` and the original `specification`, and a `DATA_MODIFIED` `AuditEvent` is emitted with the record as subject.

All audit-relevant events flow into the `AuditEvent` table, identified by `event_type`, `subject_type`, `subject_id`, `actor_role`, `actor_id`, and an event-specific `payload` object. The taxonomy is `REPORT_ISSUED`, `REPORT_RECALLED`, `DATA_MODIFIED`, `EXTERNAL_INSPECTION_RESPONDED`, `INTERNAL_AUDIT_RUN`, `QUALIFICATION_LAPSED`, and `INSTRUMENT_CALIBRATION_LAPSED`. Where a clock-advance sweep triggers an event, `actor_role` and `actor_id` are both recorded as `system`. A `LabManager` may run an internal-audit sweep that emits a single `INTERNAL_AUDIT_RUN` event carrying a snapshot of stats in its payload; this operation is idempotent within the same UTC date, meaning a second call on the same date does not emit a duplicate event. A `LabManager` may also record an external-inspection response by supplying an `inspection_id` and a `response_note`, which emits an `EXTERNAL_INSPECTION_RESPONDED` event.

### 3.9. Report Drafting, Multi-Level Review, and Issuance

When a `TestTask` reaches `COMPLETED`, the assigned `Tester` mints a `Report` for it; exactly one report exists per task. The report is created in the `DRAFTED` status with `version` 1 and a `template_code` chosen by the test method (for example `TPL-COMPRESSION-V2`). Submitting the draft for review moves the report from `DRAFTED` to `UNDER_REVIEW`. The acting tester must equal the underlying task's `assigned_tester_id`.

In the review stage a `Reviewer` whose `scope_categories` contains the sample's `material_category` either approves the review or sends it back. Approving the review sets `reviewer_id` to the acting reviewer's id but keeps the report in `UNDER_REVIEW` — the report does not advance to `SIGNED` until a signatory acts. Sending back returns the report from `UNDER_REVIEW` to `DRAFTED`, bumps `version` by one (this is the cyclic revision loop), and clears `reviewer_id`. If the reviewer's `scope_categories` does not contain the sample's `material_category`, both reviewer operations are rejected with `ERR_REVIEWER_SCOPE_MISMATCH`. Two reviewers acting concurrently — one sending back, one (via signatory) signing — serialise first-writer-wins on the report's status; the loser sees `ERR_INVALID_STATE` because the report's status no longer matches the expected from-state.

The signatory's role is the final technical authorisation. Signing transitions the report from `UNDER_REVIEW` to `SIGNED`, sets `signatory_id` to the acting signatory, and populates `signature_payload` with the embedded electronic signature (a Base64 payload derived from the signatory's `signature_certificate_id`). Three preconditions guard signing: the reviewer must have approved (`reviewer_id` is non-null); the signatory's `scope_categories` must contain the sample's `material_category` (otherwise `ERR_SIGNATORY_SCOPE_MISMATCH`); and the signatory must be a different person from both the reviewer and the tester who authored the underlying `TestRecord` (otherwise `ERR_SEGREGATION_OF_DUTIES`). The two scope checks and the segregation check are enforced in the order described in §2.7: segregation of duties fires before the signatory scope check, which fires before the reviewer scope check.

Issuing the report moves it from `SIGNED` to `ISSUED`, sets `issued_at` to the current instant, and emits a `REPORT_ISSUED` `AuditEvent` whose payload carries the report's `version`. Issuance has two additional preconditions on top of state and signature presence: an `Invoice` for the underlying task must exist in either `ISSUED` or `PAID` status (the business pre-condition: the client must have been billed before the report leaves the building), and for every non-superseded `TestRecord` under the report's task, the corresponding `Instrument`'s `calibration_valid_to` must be on or after the record's `created_at` — that is, the instrument used to produce the data must have been within calibration at the time the data was captured. If any record under the report fails this calibration check, issuance is rejected with `ERR_REPORT_BLOCKED_INSTRUMENT_LAPSED`.

A `Signatory` may recall an issued report before the 30-day archive window closes; recall returns the report from `ISSUED` to `RECALLED`, clears the `signature_payload`, and emits a `REPORT_RECALLED` audit event. A `LabManager` may reopen a recalled report, returning it from `RECALLED` back to `DRAFTED` and bumping `version` by one. If no recall happens within 30 days of `issued_at`, the clock-advance sweep auto-transitions the report to `ARCHIVED` (terminal). The boundary is inclusive on the archive side: when the logical clock is at or beyond `issued_at` plus 30 days, the sweep moves the report to `ARCHIVED`; before that instant a recall is still permitted.

### 3.10. Invoicing, Surcharges, Refunds, and Package Pricing

A `LabManager` issues an `Invoice` for a list of completed tasks belonging to one client by submitting a `task_ids` payload. Every task in the supplied list must belong to the named client, must be in `COMPLETED` status, and must not have appeared in any previously-issued invoice's `line_items`; if any task fails any of these conditions the issuance is rejected with `ERR_INVOICE_INELIGIBLE_TASKS`. The invoice carries `client_id`, a computed `line_items` array, four computed aggregate amounts (`subtotal_cents`, `surcharge_total_cents`, `refund_total_cents`, `package_discount_cents`), the computed `deposit_applied_cents`, and the final computed `total_due_cents`.

Pricing is computed in pinned steps. First, per line: each `task_id` becomes a `line_items` entry with three fields. The `base_fee_cents` is read from the per-method price table — 20000 cents for `COMPRESSION_STRENGTH`, 25000 cents for `TENSILE_STRENGTH`, 18000 cents for `COMPACTION_DENSITY`, 30000 cents for `MARSHALL_STABILITY`, and 15000 cents for `SETTING_TIME`. The `surcharge_cents` is the `base_fee_cents` multiplied by the urgent-handling surcharge rate of fifty percent and rounded half up to the nearest cent if the task's `urgent` flag is true; otherwise it is zero. The `refund_cents` is the `base_fee_cents` multiplied by the failed-retest refund rate of thirty percent and rounded half up to the nearest cent if and only if the task's `retest_count` is one and the final non-superseded `TestRecord` on the task still has `abnormal_flag` true; otherwise it is zero. The per-line surcharge and refund are each rounded individually to integer cents before any aggregation.

Second, the aggregate is built: `subtotal_cents` is the sum of all `line_items[].base_fee_cents`; `surcharge_total_cents` is the sum of all `line_items[].surcharge_cents`; `refund_total_cents` is the sum of all `line_items[].refund_cents`. A gross-of-deposit amount is then computed as `subtotal_cents` plus `surcharge_total_cents` minus `refund_total_cents`.

Third, the package discount is evaluated on the gross-of-deposit amount, before any deposit deduction. If the number of entries in `line_items` is at least 5, or if the client's `contract_id` is non-null (the contract-pricing variant, where the line-count gate is skipped), the `package_discount_cents` is the gross-of-deposit amount multiplied by ten percent, rounded half up to the nearest cent. Otherwise `package_discount_cents` is zero. The pre-deposit total is the gross-of-deposit amount minus the package discount.

Fourth, the deposit is applied: `deposit_applied_cents` is the lesser of the client's current `deposit_balance_cents` and the pre-deposit total; the computed value never exceeds the available deposit (the invariant is enforced as a final safety net by `ERR_DEPOSIT_OVERDRAW` should any arithmetic anomaly cause overdraw). The `total_due_cents` is the pre-deposit total minus `deposit_applied_cents`.

Fifth, the side effects fire: the client's `deposit_balance_cents` is decreased by `deposit_applied_cents`, and the client's `outstanding_balance_cents` is increased by `total_due_cents`. The invoice is created in the `ISSUED` status.

An unpaid invoice may be voided by a `LabManager`, but only if no `Report` referencing any task in this invoice's `line_items` is in `ISSUED` or `ARCHIVED` status — once the technical report has been issued, the invoice it billed against cannot be voided. Voiding moves the invoice from `ISSUED` to `VOIDED`, restores the previously-debited deposit (the client's `deposit_balance_cents` is increased by `deposit_applied_cents`) and reduces the client's `outstanding_balance_cents` by `total_due_cents`. A `PaymentReceived` external event whose `amount_cents` exactly equals the invoice's `total_due_cents` flips the invoice from `ISSUED` to `PAID`, sets `paid_at` to the event timestamp, and reduces the client's `outstanding_balance_cents`.

### 3.11. Concurrency Serialisation Points

Beyond the OCC-based protection on PATCH operations and the booking-overlap serialisation already discussed, three additional racing scenarios deserve named serialisation guarantees so that callers can predict the loser's error. When two assignment attempts target the last available qualified `Tester` whose `active_task_count` equals `max_concurrent_tasks` minus one, exactly one assignment succeeds; the loser receives `ERR_TESTER_WORKLOAD_EXCEEDED` and the loser's task remains `PENDING_ASSIGNMENT`. When a tester submits the final record on a task while a `LabManager` simultaneously cancels the same task, exactly one operation wins on the task's status; the loser is rejected with `ERR_INVALID_STATE`. When two concurrent client-update requests by a `LabManager` carry the same `version` value and both attempt to modify `contact_email` on the same `Client`, exactly one update succeeds and the second observes a stale version, returning `ERR_VERSION_CONFLICT`. In all of these races the system commits to first-writer-wins on the resource field involved (`Tester.active_task_count`, `TestTask.status`, `Client.version`).

### 3.12. Listing, Filtering, and Read Access

The list endpoints carry typed query filters in addition to `limit` and `offset`. Tester listing supports filtering by `posture` and by `material_category`. Sample listing supports filtering by `client_id`, by `status`, and by `material_category`. Instrument booking listing accepts a `from` and `to` window. The audit-event listing accepts `event_type`, `subject_type`, and `subject_id`. Read endpoints on individual resources return the full current row including all computed fields (`usage_minutes_total` on `Instrument`, `active_task_count` and `qualification_posture` on `Tester`, the four aggregate cents fields on `Invoice`, the embedded `signature_payload` on a `SIGNED` or `ISSUED` `Report`, and so on). List endpoints are ordered ascending by `created_at` as stated in §2.3.

## 4. Endpoint Definitions

Newly created resources are returned with HTTP 201; all other successful operations (state transitions, updates, reads) return HTTP 200, except for the explicit deletion endpoints, which return HTTP 204 with no body. All endpoints follow the response envelope of §2.2 and the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clients` | Register a client | LabManager |
| GET | `/clients/{id}` | Read a client | LabManager, LabClerk |
| PATCH | `/clients/{id}` | Update client contact info (OCC) | LabManager |
| POST | `/testers` | Create a tester | LabManager |
| GET | `/testers/{id}` | Read a tester (self-only for Tester role) | LabManager, LabClerk, Tester |
| PATCH | `/testers/{id}` | Update qualifications or workload cap | LabManager |
| GET | `/testers` | List testers with optional filters | LabManager |
| POST | `/reviewers` | Create a reviewer | LabManager |
| POST | `/signatories` | Create a signatory | LabManager |
| POST | `/instruments` | Add an instrument to the ledger | LabManager |
| GET | `/instruments/{id}` | Read an instrument | LabManager, LabClerk, Tester |
| PATCH | `/instruments/{id}` | Update calibration window or capabilities | LabManager |
| POST | `/instruments/{id}/report-failure` | Mark instrument out of service; cascade-cancel future bookings | LabManager |
| POST | `/instruments/{id}/return-to-service` | Return instrument to available | LabManager |
| DELETE | `/instruments/{id}` | Retire an instrument | LabManager |
| POST | `/instruments/{id}/bookings` | Reserve an instrument slot for a task | LabClerk, Tester |
| GET | `/instruments/{id}/bookings` | List bookings for an instrument | LabManager, LabClerk |
| POST | `/samples` | Register a sample (mints sample_code and storage_location) | LabClerk |
| GET | `/samples/{id}` | Read a sample | LabManager, LabClerk, Tester |
| GET | `/samples` | List samples | LabManager, LabClerk |
| DELETE | `/samples/{id}` | Dispose a sample | LabClerk |
| POST | `/samples/{id}/tasks` | Create a test task under a sample | LabClerk |
| GET | `/tasks/{id}` | Read a test task | LabManager, LabClerk, Tester |
| POST | `/tasks/{id}/assign` | Manually trigger tester assignment | LabManager |
| POST | `/tasks/{id}/reassign` | Force the task back to pending assignment | LabManager |
| POST | `/tasks/{id}/start` | Tester begins work | Tester |
| POST | `/tasks/{id}/complete` | Tester marks the task complete | Tester |
| POST | `/tasks/{id}/cancel` | Cancel a task before any record is submitted | LabManager |
| POST | `/tasks/{id}/records` | Submit a test record | Tester |
| GET | `/tasks/{id}/records` | List records for a task (including superseded rows) | LabManager, LabClerk, Tester, Reviewer, Signatory |
| PATCH | `/records/{id}` | Modify raw data on a submitted record (appends a modification entry) | Tester |
| GET | `/records/{id}/modifications` | List modification entries for a record | LabManager, Reviewer, Signatory |
| POST | `/tasks/{id}/report` | Mint a report for a completed task | Tester |
| POST | `/reports/{id}/submit-for-review` | Move report from drafted to under review | Tester |
| POST | `/reports/{id}/approve-review` | Reviewer signs off on review (stays under review) | Reviewer |
| POST | `/reports/{id}/send-back` | Reviewer rejects with revision (under review back to drafted; version increment) | Reviewer |
| POST | `/reports/{id}/sign` | Signatory signs the report | Signatory |
| POST | `/reports/{id}/issue` | Issue the report to the client | Signatory |
| POST | `/reports/{id}/recall` | Recall an issued report before archival | Signatory |
| POST | `/reports/{id}/reopen` | Reopen a recalled report (recalled back to drafted; version increment) | LabManager |
| GET | `/reports/{id}` | Read a report | LabManager, LabClerk, Reviewer, Signatory, Tester |
| POST | `/clients/{id}/invoices` | Issue an invoice for a list of completed tasks | LabManager |
| POST | `/invoices/{id}/void` | Void an unpaid invoice | LabManager |
| GET | `/invoices/{id}` | Read an invoice | LabManager, LabClerk |
| GET | `/audit-events` | Query the audit log | LabManager |
| POST | `/_audit/run-internal` | Trigger the periodic internal-audit sweep (idempotent per UTC date) | LabManager |
| POST | `/_audit/respond-external` | Record an external-inspection response | LabManager |
| POST | `/_clock/advance` | Advance the logical clock to a supplied `to` instant; runs all due sweeps | LabManager |
| POST | `/_events/emit` | Inject an external synchronisation event | LabManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_AUTH_INVALID` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_INSTRUMENT_SLOT_CONFLICT` | 409 |
| `ERR_TESTER_WORKLOAD_EXCEEDED` | 409 |
| `ERR_BOOKING_OUTSIDE_CALIBRATION` | 422 |
| `ERR_NO_QUALIFIED_TESTER` | 422 |
| `ERR_TEST_METHOD_NOT_SUPPORTED` | 422 |
| `ERR_WITNESS_RECORD_INCONSISTENT` | 422 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_REVIEWER_SCOPE_MISMATCH` | 422 |
| `ERR_SIGNATORY_SCOPE_MISMATCH` | 422 |
| `ERR_REPORT_BLOCKED_INSTRUMENT_LAPSED` | 422 |
| `ERR_INVOICE_INELIGIBLE_TASKS` | 422 |
| `ERR_DEPOSIT_OVERDRAW` | 422 |
| `ERR_DATA_MODIFICATION_REASON_REQUIRED` | 422 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_VALIDATION` | 422 |
