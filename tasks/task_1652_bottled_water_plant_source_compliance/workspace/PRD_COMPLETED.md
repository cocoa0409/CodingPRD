# Bottled Water Compliance API — Product Requirements Document

## 1. Introduction

A bottled water plant operates at the intersection of environmental regulation, food-safety law, and consumer trust. Every gallon withdrawn from a spring, well, or municipal connection is capped by a regulator-issued permit; every treatment run must prove its disinfection parameters before a single bottle may be filled; every label claiming "spring water" must be traceable to a genuinely spring-classified source; and every returnable bottle circulating through homes and offices must pass a validated sanitation loop before it can be refilled. When something goes wrong — a failed raw-water test, an overdue lab sample, a contaminated lot — the plant must freeze distribution, trace affected bottles by lot, recover them, and account publicly for the water it has taken from the community.

This document specifies the Bottled Water Compliance API, the system of record for that operational reality. It governs source permits and metered withdrawals, the treatment train and its quality-assurance validation, laboratory testing cadence across source, product, and sanitation samples, preform supply and the bottling-line inventory ledger, production lots and their release gates, recalls with unit-level recovery tracking, the returnable-bottle wash loop, and the monthly community water-use report. All resources are mounted under `/api`. Because compliance evaluation is inherently date-driven — caps key on calendar days and months, tests become due and overdue, permits expire — every temporal rule reads a single server-side logical clock (§2.4) rather than wall-clock time, so the plant's compliance posture is deterministic and auditable at any instant.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly six roles: `PlantAdmin`, `SourceMonitor`, `QAOfficer`, `ProductionLead`, `SanitationLead`, and `ComplianceOfficer`. A request with a missing header, or an `X-User-Role` value outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role ownership divides along segregation-of-duties lines. `PlantAdmin` owns plant and line configuration, the logical clock, test-driving injections, and the daily compliance run. `SourceMonitor` records and voids withdrawal events. `QAOfficer` validates treatment runs, schedules and results lab tests, renders QC verdicts on preform deliveries, and rejects lots. `ProductionLead` schedules and operates treatment runs, registers preform deliveries, creates and runs production lots, and fills bottles. `SanitationLead` owns the returnable-bottle loop and wash batches. `ComplianceOfficer` owns the permit lifecycle, recalls, and community water reports. All list and read endpoints are shared by every role.

For each of the six roles — `PlantAdmin`, `SourceMonitor`, `QAOfficer`, `ProductionLead`, `SanitationLead`, and `ComplianceOfficer` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources where accountability matters (for example, as `parameters_recorded_by_user_id` and `validated_by_user_id` on a treatment run, or as `completed_by_user_id` and `released_by_user_id` on a production lot) but never compares it to any entity's `id`. Segregation-of-duties checks compare the recorded operator identifiers to each other, not to resource identifiers (§2.10).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the wall clock rather than the logical clock of §2.4 (the logical clock governs business-date evaluation and the resource timestamps of §2.5, not envelope metadata).
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. An unparseable `limit` or `offset` falls back to its default, and an out-of-range value is clamped to the nearest bound rather than rejected. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; because the logical clock makes `created_at` ties common, ties fall back to creation order — a tie-break that applies wherever the system orders by `created_at`, including the per-source breakdown of §3.9. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. The Logical Clock

All date and time evaluation in the system — cap windows, due dates, permit expiry, withdrawal finalization, overdue detection — reads a single server-side logical clock, never the wall clock. A test-driving capability, restricted to `PlantAdmin`, sets the logical clock to a supplied instant: the request carries `to_iso8601` and the response echoes the new value as `current_utc`. Before any such call, the logical clock defaults to exactly 2026-08-01T00:00:00Z. The logical clock never falls back to wall-clock time; if it has never been set, every date comparison uses the startup default. Calendar-day comparisons (caps, due-date flips, expiry) are whole-day comparisons against the logical date.

A second test-driving capability, also restricted to `PlantAdmin`, writes a returnable bottle's `wash_cycle_count` directly from a payload of `bottle_id` and `wash_cycle_count`, so that the 150-wash lifecycle ceiling can be exercised without iterating the wash loop. The injection rejects an unknown `bottle_id` with `ERR_NOT_FOUND` (HTTP 404) and a negative or non-integer `wash_cycle_count` with `ERR_INVALID_REQUEST` (HTTP 400); any non-negative integer is accepted, and the response returns the updated bottle. No business endpoint may set `wash_cycle_count`; it changes only through passed wash batches (§3.8) or this injection.

### 2.5. Common Resource Properties

Every resource in the system — Plant, WaterSourcePermit, WithdrawalEvent, TreatmentRun, LabTest, BottlingLine, PreformDelivery, ProductionLot, RecallEvent, ReturnableBottle, WashBatch, and CommunityWaterReport — carries four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource. Both `created_at` and `updated_at` are stamped from the logical clock of §2.4, never from wall-clock time; while the logical clock is frozen, a change therefore re-stamps the identical `updated_at` value, and the `version` increment is the observable signal of the mutation. The `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascades and recomputes described in §2.6.

### 2.6. Hierarchical Consistency and Cascading Side Effects

A plant aggregates everything beneath it, and the system maintains hierarchical consistency synchronously: when one operation mutates several resources, every affected resource is updated in the same request, each hop refreshing the target's `updated_at` and incrementing its `version`. Suspension of a permit cancels its scheduled treatment runs and forces a recomputation of the plant's compliance posture; completing a lot moves preform units through the line ledger and spawns a lab test; passing a wash batch sanitizes its bottles and spawns a sanitation test; initiating a recall recalls its lots and quarantines their bottles. Wherever §3 says a parent's aggregates, ledger fields, pool counters, or posture are "recomputed", that recomputation is itself a mutation of the parent resource with the usual `updated_at` and `version` consequences. A recomputation that leaves the derived value unchanged is not a mutation: it refreshes neither `updated_at` nor `version`. The server performs these cascades without requiring a separate client call on the affected resources.

### 2.7. Nested Resource Retrieval and Validation Ordering

For any endpoint whose path contains nested identifiers (for example, a withdrawal event created beneath a permit beneath a plant), the existence of each path identifier is validated strictly left to right; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no further checks run. Body-supplied foreign keys — `lot_id`, `bottle_ids`, `lot_ids`, `treatment_run_id`, `source_permit_id`, the `subject_permit_id` / `subject_lot_id` / `subject_wash_batch_id` family, and `supersedes_event_id` — are likewise validated for existence at this stage.

Beyond existence, every request is evaluated against a fixed priority ladder, so that a request failing several checks always surfaces the earliest one:

1. **Authentication** — the headers rule of §2.1 (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role rule of §2.1 (`ERR_FORBIDDEN`).
3. **Existence** — path identifiers left to right, then body foreign keys (`ERR_NOT_FOUND`).
4. **Optimistic concurrency** — on the three version-guarded writes of §2.8, the expected-version precondition is checked immediately after existence and before all other state and business checks (`ERR_STALE_PERMIT_VERSION` or `ERR_STALE_LINE_VERSION`).
5. **State admissibility** — the target resource must be in a state that admits the operation, per the state machines of §3 (`ERR_INVALID_STATE`; `ERR_PERMIT_NOT_ACTIVE` for permit-gated writes; `ERR_EVENT_ALREADY_FINALIZED` for voiding a finalized event).
6. **Safety and compliance gates**, evaluated in this fixed sub-order: `ERR_SEGREGATION_OF_DUTIES`, then `ERR_TREATMENT_NOT_VALIDATED`, then `ERR_PRODUCT_TEST_NOT_PASSED`, then `ERR_SANITATION_TEST_PENDING`, then `ERR_LABEL_CLASSIFICATION_MISMATCH`, then `ERR_POSTURE_BREACH`, then `ERR_REINSTATE_BLOCKED`.
7. **Temporal rules** — `ERR_LINE_WINDOW_CONFLICT`, `ERR_WASHER_WINDOW_CONFLICT`, `ERR_WASHER_PURGE_BUFFER`, `ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW`, `ERR_FUTURE_WITHDRAWAL_DATE`, and `ERR_REPORT_PERIOD_LOCKED`.
8. **Cross-reference integrity**, evaluated in this fixed sub-order: `ERR_CROSS_PLANT_REFERENCE`, then `ERR_RUN_ALREADY_ASSIGNED`, then `ERR_LOT_NOT_RELEASED`, then `ERR_RECALL_LOT_NOT_RELEASED`, then `ERR_SUBJECT_TYPE_MISMATCH`, then `ERR_UNFINALIZED_WITHDRAWALS`, then `ERR_SUPERSEDE_TARGET_INVALID`.
9. **Capacity, quota, and uniqueness**, evaluated in this fixed sub-order: `ERR_DAILY_CAP_EXCEEDED`, then `ERR_MONTHLY_CAP_EXCEEDED`, then `ERR_PREFORM_INSUFFICIENT`, then `ERR_BOTTLE_CYCLE_LIMIT`, then `ERR_DUPLICATE_REPORT_PERIOD`, then `ERR_EMPTY_RECALL_SCOPE`, then `ERR_BOTTLE_CODE_EXISTS`.
10. **Quantity accounting** — `ERR_RECOVERY_EXCEEDS_SCOPE`, `ERR_RECOVERY_INCOMPLETE`, `ERR_METER_READING_MISMATCH`, and `ERR_OVERPRODUCTION`.
11. **Input shape** — on otherwise-valid requests, required fields must be present, enums in range, quantities positive as specified, `scheduled_end` after `scheduled_start`, `monthly_cap_gallons` no less than `daily_cap_gallons`, `valid_to` after `valid_from`, `accepted_units` greater than zero and no greater than `delivered_units`, and `period_month` between 1 and 12 inclusive; violations yield `ERR_INVALID_REQUEST` (HTTP 400). A malformed JSON body, or one that is not a JSON object, is likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The per-error HTTP status codes are catalogued in §5; where a ladder rung groups several errors, each error carries the status shown there.

### 2.8. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control, each keyed on the parent resource named in the path. No other endpoint accepts a version field.

- Recording a withdrawal event beneath a permit requires `expected_permit_version`, carrying the client's last observed `version` of that permit. If the permit's current `version` has advanced since the client read it — because another event was posted, voided, or superseded in the meantime — the request is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412). The client's remaining-capacity view is derived from the permit version it read, so the cap check must be re-evaluated against a fresh read before the create can proceed.
- Registering a preform delivery beneath a bottling line requires `expected_line_version`, carrying the client's last observed `version` of that line. A mismatch with the line's current `version` is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412), since the receiving clerk's on-hand picture is derived from the line version it read and any delivery creation, QC verdict, lot reservation, completion, or cancellation has since moved the ledger.
- Creating a production lot beneath a bottling line likewise requires `expected_line_version`; a mismatch with the line's current `version` is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412). The reservation check consumes the free-preform balance derived from the line version the client read, so the create must be re-based on a fresh read.

In each case the client learns the parent's current `version` by reading the parent, then retries against the fresh state.

### 2.9. Precision, Rounding, and Comparison Semantics

Gallons, bottle counts, and preform units are integers end to end; no rounding applies anywhere in withdrawal accounting, cap enforcement, or inventory ledgers. Acre-feet figures on community water reports are rounded to exactly 3 decimal places using round-half-up, applied per source before any summation (§3.9) — the per-source-then-sum order is the contract, and converting the summed gallons instead is a different, forbidden calculation. Disinfection and wash parameters (`uv_dose_mj_cm2`, `ozone_ct_mg_min_l`, `turbidity_ntu`, `micro_pore_micron`, `ro_rejection_pct`, `rinse_temp_c`, `sanitizer_ppm`) are compared exactly as recorded, with no rounding before comparison; a parameter sitting exactly at its threshold passes. The plant posture's 90-percent usage test is evaluated in exact integer form: the provisional monthly withdrawal multiplied by 100 is compared against 90 times the monthly cap, so usage exactly at the threshold triggers the elevated posture.

### 2.10. Segregation of Duties

Two hand-offs are segregated. A treatment run may not be validated by the operator who recorded its parameters: validation compares `X-User-ID` against the run's `parameters_recorded_by_user_id` and rejects a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A production lot may not be released by the operator who completed it: release compares `X-User-ID` against the lot's `completed_by_user_id` and rejects a match with the same error. Both checks sit on the safety rung of the validation ladder (§2.7) and therefore fire after existence and state checks but before any treatment, product-test, or sanitation verification.

### 2.11. Dual Accounting: Provisional and Certified Views

Withdrawal accounting keeps two parallel views of every permit, and which view a rule consumes is part of the contract. The **provisional** view counts events in `RECORDED` or `FINALIZED` status; the **certified** view counts `FINALIZED` events only, so identical inputs always yield a certified figure no larger than the provisional one. Each permit exposes both views for the current logical day as `withdrawn_today_provisional_gallons` and `withdrawn_today_certified_gallons`, and for the current logical year-month as `withdrawn_month_provisional_gallons` and `withdrawn_month_certified_gallons`. Events in `VOIDED` status feed neither view. Cap enforcement (§3.1) always uses the provisional view, so a recorded-but-unfinalized posting still counts against the cap; community water reports (§3.9) always use the certified view, so only finalized gallons are published.

The returnable-bottle loop keeps an analogous pair of counters on the plant. `bottle_gross_pool_units` counts the plant's bottles in `SANITIZED`, `FILLED`, or `WITH_CUSTOMER` status — every bottle not currently dirty, in wash, quarantined, or retired — while `bottle_sanitized_pool_units` counts bottles in `SANITIZED` status only, the certified fillable pool. Bottles in `RETURNED_DIRTY`, `IN_WASH`, `QUARANTINED`, or `RETIRED` are excluded from both, and whenever any bottle of the plant is `FILLED` or `WITH_CUSTOMER` the sanitized figure is strictly smaller than the gross figure. Both counters recompute on every bottle status mutation.

## 3. Business Logic & Workflows

### 3.1. Source Permits and Withdrawal Accounting

A `ComplianceOfficer` registers a source water permit beneath a plant, supplying the regulator-issued `permit_number`, a `source_classification` of `SPRING`, `WELL`, or `MUNICIPAL`, the `daily_cap_gallons` and `monthly_cap_gallons` withdrawal limits, and the validity window `valid_from` through `valid_to`. The daily cap must be a positive integer, the monthly cap must be no less than the daily cap, and `valid_to` must fall after `valid_from`; the window itself is inclusive at both ends. A new permit starts in `ACTIVE` status with `suspension_reason` null and all four withdrawal aggregates at zero. Permits of a plant can be listed via the plant-scoped collection, and a cross-plant list accepts `plant_id` and `status` filters; a single permit read returns the four aggregate fields alongside the registered attributes.

Against an `ACTIVE` permit, a `SourceMonitor` records withdrawal events. Each event carries a `withdrawal_date`, a positive integer `gallons`, and the cumulative meter readings `meter_reading_start_gallons` (zero or greater) and `meter_reading_end_gallons`. The meter readings are the independent witness of the claimed volume: the end reading minus the start reading must equal `gallons` exactly, otherwise the posting fails with `ERR_METER_READING_MISMATCH` (HTTP 422). The withdrawal date must fall inside the permit's validity window, else `ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW` (HTTP 409), and must not lie after the current logical date, else `ERR_FUTURE_WITHDRAWAL_DATE` (HTTP 409). Posting against a permit that is not `ACTIVE` — including a superseding correction — is rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 409). The create must also carry `expected_permit_version` per §2.8; because the OCC check runs immediately after existence, a stale posting never reaches the cap comparison. A recorded event starts in `RECORDED` status with `finalized_at` null.

Cap enforcement runs on the provisional view keyed on the new event's own `withdrawal_date`, and it is evaluated daily first, then monthly. The new event's `gallons` must not exceed the daily cap minus the provisional gallons already posted for that calendar date, otherwise `ERR_DAILY_CAP_EXCEEDED` (HTTP 409); it must then not exceed the monthly cap minus the provisional gallons already posted for that year-month, otherwise `ERR_MONTHLY_CAP_EXCEEDED` (HTTP 409). Equality is allowed at both levels: a posting that brings the provisional total exactly to the cap succeeds and leaves zero remaining, and one more gallon beyond that fails.

Corrections come in two forms. Voiding is the compensating action for an event still in `RECORDED` status: the event moves to `VOIDED` and drops out of every aggregate. Voiding a `FINALIZED` event is rejected with `ERR_EVENT_ALREADY_FINALIZED` (HTTP 409) — finalized history must be corrected by supersede instead — and voiding an already `VOIDED` event is rejected with `ERR_INVALID_STATE` (HTTP 409). Supersede is the correction path that replaces history: a new event created with `supersedes_event_id` pointing at an existing event of the same permit voids the referenced event and takes its place as a fresh `RECORDED` event. The supersede target must not itself be `VOIDED` and must belong to the same permit, otherwise `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 409); and when the target is `FINALIZED`, no `PUBLISHED` community report may cover the target's plant and the year-month of its `withdrawal_date`, otherwise `ERR_REPORT_PERIOD_LOCKED` (HTTP 409). The cap check for the replacement excludes the event being superseded, so correcting a posting does not double-count against the window. Whether through create-with-supersede or void, each correction increments the permit's `version` by 1 and refreshes its four withdrawal aggregates; a plain create does the same.

Finalization is the system's job, not the monitor's. During the daily compliance run (§3.2), every `RECORDED` event whose `withdrawal_date` falls strictly before the current logical date moves to `FINALIZED`, its `finalized_at` is stamped with the current logical timestamp, and the permit's aggregates refresh — the certified variants now include the event. The four aggregates are derived at read time rather than stored, so this refresh does not increment the permit's `version`; the permit's `version` advances only where this section says so. A permit's events can be listed beneath the permit, or across permits through a filtered list accepting `permit_id`, `supersedes_event_id`, and `status`.

The permit lifecycle beyond `ACTIVE` is driven partly by officers and partly by the compliance run. A `ComplianceOfficer` may manually suspend an `ACTIVE` permit, which records `suspension_reason` as `MANUAL`; the system may also suspend a permit, recording `SOURCE_TEST_FAIL` when a raw-source test completes with a failing result (§3.4) or `TEST_OVERDUE` when such a test runs more than seven days overdue (§3.2). Any suspension cancels every treatment run still `SCHEDULED` against that permit and recomputes the plant's posture — a suspended permit forces `BREACH`. Reinstatement by a `ComplianceOfficer` requires the permit to be `SUSPENDED`, and two guards apply: no raw-source test for the permit may currently be `OVERDUE`, and the most recent completed raw-source test for the permit — the greatest by `collected_at`, with ties resolved toward the later `created_at` and any further tie toward the later-created test — must be a pass, unless none has ever completed. Either failure yields `ERR_REINSTATE_BLOCKED` (HTTP 409). A successful reinstate returns the permit to `ACTIVE` with `suspension_reason` cleared to null and recomputes posture. When the compliance run observes the current logical date past `valid_to`, a permit in `ACTIVE` or `SUSPENDED` moves to `EXPIRED` and posture is recomputed; an `EXPIRED` permit may then be closed by a `ComplianceOfficer`, reaching the terminal `CLOSED` state. Suspend, reinstate, and close each increment the permit's `version`.

### 3.2. The Daily Compliance Run and Plant Compliance Posture

Once per operating day, a `PlantAdmin` triggers the plant's compliance checkpoint. The run executes seven steps in a pinned order: first, every `RECORDED` withdrawal event dated strictly before the current logical date is finalized; second, lab tests flip from `SCHEDULED` to `DUE` or to `OVERDUE` per the cadence rules of §3.4; third, the run auto-schedules raw-source tests for `ACTIVE` permits that lack an upcoming one; fourth, permits whose raw-source test is overdue by more than seven days are suspended with reason `TEST_OVERDUE`, cascading into run cancellations and posture recomputation exactly as a manual suspension does; fifth, permits past `valid_to` expire; sixth, the plant's compliance posture is recomputed; seventh, the plant's `ops_run_index` and `version` each increment by 1. The run returns a summary object containing `ops_run_index`, `events_finalized`, `tests_flipped`, `tests_auto_created`, `permits_suspended`, `permits_expired`, and the resulting `posture`. The `ops_run_index` is a monotone counter starting at 0 on plant creation, incremented once per compliance run.

The plant's `compliance_posture` is a derived traffic light, recomputed synchronously on every mutation of its inputs — permit statuses, recall statuses, lab-test statuses, and the permits' provisional monthly aggregates. It reads `BREACH` when any of the plant's permits is `SUSPENDED`, when any recall of the plant is open (`INITIATED` or `RECOVERING`), or when any raw-source lab test of the plant is `OVERDUE`. Failing that, it reads `WATCH` when any lab test of the plant is `OVERDUE`, or when any `ACTIVE` permit's `withdrawn_month_provisional_gallons` has reached at least 90 percent of its `monthly_cap_gallons` — usage exactly at 90 percent triggers `WATCH`, and the comparison is the exact integer test of §2.9. Otherwise the plant is `GREEN`. A `PlantAdmin` creates a plant by supplying its `name`; a newly created plant starts at `GREEN` with `ops_run_index` 0 and both bottle pool counters at 0, and a plant read exposes `compliance_posture`, `bottle_gross_pool_units`, and `bottle_sanitized_pool_units` alongside its `name`.

### 3.3. Treatment Runs and Disinfection Validation

Before water reaches a line, it passes through a treatment run. A `ProductionLead` schedules a run beneath a plant by supplying the `source_permit_id` of the feeding source plus a `scheduled_start` and `scheduled_end` window; the end must fall after the start, and no overlap rule applies between runs — multiple treatment trains may operate concurrently. A new run is `SCHEDULED` with `validation_round` 0, `parameters_recorded_by_user_id` null, and `validated_by_user_id` null. Runs can be listed across the plant with `plant_id`, `source_permit_id`, and `status` filters.

Starting a run — performed by a `ProductionLead` — is admitted from `SCHEDULED` and again from `REPROCESSING`, and in both cases the run's source permit must be `ACTIVE`, otherwise `ERR_PERMIT_NOT_ACTIVE`; the run moves to `IN_PROGRESS`. While `IN_PROGRESS`, a `ProductionLead` or `QAOfficer` records the disinfection parameters: `uv_dose_mj_cm2`, `ozone_ct_mg_min_l`, `turbidity_ntu`, and `micro_pore_micron` are always recorded, while `ro_rejection_pct` is optional — it is the governing parameter only for non-spring sources. Recording parameters stamps the operator's `X-User-ID` into `parameters_recorded_by_user_id` and increments the run's `version`; parameters may only be recorded while the run is `IN_PROGRESS`, and any other state yields `ERR_INVALID_STATE`.

Validation belongs to a `QAOfficer` and enforces segregation of duties against `parameters_recorded_by_user_id` (§2.10). The verdict evaluation is fixed in order, and the first failing check decides the outcome. Turbidity is examined first: a `turbidity_ntu` strictly above 0.3 fails, so exactly 0.3 passes. Next, a `uv_dose_mj_cm2` strictly below 40.0 fails, so exactly 40.0 passes. Next, an `ozone_ct_mg_min_l` strictly below 1.6 fails. Finally the evaluation branches on the source permit's `source_classification`: for a `SPRING` source, a `micro_pore_micron` strictly above 0.2 fails, so the microfiltration step governs spring water; for any other classification, an `ro_rejection_pct` that is absent or strictly below 95.0 fails, so reverse-osmosis rejection governs purified water. A run surviving all applicable checks passes. A passing verdict moves the run to `VALIDATED`; a failing verdict moves it to `FAILED`. Either way, `validation_round` increments by 1 on every validation call and the officer's `X-User-ID` is stamped into `validated_by_user_id`. A run whose parameters were never recorded fails validation (absent parameters fail), and the segregation check does not bind while `parameters_recorded_by_user_id` is null. `VALIDATED` is terminal; a `FAILED` run is not — a `ProductionLead` may move it to `REPROCESSING` and start it again, or cancel it. Cancellation by a `ProductionLead` is admitted from `SCHEDULED` and from `FAILED`, moving the run to the terminal `CANCELLED` state. Independently, when the run's source permit is suspended, every still-`SCHEDULED` run on that permit is cancelled by the cascade of §3.1. Each start, parameter recording, validation, reprocess, and cancel increments the run's `version`.

### 3.4. Laboratory Testing Cadence and Results

Lab tests track three sampling programs through a single `test_type` of `SOURCE_RAW`, `FINISHED_PRODUCT`, or `BOTTLE_SANITATION`. When a `QAOfficer` schedules a test manually, exactly one subject foreign key must be supplied, and it must match the type: `subject_permit_id` for `SOURCE_RAW`, `subject_lot_id` for `FINISHED_PRODUCT`, or `subject_wash_batch_id` for `BOTTLE_SANITATION`. A missing subject, an extra subject, or a subject of the wrong kind is rejected with `ERR_SUBJECT_TYPE_MISMATCH` (HTTP 409); a subject identifier that does not exist fails earlier with `ERR_NOT_FOUND`. Each supplied subject must belong to the plant named in the path, otherwise `ERR_CROSS_PLANT_REFERENCE` (HTTP 409) — a check that fires after existence and before the subject/type match. The `due_date` is an optional override; when omitted it defaults relative to the current logical date — seven days out for `SOURCE_RAW` (weekly source monitoring), two days out for `FINISHED_PRODUCT` (per-lot release testing), and one day out for `BOTTLE_SANITATION` (per-batch sanitation micro). A manually scheduled test starts `SCHEDULED` with `result` `PENDING`, `origin` `MANUAL`, and `collected_at` null. Tests created by the system — the auto-creations of §3.2, §3.6, and §3.8 — carry `origin` `AUTO`. The cross-plant list accepts `plant_id`, `subject_permit_id`, `subject_lot_id`, `subject_wash_batch_id`, `test_type`, and `status` filters.

Compliance runs move a `SCHEDULED` test to `DUE` when its `due_date` is no earlier than the current logical date and no more than three days away — a test exactly three days out flips, as does one due today — and move a `SCHEDULED` or `DUE` test to `OVERDUE` once the current logical date passes its `due_date`. Each flip recomputes the plant's posture. Two escalations ride on top of overdue detection: when a `SOURCE_RAW` test remains overdue by more than seven days — the current logical date more than seven days past its `due_date` — the subject permit is suspended with `suspension_reason` `TEST_OVERDUE`, cascading through run cancellation and posture recomputation as in §3.1; and the auto-scheduler keeps exactly one upcoming raw-source test per `ACTIVE` permit, creating one with `origin` `AUTO` and a `due_date` seven days out whenever no `SOURCE_RAW` test for that permit exists in `SCHEDULED` or `DUE` status with a `due_date` on or after the current date.

Recording a result is a `QAOfficer` action admitted from `SCHEDULED`, `DUE`, or `OVERDUE`; from any other state it fails with `ERR_INVALID_STATE`. The payload carries `result` and `collected_at`; a `PASS` result moves the test to the terminal `COMPLETED_PASS` state and a `FAIL` result to the terminal `COMPLETED_FAIL` state, with `collected_at` stamped from the payload and the test's `version` incremented. A failing `SOURCE_RAW` result suspends the subject permit with `suspension_reason` `SOURCE_TEST_FAIL`, cascading exactly as a manual suspension would — though if the subject permit is no longer `ACTIVE` when the failing result lands, its status and `suspension_reason` are left unchanged and no cascade fires; every result recording recomputes the plant's posture.

### 3.5. Preform Deliveries and the Line Inventory Ledger

A `PlantAdmin` creates a bottling line beneath a plant with a `line_code` (such as LINE-1) and a positive `daily_capacity_units`; the line's preform ledger starts empty, with `preform_on_hand_units` and `preform_reserved_units` both 0. Lines can be listed across plants with a `plant_id` filter, and a line read exposes the full ledger, including the derived `preform_free_units` and `preform_reorder_quantity`.

Inbound preforms arrive as deliveries registered by a `ProductionLead` with a `supplier` name and a positive `delivered_units` count; the create is OCC-guarded by `expected_line_version` per §2.8, increments the line's `version`, and lands in `PENDING_QC` with `accepted_units` null. A `QAOfficer` then renders the outcome through the verdict call's `verdict` field. An `ACCEPTED` verdict requires `accepted_units` present, greater than zero, and no greater than `delivered_units` — anything else fails input-shape validation with `ERR_INVALID_REQUEST` — and books the accepted quantity into the line's `preform_on_hand_units`. A `REJECTED` verdict sets `accepted_units` to 0 and leaves the line's inventory untouched. Either verdict moves the delivery out of `PENDING_QC` to its terminal state, increments the line's `version`, and any verdict attempted on a delivery no longer `PENDING_QC` fails with `ERR_INVALID_STATE`. Deliveries are listed beneath their line, or across lines with `line_id` and `status` filters.

The line ledger's evaluation order is pinned to break the apparent circle between reservations and reordering. `preform_reserved_units` is a stored field mutated only by lot creation, lot cancellation, and lot completion (§3.6); the derived figures never feed back into it. `preform_free_units` is the on-hand balance minus the reserved balance. `preform_reorder_quantity` is advisory only, computed on read: take the line's target stock of two days of production — `daily_capacity_units` multiplied by 2 — add the current `preform_reserved_units`, subtract the current `preform_on_hand_units`, subtract the inbound pipeline (the sum of `delivered_units` over the line's deliveries still in `PENDING_QC`), and floor the result at zero. Lot creation validates against the free balance as stored before any reorder is placed; the reorder projection never inflates it.

### 3.6. Production Lots: Reservation, Production, and Release

A `ProductionLead` creates a lot beneath a bottling line with a payload carrying the reserved `treatment_run_id`, the `label_classification` of `SPRING` or `PURIFIED`, a positive `planned_units`, the line window `scheduled_start` through `scheduled_end`, and `expected_line_version` per §2.8. Creation performs several checks. The referenced run must exist and must belong to the same plant as the line, otherwise `ERR_CROSS_PLANT_REFERENCE` (HTTP 409). The run must not already be referenced by another lot that is not `CANCELLED` — treatment runs are assigned one-to-one among live lots — otherwise `ERR_RUN_ALREADY_ASSIGNED` (HTTP 409). Label eligibility constrains the claim against the source: a `SPRING` label requires the run's source permit to be classified `SPRING`, and a `PURIFIED` label requires that source not to be `SPRING`; a mismatch fails with `ERR_LABEL_CLASSIFICATION_MISMATCH` (HTTP 409). The release gate later re-verifies the purified claim implicitly, since a purified lot's run can only have validated through the reverse-osmosis branch of §3.3. The lot's window is a half-open interval — two lots on one line whose windows merely touch, one ending exactly when the other begins, do not conflict — and any overlap with another lot not in `CANCELLED` status on the same line fails with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409). Finally, `planned_units` must not exceed the line's `preform_free_units`, otherwise `ERR_PREFORM_INSUFFICIENT` (HTTP 409). A created lot lands in `PLANNED` with `rework_count` 0, `produced_units` null, `recall_id` null, `completed_by_user_id` null, and `released_by_user_id` null; the reservation books `planned_units` into the line's `preform_reserved_units` and increments the line's `version`. Lots can be listed with `line_id`, `treatment_run_id`, `recall_id`, and `status` filters.

Starting production moves a `PLANNED` lot to `IN_PRODUCTION` and is refused while the plant's `compliance_posture` is `BREACH` — `ERR_POSTURE_BREACH` (HTTP 409) — so a plant under suspension, open recall, or overdue source testing cannot put new water into bottles. Completing production, also a `ProductionLead` action, moves an `IN_PRODUCTION` lot to `QA_HOLD` and records the actual output as `produced_units`. Overproduction is impossible to book: a count strictly above `planned_units` fails with `ERR_OVERPRODUCTION` (HTTP 422), and a count of zero or less fails with `ERR_INVALID_REQUEST`. Completion stamps the operator into `completed_by_user_id`, consumes the preforms by subtracting `produced_units` from the line's `preform_on_hand_units`, releases the reservation by subtracting `planned_units` from `preform_reserved_units`, increments the line's `version`, and auto-creates the lot's finished-product lab test — a `FINISHED_PRODUCT` test with `subject_lot_id` pointing at this lot, due two days out, `origin` `AUTO`.

Release from `QA_HOLD` may be performed by a `QAOfficer` or a `ProductionLead`, but never by the operator who completed the lot (§2.10). Three further gates apply, in the ladder's order: the lot's treatment run must be `VALIDATED`, otherwise `ERR_TREATMENT_NOT_VALIDATED` (HTTP 409), and a `FINISHED_PRODUCT` test for the lot must exist in `COMPLETED_PASS`, otherwise `ERR_PRODUCT_TEST_NOT_PASSED` (HTTP 409). A successful release stamps `released_by_user_id` and moves the lot to `RELEASED`. Alternatively, a `QAOfficer` may reject the lot from `QA_HOLD` into `REWORK`, incrementing `rework_count` by 1; a `ProductionLead` then returns a `REWORK` lot to `QA_HOLD` for a fresh review, where the release gates apply again against any passed finished-product test on the lot. Cancellation by a `ProductionLead` is admitted only from `PLANNED`: it releases the reservation by subtracting `planned_units` from the line's `preform_reserved_units`, increments the line's `version`, and moves the lot to the terminal `CANCELLED` state. The terminal states of a lot are `RECALLED` and `CANCELLED`; recall arrival (§3.7) moves a `RELEASED` lot to `RECALLED` and sets its `recall_id`.

### 3.7. Recalls and Recovery

When a released lot must come back, a `ComplianceOfficer` initiates a recall beneath the plant with a free-text `reason` and the `lot_ids` in scope. An empty scope is rejected with `ERR_EMPTY_RECALL_SCOPE` (HTTP 422); every listed lot must exist and must currently be `RELEASED`, otherwise `ERR_RECALL_LOT_NOT_RELEASED` (HTTP 409). Every listed lot must also belong to the plant named in the path — a cross-plant lot fails with `ERR_CROSS_PLANT_REFERENCE` (HTTP 409), checked before the `RELEASED`-state requirement. Initiation moves each scoped lot to `RECALLED` with `recall_id` set, quarantines every bottle in `FILLED` or `WITH_CUSTOMER` status whose `last_filled_lot_id` is in scope (moving each to `QUARANTINED` and dropping it from the plant's gross pool), freezes `units_in_scope` to the sum of the scoped lots' `produced_units` at that instant, and starts the recall in `INITIATED` with `units_recovered` 0. Because an open recall forces `BREACH`, initiation also recomputes the plant's posture. Recalls are listed beneath the plant or across plants with `plant_id` and `status` filters.

Recovery postings by a `ComplianceOfficer` carry a positive `recovered_units` count, which is added to `units_recovered`; a posting that would push `units_recovered` past `units_in_scope` fails with `ERR_RECOVERY_EXCEEDS_SCOPE` (HTTP 422). The first successful posting moves the recall from `INITIATED` to `RECOVERING`. Closing is admitted only from `RECOVERING` and only once `units_recovered` has reached at least `units_in_scope`; closing short of full recovery fails with `ERR_RECOVERY_INCOMPLETE` (HTTP 409). Closure moves the recall to the terminal `CLOSED` state, releases every `QUARANTINED` bottle whose `last_filled_lot_id` belongs to the recall's scope back to `RETURNED_DIRTY` — each such bottle must rewash before any refill, and its `last_wash_batch_id` is left unchanged so the previous sanitation test still governs the next fill after that rewash — and recomputes the plant's posture, which may lift the `BREACH` once no open recall remains. Recovery postings and closure each increment the recall's `version`.

### 3.8. The Returnable Bottle Loop and Wash-Batch Sanitation

The plant's five-gallon returnable bottles circulate through customers and back through the wash. A `SanitationLead` registers a bottle beneath the plant with an etched `bottle_code`, unique among the plant's bottles that are not `RETIRED`; reusing a live code fails with `ERR_BOTTLE_CODE_EXISTS` (HTTP 409). New stock is certified clean: a registered bottle starts in `SANITIZED` with `wash_cycle_count` 0, `last_wash_batch_id` null, `current_wash_batch_id` null, and `last_filled_lot_id` null. Bottles can be listed with `plant_id`, `current_wash_batch_id`, `last_wash_batch_id`, `last_filled_lot_id`, and `status` filters.

Filling is a `ProductionLead` action on a `SANITIZED` bottle, with the payload's `lot_id` naming the source lot. The sanitation gate comes first among the business checks: if the bottle has been washed before, the `BOTTLE_SANITATION` lab test covering the batch named by `last_wash_batch_id` must be `COMPLETED_PASS`, otherwise `ERR_SANITATION_TEST_PENDING` (HTTP 409); never-washed new stock, with a null `last_wash_batch_id`, passes this gate on its first fill. The lot must exist, must belong to the same plant as the bottle — traced through the lot's line — otherwise `ERR_CROSS_PLANT_REFERENCE`, and must be `RELEASED`, otherwise `ERR_LOT_NOT_RELEASED` (HTTP 409). A successful fill moves the bottle to `FILLED`, stamps `last_filled_lot_id`, and recomputes the plant's pools: the gross pool is unchanged since a `SANITIZED` bottle and a `FILLED` bottle both count, while the sanitized pool decrements. Delivery by a `SanitationLead` moves a `FILLED` bottle to `WITH_CUSTOMER`; taking it back moves it to `RETURNED_DIRTY`, decrementing the gross pool. Retirement by a `SanitationLead` is admitted from `RETURNED_DIRTY`, `SANITIZED`, or `QUARANTINED` and moves the bottle to the terminal `RETIRED` state, recomputing the pools. Fill, deliver, return, and retire each increment the bottle's `version`.

Washing is organized into batches scheduled by a `SanitationLead` on a `washer_unit` of `WASHER_A` or `WASHER_B`, with a `scheduled_start` and `scheduled_end` window whose end must follow its start. Two batches on the same washer may not overlap — any window intersection with another batch not in `CANCELLED` status on that washer fails with `ERR_WASHER_WINDOW_CONFLICT` (HTTP 409) — and a mandatory 30-minute purge separates consecutive batches on one washer: starting less than 30 minutes after the previous batch's end, or ending less than 30 minutes before the next batch's start, fails with `ERR_WASHER_PURGE_BUFFER` (HTTP 409). A new batch is `SCHEDULED`; its `bottle_count`, the number of bottles whose `current_wash_batch_id` names it, starts at 0. Batches are listed beneath the plant or across plants with `plant_id`, `washer_unit`, and `status` filters.

A `SanitationLead` assigns bottles to a `SCHEDULED` batch by listing their identifiers in `bottle_ids`. The batch must still be `SCHEDULED`, each bottle must be `RETURNED_DIRTY` — either violation yields `ERR_INVALID_STATE` — each bottle must belong to the same plant as the batch, otherwise `ERR_CROSS_PLANT_REFERENCE`, and each bottle's `wash_cycle_count` must still be below the 150-wash lifecycle ceiling, otherwise `ERR_BOTTLE_CYCLE_LIMIT` (HTTP 409) and the bottle must be retired instead. Assignment moves each listed bottle to `IN_WASH` with `current_wash_batch_id` set to the batch, and the batch's `bottle_count` recomputes. `bottle_count` is derived at read time from the bottles' `current_wash_batch_id` pointers, so assignment mutates the bottles only and does not increment the batch's `version`. Starting a batch requires it to be `SCHEDULED` and requires that no other batch on the same `washer_unit` is currently `RUNNING` — at most one running batch per washer, and a violation yields `ERR_INVALID_STATE` (HTTP 409) — and moves it to `RUNNING`.

Completion by a `SanitationLead` records `rinse_temp_c` and `sanitizer_ppm` and judges the wash: the batch passes when the rinse temperature is at least 71.1 degrees Celsius and the sanitizer concentration is at least 50.0 parts per million, with parameters compared exactly as recorded and values at the thresholds passing; anything else fails. A passing batch moves to `PASSED` and sanitizes its load — every assigned bottle moves from `IN_WASH` back to `SANITIZED`, its `wash_cycle_count` increments by 1, its `last_wash_batch_id` is set to this batch, its `current_wash_batch_id` clears, and both plant pools increment — then the system auto-creates the batch's `BOTTLE_SANITATION` lab test, due one day out with `origin` `AUTO`. A failing batch moves to `FAILED`, returns every assigned bottle to `RETURNED_DIRTY` without incrementing any cycle count, and spawns no sanitation test. Cancelling a `SCHEDULED` batch moves it to `CANCELLED` and compensates any already-assigned bottles back to `RETURNED_DIRTY` with `current_wash_batch_id` cleared. Start, completion, and cancellation each increment the batch's `version`.

Two recall-driven transitions cross-cut the loop (§3.7): recall initiation moves in-scope `FILLED` and `WITH_CUSTOMER` bottles to `QUARANTINED`, decrementing the gross pool; recall closure moves the scope's `QUARANTINED` bottles to `RETURNED_DIRTY` for mandatory rewashing.

### 3.9. Community Water Reports

Once a month the plant owes its community a water-use accounting. A `ComplianceOfficer` drafts a report beneath the plant by supplying `period_year` and `period_month` (1 through 12). Only one report that is not `SUPERSEDED` may exist per plant and period; a duplicate fails with `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409). The draft lands in `DRAFT` with `published_at` null and `addendum_of_report_id` null, and its totals are computed immediately from the certified view: only `FINALIZED` withdrawal events whose `withdrawal_date` falls inside the period count, grouped across the plant's permits. Reports can be listed with `plant_id`, `addendum_of_report_id`, and `status` filters.

The volume conversion's rounding order is pinned. Permits are processed in ascending order of their `created_at`. For each permit, the period's finalized gallons are summed exactly, then converted to acre-feet by dividing by 325,851 gallons per acre-foot and rounding half-up to 3 decimal places. The report's `total_withdrawn_gallons` is the exact integer sum of the per-source gallons; its `total_acre_feet` is the sum of the already-rounded per-source acre-feet figures, itself rounded half-up to 3 decimal places; and `per_source_breakdown` is the ordered array of per-permit entries, each carrying its `permit_id`, `gallons`, and `acre_feet`. Summing all gallons first and converting once is a different calculation and is forbidden — the per-source-then-sum order above is the contract.

Publication by a `ComplianceOfficer` requires the report to be `DRAFT` and requires that no `RECORDED` — unfinalized — withdrawal event exist for any of the plant's permits with a `withdrawal_date` inside the period, otherwise `ERR_UNFINALIZED_WITHDRAWALS` (HTTP 409); the practical sequence is to run the daily compliance checkpoint past the period's end first. Publication stamps `published_at` with the current logical timestamp, recomputes `total_withdrawn_gallons`, `total_acre_feet`, and `per_source_breakdown` from the finalized events as of publish time, moves the report to `PUBLISHED`, increments its `version`, and engages the period's publication lock: while a `PUBLISHED` report covers a plant and year-month, superseding a finalized event of that period is refused with `ERR_REPORT_PERIOD_LOCKED` (§3.1).

Corrections after publication go through supersession. Superseding a `PUBLISHED` report — a `ComplianceOfficer` action — moves it to the terminal `SUPERSEDED` state, creates a successor report in `DRAFT` covering the same period with `addendum_of_report_id` pointing back at the superseded report and totals recomputed from the current finalized events, returns the successor with HTTP 200 (supersession transitions the existing report rather than performing a plain create), and releases the period's publication lock so finalized events in the period become supersedable again until the successor publishes. Supersession increments the superseded report's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, act upon, or transition an existing resource return `200 OK`, including the test-driving capabilities. All request and response bodies conform to §2.2, list endpoints paginate per §2.3, and authorization follows §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock | PlantAdmin |
| POST | `/api/_inject/bottle-wash-cycles` | Set a bottle's wash cycle count directly (test-driving) | PlantAdmin |
| POST | `/api/plants` | Create a plant | PlantAdmin |
| GET | `/api/plants/{id}` | Read a plant including posture and bottle pool counters | All roles |
| POST | `/api/plants/{plantId}/compliance-runs` | Run the daily compliance checkpoint | PlantAdmin |
| POST | `/api/plants/{plantId}/permits` | Register a source water permit | ComplianceOfficer |
| GET | `/api/plants/{plantId}/permits` | List permits of a plant | All roles |
| GET | `/api/permits/{id}` | Read a permit including the four withdrawal aggregates | All roles |
| POST | `/api/permits/{id}/suspend` | Manually suspend an active permit | ComplianceOfficer |
| POST | `/api/permits/{id}/reinstate` | Reinstate a suspended permit | ComplianceOfficer |
| POST | `/api/permits/{id}/close` | Close an expired permit | ComplianceOfficer |
| POST | `/api/permits/{permitId}/withdrawal-events` | Record a withdrawal event (optionally superseding another) | SourceMonitor |
| GET | `/api/permits/{permitId}/withdrawal-events` | List withdrawal events of a permit | All roles |
| GET | `/api/withdrawal-events/{id}` | Read a withdrawal event | All roles |
| GET | `/api/withdrawal-events` | List/filter withdrawal events across permits | All roles |
| POST | `/api/withdrawal-events/{id}/void` | Void a recorded withdrawal event | SourceMonitor |
| POST | `/api/plants/{plantId}/treatment-runs` | Schedule a treatment run | ProductionLead |
| GET | `/api/treatment-runs/{id}` | Read a treatment run | All roles |
| GET | `/api/treatment-runs` | List/filter treatment runs | All roles |
| POST | `/api/treatment-runs/{id}/start` | Start a scheduled or reprocessing run | ProductionLead |
| POST | `/api/treatment-runs/{id}/record-parameters` | Record disinfection parameters on an in-progress run | ProductionLead, QAOfficer |
| POST | `/api/treatment-runs/{id}/validate` | Validate a run (pass moves to validated, fail to failed) | QAOfficer |
| POST | `/api/treatment-runs/{id}/reprocess` | Move a failed run to reprocessing | ProductionLead |
| POST | `/api/treatment-runs/{id}/cancel` | Cancel a scheduled or failed run | ProductionLead |
| POST | `/api/plants/{plantId}/lab-tests` | Schedule a lab test | QAOfficer |
| GET | `/api/lab-tests/{id}` | Read a lab test | All roles |
| GET | `/api/lab-tests` | List/filter lab tests | All roles |
| POST | `/api/lab-tests/{id}/record-result` | Record a pass/fail result with collection timestamp | QAOfficer |
| POST | `/api/plants/{plantId}/bottling-lines` | Create a bottling line | PlantAdmin |
| GET | `/api/bottling-lines/{id}` | Read a bottling line including the preform ledger | All roles |
| GET | `/api/bottling-lines/{lineId}/preform-deliveries` | List preform deliveries of a line | All roles |
| POST | `/api/bottling-lines/{lineId}/preform-deliveries` | Register an inbound preform delivery | ProductionLead |
| GET | `/api/preform-deliveries/{id}` | Read a preform delivery | All roles |
| POST | `/api/preform-deliveries/{id}/qc-verdict` | Render the QC verdict on a pending delivery | QAOfficer |
| POST | `/api/bottling-lines/{lineId}/production-lots` | Create a planned production lot | ProductionLead |
| GET | `/api/production-lots/{id}` | Read a production lot | All roles |
| GET | `/api/production-lots` | List/filter production lots | All roles |
| POST | `/api/production-lots/{id}/start` | Start production of a planned lot | ProductionLead |
| POST | `/api/production-lots/{id}/complete` | Complete production and move the lot to QA hold | ProductionLead |
| POST | `/api/production-lots/{id}/release` | Release a lot from QA hold | QAOfficer, ProductionLead |
| POST | `/api/production-lots/{id}/reject` | Reject a lot from QA hold into rework | QAOfficer |
| POST | `/api/production-lots/{id}/rework-complete` | Return a rework lot to QA hold | ProductionLead |
| POST | `/api/production-lots/{id}/cancel` | Cancel a planned lot | ProductionLead |
| POST | `/api/plants/{plantId}/recalls` | Initiate a recall over released lots | ComplianceOfficer |
| GET | `/api/recalls/{id}` | Read a recall | All roles |
| GET | `/api/plants/{plantId}/recalls` | List recalls of a plant | All roles |
| POST | `/api/recalls/{id}/recoveries` | Post recovered units against a recall | ComplianceOfficer |
| POST | `/api/recalls/{id}/close` | Close a fully recovered recall | ComplianceOfficer |
| POST | `/api/plants/{plantId}/wash-batches` | Schedule a wash batch on a washer unit | SanitationLead |
| GET | `/api/wash-batches/{id}` | Read a wash batch | All roles |
| GET | `/api/plants/{plantId}/wash-batches` | List wash batches of a plant | All roles |
| POST | `/api/wash-batches/{id}/assign-bottles` | Assign dirty bottles to a scheduled batch | SanitationLead |
| POST | `/api/wash-batches/{id}/start` | Start a scheduled batch | SanitationLead |
| POST | `/api/wash-batches/{id}/complete` | Complete a running batch with rinse/sanitizer readings | SanitationLead |
| POST | `/api/wash-batches/{id}/cancel` | Cancel a scheduled batch | SanitationLead |
| POST | `/api/plants/{plantId}/bottles` | Register a new returnable bottle | SanitationLead |
| GET | `/api/bottles/{id}` | Read a bottle | All roles |
| GET | `/api/bottles` | List/filter bottles | All roles |
| POST | `/api/bottles/{id}/fill` | Fill a sanitized bottle from a released lot | ProductionLead |
| POST | `/api/bottles/{id}/deliver` | Deliver a filled bottle to a customer | SanitationLead |
| POST | `/api/bottles/{id}/return` | Take a bottle back into the dirty returns pool | SanitationLead |
| POST | `/api/bottles/{id}/retire` | Retire a bottle | SanitationLead |
| POST | `/api/plants/{plantId}/community-reports` | Create a draft community water-use report | ComplianceOfficer |
| GET | `/api/community-reports/{id}` | Read a community water report | All roles |
| GET | `/api/community-reports` | List/filter community water reports | All roles |
| POST | `/api/community-reports/{id}/publish` | Publish a draft report | ComplianceOfficer |
| POST | `/api/community-reports/{id}/supersede` | Supersede a published report, creating a successor draft | ComplianceOfficer |
| GET | `/api/permits` | List/filter permits across plants | All roles |
| GET | `/api/bottling-lines` | List/filter bottling lines across plants | All roles |
| GET | `/api/preform-deliveries` | List/filter preform deliveries across lines | All roles |
| GET | `/api/recalls` | List/filter recalls across plants | All roles |
| GET | `/api/wash-batches` | List/filter wash batches across plants and washer units | All roles |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3 where the corresponding rule lives.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_EVENT_ALREADY_FINALIZED` | 409 |
| `ERR_STALE_PERMIT_VERSION` | 412 |
| `ERR_STALE_LINE_VERSION` | 412 |
| `ERR_DAILY_CAP_EXCEEDED` | 409 |
| `ERR_MONTHLY_CAP_EXCEEDED` | 409 |
| `ERR_WITHDRAWAL_DATE_OUT_OF_WINDOW` | 409 |
| `ERR_FUTURE_WITHDRAWAL_DATE` | 409 |
| `ERR_METER_READING_MISMATCH` | 422 |
| `ERR_SUPERSEDE_TARGET_INVALID` | 409 |
| `ERR_REPORT_PERIOD_LOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_TREATMENT_NOT_VALIDATED` | 409 |
| `ERR_PRODUCT_TEST_NOT_PASSED` | 409 |
| `ERR_SANITATION_TEST_PENDING` | 409 |
| `ERR_LABEL_CLASSIFICATION_MISMATCH` | 409 |
| `ERR_POSTURE_BREACH` | 409 |
| `ERR_REINSTATE_BLOCKED` | 409 |
| `ERR_LINE_WINDOW_CONFLICT` | 409 |
| `ERR_WASHER_WINDOW_CONFLICT` | 409 |
| `ERR_WASHER_PURGE_BUFFER` | 409 |
| `ERR_PREFORM_INSUFFICIENT` | 409 |
| `ERR_OVERPRODUCTION` | 422 |
| `ERR_CROSS_PLANT_REFERENCE` | 409 |
| `ERR_RUN_ALREADY_ASSIGNED` | 409 |
| `ERR_LOT_NOT_RELEASED` | 409 |
| `ERR_RECALL_LOT_NOT_RELEASED` | 409 |
| `ERR_SUBJECT_TYPE_MISMATCH` | 409 |
| `ERR_UNFINALIZED_WITHDRAWALS` | 409 |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 |
| `ERR_EMPTY_RECALL_SCOPE` | 422 |
| `ERR_RECOVERY_EXCEEDS_SCOPE` | 422 |
| `ERR_RECOVERY_INCOMPLETE` | 409 |
| `ERR_BOTTLE_CYCLE_LIMIT` | 409 |
| `ERR_BOTTLE_CODE_EXISTS` | 409 |
